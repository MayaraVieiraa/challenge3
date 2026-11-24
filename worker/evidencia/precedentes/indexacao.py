"""Embeddings e indexação da base de precedentes no PostgreSQL/pgvector (schema lex_precedentes).

Mesmo padrão das outras bases: BGE-M3 na mesma revisão da busca, vetores normalizados (cosseno), dataset
identificado pelo hash do manifesto, importação numa transação e estado 'validado' só depois da conferência.
Tabelas:
  datasets   - uma linha por versão (manifesto, estado: em_andamento | validado | substituido)
  embeddings - um trecho por linha (texto, hashes, metadados e vetor)
  registros  - o registro inteiro (súmula, OJ ou tema), que é a unidade entregue ao modelo
Busca exata (sem índice aproximado): com ~1,3 mil vetores, a varredura completa é rápida e não perde resultados.
"""
import hashlib
import json

import numpy as np

DDL = """
CREATE SCHEMA IF NOT EXISTS lex_precedentes;
CREATE TABLE IF NOT EXISTS lex_precedentes.datasets(
 dataset_id text PRIMARY KEY, chunks_esperados bigint NOT NULL, registros_esperados bigint NOT NULL,
 manifesto jsonb NOT NULL, estado text NOT NULL DEFAULT 'em_andamento', atualizado_em timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS lex_precedentes.embeddings(
 dataset_id text NOT NULL REFERENCES lex_precedentes.datasets(dataset_id),
 chunk_id text NOT NULL, registro_id text NOT NULL, row_index integer NOT NULL, texto text NOT NULL,
 texto_sha256 text NOT NULL, vetor_sha256 text NOT NULL, metadata jsonb NOT NULL, embedding vector(1024) NOT NULL,
 PRIMARY KEY(dataset_id, chunk_id), UNIQUE(dataset_id, row_index));
CREATE INDEX IF NOT EXISTS embeddings_registro_idx ON lex_precedentes.embeddings(dataset_id, registro_id);
CREATE TABLE IF NOT EXISTS lex_precedentes.registros(
 dataset_id text NOT NULL REFERENCES lex_precedentes.datasets(dataset_id),
 registro_id text NOT NULL, dados jsonb NOT NULL, PRIMARY KEY(dataset_id, registro_id));
"""


def _sha_bytes(b):
    return hashlib.sha256(b).hexdigest()


def vetor_sha256(v):
    return _sha_bytes(np.ascontiguousarray(v, dtype='<f4').tobytes())


def vetorizar(trechos, encoder, cache=None, lote=32):
    """Vetores normalizados (float32) na ordem dos trechos. Usa o cache .npy se ele corresponder aos mesmos textos."""
    chave = _sha_bytes('\n'.join(t['texto_sha256'] for t in trechos).encode())
    if cache is not None and cache.exists() and cache.with_suffix('.json').exists():
        meta = json.loads(cache.with_suffix('.json').read_text(encoding='utf-8'))
        if meta.get('textos_sha256') == chave:
            return np.load(cache), True
    vetores = encoder.encode([t['texto'] for t in trechos], batch_size=lote, normalize_embeddings=True,
                             convert_to_numpy=True, show_progress_bar=False).astype(np.float32)
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        np.save(cache, vetores)
        cache.with_suffix('.json').write_text(json.dumps(dict(textos_sha256=chave, n=len(trechos))), encoding='utf-8')
    return vetores, False


def manifesto(trechos, vetores, registros, modelo, revisao, chunks_sha256, registros_sha256, limite_tokens):
    from worker.evidencia.indices.pgvector_store import json_hash
    m = dict(base='lex_precedentes', esquema=1, modelo=modelo, revisao=revisao, dimensoes=int(vetores.shape[1]),
             normalizado=True, limite_tokens=limite_tokens, chunks=len(trechos), registros=len(registros),
             chunks_jsonl_sha256=chunks_sha256, registros_jsonl_sha256=registros_sha256,
             textos_sha256_ordem=_sha_bytes('\n'.join(t['texto_sha256'] for t in trechos).encode()),
             vetores_sha256_ordem=_sha_bytes('\n'.join(vetor_sha256(v) for v in vetores).encode()))
    m['dataset_id'] = json_hash(m)
    return m


def importar(conexao, trechos, vetores, registros, manifesto_):
    """Grava a versão (se ainda não existir), confere e marca como validada. Devolve (dataset_id, já_existia)."""
    from pgvector.psycopg import register_vector
    register_vector(conexao)
    conexao.execute(DDL)
    ds = manifesto_['dataset_id']
    linha = conexao.execute('SELECT estado FROM lex_precedentes.datasets WHERE dataset_id=%s', (ds,)).fetchone()
    if linha and linha[0] == 'validado':
        return ds, True
    with conexao.transaction():
        if linha:  # tentativa anterior incompleta: recomeça do zero
            conexao.execute('DELETE FROM lex_precedentes.embeddings WHERE dataset_id=%s', (ds,))
            conexao.execute('DELETE FROM lex_precedentes.registros WHERE dataset_id=%s', (ds,))
            conexao.execute('DELETE FROM lex_precedentes.datasets WHERE dataset_id=%s', (ds,))
        conexao.execute('INSERT INTO lex_precedentes.datasets (dataset_id, chunks_esperados, registros_esperados, manifesto) '
                        'VALUES (%s,%s,%s,%s)', (ds, len(trechos), len(registros), json.dumps(manifesto_, ensure_ascii=False)))
        with conexao.cursor() as cur:
            cur.executemany(
                'INSERT INTO lex_precedentes.embeddings (dataset_id, chunk_id, registro_id, row_index, texto, texto_sha256, '
                'vetor_sha256, metadata, embedding) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                [(ds, t['chunk_id'], t['registro_id'], i, t['texto'], t['texto_sha256'], vetor_sha256(v),
                  json.dumps({k: t[k] for k in t if k not in ('texto', 'chunk_id', 'registro_id', 'texto_sha256')},
                             ensure_ascii=False), v) for i, (t, v) in enumerate(zip(trechos, vetores))])
            cur.executemany('INSERT INTO lex_precedentes.registros (dataset_id, registro_id, dados) VALUES (%s,%s,%s)',
                            [(ds, r['id'], json.dumps(r, ensure_ascii=False)) for r in registros])
    erros = verificar(conexao, manifesto_)
    if erros:
        raise ValueError(f'conferência falhou; dataset continua em_andamento: {erros}')
    with conexao.transaction():
        conexao.execute("UPDATE lex_precedentes.datasets SET estado='substituido', atualizado_em=now() "
                        "WHERE estado='validado' AND dataset_id<>%s", (ds,))
        conexao.execute("UPDATE lex_precedentes.datasets SET estado='validado', atualizado_em=now() WHERE dataset_id=%s", (ds,))
    return ds, False


def verificar(conexao, manifesto_):
    """Relê do banco: contagens, hash dos textos e dos vetores na ordem (o vetor é relido e o hash recalculado)."""
    ds = manifesto_['dataset_id']
    linhas = conexao.execute('SELECT texto, texto_sha256, vetor_sha256, embedding FROM lex_precedentes.embeddings '
                             'WHERE dataset_id=%s ORDER BY row_index', (ds,)).fetchall()
    erros = []
    if len(linhas) != manifesto_['chunks']:
        erros.append(f'trechos: {len(linhas)} != {manifesto_["chunks"]}')
    if any(_sha_bytes(t.encode()) != ts for t, ts, _, _ in linhas):
        erros.append('texto_sha256 diferente do texto')
    relidos = [vetor_sha256(np.asarray(e.to_numpy() if hasattr(e, 'to_numpy') else e, dtype=np.float32)) for *_, e in linhas]
    if any(r != vs for r, (_, _, vs, _) in zip(relidos, linhas)):
        erros.append('vetor relido não confere com vetor_sha256')
    if _sha_bytes('\n'.join(ts for _, ts, _, _ in linhas).encode()) != manifesto_['textos_sha256_ordem']:
        erros.append('hash dos textos na ordem')
    if _sha_bytes('\n'.join(relidos).encode()) != manifesto_['vetores_sha256_ordem']:
        erros.append('hash dos vetores na ordem')
    n_reg = conexao.execute('SELECT count(*) FROM lex_precedentes.registros WHERE dataset_id=%s', (ds,)).fetchone()[0]
    if n_reg != manifesto_['registros']:
        erros.append(f'registros: {n_reg} != {manifesto_["registros"]}')
    return erros


DDL_LEXICO = """
CREATE TABLE IF NOT EXISTS lex_precedentes.lexico(
 dataset_id text NOT NULL REFERENCES lex_precedentes.datasets(dataset_id),
 chunk_id text NOT NULL, registro_id text NOT NULL, normalizacao text NOT NULL, texto_normalizado text NOT NULL,
 tsv tsvector NOT NULL, PRIMARY KEY(dataset_id, chunk_id));
CREATE INDEX IF NOT EXISTS lexico_tsv ON lex_precedentes.lexico USING GIN (tsv);
"""


def preparar_lexico(conexao, dataset_id):
    """Índice para a busca por palavras: texto normalizado (worker/evidencia/precedentes/normalizacao.py) e configuração sem
    stopwords. O texto guardado em `embeddings` não muda. Refeito se a versão da normalização mudar."""
    from worker.evidencia.precedentes import normalizacao as nz
    if conexao.execute("SELECT relkind FROM pg_class WHERE oid = to_regclass('lex_precedentes.lexico')").fetchone() == ('m',):
        conexao.execute('DROP MATERIALIZED VIEW lex_precedentes.lexico')  # versão anterior: visão sem normalização
    conexao.execute(nz.DDL_CONFIG)
    conexao.execute(DDL_LEXICO)
    feitos = conexao.execute('SELECT count(*) FROM lex_precedentes.lexico WHERE dataset_id=%s AND normalizacao=%s',
                             (dataset_id, nz.VERSAO)).fetchone()[0]
    total = conexao.execute('SELECT count(*) FROM lex_precedentes.embeddings WHERE dataset_id=%s', (dataset_id,)).fetchone()[0]
    if feitos == total:
        return total
    linhas = conexao.execute('SELECT chunk_id, registro_id, texto FROM lex_precedentes.embeddings WHERE dataset_id=%s',
                             (dataset_id,)).fetchall()
    with conexao.transaction():
        conexao.execute('DELETE FROM lex_precedentes.lexico WHERE dataset_id=%s', (dataset_id,))
        with conexao.cursor() as cur:
            cur.executemany(
                'INSERT INTO lex_precedentes.lexico (dataset_id, chunk_id, registro_id, normalizacao, texto_normalizado, tsv) '
                f'VALUES (%s,%s,%s,%s,%s, to_tsvector(%s::regconfig, %s))',
                [(dataset_id, c, r, nz.VERSAO, nz.normalizar(t), nz.CONFIG, nz.normalizar(t)) for c, r, t in linhas])
    return conexao.execute('SELECT count(*) FROM lex_precedentes.lexico WHERE dataset_id=%s', (dataset_id,)).fetchone()[0]


def busca_lexical(conexao, dataset_id, pergunta, k=10):
    """[(registro_id, chunk_id, escore)] pelas palavras da pergunta, normalizada da mesma forma.

    Sem stopwords: nenhuma palavra é descartada. Cada palavra pesa pelo IDF (fórmula do BM25): palavras presentes
    em quase todos os trechos ("de", "do") pesam perto de zero e as raras ("338", "insalubridade") pesam muito.
    O escore é a soma dos pesos das palavras presentes no trecho; empate desfeito por ts_rank_cd."""
    import math
    from worker.evidencia.precedentes import normalizacao as nz
    lexemas = conexao.execute('SELECT tsvector_to_array(to_tsvector(%s::regconfig, %s))',
                              (nz.CONFIG, nz.normalizar(pergunta))).fetchone()[0] or []
    if not lexemas:
        return []
    citar = lambda l: "'" + l.replace("'", "''") + "'"  # entre aspas: "$" e "/" não quebram a consulta
    total = conexao.execute('SELECT count(*) FROM lex_precedentes.lexico WHERE dataset_id=%s', (dataset_id,)).fetchone()[0]
    pesos = {}
    for l in lexemas:
        df = conexao.execute('SELECT count(*) FROM lex_precedentes.lexico WHERE dataset_id=%s AND tsv @@ to_tsquery(%s::regconfig, %s)',
                             (dataset_id, nz.CONFIG, citar(l))).fetchone()[0]
        if df:
            pesos[l] = math.log((total - df + 0.5) / (df + 0.5) + 1)
    if not pesos:
        return []
    soma = ' + '.join(f'(CASE WHEN tsv @@ to_tsquery(%s::regconfig, %s) THEN {p:.6f} ELSE 0 END)' for p in pesos.values())
    parametros = [x for l in pesos for x in (nz.CONFIG, citar(l))]
    return conexao.execute(
        f'SELECT registro_id, chunk_id, ({soma}) AS escore FROM lex_precedentes.lexico, to_tsquery(%s::regconfig, %s) q '
        'WHERE dataset_id=%s AND tsv @@ q ORDER BY escore DESC, ts_rank_cd(tsv, q) DESC, chunk_id LIMIT %s',
        (*parametros, nz.CONFIG, ' | '.join(citar(l) for l in pesos), dataset_id, k)).fetchall()


def busca_semantica(conexao, dataset_id, vetor, k=10):
    """[(registro_id, chunk_id, semelhança)] dos k trechos mais próximos."""
    return conexao.execute(
        'SELECT registro_id, chunk_id, 1 - (embedding <=> %s) FROM lex_precedentes.embeddings WHERE dataset_id=%s '
        'ORDER BY embedding <=> %s, chunk_id LIMIT %s', (vetor, dataset_id, vetor, k)).fetchall()
