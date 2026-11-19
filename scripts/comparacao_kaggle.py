"""Notebook 05: LLM isolado × busca sem LLM × RAG híbrido nas 50 perguntas jurídicas (JUS) da curadoria.

Etapas (cada uma prepara um kernel do Kaggle ou importa o resultado):
  python scripts/comparacao_kaggle.py gerar     pedidos do LLM isolado (Qwen3 8B sem fontes)  → kernel lexia-comparacao-isolado
  python scripts/comparacao_kaggle.py julgar    baixa o isolado e monta os julgamentos das 3 configurações (Gemma 3 27B)
                                                → kernel lexia-comparacao-juiz
  python scripts/comparacao_kaggle.py importar  baixa os julgamentos e calcula as métricas por resposta
Depois de gerar/julgar: kaggle datasets create|version -p <dataset> e kaggle kernels push -p <kernel> (caminhos absolutos).

Reaproveita a busca e as respostas do RAG híbrido já geradas (output/kaggle/geracao). As 10 perguntas que o guardrail
de entrada classifica como consulta individual recebem a resposta fixa nas 3 configurações (decisão do notebook 05).
Saídas fora do Git em output/kaggle/comparacao/; métricas por resposta em reports/integracao/comparacao/ (no Git).
"""
from pathlib import Path
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd

from src.integracao import comparacao as cmp
from src.integracao import guardrails as g
from src.integracao.geracao import MODELO_GERACAO, OPCOES_GERACAO, NOTA_CASO_CONCRETO, ACOES_COM_BUSCA, _hash, revisar
from src.integracao.juiz import (pedido_kaggle, interpretar, TITULO_FONTES, TITULO_FONTES_VERIFICACAO,
                                SISTEMA_JUIZ_COMPARACAO)

USUARIO = 'laisapaiva93'
BASE = ROOT / 'output/kaggle/comparacao'
GERACAO = ROOT / 'output/kaggle/geracao'
RELATORIOS = ROOT / 'reports/integracao/comparacao'
CURADORIA = ROOT / 'data/evaluation/legislacao/perguntas_consolidadas_pre09.csv'
MODELO_JUIZ = 'gemma3:27b'


def jsonl(caminho):
    return [json.loads(l) for l in Path(caminho).read_text(encoding='utf-8').splitlines() if l.strip()]


def conjunto():
    """As 50 perguntas JUS: pedido do RAG (busca + ação), referência da curadoria e resposta do RAG híbrido."""
    cur = pd.read_csv(CURADORIA, sep=';', encoding='utf-8-sig')
    cur['qid'] = cur['query_id'].str.replace('golden_set_', 'q09_p1_')
    cur = cur[cur['qid'].str.contains('JUS')].set_index('qid')
    pedidos = {p['pergunta_id']: p for p in jsonl(GERACAO / 'dataset/pedidos.jsonl') if p['pergunta_id'] in cur.index}
    respostas = {r['pergunta_id']: r for r in jsonl(GERACAO / 'resultados/respostas.jsonl')}
    itens = []
    for qid, linha in cur.iterrows():
        p = pedidos[qid]
        itens.append(dict(pedido=p, referencias=cmp.referencias(linha['fonte_juridica_sugerida']),
                          referencia_texto=f"Fonte jurídica sugerida pela curadoria: {linha['fonte_juridica_sugerida']}\n"
                                           f"Comportamento esperado: {linha['comportamento_esperado']}",
                          rag=respostas.get(qid)))
    return itens


def kernel(nome, dataset, destino):
    (destino / 'kernel').mkdir(parents=True, exist_ok=True)
    (destino / 'kernel/kernel-metadata.json').write_text(json.dumps(dict(
        id=f'{USUARIO}/{nome}', title=nome, code_file='gerar_respostas.py', language='python', kernel_type='script',
        is_private=True, enable_gpu=True, enable_tpu=False, enable_internet=True, machine_shape='NvidiaTeslaT4',
        dataset_sources=[f'{USUARIO}/{dataset}'], competition_sources=[], kernel_sources=[], model_sources=[]), indent=2),
        encoding='utf-8')
    (destino / 'kernel/gerar_respostas.py').write_text((ROOT / 'scripts/kaggle_gerar_respostas.py').read_text(encoding='utf-8'),
                                                      encoding='utf-8')
    (destino / 'dataset/dataset-metadata.json').write_text(json.dumps(dict(
        title=dataset, id=f'{USUARIO}/{dataset}', licenses=[dict(name='unknown')],
        description='Pedidos privados da comparação do LexIA (notebook 05). Não redistribuir.'), indent=2), encoding='utf-8')


def gravar(pedidos, destino):
    (destino / 'dataset').mkdir(parents=True, exist_ok=True)
    with (destino / 'dataset/pedidos.jsonl').open('w', encoding='utf-8', newline='\n') as f:
        for p in pedidos:
            f.write(json.dumps(p, ensure_ascii=False) + '\n')


def gerar():
    pedidos = []
    for item in conjunto():
        p = item['pedido']
        if p['acao'] not in ACOES_COM_BUSCA:
            continue
        nota = NOTA_CASO_CONCRETO.replace(' com base nas fontes', '')   # o isolado não recebe fontes
        usuario = p['pergunta_sanitizada'] + (nota if p['acao'] == 'orientar_sem_aconselhar' else '')
        mensagens = [dict(role='system', content=cmp.PROMPT_ISOLADO), dict(role='user', content=usuario)]
        pedidos.append(dict(pergunta_id=p['pergunta_id'], precisa_llm=True, modelo=MODELO_GERACAO, opcoes=OPCOES_GERACAO,
                            mensagens=mensagens, think=False, pedido_sha256=_hash(MODELO_GERACAO, OPCOES_GERACAO, mensagens)))
    destino = BASE / 'isolado'
    gravar(pedidos, destino)
    kernel('lexia-comparacao-isolado', 'lexia-comparacao-isolado-pedidos', destino)
    print(len(pedidos), 'pedidos do LLM isolado →', destino.relative_to(ROOT))


def baixar(kernel_id, destino):
    destino.mkdir(parents=True, exist_ok=True)
    if '--sem-download' not in sys.argv:
        subprocess.run(['kaggle', 'kernels', 'output', kernel_id, '-p', str(destino), '-o'], check=True)
    return {r['pergunta_id']: r for r in jsonl(destino / 'respostas.jsonl')}


def julgar():
    isolado = baixar(f'{USUARIO}/lexia-comparacao-isolado', BASE / 'isolado/resultados')
    pedidos = []
    for item in conjunto():
        p = item['pedido']
        if p['acao'] not in ACOES_COM_BUSCA:
            continue
        legislacao = [f for f in p['fontes'] if f['fonte'] == 'legislacao']
        respostas = {'llm_isolado': ((isolado.get(p['pergunta_id']) or {}).get('resposta'), p['fontes'], TITULO_FONTES_VERIFICACAO),
                     'busca_sem_llm': (cmp.resposta_busca(legislacao), legislacao[:3], TITULO_FONTES),
                     'rag_hibrido': ((item['rag'] or {}).get('resposta'), p['fontes'], TITULO_FONTES)}
        for config, (texto, fontes, titulo) in respostas.items():
            if texto:
                pedidos.append(dict(pedido_kaggle(f'{config}|{p["pergunta_id"]}', p['pergunta_sanitizada'], p['acao'], fontes,
                                                  texto, item['referencia_texto'], modelo=MODELO_JUIZ, titulo_fontes=titulo,
                                                  sistema=SISTEMA_JUIZ_COMPARACAO),
                                    config=config))
    destino = BASE / 'juiz'
    gravar(pedidos, destino)
    kernel('lexia-comparacao-juiz', 'lexia-comparacao-juiz-pedidos', destino)
    print(len(pedidos), 'julgamentos:', pd.Series([p['config'] for p in pedidos]).value_counts().to_dict())


def importar():
    isolado = baixar(f'{USUARIO}/lexia-comparacao-isolado', BASE / 'isolado/resultados')
    saidas = baixar(f'{USUARIO}/lexia-comparacao-juiz', BASE / 'juiz/resultados')
    pedidos_juiz = {p['pergunta_id']: p for p in jsonl(BASE / 'juiz/dataset/pedidos.jsonl')}
    linhas = []
    for item in conjunto():
        p = item['pedido']
        qid, refs = p['pergunta_id'], item['referencias']
        legislacao = [f for f in p['fontes'] if f['fonte'] == 'legislacao']
        for config in cmp.CONFIGURACOES:
            linha = dict(pergunta_id=qid, acao=p['acao'], config=config, n_referencias=len(refs))
            if p['acao'] not in ACOES_COM_BUSCA:   # resposta fixa nas 3 configurações
                saida = revisar(p, p['resposta_fixa'])
                linhas.append(dict(linha, resposta_fixa=True, seguranca=cmp.seguro(saida.alertas), latencia_s=0.0,
                                   inferencia_s=0.0))
                continue
            rec = (isolado.get(qid) if config == 'llm_isolado' else item['rag'] if config == 'rag_hibrido' else None) or {}
            texto = cmp.resposta_busca(legislacao) if config == 'busca_sem_llm' else rec.get('resposta') or ''
            busca_s = p.get('segundos_recuperacao') or 0.0
            inferencia = 0.0 if config == 'busca_sem_llm' else rec.get('segundos')
            latencia = (inferencia or 0.0) + (busca_s if config != 'llm_isolado' else 0.0)
            saida = revisar(dict(p, fontes=[] if config == 'llm_isolado' else p['fontes']), texto) if texto else None
            linha.update(resposta_fixa=False, latencia_s=latencia, inferencia_s=inferencia,
                         recall_3=cmp.recall_em_3(refs, legislacao) if config != 'llm_isolado' else None,
                         cita_referencia=cmp.cita_referencia(texto, refs) if config != 'busca_sem_llm' else None,
                         seguranca=cmp.seguro(saida.alertas) if saida else None)
            jid = f'{config}|{qid}'
            s = saidas.get(jid)
            if s and pedidos_juiz.get(jid) and s.get('pedido_sha256') == pedidos_juiz[jid]['pedido_sha256']:
                try:
                    j = interpretar(s['resposta'])
                    linha.update(correcao=j.get('correcao'), fidelidade=j.get('fidelidade'), aderencia=j.get('comportamento'),
                                 clareza=j.get('clareza'), veredito_regra=j['veredito_regra'])
                except (ValueError, TypeError) as e:
                    linha['erro_juiz'] = str(e)[:120]
            linhas.append(linha)
    df = pd.DataFrame(linhas)
    RELATORIOS.mkdir(parents=True, exist_ok=True)
    df.to_csv(RELATORIOS / 'metricas_por_resposta.csv', index=False, encoding='utf-8')
    print(df.groupby('config')[['correcao', 'fidelidade', 'aderencia', 'seguranca', 'recall_3', 'cita_referencia',
                                'latencia_s', 'inferencia_s']].mean().round(2).T)


if __name__ == '__main__':
    {'gerar': gerar, 'julgar': julgar, 'importar': importar}[sys.argv[1]]()
