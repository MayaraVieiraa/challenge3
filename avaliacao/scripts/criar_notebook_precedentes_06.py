"""Cria avaliacao/notebooks/05_docs_precedentes/06_avaliacao_recuperacao_precedentes.ipynb.

Precisa: Postgres com lex_precedentes validado (notebook 05) e lex_jurisprudencia validado; modelos BGE-M3 e
bge-reranker-v2-m3 em cache; pedidos da geração em dados/output/kaggle/geracao/dataset/pedidos.jsonl (perguntas protegidas,
usadas só em memória). Relatórios (só identificadores, nomes de precedentes e posições): dados/relatorios/precedentes/avaliacao/.
Execução: python avaliacao/scripts/executar_notebook_integracao.py avaliacao/notebooks/05_docs_precedentes/06_avaliacao_recuperacao_precedentes.ipynb
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DESTINO = ROOT / 'avaliacao/notebooks/05_docs_precedentes/06_avaliacao_recuperacao_precedentes.ipynb'
celulas = []


def md(ident, texto):
    celulas.append(dict(cell_type='markdown', id=ident, metadata={}, source=texto.strip().splitlines(keepends=True)))


def code(ident, texto):
    celulas.append(dict(cell_type='code', id=ident, metadata={}, execution_count=None, outputs=[],
                        source=texto.strip().splitlines(keepends=True)))


md('av_intro', '''
# 06 · Avaliação da recuperação dos precedentes

Este notebook responde: **quando a regra que decide a pergunta está num precedente do TST, a base `lex_precedentes` entrega esse precedente?** E qual forma de busca funciona melhor nela?

**Dois gabaritos:**

| Gabarito | O que é | Tamanho | Peso |
|---|---|---|---|
| **A, especialista** | Perguntas reais da amostra do advogado revisor (notebook `03_integracao/04_avaliacao`), em que ele apontou o precedente do TST que decidia a pergunta. São as respostas que falharam por falta do precedente (notebook 00) | 7 perguntas (a 8ª depende do STF, fora desta base) | É o que mede o problema real, mas é pequeno |
| **B, prata (automático)** | Trechos de acórdãos da base de jurisprudência que citam **exatamente um** precedente do TST | 300 perguntas, de cerca de 150 precedentes | É grande, mas tem ruído: mede se a base acha o precedente pela descrição do caso |

**Como o gabarito B é montado:**
- A citação é mascarada: "Súmula nº 338 do TST" vira "[precedente]".
- Os 250 caracteres de cada lado da citação viram a pergunta.
- Trechos que **transcrevem** o texto do precedente, com 10 palavras seguidas iguais, são descartados, porque a busca estaria só copiando.
- Cada precedente entra no máximo 3 vezes, para que as súmulas processuais muito citadas, como a 333 e a 126, não dominem o conjunto.
- A seleção é determinística: os trechos são ordenados pelo hash do identificador.

**Buscas comparadas** (as mesmas peças da busca integrada):

| Busca | Como funciona |
|---|---|
| Semântica | BGE-M3, cosseno, 50 trechos |
| Por palavras | Texto normalizado, sem stopwords, peso IDF (notebook 05, seção 3), 50 trechos |
| Híbrida | Fusão das duas por RRF (k = 60) |
| Híbrida + reranker | Os 20 primeiros da híbrida reordenados pelo `bge-reranker-v2-m3`, que lê 256 tokens por par, como na busca integrada |

**Métricas**, contadas no nível do **precedente** (a unidade entregue ao modelo): Hit@1, Hit@3, Hit@5 e MRR@10. No gabarito A, também conferimos se o trecho que achou o precedente é o **item certo**, como a Súmula 338, I.

**Privacidade:** as perguntas da curadoria e os trechos dos acórdãos são usados só em memória. As tabelas e os CSVs mostram apenas identificadores, nomes de precedentes e posições.
''')
md('av_dados', '''
### Dados desta etapa

| | Caminho no repositório | Formato | Quantidade | Versionado? |
|---|---|---|---|---|
| Entrada | PostgreSQL, schema `lex_precedentes` (notebook 05) | tabelas | 1.268 trechos · 1.493 registros | fora do Git (banco) |
| Entrada | `dados/processed/precedentes/precedentes_tst.jsonl` | JSONL | 1.493 registros | fora do Git |
| Entrada (gabarito A) | `dados/output/kaggle/geracao/dataset/pedidos.jsonl` | JSONL | 7 perguntas usadas (protegidas, só em memória) | fora do Git |
| Entrada (gabarito B) | PostgreSQL, `lex_jurisprudencia.embeddings` | tabela | 8.000 trechos candidatos, dos 303.257 | fora do Git (banco) |
| Relatórios | `dados/relatorios/precedentes/avaliacao/` | CSV, JSON e PNG | gabarito_especialista.csv (7 linhas), gabarito_prata.csv (300), resultados_especialista.csv (7), resultados_prata.csv (300), metricas.csv (8), manifesto_avaliacao.json, metricas_por_busca.png | sim |

Os CSV levam só identificadores, nomes de precedentes e posições. O texto das perguntas e dos acórdãos não é gravado.
''')
code('av_setup', r'''
from pathlib import Path
import json, os, sys, hashlib, time
import numpy as np, pandas as pd
import matplotlib.pyplot as plt
from IPython.display import display

ROOT = next(p for p in (Path.cwd(), *Path.cwd().parents) if (p / 'worker/evidencia/precedentes').exists())
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault('HF_HUB_OFFLINE', '1')
pd.set_option('display.max_colwidth', 80); pd.set_option('display.width', 250); pd.set_option('display.max_columns', None)
import psycopg
from pgvector.psycopg import register_vector
from sentence_transformers import SentenceTransformer, CrossEncoder
from worker.evidencia.recuperador import MODELO, REVISAO, RERANKER
from worker.evidencia.precedentes import indexacao as ix, avaliacao as av
from worker.evidencia.indices.pgvector_store import load_database_url

REL = ROOT / 'dados/relatorios/precedentes/avaliacao'; REL.mkdir(parents=True, exist_ok=True)
registros = [json.loads(l) for l in (ROOT / 'dados/processed/precedentes/precedentes_tst.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
por_id = {r['id']: r for r in registros}
conexao = psycopg.connect(load_database_url(ROOT / '.env.pgvector.local'), autocommit=True)
register_vector(conexao)
dataset = conexao.execute("SELECT dataset_id FROM lex_precedentes.datasets WHERE estado='validado'").fetchone()[0]
man_ix = json.loads((ROOT / 'dados/relatorios/precedentes/indexacao/manifesto_indexacao.json').read_text(encoding='utf-8'))
assert dataset == man_ix['dataset_id'], 'a versão validada no banco não é a do manifesto do notebook 05'
trechos = {c: dict(registro=r, texto=t, item=(m or {}).get('item')) for c, r, t, m in conexao.execute(
    'SELECT chunk_id, registro_id, texto, metadata FROM lex_precedentes.embeddings WHERE dataset_id=%s', (dataset,)).fetchall()}
chunk_reg = {c: v['registro'] for c, v in trechos.items()}
ix.preparar_lexico(conexao, dataset)
encoder = SentenceTransformer(MODELO, revision=REVISAO, device='cpu', local_files_only=True)
reranker = CrossEncoder(RERANKER, max_length=256, device='cpu', local_files_only=True)
print(f'lex_precedentes {dataset[:12]}… · {len(trechos)} trechos · {len(registros)} registros')
''')

md('av_busca_texto', '## 1. As quatro buscas')
code('av_busca', r'''
METODOS = ['semântica', 'por palavras', 'híbrida', 'híbrida + reranker']

def buscar(pergunta, k=50, n_rerank=20):
    vetor = encoder.encode([pergunta], normalize_embeddings=True)[0].astype(np.float32)
    sem = [c for _, c, _ in ix.busca_semantica(conexao, dataset, vetor, k=k)]
    lex = [c for _, c, _ in ix.busca_lexical(conexao, dataset, pergunta, k=k)]
    hib = av.rrf([sem, lex])
    cand = hib[:n_rerank]
    notas = reranker.predict([(pergunta, trechos[c]['texto']) for c in cand], show_progress_bar=False) if cand else []
    rer = [c for _, c in sorted(zip(notas, cand), key=lambda x: (-x[0], x[1]))]
    return dict(zip(METODOS, [sem, lex, hib, rer]))

def posicao(chunks, esperado):
    ordem = av.ordem_registros(chunks, chunk_reg)
    return ordem.index(esperado) + 1 if esperado in ordem else None

def item_encontrado(chunks, esperado):
    """Item do primeiro trecho do precedente esperado na lista (None se o precedente não tem itens)."""
    return next((trechos[c]['item'] for c in chunks if chunk_reg[c] == esperado), None)
print('ok')
''')

md('av_a_texto', '''
## 2. Gabarito A: perguntas reais com o precedente apontado pelo advogado

São as perguntas da amostra do advogado em que a resposta falhou porque o sistema não tinha o precedente (notebook 00, seção 4). O texto delas é protegido e não aparece aqui.
''')
code('av_a', r'''
GABARITO_A = [  # (pergunta_id, precedente esperado, item)
    ('juris_004', 'TST-SUM-338', 'I'), ('q09_p2_FAQ32', 'TST-SUM-276', None), ('juris_013', 'TST-SUM-378', 'II'),
    ('juris_019', 'TST-SUM-6', 'VIII'), ('juris_017', 'TST-IRR-58', None), ('q09_p1_JUS-001', 'TST-SUM-60', 'II'),
    ('q09_p2_FAQ26', 'TST-SUM-45', None)]
pedidos = {json.loads(l)['pergunta_id']: json.loads(l) for l in
           (ROOT / 'dados/output/kaggle/geracao/dataset/pedidos.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()}
linhas_a = []
for pid, esperado, item in GABARITO_A:
    res = buscar(pedidos[pid]['pergunta_sanitizada'])
    linha = dict(pergunta=pid, precedente=por_id[esperado]['nome_citacao'] + (f', {item}' if item else ''))
    for m in METODOS:
        linha[m] = posicao(res[m], esperado)
    achado = item_encontrado(res['híbrida + reranker'], esperado)
    linha['item certo (reranker)'] = None if item is None else (achado == item)
    linha['1º (reranker)'] = por_id[av.ordem_registros(res['híbrida + reranker'], chunk_reg)[0]]['nome_citacao']
    linhas_a.append(linha)
tab_a = pd.DataFrame(linhas_a)
display(tab_a)
met_a = pd.DataFrame({m: av.metricas([l[m] for l in linhas_a]) for m in METODOS}).T
display(met_a)
pd.DataFrame([dict(pergunta=p, esperado=e, item=i) for p, e, i in GABARITO_A]).to_csv(REL / 'gabarito_especialista.csv', index=False, encoding='utf-8')
''')

md('av_a_comparacao_texto', '''
**Mesma súmula, duas bases.** No notebook 00, o texto destas súmulas, então digitado de memória, foi colocado entre os 20 mil acórdãos da base de jurisprudência. Aqui está a posição do texto oficial na base separada.
''')
code('av_a_comparacao', r'''
rank00 = pd.read_csv(ROOT / 'dados/relatorios/precedentes/teste_ranking_jurisprudencia.csv')
comp = rank00[['pergunta_id', 'precedente', 'posicao_entre_documentos']].rename(
    columns={'pergunta_id': 'pergunta', 'posicao_entre_documentos': 'na base de jurisprudência (de 20 mil)'})
comp = comp.merge(tab_a[['pergunta', 'semântica', 'híbrida + reranker']].rename(
    columns={'semântica': 'em lex_precedentes: semântica', 'híbrida + reranker': 'em lex_precedentes: híbrida + reranker'}), on='pergunta')
display(comp)
''')

md('av_b_texto', '''
## 3. Gabarito B: trechos de acórdãos com a citação mascarada

**Seleção:**
- Os candidatos são os trechos da base de jurisprudência validada que mencionam súmula ou OJ seguidos de número. Eles são ordenados pelo hash do identificador e limitados aos 8 mil primeiros.
- Fica a primeira ocorrência de cada caso aceito, até 300 perguntas.
- A tabela de descartes mostra por que os outros saíram:
  - mais de um precedente citado no mesmo trecho;
  - precedente fora da busca (cancelado, suspenso ou em quarentena);
  - transcrição do texto do precedente;
  - excesso de ocorrências do mesmo precedente.
''')
code('av_b_monta', r'''
ds_jur = conexao.execute("SELECT dataset_id FROM lex_jurisprudencia.datasets WHERE estado='validado'").fetchone()[0]
candidatos = conexao.execute(r"""SELECT chunk_id, registro_id, texto FROM lex_jurisprudencia.embeddings WHERE dataset_id=%s
    AND texto ~* '(s[úu]mula|orienta[çc][ãa]o jurisprudencial|\moj\M)\s*(n[º°o.]*\s*)?\d{1,3}'
    ORDER BY md5(chunk_id) LIMIT 8000""", (ds_jur,)).fetchall()
itens_b, descartes = av.gabarito_prata(candidatos, registros, limite=300)
del candidatos
print(f'{len(itens_b)} perguntas · {len({i["esperado"] for i in itens_b})} precedentes distintos · '
      f'{len({i["acordao"] for i in itens_b})} acórdãos distintos')
display(pd.Series(descartes, name='trechos descartados').to_frame())
pd.DataFrame([{k: i[k] for k in ('id', 'chunk_origem', 'acordao', 'esperado', 'item', 'tipo')} for i in itens_b]).to_csv(
    REL / 'gabarito_prata.csv', index=False, encoding='utf-8')
''')
code('av_b_roda', r'''
inicio = time.monotonic()
linhas_b = []
for i in itens_b:
    res = buscar(i['pergunta'])
    linha = dict(id=i['id'], esperado=i['esperado'], tipo=i['tipo'])
    for m in METODOS:
        linha[m] = posicao(res[m], i['esperado'])
    linha['1º (reranker)'] = (av.ordem_registros(res['híbrida + reranker'], chunk_reg) or [None])[0]
    linha['1º (híbrida)'] = (av.ordem_registros(res['híbrida'], chunk_reg) or [None])[0]
    linhas_b.append(linha)
tab_b = pd.DataFrame(linhas_b)
print(f'{len(tab_b)} perguntas em {time.monotonic() - inicio:.0f} s')
met_b = pd.DataFrame({m: av.metricas(tab_b[m].tolist()) for m in METODOS}).T
display(met_b)
por_tipo = pd.DataFrame({(t, m): av.metricas(tab_b[tab_b.tipo == t][m].tolist()) for t in ['sumula', 'orientacao_jurisprudencial'] for m in METODOS}).T[['Hit@1', 'Hit@3', 'MRR@10', 'n']]
display(por_tipo)
''')
code('av_b_grafico', r'''
fig, ax = plt.subplots(figsize=(9, 3.6))
x = np.arange(len(METODOS)); w = 0.2
for j, (g, met, cor) in enumerate([('A especialista (n=7)', met_a, '#d08a2e'), ('B prata (n=%d)' % len(tab_b), met_b, '#2f6db5')]):
    for k, (col, alfa) in enumerate([('Hit@1', .55), ('Hit@3', 1.0)]):
        pos = x + (j * 2 + k - 1.5) * w
        ax.bar(pos, met[col].values, w, color=cor, alpha=alfa, label=f'{g} · {col}')
ax.set_xticks(x, METODOS); ax.set_ylim(0, 1.05); ax.set_ylabel('acerto')
ax.set_title('Precedente esperado entre os primeiros, por tipo de busca')
ax.legend(frameon=False, fontsize=8, ncol=2, loc='lower right'); ax.spines[['top', 'right']].set_visible(False)
fig.tight_layout(); fig.savefig(REL / 'metricas_por_busca.png', dpi=110)
display(fig); plt.close(fig)
''')

md('av_erros_texto', '''
## 4. Quando erra, o que vem em primeiro?

Nos erros do gabarito B, comparamos o precedente esperado com o que ficou em 1º. Muitas vezes o 1º é um precedente vizinho, do mesmo assunto ou do mesmo dispositivo. Nesse caso, o erro pesa menos para a resposta, porque o modelo recebe 3 precedentes.
''')
code('av_erros', r'''
melhor = met_b['MRR@10'].idxmax()
col1 = '1º (reranker)' if melhor == 'híbrida + reranker' else '1º (híbrida)'
erros = tab_b[(tab_b[melhor] != 1)]
print(f'Busca de referência: {melhor} · erros no 1º lugar: {len(erros)} de {len(tab_b)} '
      f'(o esperado aparece até o 3º em {int((erros[melhor] <= 3).sum())}; não aparece até o 10º em {int(erros[melhor].isna().sum() + (erros[melhor] > 10).sum())})')
amostra = erros.head(12).assign(
    esperado_nome=lambda d: d.esperado.map(lambda r: por_id[r]['nome_citacao'] + ' — ' + por_id[r]['titulo'][:50]),
    primeiro_nome=lambda d: d[col1].map(lambda r: por_id[r]['nome_citacao'] + ' — ' + por_id[r]['titulo'][:50] if r else None))
display(amostra[['id', 'esperado_nome', 'primeiro_nome', melhor]])
''')

md('av_grava_texto', '## 5. Gravação')
code('av_grava', r'''
tab_a.to_csv(REL / 'resultados_especialista.csv', index=False, encoding='utf-8')
tab_b.to_csv(REL / 'resultados_prata.csv', index=False, encoding='utf-8')
metricas = pd.concat([met_a.assign(gabarito='A especialista'), met_b.assign(gabarito='B prata')]).rename_axis('busca').reset_index()
metricas.to_csv(REL / 'metricas.csv', index=False, encoding='utf-8')
(REL / 'manifesto_avaliacao.json').write_text(json.dumps(dict(
    dataset_precedentes=dataset, dataset_jurisprudencia=ds_jur, modelo=f'{MODELO}@{REVISAO}', reranker=RERANKER,
    reranker_max_length=256, rrf_k=av.RRF_K, n_rerank=20, janela_caracteres=av.JANELA, max_por_precedente=av.MAX_POR_PRECEDENTE,
    gabarito_especialista=len(tab_a), gabarito_prata=len(tab_b), descartes_prata=descartes), indent=2, ensure_ascii=False), encoding='utf-8')
display(metricas)
''')

md('av_conclusao', '''
## Conclusões

1. **A base separada resolve o problema do notebook 00.** No gabarito A, a busca híbrida + reranker põe em 1º lugar 5 dos 7 precedentes que faltaram nas respostas reprovadas pelo advogado: Súmulas 338, 276, 378 e 6, e Tema 58. Na base de jurisprudência, essas súmulas ficavam entre a 8ª e a 3.370ª posição. A busca só semântica acha 6 dos 7 até o 3º lugar.
2. **As duas falhas do gabarito A apontam ajustes concretos:**
   - **Súmula 60:** a busca semântica a punha em 3º, mas a fusão com a busca por palavras a levou ao 21º lugar. Como o reranker só reordena os 20 primeiros, ela ficou de fora. **Ajuste:** montar o conjunto do reranker com a união dos primeiros de cada busca, e não só com os primeiros da fusão.
   - **Súmula 45:** nenhuma busca achou. A pergunta fala em "13º salário" e a súmula, em "gratificação natalina", um sinônimo jurídico que nem o vetor nem as palavras ligaram. **Ajuste:** um dicionário de sinônimos jurídicos na normalização da pergunta, como "13º salário" = "gratificação natalina", "DSR" = "repouso semanal remunerado" e "FGTS" = "fundo de garantia".
3. **No gabarito B, a híbrida + reranker é a melhor:**
   - Hit@1 de 0,33, Hit@3 de 0,53 e MRR de 0,44;
   - em seguida vem a semântica, com 0,29, 0,46 e 0,40;
   - a busca por palavras sozinha é a mais fraca (0,17 e 0,30). Na fusão, ela deixa a híbrida sem reranker abaixo da semântica (0,27 e 0,43), e o reranker recupera.
4. **O gabarito B é conservador:**
   - muitos erros são súmulas processuais, como as 126, 333, 422 e 128, sobre o cabimento de recurso. O texto delas pouco descreve o caso, e o acórdão as cita de passagem;
   - parte dos "erros" é um precedente vizinho também correto, como a Súmula 438 e o Tema 211, ambos sobre o intervalo para recuperação térmica.
5. **Item certo:** nas súmulas com itens, o primeiro trecho encontrado nem sempre é o item da pergunta (foi o item certo em 1 dos 3 casos em que a súmula veio). Como o modelo recebe o **registro inteiro**, o item certo chega mesmo assim. Mas a busca ainda não distingue bem os itens.
6. **Recomendação para integrar a base como terceira fonte:**
   - usar a busca **híbrida + reranker**, com o conjunto do reranker vindo da **união** dos primeiros da semântica e da busca por palavras;
   - começar com uma **cota de 3 precedentes**, pelo Hit@3;
   - testar no conjunto maior de perguntas, junto com os sinônimos jurídicos.
7. **Limitações:**
   - o gabarito A tem só 7 perguntas, e cada uma vale 14 pontos percentuais;
   - o gabarito B é automático: um precedente igualmente correto conta como erro;
   - o tempo é alto: cerca de 16 s por pergunta na CPU, sobretudo por causa do reranker. Na busca integrada, ele reordena só 20 trechos por fonte.
''')

notebook = dict(cells=celulas, nbformat=4, nbformat_minor=5,
                metadata=dict(kernelspec=dict(display_name='Python 3', language='python', name='python3'),
                              language_info=dict(name='python', version='3.14.6')))
DESTINO.write_text(json.dumps(notebook, indent=2, ensure_ascii=False), encoding='utf-8')
print('Notebook criado em', DESTINO.relative_to(ROOT))
