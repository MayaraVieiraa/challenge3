"""Baixa as respostas do kernel do Kaggle, valida e aplica o guardrail de saída.

Saídas:
  output/kaggle/geracao_v2/resultados/            saída bruta do kernel (fora do Git)
  output/kaggle/geracao_v2/respostas_revisadas.jsonl  pergunta, ação, fontes, resposta final e alertas (fora do Git)
  reports/integracao/geracao_v2/revisao_saida.csv     uma linha por pergunta, só identificadores e métricas (no Git)
Uso: python scripts/importar_geracao_kaggle.py [--sem-download]
"""
from pathlib import Path
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd

from src.integracao import guardrails as g
from src.integracao.geracao import (
    FORMATO_SAIDA,
    analisar_saida_estruturada,
    renderizar_saida_estruturada,
    validar_resposta,
    revisar,
)
from src.integracao.observabilidade import Observabilidade

KERNEL = 'laisapaiva93/lexia-geracao-qwen3-v2'
BASE = ROOT / 'output/kaggle/geracao_v2'
RELATORIOS = ROOT / 'reports/integracao/geracao_v2'


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
    linhas, revisadas = [], []
    observabilidade = Observabilidade(BASE / 'observabilidade_importacao.jsonl')
    for p in pedidos:
        estrutura = None
        if p.get('erro_contexto'):
            problemas, texto = ['prompt excedeu o orçamento de contexto; geração não executada'], ''
            segundos, tokens = 0, None
            tokens_entrada = None
        elif p['precisa_llm']:
            r = respostas.get(p['pergunta_id'])
            problemas = ['sem resposta do kernel'] if r is None else validar_resposta(p, r)
            texto = ''
            if r and not problemas:
                bruto = r.get('resposta') or ''
                if p.get('formato') == FORMATO_SAIDA:
                    estrutura = analisar_saida_estruturada(bruto)
                    texto = renderizar_saida_estruturada(estrutura)
                else:
                    texto = bruto
            segundos, tokens = (r or {}).get('segundos'), (r or {}).get('tokens_saida')
            tokens_entrada = (r or {}).get('prompt_tokens')
        else:
            problemas, texto, segundos, tokens = [], p['resposta_fixa'], 0, None
            tokens_entrada = None
        saida = revisar(p, texto) if texto else g.ResultadoSaida(False, [dict(codigo='sem_resposta', detalhe='')], '')
        codigos = sorted({a['codigo'] for a in saida.alertas})
        linhas.append(dict(pergunta_id=p['pergunta_id'], origem=p['origem'], acao=p['acao'], precisa_llm=p['precisa_llm'],
                           fontes=len(p['fontes']), valida=not problemas, problemas='; '.join(problemas),
                           aprovada=saida.aprovada and not problemas,
                           bloqueantes=', '.join(c for c in codigos if c in g.BLOQUEANTES),
                           alertas=', '.join(c for c in codigos if c not in g.BLOQUEANTES),
                           segundos_geracao=segundos, tokens_saida=tokens, segundos_recuperacao=p.get('segundos_recuperacao')))
        revisadas.append(dict(pergunta_id=p['pergunta_id'], origem=p['origem'], acao=p['acao'],
                              pergunta_sanitizada=p['pergunta_sanitizada'], fontes=p['fontes'], resposta_modelo=texto,
                              saida_estruturada=estrutura,
                              resposta_final=saida.resposta_final, alertas=saida.alertas, aprovada=linhas[-1]['aprovada'],
                              problemas=problemas))
        observabilidade.registrar(
            'validacao_resposta',
            status='aprovada' if linhas[-1]['aprovada'] else 'reprovada',
            pergunta_id=p['pergunta_id'],
            metricas={
                'valida': not problemas,
                'aprovada': saida.aprovada and not problemas,
                'alertas': len(saida.alertas),
                'tokens_saida': tokens or 0,
                'tokens_entrada_observados': tokens_entrada or 0,
                'duracao_geracao_ms': (segundos or 0) * 1000,
            },
            tipo_erro='context_window_exceeded' if p.get('erro_contexto') else ('validation_failed' if problemas else None),
        )
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


if __name__ == '__main__':
    main()
