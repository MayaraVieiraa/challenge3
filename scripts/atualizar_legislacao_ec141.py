"""Atualiza a base de legislação com a Emenda Constitucional nº 141/2026 (jornada de 40 horas e dois dias de repouso).

Não altera os datasets existentes: cria uma NOVA versão de cada um (D_paragrafo_completo e A_artigo) no mesmo banco.
Assim os notebooks já publicados continuam reproduzíveis com os IDs antigos, e a busca passa a usar os novos.

O que muda em cada versão nova:
  D (parágrafos) - o trecho "caput com descendentes" do art. 7º da CF (incisos XIII e XV com a nova redação e nota
                   de vigência); o parágrafo único passa a § 1º; entram os §§ 2º e 3º; entram os 10 artigos da EC 141.
  A (artigos)    - o art. 7º da CF inteiro na nova redação; entram os 10 artigos da EC 141.
Os demais trechos são copiados com o mesmo texto e o mesmo vetor. Só os trechos novos ou alterados recebem
embedding (BGE-M3 na mesma revisão, sobre o texto completo do trecho, como na base original).

Notas de vigência (art. 6º e art. 10 da EC 141/2026; publicação em 16/10/2026):
  - inciso XIII: 44 h até 15/12/2026; no máximo 42 h a partir de 16/12/2026; 40 h a partir de 16/12/2027;
  - inciso XV (dois dias de repouso): a partir de 16/12/2026.

Entrada : data/atualizacoes_legislacao/ec_141_2026/ec_141_2026.md (transcrição versionada da EC)
Saída   : novos datasets em lex_clt.vector_datasets / lex_clt.chunk_embeddings
          reports/legislacao/atualizacoes/ec_141_2026.json (IDs, trechos alterados, hashes)
Uso     : python scripts/atualizar_legislacao_ec141.py [--verificar]   (idempotente: se já existir, só confere)
"""
import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault('HF_HUB_OFFLINE', '1')

from src.storage.pgvector_store import json_hash, load_database_url, sha256_file, vector_hash  # noqa: E402

BASE = {'D_paragrafo_completo': '036e49f3a30a99ea706fce9be2f8301aabf5817c81e9f700535753b046657313',
        'A_artigo': '508abda2246b7cc1db28bd9b0bf762bddfb2a5696f6681ec22e99b60108876f9'}
EC_MD = ROOT / 'data/atualizacoes_legislacao/ec_141_2026/ec_141_2026.md'
EC_PDF = ROOT / 'data/raw/precedentes/nova_lei_escala_de_trabalho.pdf'
RELATORIO = ROOT / 'reports/legislacao/atualizacoes/ec_141_2026.json'
ATUALIZACAO = 'ec_141_2026'
URL_EC = 'https://planalto.gov.br/ccivil_03/constituicao/emendas/emc/emc141.htm'
CAMINHO_EC = 'constituicao/emendas/emc-141-2026.md'
ART7_ID = '99c88f56a8770ab440a7f9755b1c7f97b03720d6832ee0a8687aca46bc622026'
CHUNKS_ALTERADOS = {'D_paragrafo_completo': {'caput': 'ccae4dfa7db984df0f517221aed2690305e403ab696e1b7eb7a53f567d99a384',
                                             'paragrafo_unico': '9ee7ea8640234401d1d792b3f3b300c042c5ceb455a093b95097cb38e1e072f7'},
                    'A_artigo': {'artigo': 'cb1ef7ff56ef03edf10e30c78c2971b2a41e513fa132bfeadb3371db495ed6d2'}}
CONTEXTO_ART7 = ('[constituicao/constituicao-1988.md | TÍTULO II — Dos Direitos e Garantias Fundamentais > '
                 'CAPÍTULO II — DOS DIREITOS SOCIAIS > Art. 7º')

XIII_ANTIGO = ('XIII - duração do trabalho normal não superior a oito horas diárias e quarenta e quatro semanais, facultada a '
               'compensação de horários e a redução da jornada, mediante acordo ou convenção coletiva de trabalho; '
               '(Vide Decreto-Lei nº 5.452, de 1943)')
XIII_NOVO = ('XIII - duração do trabalho normal não superior a 8 (oito) horas diárias e 40 (quarenta) horas semanais, facultada '
             'a compensação de horários e a redução da jornada, mediante acordo ou convenção coletiva de trabalho; '
             '(Redação dada pela Emenda Constitucional nº 141, de 2026) (Vide Decreto-Lei nº 5.452, de 1943) '
             '[Nota de vigência: a redução para 40 horas é progressiva (art. 6º da EC 141/2026): até 15/12/2026, '
             '44 horas semanais; a partir de 16/12/2026, no máximo 42 horas semanais; a partir de 16/12/2027, '
             '40 horas semanais.]')
XV_ANTIGO = 'XV - repouso semanal remunerado, preferencialmente aos domingos;'
XV_NOVO = ('XV - repouso semanal remunerado de 2 (dois) dias, um dos quais preferencialmente aos domingos; '
           '(Redação dada pela Emenda Constitucional nº 141, de 2026) [Nota de vigência: esta redação vale a partir de '
           '16/12/2026 (art. 10, I, da EC 141/2026); até 15/12/2026 vale a redação anterior: "repouso semanal '
           'remunerado, preferencialmente aos domingos".]')
PAR_UNICO = 'Parágrafo único. São assegurados à categoria dos trabalhadores domésticos'
P1_NOVO = '§ 1º São assegurados à categoria dos trabalhadores domésticos'
NOTA_P1 = ' (Parágrafo único numerado como § 1º pela Emenda Constitucional nº 141, de 2026)'


def _sha(texto):
    return hashlib.sha256(texto.encode('utf-8')).hexdigest()


def artigos_ec():
    """Os 10 artigos da EC, na ordem, a partir da transcrição: [(ref, texto)]."""
    corpo = EC_MD.read_text(encoding='utf-8').split('---', 2)[2]
    partes = re.split(r'^###### (Art\. \d+º?)\s*$', corpo, flags=re.M)
    cabeca = partes[0].strip()
    artigos = []
    for ref, texto in zip(partes[1::2], partes[2::2]):
        texto = texto.strip().replace('\nBrasília, 16 de outubro de 2026.', '').strip()
        if ref == 'Art. 1º':
            ementa = cabeca.split('\n\n', 1)[1].strip()
            texto = f'{ementa}\n\n{texto}'
        artigos.append((ref, texto))
    assert [r for r, _ in artigos] == [f'Art. {i}º' for i in range(1, 10)] + ['Art. 10'], [r for r, _ in artigos]
    return artigos


def _tokens():
    try:
        import tiktoken
        enc = tiktoken.get_encoding('cl100k_base')
        return lambda t: len(enc.encode(t))
    except Exception:
        return lambda t: None


def trechos_novos(linhas_base, estrategia):
    """Trechos alterados e acrescentados: lista de dicts com chunk_id, article_id, source_path, text_content, metadata,
    substitui (chunk_id antigo ou None)."""
    tokens = _tokens()
    por_id = {l['chunk_id']: l for l in linhas_base}
    alterados = CHUNKS_ALTERADOS[estrategia]
    novos = []

    def novo(texto, article_id, source_path, meta_base, substitui=None, **extra):
        meta = dict(meta_base or {})
        meta.update(extra, estrategia=estrategia, atualizacao=ATUALIZACAO, retrieved='2026-11-22',
                    fonte_atualizacao=URL_EC, tamanho_caracteres=len(texto), tokens_reais_total=tokens(texto),
                    posicao_inicio_original=None, posicao_fim_original=None, inicio_no_artigo=None, fim_no_artigo=None)
        cid = _sha(json.dumps([ATUALIZACAO, estrategia, source_path, meta.get('artigo_ref'), meta.get('parte'),
                               meta.get('contexto'), _sha(texto)], ensure_ascii=False))
        meta['chunk_id'] = cid
        novos.append(dict(chunk_id=cid, article_id=article_id, source_path=source_path, text_content=texto,
                          metadata=meta, substitui=substitui))

    def trocar(texto, antigo, novo_):
        assert texto.count(antigo) == 1, f'trecho esperado não encontrado: {antigo[:60]}'
        return texto.replace(antigo, novo_)

    if estrategia == 'D_paragrafo_completo':
        caput = por_id[alterados['caput']]
        texto = trocar(trocar(caput['text_content'], XIII_ANTIGO, XIII_NOVO), XV_ANTIGO, XV_NOVO)
        novo(texto, ART7_ID, caput['source_path'], caput['metadata'], substitui=caput['chunk_id'], redacao='EC 141/2026')
        pu = por_id[alterados['paragrafo_unico']]
        assert PAR_UNICO in pu['text_content']
        texto = pu['text_content'].replace(f'{CONTEXTO_ART7} > Parágrafo único]', f'{CONTEXTO_ART7} > § 1º]')
        texto = texto.replace(PAR_UNICO, P1_NOVO).rstrip() + NOTA_P1 + '\n'
        novo(texto, ART7_ID, pu['source_path'], pu['metadata'], substitui=pu['chunk_id'], redacao='EC 141/2026',
             contexto=f'{CONTEXTO_ART7} > § 1º]')
        ec_art1 = dict(artigos_ec())['Art. 1º']
        for n, par in ((2, '§ 2º'), (3, '§ 3º')):
            corpo = re.search(rf'^{par} .*$', ec_art1, re.M).group(0).rstrip('" (NR)').rstrip('"')
            texto = f'{CONTEXTO_ART7} > {par}]\n{corpo} (Incluído pela Emenda Constitucional nº 141, de 2026)\n'
            novo(texto, ART7_ID, pu['source_path'], pu['metadata'], redacao='EC 141/2026', parte=n,
                 contexto=f'{CONTEXTO_ART7} > {par}]', tipo_bloco='paragrafo_com_descendentes',
                 record_id_origem=_sha(f'{ATUALIZACAO}|Art. 7º|{par}'),
                 record_ids_json=json.dumps([_sha(f'{ATUALIZACAO}|Art. 7º|{par}')]))
    else:
        art = por_id[alterados['artigo']]
        texto = trocar(trocar(art['text_content'], XIII_ANTIGO, XIII_NOVO), XV_ANTIGO, XV_NOVO)
        assert texto.count(PAR_UNICO) == 1  # o parágrafo único é o último bloco do artigo
        texto = texto.replace(PAR_UNICO, P1_NOVO).rstrip() + NOTA_P1
        ec_art1 = dict(artigos_ec())['Art. 1º']
        for par in ('§ 2º', '§ 3º'):
            corpo = re.search(rf'^{par} .*$', ec_art1, re.M).group(0).rstrip('" (NR)').rstrip('"')
            texto += f'\n\n{corpo} (Incluído pela Emenda Constitucional nº 141, de 2026)'
        novo(texto + '\n', ART7_ID, art['source_path'], art['metadata'], substitui=art['chunk_id'], redacao='EC 141/2026')

    for ref, corpo in artigos_ec():
        contexto = f'[{CAMINHO_EC} | Emenda Constitucional nº 141, de 16 de outubro de 2026 > {ref}]'
        texto = f'{contexto}\n###### {ref}\n\n{corpo}\n'
        artigo_id = _sha(f'{CAMINHO_EC}|{ref}')
        novo(texto, artigo_id, CAMINHO_EC, None, artigo_ref=ref, artigo_id=artigo_id, contexto=contexto, parte=0,
             tipo_bloco='caput_com_descendentes' if estrategia == 'D_paragrafo_completo' else None,
             caminho_relativo=CAMINHO_EC, source=URL_EC, date=None, status_declarado='in_force',
             record_id_origem=artigo_id, record_ids_json=json.dumps([artigo_id]), tokenizador='cl100k_base',
             sha256_fonte=sha256_file(EC_MD), tem_alerta_parser=False)
    return novos


def criar_versao(conexao, encoder, estrategia):
    from pgvector.psycopg import register_vector
    import numpy as np

    register_vector(conexao)
    base = BASE[estrategia]
    manifesto_base, modelo, dims = conexao.execute(
        'SELECT manifest, model, dimensions FROM lex_clt.vector_datasets WHERE dataset_id=%s', (base,)).fetchone()
    linhas = [dict(chunk_id=c, row_index=r, article_id=a, source_path=s, text_content=t, text_sha256=ts,
                   vector_sha256=vs, metadata=m) for c, r, a, s, t, ts, vs, m in conexao.execute(
        'SELECT chunk_id, row_index, article_id, source_path, text_content, text_sha256, vector_sha256, metadata '
        'FROM lex_clt.chunk_embeddings WHERE dataset_id=%s ORDER BY row_index', (base,)).fetchall()]
    novos = trechos_novos(linhas, estrategia)
    vetores = encoder.encode([n['text_content'] for n in novos], normalize_embeddings=True, convert_to_numpy=True,
                             show_progress_bar=False).astype(np.float32)
    substituidos = {n['substitui']: n for n in novos if n['substitui']}
    proximo = max(l['row_index'] for l in linhas) + 1
    ordem = []  # (row_index, text_sha256, vector_sha256) da versão nova, para o manifesto
    for l in linhas:
        n = substituidos.get(l['chunk_id'])
        if n:
            n['row_index'] = l['row_index']
        else:
            ordem.append((l['row_index'], l['text_sha256'], l['vector_sha256']))
    for n, v in zip(novos, vetores):
        if 'row_index' not in n:
            n['row_index'], proximo = proximo, proximo + 1
        n['embedding'], n['text_sha256'], n['vector_sha256'] = v, _sha(n['text_content']), vector_hash(v)
        ordem.append((n['row_index'], n['text_sha256'], n['vector_sha256']))
    ordem.sort()
    manifesto = dict(
        model=modelo, strategy=estrategia, dimensions=dims, chunk_count=len(ordem),
        model_config_sha256=manifesto_base.get('model_config_sha256'), base_dataset_id=base,
        base_manifest_sha256=json_hash(manifesto_base), atualizacao=ATUALIZACAO,
        fonte_atualizacao=dict(norma='Emenda Constitucional nº 141, de 16/10/2026', url=URL_EC,
                               transcricao=str(EC_MD.relative_to(ROOT)).replace('\\', '/'),
                               transcricao_sha256=sha256_file(EC_MD),
                               pdf_sha256=sha256_file(EC_PDF) if EC_PDF.exists() else None),
        trechos_substituidos=sorted(substituidos), trechos_acrescentados=sum(1 for n in novos if not n['substitui']),
        embeddings_recomputed=f'parcial: {len(novos)} trechos novos ou alterados; os demais copiados da base',
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
                (dataset_id, base, list(substituidos)))
            for n in novos:
                conexao.execute(
                    'INSERT INTO lex_clt.chunk_embeddings (dataset_id, chunk_id, row_index, article_id, source_path, text_content, '
                    'text_sha256, vector_sha256, metadata, embedding) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                    (dataset_id, n['chunk_id'], n['row_index'], n['article_id'], n['source_path'], n['text_content'],
                     n['text_sha256'], n['vector_sha256'], json.dumps(n['metadata'], ensure_ascii=False), n['embedding']))
    return dataset_id, manifesto, novos, bool(existe)


def verificar(conexao, estrategia, dataset_id, manifesto):
    """Confere no banco: contagem, hashes na ordem, art. 7º novo sem a redação antiga, base intacta."""
    linhas = conexao.execute('SELECT row_index, text_sha256, vector_sha256, text_content FROM lex_clt.chunk_embeddings '
                             'WHERE dataset_id=%s ORDER BY row_index', (dataset_id,)).fetchall()
    erros = []
    if len(linhas) != manifesto['chunk_count']:
        erros.append('contagem')
    if hashlib.sha256('\n'.join(t for _, t, _, _ in linhas).encode()).hexdigest() != manifesto['textos_sha256_ordem']:
        erros.append('hash dos textos')
    if hashlib.sha256('\n'.join(v for _, _, v, _ in linhas).encode()).hexdigest() != manifesto['vetores_sha256_ordem']:
        erros.append('hash dos vetores')
    if any(_sha(t) != s for _, s, _, t in linhas):
        erros.append('text_sha256 de algum trecho')
    art7 = [t for _, _, _, t in linhas if CONTEXTO_ART7 in t]
    if any('quarenta e quatro semanais, facultada' in t and 'Nota de vigência' not in t for t in art7):
        erros.append('redação antiga do inciso XIII sem a nota')
    if not any('40 (quarenta) horas semanais' in t for t in art7):
        erros.append('inciso XIII novo ausente')
    base = conexao.execute('SELECT count(*) FROM lex_clt.chunk_embeddings WHERE dataset_id=%s', (BASE[estrategia],)).fetchone()[0]
    return dict(estrategia=estrategia, dataset_id=dataset_id, trechos=len(linhas), trechos_base=base,
                trechos_art7=len(art7), erros=erros)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--verificar', action='store_true', help='só confere as versões já criadas')
    ap.parse_args()
    import psycopg
    from sentence_transformers import SentenceTransformer
    from src.integracao.recuperacao import MODELO, REVISAO

    conexao = psycopg.connect(load_database_url(ROOT / '.env.pgvector.local'), autocommit=True)
    encoder = SentenceTransformer(MODELO, revision=REVISAO, device='cpu', local_files_only=True)
    encoder.max_seq_length = 8192
    relatorio = dict(atualizacao=ATUALIZACAO, norma='Emenda Constitucional nº 141, de 16/10/2026', versoes={})
    for estrategia in BASE:
        dataset_id, manifesto, novos, ja_existia = criar_versao(conexao, encoder, estrategia)
        conferencia = verificar(conexao, estrategia, dataset_id, manifesto)
        print(('já existia: ' if ja_existia else 'criada: ') + json.dumps(conferencia, ensure_ascii=False))
        if conferencia['erros']:
            raise SystemExit(f'falha na verificação de {estrategia}: {conferencia["erros"]}')
        relatorio['versoes'][estrategia] = dict(
            dataset_id=dataset_id, base_dataset_id=BASE[estrategia], trechos=conferencia['trechos'],
            trechos_base=conferencia['trechos_base'], substituidos=manifesto['trechos_substituidos'],
            acrescentados=[dict(chunk_id=n['chunk_id'], contexto=n['metadata'].get('contexto'))
                           for n in novos if not n['substitui']],
            textos_sha256_ordem=manifesto['textos_sha256_ordem'], vetores_sha256_ordem=manifesto['vetores_sha256_ordem'])
    relatorio['fonte'] = manifesto['fonte_atualizacao']
    RELATORIO.parent.mkdir(parents=True, exist_ok=True)
    RELATORIO.write_text(json.dumps(relatorio, indent=2, ensure_ascii=False), encoding='utf-8')
    print('relatório:', RELATORIO.relative_to(ROOT))


if __name__ == '__main__':
    main()
