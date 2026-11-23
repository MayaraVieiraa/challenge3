"""Efeito dos sinônimos jurídicos e da terceira fonte na busca de legislação e de decisões (notebook 07, seção 9).

Usa os gabaritos e a configuração final do notebook 01 da integração (híbrida com IDF + reranker, cotas 3 + 3,
cota de 10 candidatos por fonte, 256 tokens no reranker) e compara três execuções nas mesmas perguntas:
  2 bases, sem sinônimos      referência, com a legislação atual (ec141_2026_notas)
  2 bases, com sinônimos      só liga expandir_sinonimos
  3 bases (com precedentes)   configuracao_com_precedentes(): sinônimos + precedentes + união no reranker

Lê:    data/evaluation/legislacao/eval_dataset_{dev,test}_aprovado.json  (16 perguntas com artigo esperado)
       data/evaluation/jurisprudencia/perguntas_suporte.jsonl            (17 perguntas com trecho anotado)
       banco PostgreSQL (lex_clt, lex_jurisprudencia, lex_precedentes, lex_integracao)
Grava: reports/integracao/precedentes/sinonimos_recuperacao.csv   (uma linha por pergunta e execução; só ids)
       reports/integracao/precedentes/sinonimos_resumo.csv
Execução: python scripts/avaliar_sinonimos_recuperacao.py
"""
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.integracao import avaliacao_recuperacao as av  # noqa: E402
from src.integracao.recuperacao import Configuracao, Recuperador, configuracao_com_precedentes  # noqa: E402
from src.integracao.sinonimos import expandir  # noqa: E402
from src.storage.pgvector_store import load_database_url  # noqa: E402

SAIDA = ROOT / 'reports/integracao/precedentes'
COTAS = {'legislacao': 3, 'jurisprudencia': 3}
BASE = dict(top_k=10, entrega_por_fonte=COTAS, cota_por_fonte=10, reranker_max_length=256, lexical_modo='idf')
EXECUCOES = {
    '2 bases, sem sinônimos': Configuracao(**BASE),
    '2 bases, com sinônimos': Configuracao(**BASE, expandir_sinonimos=True),
    '3 bases (com precedentes)': configuracao_com_precedentes(),
}


def main():
    SAIDA.mkdir(parents=True, exist_ok=True)
    gabarito = av.gabarito_legislacao(ROOT) + av.gabarito_jurisprudencia(ROOT)
    r = Recuperador(load_database_url(ROOT / '.env.pgvector.local'), device='cpu', carregar_reranker=True)
    partes = []
    for rotulo, cfg in EXECUCOES.items():
        df = av.avaliar(r, gabarito, cfg, rotulo)
        partes.append(df)
        print('concluído:', rotulo, flush=True)
    r.fechar()
    resultados = pd.concat(partes, ignore_index=True)
    mudou = {q['query_id']: expandir(q['pergunta']) != q['pergunta'] for q in gabarito}
    resultados['pergunta_expandida'] = resultados.query_id.map(mudou)
    resultados.to_csv(SAIDA / 'sinonimos_recuperacao.csv', index=False)
    resumo = av.resumo(resultados)
    resumo.to_csv(SAIDA / 'sinonimos_resumo.csv', index=False)
    print(resumo.to_string())
    print('perguntas que ganharam sinônimos:', sum(mudou.values()), 'de', len(mudou))


if __name__ == '__main__':
    main()
