"""Cria os notebooks 01 (auditoria), 02 (EDA) e 03 (limpeza e estruturação) de notebooks/05_docs_precedentes/.

Fluxo dos dados (fora do Git: data/raw, data/interim e data/processed estão no .gitignore):
  data/raw/precedentes/*.pdf                        PDFs recebidos, sem edição
  data/interim/precedentes/verbetes_brutos.jsonl    01: um bloco bruto por súmula, OJ ou tema
  data/processed/precedentes/precedentes_tst.jsonl  03: JSONL único e estruturado (entra no chunking, notebook 04)
Relatórios versionados (só identificadores, contagens e hashes): reports/precedentes/{auditoria,eda,estruturacao}/

Execução: python scripts/executar_notebook_integracao.py notebooks/05_docs_precedentes/<notebook>.ipynb
"""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
PASTA = ROOT / 'notebooks/05_docs_precedentes'

SETUP = r'''
from pathlib import Path
import json, sys
import pandas as pd
import matplotlib.pyplot as plt
from IPython.display import display, Markdown

ROOT = next(p for p in (Path.cwd(), *Path.cwd().parents) if (p / 'src/precedentes').exists())
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
pd.set_option('display.max_colwidth', 120)
pd.set_option('display.width', 250)
pd.set_option('display.max_columns', None)
RAW = ROOT / 'data/raw/precedentes'
BRUTOS = ROOT / 'data/interim/precedentes/verbetes_brutos.jsonl'
SAIDA_JSONL = ROOT / 'data/processed/precedentes/precedentes_tst.jsonl'
REL = ROOT / 'reports/precedentes'
'''


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


# ---------------------------------------------------------------------------------------------------------------
# 01 - Auditoria
# ---------------------------------------------------------------------------------------------------------------
n1 = Notebook('01_auditoria_precedentes.ipynb')
n1.md('aud_intro', '''
# 01 · Auditoria dos documentos de precedentes

Primeiro notebook da base de precedentes do TST. O `00_introducao_precedentes.ipynb` explica por que essa base existe. Aqui conferimos **o que foi recebido** antes de extrair qualquer texto.

**O que este notebook faz:**
1. **Inventário:** registra arquivo, emissor, data de referência, páginas, camada de texto e hash SHA-256 de cada PDF. O hash identifica a versão usada.
2. **Papel de cada documento:** define o que entra na base, o que serve só para conferir a vigência e o que vai para outra base.
3. **Extração bruta:** separa um bloco por súmula, OJ ou tema, sem limpeza.
4. **Integridade da extração:** confere se a numeração está completa e sem repetições.
5. **Vigência:** compara a coletânea, atualizada até 2024, com a notícia de cancelamentos.

**Ordem da pasta:**

| Notebook | Conteúdo | Situação |
|---|---|---|
| `00_introducao_precedentes` | Por que criar a terceira base: teste de posição e exemplos das 25 respostas | pronto |
| `01_auditoria_precedentes` | Este notebook | pronto |
| `02_eda_precedentes` | Volume, tamanho, situação, estrutura e normas citadas | pronto |
| `03_limpeza_estruturacao_precedentes` | Campos, vigência e o JSONL único | pronto |
| `04_chunking_precedentes` | Um trecho por enunciado ou item, com cabeçalho (1.268 trechos) | pronto |
| `05_embeddings_indexacao_precedentes` | BGE-M3 e schema `lex_precedentes` validado | pronto |
| `06_avaliacao_recuperacao_precedentes` | Hit@k com o precedente esperado | a fazer |
''')
n1.code('aud_setup', SETUP + r'''
from src.precedentes import documentos, extracao
(REL / 'auditoria').mkdir(parents=True, exist_ok=True)
''')

n1.md('aud_inv_texto', '''
## 1. Inventário dos arquivos

Os 10 PDFs enviados estão em `data/raw/precedentes/` exatamente como foram baixados. Eles ficam fora do Git porque são grandes: o maior tem 238 MB. O inventário registra o hash de cada um para que a extração possa ser refeita com a mesma versão.

Dois arquivos terminam em "(1)": a coletânea do TRT-3 e o índice de repercussão geral foram baixados duas vezes. O hash mostra que são cópias byte a byte dos originais. Eles ficam registrados como `duplicata` e não são lidos. Por isso, há **10 arquivos e 8 documentos distintos**.
''')
n1.code('aud_inv', r'''
inv = documentos.inventario(RAW)
print(f'{len(inv)} PDFs na pasta · faltando do catálogo: {inv.attrs["faltando"] or "nenhum"}')
repetidos = inv[inv.sha256.duplicated(keep=False)].sort_values('sha256')
print(f'Arquivos com hash repetido: {len(repetidos)} · documentos distintos: {inv.sha256.nunique()}')
print('Duplicatas confirmadas pelo hash:', ', '.join(repetidos[repetidos.papel == "duplicata"].sigla))
display(inv[['sigla', 'emissor', 'data_referencia', 'paginas', 'tamanho_mb', 'camada_texto', 'paginas_sem_texto', 'papel']]
        .assign(sha256=inv.sha256.str[:12] + '…'))
inv.drop(columns=['uso']).to_csv(REL / 'auditoria/inventario_documentos.csv', index=False, encoding='utf-8')
''')

n1.md('aud_papel_texto', '''
## 2. O papel de cada documento

Os documentos têm três destinos diferentes. A decisão fica registrada aqui e pode ser revista.
''')
n1.code('aud_papel', r'''
display(inv[['sigla', 'papel', 'destino', 'uso']])
''')
n1.md('aud_papel_leitura', '''
**Resumo das decisões:**

- **Entram na base:**
  - **Coletânea do TRT-3 (06/2024):** súmulas e OJs do TST. É a única fonte recebida que traz todos os verbetes no formato oficial, com situação e histórico.
  - **Índice de IRR do TST (19/11/2026):** temas repetitivos.
- **Serve só como alerta de vigência:** a **notícia de cancelamento**. Não é documento oficial e foi gerada em 22/11/2026 por uma ferramenta automática, sem data de publicação nem link para a resolução. Por isso não altera a situação oficial (seção 5).
- **Ficam para depois:**
  - **Índice de repercussão geral do STF:** entra na etapa do STF.
  - **Acórdão 168:** a tese dele, a reafirmação da Súmula 462, já está no índice de IRR, e o documento contém nomes das partes.
- **Não entram:**
  - **Coletânea do TRT-2 (2021):** é mais antiga e repete a do TRT-3.
  - **EC 141/2026 e autógrafo da Câmara:** são norma constitucional, não precedente. A EC 141 foi aplicada à **base de legislação** numa versão nova (`ec141_2026`), com o art. 7º atualizado e os 10 artigos da emenda (`scripts/atualizar_legislacao_ec141.py`). A cópia bruta da Constituição, mostrada na célula abaixo, não foi editada e guarda a redação anterior.
- **Cópias "(1)":** duas cópias idênticas, registradas como `duplicata`.
''')
n1.code('aud_ec141', r'''
cf = ROOT / 'data/raw/legislacao/constituicao/constituicao-1988.md'
if cf.exists():
    linhas = [l.strip() for l in cf.read_text(encoding='utf-8').splitlines() if l.startswith(('XIII - duração', 'XV - repouso'))]
    print('Art. 7º na cópia bruta da Constituição (redação anterior; a busca usa a versão ec141_2026):')
    for l in linhas:
        print('  ', l[:150])
else:
    print('Cópia local da legislação não encontrada; conferir na base de legislação.')
''')

n1.md('aud_paginas_texto', '''
## 3. Que parte de cada PDF é usada

| Documento | Páginas | Conteúdo | Fica de fora |
|---|---|---|---|
| Coletânea TRT-3 | 65-256 | Súmulas (65-152), OJs do Tribunal Pleno/Órgão Especial (154-155), SBDI-1 (157-212), SBDI-1 transitória (214-225), SBDI-2 (227-250) e SDC (252-256) | A 1ª parte (TRT-3) e os temas de IRR de 2024, substituídos pelo índice de 2026. Também os precedentes normativos e os índices |
| Índice de IRR | 12-121 | Parte temática: cada tema com título, questão jurídica, tese e referências | Apresentação, glossário e a tabela final, que repete os mesmos temas em colunas |

Cada verbete da coletânea começa com o código oficial (`SUM-338`, `OJ-SDI1-394`...). No índice de IRR, a **cor do título** indica a situação do tema, segundo a legenda da página 2:
- azul: tese fixada;
- mostarda: afetado, ainda sem tese;
- vermelho: tese superada.
''')
n1.code('aud_sumario', r'''
pag = extracao.texto_paginas(RAW / 'arquivo-versao-eletronica-28-6-2024-1.pdf', [4])[4]
print(pag[pag.find('2ª PARTE'):pag.find('ÍNDICES')].strip())
''')

n1.md('aud_extr_texto', '''
## 4. Extração bruta e integridade da numeração

A extração só separa os blocos, sem limpar nada. A limpeza é feita no notebook 03. A numeração de cada série deve ser contínua, de 1 até o maior número, sem faltas nem repetições. Os cancelados continuam listados na coletânea com o próprio número, então uma falta indicaria um verbete perdido na leitura.

Durante o desenvolvimento, essa conferência pegou três problemas na leitura do PDF, já corrigidos:
- códigos colados no título, como `SUM-418MANDADO` e `SUM- 43`;
- redações antigas no histórico que pareciam verbetes novos, como `OJ-SDC-6 –Dissídio...`;
- títulos de tema justificados palavra por palavra, em que o número ficava em outro bloco.
''')
n1.code('aud_extr', r'''
verbetes = extracao.verbetes_tst_trt3(RAW / 'arquivo-versao-eletronica-28-6-2024-1.pdf')
temas = extracao.temas_irr(RAW / 'Índice Temático IRRs - versão Novembro 19_11_2026.pdf')

def numeracao(registros, chave):
    linhas = []
    for serie, grupo in pd.DataFrame(registros).groupby(chave):
        nums = grupo.numero.tolist()
        faltam = sorted(set(range(1, max(nums) + 1)) - set(nums))
        linhas.append(dict(serie=serie, blocos=len(nums), distintos=len(set(nums)), maior_numero=max(nums),
                           faltando=len(faltam), numeros_faltando=', '.join(map(str, faltam[:20])) or '-'))
    return pd.DataFrame(linhas)

num_v = numeracao(verbetes, 'serie')
num_t = numeracao(temas, 'subtipo')
print(f'Súmulas e OJs: {len(verbetes)} blocos · temas: {len(temas)} blocos ({len({t["codigo"] for t in temas})} temas distintos)')
display(num_v)
display(num_t)
pd.concat([num_v.assign(fonte='TRT3_2024'), num_t.assign(fonte='IRR_2026')]).to_csv(
    REL / 'auditoria/numeracao_series.csv', index=False, encoding='utf-8')
''')
n1.md('aud_extr_leitura', '''
**Leitura:**
- **Súmulas e OJs:** as seis séries estão completas, sem faltas nem repetições. Cada número de 1 ao último aparece uma única vez.
- **Temas repetitivos:** os 317 IRR e os 2 IRDR estão completos. No IAC, a contagem mostra o nº 1 como faltante, mas o próprio índice remissivo do PDF só lista os IAC 002 e 003. O nº 1 não está no documento, então não houve perda na leitura. Há mais blocos do que temas porque o índice repete o tema em cada assunto a que ele pertence e na seção de suspensões. O notebook 03 junta essas repetições.
''')

n1.md('aud_vig_texto', '''
## 5. Vigência: a coletânea de 2024 diante da notícia de cancelamentos

A coletânea foi atualizada até **28/06/2024**. A notícia recebida diz que o TST cancelou 36 enunciados, mas só nomeia 26. Conferimos cada um desses 26 na coletânea:
- se o enunciado existe;
- se a coletânea já o dava como cancelado.
''')
n1.code('aud_vig', r'''
noticia = pd.DataFrame(extracao.cancelamentos_noticia(RAW / 'cancelamento_36_enunciados_tst.pdf'))
cabecalho = {v['codigo']: v['texto_bruto'][:400].lower() for v in verbetes}
noticia['na_coletanea'] = noticia.codigo.map(lambda c: c in cabecalho)
noticia['ja_cancelado_em_2024'] = noticia.codigo.map(lambda c: 'cancelad' in ' '.join(cabecalho.get(c, '').split('\n')[:3]))
print(f'Itens nomeados na notícia: {len(noticia)} · na coletânea: {noticia.na_coletanea.sum()} '
      f'(o PN 100 é precedente normativo, fora do escopo) · já cancelados em 2024: {noticia.ja_cancelado_em_2024.sum()}')
display(noticia[['codigo', 'titulo_noticia', 'alcance', 'na_coletanea', 'ja_cancelado_em_2024']])
noticia.to_csv(REL / 'auditoria/conferencia_noticia_cancelamento.csv', index=False, encoding='utf-8')
''')
n1.md('aud_vig_leitura', '''
**Leitura:** quase todos os enunciados da notícia aparecem como **vigentes** na coletânea de 2024. Ou seja, se a notícia estiver certa, a coletânea está desatualizada justamente em temas comuns nas perguntas:
- intervalo intrajornada (Súmula 437);
- jornada 12x36 (Súmula 444);
- horas in itinere (Súmula 90);
- terceirização (Súmula 331, I);
- preposto (Súmula 377).

**Decisão (aplicada no notebook 03):**
- a situação oficial continua sendo a da coletânea;
- cada enunciado citado na notícia recebe um **alerta de vigência**;
- os enunciados dados como cancelados **por inteiro** ficam **fora da busca** até a resolução oficial do TST ser conferida. Citar como regra uma súmula cancelada é pior do que não ter a súmula;
- os enunciados com cancelamento **parcial**, como a Súmula 6 em alguns itens e as Súmulas 331 e 372 no item I, continuam na busca, com o alerta.

**Pendente:** o livro oficial de súmulas e OJs do TST atualizado em 2026, ou a resolução dos cancelamentos. Com ele, este notebook roda de novo e os alertas viram situação oficial.
''')

n1.md('aud_grava_texto', '''
## 6. Gravação dos blocos brutos e manifesto

Os blocos brutos vão para `data/interim/precedentes/`, fora do Git, e são a entrada da EDA e da limpeza. O manifesto, que é versionado, registra o hash de cada PDF de origem e o hash do arquivo bruto. Com isso, qualquer mudança nos documentos ou no extrator aparece na próxima execução.
''')
n1.code('aud_grava', r'''
import hashlib
BRUTOS.parent.mkdir(parents=True, exist_ok=True)
sha = dict(zip(inv.arquivo, inv.sha256))
with BRUTOS.open('w', encoding='utf-8') as f:
    for v in verbetes:
        f.write(json.dumps(dict(v, fonte='TRT3_2024'), ensure_ascii=False) + '\n')
    for t in temas:
        f.write(json.dumps(dict(t, fonte='IRR_2026'), ensure_ascii=False) + '\n')
manifesto = dict(
    fontes={s: dict(arquivo=a, sha256=sha[a]) for s, a in [('TRT3_2024', 'arquivo-versao-eletronica-28-6-2024-1.pdf'),
                                                          ('IRR_2026', 'Índice Temático IRRs - versão Novembro 19_11_2026.pdf'),
                                                          ('NOTICIA_CANCELAMENTO', 'cancelamento_36_enunciados_tst.pdf')]},
    paginas=dict(TRT3_2024=extracao.PAGINAS_TST_TRT3, IRR_2026=extracao.PAGINAS_TEMAS_IRR),
    blocos=dict(verbetes=len(verbetes), temas=len(temas)),
    brutos_sha256=hashlib.sha256(BRUTOS.read_bytes()).hexdigest())
(REL / 'auditoria/manifesto_auditoria.json').write_text(json.dumps(manifesto, indent=2, ensure_ascii=False), encoding='utf-8')
print(json.dumps(manifesto, indent=2, ensure_ascii=False))
''')
n1.md('aud_conclusao', '''
## Conclusões

- **Recebido e conferido:** 10 PDFs, com hash. São 8 documentos distintos e 2 cópias idênticas, assim distribuídos:
  - 2 fontes principais;
  - 1 fonte de vigência;
  - 2 referências;
  - 3 fora do escopo.
- **Extração íntegra:**
  - 463 súmulas e 709 OJs, em seis séries completas;
  - 321 temas repetitivos (317 IRR, 2 IAC e 2 IRDR), sem falta de numeração. O IAC 1 não consta do índice.
- **Risco principal:** a vigência. A coletânea é de 06/2024, e a notícia aponta cancelamentos posteriores. A solução provisória é a quarentena; a definitiva é o livro oficial de 2026.
- **Fora desta base:** a EC 141/2026, que foi aplicada à **base de legislação**. O art. 7º da Constituição ganhou uma versão nova, `ec141_2026`, com a jornada de 40 horas progressiva e os dois dias de repouso. A célula da seção 2 mostra a redação antiga, que continua guardada na versão `original`.

Próximo: `02_eda_precedentes.ipynb`.
''')
n1.gravar()

# ---------------------------------------------------------------------------------------------------------------
# 02 - EDA
# ---------------------------------------------------------------------------------------------------------------
n2 = Notebook('02_eda_precedentes.ipynb')
n2.md('eda_intro', '''
# 02 · Análise exploratória dos precedentes

Este notebook explora os blocos brutos gravados pela auditoria (notebook 01), antes da limpeza, para responder:
1. **Quanto tem de cada tipo**, e quanto ainda vale.
2. **Qual o tamanho dos textos em tokens**, o que define o chunking do notebook 04.
3. **Que ruído o texto bruto carrega:** histórico, notas do TRT-3, origens "(ex-...)" e cabeçalhos. Isso define as regras do notebook 03.
4. **Se a cor do título dos temas bate com o texto da tese.**
5. **Quais normas os precedentes interpretam.**
6. **Se os precedentes que faltaram nas 25 respostas do advogado estão nos documentos.**
''')
n2.code('eda_setup', SETUP + r'''
import re
from collections import Counter
brutos = pd.read_json(BRUTOS, lines=True)
verb = brutos[brutos.fonte == 'TRT3_2024'].copy()
tem = brutos[brutos.fonte == 'IRR_2026'].copy()
(REL / 'eda').mkdir(parents=True, exist_ok=True)
print(f'{len(verb)} blocos de súmulas e OJs · {len(tem)} blocos de temas ({tem.codigo.nunique()} temas distintos)')
''')

n2.md('eda_vol_texto', '''
## 1. Volume por tipo e situação preliminar

Aqui a situação é **preliminar**: um verbete conta como cancelado quando o cabeçalho diz "cancelada" ou "cancelamento". Nos temas, ela vem da cor do título. A regra completa fica no notebook 03, que trata casos como o cancelamento de um item só e os verbetes convertidos em outro.
''')
n2.code('eda_vol', r'''
def cabecalho(t):
    return ' '.join(t.split('\n')[:4]).lower()
verb['cancelado_prelim'] = verb.texto_bruto.map(lambda t: bool(re.search(r'\(cancelad|cancelamento mantido', cabecalho(t))))
rotulo = {'SUM': 'Súmulas', 'OJ-SDI1': 'OJ SBDI-1', 'OJ-SDI2': 'OJ SBDI-2', 'OJ-SDI1T': 'OJ SBDI-1 transitória',
          'OJ-SDC': 'OJ SDC', 'OJ-TP/OE': 'OJ Pleno/Órgão Especial'}
vol = verb.groupby('serie').agg(total=('numero', 'size'), canceladas=('cancelado_prelim', 'sum'))
vol['ativas'] = vol.total - vol.canceladas
vol = vol.rename(index=rotulo).sort_values('total')
temas_unicos = tem.drop_duplicates('codigo')
cores = temas_unicos.situacao_cor.value_counts()
display(vol)
print('Temas por cor do título:', cores.to_dict())

fig, ax = plt.subplots(figsize=(8, 3.6))
ax.barh(vol.index, vol.ativas, color='#2f6db5', label='ativas')
ax.barh(vol.index, vol.canceladas, left=vol.ativas, color='#c9c9c9', label='canceladas')
for i, (a, c) in enumerate(zip(vol.ativas, vol.canceladas)):
    ax.text(a + c + 4, i, f'{a} + {c}', va='center', fontsize=9)
ax.set_xlim(0, vol.total.max() * 1.18)
ax.set_title('Súmulas e OJs do TST na coletânea (06/2024)')
ax.legend(loc='lower right', frameon=False)
ax.spines[['top', 'right']].set_visible(False)
fig.tight_layout()
fig.savefig(REL / 'eda/volume_por_serie.png', dpi=110)
display(fig); plt.close(fig)
''')
n2.md('eda_vol_leitura', '''
**Leitura:** cerca de um terço dos verbetes já estava cancelado em 2024, a maioria OJs convertidas em súmulas. Eles **não podem** ser entregues como regra. Ficam registrados porque os acórdãos da base de jurisprudência ainda os citam, e uma resposta pode precisar dizer que tal OJ foi cancelada. Nos temas, a maior parte já tem tese fixada, e cerca de um terço está afetado, ainda sem tese.
''')

n2.md('eda_tam_texto', '''
## 2. Tamanho dos textos em tokens

O tamanho é medido com o tokenizador do BGE-M3, na mesma revisão da busca. Se o modelo não estiver em cache, a medida é estimada pelo número de palavras. O texto bruto ainda inclui o histórico e as notas, por isso também medimos o enunciado sem o histórico. Esse recorte é próximo do que vai para a busca.
''')
n2.code('eda_tam', r'''
import os
os.environ.setdefault('HF_HUB_OFFLINE', '1')
try:
    from transformers import AutoTokenizer
    from src.integracao.recuperacao import MODELO, REVISAO
    tok = AutoTokenizer.from_pretrained(MODELO, revision=REVISAO, local_files_only=True)
    contar = lambda t: len(tok(t, add_special_tokens=False)['input_ids'])
    medida = f'tokens do {MODELO}'
except Exception as erro:
    contar = lambda t: int(len(t.split()) * 1.6)
    medida = f'estimativa por palavras ({type(erro).__name__})'

def sem_historico(t):
    t = re.split(r'\bHistórico\s*:?', t, maxsplit=1)[0]
    return '\n'.join(l for l in t.split('\n') if not l.strip().startswith('•'))

verb['tokens_bruto'] = verb.texto_bruto.map(contar)
verb['tokens_enunciado'] = verb.texto_bruto.map(sem_historico).map(contar)
tem_u = tem.sort_values('texto_bruto', key=lambda s: s.str.len()).drop_duplicates('codigo', keep='last').copy()
tem_u['tokens_bruto'] = tem_u.texto_bruto.map(contar)
tem_u['tokens_enunciado'] = tem_u.tokens_bruto
ativos = verb[~verb.cancelado_prelim]
tab = pd.concat([ativos.assign(grupo=ativos.serie.map(lambda s: 'Súmulas' if s == 'SUM' else 'OJs')), tem_u.assign(grupo='Temas')])
resumo_tok = tab.groupby('grupo').tokens_enunciado.describe(percentiles=[.5, .9, .99])[['count', 'mean', '50%', '90%', '99%', 'max']].round(0)
print('Medida:', medida, '· só verbetes ativos e temas')
display(resumo_tok)
print('Acima de 512 tokens:', (tab.tokens_enunciado > 512).groupby(tab.grupo).sum().to_dict())
resumo_tok.to_csv(REL / 'eda/tokens_por_tipo.csv', encoding='utf-8')

fig, ax = plt.subplots(figsize=(8, 3.4))
for grupo, cor in [('Súmulas', '#2f6db5'), ('OJs', '#7aa6d8'), ('Temas', '#d08a2e')]:
    ax.hist(tab[tab.grupo == grupo].tokens_enunciado.clip(upper=1200), bins=40, alpha=.6, color=cor, label=grupo)
ax.axvline(512, color='#444', lw=1, ls='--'); ax.text(520, ax.get_ylim()[1] * .9, '512 tokens', fontsize=8)
ax.set_xlabel('tokens do enunciado (corte visual em 1.200)'); ax.set_ylabel('verbetes')
ax.set_title('Tamanho dos enunciados ativos')
ax.legend(frameon=False); ax.spines[['top', 'right']].set_visible(False)
fig.tight_layout(); fig.savefig(REL / 'eda/tokens_por_tipo.png', dpi=110)
display(fig); plt.close(fig)
''')
n2.md('eda_tam_leitura', '''
**Leitura:** os precedentes são **curtos**, e a grande maioria cabe inteira num único trecho. Os acórdãos da base de jurisprudência têm milhares de tokens; um precedente tem, em geral, poucas centenas. Para o chunking (notebook 04), isso significa:
- **um trecho por enunciado** como regra;
- divisão **por item** (I, II, III...) só nas súmulas longas, repetindo o título em cada item;
- os poucos temas longos, com teses de várias partes, são divididos pelos números da tese.
''')

n2.md('eda_ruido_texto', '''
## 3. O que o texto bruto carrega além do enunciado

Contamos em quantos verbetes ativos aparece cada elemento que **não** é a regra. Cada linha da tabela vira uma regra do notebook 03.
''')
n2.code('eda_ruido', r'''
padroes = {
    'histórico de redações ("Histórico:")': r'\bHistórico\s*:?',
    'nota remissiva ao TRT-3 (linha com "•")': r'^\s*•',
    'origem do item ("(ex-Súmula...", "(ex-OJ...")': r'\(ex-',
    'enunciado em itens (I -, II -...)': r'(?:^|\s)II\s*[-–]\s',
    'remissão a outro precedente ("Vide", "Tema ... IRR")': r'\(Vide|Tema \d+ IRR',
    'hifenização no fim da linha': r'[a-zà-ú]-\n[a-zà-ú]',
}
ruido = pd.DataFrame([dict(elemento=k, verbetes=int(ativos.texto_bruto.str.contains(p, regex=True, flags=re.M).sum()))
                      for k, p in padroes.items()])
ruido['% dos ativos'] = (100 * ruido.verbetes / len(ativos)).round(1)
display(ruido)
ruido.to_csv(REL / 'eda/ruido_texto_bruto.csv', index=False, encoding='utf-8')
print('\nExemplo (Súmula 60 bruta):\n')
print(verb.set_index('codigo').loc['SUM-60', 'texto_bruto'])
''')
n2.md('eda_ruido_leitura', '''
**Leitura:** o exemplo da Súmula 60 mostra o problema. Além do enunciado, o bloco traz:
- a **redação original**, que já não vale;
- uma nota do TRT-3 ("SÚM. 29, OJ-Turmas 24...").

Se o histórico entrar na busca, o modelo pode citar uma redação revogada como se fosse a atual. Por isso, no notebook 03:
- o histórico vai para um campo à parte, fora do texto de busca;
- as notas do TRT-3 também vão para um campo à parte;
- as origens "(ex-...)" saem do texto de busca e ficam no texto oficial.
''')

n2.md('eda_temas_texto', '''
## 4. Temas: a cor do título confere com a tese?

A situação do tema pode ser lida de duas formas: pela cor do título ou pelo texto da tese ("Ainda não fixada", "Superada"). Comparamos as duas para ver qual é mais confiável.
''')
n2.code('eda_temas', r'''
def sit_tese(t):
    m = re.search(r'^Tese\s*:\s*(.*)$', t, re.M)
    if not m or m.group(1).lower().startswith('ainda não fixada'):
        return 'sem tese'
    return 'superada' if m.group(1).lower().startswith('superada') else 'tese fixada'
tem_u['pela_tese'] = tem_u.texto_bruto.map(sit_tese)
cruz = pd.crosstab(tem_u.situacao_cor, tem_u.pela_tese, margins=True, margins_name='total')
display(cruz)
diverg = tem_u[(tem_u.situacao_cor == 'mostarda') & (tem_u.pela_tese == 'tese fixada')]
print('Cor mostarda, mas com tese no texto:', ', '.join(diverg.codigo))
cruz.to_csv(REL / 'eda/temas_cor_vs_tese.csv', encoding='utf-8')
oc = tem.groupby('codigo').size()
print(f'\nOcorrências por tema no índice: média {oc.mean():.1f} · máximo {oc.max()} · temas com aviso de suspensão: '
      f'{tem.groupby("codigo").texto_bruto.apply(lambda s: s.str.contains("AVISO").any()).sum()}')
assuntos = tem[~tem.assunto.fillna('').str.startswith('INCIDENTES')].assunto.value_counts().head(12)
display(assuntos.rename('temas').to_frame())
''')
n2.md('eda_temas_leitura', '''
**Leitura:** a cor e o texto concordam em quase todos os temas. A exceção são poucos temas em mostarda que já trazem a tese escrita, provavelmente julgados depois de a cor ser atribuída. Por isso, **o texto da tese decide a situação** e a cor serve como conferência.

Os assuntos com mais temas são justamente os mais frequentes nas perguntas:
- horas extras e jornada;
- negociação coletiva, muito por causa do Tema 1.046 do STF;
- adicionais;
- dispensa.
''')

n2.md('eda_normas_texto', '''
## 5. Que normas os precedentes interpretam

Contamos os artigos da CLT citados nos enunciados ativos e nas referências dos temas. Essa ligação permite, mais adiante, buscar o precedente pelo artigo da lei que a pergunta menciona.
''')
n2.code('eda_normas', r'''
ART_CLT = re.compile(r'art(?:igo)?s?\.?\s*(\d{1,3}(?:-[A-Z])?)(?:[^.;]{0,40}?)\s*,?\s*da CLT|CLT\s*[:,]?\s*arts?\.?\s*(\d{1,3}(?:-[A-Z])?)', re.I)
def artigos(t):
    return {a or b for a, b in ART_CLT.findall(t)}
textos = pd.concat([ativos.texto_bruto.map(sem_historico), tem_u.texto_bruto])
cont = Counter(a for t in textos for a in artigos(t))
top = pd.DataFrame(cont.most_common(15), columns=['art. da CLT', 'precedentes'])
display(top.T)
print(f'Precedentes ativos que citam ao menos um artigo da CLT: {sum(bool(artigos(t)) for t in textos)} de {len(textos)}')
top.to_csv(REL / 'eda/artigos_clt_mais_citados.csv', index=False, encoding='utf-8')
reafirma = tem_u.texto_bruto.str.contains(r'Reafirmação|reafirma', case=False).sum()
print(f'Temas que reafirmam súmula ou OJ (reafirmação de jurisprudência): {reafirma}')
''')

n2.md('eda_cobertura_texto', '''
## 6. Os precedentes que faltaram nas 25 respostas estão aqui?

O notebook 00 lista os precedentes que o advogado revisor apontou como decisivos nas respostas reprovadas. Conferimos se cada um está nos documentos recebidos e se está ativo. As perguntas não aparecem aqui, porque são protegidas.
''')
n2.code('eda_cobertura', r'''
esperados = [('P6', 'SUM-338', 'I'), ('P7', 'SUM-276', None), ('P10', 'SUM-378', 'II'), ('P11', 'SUM-6', 'VIII'),
             ('P24', 'SUM-60', 'II'), ('P3', 'SUM-45', None)]
idx = verb.set_index('codigo')
linhas = []
for p, cod, item in esperados:
    t = idx.texto_bruto.get(cod, '')
    linhas.append(dict(resposta=p, precedente=cod + (f', {item}' if item else ''), encontrado=bool(t),
                       ativo=bool(t) and not idx.cancelado_prelim.get(cod, True),
                       item_presente=(item is None) or bool(re.search(rf'(?:^|\s){item}\s*[-–]', t))))
revista = tem_u[tem_u.texto_bruto.str.contains(r'revista (?:visual|íntima|de bolsas|pessoal)|pertences', case=False)]
for _, r in revista.iterrows():
    linhas.append(dict(resposta='P23', precedente=r.codigo, encontrado=True, ativo=r.pela_tese == 'tese fixada', item_presente=True))
cob = pd.DataFrame(linhas)
display(cob)
cob.to_csv(REL / 'eda/cobertura_precedentes_respostas.csv', index=False, encoding='utf-8')
print('Fora desta base: P4 (ADI 5766 do STF) fica para a etapa do STF.')
''')
n2.md('eda_cobertura_leitura', '''
**Leitura:** os precedentes das respostas reprovadas estão nos documentos, ativos e com o item certo:
- Súmula 338, I;
- Súmula 276;
- Súmula 378, II;
- Súmula 6, VIII;
- Súmula 60, II;
- Súmula 45.

A tese sobre revista de pertences está no índice de IRR. Só a P4, que depende de uma decisão do STF, fica de fora. Assim, a base cobre 7 dos 8 casos em que faltou o precedente.

## Conclusões para a limpeza (notebook 03)

1. **Situação:** é preciso uma regra mais completa que a preliminar, que trate cancelamento de item, conversão em outro verbete e quarentena dos cancelamentos noticiados.
2. **Texto de busca:** só o enunciado vigente, sem o histórico, sem as notas do TRT-3 e sem as origens "(ex-...)".
3. **Itens:** separar os itens (I, II...) para o chunking.
4. **Temas:** um registro por tema, juntando as repetições. A situação vem da tese, e a cor serve de conferência. Os avisos de suspensão ficam num campo à parte.
5. **Tamanho:** os textos são curtos, e o chunking pode usar um trecho por enunciado ou por item.
''')
n2.gravar()

# ---------------------------------------------------------------------------------------------------------------
# 03 - Limpeza e estruturação
# ---------------------------------------------------------------------------------------------------------------
n3 = Notebook('03_limpeza_estruturacao_precedentes.ipynb')
n3.md('lim_intro', '''
# 03 · Limpeza e estruturação dos precedentes

Este notebook transforma os blocos brutos da auditoria num **JSONL único**, `data/processed/precedentes/precedentes_tst.jsonl`, com um registro por súmula, OJ ou tema. Esse arquivo é a entrada do chunking (notebook 04).

**Regras de limpeza (definidas a partir da EDA):**

| Problema no bruto | Regra |
|---|---|
| Linha quebrada e hifenização no fim da linha | Juntar as linhas. "jorna-\\nda" vira "jornada", e "ex-\\nSúmula" mantém o hífen |
| Cabeçalho e rodapé de página ("SÚMULAS - TST", "SUMÁRIO") | Removidos já na extração |
| Parêntese no título, como "(ART. 612 DA CLT)", e parêntese de situação, como "(cancelada)" | O parêntese em maiúsculas é parte do título. Os símbolos "º" e "ª" não contam como minúscula. Os parênteses de situação são lidos em sequência, porque às vezes há dois seguidos, como "(nova redação) ... (cancelada)", e o último é o que vale. Um parêntese só com a publicação, como "(DEJT ...)", não é situação |
| Publicação ("- Res. 129/2005, DJ 20, 22 e 25.04.2005") | Retirada do enunciado |
| Histórico de redações | Campo `historico`, fora do texto de busca |
| Notas remissivas ao TRT-3 ("• SÚM. 29 TRT3") | Campo `remissoes_trt3` |
| Origem do item ("(ex-OJ nº 234 da SBDI-1...)") | Mantida em `texto` (oficial) e retirada de `texto_busca` |
| Itens I, II, III... (também no formato "I.", como na Súmula 85) | Lista `itens` |
| Tema repetido em vários assuntos | Um registro por tema, com os `assuntos` e as `paginas` reunidos |
| Número da página colado na tese ("Ainda não fixada. 21") | Corrigido |
| Faixa "IRR com determinação de suspensão" | Campo `avisos` |

**Vigência:**

| Situação | Quando | Entra na busca? |
|---|---|---|
| `vigente` | Súmula ou OJ sem cancelamento no cabeçalho, inclusive quando só um item foi cancelado | sim |
| `cancelada` | O cabeçalho diz cancelada ou cancelamento, ou o verbete não tem enunciado porque foi convertido em outro | não, mas fica registrada |
| `suspensa` | Súmula com eficácia ou aplicação suspensa por decisão do STF, como as Súmulas 228 e 277 | não, mas fica registrada |
| `tese_fixada` | Tema com tese no texto | sim |
| `afetado_sem_tese` | Tese "Ainda não fixada". Útil para responder que a questão está pendente no TST | sim |
| `tese_superada` | Tese "Superada" | não |
| alerta da notícia | Cancelamento noticiado sem fonte oficial. A situação oficial não muda | integral: **não** (quarentena); parcial: sim, com o alerta |
''')
n3.code('lim_setup', SETUP + r'''
from src.precedentes import documentos, extracao, estruturacao as est
brutos = [json.loads(l) for l in BRUTOS.read_text(encoding='utf-8').splitlines()]
manifesto = json.loads((REL / 'auditoria/manifesto_auditoria.json').read_text(encoding='utf-8'))
inv = {c['sigla']: c for c in documentos.CATALOGO}
def fonte(sigla):
    return dict(sigla=sigla, arquivo=inv[sigla]['arquivo'], sha256=manifesto['fontes'][sigla]['sha256'],
                data_referencia=inv[sigla]['data_referencia'])
alertas = {a['codigo']: a for a in extracao.cancelamentos_noticia(RAW / 'cancelamento_36_enunciados_tst.pdf')}
(REL / 'estruturacao').mkdir(parents=True, exist_ok=True)
print(f"{len(brutos)} blocos brutos · alertas da notícia: {len(alertas)}")
''')

n3.md('lim_estr_texto', '## 1. Estruturação')
n3.code('lim_estr', r'''
verbetes = [est.estruturar_verbete(b, fonte('TRT3_2024'), alertas) for b in brutos if b['fonte'] == 'TRT3_2024']
temas = est.estruturar_temas([b for b in brutos if b['fonte'] == 'IRR_2026'], fonte('IRR_2026'))
registros = verbetes + temas
df = pd.DataFrame(registros)
print(f'{len(verbetes)} súmulas e OJs + {len(temas)} temas = {len(registros)} registros')
resumo = pd.crosstab(df.tipo, df.situacao, margins=True, margins_name='total')
display(resumo)
print('Entram na busca:', df.buscavel.groupby(df.tipo).sum().to_dict(), '· total', int(df.buscavel.sum()))
''')

n3.md('lim_antes_texto', '''
## 2. Antes e depois: exemplos

Mostramos um exemplo de cada caso:

| Registro | Caso |
|---|---|
| Súmula 338 | Enunciado com itens |
| OJ 394 da SBDI-1 | Parêntese só com a publicação |
| Súmula 221 | Cancelamento de um item só, então continua vigente |
| OJ 27 da SBDI-1 | Convertida em súmula, então fica cancelada |
| OJ 21 da SDC | Título com parêntese em maiúsculas |
| Tema 128 | Tese fixada |
| Tema 43 | Afetado, ainda sem tese, com aviso de suspensão |
''')
n3.code('lim_antes', r'''
por_id = {r['id']: r for r in registros}
bruto_por_codigo = {b['codigo']: b for b in brutos if b['fonte'] == 'TRT3_2024'}
print('ANTES (bruto) - Súmula 338:\n')
print(bruto_por_codigo['SUM-338']['texto_bruto'][:900], '\n')
print('DEPOIS (campos):')
r = por_id['TST-SUM-338']
for campo in ('nome_citacao', 'titulo', 'situacao', 'situacao_detalhe', 'buscavel'):
    print(f'  {campo}: {r[campo]}')
print('  itens:', [i['item'] for i in r['itens']])
print('  texto_busca:', r['texto_busca'][:400], '…')
print('  historico:', (r['historico'] or '')[:160], '…')
print('  remissoes_trt3:', r['remissoes_trt3'])
cols = ['id', 'titulo', 'situacao', 'situacao_detalhe', 'buscavel', 'texto_busca']
display(pd.DataFrame([por_id[i] for i in ['TST-OJ-SDI1-394', 'TST-SUM-221', 'TST-OJ-SDI1-27', 'TST-OJ-SDC-21',
                                          'TST-IRR-128', 'TST-IRR-43']])[cols + ['avisos']])
''')

n3.md('lim_vig_texto', '''
## 3. Vigência: quarentena dos cancelamentos noticiados

Os enunciados citados na notícia continuam com a situação oficial da coletânea e recebem o alerta. Os cancelados **por inteiro** saem da busca. Os cancelados **em parte** continuam na busca com o alerta, e o modelo deve avisar que aquele item pode não valer mais.
''')
n3.code('lim_vig', r'''
alert = df[df.alerta_vigencia.notna()][['id', 'nome_citacao', 'titulo', 'situacao', 'buscavel', 'alerta_vigencia']]
print(f'{len(alert)} com alerta · em quarentena (fora da busca): {(~alert.buscavel & (alert.situacao == "vigente")).sum()}')
display(alert)
''')

n3.md('lim_valid_texto', '''
## 4. Validação e gravação do JSONL único

O arquivo só é gravado se passar nas verificações abaixo:
- nenhum `id` repetido;
- nenhum campo obrigatório vazio (tipo, número, nome de citação, situação e origem);
- nenhum registro buscável sem texto de busca.

O manifesto registra o hash do JSONL, das fontes e as contagens. Com isso, o chunking do notebook 04 pode conferir que usa exatamente esta versão.
''')
n3.code('lim_valid', r'''
problemas = est.validar(registros)
print('Problemas:', problemas or 'nenhum')
sha_jsonl = est.gravar_jsonl(registros, SAIDA_JSONL)
contagens = df.groupby(['tipo', 'situacao']).size().rename('registros').reset_index()
contagens.to_csv(REL / 'estruturacao/contagens.csv', index=False, encoding='utf-8')
manifesto_est = dict(arquivo=str(SAIDA_JSONL.relative_to(ROOT)).replace('\\', '/'), sha256=sha_jsonl,
                     registros=len(registros), buscaveis=int(df.buscavel.sum()), esquema=est.ESQUEMA,
                     fontes={s: fonte(s) for s in ('TRT3_2024', 'IRR_2026')},
                     alertas_noticia=len(alert), brutos_sha256=manifesto['brutos_sha256'])
(REL / 'estruturacao/manifesto_estruturacao.json').write_text(json.dumps(manifesto_est, indent=2, ensure_ascii=False), encoding='utf-8')
print(f'Gravado: {manifesto_est["arquivo"]} · {len(registros)} registros · {manifesto_est["buscaveis"]} buscáveis · sha256 {sha_jsonl[:16]}…')
display(contagens)
print('\nUm registro do JSONL (Súmula 60):')
print(json.dumps({k: v for k, v in por_id['TST-SUM-60'].items() if k not in ('historico',)}, ensure_ascii=False, indent=1)[:1800])
''')

n3.md('lim_oficial_texto', '''
## 5. Texto oficial das súmulas do teste de posição

O teste de posição do notebook 00 usou textos de súmula digitados de memória, porque os documentos ainda não tinham chegado. Abaixo está o texto oficial, já estruturado, dos mesmos itens. O notebook 06 repete o teste com esse texto, dentro da base separada.
''')
n3.code('lim_oficial', r'''
def item(rid, it=None):
    r = por_id[rid]
    if it:
        return next(i['texto'] for i in r['itens'] if i['item'] == it)
    return r['texto_busca']
for rid, it in [('TST-SUM-338', 'I'), ('TST-SUM-276', None), ('TST-SUM-378', 'II'), ('TST-SUM-6', 'VIII'), ('TST-SUM-60', None)]:
    print(f"{por_id[rid]['nome_citacao']}{', item ' + it if it else ''}: {est.sem_origem(item(rid, it))}\n")
''')

n3.md('lim_conclusao', '''
## Conclusões

- **JSONL único gravado:** súmulas, OJs e temas num só arquivo, com o mesmo esquema. Cada registro tem o nome de citação ("Súmula 60 do TST", "Tema 128 de IRR do TST"), que o prompt vai usar para identificar a fonte.
- **Só vai para a busca o que vale:**
  - os cancelados, as súmulas suspensas pelo STF, as teses superadas e os cancelamentos integrais noticiados ficam registrados, fora da busca;
  - o texto de busca não leva o histórico nem as notas.
- **Pendências:**
  1. **Livro oficial do TST de 2026**, ou a resolução dos cancelamentos, para confirmar a quarentena.
  2. **EC 141/2026** na base de legislação (art. 7º da Constituição).
  3. **Precedentes do STF**, a partir do índice de repercussão geral já recebido, numa etapa posterior.

Próximo: `04_chunking_precedentes.ipynb`, com um trecho por enunciado ou por item e o título repetido em cada item.
''')
n3.gravar()
