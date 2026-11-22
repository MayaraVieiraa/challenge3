"""Aplica o guardrail de saída v1 e o validador v3 às 111 respostas da geração (Qwen3 8B, prompt v1).

É a linha de base do notebook 06: quantas respostas atuais o validador v3 bloquearia e se ele pega as falhas que o
advogado revisor apontou nas 25 respostas da amostra (reports/integracao/juiz/diagnostico_especialista_27b.csv).

Entrada : output/kaggle/geracao/dataset/pedidos.jsonl e output/kaggle/geracao/resultados/respostas.jsonl (fora do Git)
Saída   : reports/integracao/correcoes/validador_v3_geracao.csv (só identificadores, contagens e códigos dos alertas)
Uso     : python scripts/avaliar_validador_v3.py [--respostas caminho.jsonl] [--rotulo v1]
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.integracao import geracao as ger  # noqa: E402
from src.integracao import guardrails as g  # noqa: E402

PEDIDOS = ROOT / 'output/kaggle/geracao/dataset/pedidos.jsonl'
RESPOSTAS = ROOT / 'output/kaggle/geracao/resultados/respostas.jsonl'
SAIDA = ROOT / 'reports/integracao/correcoes'
CODIGOS_V3 = ('norma_fora_das_fontes', 'sem_marcacao_fonte', 'lei_citada_com_decisao', 'citacao_em_lote',
              'metadado_interno', 'abertura_categorica')


def ler_jsonl(caminho):
    return [json.loads(l) for l in Path(caminho).read_text(encoding='utf-8').splitlines() if l.strip()]


def avaliar(pedidos, respostas, rotulo):
    por_id = {r['pergunta_id']: r for r in respostas}
    linhas = []
    for p in pedidos:
        if not p.get('precisa_llm') or p['pergunta_id'] not in por_id:
            continue
        texto = por_id[p['pergunta_id']].get('resposta') or ''
        v1 = ger.revisar(dict(p, versao_prompt=None), texto)
        v3 = ger.revisar(dict(p, versao_prompt='v3'), texto)
        cont = Counter(a['codigo'] for a in v3.alertas)
        linha = dict(id=p['pergunta_id'], acao=p['acao'], respostas=rotulo, bloqueada_v1=not v1.aprovada,
                     bloqueada_v3=not v3.aprovada,
                     bloqueantes_v3=';'.join(sorted({a['codigo'] for a in v3.alertas if a['codigo'] in g.BLOQUEANTES_V3})))
        linha.update({c: cont.get(c, 0) for c in CODIGOS_V3})
        linha['normas_fora'] = ';'.join(a['detalhe'].replace(' não aparece em nenhuma fonte entregue', '')
                                        for a in v3.alertas if a['codigo'] == 'norma_fora_das_fontes')
        linhas.append(linha)
    return pd.DataFrame(linhas)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--respostas', default=str(RESPOSTAS))
    ap.add_argument('--pedidos', default=str(PEDIDOS))
    ap.add_argument('--rotulo', default='v1', help='nome do conjunto de respostas (v1 = geração atual)')
    args = ap.parse_args()
    df = avaliar(ler_jsonl(args.pedidos), ler_jsonl(args.respostas), args.rotulo)
    SAIDA.mkdir(parents=True, exist_ok=True)
    arquivo = SAIDA / f'validador_v3_respostas_{args.rotulo}.csv'
    df.to_csv(arquivo, index=False, encoding='utf-8')
    print(f'{len(df)} respostas · bloqueadas pelo guardrail v1: {df.bloqueada_v1.sum()} · pelo validador v3: {df.bloqueada_v3.sum()}')
    print('respostas com cada alerta:', {c: int((df[c] > 0).sum()) for c in CODIGOS_V3})
    print('saída:', arquivo.relative_to(ROOT))


if __name__ == '__main__':
    main()
