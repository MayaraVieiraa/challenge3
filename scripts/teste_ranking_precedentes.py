"""Teste: uma súmula do TST competiria com os acórdãos se fosse anexada à base de jurisprudência?

Para perguntas da amostra do advogado revisor em que a regra decisiva é uma súmula, compara a semelhança
(BGE-M3, mesma revisão da busca) entre a pergunta e o texto da súmula com a semelhança entre a pergunta e os
303 mil chunks de acórdãos da base de jurisprudência validada. A posição é exata: conta quantos chunks e quantos
documentos (acórdãos) ficam acima da súmula.

ATENÇÃO: os textos das súmulas abaixo foram digitados de memória, só para este teste (versão provisória). Quando a
coletânea oficial do TST chegar, rodar de novo com o texto oficial (--oficial, a implementar no notebook 01).

Requer: Postgres com pgvector (Docker) e o modelo BAAI/bge-m3 em cache local.
Saída : reports/precedentes/teste_ranking_jurisprudencia.csv (identificadores e números; sem o texto das perguntas)
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault('HF_HUB_OFFLINE', '1')

import pandas as pd  # noqa: E402

SAIDA = ROOT / 'reports/precedentes/teste_ranking_jurisprudencia.csv'
PEDIDOS = ROOT / 'output/kaggle/geracao/dataset/pedidos.jsonl'
SUMULAS = {
    'juris_004': ('Súmula 338, I, do TST', 'Súmula nº 338 do TST. JORNADA DE TRABALHO. REGISTRO. ÔNUS DA PROVA. I - É ônus do empregador que conta com mais de 10 (dez) empregados o registro da jornada de trabalho na forma do art. 74, § 2º, da CLT. A não-apresentação injustificada dos controles de frequência gera presunção relativa de veracidade da jornada de trabalho, a qual pode ser elidida por prova em contrário.'),
    'q09_p2_FAQ32': ('Súmula 276 do TST', 'Súmula nº 276 do TST. AVISO PRÉVIO. RENÚNCIA PELO EMPREGADO. O direito ao aviso prévio é irrenunciável pelo empregado. O pedido de dispensa de cumprimento não exime o empregador de pagar o respectivo valor, salvo comprovação de haver o prestador dos serviços obtido novo emprego.'),
    'juris_013': ('Súmula 378, II, do TST', 'Súmula nº 378 do TST. ESTABILIDADE PROVISÓRIA. ACIDENTE DO TRABALHO. ART. 118 DA LEI Nº 8.213/1991. II - São pressupostos para a concessão da estabilidade o afastamento superior a 15 dias e a consequente percepção do auxílio-doença acidentário, salvo se constatada, após a despedida, doença profissional que guarde relação de causalidade com a execução do contrato de emprego.'),
    'juris_019': ('Súmula 6, VIII, do TST', 'Súmula nº 6 do TST. EQUIPARAÇÃO SALARIAL. ART. 461 DA CLT. VIII - É do empregador o ônus da prova do fato impeditivo, modificativo ou extintivo da equiparação salarial.'),
    'q09_p1_JUS-001': ('Súmula 60 do TST', 'Súmula nº 60 do TST. ADICIONAL NOTURNO. INTEGRAÇÃO NO SALÁRIO E PRORROGAÇÃO EM HORÁRIO DIURNO. I - O adicional noturno, pago com habitualidade, integra o salário do empregado para todos os efeitos. II - Cumprida integralmente a jornada no período noturno e prorrogada esta, devido é também o adicional quanto às horas prorrogadas. Exegese do art. 73, § 5º, da CLT.'),
}


def main():
    import psycopg
    from pgvector.psycopg import register_vector
    from sentence_transformers import SentenceTransformer
    from src.integracao.recuperacao import MODELO, REVISAO
    from src.storage.pgvector_store import load_database_url

    perguntas = {}
    for linha in PEDIDOS.read_text(encoding='utf-8').splitlines():
        p = json.loads(linha)
        if p['pergunta_id'] in SUMULAS:
            perguntas[p['pergunta_id']] = p['pergunta_sanitizada']
    conexao = psycopg.connect(load_database_url(ROOT / '.env.pgvector.local'), autocommit=True)
    register_vector(conexao)
    ds = conexao.execute("SELECT dataset_id FROM lex_jurisprudencia.datasets WHERE estado='validado'").fetchone()[0]
    total_chunks, total_docs = conexao.execute(
        'SELECT count(*), count(DISTINCT registro_id) FROM lex_jurisprudencia.embeddings WHERE dataset_id=%s', (ds,)).fetchone()
    encoder = SentenceTransformer(MODELO, revision=REVISAO, device='cpu', local_files_only=True)

    linhas = []
    for pid, (nome, texto) in SUMULAS.items():
        q, s = encoder.encode([perguntas[pid], texto], normalize_embeddings=True)
        sim = float(q @ s)
        # Melhor semelhança por documento (acórdão) e posição exata da súmula entre chunks e entre documentos.
        acima_chunks, acima_docs, top1, top3_doc = conexao.execute(
            '''WITH s AS (SELECT registro_id, 1 - (embedding <=> %(q)s) AS sim
                          FROM lex_jurisprudencia.embeddings WHERE dataset_id = %(ds)s),
                    d AS (SELECT registro_id, max(sim) AS sim FROM s GROUP BY registro_id)
               SELECT (SELECT count(*) FROM s WHERE sim > %(t)s), (SELECT count(*) FROM d WHERE sim > %(t)s),
                      (SELECT max(sim) FROM s), (SELECT sim FROM d ORDER BY sim DESC OFFSET 2 LIMIT 1)''',
            dict(q=q, ds=ds, t=sim)).fetchone()
        linhas.append(dict(pergunta_id=pid, precedente=nome, semelhanca_sumula=round(sim, 3),
                           semelhanca_1o_acordao=round(float(top1), 3), semelhanca_3o_documento=round(float(top3_doc), 3),
                           posicao_entre_chunks=int(acima_chunks) + 1, posicao_entre_documentos=int(acima_docs) + 1,
                           entregue_com_cota_3=int(acima_docs) + 1 <= 3, total_chunks=int(total_chunks),
                           total_documentos=int(total_docs), texto_sumula='provisório (digitado de memória)'))
        print(linhas[-1])
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(linhas).to_csv(SAIDA, index=False, encoding='utf-8')
    print('saída:', SAIDA.relative_to(ROOT))


if __name__ == '__main__':
    main()
