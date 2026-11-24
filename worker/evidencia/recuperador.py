"""Recuperação conjunta de legislação e jurisprudência no mesmo banco PostgreSQL/pgvector.

Fluxo por pergunta:
  1. Para cada fonte, busca semântica (BGE-M3, cosseno no pgvector) e busca lexical (full-text search do
     PostgreSQL, configuração 'portuguese'), fundidas por RRF (k=60).
  2. As listas das duas fontes são combinadas com uma cota de candidatos por fonte e, opcionalmente,
     reordenadas pelo cross-encoder bge-reranker-v2-m3 (o mesmo do notebook 06 de legislação).
  3. Entrega: na legislação, o artigo completo (estratégia A) do chunk de parágrafo encontrado (D → A);
     na jurisprudência, o trecho da decisão com tribunal, processo, órgão julgador e data. Resultados
     repetidos do mesmo artigo ou da mesma decisão são agrupados.

A busca lexical usa visões materializadas no schema próprio `lex_integracao`, com índices GIN; as tabelas
de legislação (`lex_clt`) e de jurisprudência (`lex_jurisprudencia`) não são alteradas.

Terceira fonte (opcional): precedentes do TST (súmulas, OJs e temas), schema `lex_precedentes` (notebooks
05_docs_precedentes). Entra só quando a configuração pede (`configuracao_com_precedentes()`), para não mudar os
resultados já medidos com duas fontes. Na fonte de precedentes, a busca por palavras usa o índice normalizado e sem
stopwords da própria base, o reranker recebe a UNIÃO dos primeiros de cada busca (a fusão RRF sozinha perdia a
Súmula 60, notebook 06 de precedentes) e o modelo recebe o registro inteiro, com nome de citação, situação e alerta.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import json
import os
import time

import numpy as np

# Versões da base de legislação (D_paragrafo_completo, A_artigo). As antigas continuam no banco para reproduzir os
# notebooks publicados antes da atualização; a busca usa VERSAO_LEGISLACAO, salvo pedido explícito.
VERSOES_LEGISLACAO = {
    'original': ('036e49f3a30a99ea706fce9be2f8301aabf5817c81e9f700535753b046657313',
                 '508abda2246b7cc1db28bd9b0bf762bddfb2a5696f6681ec22e99b60108876f9'),
    # EC 141/2026: art. 7º da CF (jornada de 40 h progressiva e dois dias de repouso) + os 10 artigos da emenda.
    # avaliacao/scripts/atualizar_legislacao_ec141.py; dados/relatorios/legislacao/atualizacoes/ec_141_2026.json
    'ec141_2026': ('2f1ab3f092e990cdf549adb0e825381dffd66aa0f5b1f7b3c4d557c3b2015299',
                   '4cbd00716aff870627506f32993a01c8e9300915a7d6b2bf2b07f0456a793bcb'),
    # ec141_2026 + notas de vigência: LC 150/2015 arts. 2º (44 h) e 16, Lei 605/1949 art. 1º e CLT arts. 67 e 385 (repouso de 24 h).
    # avaliacao/scripts/atualizar_legislacao_notas_ec141.py; dados/relatorios/legislacao/atualizacoes/ec_141_2026_notas.json
    'ec141_2026_notas': ('dca7b51d5efa82bb000a427de92bd92aab4d162f9a7881a4d0ff9cad948692e5',
                         'd61d07a50919f1f423b26726d22085519b17fb1429f858bbef12dd969179c62d'),
    # ec141_2026_notas + nota no divisor 220 da LC 150/2015, art. 2º, § 2º (opção B, 2026-11-23). Usada a partir da v3.3.
    # avaliacao/scripts/atualizar_legislacao_nota_divisor_lc150.py; dados/relatorios/legislacao/atualizacoes/lc150_divisor_220_nota.json
    'ec141_2026_notas_divisor': ('96d0710a21cdf06ceb29a839cd295a1ba09a38b70a413477d57b108621cd4346',
                                 'fbb9073502063f5c3866e9343c0abf519d157afe822342fd11acc3957d6acb40'),
}
VERSAO_LEGISLACAO = 'ec141_2026_notas_divisor'
LEGISLACAO_D, LEGISLACAO_A = VERSOES_LEGISLACAO[VERSAO_LEGISLACAO]  # D_paragrafo_completo, A_artigo
MODELO = 'BAAI/bge-m3'
REVISAO = '5617a9f61b028005a4858fdac845db406aefb181'
RERANKER = 'BAAI/bge-reranker-v2-m3'
RRF_K = 60
FONTES = ('legislacao', 'jurisprudencia')
FONTES_COM_PRECEDENTES = ('legislacao', 'jurisprudencia', 'precedentes')

DDL_LEXICO = """
CREATE SCHEMA IF NOT EXISTS lex_integracao;
CREATE MATERIALIZED VIEW IF NOT EXISTS lex_integracao.lexico_legislacao AS
  SELECT chunk_id, article_id, to_tsvector('portuguese', text_content) AS tsv
  FROM lex_clt.chunk_embeddings WHERE dataset_id = %(d)s;
CREATE INDEX IF NOT EXISTS lexico_legislacao_tsv ON lex_integracao.lexico_legislacao USING GIN (tsv);
CREATE UNIQUE INDEX IF NOT EXISTS lexico_legislacao_id ON lex_integracao.lexico_legislacao (chunk_id);
CREATE MATERIALIZED VIEW IF NOT EXISTS lex_integracao.lexico_jurisprudencia AS
  SELECT chunk_id, registro_id, to_tsvector('portuguese', texto) AS tsv
  FROM lex_jurisprudencia.embeddings WHERE dataset_id = %(j)s;
CREATE INDEX IF NOT EXISTS lexico_jurisprudencia_tsv ON lex_integracao.lexico_jurisprudencia USING GIN (tsv);
CREATE UNIQUE INDEX IF NOT EXISTS lexico_jurisprudencia_id ON lex_integracao.lexico_jurisprudencia (chunk_id);
"""


def rrf(rankings, k=RRF_K):
    """Reciprocal Rank Fusion: soma 1/(k+posição) de cada lista; não depende da escala dos escores."""
    escores = {}
    for ranking in rankings:
        for posicao, ident in enumerate(ranking, 1):
            escores[ident] = escores.get(ident, 0.0) + 1.0 / (k + posicao)
    return sorted(escores, key=lambda i: (-escores[i], i)), escores


@dataclass
class Configuracao:
    """Configuração da busca. Padrão (desde 2026-11-23): as 3 bases, com 3 artigos, 3 decisões e 3 precedentes.

    Para reproduzir as medições feitas com 2 bases (notebooks 01 a 06 da integração, gerações v1 a v3.1), use
    `configuracao_duas_bases()`, que devolve os padrões anteriores."""
    fontes: tuple = FONTES_COM_PRECEDENTES
    candidatos_por_busca: int = 50       # por fonte, em cada busca (semântica e lexical)
    cota_por_fonte: int = 10             # candidatos de cada fonte enviados à combinação (notebook 01, seção 9)
    usar_lexical: bool = True
    usar_semantica: bool = True
    usar_reranker: bool = True
    top_k: int = 10                      # unidades entregues sem cotas (antes de 2026-11-23: 5)
    # Cotas de entrega por fonte. Com cotas, cada fonte mantém o próprio ranking e reserva suas posições; sem cotas
    # (None), uma única lista combinada é cortada em top_k.
    entrega_por_fonte: dict | None = field(default_factory=lambda: {'legislacao': 3, 'jurisprudencia': 3, 'precedentes': 3})
    reranker_max_length: int | None = 256    # tokens lidos por par pergunta–trecho (None = valor do carregamento)
    lexical_modo: str = 'idf'            # 'idf', 'ts_rank' ou 'ts_rank_cd' (primeira versão)
    lexical_poda: float = 0.20           # descarta lexemas presentes em mais dessa fração dos chunks (modo idf)
    # Fontes em que o reranker recebe a união dos `cota_por_fonte` primeiros de cada busca (semântica e por palavras),
    # e não os primeiros da fusão RRF. Avaliação de precedentes: a fusão deixava de fora precedente que a semântica
    # punha em 3º.
    uniao_reranker: tuple = ('precedentes',)
    expandir_sinonimos: bool = True      # acrescenta sinônimos jurídicos à pergunta (worker/evidencia/sinonimos.py)
    alerta_lei_posterior: bool = True    # precedente anterior a mudança da lei (False reproduz a geração v3.2)
    extras: dict = field(default_factory=dict)


def configuracao_com_precedentes(**alteracoes):
    """Configuração com a terceira fonte (notebook 06 de precedentes): 3 artigos, 3 decisões e 3 precedentes;
    reranker sobre a união das buscas na fonte de precedentes; sinônimos jurídicos na pergunta. É a padrão desde
    2026-11-23 (igual a `Configuracao(**alteracoes)`); o nome fica para os scripts e notebooks que a usam."""
    return Configuracao(**alteracoes)


def configuracao_duas_bases(**alteracoes):
    """Padrões anteriores a 2026-11-23: legislação e decisões, sem cotas, top_k 5, sem união no reranker e sem
    sinônimos. Reproduz as medições dos notebooks 01 a 06 da integração e as gerações v1 a v3.1."""
    base = dict(fontes=FONTES, top_k=5, entrega_por_fonte=None, uniao_reranker=(), expandir_sinonimos=False)
    base.update(alteracoes)
    return Configuracao(**base)


def selecionar_uniao(semantica, lexical, n, escores):
    """Candidatos da união dos n primeiros de cada lista, na ordem da fusão RRF (escores de `rrf`)."""
    manter = set(semantica[:n]) | set(lexical[:n])
    return sorted(manter, key=lambda c: (-escores.get(c, 0.0), c))


_LEI_POSTERIOR = None


def alerta_lei_posterior(registro_id):
    """Alerta de lei posterior do precedente (worker/evidencia/precedentes_lei_posterior.json, versionado), ou None.

    Súmulas e OJs anteriores a uma mudança da lei sobre o mesmo ponto (Reforma Trabalhista de 2017, EC 141/2026).
    Gerado por avaliacao/scripts/gerar_alertas_lei_posterior_precedentes.py; a lista deve ser confirmada pelo advogado revisor.
    """
    global _LEI_POSTERIOR
    if _LEI_POSTERIOR is None:
        caminho = Path(__file__).with_name('precedentes_lei_posterior.json')
        _LEI_POSTERIOR = json.loads(caminho.read_text(encoding='utf-8'))['precedentes'] if caminho.exists() else {}
    item = _LEI_POSTERIOR.get(registro_id)
    return item['alerta'] if item else None


def texto_precedente(dados, com_lei_posterior=True):
    """Texto entregue ao modelo para um precedente: nome, título, enunciado (sem as notas de origem) e alertas.

    com_lei_posterior=False reproduz o texto da geração v3.2 (antes do alerta de lei posterior)."""
    partes = [f"{dados['nome_citacao']} — {dados['titulo']}", dados.get('texto_busca') or dados.get('texto') or '']
    if dados.get('situacao') == 'afetado_sem_tese':
        partes.append('[Situação: tema afetado, ainda sem tese fixada pelo TST.]')
    if dados.get('alerta_vigencia'):
        partes.append(f"[Alerta de vigência: {dados['alerta_vigencia']}]")
    posterior = alerta_lei_posterior(dados.get('id')) if com_lei_posterior else None
    if posterior:
        partes.append(f'[Alerta de lei posterior: {posterior}]')
    return '\n'.join(p for p in partes if p)


class Recuperador:
    def __init__(self, database_url, device='cpu', carregar_reranker=True, reranker_max_length=512,
                 versao_legislacao=VERSAO_LEGISLACAO):
        os.environ.setdefault('HF_HUB_OFFLINE', '1')
        os.environ.setdefault('TRANSFORMERS_OFFLINE', '1')
        import psycopg
        from pgvector.psycopg import register_vector
        from sentence_transformers import SentenceTransformer
        self.conexao = psycopg.connect(database_url, connect_timeout=10, autocommit=True)
        register_vector(self.conexao)
        self.versao_legislacao = versao_legislacao
        self.legislacao_d, self.legislacao_a = VERSOES_LEGISLACAO[versao_legislacao]
        self.dataset_jurisprudencia = self._dataset_jurisprudencia()
        self._dataset_prec = None   # carregado só quando a configuração pede a fonte de precedentes
        self._df = {}   # frequência de documentos por (fonte, lexema), usada no IDF da busca lexical
        self.encoder = SentenceTransformer(MODELO, revision=REVISAO, device=device, local_files_only=True)
        self.encoder.max_seq_length = 8192
        self.reranker = None
        if carregar_reranker:
            from sentence_transformers import CrossEncoder
            self.reranker = CrossEncoder(RERANKER, max_length=reranker_max_length, device=device, local_files_only=True)
            self._max_length_original = self.reranker.max_length
        if self._lexico_legislacao_de_outra_versao():
            self.preparar_lexico()

    def _lexico_legislacao_de_outra_versao(self):
        """True se a visão lexical da legislação existe mas foi criada para outra versão (o comentário guarda o ID)."""
        if not self.conexao.execute("SELECT to_regclass('lex_integracao.lexico_legislacao')").fetchone()[0]:
            return False
        comentario = self.conexao.execute(
            "SELECT obj_description('lex_integracao.lexico_legislacao'::regclass, 'pg_class')").fetchone()[0]
        return comentario != self.legislacao_d

    # --- preparação -------------------------------------------------------------------------------------
    def _dataset_jurisprudencia(self):
        linhas = self.conexao.execute(
            "SELECT dataset_id FROM lex_jurisprudencia.datasets WHERE estado='validado'").fetchall()
        if len(linhas) != 1:
            raise ValueError(f'Esperado um dataset de jurisprudência validado; encontrados {len(linhas)}.')
        return linhas[0][0]

    def preparar_lexico(self):
        """Cria (uma vez) as visões materializadas e os índices GIN da busca lexical."""
        import re
        ids = dict(d=self.legislacao_d, j=self.dataset_jurisprudencia)
        if not all(re.fullmatch(r'[0-9a-f]{64}', v) for v in ids.values()):
            raise ValueError('Identificador de dataset inválido.')
        # A visão lexical da legislação é de uma versão só: se foi criada para outra, é recriada para a atual.
        if self._lexico_legislacao_de_outra_versao():
            self.conexao.execute('DROP MATERIALIZED VIEW lex_integracao.lexico_legislacao')
        # DDL não aceita parâmetros: os IDs, já validados como hexadecimais, entram como literais.
        for comando in filter(str.strip, DDL_LEXICO.split(';')):
            self.conexao.execute(comando.replace('%(d)s', f"'{ids['d']}'").replace('%(j)s', f"'{ids['j']}'"))
        self.conexao.execute(f"COMMENT ON MATERIALIZED VIEW lex_integracao.lexico_legislacao IS '{ids['d']}'")
        self._df.clear()
        contagens = {}
        for fonte in FONTES:
            contagens[fonte] = self.conexao.execute(f'SELECT count(*) FROM lex_integracao.lexico_{fonte}').fetchone()[0]
        return contagens

    # --- buscas por fonte -------------------------------------------------------------------------------
    def vetor(self, pergunta):
        v = self.encoder.encode([pergunta], normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False)[0]
        return np.asarray(v, dtype=np.float32)

    def semantica(self, fonte, vetor, k):
        if fonte == 'legislacao':
            sql = ('SELECT chunk_id FROM lex_clt.chunk_embeddings WHERE dataset_id=%s '
                   'ORDER BY embedding <=> %s, row_index LIMIT %s')
            parametros = (self.legislacao_d, vetor, k)
        elif fonte == 'precedentes':
            sql = ('SELECT chunk_id FROM lex_precedentes.embeddings WHERE dataset_id=%s '
                   'ORDER BY embedding <=> %s, chunk_id LIMIT %s')
            parametros = (self.dataset_precedentes, vetor, k)
        else:
            sql = ('SELECT chunk_id FROM lex_jurisprudencia.embeddings WHERE dataset_id=%s '
                   'ORDER BY embedding <=> %s, chunk_id LIMIT %s')
            parametros = (self.dataset_jurisprudencia, vetor, k)
        return [r[0] for r in self.conexao.execute(sql, parametros).fetchall()]

    @property
    def dataset_precedentes(self):
        """Versão validada de `lex_precedentes` (e índice de palavras pronto), carregada na primeira consulta."""
        if self._dataset_prec is None:
            from worker.evidencia.precedentes import indexacao as ix
            linhas = self.conexao.execute("SELECT dataset_id FROM lex_precedentes.datasets WHERE estado='validado'").fetchall()
            if len(linhas) != 1:
                raise ValueError(f'Esperado um dataset de precedentes validado; encontrados {len(linhas)}.')
            self._dataset_prec = linhas[0][0]
            ix.preparar_lexico(self.conexao, self._dataset_prec)
        return self._dataset_prec

    def _frequencia(self, fonte, lexema):
        """Número de chunks da fonte que contêm o lexema; lexema=None dá o total de chunks (cache em memória)."""
        chave = (fonte, lexema)
        if chave not in self._df:
            sql = f'SELECT count(*) FROM lex_integracao.lexico_{fonte}'
            if lexema is None:
                self._df[chave] = self.conexao.execute(sql).fetchone()[0]
            else:
                self._df[chave] = self.conexao.execute(
                    sql + " WHERE tsv @@ to_tsquery('portuguese', %s)", (lexema,)).fetchone()[0]
        return self._df[chave]

    def lexical(self, fonte, pergunta, k, modo='idf', poda=0.20):
        """Busca lexical com os lexemas da pergunta (sem stopwords) combinados com OU.

        modo='idf': ordena pela soma dos pesos IDF (fórmula do BM25) dos lexemas presentes no chunk; lexemas que
        aparecem em mais de `poda` dos chunks são descartados (equivalem a stopwords do domínio, como "trabalho").
        modo='ts_rank' ou 'ts_rank_cd': ordenação nativa do PostgreSQL, sem IDF. ts_rank_cd foi a primeira versão
        e é a pior: favorece chunks curtos com termos genéricos (ver notebook 01, seção 10).
        """
        import math
        if fonte == 'precedentes':
            # índice próprio: texto normalizado, sem stopwords e com peso IDF (worker/evidencia/precedentes/normalizacao.py)
            from worker.evidencia.precedentes import indexacao as ix
            return [c for _, c, _ in ix.busca_lexical(self.conexao, self.dataset_precedentes, pergunta, k)]
        lexemas = self.conexao.execute(
            "SELECT tsvector_to_array(to_tsvector('portuguese', %s))", (pergunta,)).fetchone()[0] or []
        if modo == 'idf':
            total = self._frequencia(fonte, None)
            presentes = [l for l in lexemas if self._frequencia(fonte, l)]
            lexemas = [l for l in presentes if self._frequencia(fonte, l) / total <= poda] or presentes
        if not lexemas:
            return []
        consulta = ' | '.join(lexemas)
        if modo == 'idf':
            pesos = [math.log((total - self._frequencia(fonte, l) + 0.5) / (self._frequencia(fonte, l) + 0.5) + 1)
                     for l in lexemas]
            soma = ' + '.join(f"(CASE WHEN tsv @@ to_tsquery('portuguese', %s) THEN {p:.6f} ELSE 0 END)" for p in pesos)
            sql = (f"SELECT chunk_id FROM lex_integracao.lexico_{fonte}, to_tsquery('portuguese', %s) q WHERE tsv @@ q "
                   f'ORDER BY ({soma}) DESC, ts_rank_cd(tsv, q, 32) DESC, chunk_id LIMIT %s')
            parametros = (consulta, *lexemas, k)
        elif modo in ('ts_rank', 'ts_rank_cd'):
            sql = (f"SELECT chunk_id FROM lex_integracao.lexico_{fonte}, to_tsquery('portuguese', %s) q "
                   f'WHERE tsv @@ q ORDER BY {modo}(tsv, q) DESC, chunk_id LIMIT %s')
            parametros = (consulta, k)
        else:
            raise ValueError(f'Modo lexical desconhecido: {modo}')
        return [r[0] for r in self.conexao.execute(sql, parametros).fetchall()]

    def buscar_fonte(self, fonte, pergunta, config, vetor=None):
        listas = []
        if config.usar_semantica:
            listas.append(self.semantica(fonte, vetor if vetor is not None else self.vetor(pergunta), config.candidatos_por_busca))
        if config.usar_lexical:
            listas.append(self.lexical(fonte, pergunta, config.candidatos_por_busca, config.lexical_modo, config.lexical_poda))
        ordem, escores = rrf(listas)
        return [dict(fonte=fonte, chunk_id=c, rrf=escores[c]) for c in ordem]

    def candidatos_fonte(self, fonte, pergunta, config, vetor=None):
        """Candidatos de uma fonte para o reranker: os primeiros da fusão RRF ou, nas fontes de `uniao_reranker`,
        a união dos primeiros de cada busca (semântica e por palavras)."""
        if fonte not in config.uniao_reranker:
            return self.buscar_fonte(fonte, pergunta, config, vetor)[:config.cota_por_fonte]
        sem = self.semantica(fonte, vetor if vetor is not None else self.vetor(pergunta), config.candidatos_por_busca) \
            if config.usar_semantica else []
        lex = self.lexical(fonte, pergunta, config.candidatos_por_busca, config.lexical_modo, config.lexical_poda) \
            if config.usar_lexical else []
        _, escores = rrf([l for l in (sem, lex) if l])
        return [dict(fonte=fonte, chunk_id=c, rrf=escores[c]) for c in selecionar_uniao(sem, lex, config.cota_por_fonte, escores)]

    # --- conteúdo e entrega -----------------------------------------------------------------------------
    def conteudo(self, candidatos):
        por_fonte = {f: [c['chunk_id'] for c in candidatos if c['fonte'] == f] for f in FONTES_COM_PRECEDENTES}
        dados = {}
        if por_fonte['legislacao']:
            for cid, art, texto, meta in self.conexao.execute(
                    'SELECT chunk_id, article_id, text_content, metadata FROM lex_clt.chunk_embeddings '
                    'WHERE dataset_id=%s AND chunk_id = ANY(%s)', (self.legislacao_d, por_fonte['legislacao'])).fetchall():
                dados[('legislacao', cid)] = dict(texto=texto, unidade=art, metadata=meta)
        if por_fonte['jurisprudencia']:
            for cid, reg, texto, meta in self.conexao.execute(
                    'SELECT chunk_id, registro_id, texto, metadata FROM lex_jurisprudencia.embeddings '
                    'WHERE dataset_id=%s AND chunk_id = ANY(%s)', (self.dataset_jurisprudencia, por_fonte['jurisprudencia'])).fetchall():
                dados[('jurisprudencia', cid)] = dict(texto=texto, unidade=reg, metadata=meta)
        if por_fonte['precedentes']:
            for cid, reg, texto, meta in self.conexao.execute(
                    'SELECT chunk_id, registro_id, texto, metadata FROM lex_precedentes.embeddings '
                    'WHERE dataset_id=%s AND chunk_id = ANY(%s)', (self.dataset_precedentes, por_fonte['precedentes'])).fetchall():
                dados[('precedentes', cid)] = dict(texto=texto, unidade=reg, metadata=meta)
        return [dict(c, **dados[(c['fonte'], c['chunk_id'])]) for c in candidatos]

    def precedentes(self, registro_ids):
        """Registros inteiros dos precedentes (unidade entregue ao modelo)."""
        linhas = self.conexao.execute(
            'SELECT registro_id, dados FROM lex_precedentes.registros WHERE dataset_id=%s AND registro_id = ANY(%s)',
            (self.dataset_precedentes, list(registro_ids))).fetchall()
        return {r: d for r, d in linhas}

    def artigos(self, article_ids):
        linhas = self.conexao.execute(
            'SELECT article_id, text_content, metadata FROM lex_clt.chunk_embeddings WHERE dataset_id=%s AND article_id = ANY(%s)',
            (self.legislacao_a, list(article_ids))).fetchall()
        return {a: dict(texto=t, metadata=m) for a, t, m in linhas}

    def buscar(self, pergunta, config=None):
        """Retorna (unidades entregues, diagnóstico). Unidade = artigo (legislação) ou decisão (jurisprudência)."""
        config = config or Configuracao()
        inicio = time.monotonic()
        if config.expandir_sinonimos:
            from worker.evidencia.sinonimos import expandir
            pergunta = expandir(pergunta)
        vetor = self.vetor(pergunta) if config.usar_semantica else None
        candidatos = []
        for fonte in config.fontes:
            candidatos += self.candidatos_fonte(fonte, pergunta, config, vetor)
        candidatos = self.conteudo(candidatos)
        if config.usar_reranker and self.reranker is not None and candidatos:
            self.reranker.max_length = config.reranker_max_length or self._max_length_original
            escores = self.reranker.predict([(pergunta, c['texto']) for c in candidatos], show_progress_bar=False)
            for c, s in zip(candidatos, escores):
                c['rerank'] = float(s)
            candidatos.sort(key=lambda c: (-c['rerank'], c['chunk_id']))
        else:
            candidatos.sort(key=lambda c: (-c['rrf'], c['fonte'], c['chunk_id']))
        # Agrupa por unidade (artigo ou decisão), mantendo a melhor posição e todos os chunks encontrados.
        unidades, vistas = [], {}
        for posicao, c in enumerate(candidatos, 1):
            chave = (c['fonte'], c['unidade'])
            if chave in vistas:
                vistas[chave]['chunks'].append(c)
                continue
            u = dict(fonte=c['fonte'], unidade=c['unidade'], posicao_chunk=posicao, chunks=[c],
                     escore=c.get('rerank', c['rrf']))
            vistas[chave] = u
            unidades.append(u)
        por_fonte = {f: [u for u in unidades if u['fonte'] == f] for f in config.fontes}
        if config.entrega_por_fonte:
            # Cada fonte entrega suas melhores unidades; a legislação vem antes da jurisprudência no contexto.
            entregues = [u for f in config.fontes for u in por_fonte[f][:config.entrega_por_fonte.get(f, 0)]]
        else:
            entregues = unidades[:config.top_k]
        artigos = self.artigos([u['unidade'] for u in entregues if u['fonte'] == 'legislacao'])
        registros = self.precedentes([u['unidade'] for u in entregues if u['fonte'] == 'precedentes']) \
            if any(u['fonte'] == 'precedentes' for u in entregues) else {}
        for u in entregues:
            if u['fonte'] == 'legislacao':
                a = artigos.get(u['unidade'])
                u['texto'] = a['texto'] if a else u['chunks'][0]['texto']
                u['metadata'] = a['metadata'] if a else u['chunks'][0]['metadata']
            elif u['fonte'] == 'precedentes':
                d = registros[u['unidade']]
                u['texto'] = texto_precedente(d, com_lei_posterior=config.alerta_lei_posterior)
                u['metadata'] = dict(nome_citacao=d['nome_citacao'], tipo=d['tipo'], titulo=d['titulo'],
                                     situacao=d['situacao'], alerta_vigencia=d.get('alerta_vigencia'),
                                     alerta_lei_posterior=alerta_lei_posterior(d.get('id')) if config.alerta_lei_posterior else None,
                                     item_encontrado=(u['chunks'][0].get('metadata') or {}).get('item'),
                                     data_referencia=(d.get('fonte') or {}).get('data_referencia'))
            else:
                u['texto'] = u['chunks'][0]['texto']
                u['metadata'] = u['chunks'][0]['metadata']
        diagnostico = dict(segundos=time.monotonic() - inicio, candidatos=len(candidatos), unidades=len(unidades),
                           pergunta_busca=pergunta,
                           ranking_unidades=[(u['fonte'], u['unidade']) for u in unidades],
                           ranking_por_fonte={f: [(u['fonte'], u['unidade']) for u in lista] for f, lista in por_fonte.items()},
                           com_cotas=bool(config.entrega_por_fonte),
                           candidatos_detalhe=[dict(fonte=c['fonte'], unidade=c['unidade'], metadata=c['metadata'])
                                               for c in candidatos])
        return entregues, diagnostico

    def fechar(self):
        self.conexao.close()
