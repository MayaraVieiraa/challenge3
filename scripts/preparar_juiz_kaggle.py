"""Prepara os pedidos do juiz (Gemma 3 12B no Kaggle).

Dois grupos de julgamento no mesmo pacote:
  calib_<id>  as 9 respostas antigas com decisão humana (feedback pós-teste): calibração do juiz.
              O juiz não vê a decisão da revisora.
  ger_<id>    as respostas geradas pelo Qwen3 8B (output/kaggle/geracao_v2/respostas_revisadas.jsonl).
Referência: resposta-ouro da curadoria (avaliação 09) ou pontos esperados + limites (conjuntos aprovados).
Saídas (fora do Git): output/kaggle/juiz_v2/dataset/ e output/kaggle/juiz_v2/kernel/.
Com --llama: só llama_<id>, as respostas da LLM B (Llama 3.1 8B) às mesmas perguntas, para comparar os dois
geradores com o mesmo juiz (output/kaggle/juiz_v2_llama/, kernel lexia-juiz-gemma3-v2-llama).
"""
from pathlib import Path
import glob
import json
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd

from src.integracao import guardrails as g
from src.integracao.context_window import ContextWindowExceeded
from src.integracao.juiz import pedido_kaggle, MODELO_JUIZ_KAGGLE
from src.integracao.observabilidade import Observabilidade

USUARIO_KAGGLE = 'laisapaiva93'
DATASET = 'lexia-juiz-pedidos-v2'
KERNEL = 'lexia-juiz-gemma3-v2'
# Cópia local (fora do Git) da curadoria anterior à avaliação 09, usada quando a pasta avaliacao_09 não existe.
BACKUP_CURADORIA = ROOT / 'data/evaluation/legislacao/perguntas_consolidadas_pre09.csv'
DESTINO = ROOT / 'output/kaggle/juiz_v2'


def preparar_pedido(julgamento_id, grupo, pergunta, acao, fontes, resposta, referencia, modelo, observabilidade):
    inicio = time.monotonic()
    try:
        pedido = pedido_kaggle(julgamento_id, pergunta, acao, fontes, resposta, referencia, modelo=modelo)
    except ContextWindowExceeded as erro:
        observabilidade.registrar(
            'preparacao_pedido_juiz',
            status='contexto_excedido',
            pergunta_id=julgamento_id,
            duracao_ms=(time.monotonic() - inicio) * 1000,
            metricas=erro.budget.para_dict(),
            tipo_erro=type(erro).__name__,
        )
        return dict(pergunta_id=julgamento_id, grupo=grupo, precisa_llm=False,
                    erro_contexto=erro.budget.para_dict())
    observabilidade.registrar(
        'preparacao_pedido_juiz',
        status='preparado',
        pergunta_id=julgamento_id,
        duracao_ms=(time.monotonic() - inicio) * 1000,
        metricas={
            'tokens_entrada_estimados': pedido['janela_contexto']['estimated_input_tokens'],
            'contexto_maximo': pedido['janela_contexto']['max_context_tokens'],
        },
    )
    return dict(pedido, grupo=grupo)


def referencias():
    refs = {}
    avaliacao_09 = next((ROOT / 'data/evaluation/legislacao/avaliacao_09').glob('*/perguntas_consolidadas.csv'), None)
    if avaliacao_09 is not None:
        curadoria = pd.read_csv(avaliacao_09)
        for _, q in curadoria.iterrows():
            if isinstance(q['resposta_ouro_planilha'], str) and q['resposta_ouro_planilha'].strip():
                refs[q['query_id']] = q['resposta_ouro_planilha'].strip()
    elif BACKUP_CURADORIA.exists():
        # Versão anterior à avaliação 09 (mesmas 100 perguntas, ids antigos e separador ';'). Só as FAQ têm resposta;
        # as perguntas JUS ficam sem referência e são julgadas pela fidelidade às fontes e pelo comportamento.
        curadoria = pd.read_csv(BACKUP_CURADORIA, sep=';', encoding='utf-8-sig')
        for _, q in curadoria.iterrows():
            novo_id = re.sub(r'^golden_set_', 'q09_p1_', re.sub(r'^faqs_lexia_', 'q09_p2_', q['query_id']))
            if isinstance(q['resposta'], str) and q['resposta'].strip():
                refs[novo_id] = q['resposta'].strip()
        print(f'avaliacao_09 ausente; referências da curadoria lidas de {BACKUP_CURADORIA.name} ({len(refs)} com resposta)')
    else:
        print('AVISO: sem respostas-ouro da curadoria; só os conjuntos aprovados terão referência')
    for nome in ('dev', 'test'):
        for q in json.loads((ROOT / f'data/evaluation/legislacao/eval_dataset_{nome}_aprovado.json').read_text(encoding='utf-8')):
            partes = [f'Pontos esperados: {q["pontos_esperados"]}' if q.get('pontos_esperados') else '',
                      f'Limites: {q["limites_resposta"]}' if q.get('limites_resposta') else '']
            if any(partes):
                refs[q['query_id']] = '\n'.join(p for p in partes if p)
    return refs


def main():
    global DATASET, KERNEL, DESTINO
    llama = '--llama' in sys.argv
    so_calibracao = '--so-calibracao' in sys.argv
    # --27b: Gemma 3 27B (~17 GB), dividido pelo Ollama entre as 2 GPUs T4 do Kaggle; o 12B aprovou as 3 respostas
    # que a revisora reprovou (calibração 0 de 3 nas reprovadas).
    modelo = 'gemma3:27b' if '--27b' in sys.argv else MODELO_JUIZ_KAGGLE
    if '--27b' in sys.argv:
        DATASET, KERNEL, DESTINO = 'lexia-juiz-27b-pedidos-v2', 'lexia-juiz-gemma3-v2-27b', ROOT / 'output/kaggle/juiz_v2_27b'
    if llama:
        # Terceira rodada: o mesmo juiz julga as respostas da LLM B (Llama 3.1 8B) às mesmas perguntas.
        # Requer: python scripts/importar_geracao_kaggle.py --fallback (preenche resposta_llm_b).
        DATASET, KERNEL, DESTINO = DATASET.replace('pedidos', 'llama-pedidos'), KERNEL + '-llama', DESTINO.with_name(DESTINO.name + '_llama')
    refs = referencias()
    pedidos = []
    observabilidade = Observabilidade(DESTINO / 'observabilidade_preparacao.jsonl')
    arquivo = glob.glob(str(ROOT / 'data/evaluation/legislacao/feedback_pos_teste/*/respostas_reais_e_feedback.jsonl'))[0]
    for l in Path(arquivo).read_text(encoding='utf-8').splitlines() if not llama else []:
        if l.strip():
            r = json.loads(l)
            entrada = g.verificar_entrada(r['pergunta'])
            fontes = [dict(fonte='legislacao', caminho_relativo=f.get('caminho_relativo'), artigo_ref=f.get('artigo_ref'),
                           conteudo=f.get('conteudo_chunk', '')) for f in r['fontes_entregues']]
            pedidos.append(preparar_pedido(
                f'calib_{r["query_id"]}', 'calibracao', entrada.pergunta_sanitizada, entrada.acao, fontes,
                r['resposta_real_modelo'], refs.get(r['query_id']), modelo, observabilidade,
            ))
    revisadas = ROOT / 'output/kaggle/geracao_v2/respostas_revisadas.jsonl'
    for l in revisadas.read_text(encoding='utf-8').splitlines() if not so_calibracao else []:
        if l.strip():
            r = json.loads(l)
            if llama:
                if r['acao'] in ('responder', 'orientar_sem_aconselhar') and r.get('resposta_llm_b'):
                    pedidos.append(preparar_pedido(
                        f'llama_{r["pergunta_id"]}', 'llama', r['pergunta_sanitizada'], r['acao'],
                        r['fontes'], r['resposta_llm_b'], refs.get(r['pergunta_id']), modelo, observabilidade,
                    ))
                continue
            if r['acao'] in ('responder', 'orientar_sem_aconselhar') and r['resposta_modelo']:
                pedidos.append(preparar_pedido(
                    f'ger_{r["pergunta_id"]}', 'geracao', r['pergunta_sanitizada'], r['acao'], r['fontes'],
                    r['resposta_modelo'], refs.get(r['pergunta_id']), modelo, observabilidade,
                ))
    (DESTINO / 'dataset').mkdir(parents=True, exist_ok=True)
    with (DESTINO / 'dataset/pedidos.jsonl').open('w', encoding='utf-8', newline='\n') as f:
        for p in pedidos:
            f.write(json.dumps(p, ensure_ascii=False) + '\n')
    (DESTINO / 'dataset/dataset-metadata.json').write_text(json.dumps(dict(
        title=DATASET, id=f'{USUARIO_KAGGLE}/{DATASET}', licenses=[dict(name='unknown')],
        description='Pedidos privados do juiz do LexIA (respostas geradas + fontes). Não redistribuir.'), indent=2), encoding='utf-8')
    (DESTINO / 'kernel').mkdir(parents=True, exist_ok=True)
    (DESTINO / 'kernel/kernel-metadata.json').write_text(json.dumps(dict(
        id=f'{USUARIO_KAGGLE}/{KERNEL}', title=KERNEL, code_file='gerar_respostas.py', language='python',
        kernel_type='script', is_private=True, enable_gpu=True, enable_tpu=False, enable_internet=True,
        machine_shape='NvidiaTeslaT4', dataset_sources=[f'{USUARIO_KAGGLE}/{DATASET}'], competition_sources=[],
        kernel_sources=[], model_sources=[]), indent=2), encoding='utf-8')
    (DESTINO / 'kernel/gerar_respostas.py').write_text((ROOT / 'scripts/kaggle_gerar_respostas.py').read_text(encoding='utf-8'),
                                                       encoding='utf-8')
    print(f'{len(pedidos)} pedidos de julgamento:', pd.Series([p['grupo'] for p in pedidos]).value_counts().to_dict(),
          '| com referência:', sum('RESPOSTA DE REFERÊNCIA' in p['mensagens'][1]['content'] for p in pedidos))


if __name__ == '__main__':
    main()
