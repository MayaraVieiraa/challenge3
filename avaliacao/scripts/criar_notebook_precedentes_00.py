"""Cria avaliacao/notebooks/05_docs_precedentes/00_introducao_precedentes.ipynb: por que a terceira base (precedentes do TST) existe.

Dados (só identificadores e números; sem texto de perguntas protegidas):
  dados/relatorios/precedentes/teste_ranking_jurisprudencia.csv     avaliacao/scripts/teste_ranking_precedentes.py
  dados/relatorios/integracao/juiz/diagnostico_especialista_27b.csv avaliacao/scripts/importar_revisao_juiz.py
Execução: python avaliacao/scripts/executar_notebook_integracao.py avaliacao/notebooks/05_docs_precedentes/00_introducao_precedentes.ipynb
"""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[2]
DESTINO = ROOT / 'avaliacao/notebooks/05_docs_precedentes/00_introducao_precedentes.ipynb'
celulas = []


def md(ident, texto):
    celulas.append(dict(cell_type='markdown', id=ident, metadata={}, source=texto.strip().splitlines(keepends=True)))


def code(ident, texto):
    celulas.append(dict(cell_type='code', id=ident, metadata={}, execution_count=None, outputs=[],
                        source=texto.strip().splitlines(keepends=True)))


md('prec_intro', '''
# Terceira base: precedentes do TST

O LexIA responde com base em duas bases:
- **legislação:** CLT, Constituição, leis e códigos;
- **jurisprudência:** 20 mil acórdãos de TRTs, do TST e do STF.

Este notebook explica por que precisamos de uma **terceira base**, com os precedentes qualificados do Tribunal Superior do Trabalho:
- **súmulas;**
- **orientações jurisprudenciais (OJs);**
- **teses dos temas de recursos repetitivos.**

Também explica por que essa base precisa ser **separada** da base de jurisprudência.

**Resumo:**

1. **Sem os precedentes, as respostas ficam incompletas.** Na avaliação de um advogado revisor (notebook `03_integracao/04_avaliacao.ipynb`), a regra que decidia a pergunta estava num precedente do TST em 8 das 25 respostas. Essas respostas foram reprovadas porque o sistema não tinha esses documentos. Sem eles, o modelo resumiu a regra a partir de um acórdão, perdeu as condições ou concluiu o contrário.
2. **Misturados aos acórdãos, os precedentes não seriam encontrados.** No teste da seção 5, a súmula certa ficaria entre a 8ª e a 3.370ª posição entre os 20 mil acórdãos. Como a busca entrega só 3 decisões por pergunta, em nenhum caso ela chegaria ao modelo.
3. **Uma base separada é mais barata e mais reprodutível.** Ela não obriga a refazer a base de jurisprudência validada, com 303 mil trechos, e tem uma cota de entrega própria.
4. **Os documentos oficiais já chegaram** (seção 2). Foram 10 arquivos, com 8 documentos distintos, que resultaram em:
   - 463 súmulas, 709 OJs e 321 temas repetitivos do TST;
   - um JSONL único com 1.493 registros, dos quais 1.022 entram na busca.

   A **Emenda Constitucional nº 141/2026**, que reduz a jornada para 40 horas e prevê dois dias de repouso, veio junto. Ela não é precedente e foi aplicada à base de legislação.
''')

md('prec_tipos', '''
## 1. Os três tipos de documento

São **precedentes qualificados**: enunciados curtos que resumem o entendimento consolidado do tribunal sobre um ponto de direito. Um acórdão conta como um caso foi decidido. Um precedente diz qual é a regra que o tribunal aplica.

| Tipo | O que é | Quem edita | Força |
|---|---|---|---|
| **Súmula do TST** | Enunciado numerado que resume a jurisprudência reiterada do tribunal sobre um tema. Pode ter itens (I, II, III...) e é revista quando a lei muda, como depois da reforma trabalhista de 2017 | Tribunal Pleno do TST | Orienta todos os juízes do trabalho e serve para barrar recursos contrários a ela. Na prática, é a regra aplicada |
| **Orientação jurisprudencial (OJ)** | Entendimento predominante de uma das seções especializadas do TST. É mais específico e técnico que a súmula, e muitas vezes é o caminho para virar súmula | SDI-1 (dissídios individuais), SDI-2 (ações rescisórias, mandados de segurança) e SDC (dissídios coletivos) | Orienta o julgamento dos recursos naquela seção. Algumas OJs têm versões "transitórias" |
| **Tema de recurso repetitivo (tese do TST)** | Tese jurídica fixada no julgamento de recursos de revista repetitivos, quando muitos processos discutem a mesma questão | Pleno ou SDI-1 do TST, no rito de recursos repetitivos (art. 896-C da CLT) | **Vinculante:** os juízes e tribunais do trabalho devem aplicar a tese (art. 927 do CPC) |

**O que vem junto de cada documento:**
- **Situação:** vigente, cancelado ou com redação alterada. É o ponto mais sensível, porque uma súmula cancelada apresentada como regra é pior do que nenhuma súmula.
- **Data da redação atual** e normas que o precedente interpreta (por exemplo, "art. 73, § 5º, da CLT").
- **Itens separados**, quando houver.

O índice de recursos repetitivos do TST também traz dois tipos semelhantes, que entram na base como temas:
- **IAC:** incidente de assunção de competência;
- **IRDR:** incidente de resolução de demandas repetitivas.

Ficam para depois:
- os precedentes normativos do TST, usados em dissídios coletivos. Eles estão na coletânea recebida, mas fora do escopo;
- as súmulas vinculantes e os temas de repercussão geral do STF. O índice já foi recebido e será usado numa etapa posterior.
''')

md('prec_docs', '''
## 2. Os documentos recebidos

Os 10 arquivos estão em `dados/raw/precedentes/`, exatamente como foram baixados. O notebook `01_auditoria_precedentes` registra o hash de cada um. Dois arquivos terminam em "(1)" e são cópias byte a byte de outros dois, com o mesmo hash. Por isso, há **8 documentos distintos**.

| Documento | O que é | Para onde vai |
|---|---|---|
| **Coletânea do TRT-3** (`arquivo-versao-eletronica-28-6-2024-1.pdf`, 421 p.) | Jurisprudência consolidada do TST, com súmulas e OJs no formato oficial, situação e histórico de cada verbete. Atualizada até 28/06/2024 | **Fonte principal** de súmulas e OJs: 463 súmulas e 709 OJs |
| **Índice de recursos repetitivos do TST** (19/11/2026, 221 p.) | Os temas de IRR, IAC e IRDR, cada um com a questão jurídica, a tese (ou "ainda não fixada") e as normas de referência | **Fonte principal** dos temas: 321 temas |
| **Notícia do cancelamento de 36 enunciados** | Texto não oficial que nomeia 26 súmulas e OJs canceladas depois de 2024 | **Alerta de vigência.** Os 22 dados como cancelados por inteiro ficam fora da busca até a resolução oficial do TST ser conferida |
| **Índice de repercussão geral** (19/11/2026, 377 p.) | Temas de repercussão geral e decisões do STF em matéria trabalhista | Etapa posterior (precedentes do STF) |
| **Acórdão 168 do TST** | Reafirmação da Súmula 462 em recurso repetitivo | Não entra: tem nomes das partes, e a tese já está no índice de IRR |
| **Coletânea do TRT-2** (2021, 441 p.) | Jurisprudência consolidada do TRT-2 | Não entra: mais antiga e repete a do TRT-3 |
| **EC 141/2026** (`nova_lei_escala_de_trabalho.pdf`) | Emenda que muda o art. 7º da Constituição: 40 horas semanais, com transição (42 horas a partir de 16/12/2026 e 40 a partir de 16/12/2027), e dois dias de repouso a partir de 16/12/2026 | **Base de legislação.** Nova versão `ec141_2026`, com o art. 7º atualizado, nota de vigência e os 10 artigos da emenda |
| **Autógrafo da Câmara** (`DOC-SF…20260528.pdf`) | Texto da mesma emenda durante a tramitação (28/05/2026) | Não entra: a versão oficial é a EC 141 |
| Cópias "(1)" da coletânea do TRT-3 e do índice de repercussão geral | Mesmo hash dos originais | Registradas como duplicata e não lidas |

**Por que a EC 141 importa aqui.** Ela mostra que uma base desatualizada derruba a resposta tanto quanto uma base incompleta. Antes da atualização, uma pergunta sobre jornada recebia o texto de 44 horas sem nenhum aviso.

Com a nota de vigência, o modelo pode responder corretamente nos três momentos:
- hoje, o limite ainda é de 44 horas;
- a partir de 16/12/2026, passa a 42 horas;
- a partir de 16/12/2027, chega a 40 horas.

O mesmo cuidado vale para os precedentes. Por isso a situação de cada súmula (vigente, cancelada ou em quarentena) vai junto do texto.
''')
md('prec_mapa_dados', '''
### Mapa de dados da pasta (da origem ao banco)

| | Caminho no repositório | Formato | Quantidade | Versionado? |
|---|---|---|---|---|
| Documentos recebidos (01) | `dados/raw/precedentes/*.pdf` | PDF | 10 arquivos, 8 distintos | fora do Git |
| Blocos brutos (01) | `dados/interim/precedentes/verbetes_brutos.jsonl` | JSONL (um registro JSON por linha) | 1.596 blocos | fora do Git |
| **Base estruturada (03)** | `dados/processed/precedentes/precedentes_tst.jsonl` | JSONL (um registro JSON por linha) | **1.493 registros**: 463 súmulas, 709 OJs e 321 temas; 1.022 buscáveis | fora do Git |
| Trechos (04) | `dados/processed/precedentes/chunks_precedentes.jsonl` | JSONL (um registro JSON por linha) | 1.268 trechos | fora do Git |
| Vetores (05) | `dados/processed/precedentes/vetores_bge_m3.npy` | NumPy (.npy) | 1.268 × 1.024 | fora do Git |
| Banco (05) | `PostgreSQL, schema lex_precedentes` | tabelas | embeddings 1.268 · registros 1.493 · lexico 1.268 | fora do Git (banco) |
| Relatórios (01 a 06) | `dados/relatorios/precedentes/ (auditoria, eda, estruturacao, chunking, indexacao, avaliacao)` | CSV, JSON e PNG | só identificadores, contagens e hashes | sim |

**Formato:** a base estruturada é gravada em **JSONL** (texto, um registro JSON por linha), e não em CSV, porque cada registro tem campos com listas (itens da súmula, páginas, assuntos, histórico). Os arquivos **CSV** do projeto são os relatórios em `dados/relatorios/precedentes/`. Os arquivos de dados ficam em `dados/`, dentro da pasta do repositório, mas **fora do Git** (`.gitignore`): contêm texto integral e são recriados pelos notebooks.
''')
code('prec_docs_inv', r'''
from pathlib import Path
import pandas as pd
from IPython.display import display
ROOT = next(p for p in (Path.cwd(), *Path.cwd().parents) if (p / 'worker/evidencia').exists())
pd.set_option('display.width', 250); pd.set_option('display.max_columns', None)
inv = pd.read_csv(ROOT / 'dados/relatorios/precedentes/auditoria/inventario_documentos.csv')
print(f'{len(inv)} arquivos · {inv.sha256.nunique()} documentos distintos')
display(inv[['sigla', 'data_referencia', 'paginas', 'tamanho_mb', 'papel', 'destino']].assign(sha256=inv.sha256.str[:12]))
''')

md('prec_setup_texto', '## 3. Configuração e carga dos dados')
code('prec_setup', r'''
from pathlib import Path
import sys
import pandas as pd
import matplotlib.pyplot as plt
from IPython.display import display

ROOT = next(p for p in (Path.cwd(), *Path.cwd().parents) if (p / 'worker/evidencia').exists())
ranking = pd.read_csv(ROOT / 'dados/relatorios/precedentes/teste_ranking_jurisprudencia.csv')
diag = pd.read_csv(ROOT / 'dados/relatorios/integracao/juiz/diagnostico_especialista_27b.csv')
humano = pd.read_csv(ROOT / 'dados/relatorios/integracao/juiz/concordancia_humano_27b.csv')
print(f'Teste de ranking: {len(ranking)} súmulas · amostra do advogado: {len(diag)} respostas')
''')

md('prec_exemplos_texto', '''
## 4. As respostas sem precedente na amostra do advogado

Das 25 respostas que o advogado revisor avaliou às cegas, **8** tinham a regra decisiva num precedente que o corpus não tem. O advogado reprovou as 8. Mesmo assim, o juiz automático aprovou metade delas pela regra fixa.
''')
code('prec_exemplos', r'''
prec = diag[diag.precedente].merge(humano[['id', 'veredito_humano']], on='id')
print(f"Respostas em que falta o precedente: {len(prec)} de {len(diag)}")
print(f"Reprovadas pelo advogado: {(prec.veredito_humano == 'reprovada').sum()} · "
      f"aprovadas pela regra do juiz: {(prec.veredito_regra == 'aprovada').sum()}")
display(prec[['ordem', 'id', 'acao', 'veredito_humano', 'veredito_regra']]
        .rename(columns={'ordem': 'P', 'veredito_humano': 'advogado', 'veredito_regra': 'juiz (regra)'}))
''')

md('prec_exemplos_tabela', '''
As perguntas da curadoria são protegidas, para não contaminar avaliações futuras. Por isso a tabela traz um **resumo** de cada pergunta e da falha da resposta, e não o texto original. O precedente indicado é o que o advogado apontou como decisivo. Todos foram encontrados nos documentos oficiais, ativos e com o item certo (notebook 02, seção 6), exceto o caso do STF.

| P | Assunto da pergunta | O que a resposta disse (resumo) | Precedente que decidia | Tipo |
|---|---|---|---|---|
| 6 | Horas extras quando a empresa não mantinha controle de ponto | Que o trabalhador sempre precisa provar as horas extras, lendo o art. 74, § 2º, da CLT ao contrário | Súmula 338, I: sem os controles, presume-se verdadeira a jornada alegada (empresas obrigadas ao registro) | Súmula |
| 7 | O que é aviso prévio | Que o aviso "não é obrigatório" se o empregado arranja novo emprego, e prazos pela redação antiga | Súmula 276: o aviso é irrenunciável pelo empregado, e o pagamento só é dispensado se houver novo emprego comprovado | Súmula |
| 10 | Demissão logo após voltar de afastamento | Partiu da premissa de que a demissão "pode ser válida" e não mencionou a estabilidade acidentária | Súmula 378, II: requisitos da estabilidade de 12 meses; e a tese sobre doença ocupacional reconhecida depois da dispensa | Súmula e tema |
| 11 | Colega que faz o mesmo trabalho e ganha mais | Inverteu o ônus da prova e usou a redação anterior à reforma | Súmula 6, VIII: cabe ao empregador provar o fato que impede a equiparação | Súmula |
| 23 | Revista diária dos pertences e indenização | Abriu com "sim, gera indenização" para a revista visual, que em regra não gera | Tese do TST: a revista visual, impessoal e sem contato físico não gera dano moral por si só | Tema repetitivo |
| 24 | Trabalho noturno e jornada que avança pela madrugada | Disse que o adicional vale para qualquer hora depois das 5h, sem a condição | Súmula 60, II: o adicional se estende às horas prorrogadas quando a jornada foi cumprida integralmente no período noturno | Súmula |
| 3 | Horas extras e adicionais no 13º salário | Fundamentou num artigo de banco de horas e citou uma súmula fora do contexto | Súmula 45: as horas extras habituais integram o 13º salário | Súmula |
| 4 | Honorários de sucumbência para o trabalhador | Misturou o regime anterior à reforma com o atual e omitiu a proteção do beneficiário da justiça gratuita | Decisão do STF na ADI 5766 e entendimento do TST sobre a cobrança suspensa | STF e TST (o STF fica para uma etapa posterior) |

**Por que isso torna a resposta insuficiente.** Em todos esses casos, as fontes entregues traziam o artigo de lei e acórdãos que **mencionavam** o precedente, mas não o **texto do precedente**. Sem ele, o modelo:
- reconstruiu a regra a partir de um acórdão e perdeu a condição (P24, "integralmente");
- concluiu o oposto da tese (P6, P23);
- ou nem chegou ao instituto certo (P10, estabilidade).

O advogado resume assim: a conferência quase sempre termina numa súmula ou tema do TST que não estava no contexto.
''')

md('prec_teste_texto', '''
## 5. O teste: anexar os precedentes à base de jurisprudência funcionaria?

**Pergunta:** se colocássemos as súmulas dentro da base de jurisprudência, a busca as encontraria?

**Método:**
1. Escolhemos 5 perguntas da amostra do advogado em que a regra decisiva é uma súmula.
2. Com o mesmo modelo de embeddings da busca (BGE-M3, mesma revisão), medimos a semelhança entre a pergunta e o texto da súmula.
3. Contamos quantos dos 303.257 trechos de acórdãos, e quantos dos 20 mil documentos, ficam **acima** da súmula. A busca entrega 3 decisões por pergunta, então a súmula só chegaria ao modelo se ficasse entre os 3 primeiros documentos.

**Ressalva:** os textos das súmulas deste teste foram digitados de memória, como versão provisória. O texto oficial já está estruturado no notebook 03, e o teste será repetido com ele no notebook 06. A distância observada, porém, é grande demais para mudar de conclusão por diferenças de redação.

Script: `avaliacao/scripts/teste_ranking_precedentes.py`. Ele precisa do Postgres no Docker e do modelo em cache. O resultado fica salvo em `dados/relatorios/precedentes/`.
''')
code('prec_teste', r'''
t = ranking.copy()
display(t[['pergunta_id', 'precedente', 'semelhanca_sumula', 'semelhanca_1o_acordao', 'semelhanca_3o_documento',
           'posicao_entre_documentos', 'posicao_entre_chunks', 'entregue_com_cota_3']]
        .rename(columns={'semelhanca_sumula': 'sem. súmula', 'semelhanca_1o_acordao': 'sem. 1º trecho',
                         'semelhanca_3o_documento': 'sem. 3º documento', 'posicao_entre_documentos': 'posição (de 20 mil docs)',
                         'posicao_entre_chunks': 'posição (de 303 mil trechos)', 'entregue_com_cota_3': 'chegaria ao modelo?'}))

fig, axes = plt.subplots(1, 2, figsize=(13, 4.3))
x = range(len(t))
axes[0].bar([i - 0.2 for i in x], t.semelhanca_sumula, 0.4, color='#1f77b4', label='Súmula certa')
axes[0].bar([i + 0.2 for i in x], t.semelhanca_3o_documento, 0.4, color='#7f7f7f', label='3º acórdão (último entregue)')
axes[0].set_xticks(list(x), [p.replace(' do TST', '').rstrip(',') for p in t.precedente], rotation=15)
axes[0].set_ylim(0.4, 0.8)
axes[0].set_ylabel('Semelhança com a pergunta (cosseno)')
axes[0].set_title('A súmula fica abaixo do último acórdão entregue')
axes[0].legend(loc='upper left')

axes[1].barh([p.replace(' do TST', '').rstrip(',') for p in t.precedente], t.posicao_entre_documentos, color='#d62728')
axes[1].axvline(3, color='black', linestyle='--', label='cota de entrega (3)')
axes[1].set_xscale('log')
for i, v in enumerate(t.posicao_entre_documentos):
    axes[1].text(v * 1.1, i, f'{v}ª', va='center', fontweight='bold')
axes[1].set_xlabel('Posição da súmula entre os 20 mil documentos (escala log)')
axes[1].set_title('Posição se anexada à base de jurisprudência')
axes[1].set_xlim(1, 20000)
axes[1].legend(loc='upper right')
plt.tight_layout()
plt.savefig(ROOT / 'dados/relatorios/precedentes/teste_ranking_jurisprudencia.png', dpi=150)
plt.show()
''')

md('prec_teste_leitura', '''
**Resultado.** Em nenhuma das 5 perguntas a súmula chegaria ao modelo. A melhor posição foi a 8ª (Súmula 276), e a pior foi a 3.370ª (Súmula 338).

**Por quê.** A súmula é um enunciado curto e abstrato. Os acórdãos são longos, descrevem casos parecidos com a pergunta e muitas vezes citam a própria súmula. Por isso, na comparação de embeddings, os acórdãos sempre parecem mais próximos da pergunta, mesmo quando a regra está na súmula. São milhares de acórdãos competindo com um único enunciado.
''')

md('prec_separada', '''
## 6. Por que uma base separada, e não um anexo à jurisprudência

Além do ranking, a estrutura da base de jurisprudência também atrapalha:

| | Anexar à jurisprudência | Terceira base (`lex_precedentes`) |
|---|---|---|
| **Busca** | A súmula disputa com 303 mil trechos de acórdãos e não é entregue. Seria preciso filtrar por tipo e dar uma cota separada dentro da mesma fonte, ou seja, o mesmo código da base nova | Disputa só com outros precedentes (1 a 2 mil enunciados), com cota de entrega própria |
| **Base validada** | É uma versão congelada, com hash, manifesto e contagem fixa. Anexar exigiria gerar e validar de novo os 303 mil trechos | A base de jurisprudência não muda |
| **Reprodutibilidade** | Os notebooks de integração (01, 04, 05, 06) apontam para o dataset atual e deixariam de ser reproduzíveis | Nada muda no que já foi medido |
| **Metadados** | Os campos são de acórdão: processo, relator, órgão julgador, privacidade. Faltam vigência, itens e normas interpretadas | Campos próprios: tipo, número, item, situação, data da redação, normas interpretadas |
| **Trecho (chunk)** | Janela fixa de 500 tokens | Um enunciado ou item por trecho |
| **Atualização** | O TST edita e cancela súmulas. Cada mudança obrigaria a refazer a base grande | Cada atualização gera uma versão nova só da base pequena |
| **Comparar com e sem** | Exige filtrar por tipo | Basta ligar ou desligar a fonte na configuração |
''')

md('prec_proximos', '''
## 7. Próximos passos desta pasta

Os documentos e o destino de cada um estão na seção 2.

**Pendências de fonte:**
- o livro oficial de súmulas e OJs do TST atualizado em 2026, ou a resolução dos cancelamentos, para confirmar a quarentena;
- a Lei 605/1949 (repouso de 24 horas) e a LC 150/2015 (domésticos, 44 horas), que ainda trazem a regra anterior à EC 141.

| Notebook | Conteúdo | Situação |
|---|---|---|
| `01_auditoria_precedentes` | Origem, data e hash dos arquivos. Numeração completa, duplicatas e vigência diante da notícia de cancelamentos | pronto |
| `02_eda_precedentes` | Quantidade por tipo, tamanho em tokens, ruído do texto bruto, cor do título x tese, normas citadas e cobertura dos precedentes das 25 respostas | pronto |
| `03_limpeza_estruturacao_precedentes` | Título, enunciado, itens e histórico separados. Vigência e quarentena. JSONL único `precedentes_tst.jsonl` | pronto |
| `04_chunking_precedentes` | Um trecho por enunciado ou por item, com cabeçalho; limite de 220 tokens (1.268 trechos) | pronto |
| `05_embeddings_indexacao_precedentes` | BGE-M3 na mesma revisão, schema `lex_precedentes` validado, dataset com hash e manifesto, visão lexical | pronto |
| `06_avaliacao_recuperacao_precedentes` | Este mesmo teste dentro da base separada e com o texto oficial. Gabarito com o precedente esperado nas perguntas da curadoria. Hit@1 e Hit@3 | a fazer |

**Depois, na integração:**
- a busca conjunta passa a ter três fontes, com cotas a definir por teste;
- o prompt passa a identificar o precedente pelo nome, por exemplo "Súmula 60 do TST";
- o efeito é medido nas 8 perguntas da seção 4 e nas 111 respostas da geração.

**Privacidade:** súmulas, OJs e teses são textos públicos e sem dados pessoais, então não precisam de mascaramento. Ainda assim, as perguntas da curadoria continuam fora dos arquivos versionados.
''')

notebook = dict(cells=celulas,
                metadata=dict(kernelspec=dict(display_name='Python 3', language='python', name='python3'),
                              language_info=dict(name='python', version='3.14.6')),
                nbformat=4, nbformat_minor=5)
DESTINO.parent.mkdir(parents=True, exist_ok=True)
DESTINO.write_text(json.dumps(notebook, indent=2, ensure_ascii=False), encoding='utf-8')
print(f'Notebook criado em {DESTINO}')
