"""Nota de vigência no divisor 220 da LC 150/2015 (art. 2º, § 2º), ligado à jornada de 44 horas.

Decisão da usuária (2026-11-23), opção B: a nota só informa o que a EC 141/2026, a CF e a Súmula 431 do TST dizem.
  - A EC 141 reduz o limite semanal (44 / 42 / 40 horas) e não alterou o divisor 220.
  - Para 40 horas semanais, a Súmula 431 do TST aplica o divisor 200 (regra fixada para a CLT).
  - Para 42 horas, não há divisor fixado em lei ou súmula: a nota não indica nenhum.
  - A ressalva do próprio § 2º (jornada contratual inferior, divisor diverso) continua.

Parte da versão `ec141_2026_notas` e cria `ec141_2026_notas_divisor`, com o mesmo método do script das notas
(avaliacao/scripts/atualizar_legislacao_notas_ec141.py): só o trecho com a nota recebe embedding novo; os demais são copiados.
Na estratégia A (artigo inteiro), o art. 2º já tem a nota da jornada no caput; a nota nova entra depois do § 2º.

Saída : novos datasets em lex_clt (D e A) e dados/relatorios/legislacao/atualizacoes/lc150_divisor_220_nota.json
Uso   : python avaliacao/scripts/atualizar_legislacao_nota_divisor_lc150.py   (idempotente: se a versão já existir, só confere)
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / 'scripts'):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import atualizar_legislacao_notas_ec141 as notas  # noqa: E402

NOTA_LC150_DIVISOR = (
    '[Nota de vigência: a Emenda Constitucional nº 141, de 2026, reduz o limite semanal de trabalho do art. 7º, XIII, '
    'da CF, aplicável aos empregados domésticos pelo § 1º do art. 7º da CF: 44 horas semanais até 15/12/2026, 42 horas '
    'a partir de 16/12/2026 e 40 horas a partir de 16/12/2027. A emenda não alterou este divisor de 220 horas, que '
    'corresponde à jornada de 44 horas semanais. Para empregados sujeitos a 40 horas semanais, a Súmula 431 do TST '
    'aplica o divisor 200 (entendimento fixado para os empregados regidos pela CLT). Para 42 horas semanais, não há '
    'divisor fixado em lei ou súmula. Continua valendo a ressalva deste parágrafo: se o contrato estipular jornada '
    'mensal inferior, o divisor é diverso.]')
DISPOSITIVO = ('O salário-hora normal, em caso de empregado mensalista, será obtido dividindo-se o salário mensal por 220 '
               '(duzentas e vinte) horas, salvo se o contrato estipular jornada mensal inferior que resulte em divisor diverso.')


def main():
    notas.ATUALIZACAO = 'ec141_2026_notas_divisor'
    notas.BASE_VERSAO = 'ec141_2026_notas'
    notas.RELATORIO = ROOT / 'dados/relatorios/legislacao/atualizacoes/lc150_divisor_220_nota.json'
    notas.DATA_ATUALIZACAO = '2026-11-23'
    notas.PERMITIR_NOTA_EXISTENTE = True
    notas.ALVOS = [(DISPOSITIVO, NOTA_LC150_DIVISOR, 'leis-complementares/2015/lcp-150-2015.md', 'Art. 2º')]

    import psycopg
    from sentence_transformers import SentenceTransformer
    from worker.evidencia.recuperador import MODELO, REVISAO, VERSOES_LEGISLACAO
    from worker.evidencia.indices.pgvector_store import load_database_url

    conexao = psycopg.connect(load_database_url(ROOT / '.env.pgvector.local'), autocommit=True)
    encoder = SentenceTransformer(MODELO, revision=REVISAO, device='cpu', local_files_only=True)
    encoder.max_seq_length = 8192
    d, a = VERSOES_LEGISLACAO[notas.BASE_VERSAO]
    relatorio = dict(atualizacao=notas.ATUALIZACAO, versao_base=notas.BASE_VERSAO,
                     decisao='opção B (2026-11-23): nota que só informa; sem divisor para 42 horas',
                     notas={'LC 150/2015, art. 2º, § 2º': NOTA_LC150_DIVISOR}, versoes={})
    for estrategia, base in (('D_paragrafo_completo', d), ('A_artigo', a)):
        r = notas.criar_versao(conexao, encoder, estrategia, base)
        print(('já existia: ' if r['ja_existia'] else 'criada: ') + f"{estrategia} {r['dataset_id']} ({r['trechos']} trechos)")
        relatorio['versoes'][estrategia] = r
    notas.RELATORIO.parent.mkdir(parents=True, exist_ok=True)
    notas.RELATORIO.write_text(json.dumps(relatorio, indent=2, ensure_ascii=False), encoding='utf-8')
    print('relatório:', notas.RELATORIO.relative_to(ROOT))


if __name__ == '__main__':
    main()
