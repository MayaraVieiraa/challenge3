"""Cria os notebooks 04 (chunking) e 05 (embeddings e indexação) de avaliacao/notebooks/05_docs_precedentes/.

Fluxo (dados fora do Git):
  dados/processed/precedentes/precedentes_tst.jsonl      03: registros estruturados
  dados/processed/precedentes/chunks_precedentes.jsonl   04: trechos
  dados/processed/precedentes/vetores_bge_m3.npy         05: cache dos vetores
  PostgreSQL/pgvector, schema lex_precedentes           05: versão validada
Relatórios versionados: dados/relatorios/precedentes/{chunking,indexacao}/ (contagens, hashes e manifestos).
Execução: python avaliacao/scripts/executar_notebook_integracao.py avaliacao/notebooks/05_docs_precedentes/<notebook>.ipynb
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PASTA = ROOT / 'avaliacao/notebooks/05_docs_precedentes'


class Notebook:
    def __init__(self, nome):
        self.nome, self.celulas = nome, []

    def md(self, ident, texto):
        self.celulas.append(dict(cell_type='markdown', id=ident, metadata={},
                                 source=texto.strip().splitlines(keepends=True)))

    def code(self, ident, texto):
        self.celulas.append(dict(cell_type='code', id=ident, metadata={}, execution_count=None, outputs=[],
                                 source=texto.strip().splitlines(keepends=True)))

    def gravar(self):
        nb = dict(cells=self.celulas, nbformat=4, nbformat_minor=5,
                  metadata=dict(kernelspec=dict(display_name='Python 3', language='python', name='python3'),
                                language_info=dict(name='python', version='3.14.6')))
        destino = PASTA / self.nome
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(json.dumps(nb, indent=2, ensure_ascii=False), encoding='utf-8')
        print('Notebook criado em', destino.relative_to(ROOT))

SETUP = r'''
from pathlib import Path
import json, os, sys, hashlib
import pandas as pd
import matplotlib.pyplot as plt
from IPython.display import display

ROOT = next(p for p in (Path.cwd(), *Path.cwd().parents) if (p / 'worker/evidencia/precedentes').exists())
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault('HF_HUB_OFFLINE', '1')
pd.set_option('display.max_colwidth', 120); pd.set_option('display.width', 250); pd.set_option('display.max_columns', None)
PROC = ROOT / 'dados/processed/precedentes'
REGISTROS = PROC / 'precedentes_tst.jsonl'
TRECHOS = PROC / 'chunks_precedentes.jsonl'
REL = ROOT / 'dados/relatorios/precedentes'
'''

# ---------------------------------------------------------------------------------------------------------------
n4 = Notebook('04_chunking_precedentes.ipynb')
n4.md('ch_intro', '''
# 04 · Chunking dos precedentes

Este notebook divide os registros do JSONL único (notebook 03) em **trechos**, que são as unidades da busca. A EDA (notebook 02) mostrou que os precedentes são curtos, com mediana de cerca de 100 tokens por enunciado. Por isso a divisão é simples e segue a estrutura do próprio texto.

| Decisão | Regra | Por quê |
|---|---|---|
| O que entra | Só os registros **buscáveis** (vigentes, com tese fixada ou afetados sem tese) | Cancelados, suspensos, superados e em quarentena não podem ser entregues como regra. Eles ficam registrados no JSONL e na tabela de registros (notebook 05), fora do índice |
| Unidade | Um trecho por enunciado. Súmula ou OJ com itens: **um trecho por item**. Tema: questão jurídica e tese juntas | A pergunta costuma tocar um item específico, como a Súmula 338, I ou III. Separar os itens evita que um item irrelevante dilua o vetor |
| Caput antes dos itens | É repetido no início de cada item | Sem ele, o item perde o sentido. Exemplo: OJ 225 da SBDI-1, "Celebrado contrato de concessão...: I - ..." |
| Cabeçalho | Todo trecho começa com "[Súmula 338 do TST — TÍTULO — item I]" | O trecho se explica sozinho na busca, no reranker e no prompt, e o nome de citação fica junto do texto |
| Tamanho | Até **220 tokens** (tokenizador do BGE-M3), com o cabeçalho incluído. Acima disso, o texto é dividido por frases, com o cabeçalho repetido e "parte k de n" | O reranker lê 256 tokens por par pergunta–trecho. Descontada a pergunta, um trecho de até 220 tokens é lido inteiro |
| Entrega | A busca encontra o trecho, mas o modelo recebe o **registro inteiro**, com todos os itens e o nome de citação | É o mesmo padrão da legislação, que busca no parágrafo e entrega o artigo. O item encontrado indica onde está a regra, mas o enunciado completo evita perder condições de outros itens |
''')
n4.md('ch_dados', '''
### Dados desta etapa

| | Caminho no repositório | Formato | Quantidade | Versionado? |
|---|---|---|---|---|
| Entrada | `dados/processed/precedentes/precedentes_tst.jsonl` | JSONL (um registro JSON por linha) | 1.493 registros (1.022 buscáveis) | fora do Git |
| Saída | `dados/processed/precedentes/chunks_precedentes.jsonl` | JSONL (um registro JSON por linha) | **1.268 trechos** (442 de súmulas, 425 de OJs, 401 de temas) | fora do Git |
| Relatórios | `dados/relatorios/precedentes/chunking/` | CSV, JSON e PNG | contagens.csv (3 linhas: uma por tipo), manifesto_chunking.json, tokens_trechos.png | sim |

**Formato:** a base estruturada é gravada em **JSONL** (texto, um registro JSON por linha), e não em CSV, porque cada registro tem campos com listas (itens da súmula, páginas, assuntos, histórico). Os arquivos **CSV** do projeto são os relatórios em `dados/relatorios/precedentes/`. Os arquivos de dados ficam em `dados/`, dentro da pasta do repositório, mas **fora do Git** (`.gitignore`): contêm texto integral e são recriados pelos notebooks.
''')
n4.code('ch_setup', SETUP + r'''
from transformers import AutoTokenizer
from worker.evidencia.recuperador import MODELO, REVISAO
from worker.evidencia.precedentes import chunking as ch, estruturacao as est
registros = [json.loads(l) for l in REGISTROS.read_text(encoding='utf-8').splitlines() if l.strip()]
man_est = json.loads((REL / 'estruturacao/manifesto_estruturacao.json').read_text(encoding='utf-8'))
sha_reg = hashlib.sha256(REGISTROS.read_bytes()).hexdigest()
assert sha_reg == man_est['sha256'], 'o JSONL não é o registrado no manifesto da estruturação (rode o notebook 03)'
tok = AutoTokenizer.from_pretrained(MODELO, revision=REVISAO, local_files_only=True)
contar = lambda t: len(tok(t, add_special_tokens=False)['input_ids'])
(REL / 'chunking').mkdir(parents=True, exist_ok=True)
print(f'{len(registros)} registros ({sum(r["buscavel"] for r in registros)} buscáveis) · JSONL conferido com o manifesto do 03 · limite {ch.LIMITE_TOKENS} tokens')
''')

n4.md('ch_gera_texto', '## 1. Geração e validação dos trechos')
n4.code('ch_gera', r'''
trechos = ch.gerar_trechos(registros, contar, est.sem_origem)
problemas, avisos = ch.validar(registros, trechos)
print(f'{len(trechos)} trechos de {len({t["registro_id"] for t in trechos})} registros')
print('Problemas (impedem gravar):', problemas or 'nenhum')
print(f'Trechos acima de {ch.LIMITE_TOKENS} tokens (uma única frase longa, que não se divide sem quebrar o sentido): {len(avisos)}')
for a in avisos:
    print('  ', a)
''')
n4.md('ch_gera_leitura', '''
A validação confere:
- todo registro buscável tem pelo menos um trecho, e nenhum registro fora da busca tem trecho;
- não há identificador repetido;
- **nenhum texto se perde na divisão:**
  - nos registros sem itens, os trechos juntos reproduzem o texto de busca;
  - nos registros por item, o caput e cada item aparecem nos trechos.

Os trechos acima do limite são frases únicas, sobretudo teses longas de temas. Elas ficam inteiras, porque cortá-las no meio quebraria a regra. Na busca semântica, o BGE-M3 lê o trecho todo. Só o reranker lê parte dele.
''')

n4.md('ch_dist_texto', '## 2. Distribuição')
n4.code('ch_dist', r'''
df = pd.DataFrame(trechos)
nomes = {'sumula': 'Súmulas', 'orientacao_jurisprudencial': 'OJs', 'tema_repetitivo': 'Temas'}
resumo = df.groupby('tipo').agg(registros=('registro_id', 'nunique'), trechos=('chunk_id', 'size'),
                                trechos_por_item=('item', lambda s: int(s.notna().sum())),
                                registros_divididos_em_partes=('partes', lambda s: int(df.loc[s.index][s > 1].registro_id.nunique())),
                                tokens_medios=('tokens', 'mean'), tokens_max=('tokens', 'max')).round(0).rename(index=nomes)
display(resumo)
resumo.to_csv(REL / 'chunking/contagens.csv', encoding='utf-8')

fig, ax = plt.subplots(figsize=(8, 3.3))
for tipo, cor in [('sumula', '#2f6db5'), ('orientacao_jurisprudencial', '#7aa6d8'), ('tema_repetitivo', '#d08a2e')]:
    ax.hist(df[df.tipo == tipo].tokens, bins=40, alpha=.6, color=cor, label=nomes[tipo])
ax.axvline(ch.LIMITE_TOKENS, color='#444', lw=1, ls='--')
ax.text(ch.LIMITE_TOKENS + 5, ax.get_ylim()[1] * .9, f'limite {ch.LIMITE_TOKENS}', fontsize=8)
ax.set_xlabel('tokens do trecho (BGE-M3, com cabeçalho)'); ax.set_ylabel('trechos')
ax.set_title('Tamanho dos trechos'); ax.legend(frameon=False); ax.spines[['top', 'right']].set_visible(False)
fig.tight_layout(); fig.savefig(REL / 'chunking/tokens_trechos.png', dpi=110)
display(fig); plt.close(fig)
''')

n4.md('ch_exemplos_texto', '## 3. Exemplos')
n4.code('ch_exemplos', r'''
def mostrar(rid, max_partes=3):
    for t in [t for t in trechos if t['registro_id'] == rid][:max_partes]:
        print(f"({t['tokens']} tokens) {t['texto'][:420]}\n")
print('— Súmula 338 (um trecho por item):\n'); mostrar('TST-SUM-338')
print('— OJ 225 da SBDI-1 (caput repetido em cada item):\n'); mostrar('TST-OJ-SDI1-225', 1)
print('— Tema 58 de IRR (questão + tese num trecho):\n'); mostrar('TST-IRR-58')
maior = df[df.partes > 1].sort_values('partes', ascending=False).iloc[0]
print(f"— {maior.nome_citacao} (tese longa dividida em {maior.partes} partes; mostrando 2):\n"); mostrar(maior.registro_id, 2)
''')

n4.md('ch_grava_texto', '''
## 4. Gravação e manifesto

Os trechos vão para `dados/processed/precedentes/chunks_precedentes.jsonl`, fora do Git. O manifesto, que é versionado, registra:
- o hash do JSONL de trechos;
- o hash do JSONL de registros de origem;
- os parâmetros;
- as contagens.

O notebook 05 confere esse hash antes de gerar os vetores.
''')
n4.md('ch_grava_dados', '''
> **Grava:** `dados/processed/precedentes/chunks_precedentes.jsonl` (JSONL, 1.268 linhas, fora do Git) e `dados/relatorios/precedentes/chunking/manifesto_chunking.json`
''')
n4.code('ch_grava', r'''
if problemas:
    raise ValueError(f'{len(problemas)} problemas; nada foi gravado')
sha_tr = ch.gravar_jsonl(trechos, TRECHOS)
manifesto = dict(arquivo=str(TRECHOS.relative_to(ROOT)).replace('\\', '/'), sha256=sha_tr, trechos=len(trechos),
                 registros=int(df.registro_id.nunique()), registros_jsonl_sha256=sha_reg, limite_tokens=ch.LIMITE_TOKENS,
                 tokenizador=f'{MODELO}@{REVISAO}', acima_do_limite=len(avisos),
                 regras=['um trecho por enunciado; por item em súmulas e OJs com itens; caput repetido em cada item',
                         'cabeçalho com nome de citação, título e item', 'divisão por frases acima do limite',
                         'só registros buscáveis'])
(REL / 'chunking/manifesto_chunking.json').write_text(json.dumps(manifesto, indent=2, ensure_ascii=False), encoding='utf-8')
print(json.dumps(manifesto, indent=2, ensure_ascii=False))
''')
n4.md('ch_conclusao', '''
## Conclusões

- **Cerca de 1,3 mil trechos**, a partir dos 1.022 registros buscáveis:
  - as súmulas e OJs com itens viram um trecho por item;
  - as teses longas de temas são divididas por frases;
  - o restante fica em um trecho por enunciado.
- **Cada trecho é legível sozinho.** O cabeçalho traz o nome de citação e o título, e o caput se repete nos itens. Isso ajuda o reranker e o prompt, que vai citar "Súmula 338, I, do TST".
- **Nada se perdeu na divisão.** A validação confere o texto de cada registro.

Próximo: `05_embeddings_indexacao_precedentes.ipynb`.
''')
n4.gravar()

# ---------------------------------------------------------------------------------------------------------------
n5 = Notebook('05_embeddings_indexacao_precedentes.ipynb')
n5.md('ix_intro', '''
# 05 · Embeddings e indexação dos precedentes

Este notebook gera os vetores dos trechos do notebook 04 e grava a base no PostgreSQL/pgvector, no schema próprio `lex_precedentes`. Ele segue o mesmo padrão das bases de legislação e de jurisprudência.

| Item | Decisão |
|---|---|
| Modelo | **BGE-M3**, na mesma revisão usada nas outras bases (`worker/evidencia/recuperador.py`), para que pergunta e trecho fiquem no mesmo espaço vetorial |
| Vetores | 1024 dimensões, normalizados; a semelhança é o cosseno |
| Versão | Identificada pelo **hash do manifesto**: modelo, revisão, hash dos trechos e hash dos vetores na ordem. Qualquer mudança gera outra versão |
| Importação | Numa transação. Depois, os textos e os vetores são relidos do banco e os hashes conferidos. Só então a versão fica `validado`, e a anterior passa a `substituido` |
| Tabelas | `datasets` (manifesto e estado); `embeddings` (um trecho por linha); `registros` (o registro inteiro, incluindo os que estão fora da busca, para a entrega e para dizer que um enunciado foi cancelado) |
| Índice | Busca **exata**, sem índice aproximado: com cerca de 1,3 mil vetores, a varredura completa é rápida e não perde resultados. Mais um índice para a busca por palavras (`lex_precedentes.lexico`), com o texto normalizado e **sem stopwords** (seção 3) |
''')
n5.md('ix_dados', '''
### Dados desta etapa

| | Caminho no repositório | Formato | Quantidade | Versionado? |
|---|---|---|---|---|
| Entrada | `dados/processed/precedentes/chunks_precedentes.jsonl` | JSONL (um registro JSON por linha) | 1.268 trechos | fora do Git |
| Entrada | `dados/processed/precedentes/precedentes_tst.jsonl` | JSONL (um registro JSON por linha) | 1.493 registros | fora do Git |
| Saída (cache) | `dados/processed/precedentes/vetores_bge_m3.npy` | NumPy (.npy), float32 | matriz 1.268 × 1.024 | fora do Git |
| Saída (banco) | `PostgreSQL no Docker, schema lex_precedentes` | tabelas | datasets (1 versão validada), embeddings (1.268 linhas), registros (1.493), lexico (1.268) | fora do Git (banco) |
| Relatórios | `dados/relatorios/precedentes/indexacao/manifesto_indexacao.json` | JSON | manifesto da versão (hashes e contagens) | sim |

**Formato:** a base estruturada é gravada em **JSONL** (texto, um registro JSON por linha), e não em CSV, porque cada registro tem campos com listas (itens da súmula, páginas, assuntos, histórico). Os arquivos **CSV** do projeto são os relatórios em `dados/relatorios/precedentes/`. Os arquivos de dados ficam em `dados/`, dentro da pasta do repositório, mas **fora do Git** (`.gitignore`): contêm texto integral e são recriados pelos notebooks.
''')
n5.code('ix_setup', SETUP + r'''
import numpy as np, psycopg
from sentence_transformers import SentenceTransformer
from worker.evidencia.recuperador import MODELO, REVISAO
from worker.evidencia.precedentes import indexacao as ix
from worker.evidencia.indices.pgvector_store import load_database_url
trechos = [json.loads(l) for l in TRECHOS.read_text(encoding='utf-8').splitlines() if l.strip()]
registros = [json.loads(l) for l in REGISTROS.read_text(encoding='utf-8').splitlines() if l.strip()]
man_ch = json.loads((REL / 'chunking/manifesto_chunking.json').read_text(encoding='utf-8'))
sha_tr = hashlib.sha256(TRECHOS.read_bytes()).hexdigest()
sha_reg = hashlib.sha256(REGISTROS.read_bytes()).hexdigest()
assert sha_tr == man_ch['sha256'] and sha_reg == man_ch['registros_jsonl_sha256'], 'trechos ou registros diferentes do manifesto do 04'
(REL / 'indexacao').mkdir(parents=True, exist_ok=True)
print(f'{len(trechos)} trechos · {len(registros)} registros · conferidos com o manifesto do 04 · modelo {MODELO}@{REVISAO[:8]}')
''')

n5.md('ix_vet_texto', '''
## 1. Vetores

Os vetores são calculados no computador local, na CPU, porque são poucos trechos. Eles ficam num cache em `dados/processed/precedentes/`. Uma nova execução só recalcula se os textos mudarem.
''')
n5.md('ix_vet_dados', '''
> **Lê:** `dados/processed/precedentes/chunks_precedentes.jsonl` (1.268 trechos)<br>
> **Grava:** `dados/processed/precedentes/vetores_bge_m3.npy` (NumPy, 1.268 × 1.024, fora do Git)
''')
n5.code('ix_vet', r'''
import time
inicio = time.monotonic()
encoder = SentenceTransformer(MODELO, revision=REVISAO, device='cpu', local_files_only=True)
encoder.max_seq_length = 8192
vetores, do_cache = ix.vetorizar(trechos, encoder, cache=PROC / 'vetores_bge_m3.npy')
normas = np.linalg.norm(vetores, axis=1)
print(f'{vetores.shape[0]} vetores de {vetores.shape[1]} dimensões · {"do cache" if do_cache else f"calculados em {time.monotonic() - inicio:.0f} s"}')
print(f'norma: mín {normas.min():.4f} · máx {normas.max():.4f} (normalizados) · valores finitos: {bool(np.isfinite(vetores).all())}')
''')

n5.md('ix_imp_texto', '## 2. Manifesto, importação e conferência')
n5.md('ix_imp_dados', '''
> **Lê:** os trechos, os vetores e os 1.493 registros<br>
> **Grava:** tabelas `lex_precedentes.datasets`, `lex_precedentes.embeddings` (1.268 linhas) e `lex_precedentes.registros` (1.493 linhas) no PostgreSQL; `dados/relatorios/precedentes/indexacao/manifesto_indexacao.json`
''')
n5.code('ix_imp', r'''
manifesto = ix.manifesto(trechos, vetores, registros, MODELO, REVISAO, sha_tr, sha_reg, man_ch['limite_tokens'])
conexao = psycopg.connect(load_database_url(ROOT / '.env.pgvector.local'), autocommit=True)
dataset_id, ja_existia = ix.importar(conexao, trechos, vetores, registros, manifesto)
erros = ix.verificar(conexao, manifesto)
estados = conexao.execute('SELECT left(dataset_id, 12), estado, chunks_esperados, registros_esperados, atualizado_em '
                          'FROM lex_precedentes.datasets ORDER BY atualizado_em').fetchall()
print(f'Versão {dataset_id[:16]}… {"já estava validada" if ja_existia else "importada e validada"} · conferência: {erros or "ok"}')
display(pd.DataFrame(estados, columns=['dataset', 'estado', 'trechos', 'registros', 'atualizado_em']))
(REL / 'indexacao/manifesto_indexacao.json').write_text(json.dumps(manifesto, indent=2, ensure_ascii=False), encoding='utf-8')
''')

n5.md('ix_lex_texto', '''
## 3. Busca por palavras: normalização do texto, sem stopwords

A busca por palavras do PostgreSQL compara as palavras da pergunta com as do trecho. O texto jurídico tem várias formas de escrever a mesma coisa, e o índice padrão as trata como palavras diferentes.

**A normalização vale só para o índice e para a pergunta.** O texto guardado e entregue ao modelo continua o oficial, com "art. 7º", "Lei nº 8.036" e "§ 1º", porque o modelo e o validador citam a norma como ela está escrita.

| Regra | Exemplo | Problema que resolve |
|---|---|---|
| "§" e "§§" viram "paragrafo" e "paragrafos" | "§ 1º" → "paragrafo 1" | O índice padrão descartava o "§" |
| "art." e "arts." viram "artigo" e "artigos" | "art. 7º" → "artigo 7" | "art" e "artigo" eram palavras diferentes |
| "nº", "n.º", "n°" e "no." antes de número são removidos | "Lei nº 8.036" → "lei 8036" | — |
| O ordinal colado ao número é removido | "7º", "7°", "7o" e "1ª" → "7" e "1" | "7º" e "7" eram palavras diferentes |
| O ponto de milhar é removido, e a barra entre números é separada | "8.036/1990" → "8036 / 1990"; "Tema 1.046" → "1046" | — |
| O numeral romano isolado vira uma marca própria | "XIII" → "inc13" | O radicalizador do português transformava "xiii" em "xii", juntando os incisos XII e XIII |
| Tudo fica em minúsculas e sem acento | "não" = "nao" | — |

**Sem stopwords.** O índice padrão em português descarta palavras como "não", "de", "a" e "o". No texto jurídico, "não" muda o sentido da regra: "é devido" e "não é devido" ficavam iguais no índice. Por isso usamos uma configuração própria (`lex_precedentes.pt_sem_stopwords`), que mantém todas as palavras e só aplica o radicalizador, que reduz "trabalhadores" e "trabalhador" à mesma raiz.

**As palavras comuns não atrapalham porque cada palavra pesa pelo IDF**, como no BM25. "De" aparece em quase todos os trechos e pesa perto de zero; "338" ou "insalubridade" são raras e pesam muito. Nenhuma palavra é descartada, mas as frequentes quase não contam.
''')
n5.md('ix_lex_dados', '''
> **Lê:** `lex_precedentes.embeddings`<br>
> **Grava:** tabela `lex_precedentes.lexico` (1.268 linhas, texto normalizado) no PostgreSQL
''')
n5.code('ix_lex', r'''
from worker.evidencia.precedentes import normalizacao as nz
print('Trechos no índice de palavras:', ix.preparar_lexico(conexao, dataset_id), f'(normalização {nz.VERSAO})')
casos = ['art. 7º, XIII, da CF', 'Lei nº 8.036/1990', 'Tema 1.046 do STF', '§§ 2º e 3º', 'Não é devido o adicional']
comparacao = []
for t in casos:
    padrao = conexao.execute("SELECT to_tsvector('portuguese', %s)::text", (t,)).fetchone()[0]
    nosso = conexao.execute('SELECT to_tsvector(%s::regconfig, %s)::text', (nz.CONFIG, nz.normalizar(t))).fetchone()[0]
    comparacao.append({'texto': t, 'índice padrão (português)': padrao, 'texto normalizado': nz.normalizar(t), 'índice LexIA (sem stopwords)': nosso})
display(pd.DataFrame(comparacao))
''')

n5.md('ix_teste_texto', '''
## 4. Testes de funcionamento

Estes testes não avaliam a qualidade da busca. Essa avaliação fica no notebook 06, com as perguntas da curadoria e o gabarito. Aqui só conferimos que o índice responde de forma coerente:
1. **Cada trecho acha a si mesmo.** O vetor de cada trecho, usado como consulta, tem que voltar em 1º lugar. Isso confere a gravação e a ordem dos vetores.
2. **Três perguntas de exemplo,** escritas para este teste (não são perguntas da curadoria), sobre temas em que já sabemos qual precedente decide. Mostramos em que posição o precedente esperado aparece na busca semântica.
3. **As mesmas perguntas na busca por palavras,** mais uma que cita a lei sem o ponto e sem o "nº" ("Lei 8036"). Ela tem que achar o texto que diz "Lei nº 8.036".
''')
n5.code('ix_teste', r'''
from pgvector.psycopg import register_vector
register_vector(conexao)
amostra = np.random.default_rng(42).choice(len(trechos), size=50, replace=False)
acertos = sum(ix.busca_semantica(conexao, dataset_id, vetores[i], k=1)[0][1] == trechos[i]['chunk_id'] for i in amostra)
print(f'1. Trecho acha a si mesmo: {acertos} de {len(amostra)}')

exemplos = [
    ('A empresa não apresentou os cartões de ponto no processo. Quem precisa provar as horas extras?', 'TST-SUM-338'),
    ('Trabalho à noite e a jornada passa das 5 da manhã. O adicional noturno vale para as horas depois das 5h?', 'TST-SUM-60'),
    ('A empresa olha dentro das bolsas dos funcionários todo dia, sem encostar neles. Isso gera dano moral?', 'TST-IRR-58'),
]
linhas = []
for pergunta, esperado in exemplos:
    q = encoder.encode([pergunta], normalize_embeddings=True)[0].astype(np.float32)
    achados = ix.busca_semantica(conexao, dataset_id, q, k=50)
    ordem_reg = list(dict.fromkeys(r for r, _, _ in achados))
    linhas.append(dict(esperado=esperado, posicao_entre_registros=(ordem_reg.index(esperado) + 1) if esperado in ordem_reg else '>50 trechos',
                       primeiro=ordem_reg[0], semelhanca_1o=round(achados[0][2], 3)))
display(pd.DataFrame(linhas))

print()
print('3. Busca por palavras (texto normalizado, sem stopwords, peso IDF):')
lex = []
for pergunta, esperado in exemplos + [('Lei 8036 saque do FGTS', 'TST-OJ-SDI1-42')]:
    achados = ix.busca_lexical(conexao, dataset_id, pergunta, k=20)
    ordem_reg = list(dict.fromkeys(r for r, _, _ in achados))
    lex.append(dict(pergunta=pergunta[:60], esperado=esperado,
                    posicao=(ordem_reg.index(esperado) + 1) if esperado in ordem_reg else '>20 trechos', primeiro=ordem_reg[0] if ordem_reg else None))
display(pd.DataFrame(lex))
''')
n5.md('ix_teste_leitura', '''
**Leitura.**

No notebook 00, essas mesmas súmulas ficavam entre a 8ª e a 3.370ª posição quando disputavam com 20 mil acórdãos. Aqui, na base separada, elas disputam só com outros precedentes. O teste é só de funcionamento. A medida que vale (Hit@1 e Hit@3 com o gabarito, e a repetição do teste de posição com o texto oficial) fica no notebook 06.

## Conclusões

- **A base `lex_precedentes` está gravada e validada:**
  - trechos e vetores BGE-M3 na mesma revisão das outras bases;
  - registros inteiros para a entrega;
  - índice para a busca por palavras, com texto normalizado ("art. 7º" = "art. 7", "Lei nº 8.036" = "Lei 8036", incisos romanos separados), sem stopwords e com peso IDF.
- **A versão é reproduzível.** O hash do manifesto amarra modelo, revisão, trechos e vetores, e o JSONL de trechos é conferido com o manifesto do 04.
- **Próximos passos:**
  1. Notebook 06: avaliação da recuperação.
  2. Integração da base como terceira fonte da busca, com cota própria, e citação pelo nome no prompt.
''')
n5.gravar()
