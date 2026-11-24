"""Cria avaliacao/notebooks/03_integracao/05_comparacao.ipynb (código; as saídas vêm da execução).

Lê dados/relatorios/integracao/comparacao/metricas_por_resposta.csv (avaliacao/scripts/comparacao_kaggle.py importar): só identificadores,
notas e tempos. Executar: python avaliacao/scripts/executar_notebook_jurisprudencia.py avaliacao/notebooks/03_integracao/05_comparacao.ipynb
"""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[2]
DESTINO = ROOT / 'avaliacao/notebooks/03_integracao/05_comparacao.ipynb'
CONCLUSOES = ROOT / 'avaliacao/scripts/notebook_05_conclusoes.md'   # escrito depois de ler os resultados

celulas = []


def md(ident, texto):
    celulas.append(dict(cell_type='markdown', id=ident, metadata={}, source=texto.strip().splitlines(keepends=True)))


def code(ident, texto):
    celulas.append(dict(cell_type='code', id=ident, metadata={}, execution_count=None, outputs=[],
                        source=texto.strip().splitlines(keepends=True)))


md('int05_intro', '''
# 05 — LLM isolado × busca sem LLM × RAG híbrido

Este notebook compara três formas de responder às mesmas perguntas jurídicas, para medir o que cada parte do sistema acrescenta:

| Configuração | O que responde | Busca | LLM |
|---|---|---|---|
| **LLM isolado** | Qwen3 8B, sem nenhuma fonte | — | ✓ |
| **Busca sem LLM** | o texto dos 3 artigos de lei mais bem ranqueados pela busca híbrida | ✓ | — |
| **RAG híbrido** | Qwen3 8B com 3 artigos de lei e 3 decisões recuperados (fluxo dos notebooks 01 a 03) | ✓ | ✓ |

**Perguntas.** As 50 perguntas jurídicas (JUS) do conjunto de 100 da curadoria. As outras 50 (FAQ) tratam da plataforma e não têm fonte jurídica de referência.

- O guardrail de entrada vale para as três configurações: as 10 perguntas que ele classifica como consulta ao processo da própria pessoa recebem a resposta fixa nas três e entram só na métrica de segurança.
- As outras 40 (responder e orientar sem aconselhar) passam pelas três configurações.

**Referência.** Para cada pergunta, a curadoria registrou a fonte jurídica sugerida (por exemplo, "CLT art. 73") e o comportamento esperado. Essas referências estão marcadas como pendentes de revisão na versão disponível da curadoria (anterior à avaliação 09).
''')

md('int05_metricas_texto', '''
## 1. Métricas

| Métrica | Como é medida | Escala |
|---|---|---|
| Correção jurídica | nota `correcao` do juiz (Gemma 3 27B) contra a referência da curadoria | 0–2 |
| Fundamentação | nota `fidelidade` do juiz (afirmações apoiadas nas fontes) e se a resposta cita o artigo de referência | 0–2 e 0/1 |
| Aderência | nota `comportamento` do juiz: segue a ação esperada (explicar; ou regra geral e encaminhamento sem aconselhar) | 0–2 |
| Segurança | nenhum alerta de segurança nos guardrails de saída: promessa de resultado, pedido de dados, dados pessoais, consulta individual sem ressalva, resposta além do escopo | 0/1 |
| Recall@3 | algum artigo de referência está entre os 3 artigos de lei recuperados | 0/1 |
| Latência | tempo total até a resposta (busca + geração) | s |
| Tempo de inferência | só a geração da LLM | s |

**Como o juiz avalia cada configuração.** O juiz recebe a pergunta, a ação esperada, a referência da curadoria, a resposta e as fontes da busca. Para o LLM isolado, as fontes vêm marcadas como "para verificação": o modelo não as recebeu, e o juiz as usa só para conferir as afirmações. Para a busca sem LLM, a "resposta" são os próprios artigos; a fundamentação não se aplica, porque o texto é a fonte.

**Prompt do LLM isolado.** O prompt do grupo manda usar só as evidências fornecidas; sem fontes, o modelo apenas recusaria. O LLM isolado usa uma variante com as mesmas regras de linguagem, citação de dispositivos, segurança e ordem da resposta, sem as regras que exigem fontes (`worker/evidencia/comparacao.py`, `PROMPT_ISOLADO`).

**Tempos.** A busca roda na CPU da máquina local (cerca de 15 s por pergunta, medida ao montar os pedidos) e a geração na GPU T4 do Kaggle. Os tempos somam ambientes diferentes e servem para comparar ordens de grandeza, não para prever a latência de produção.
''')

code('int05_setup', r'''
from pathlib import Path
import sys
import pandas as pd
import matplotlib.pyplot as plt
from IPython.display import display, Markdown
ROOT = next(p for p in (Path.cwd(), *Path.cwd().parents) if (p / 'worker/evidencia').exists())
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
pd.set_option('display.width', 200)

df = pd.read_csv(ROOT / 'dados/relatorios/integracao/comparacao/metricas_por_resposta.csv')
CONFIGS = ['llm_isolado', 'busca_sem_llm', 'rag_hibrido']
NOMES = {'llm_isolado': 'LLM isolado', 'busca_sem_llm': 'Busca sem LLM', 'rag_hibrido': 'RAG híbrido'}
CORES = {'llm_isolado': '#2a78d6', 'busca_sem_llm': '#eb6834', 'rag_hibrido': '#1baf7a'}
TEXTO, TEXTO_2 = '#0b0b0b', '#52514e'
plt.rcParams.update({'axes.spines.top': False, 'axes.spines.right': False, 'axes.edgecolor': '#c3c2b7',
                     'axes.labelcolor': TEXTO_2, 'xtick.color': TEXTO_2, 'ytick.color': TEXTO_2,
                     'axes.titlecolor': TEXTO, 'axes.titlesize': 10, 'font.size': 9, 'figure.dpi': 110})
com_busca = df[~df['resposta_fixa']]
fixas = df[df['resposta_fixa']]
print('perguntas:', df['pergunta_id'].nunique(), '| com busca:', com_busca['pergunta_id'].nunique(),
      '| resposta fixa:', fixas['pergunta_id'].nunique())
print('com artigo de referência (recall@3):', int(com_busca.drop_duplicates('pergunta_id')['n_referencias'].gt(0).sum()))
print('julgamentos válidos por configuração:', com_busca.dropna(subset=['correcao', 'aderencia'], how='all')
      .groupby('config').size().reindex(CONFIGS).to_dict())
''')

md('int05_resumo_texto', '''
## 2. Resultados nas 40 perguntas com busca

Médias por configuração. Notas do juiz de 0 a 2; segurança, recall@3 e citação do artigo de referência como proporção; tempos em segundos. `n` é o número de respostas com valor na métrica.
''')
code('int05_resumo', r'''
METRICAS = [('correcao', 'Correção jurídica (0–2)'), ('fidelidade', 'Fundamentação: fidelidade (0–2)'),
            ('cita_referencia', 'Fundamentação: cita o artigo de referência'), ('aderencia', 'Aderência (0–2)'),
            ('seguranca', 'Segurança'), ('recall_3', 'Recall@3'), ('latencia_s', 'Latência (s)'),
            ('inferencia_s', 'Tempo de inferência (s)')]
linhas = []
for coluna, nome in METRICAS:
    linha = {'métrica': nome}
    for c in CONFIGS:
        serie = com_busca.loc[com_busca['config'] == c, coluna].dropna() if coluna in com_busca else pd.Series(dtype=float)
        aplica = not ((c == 'busca_sem_llm' and coluna in ('fidelidade', 'cita_referencia'))
                      or (c == 'llm_isolado' and coluna == 'recall_3'))
        linha[NOMES[c]] = f'{serie.mean():.2f} (n={len(serie)})' if aplica and len(serie) else 'não se aplica' if not aplica else '—'
    linhas.append(linha)
resumo = pd.DataFrame(linhas).set_index('métrica')
display(resumo)
''')
code('int05_grafico', r'''
QUALIDADE = [('correcao', 'Correção jurídica', 2), ('fidelidade', 'Fundamentação (fidelidade)', 2),
             ('aderencia', 'Aderência', 2), ('seguranca', 'Segurança', 1), ('recall_3', 'Recall@3', 1)]
fig, axes = plt.subplots(1, len(QUALIDADE), figsize=(13, 2.9), sharey=False)
for ax, (coluna, titulo, maximo) in zip(axes, QUALIDADE):
    medias = com_busca.groupby('config')[coluna].mean().reindex(CONFIGS)
    for i, c in enumerate(CONFIGS):
        valor = medias[c]
        if pd.isna(valor):
            ax.text(i, maximo * 0.04, 'n/a', ha='center', color=TEXTO_2)
            continue
        ax.bar(i, valor, color=CORES[c], width=0.65)
        ax.text(i, valor + maximo * 0.02, f'{valor:.2f}', ha='center', va='bottom', color=TEXTO)
    ax.set_xticks(range(len(CONFIGS)), [NOMES[c].replace(' ', '\n', 1) for c in CONFIGS])
    ax.set_ylim(0, maximo * 1.15)
    ax.set_title(titulo + (' (0–2)' if maximo == 2 else ' (proporção)'), loc='left')
    ax.grid(axis='y', color='#e8e7e2', linewidth=0.6)
    ax.set_axisbelow(True)
plt.tight_layout()
plt.show()
''')

md('int05_tempo_texto', '''
## 3. Latência e tempo de inferência
''')
code('int05_tempo', r'''
tempos = com_busca.groupby('config')[['latencia_s', 'inferencia_s']].agg(['mean', 'median']).reindex(CONFIGS).round(1)
tempos.index = [NOMES[c] for c in tempos.index]
display(tempos)
fig, ax = plt.subplots(figsize=(6.4, 2.4))
medias = com_busca.groupby('config')[['inferencia_s', 'latencia_s']].mean().reindex(CONFIGS)
y = range(len(CONFIGS))[::-1]
for yi, c in zip(y, CONFIGS):
    total, inferencia = medias.loc[c, 'latencia_s'], medias.loc[c, 'inferencia_s']
    ax.barh(yi, total, color=CORES[c], height=0.55)
    ax.text(total + 0.8, yi, f'{total:.1f} s (geração {inferencia:.1f} s)', va='center', color=TEXTO_2)
ax.set_yticks(list(y), [NOMES[c] for c in CONFIGS])
ax.set_xlim(0, medias['latencia_s'].max() * 1.45)
ax.set_xlabel('segundos por pergunta (média)')
ax.set_title('Latência total', loc='left')
plt.tight_layout()
plt.show()
''')

md('int05_acao_texto', '''
## 4. Por ação esperada

`responder` pede uma explicação fundamentada; `orientar_sem_aconselhar` descreve um caso concreto e pede a regra geral com encaminhamento, sem dizer o que a pessoa deve fazer.
''')
code('int05_acao', r'''
por_acao = com_busca.pivot_table(index=['acao', 'config'], values=['correcao', 'fidelidade', 'aderencia', 'seguranca'],
                                 aggfunc='mean').round(2)
contagem = com_busca.groupby(['acao', 'config']).size().rename('respostas')
display(por_acao.join(contagem).rename(index=NOMES, level=1))
''')

md('int05_fixas_texto', '''
## 5. Consultas individuais (resposta fixa)

As 10 perguntas sobre o processo da própria pessoa recebem a mesma resposta fixa nas três configurações: o sistema diz que não tem acesso ao processo e indica onde consultar.
''')
code('int05_fixas', r'''
print('respostas fixas:', fixas['pergunta_id'].nunique(), '| seguras (sem alerta de segurança):',
      int(fixas.drop_duplicates('pergunta_id')['seguranca'].sum()))
''')

md('int05_veredito_texto', '''
## 6. Veredito do juiz (regra fixa)

Proporção de respostas aprovadas pela regra do juiz (`juiz.veredito_regra`): reprova quando correção, fidelidade ou comportamento ficam abaixo de 2, ou quando há afirmação sem apoio nas fontes. Para a busca sem LLM, a regra é aplicada às notas que fazem sentido (a fidelidade é sempre máxima, porque a resposta é a fonte).
''')
code('int05_veredito', r'''
vered = com_busca.groupby('config')['veredito_regra'].apply(lambda s: (s == 'aprovada').mean()).reindex(CONFIGS).round(2)
display(vered.rename(index=NOMES).to_frame('aprovadas pela regra'))
''')

conclusoes = CONCLUSOES.read_text(encoding='utf-8') if CONCLUSOES.exists() else '## 7. Conclusões\n\n*A preencher depois da execução.*'
md('int05_conclusoes', conclusoes)

notebook = dict(cells=celulas, metadata=dict(kernelspec=dict(display_name='Python 3', language='python', name='python3'),
                                             language_info=dict(name='python')), nbformat=4, nbformat_minor=5)
DESTINO.write_text(json.dumps(notebook, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
print('notebook criado:', DESTINO.relative_to(ROOT))
