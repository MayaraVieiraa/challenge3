"""Segunda passada de uma geração: as respostas bloqueadas pelo validador v3 são reescritas com busca complementar.

Para cada resposta bloqueada (validador v3):
  1. as normas citadas fora das fontes são buscadas na base (worker/evidencia/complementar.py), no máximo 2 fontes
     novas por resposta, numeradas depois das originais;
  2. o pedido de revisão leva as fontes originais e as novas, a resposta anterior e os motivos do bloqueio (norma
     fora das fontes, encontrada ou não na base; [Fonte N] inexistente; demais bloqueantes);
  3. o mesmo modelo, com as mesmas opções, reescreve a resposta (kernel de geração do Kaggle).
As respostas aprovadas não mudam. A resposta final de cada pergunta é a revisada, se houver, ou a original.

Lê:    dados/output/kaggle/<geracao>/dataset/pedidos.jsonl e dados/output/kaggle/<geracao>/resultados/respostas.jsonl (fora do Git)
Grava: dados/output/kaggle/<geracao>_revisao/{dataset,kernel}   (fora do Git)
       dados/relatorios/integracao/correcoes/<geracao>_revisao_complementar.csv   (só identificadores e códigos)
Uso:   python avaliacao/scripts/preparar_revisao_complementar.py --geracao geracao_v3_3
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from worker.evidencia import explicador as ger  # noqa: E402
from worker.evidencia import guardas as g  # noqa: E402
from worker.evidencia.complementar import BuscaComplementar, fontes_validador, montar_revisao, normas_faltantes  # noqa: E402
from worker.evidencia.context_window import ContextWindowExceeded, validar_janela_contexto  # noqa: E402
from worker.evidencia.recuperador import Recuperador  # noqa: E402
from worker.evidencia.indices.pgvector_store import load_database_url  # noqa: E402

USUARIO_KAGGLE = 'laisapaiva93'
KERNEL_ORIGEM = ROOT / 'dados/output/kaggle/geracao/kernel'


def ler(caminho):
    return [json.loads(l) for l in Path(caminho).read_text(encoding='utf-8').splitlines() if l.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--geracao', required=True, help='pasta em dados/output/kaggle, por exemplo geracao_v3_3')
    ap.add_argument('--versao-legislacao', default=None, help='versão da legislação da geração (padrão: a do pedido)')
    args = ap.parse_args()
    base = ROOT / 'dados/output/kaggle' / args.geracao
    destino = ROOT / 'dados/output/kaggle' / f'{args.geracao}_revisao'
    sufixo = args.geracao.replace('geracao_', '').replace('_', '-')
    dataset_nome, kernel_nome = f'lexia-revisao-{sufixo}-pedidos', f'lexia-revisao-qwen3-{sufixo}'
    relatorio = ROOT / f'dados/relatorios/integracao/correcoes/{args.geracao}_revisao_complementar.csv'

    pedidos = {p['pergunta_id']: p for p in ler(base / 'dataset/pedidos.jsonl')}
    respostas = {r['pergunta_id']: r for r in ler(base / 'resultados/respostas.jsonl')}
    bloqueadas = []
    for pid, r in respostas.items():
        p = pedidos[pid]
        if r.get('pedido_sha256') != p['pedido_sha256']:
            raise SystemExit(f'{pid}: a resposta não corresponde ao pedido (nada gravado)')
        saida = ger.revisar(dict(p, versao_prompt='v3'), r.get('resposta') or '')
        if not saida.aprovada:
            bloqueadas.append((p, r.get('resposta') or '', saida))
    versoes = {p.get('versao_legislacao') for p, _, _ in bloqueadas}
    versao = args.versao_legislacao or (versoes.pop() if len(versoes) == 1 else None)
    if versao is None:
        raise SystemExit(f'informe --versao-legislacao (pedidos com versões {versoes})')

    rec = Recuperador(load_database_url(ROOT / '.env.pgvector.local'), device='cpu', carregar_reranker=False,
                      versao_legislacao=versao)
    busca = BuscaComplementar(rec)
    novos, linhas, acima = [], [], []
    for p, texto, saida in bloqueadas:
        faltam = normas_faltantes(texto, fontes_validador(p['fontes']))
        encontradas = busca.buscar(p['pergunta_sanitizada'], faltam, ja_entregues={f['unidade'] for f in p['fontes']})
        novo = montar_revisao(p, texto, saida, encontradas)
        try:
            janela = validar_janela_contexto(novo['mensagens'], max_context_tokens=p['opcoes']['num_ctx'],
                                             max_output_tokens=p['opcoes']['num_predict'])
        except ContextWindowExceeded as erro:
            acima.append(f"{p['pergunta_id']} ({erro.budget.estimated_input_tokens})")
            continue
        novos.append(dict(novo, janela_contexto=janela.para_dict()))
        linhas.append(dict(pergunta_id=p['pergunta_id'],
                           bloqueantes=';'.join(sorted({a['codigo'] for a in saida.alertas} & g.BLOQUEANTES_V3)),
                           normas_faltantes=';'.join(f['rotulo'] for f in faltam),
                           encontradas=';'.join(f['rotulo'] for f, x in encontradas if x),
                           nao_encontradas=';'.join(f['rotulo'] for f, x in encontradas if not x),
                           fontes_complementares=';'.join(novo['fontes_complementares']),
                           tokens=janela.estimated_input_tokens))
    rec.fechar()
    if acima:
        print(f'aviso: pedidos de revisão acima da janela, ficam com a resposta original: {acima}')

    dataset = destino / 'dataset'
    dataset.mkdir(parents=True, exist_ok=True)
    with (dataset / 'pedidos.jsonl').open('w', encoding='utf-8', newline='\n') as f:
        for p in novos:
            f.write(json.dumps(p, ensure_ascii=False) + '\n')
    (dataset / 'dataset-metadata.json').write_text(json.dumps(dict(
        title=dataset_nome, id=f'{USUARIO_KAGGLE}/{dataset_nome}', licenses=[dict(name='unknown')],
        description=(f'Pedidos privados da segunda passada do LexIA ({args.geracao}): respostas bloqueadas pelo '
                     'validador, reescritas com busca complementar. Contém trechos de decisões não anonimizados '
                     'integralmente; não redistribuir.')), indent=2, ensure_ascii=False), encoding='utf-8')
    kernel = destino / 'kernel'
    kernel.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(KERNEL_ORIGEM / 'gerar_respostas.py', kernel / 'gerar_respostas.py')
    meta = json.loads((KERNEL_ORIGEM / 'kernel-metadata.json').read_text(encoding='utf-8'))
    meta.update(id=f'{USUARIO_KAGGLE}/{kernel_nome}', title=kernel_nome, dataset_sources=[f'{USUARIO_KAGGLE}/{dataset_nome}'])
    (kernel / 'kernel-metadata.json').write_text(json.dumps(meta, indent=2), encoding='utf-8')

    t = pd.DataFrame(linhas)
    relatorio.parent.mkdir(parents=True, exist_ok=True)
    t.to_csv(relatorio, index=False, encoding='utf-8')
    print(f'{len(respostas)} respostas · bloqueadas: {len(bloqueadas)} · pedidos de revisão: {len(novos)}')
    if len(t):
        print(f"com norma fora das fontes: {int((t.normas_faltantes != '').sum())} · com fonte nova encontrada: "
              f"{int((t.encontradas != '').sum())} · fontes novas: {sum(len(x.split(';')) for x in t.fontes_complementares if x)}")
    print('dataset:', dataset.relative_to(ROOT), '· kernel:', kernel.relative_to(ROOT), '· relatório:', relatorio.relative_to(ROOT))


if __name__ == '__main__':
    main()
