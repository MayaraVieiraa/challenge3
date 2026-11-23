"""Importa uma geração em duas etapas (v3.4) para o formato de uma etapa, usado pelo validador e pela segunda passada.

Para cada resposta: confere o hash do pedido, refaz as mensagens da redação a partir das fontes escolhidas e
confere que são as mesmas que o kernel usou. Grava o "pedido efetivo" (fontes = só as escolhidas, mensagens = as da
redação) e a resposta com o hash desse pedido. Assim, `scripts/avaliar_validador_v3.py` e
`scripts/preparar_revisao_complementar.py` funcionam sem mudança.

Lê:    output/kaggle/<geracao>/dataset/pedidos.jsonl e output/kaggle/<geracao>/resultados/respostas.jsonl
Grava: output/kaggle/<geracao>_efetivos/dataset/pedidos.jsonl e .../resultados/respostas.jsonl (fora do Git)
Uso:   python scripts/importar_geracao_duas_etapas.py --geracao geracao_v3_4
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.integracao import duas_etapas as de  # noqa: E402
from src.integracao.geracao import _hash  # noqa: E402


def ler(c):
    return [json.loads(l) for l in Path(c).read_text(encoding='utf-8').splitlines() if l.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--geracao', required=True)
    args = ap.parse_args()
    base, destino = ROOT / 'output/kaggle' / args.geracao, ROOT / 'output/kaggle' / f'{args.geracao}_efetivos'
    pedidos = {p['pergunta_id']: p for p in ler(base / 'dataset/pedidos.jsonl')}
    efetivos, respostas, problemas = [], [], []
    for r in ler(base / 'resultados/respostas.jsonl'):
        p = pedidos[r['pergunta_id']]
        if r['pedido_sha256'] != p['pedido_sha256']:
            raise SystemExit(f"{r['pergunta_id']}: a resposta não corresponde ao pedido")
        mensagens, selecionadas = de.montar_redacao(p['pergunta_sanitizada'], p['fontes'], r['escolhidas'], p['data_atual'],
                                                    p['redacao']['complemento'], r['nao_coberto'])
        if mensagens != r['mensagens_redacao']:
            raise SystemExit(f"{r['pergunta_id']}: as mensagens da redação não são reproduzidas")
        if not r.get('resposta'):
            problemas.append(r['pergunta_id'])
        efetivo = {k: v for k, v in p.items() if k not in ('escolha', 'redacao', 'janela_contexto')}
        efetivo.update(fontes=selecionadas, mensagens=mensagens, escolhidas=r['escolhidas'], nao_coberto=r['nao_coberto'],
                       fontes_v3_3=[f['unidade'] for f in p['fontes']], pedido_duas_etapas_sha256=p['pedido_sha256'],
                       pedido_sha256=_hash(p['modelo'], p['opcoes'], mensagens))
        efetivos.append(efetivo)
        respostas.append(dict(pergunta_id=r['pergunta_id'], pedido_sha256=efetivo['pedido_sha256'], modelo=r.get('modelo'),
                              resposta=r.get('resposta'), done_reason=r.get('done_reason'), prompt_tokens=r.get('prompt_tokens'),
                              tokens_saida=r.get('tokens_saida'), segundos=r.get('segundos')))
    efetivos += [p for p in pedidos.values() if not p.get('precisa_llm')]
    for pasta, linhas in (('dataset', efetivos), ('resultados', respostas)):
        (destino / pasta).mkdir(parents=True, exist_ok=True)
        with (destino / pasta / ('pedidos.jsonl' if pasta == 'dataset' else 'respostas.jsonl')).open('w', encoding='utf-8', newline='\n') as f:
            for l in linhas:
                f.write(json.dumps(l, ensure_ascii=False) + '\n')
    print(f'{len(respostas)} respostas importadas · sem resposta: {problemas or "nenhuma"} · fontes escolhidas por resposta: '
          f'{dict(sorted(Counter(len(r["escolhidas"]) for r in ler(base / "resultados/respostas.jsonl")).items()))}')
    print('saída:', destino.relative_to(ROOT))


if __name__ == '__main__':
    main()
