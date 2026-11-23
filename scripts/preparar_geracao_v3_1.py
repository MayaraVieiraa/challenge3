"""Prepara a geração v3.1: prompt v3 com a regra 24 + legislação atualizada (EC 141/2026 e notas de vigência).

Mesmas perguntas, mesmas decisões judiciais, mesmo modelo e opções da geração atual. Muda só:
  1. a legislação: as 3 fontes de legislação de cada pedido são buscadas de novo na versão `ec141_2026_notas`
     (a jurisprudência é copiada do pedido original, sem nova busca);
  2. o prompt: v3 com a regra 24 (notas de vigência), data atual 2026-11-22.

Controle: antes de trocar a versão, a mesma busca só de legislação é feita na versão `original` e precisa reproduzir
exatamente as fontes de legislação do pedido original (mesmos artigos, mesmo texto, mesma ordem). Se não reproduzir,
nada é gravado: a diferença não poderia ser atribuída à atualização.

Saída (fora do Git): output/kaggle/geracao_v3_1/{dataset,kernel}; resumo das trocas em
reports/integracao/correcoes/geracao_v3_1_fontes_trocadas.csv (só identificadores).
Uso: python scripts/preparar_geracao_v3_1.py
"""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from src.integracao.context_window import ContextWindowExceeded, validar_janela_contexto  # noqa: E402
from src.integracao.geracao import _hash, fonte_para_prompt  # noqa: E402
from src.integracao.prompt_juridico import build_rag_prompt  # noqa: E402
from src.integracao.recuperacao import Recuperador, VERSOES_LEGISLACAO, configuracao_duas_bases  # noqa: E402
from src.storage.pgvector_store import load_database_url  # noqa: E402

ORIGEM = ROOT / 'output/kaggle/geracao'
DESTINO = ROOT / 'output/kaggle/geracao_v3_1'
RELATORIO = ROOT / 'reports/integracao/correcoes/geracao_v3_1_fontes_trocadas.csv'
USUARIO_KAGGLE = 'laisapaiva93'
DATASET = 'lexia-geracao-v3-1-pedidos'
KERNEL = 'lexia-geracao-qwen3-v3-1'
DATA_ATUAL = '2026-11-22'
VERSAO_NOVA = 'ec141_2026_notas'
COTA_LEGISLACAO = 3


def legislacao(recuperador, pergunta):
    config = configuracao_duas_bases(fontes=('legislacao',), entrega_por_fonte={'legislacao': COTA_LEGISLACAO}, top_k=10)
    entregues, _ = recuperador.buscar(pergunta, config)
    return [fonte_para_prompt(u) for u in entregues]


def chave(fontes):
    return [(f['unidade'], f['conteudo']) for f in fontes]


def main():
    pedidos = [json.loads(l) for l in (ORIGEM / 'dataset/pedidos.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
    com_llm = [p for p in pedidos if p.get('precisa_llm')]
    url = load_database_url(ROOT / '.env.pgvector.local')

    # 1. controle: a versão original reproduz as fontes de legislação dos pedidos
    rec = Recuperador(url, device='cpu', carregar_reranker=True, versao_legislacao='original')
    divergentes = [p['pergunta_id'] for p in com_llm
                   if chave(legislacao(rec, p['pergunta_sanitizada'])) != chave([f for f in p['fontes'] if f['fonte'] == 'legislacao'])]
    rec.fechar()
    if divergentes:
        raise SystemExit(f'a busca na versão original não reproduz {len(divergentes)} pedidos (nada gravado): {divergentes[:10]}')
    print(f'controle ok: a versão original reproduz as fontes de legislação dos {len(com_llm)} pedidos')

    # 2. versão nova
    rec = Recuperador(url, device='cpu', carregar_reranker=True, versao_legislacao=VERSAO_NOVA)
    novos, trocas, acima = [], [], []
    for p in pedidos:
        if not p.get('precisa_llm'):
            novos.append(p)
            continue
        sistema1, usuario1 = build_rag_prompt(p['pergunta_sanitizada'], p['fontes'])
        if p['mensagens'][0]['content'] != sistema1 or not p['mensagens'][1]['content'].startswith(usuario1):
            raise SystemExit(f"{p['pergunta_id']}: o prompt v1 não reproduz o pedido original")
        complemento = p['mensagens'][1]['content'][len(usuario1):]
        antigas = [f for f in p['fontes'] if f['fonte'] == 'legislacao']
        leg = legislacao(rec, p['pergunta_sanitizada'])
        fontes = leg + [f for f in p['fontes'] if f['fonte'] != 'legislacao']
        sistema, usuario = build_rag_prompt(p['pergunta_sanitizada'], fontes, versao='v3', data_atual=DATA_ATUAL)
        mensagens = [dict(role='system', content=sistema), dict(role='user', content=usuario + complemento)]
        try:
            janela = validar_janela_contexto(mensagens, max_context_tokens=p['opcoes']['num_ctx'],
                                             max_output_tokens=p['opcoes']['num_predict'])
        except ContextWindowExceeded as erro:
            acima.append(f"{p['pergunta_id']} ({erro.budget.estimated_input_tokens})")
            continue
        novos.append(dict(p, fontes=fontes, mensagens=mensagens, versao_prompt='v3', versao_legislacao=VERSAO_NOVA,
                          data_atual=DATA_ATUAL, pedido_sha256=_hash(p['modelo'], p['opcoes'], mensagens),
                          pedido_v1_sha256=p['pedido_sha256'], janela_contexto=janela.para_dict()))
        trocas.append(dict(pergunta_id=p['pergunta_id'],
                           legislacao_mudou=chave(leg) != chave(antigas),
                           artigos_mudaram=[f['unidade'] for f in leg] != [f['unidade'] for f in antigas],
                           com_nota_vigencia=sum('Nota de vigência' in f['conteudo'] for f in leg),
                           com_ec141=sum('emc-141-2026' in (f.get('caminho_relativo') or '') for f in leg)))
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
        description=('Pedidos privados de geração do LexIA, prompt v3 com regra 24 e legislação atualizada (EC 141/2026). '
                     'Contém trechos de decisões não anonimizados integralmente; não redistribuir.')), indent=2, ensure_ascii=False),
        encoding='utf-8')
    kernel = DESTINO / 'kernel'
    kernel.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ORIGEM / 'kernel/gerar_respostas.py', kernel / 'gerar_respostas.py')
    meta = json.loads((ORIGEM / 'kernel/kernel-metadata.json').read_text(encoding='utf-8'))
    meta.update(id=f'{USUARIO_KAGGLE}/{KERNEL}', title=KERNEL, dataset_sources=[f'{USUARIO_KAGGLE}/{DATASET}'])
    (kernel / 'kernel-metadata.json').write_text(json.dumps(meta, indent=2), encoding='utf-8')

    t = pd.DataFrame(trocas)
    RELATORIO.parent.mkdir(parents=True, exist_ok=True)
    t.to_csv(RELATORIO, index=False, encoding='utf-8')
    print(f"{len(novos)} pedidos ({len(t)} com LLM) · legislação mudou em {int(t.legislacao_mudou.sum())} "
          f"(artigos diferentes em {int(t.artigos_mudaram.sum())}) · com nota de vigência: {int((t.com_nota_vigencia > 0).sum())} "
          f"· com artigo da EC 141: {int((t.com_ec141 > 0).sum())}")
    print('dataset:', dataset.relative_to(ROOT), '· kernel:', kernel.relative_to(ROOT), '· relatório:', RELATORIO.relative_to(ROOT))


if __name__ == '__main__':
    main()
