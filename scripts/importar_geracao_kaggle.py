"""Baixa as respostas do kernel do Kaggle, valida e aplica o guardrail de saída.

Saídas:
  output/kaggle/geracao/resultados/            saída bruta do kernel (fora do Git)
  output/kaggle/geracao/respostas_revisadas.jsonl  pergunta, ação, fontes, resposta final e alertas (fora do Git)
  reports/integracao/geracao/revisao_saida.csv     uma linha por pergunta, só identificadores e métricas (no Git)
Uso: python scripts/importar_geracao_kaggle.py [--sem-download] [--fallback] [--local]
  --fallback  lê também a segunda passada (LLM B, scripts/preparar_fallback_kaggle.py) e escolhe a resposta final:
              A se servir, senão B se servir, senão a resposta segura (geracao.escolher_resposta).
"""
from pathlib import Path
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd

from src.integracao import guardrails as g
from src.integracao.geracao import (validar_resposta, revisar, escolher_resposta, pedido_fallback, MODELO_FALLBACK,
                                    RESPOSTA_SEGURA)

KERNEL = 'laisapaiva93/lexia-geracao-qwen3'
KERNEL_FALLBACK = 'laisapaiva93/lexia-fallback-llama31'
BASE = ROOT / 'output/kaggle/geracao'
RELATORIOS = ROOT / 'reports/integracao/geracao'


def main():
    local = '--local' in sys.argv   # plano B: geração no Ollama local (scripts/gerar_respostas_local.py)
    resultados = BASE / ('resultados_local' if local else 'resultados')
    resultados.mkdir(parents=True, exist_ok=True)
    if '--sem-download' not in sys.argv and not local:
        subprocess.run(['kaggle', 'kernels', 'output', KERNEL, '-p', str(resultados), '-o'], check=True)
    arquivo_pedidos = BASE / ('dataset_local' if local else 'dataset') / 'pedidos.jsonl'
    pedidos = [json.loads(l) for l in arquivo_pedidos.read_text(encoding='utf-8').splitlines() if l.strip()]
    respostas = {}
    for l in (resultados / 'respostas.jsonl').read_text(encoding='utf-8').splitlines():
        if l.strip():
            r = json.loads(l)
            respostas[r['pergunta_id']] = r
    # Segunda passada (LLM B, fallback): output/kaggle/fallback/resultados/respostas.jsonl, se existir.
    respostas_b = {}
    arquivo_b = ROOT / 'output/kaggle/fallback/resultados/respostas.jsonl'
    if '--fallback' in sys.argv:
        if '--sem-download' not in sys.argv:
            subprocess.run(['kaggle', 'kernels', 'output', KERNEL_FALLBACK, '-p', str(arquivo_b.parent), '-o'], check=True)
        for l in arquivo_b.read_text(encoding='utf-8').splitlines():
            if l.strip():
                r = json.loads(l)
                respostas_b[r['pergunta_id']] = r
    linhas, revisadas = [], []
    for p in pedidos:
        modelo, motivo_a, motivo_b, resposta_b = None, None, None, None
        if p['precisa_llm']:
            r = respostas.get(p['pergunta_id'])
            problemas = ['sem resposta do kernel'] if r is None else validar_resposta(p, r)
            segundos, tokens = (r or {}).get('segundos'), (r or {}).get('tokens_saida')
            # Resposta final com fallback: A se servir, senão B se servir, senão a resposta segura.
            escolha = escolher_resposta(p, r, respostas_b.get(p['pergunta_id']))
            texto, modelo, motivo_a, motivo_b = escolha['texto'], escolha['modelo'], escolha['motivo_a'], escolha['motivo_b']
            resposta_b = (respostas_b.get(p['pergunta_id']) or {}).get('resposta')
        else:
            problemas, texto, segundos, tokens = [], p['resposta_fixa'], 0, None
        saida = revisar(p, texto) if texto else g.ResultadoSaida(False, [dict(codigo='sem_resposta', detalhe='')], '')
        codigos = sorted({a['codigo'] for a in saida.alertas})
        linhas.append(dict(pergunta_id=p['pergunta_id'], origem=p['origem'], acao=p['acao'], precisa_llm=p['precisa_llm'],
                           fontes=len(p['fontes']), valida=not problemas, problemas='; '.join(problemas),
                           modelo_final=modelo, motivo_fallback=motivo_a, motivo_b=motivo_b,
                           resposta_segura=texto == RESPOSTA_SEGURA,
                           aprovada=saida.aprovada and (not problemas or modelo == MODELO_FALLBACK),
                           bloqueantes=', '.join(c for c in codigos if c in g.BLOQUEANTES),
                           alertas=', '.join(c for c in codigos if c not in g.BLOQUEANTES),
                           segundos_geracao=segundos, tokens_saida=tokens, segundos_recuperacao=p.get('segundos_recuperacao')))
        revisadas.append(dict(pergunta_id=p['pergunta_id'], origem=p['origem'], acao=p['acao'],
                              pergunta_sanitizada=p['pergunta_sanitizada'], fontes=p['fontes'], resposta_modelo=texto,
                              modelo_final=modelo, motivo_fallback=motivo_a, resposta_llm_b=resposta_b,
                              resposta_final=saida.resposta_final, alertas=saida.alertas, aprovada=linhas[-1]['aprovada'],
                              problemas=problemas))
    with (BASE / 'respostas_revisadas.jsonl').open('w', encoding='utf-8', newline='\n') as f:
        for r in revisadas:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    RELATORIOS.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(linhas)
    df.to_csv(RELATORIOS / 'revisao_saida.csv', index=False, encoding='utf-8')
    resumo = json.loads((resultados / 'resumo.json').read_text(encoding='utf-8')) if (resultados / 'resumo.json').exists() else {}
    (RELATORIOS / 'resumo_kernel.json').write_text(json.dumps(resumo, indent=2, ensure_ascii=False), encoding='utf-8')
    print(df.groupby(['precisa_llm', 'acao']).agg(perguntas=('aprovada', 'size'), validas=('valida', 'mean'),
                                                  aprovadas=('aprovada', 'mean')).round(2))
    print(resumo)
    if respostas_b:
        comparar_llm_b(pedidos, respostas, respostas_b)


def comparar_llm_b(pedidos, respostas_a, respostas_b):
    """Mesmas verificações para as respostas da A e da B, pergunta a pergunta (reports/.../comparacao_llm_b.csv)."""
    linhas = []
    for p in pedidos:
        if not p['precisa_llm'] or p['pergunta_id'] not in respostas_b:
            continue
        for rotulo, pedido, r in (('A', p, respostas_a.get(p['pergunta_id'])),
                                  ('B', pedido_fallback(p), respostas_b[p['pergunta_id']])):
            texto = (r or {}).get('resposta') or ''
            problemas = validar_resposta(pedido, r) if r else ['sem resposta']
            saida = revisar(p, texto) if texto else None
            codigos = sorted({a['codigo'] for a in saida.alertas}) if saida else []
            citacoes = len(g.CITACAO.findall(texto))
            linhas.append(dict(pergunta_id=p['pergunta_id'], acao=p['acao'], llm=rotulo, modelo=pedido['modelo'],
                               valida=not problemas, problemas='; '.join(problemas),
                               aprovada=bool(saida and saida.aprovada and not problemas),
                               bloqueantes=', '.join(c for c in codigos if c in g.BLOQUEANTES),
                               alertas=', '.join(c for c in codigos if c not in g.BLOQUEANTES),
                               citacoes=citacoes, segundos=(r or {}).get('segundos'), tokens_saida=(r or {}).get('tokens_saida')))
    df = pd.DataFrame(linhas)
    df.to_csv(RELATORIOS / 'comparacao_llm_b.csv', index=False, encoding='utf-8')
    resumo_b = ROOT / 'output/kaggle/fallback/resultados/resumo.json'
    if resumo_b.exists():
        (RELATORIOS / 'resumo_kernel_llm_b.json').write_text(resumo_b.read_text(encoding='utf-8'), encoding='utf-8')
    print(df.groupby('modelo').agg(respostas=('valida', 'size'), validas=('valida', 'sum'), aprovadas=('aprovada', 'sum'),
                                   citacoes_media=('citacoes', 'mean'), segundos_media=('segundos', 'mean')).round(1))


if __name__ == '__main__':
    main()
