"""Notas de vigência da EC 141/2026 em normas infraconstitucionais que repetem a regra antiga.

Parte da versão `ec141_2026` da base de legislação (art. 7º da CF já atualizado) e cria a versão
`ec141_2026_notas`, acrescentando uma nota de vigência a:
  - LC 150/2015, art. 2º (domésticos: 8 horas diárias e 44 semanais)  -> transição 44 / 42 / 40 horas;
  - Lei 605/1949, art. 1º (repouso semanal de 24 horas consecutivas) -> 2 dias de repouso a partir de 16/12/2026;
  - LC 150/2015, art. 16 (domésticos: descanso semanal de 24 horas)  -> idem, pelo § 1º do art. 7º da CF;
  - CLT, art. 67 (descanso semanal de 24 horas consecutivas)         -> idem;
  - CLT, art. 385 (descanso semanal da mulher, 24 horas)              -> idem.
O texto da lei não muda: a nota vem logo depois do dispositivo, entre colchetes, e diz só o que a EC 141 e a CF dizem.
As notas citam "art. 7º, XIII/XV, da CF" no próprio texto, para que o validador v3 aceite a citação da CF feita a
partir delas. Só os trechos com nota recebem embedding novo; os demais são copiados (mesmo texto e vetor).

Saída : novos datasets em lex_clt (D e A) e reports/legislacao/atualizacoes/ec_141_2026_notas.json
Uso   : python scripts/atualizar_legislacao_notas_ec141.py      (idempotente: se a versão já existir, só confere)
"""
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / 'scripts'):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
os.environ.setdefault('HF_HUB_OFFLINE', '1')

from src.storage.pgvector_store import json_hash, load_database_url, vector_hash  # noqa: E402

ATUALIZACAO = 'ec141_2026_notas'
BASE_VERSAO = 'ec141_2026'
RELATORIO = ROOT / 'reports/legislacao/atualizacoes/ec_141_2026_notas.json'
URL_EC = 'https://planalto.gov.br/ccivil_03/constituicao/emendas/emc/emc141.htm'
DATA_ATUALIZACAO = '2026-11-22'
PERMITIR_NOTA_EXISTENTE = False   # True: o trecho pode já ter outra nota (ex.: artigo inteiro, estratégia A)

NOTA_LC150_ART2 = (
    '[Nota de vigência: o limite semanal deste artigo segue o art. 7º, XIII, da CF, na redação da Emenda '
    'Constitucional nº 141, de 2026, que se aplica aos empregados domésticos pelo § 1º do art. 7º da CF. A redução '
    'é progressiva (art. 6º da EC 141/2026): até 15/12/2026, 44 horas semanais; a partir de 16/12/2026, no máximo '
    '42 horas semanais; a partir de 16/12/2027, 40 horas semanais. O limite de 8 horas diárias continua, e a '
    'redução não pode diminuir o salário, inclusive os pisos salariais (art. 2º da EC 141/2026).]')
NOTA_LEI605_ART1 = (
    '[Nota de vigência: a partir de 16/12/2026, o art. 7º, XV, da CF, na redação da Emenda Constitucional nº 141, '
    'de 2026 (art. 10, I, da emenda), assegura repouso semanal remunerado de 2 (dois) dias, um dos quais '
    'preferencialmente aos domingos; desde essa data, o mínimo de 24 horas consecutivas deste artigo fica superado '
    'pela regra constitucional. Convenção ou acordo coletivo pode estabelecer regime compensatório que assegure, na '
    'média, 2 dias de repouso no mês, com pelo menos 1 dia dentro de cada semana de trabalho (art. 7º, § 2º, da CF). '
    'A EC 141 não alterou os demais dispositivos desta Lei, que continuam aplicáveis no que forem compatíveis com a '
    'nova regra.]')
NOTA_LC150_ART16 = (
    '[Nota de vigência: a partir de 16/12/2026, o art. 7º, XV, da CF, na redação da Emenda Constitucional nº 141, '
    'de 2026 (art. 10, I, da emenda), assegura repouso semanal remunerado de 2 (dois) dias, um dos quais '
    'preferencialmente aos domingos, também aos empregados domésticos (§ 1º do art. 7º da CF); desde essa data, o '
    'mínimo de 24 horas consecutivas deste artigo fica superado pela regra constitucional. Convenção ou acordo '
    'coletivo pode estabelecer regime compensatório que assegure, na média, 2 dias de repouso no mês, com pelo menos '
    '1 dia dentro de cada semana de trabalho (art. 7º, § 2º, da CF). O descanso remunerado em feriados não foi '
    'alterado pela EC 141.]')
NOTA_CLT_ART67 = (
    '[Nota de vigência: a partir de 16/12/2026, o art. 7º, XV, da CF, na redação da Emenda Constitucional nº 141, '
    'de 2026 (art. 10, I, da emenda), assegura repouso semanal remunerado de 2 (dois) dias, um dos quais '
    'preferencialmente aos domingos; desde essa data, o descanso semanal de 24 horas consecutivas deste artigo fica '
    'superado pela regra constitucional. Convenção ou acordo coletivo pode estabelecer regime compensatório que '
    'assegure, na média, 2 dias de repouso no mês, com pelo menos 1 dia dentro de cada semana de trabalho '
    '(art. 7º, § 2º, da CF), inclusive para os regimes diferenciados de trabalho. A escala de revezamento do '
    'parágrafo único deste artigo não foi alterada pela EC 141.]')
NOTA_CLT_ART385 = (
    '[Nota de vigência: a partir de 16/12/2026, o art. 7º, XV, da CF, na redação da Emenda Constitucional nº 141, '
    'de 2026 (art. 10, I, da emenda), assegura a todos os trabalhadores repouso semanal remunerado de 2 (dois) dias, '
    'um dos quais preferencialmente aos domingos; desde essa data, o descanso semanal de 24 horas consecutivas deste '
    'artigo fica superado pela regra constitucional. Convenção ou acordo coletivo pode estabelecer regime '
    'compensatório que assegure, na média, 2 dias de repouso no mês, com pelo menos 1 dia dentro de cada semana de '
    'trabalho (art. 7º, § 2º, da CF).]')

# (trecho do texto após o qual a nota entra, nota, descrição)
ALVOS = [
    ('A duração normal do trabalho doméstico não excederá 8 (oito) horas diárias e 44 (quarenta e quatro) semanais, '
     'observado o disposto nesta Lei.', NOTA_LC150_ART2, 'leis-complementares/2015/lcp-150-2015.md', 'Art. 2º'),
    ('Todo empregado tem direito ao repouso semanal remunerado de vinte e quatro horas consecutivas, preferentemente '
     'aos domingos e, nos limites das exigências técnicas das empresas, nos feriados civis e religiosos, de acordo com '
     'a tradição local.', NOTA_LEI605_ART1, 'leis/1949/lei-605-1949.md', 'Art. 1º'),
    ('É devido ao empregado doméstico descanso semanal remunerado de, no mínimo, 24 (vinte e quatro) horas '
     'consecutivas, preferencialmente aos domingos, além de descanso remunerado em feriados.', NOTA_LC150_ART16,
     'leis-complementares/2015/lcp-150-2015.md', 'Art. 16'),
    ('Será assegurado a todo empregado um descanso semanal de 24 (vinte e quatro) horas consecutivas, o qual, salvo '
     'motivo de conveniência pública ou necessidade imperiosa do serviço, deverá coincidir com o domingo, no todo ou '
     'em parte.', NOTA_CLT_ART67, 'codigos/consolidacao-das-leis-do-trabalho-clt-del-5452-1943.md', 'Art. 67'),
    ('O descanso semanal será de 24 (vinte e quatro) horas consecutivas e coincidirá no todo ou em parte com o domingo, '
     'salvo motivo de conveniência pública ou necessidade imperiosa de serviço, a juízo da autoridade competente, na '
     'forma das disposições gerais, caso em que recairá em outro dia.', NOTA_CLT_ART385,
     'codigos/consolidacao-das-leis-do-trabalho-clt-del-5452-1943.md', 'Art. 385'),
]


def _sha(texto):
    return hashlib.sha256(texto.encode('utf-8')).hexdigest()


def trechos_com_nota(conexao, dataset_id):
    novos = []
    for dispositivo, nota, caminho, artigo in ALVOS:
        linhas = conexao.execute(
            'SELECT chunk_id, article_id, source_path, text_content, metadata FROM lex_clt.chunk_embeddings '
            "WHERE dataset_id=%s AND source_path=%s AND metadata->>'artigo_ref'=%s AND position(%s in text_content) > 0",
            (dataset_id, caminho, artigo, dispositivo)).fetchall()
        if len(linhas) != 1:
            raise SystemExit(f'{caminho} {artigo}: esperado 1 trecho com o dispositivo, encontrados {len(linhas)}')
        cid, art, sp, texto, meta = linhas[0]
        if 'Nota de vigência' in texto and not PERMITIR_NOTA_EXISTENTE:
            raise SystemExit(f'{caminho} {artigo}: o trecho já tem nota')
        novo_texto = texto.replace(dispositivo, f'{dispositivo} {nota}', 1)
        meta = dict(meta or {})
        meta.update(atualizacao=ATUALIZACAO, nota_vigencia='EC 141/2026', fonte_atualizacao=URL_EC,
                    tamanho_caracteres=len(novo_texto), tokens_reais_total=None, retrieved=DATA_ATUALIZACAO)
        novo_id = _sha(json.dumps([ATUALIZACAO, dataset_id, cid, _sha(novo_texto)]))
        meta['chunk_id'] = novo_id
        novos.append(dict(substitui=cid, chunk_id=novo_id, article_id=art, source_path=sp, text_content=novo_texto,
                          metadata=meta, artigo=f'{caminho} {artigo}'))
    return novos


def criar_versao(conexao, encoder, estrategia, base):
    from pgvector.psycopg import register_vector
    import numpy as np

    register_vector(conexao)
    manifesto_base, modelo, dims = conexao.execute(
        'SELECT manifest, model, dimensions FROM lex_clt.vector_datasets WHERE dataset_id=%s', (base,)).fetchone()
    linhas = conexao.execute('SELECT chunk_id, row_index, text_sha256, vector_sha256 FROM lex_clt.chunk_embeddings '
                             'WHERE dataset_id=%s ORDER BY row_index', (base,)).fetchall()
    novos = trechos_com_nota(conexao, base)
    vetores = encoder.encode([n['text_content'] for n in novos], normalize_embeddings=True, convert_to_numpy=True,
                             show_progress_bar=False).astype(np.float32)
    por_antigo = {n['substitui']: n for n in novos}
    for n, v in zip(novos, vetores):
        n.update(embedding=v, text_sha256=_sha(n['text_content']), vector_sha256=vector_hash(v))
    ordem = []
    for cid, ri, ts, vs in linhas:
        n = por_antigo.get(cid)
        if n:
            n['row_index'] = ri
            ordem.append((ri, n['text_sha256'], n['vector_sha256']))
        else:
            ordem.append((ri, ts, vs))
    manifesto = dict(
        model=modelo, strategy=estrategia, dimensions=dims, chunk_count=len(ordem),
        model_config_sha256=manifesto_base.get('model_config_sha256'), base_dataset_id=base,
        base_manifest_sha256=json_hash(manifesto_base), atualizacao=ATUALIZACAO,
        fonte_atualizacao=dict(norma='Emenda Constitucional nº 141, de 16/10/2026', url=URL_EC,
                               notas={f'{c} {art}': _sha(n) for _, n, c, art in ALVOS}),
        trechos_substituidos=sorted(por_antigo), trechos_acrescentados=0,
        embeddings_recomputed=f'parcial: {len(novos)} trechos com nota; os demais copiados da base',
        textos_sha256_ordem=hashlib.sha256('\n'.join(t for _, t, _ in ordem).encode()).hexdigest(),
        vetores_sha256_ordem=hashlib.sha256('\n'.join(v for _, _, v in ordem).encode()).hexdigest())
    manifesto['dataset_id'] = dataset_id = json_hash(manifesto)
    existe = conexao.execute('SELECT 1 FROM lex_clt.vector_datasets WHERE dataset_id=%s', (dataset_id,)).fetchone()
    if not existe:
        with conexao.transaction():
            conexao.execute('INSERT INTO lex_clt.vector_datasets (dataset_id, model, strategy, dimensions, chunk_count, manifest) '
                            'VALUES (%s,%s,%s,%s,%s,%s)', (dataset_id, modelo, estrategia, dims, len(ordem),
                                                            json.dumps(manifesto, ensure_ascii=False)))
            conexao.execute(
                'INSERT INTO lex_clt.chunk_embeddings (dataset_id, chunk_id, row_index, article_id, source_path, text_content, '
                'text_sha256, vector_sha256, metadata, embedding) '
                'SELECT %s, chunk_id, row_index, article_id, source_path, text_content, text_sha256, vector_sha256, metadata, embedding '
                'FROM lex_clt.chunk_embeddings WHERE dataset_id=%s AND NOT (chunk_id = ANY(%s))',
                (dataset_id, base, list(por_antigo)))
            for n in novos:
                conexao.execute(
                    'INSERT INTO lex_clt.chunk_embeddings (dataset_id, chunk_id, row_index, article_id, source_path, text_content, '
                    'text_sha256, vector_sha256, metadata, embedding) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                    (dataset_id, n['chunk_id'], n['row_index'], n['article_id'], n['source_path'], n['text_content'],
                     n['text_sha256'], n['vector_sha256'], json.dumps(n['metadata'], ensure_ascii=False), n['embedding']))
    # conferência no banco
    gravado = conexao.execute('SELECT text_sha256, vector_sha256, text_content FROM lex_clt.chunk_embeddings '
                              'WHERE dataset_id=%s ORDER BY row_index', (dataset_id,)).fetchall()
    erros = []
    if hashlib.sha256('\n'.join(t for t, _, _ in gravado).encode()).hexdigest() != manifesto['textos_sha256_ordem']:
        erros.append('hash dos textos')
    if hashlib.sha256('\n'.join(v for _, v, _ in gravado).encode()).hexdigest() != manifesto['vetores_sha256_ordem']:
        erros.append('hash dos vetores')
    # cada nota aparece em exatamente um trecho da versão (a base pode ter outras notas)
    if any(sum(nota in t for _, _, t in gravado) != 1 for _, nota, _, _ in ALVOS):
        erros.append('notas ausentes ou repetidas')
    if erros:
        raise SystemExit(f'{estrategia}: falha na conferência: {erros}')
    return dict(dataset_id=dataset_id, base_dataset_id=base, trechos=len(gravado), ja_existia=bool(existe),
                com_nota=[dict(artigo=n['artigo'], chunk_antigo=n['substitui'], chunk_novo=n['chunk_id']) for n in novos],
                textos_sha256_ordem=manifesto['textos_sha256_ordem'], vetores_sha256_ordem=manifesto['vetores_sha256_ordem'])


def main():
    import psycopg
    from sentence_transformers import SentenceTransformer
    from src.integracao.recuperacao import MODELO, REVISAO, VERSOES_LEGISLACAO

    conexao = psycopg.connect(load_database_url(ROOT / '.env.pgvector.local'), autocommit=True)
    encoder = SentenceTransformer(MODELO, revision=REVISAO, device='cpu', local_files_only=True)
    encoder.max_seq_length = 8192
    d, a = VERSOES_LEGISLACAO[BASE_VERSAO]
    relatorio = dict(atualizacao=ATUALIZACAO, versao_base=BASE_VERSAO,
                     notas={'LC 150/2015, art. 2º': NOTA_LC150_ART2, 'Lei 605/1949, art. 1º': NOTA_LEI605_ART1,
                            'LC 150/2015, art. 16': NOTA_LC150_ART16, 'CLT, art. 67': NOTA_CLT_ART67,
                            'CLT, art. 385': NOTA_CLT_ART385}, versoes={})
    for estrategia, base in (('D_paragrafo_completo', d), ('A_artigo', a)):
        r = criar_versao(conexao, encoder, estrategia, base)
        print(('já existia: ' if r['ja_existia'] else 'criada: ') + f"{estrategia} {r['dataset_id']} ({r['trechos']} trechos)")
        relatorio['versoes'][estrategia] = r
    RELATORIO.parent.mkdir(parents=True, exist_ok=True)
    RELATORIO.write_text(json.dumps(relatorio, indent=2, ensure_ascii=False), encoding='utf-8')
    print('relatório:', RELATORIO.relative_to(ROOT))


if __name__ == '__main__':
    main()
