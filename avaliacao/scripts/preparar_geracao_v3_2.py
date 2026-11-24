"""Prepara a geração v3.2: a geração v3.1 com a terceira base (precedentes do TST) nas fontes.

Parte dos pedidos da v3.1 e muda só uma coisa, para que a diferença entre v3.1 e v3.2 venha só dos precedentes:
  - entram 3 precedentes por pergunta (Fontes 7 a 9), buscados como em `configuracao_com_precedentes()`:
    busca semântica + por palavras, união no reranker e sinônimos jurídicos na pergunta;
  - o prompt v3 ganha a regra 25 (precedentes) e o tipo de fonte "precedente do TST".
Continuam iguais: as perguntas, as 3 fontes de legislação (versão ec141_2026_notas) e as 3 decisões judiciais da v3.1,
a data atual (2026-11-22), o modelo (Qwen3 8B q8_0) e as opções (temperatura 0, seed 42).

Os sinônimos entram só na busca dos precedentes. A legislação e as decisões não são buscadas de novo; na
configuração de produção elas também recebem os sinônimos, efeito pequeno medido à parte (notebook 07, seção 8).

Controles (se algum falhar, nada é gravado):
  1. o prompt v3 refeito com as fontes da v3.1 reproduz a mensagem do usuário da v3.1, e o prompt de sistema só
     difere pela regra 25;
  2. todos os pedidos cabem na janela de contexto (16.384 tokens, com 1.200 de saída). Se um pedido não couber com
     os 3 precedentes, sai o de pior posição até caber (registrado no relatório); as opções do modelo não mudam.
     Só a juris_011, já a maior da v3.1, passou do limite: 15.255 tokens estimados com 3 precedentes e 14.679 com
     1, para 14.672 de limite. Ela fica sem precedentes (igual à v3.1, a menos da regra 25).

Saída (fora do Git): dados/output/kaggle/geracao_v3_2/{dataset,kernel}; resumo dos precedentes entregues em
dados/relatorios/integracao/correcoes/geracao_v3_2_precedentes.csv (só identificadores).
Uso: python avaliacao/scripts/preparar_geracao_v3_2.py
"""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from worker.evidencia.context_window import ContextWindowExceeded, validar_janela_contexto  # noqa: E402
from worker.evidencia.explicador import _hash, fonte_para_prompt  # noqa: E402
from worker.evidencia.prompt_juridico import REGRA_25_V3_2, REGRAS_V3, build_rag_prompt  # noqa: E402
from worker.evidencia.recuperador import Recuperador, configuracao_com_precedentes  # noqa: E402
from worker.evidencia.sinonimos import termos_faltantes  # noqa: E402
from worker.evidencia.indices.pgvector_store import load_database_url  # noqa: E402

ORIGEM = ROOT / 'dados/output/kaggle/geracao_v3_1'
KERNEL_ORIGEM = ROOT / 'dados/output/kaggle/geracao/kernel'
DESTINO = ROOT / 'dados/output/kaggle/geracao_v3_2'
RELATORIO = ROOT / 'dados/relatorios/integracao/correcoes/geracao_v3_2_precedentes.csv'
USUARIO_KAGGLE = 'laisapaiva93'
DATASET = 'lexia-geracao-v3-2-pedidos'
KERNEL = 'lexia-geracao-qwen3-v3-2'
COTA_PRECEDENTES = 3
REGRA_25 = REGRAS_V3[REGRAS_V3.index('\n25. ') + 1:]
# alerta_lei_posterior=False: a v3.2 foi preparada antes do alerta de lei posterior (v3.3)
CONFIG = configuracao_com_precedentes(fontes=('precedentes',), entrega_por_fonte={'precedentes': COTA_PRECEDENTES},
                                      alerta_lei_posterior=False)


def main():
    pedidos = [json.loads(l) for l in (ORIGEM / 'dataset/pedidos.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
    rec = Recuperador(load_database_url(ROOT / '.env.pgvector.local'), device='cpu', carregar_reranker=True,
                      versao_legislacao='ec141_2026_notas')
    novos, linhas, acima = [], [], []
    for p in pedidos:
        if not p.get('precisa_llm'):
            novos.append(p)
            continue
        data_atual = p['data_atual']
        # Controle 1: o prompt atual, com as fontes da v3.1, reproduz a v3.1 (a menos da regra 25 no sistema).
        sistema31, usuario31 = build_rag_prompt(p['pergunta_sanitizada'], p['fontes'], versao='v3', data_atual=data_atual)
        if sistema31.replace(REGRA_25, '', 1) != p['mensagens'][0]['content']:
            raise SystemExit(f"{p['pergunta_id']}: o prompt de sistema difere da v3.1 além da regra 25 (nada gravado)")
        if not p['mensagens'][1]['content'].startswith(usuario31):
            raise SystemExit(f"{p['pergunta_id']}: a mensagem do usuário não reproduz a v3.1 (nada gravado)")
        complemento = p['mensagens'][1]['content'][len(usuario31):]

        entregues, _ = rec.buscar(p['pergunta_sanitizada'], CONFIG)
        encontrados = [fonte_para_prompt(u) for u in entregues]
        # Se não couber na janela, tira o precedente de pior posição (as opções do modelo não mudam).
        janela = None
        for n in range(len(encontrados), -1, -1):
            precedentes = encontrados[:n]
            fontes = p['fontes'] + precedentes
            sistema, usuario = build_rag_prompt(p['pergunta_sanitizada'], fontes, versao='v3', data_atual=data_atual)
            sistema = sistema.replace(REGRA_25, REGRA_25_V3_2, 1)   # a v3.2 usou o texto anterior da regra 25
            mensagens = [dict(role='system', content=sistema), dict(role='user', content=usuario + complemento)]
            try:
                janela = validar_janela_contexto(mensagens, max_context_tokens=p['opcoes']['num_ctx'],
                                                 max_output_tokens=p['opcoes']['num_predict'])
                break
            except ContextWindowExceeded as erro:
                excedeu = erro.budget.estimated_input_tokens
        if janela is None:
            acima.append(f"{p['pergunta_id']} ({excedeu})")
            continue
        novos.append(dict(p, fontes=fontes, mensagens=mensagens, fontes_recuperacao=['legislacao', 'jurisprudencia', 'precedentes'],
                          pedido_sha256=_hash(p['modelo'], p['opcoes'], mensagens), pedido_v3_1_sha256=p['pedido_sha256'],
                          janela_contexto=janela.para_dict()))
        linhas.append(dict(pergunta_id=p['pergunta_id'], precedentes=';'.join(f['unidade'] for f in precedentes),
                           entregues=len(precedentes), cortados_pela_janela=';'.join(f['unidade'] for f in encontrados[len(precedentes):]),
                           situacoes=';'.join(f.get('situacao') or '' for f in precedentes),
                           com_alerta_vigencia=sum(bool(f.get('alerta_vigencia')) for f in precedentes),
                           sem_tese=sum(f.get('situacao') == 'afetado_sem_tese' for f in precedentes),
                           sinonimos=len(termos_faltantes(p['pergunta_sanitizada'])),
                           tokens_v3_1=p['janela_contexto']['estimated_input_tokens'],
                           tokens_v3_2=janela.estimated_input_tokens))
    rec.fechar()
    if acima:
        raise SystemExit(f'pedidos acima da janela de contexto (nada gravado): {acima}')

    dataset = DESTINO / 'dataset'
    dataset.mkdir(parents=True, exist_ok=True)
    with (dataset / 'pedidos.jsonl').open('w', encoding='utf-8', newline='\n') as f:
        for p in novos:
            f.write(json.dumps(p, ensure_ascii=False) + '\n')
    (dataset / 'dataset-metadata.json').write_text(json.dumps(dict(
        title=DATASET, id=f'{USUARIO_KAGGLE}/{DATASET}', licenses=[dict(name='unknown')],
        description=('Pedidos privados de geração do LexIA, prompt v3 com regras 24 e 25, legislação atualizada '
                     '(EC 141/2026) e precedentes do TST como terceira fonte. Contém trechos de decisões não '
                     'anonimizados integralmente; não redistribuir.')), indent=2, ensure_ascii=False), encoding='utf-8')
    kernel = DESTINO / 'kernel'
    kernel.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(KERNEL_ORIGEM / 'gerar_respostas.py', kernel / 'gerar_respostas.py')
    meta = json.loads((KERNEL_ORIGEM / 'kernel-metadata.json').read_text(encoding='utf-8'))
    meta.update(id=f'{USUARIO_KAGGLE}/{KERNEL}', title=KERNEL, dataset_sources=[f'{USUARIO_KAGGLE}/{DATASET}'])
    (kernel / 'kernel-metadata.json').write_text(json.dumps(meta, indent=2), encoding='utf-8')

    t = pd.DataFrame(linhas)
    RELATORIO.parent.mkdir(parents=True, exist_ok=True)
    t.to_csv(RELATORIO, index=False, encoding='utf-8')
    cortados = t[t.entregues < COTA_PRECEDENTES]
    print(f'{len(novos)} pedidos ({len(t)} com LLM) · com {COTA_PRECEDENTES} precedentes: {int((t.entregues == COTA_PRECEDENTES).sum())} · '
          f'com menos, por causa da janela: {dict(zip(cortados.pergunta_id, cortados.entregues))}')
    print(f'precedentes distintos entregues: {len({u for l in t.precedentes for u in l.split(";")})} · '
          f'pedidos com alerta de vigência: {int((t.com_alerta_vigencia > 0).sum())} · com tema sem tese: {int((t.sem_tese > 0).sum())} '
          f'· com sinônimos: {int((t.sinonimos > 0).sum())}')
    print(f'tokens de entrada (estimados): v3.1 média {t.tokens_v3_1.mean():.0f}, máx {t.tokens_v3_1.max()} · '
          f'v3.2 média {t.tokens_v3_2.mean():.0f}, máx {t.tokens_v3_2.max()} (limite 14.672)')
    print('dataset:', dataset.relative_to(ROOT), '· kernel:', kernel.relative_to(ROOT), '· relatório:', RELATORIO.relative_to(ROOT))


if __name__ == '__main__':
    main()
