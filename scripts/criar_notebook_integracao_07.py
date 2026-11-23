"""Cria notebooks/03_integracao/07_integracao_precedentes.ipynb (código; as saídas vêm da execução).

Documenta a entrada da base de precedentes do TST como terceira fonte no código de produção (src/integracao/).
Lê:    banco PostgreSQL (schemas lex_clt, lex_jurisprudencia, lex_precedentes, lex_integracao)
       output/kaggle/geracao/dataset/pedidos.jsonl            perguntas sanitizadas (nunca impressas)
       reports/precedentes/avaliacao/resultados_especialista.csv   posições antes da integração
       output/kaggle/geracao*/resultados/respostas.jsonl          respostas v1, v3 e v3.1 (só ids nos alertas)
       reports/integracao/precedentes/sinonimos_*.csv             scripts/avaliar_sinonimos_recuperacao.py
Grava: reports/integracao/precedentes/entrega_especialista.csv     só identificadores e posições
       reports/integracao/precedentes/alertas_precedentes_respostas.csv
Execução: python scripts/executar_notebook_integracao.py notebooks/03_integracao/07_integracao_precedentes.ipynb
"""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
DESTINO = ROOT / 'notebooks/03_integracao/07_integracao_precedentes.ipynb'
celulas = []


def md(ident, texto):
    celulas.append(dict(cell_type='markdown', id=ident, metadata={}, source=texto.strip().splitlines(keepends=True)))


def code(ident, texto):
    celulas.append(dict(cell_type='code', id=ident, metadata={}, execution_count=None, outputs=[],
                        source=texto.strip().splitlines(keepends=True)))


md('int07_intro', '''
# 07 — Integração dos precedentes do TST como terceira fonte

A base de precedentes reúne súmulas, orientações jurisprudenciais (OJs) e temas de recursos repetitivos do TST. Ela foi construída e avaliada nos notebooks de `notebooks/05_docs_precedentes/`, do 00 ao 06. Este notebook registra a entrada dessa base **no código que vai para produção**, `src/integracao/`. A partir daqui, o sistema busca em três bases:

| Base | O que diz | Schema no banco |
|---|---|---|
| Legislação | a regra (CLT, CF, leis) | `lex_clt` |
| Decisões judiciais | como um caso concreto foi julgado | `lex_jurisprudencia` |
| **Precedentes do TST** | como o TST interpreta e aplica a regra | `lex_precedentes` |

**O modelo não é treinado de novo.** A junção acontece antes dele, na busca e no texto do prompt. Para o Qwen3, um precedente é mais uma `[Fonte N]`, identificada como "precedente do TST (súmula)". A regra 25 do prompt diz a ele como citar esse tipo de fonte.

### O que mudou no código de produção

| Arquivo | O que passou a fazer |
|---|---|
| `src/integracao/recuperacao.py` | busca também em `lex_precedentes`: semântica, por palavras (índice normalizado, sem stopwords, com peso IDF) e reranker sobre a **união** das duas buscas. Entrega o registro inteiro do precedente, com nome de citação, situação e alerta de vigência (`configuracao_com_precedentes`, `selecionar_uniao`, `texto_precedente`, `Recuperador.precedentes`) |
| `src/integracao/sinonimos.py` | **arquivo novo.** Acrescenta à pergunta os termos jurídicos equivalentes ("13º" → "gratificação natalina"), sem alterar a pergunta original |
| `src/integracao/prompt_juridico.py` | prompt v3: tipo de fonte "precedente do TST (…)", campo "Precedente" e **regra 25**. O v1 continua idêntico |
| `src/integracao/geracao.py` | converte a unidade de precedente em fonte do prompt e passa o nome de citação ao validador |
| `src/integracao/guardrails.py` | validador v3: a súmula citada pelo nome da fonte ("Súmula 338 do TST") conta como norma presente nas fontes; **4 alertas novos** para precedentes (seção 7) |
| `src/integracao/situacao_precedentes.json` | **arquivo novo, versionado.** Situação das súmulas, OJs e temas (cancelados, suspensos, superados, em quarentena) para o validador. Gerado por `scripts/gerar_catalogo_situacao_precedentes.py` |
| `tests/test_integracao_precedentes.py` | **arquivo novo.** Testes da integração dos precedentes |

### O fluxo com três bases

```
pergunta
  → guardrails de entrada                      (guardrails.py)
  → sinônimos jurídicos                        (sinonimos.py)
  → busca em cada base: semântica + palavras   (recuperacao.py)
  → reranker → 3 artigos + 3 decisões + 3 precedentes
  → prompt v3: [Fonte 1] … [Fonte 9], cada uma com seu tipo   (prompt_juridico.py)
  → Qwen3 8B escreve a resposta citando as [Fonte N]
  → validador v3 confere as normas citadas     (guardrails.py)
  → resposta
```
''')

md('int07_setup_texto', '''
## 1. Configuração e dados desta etapa

> **Dados desta etapa**
> - **Base de precedentes:** 1.493 registros (463 súmulas, 709 OJs, 321 temas), dos quais 1.022 são buscáveis; 1.268 trechos (chunks) com vetores BGE-M3.
> - **Formato e caminho:** JSONL em `data/processed/precedentes/precedentes_tst.jsonl` (registros) e `data/processed/precedentes/chunks_precedentes.jsonl` (trechos); no banco, schema `lex_precedentes` (tabelas `datasets`, `registros`, `embeddings`, `lexico`).
> - **Perguntas:** as 7 do gabarito do advogado (`reports/precedentes/avaliacao/gabarito_especialista.csv`), lidas de `output/kaggle/geracao/dataset/pedidos.jsonl`. O texto das perguntas não é impresso: aparecem só os identificadores.
> - **Grava:** `reports/integracao/precedentes/entrega_especialista.csv` (CSV, só identificadores e posições).

A célula abaixo confere no banco as contagens da versão validada.
''')
code('int07_setup', r'''
from pathlib import Path
import sys, json, io, unittest
import pandas as pd
from IPython.display import display, Markdown

ROOT = next(p for p in (Path.cwd(), *Path.cwd().parents) if (p / 'src/integracao').exists())
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from src.storage.pgvector_store import load_database_url
from src.integracao.recuperacao import (Recuperador, Configuracao, configuracao_com_precedentes, FONTES,
                                        FONTES_COM_PRECEDENTES, texto_precedente)
from src.integracao.sinonimos import GRUPOS, termos_faltantes
from src.integracao.geracao import fonte_para_prompt
from src.integracao.prompt_juridico import build_rag_prompt, REGRAS_V3

pd.set_option('display.width', 250); pd.set_option('display.max_columns', None)
SAIDA = ROOT / 'reports/integracao/precedentes'
SAIDA.mkdir(parents=True, exist_ok=True)

r = Recuperador(load_database_url(ROOT / '.env.pgvector.local'), device='cpu', carregar_reranker=True)
ds = r.dataset_precedentes
q = lambda sql: r.conexao.execute(sql, (ds,)).fetchall()
registros = q('SELECT count(*) FROM lex_precedentes.registros WHERE dataset_id=%s')[0][0]
chunks, buscaveis = q('SELECT count(*), count(DISTINCT registro_id) FROM lex_precedentes.embeddings WHERE dataset_id=%s')[0]
print(f'Dataset de precedentes validado: {ds[:12]}…')
print(f'Registros: {registros} · buscáveis (com trechos indexados): {buscaveis} · trechos: {chunks}')
por_tipo = q("""SELECT r.dados->>'tipo', r.dados->>'situacao', count(*) FROM lex_precedentes.registros r
               WHERE r.dataset_id=%s AND EXISTS (SELECT 1 FROM lex_precedentes.embeddings e
                     WHERE e.dataset_id=r.dataset_id AND e.registro_id=r.registro_id) GROUP BY 1, 2 ORDER BY 1, 2""")
tabela = pd.DataFrame(por_tipo, columns=['tipo', 'situação', 'registros buscáveis'])
display(tabela.pivot(index='tipo', columns='situação', values='registros buscáveis').fillna(0).astype(int))
''')

md('int07_chave_texto', '''
## 2. A chave de ativação

A terceira fonte entra por uma configuração própria, `configuracao_com_precedentes()`. A configuração padrão, `Configuracao()`, continua com duas bases. Assim, as gerações v1, v3 e v3.1, medidas com duas bases, continuam reproduzíveis.

**Para valer em produção,** a configuração com precedentes passa a ser a usada pelo ponto de entrada do sistema. Isso será feito depois da medição das respostas (geração v3.2 e juiz).
''')
code('int07_chave', r'''
padrao, nova = Configuracao(), configuracao_com_precedentes()
campos = ['fontes', 'entrega_por_fonte', 'top_k', 'uniao_reranker', 'expandir_sinonimos']
display(pd.DataFrame({'Configuracao() — padrão': [str(getattr(padrao, c)) for c in campos],
                      'configuracao_com_precedentes()': [str(getattr(nova, c)) for c in campos]}, index=campos))
''')

md('int07_busca_texto', '''
## 3. Busca: os precedentes que o advogado apontou como decisivos

O notebook 06 de precedentes avaliou a base sozinha, sem as outras fontes. Nas 7 perguntas em que o advogado revisor apontou um precedente decisivo, a busca híbrida com reranker pôs 5 em 1º lugar e perdeu 2:
- a **Súmula 60** ficava em 3º na busca semântica, mas não aparecia na busca por palavras, e a fusão das duas a empurrava para 21º. O reranker não chegava a vê-la;
- a **Súmula 45** não era encontrada por nenhuma busca: a pergunta diz "13º", e a súmula diz "gratificação natalina".

As duas correções da integração atacam esses casos:
- **União no reranker:** na fonte de precedentes, o reranker recebe os 10 primeiros de cada busca, e não só os 10 primeiros da fusão;
- **Sinônimos jurídicos:** a pergunta ganha, entre parênteses, os termos equivalentes que faltam.

Agora a busca roda no fluxo completo, com as três bases e a cota de 3 precedentes por pergunta.
''')
code('int07_busca', r'''
pedidos = {}
with open(ROOT / 'output/kaggle/geracao/dataset/pedidos.jsonl', encoding='utf-8') as f:
    for linha in f:
        p = json.loads(linha)
        pedidos[p['pergunta_id']] = p['pergunta_sanitizada']
antes = pd.read_csv(ROOT / 'reports/precedentes/avaliacao/resultados_especialista.csv')
ESPERADO = {'juris_004': 'TST-SUM-338', 'q09_p2_FAQ32': 'TST-SUM-276', 'juris_013': 'TST-SUM-378', 'juris_019': 'TST-SUM-6',
            'juris_017': 'TST-IRR-58', 'q09_p1_JUS-001': 'TST-SUM-60', 'q09_p2_FAQ26': 'TST-SUM-45'}

linhas, ultimas = [], {}
for pid, esperado in ESPERADO.items():
    entregues, diag = r.buscar(pedidos[pid], nova)     # o texto da pergunta não é impresso
    ranking = [u for _, u in diag['ranking_por_fonte']['precedentes']]
    prec = [u['unidade'] for u in entregues if u['fonte'] == 'precedentes']
    pos_antes = antes.loc[antes.pergunta == pid, 'híbrida + reranker'].iloc[0]
    linhas.append(dict(pergunta=pid, esperado=esperado,
                       **{'antes (base sozinha)': 'perdido' if pd.isna(pos_antes) else f'{int(pos_antes)}º',
                          'agora (3 bases)': f'{ranking.index(esperado) + 1}º' if esperado in ranking else 'perdido',
                          'entregue ao modelo': esperado in prec,
                          'sinônimos acrescentados': ', '.join(termos_faltantes(pedidos[pid])) or '—',
                          'fontes entregues': ' + '.join(f"{sum(u['fonte'] == f for u in entregues)} {f}" for f in nova.fontes),
                          'segundos': round(diag['segundos'], 1)}))
    ultimas[pid] = entregues
resultado = pd.DataFrame(linhas)
resultado.to_csv(SAIDA / 'entrega_especialista.csv', index=False)
display(resultado)
print(f"Precedentes esperados entregues ao modelo: {resultado['entregue ao modelo'].sum()} de {len(resultado)}")
''')

md('int07_padrao_texto', '''
Conferência: com a configuração padrão, a mesma busca continua entregando só legislação e decisões.
''')
code('int07_padrao', r'''
entregues_padrao, _ = r.buscar(pedidos['juris_004'], Configuracao(entrega_por_fonte={'legislacao': 3, 'jurisprudencia': 3}, top_k=10))
print('Configuração padrão:', pd.Series([u['fonte'] for u in entregues_padrao]).value_counts().to_dict())
assert {u['fonte'] for u in entregues_padrao} == set(FONTES)
''')

md('int07_sinonimos_texto', '''
## 4. Sinônimos jurídicos

Cada grupo reúne formas usadas por quem pergunta e pelos textos legais. Quando a pergunta tem um termo do grupo, os que faltam vão ao fim, entre parênteses. A pergunta original não muda.

Para evitar falsos positivos, um número sozinho não dispara o grupo do 13º salário: "13 de maio", "Lei 13.467", "art. 13º" e "13ª Região" ficam como estão (testes em `tests/test_integracao_precedentes.py`).
''')
code('int07_sinonimos', r'''
display(pd.DataFrame({'termos equivalentes': [' · '.join(g) for g in GRUPOS]}, index=range(1, len(GRUPOS) + 1)))
''')

md('int07_prompt_texto', '''
## 5. O que o modelo recebe

Exemplo com uma pergunta fictícia e uma fonte real da base: a Súmula 338 do TST. A fonte chega com o tipo, o nome de citação e o enunciado sem as notas de origem. Quando é o caso, chega também a situação ("tema ainda sem tese fixada") e o alerta de vigência.
''')
code('int07_prompt', r'''
d = r.precedentes(['TST-SUM-338'])['TST-SUM-338']
unidade = dict(fonte='precedentes', unidade='TST-SUM-338', texto=texto_precedente(d),
               metadata=dict(nome_citacao=d['nome_citacao'], tipo=d['tipo'], situacao=d['situacao'],
                             alerta_vigencia=d.get('alerta_vigencia')))
_, usuario = build_rag_prompt('Pergunta fictícia: quem deve provar a jornada de trabalho?', [fonte_para_prompt(unidade)],
                              versao='v3', data_atual='2026-11-23')
print(usuario)
''')
code('int07_regra25', r'''
print(REGRAS_V3[REGRAS_V3.index('\n25. ') + 1:])
''')

md('int07_testes_texto', '''
## 6. Testes

Os testes novos ficam em `tests/test_integracao_precedentes.py`, sem banco nem modelos. Eles cobrem sinônimos, configuração, união no reranker, entrega, prompt, validador e os 4 alertas da seção 7. A célula roda todos os testes da integração (`tests/test_integracao_*.py`).
''')
code('int07_testes', r'''
saida = io.StringIO()
suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'), pattern='test_integracao_*.py')
res = unittest.TextTestRunner(stream=saida, verbosity=0).run(suite)
novos = unittest.defaultTestLoader.loadTestsFromName('test_integracao_precedentes').countTestCases()
print(f'Testes da integração: {res.testsRun} · falhas: {len(res.failures)} · erros: {len(res.errors)} · '
      f'novos desta etapa: {novos}')
assert res.wasSuccessful(), saida.getvalue()
''')

md('int07_alertas_texto', '''
## 7. Validador: alertas para precedentes

Com uma terceira espécie de fonte, surgem erros que o validador v3 não via. Foram acrescentados 4 alertas **informativos**: eles não bloqueiam a resposta até serem medidos nas respostas com precedentes (geração v3.2).

| Alerta | O que confere |
|---|---|
| `precedente_fonte_trocada` | súmula, OJ ou tema citado com uma `[Fonte N]` que não o contém, quando outra fonte de precedente entregue o contém. O `norma_fora_das_fontes` só confere se a norma está em *alguma* fonte |
| `tema_sem_tese_como_regra` | cita um tema afetado e ainda sem tese fixada, sem dizer que a questão está pendente no TST |
| `alerta_vigencia_omitido` | cita um precedente que chegou com alerta de vigência, sem avisar que ele pode ter mudado |
| `precedente_cancelado` | cita súmula, OJ ou tema cancelado, suspenso, superado ou em quarentena (cancelamento integral noticiado em fonte não oficial), sem dizer isso. Pega também o que o modelo cita de memória ou o que vem no texto de uma decisão antiga |

O último alerta precisa saber a situação de todos os precedentes, mesmo dos que não foram entregues. A base completa fica em `data/processed/`, que não vai para o Git. Por isso, um catálogo pequeno e versionado vai junto do código: `src/integracao/situacao_precedentes.json`.

Para não confundir numerações:
- súmula vinculante e citações seguidas de STF, STJ ou TRT não contam;
- OJ sem a série (SBDI-1, SBDI-2, SDC…) só conta quando todas as OJs com aquele número estão inativas;
- tema só conta quando o trecho fala em IRR, repetitivo ou TST.
''')
code('int07_catalogo', r'''
from collections import Counter
from src.integracao import guardrails as g
from src.integracao import geracao as ger
cat = g.catalogo_precedentes()
cont = Counter(cat['sumulas'].values())
oj_inativas = Counter(v for series in cat['ojs'].values() for v in series.values() if v in g.NOMES_SITUACAO)
display(pd.DataFrame({'súmulas': cont, 'OJs': oj_inativas, 'temas de IRR': Counter(cat['temas_irr'].values())}).fillna(0).astype(int))
print(f"Catálogo gerado de {cat['origem']} ({cat['registros']} registros, sha256 {cat['origem_sha256'][:12]}…)")
''')

md('int07_alertas_respostas_texto', '''
**Os alertas nas respostas que já existem.** As gerações v1, v3 e v3.1 foram feitas sem a base de precedentes, então só o alerta `precedente_cancelado` pode aparecer nelas. A tabela mostra só o identificador da pergunta e o precedente citado.
''')
code('int07_alertas_respostas', r'''
NOVOS = ('precedente_fonte_trocada', 'tema_sem_tese_como_regra', 'alerta_vigencia_omitido', 'precedente_cancelado')
ler = lambda c: [json.loads(l) for l in Path(c).read_text(encoding='utf-8').splitlines() if l.strip()]
linhas, contagem = [], []
for rotulo, pasta in (('v1', 'geracao'), ('v3', 'geracao_v3'), ('v3.1', 'geracao_v3_1')):
    base = ROOT / 'output/kaggle' / pasta
    pedidos_g = ler(base / 'dataset/pedidos.jsonl')
    respostas = {x['pergunta_id']: x for x in ler(base / 'resultados/respostas.jsonl')}
    bloqueadas = 0
    for p in pedidos_g:
        if not p.get('precisa_llm') or p['pergunta_id'] not in respostas:
            continue
        s = ger.revisar(dict(p, versao_prompt='v3'), respostas[p['pergunta_id']].get('resposta') or '')
        bloqueadas += not s.aprovada
        linhas += [dict(geracao=rotulo, pergunta=p['pergunta_id'], alerta=a['codigo'], detalhe=a['detalhe'])
                   for a in s.alertas if a['codigo'] in NOVOS]
    contagem.append(dict(geracao=rotulo, bloqueadas_validador_v3=bloqueadas,
                         **{c: sum(1 for l in linhas if l['geracao'] == rotulo and l['alerta'] == c) for c in NOVOS}))
alertas_resp = pd.DataFrame(linhas, columns=['geracao', 'pergunta', 'alerta', 'detalhe'])
alertas_resp.to_csv(SAIDA / 'alertas_precedentes_respostas.csv', index=False)
display(pd.DataFrame(contagem).set_index('geracao'))
display(alertas_resp)
''')

md('int07_alertas_conclusao', '''
- **Nenhum bloqueio mudou.** Os alertas novos são informativos; as respostas bloqueadas continuam 34 (v1), 8 (v3) e 13 (v3.1), como no notebook 06.
- **O alerta de cancelado já encontra casos reais.** O modelo cita de memória súmulas em quarentena, como a Súmula 450 (férias pagas fora do prazo), sem avisar do cancelamento noticiado. A confirmação depende do livro oficial do TST de 2026, pendente.
- Os outros 3 alertas só podem aparecer em respostas geradas com precedentes nas fontes (geração v3.2).
''')

md('int07_sinonimos_efeito_texto', '''
## 8. Efeito dos sinônimos nas outras duas bases

A expansão da pergunta vale para a busca inteira: a legislação e as decisões também recebem a pergunta com os sinônimos. Esta seção confere se isso piorou a busca de artigos e decisões, com os **gabaritos e a configuração final do notebook 01 da integração** (híbrida com IDF + reranker, cotas de 3 + 3):
- legislação: 16 perguntas com o artigo esperado;
- jurisprudência: 17 perguntas com o trecho da decisão anotado.

São três execuções nas mesmas perguntas, feitas por `scripts/avaliar_sinonimos_recuperacao.py` (cerca de meia hora na CPU). O notebook só lê o resultado:

| Execução | O que muda |
|---|---|
| 2 bases, sem sinônimos | referência, com a legislação atual (EC 141/2026) |
| 2 bases, com sinônimos | só os sinônimos |
| 3 bases (com precedentes) | a configuração completa: sinônimos, precedentes e união no reranker |

Referência do notebook 01 (seção 10, antes da EC 141): legislação Hit@1 = 0,875, Hit@3 = 1,00, MRR@10 = 0,927; jurisprudência Hit@1 = 0,059, Hit@3 = 0,176, MRR@10 = 0,130.
''')
code('int07_sinonimos_efeito', r'''
ordem = ['2 bases, sem sinônimos', '2 bases, com sinônimos', '3 bases (com precedentes)']
rodadas = {'1ª rodada (15 grupos)': '_15_grupos', '2ª rodada (14 grupos)': ''}
tabelas, por_pergunta = [], []
for rodada, sufixo in rodadas.items():
    res = pd.read_csv(SAIDA / f'sinonimos_resumo{sufixo}.csv').assign(rodada=rodada)
    tabelas.append(res)
    por_pergunta.append(pd.read_csv(SAIDA / f'sinonimos_recuperacao{sufixo}.csv').assign(rodada=rodada))
tab = pd.concat(tabelas).set_index(['fonte', 'rodada', 'configuracao'])[['hit@1', 'hit@3', 'hit@5', 'hit@10', 'mrr@10', 'segundos']]
display(tab.reindex([(f, r, c) for f in ('legislacao', 'jurisprudencia') for r in rodadas for c in ordem]))
porq = pd.concat(por_pergunta)
pos = porq.pivot_table(index=['fonte', 'query_id'], columns=['rodada', 'configuracao'], values='posicao',
                       aggfunc='first', dropna=False)
pos = pos.reindex(columns=[(r, c) for r in rodadas for c in ordem])
mudaram = pos[pos.apply(lambda l: l.fillna(99).nunique() > 1, axis=1)].astype(object).fillna('fora dos 10')
print('Perguntas cuja posição do item correto mudou (as demais ficaram iguais nas 6 execuções):')
display(mudaram)
ultima = porq[(porq.rodada == '2ª rodada (14 grupos)') & (porq.configuracao == ordem[0])]
print('Perguntas que ganham sinônimos (14 grupos):', int(ultima.pergunta_expandida.sum()), 'de', len(ultima))
''')

md('int07_sinonimos_conclusao', '''
- **1ª rodada, com 15 grupos:** a legislação não mudou. Na jurisprudência, a pergunta `juris_011` perdeu a decisão certa, que estava em 4º e saiu dos 10 primeiros. A causa foi o termo "justa causa do empregador", do grupo da rescisão indireta: na busca por palavras, "justa causa" puxa decisões sobre justa causa *do empregado*, o caso oposto.
- **Correção:** o grupo ('rescisão indireta', 'justa causa do empregador') foi retirado de `src/integracao/sinonimos.py`. Testada sozinha, sem esse termo, a `juris_011` ficou em 3º, melhor que sem sinônimos.
- **2ª rodada, com 14 grupos (a que fica no código):** a legislação continua igual (Hit@1 = 0,875, Hit@3 = 1,00, MRR@10 = 0,927). Na jurisprudência, nada piora e a `juris_011` sobe do 4º para o 3º lugar: Hit@3 vai de 0,176 para 0,235 e MRR@10 de 0,130 para 0,135.
- **A terceira base não mexe nas outras duas.** "2 bases, com sinônimos" e "3 bases" têm os mesmos números na legislação e na jurisprudência, porque cada base tem a própria cota de entrega. O custo é o tempo: o reranker lê mais candidatos.
- **Limite da medição:** são 33 perguntas, das quais só 4 ou 5 ganham sinônimos. Ela mostra que os sinônimos não estragam o que já funcionava, mas não mede ganho. O teste no conjunto maior de perguntas fica para depois, como decidido.
''')

md('int07_conclusao', '''
## 9. Conclusões e próximos passos

1. **A base de precedentes está no código de produção.** Ela é uma terceira base de busca, no mesmo nível da legislação e das decisões, e não uma documentação à parte. A junção com o modelo acontece no prompt: o modelo não é treinado de novo.
2. **A busca entrega os 7 precedentes decisivos apontados pelo advogado.** Antes eram 5. A Súmula 60 voltou pela união no reranker, e a Súmula 45 pelos sinônimos.
3. **Nada do que já foi medido mudou.** A configuração padrão continua com duas bases, e o prompt v1 continua idêntico.
4. **O validador ganhou 4 alertas para precedentes** (seção 7), ainda informativos. Nas respostas antigas, nenhum bloqueio mudou, e o alerta de cancelado já encontrou súmulas em quarentena citadas de memória.
5. **Os sinônimos não pioram a busca de artigos e decisões** (seção 8), depois de retirado o grupo da rescisão indireta, que atrapalhava a busca de decisões.
6. **Próximos passos:**
   - medir os 4 alertas novos nas respostas geradas com precedentes e decidir se algum passa a bloquear;
   - gerar de novo as respostas com três bases (geração v3.2, no Kaggle) e medir com o validador v3 e o juiz;
   - se as respostas melhorarem, tornar `configuracao_com_precedentes()` a configuração de produção;
   - para hospedar: restaurar os schemas do banco no servidor, servir o BGE-M3, o reranker e o Qwen3, e criar o ponto de entrada (API).
''')
code('int07_fim', 'r.fechar()')

notebook = dict(cells=celulas,
                metadata=dict(kernelspec=dict(display_name='Python 3', language='python', name='python3'),
                              language_info=dict(name='python', version='3.14.6')),
                nbformat=4, nbformat_minor=5)
DESTINO.write_text(json.dumps(notebook, indent=2, ensure_ascii=False), encoding='utf-8')
print(f'Notebook criado em {DESTINO}')
