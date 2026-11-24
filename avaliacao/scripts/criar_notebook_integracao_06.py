"""Cria avaliacao/notebooks/03_integracao/06_correcoes.ipynb (código; as saídas vêm da execução).

Dados (só identificadores, contagens e códigos de alertas):
  dados/relatorios/integracao/correcoes/validador_v3_respostas_v1.csv     avaliacao/scripts/avaliar_validador_v3.py
  dados/relatorios/integracao/correcoes/validador_v3_respostas_v3.csv     idem, com --rotulo v3 (depois da nova geração)
  dados/relatorios/integracao/juiz/diagnostico_especialista_27b.csv       avaliacao/scripts/importar_revisao_juiz.py
Execução: python avaliacao/scripts/executar_notebook_integracao.py avaliacao/notebooks/03_integracao/06_correcoes.ipynb
"""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[2]
DESTINO = ROOT / 'avaliacao/notebooks/03_integracao/06_correcoes.ipynb'
celulas = []


def md(ident, texto):
    celulas.append(dict(cell_type='markdown', id=ident, metadata={}, source=texto.strip().splitlines(keepends=True)))


def code(ident, texto):
    celulas.append(dict(cell_type='code', id=ident, metadata={}, execution_count=None, outputs=[],
                        source=texto.strip().splitlines(keepends=True)))


md('int06_intro', '''
# 06 — Correções a partir do diagnóstico do especialista

O notebook 04 mostrou onde o sistema erra, pelas 25 respostas que um advogado revisor avaliou às cegas. O maior gargalo é a geração. Os erros mais comuns são:
- citação errada;
- regra distorcida;
- norma citada sem estar nas fontes;
- abertura contraditória.

Este notebook registra as correções aplicadas e mede o efeito delas.

| Correção | Onde | Situação |
|---|---|---|
| **Prompt v3:** regras de citação e de precisão acrescentadas ao prompt do grupo, mais a data atual e o tipo de cada fonte | `worker/evidencia/prompt_juridico.py` (`REGRAS_V3`, `build_rag_prompt(..., versao='v3')`) | implementado |
| **Validador v3:** confere, depois da geração, as falhas detectáveis por regra | `worker/evidencia/guardas.py` (`verificar_saida(..., versao='v3')`) | implementado e medido nas respostas atuais |
| Nova geração com o prompt v3, mesmas fontes | Kaggle: gerador Qwen3 8B (`lexia-geracao-qwen3-v3`) | executada (111 de 111) e medida na seção 6 |
| Geração v3.1: legislação atualizada (EC 141/2026) e regra 24 | Kaggle: `lexia-geracao-qwen3-v3-1` | executada (111 de 111) e medida na seção 6b |
| Novo julgamento das respostas v3 e v3.1 | Kaggle: juiz Gemma 3 27B | a fazer (etapa feita depois, à parte) |
| Critérios novos no juiz | `avaliacao/juiz.py` | a fazer |

**A versão original continua intacta.** O `SYSTEM_PROMPT_LEGAL` do grupo e o guardrail original (`versao='v1'`) não mudaram. O prompt v1 reproduz byte a byte os 111 pedidos já exportados, e os notebooks 03 a 05 continuam reproduzíveis. A versão v3 é escolhida no pedido (`versao_prompt='v3'`), e a revisão usa o validador correspondente.
''')

md('int06_setup_texto', '## 1. Configuração e carga dos dados')
code('int06_setup', r'''
from pathlib import Path
import sys
import pandas as pd
import matplotlib.pyplot as plt
from IPython.display import display, Markdown

ROOT = next(p for p in (Path.cwd(), *Path.cwd().parents) if (p / 'worker/evidencia').exists())
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from worker.evidencia import guardas as g
from worker.evidencia.prompt_juridico import REGRAS_V3

pd.set_option('display.width', 250); pd.set_option('display.max_columns', None)
CORRECOES = ROOT / 'dados/relatorios/integracao/correcoes'
antes = pd.read_csv(CORRECOES / 'validador_v3_respostas_v1.csv')
diag = pd.read_csv(ROOT / 'dados/relatorios/integracao/juiz/diagnostico_especialista_27b.csv')
arquivo_depois = CORRECOES / 'validador_v3_respostas_v3.csv'
depois = pd.read_csv(arquivo_depois) if arquivo_depois.exists() else None
arquivo_v31 = CORRECOES / 'validador_v3_respostas_v3_1.csv'
depois31 = pd.read_csv(arquivo_v31) if arquivo_v31.exists() else None
CODIGOS = ['norma_fora_das_fontes', 'sem_marcacao_fonte', 'lei_citada_com_decisao', 'abertura_categorica',
           'citacao_em_lote', 'metadado_interno']
ROTULOS = {'norma_fora_das_fontes': 'Norma fora das fontes', 'sem_marcacao_fonte': 'Sem [Fonte N]',
           'lei_citada_com_decisao': 'Lei sustentada só por decisão', 'abertura_categorica': 'Abertura sim/não condicionada',
           'citacao_em_lote': 'Mais de 2 fontes na frase', 'metadado_interno': 'Metadado interno exposto'}
print(f'Respostas atuais avaliadas: {len(antes)} · nova geração (v3): {"disponível" if depois is not None else "ainda não executada"}')
''')

md('int06_prompt_texto', '''
## 2. Prompt v3

As regras 16 a 23 foram acrescentadas depois das 15 regras originais. Cada uma corresponde a um tipo de falha do diagnóstico:

| Regra | Falha que ataca (notebook 04) |
|---|---|
| 16. Só citar `[Fonte N]` se o texto da fonte contém a informação; no máximo 2 fontes por afirmação | citação errada |
| 17. Só citar normas que aparecem nas fontes; não completar de memória | completa de memória |
| 18. Decisão judicial não sustenta texto de lei; caso concreto não vira regra geral | citação errada, caso generalizado |
| 19. Regra primeiro, exceção depois; preservar as condições ("desde que", "salvo", "integralmente") | abertura contraditória, regra distorcida |
| 20. Normas de categoria específica (doméstico, rural, professor) só para essa categoria | escopo |
| 21. Citar exatamente o dispositivo que contém a informação | citação errada (CF art. 51, art. 3º, III) |
| 22. Resposta jurídica sempre com pelo menos uma `[Fonte N]` | sem marcação de fonte |
| 23. Usar a data atual e não expor metadados internos (como `in_force`) | prazos e normas temporárias, metadado vazado |

No prompt do usuário, o v3 informa também a **data atual** e o **tipo de cada fonte** (legislação ou decisão judicial). Ele deixa de mostrar o status interno de vigência.
''')
code('int06_prompt', r'''
print(REGRAS_V3)
''')

md('int06_validador_texto', '''
## 3. Validador v3

O validador v3 roda depois da geração, sobre o texto da resposta e as fontes entregues. Ele soma alertas novos aos do guardrail original:

| Alerta | O que confere | Efeito |
|---|---|---|
| `norma_fora_das_fontes` | Lei, súmula, OJ ou tema citado pelo número, e artigo de código (CLT, CF, CPC, CC), que não aparece em nenhuma fonte entregue | **bloqueia** |
| `sem_marcacao_fonte` | Resposta com conteúdo jurídico e nenhuma marcação `[Fonte N]` | **bloqueia** |
| `lei_citada_com_decisao` | Frase que cita norma e só aponta para decisões judiciais | alerta |
| `abertura_categorica` | Abre com "sim" ou "não" e depois condiciona ("no entanto", "depende", "salvo") | alerta |
| `citacao_em_lote` | Mais de duas fontes numa frase | alerta |
| `metadado_interno` | Status de vigência, caminho ou nome de arquivo na resposta | alerta |

**Quando uma resposta é bloqueada,** o fluxo atual manda o mesmo pedido para a LLM B (Llama 3.1 8B). Se ela também falhar, entra a resposta segura. Como o Llama foi pior como gerador, a ação mais adequada para esses alertas pode ser **gerar de novo com o próprio Qwen**, informando o motivo do bloqueio. Essa decisão fica para depois da medição da seção 6.

**O que o validador não confere:** se o conteúdo de um artigo corresponde à afirmação (por exemplo, "art. 482 = justa causa"). Ele só confere se a norma está nas fontes. Essa checagem exige o texto de referência de cada dispositivo e fica para uma próxima etapa.
''')

md('int06_base_texto', '''
## 4. Linha de base: o validador v3 nas 111 respostas atuais

As respostas atuais foram geradas com o prompt v1. Aplicar o validador v3 a elas mostra quanto ele pegaria hoje, antes de qualquer mudança na geração.
''')
code('int06_base', r'''
n = len(antes)
print(f'Bloqueadas pelo guardrail original (v1): {antes.bloqueada_v1.sum()} de {n}')
print(f'Bloqueadas pelo validador v3:           {antes.bloqueada_v3.sum()} de {n} ({antes.bloqueada_v3.mean():.0%})')
contagem = pd.Series({ROTULOS[c]: int((antes[c] > 0).sum()) for c in CODIGOS}).sort_values()
display(contagem.rename('respostas com o alerta').to_frame())

fig, ax = plt.subplots(figsize=(9, 3.8))
codigo_de = {r: k for k, r in ROTULOS.items()}
cores = ['#d62728' if codigo_de[r] in g.BLOQUEANTES_V3 else '#ff7f0e' for r in contagem.index]
ax.barh(contagem.index, contagem.values, color=cores)
for i, v in enumerate(contagem.values):
    ax.text(v + 0.5, i, str(v), va='center', fontweight='bold')
ax.set_xlim(0, n)
ax.set_xlabel(f'Respostas (de {n})')
ax.set_title('Alertas do validador v3 nas respostas atuais (vermelho = bloqueia)')
plt.tight_layout()
plt.savefig(CORRECOES / 'validador_v3_linha_de_base.png', dpi=150)
plt.show()
''')

md('int06_normas_texto', '''
Normas citadas que não estão em nenhuma fonte entregue. A lista traz só o identificador da resposta e a norma, sem o texto. Todas foram conferidas no texto das respostas e são citações sem base, algumas erradas também no conteúdo. Por exemplo: prescrição de "1 ano" atribuída ao art. 1º, § 2º, da CLT; a Lei 11.350/2006, que trata de agentes comunitários de saúde, citada para prescrição; e o art. 114 "da CLT".
''')
code('int06_normas', r'''
display(antes.dropna(subset=['normas_fora'])[['id', 'normas_fora']].reset_index(drop=True))
''')

md('int06_advogado_texto', '''
## 5. O validador pega o que o advogado apontou?

Cruzamento com a classificação das 25 observações do advogado revisor (notebook 04, seção 8). Para cada tipo de falha, a tabela mostra quantas dessas respostas recebem pelo menos um alerta do validador v3 e quantas ele bloquearia.
''')
code('int06_advogado', r'''
m = diag.merge(antes, on='id', suffixes=('', '_v3'))
m['algum_alerta'] = m[CODIGOS].gt(0).any(axis=1)
tipos = ['memoria', 'citacao', 'abertura', 'mecanismo', 'escopo', 'recall', 'ruido', 'precedente', 'fronteira']
linhas = []
for t in tipos:
    sub = m[m[t]]
    linhas.append({'tipo de falha (advogado)': t, 'respostas': len(sub), 'com alerta v3': int(sub.algum_alerta.sum()),
                   'bloqueadas v3': int(sub.bloqueada_v3.sum())})
display(pd.DataFrame(linhas))
print(f'Das 25 respostas reprovadas pelo advogado, o validador v3 bloquearia {m.bloqueada_v3.sum()} '
      f'e alertaria em {m.algum_alerta.sum()}.')
print(f'A regra fixa do juiz tinha aprovado 15; destas, o validador v3 bloquearia '
      f'{int(m[m.veredito_regra == "aprovada"].bloqueada_v3.sum())}.')
''')

md('int06_advogado_leitura', '''
**Leitura.**

1. **O validador pega o que é verificável por regra.** Ele pega norma citada sem estar nas fontes, falta de `[Fonte N]`, lei sustentada só por decisão e abertura contraditória. Isso cobre boa parte das falhas de citação e de memória.
2. **As "leis de memória" estavam, na verdade, nos acórdãos entregues.** Ao conferir o texto das fontes, várias leis que o advogado classificou como "de memória" estavam nos acórdãos:
   - na pergunta do saque do FGTS: a Lei 13.979/2020 e o Decreto Legislativo 6/2020;
   - na do Imposto de Renda: a Lei 12.350/2010 e a IN 1.127/2011;
   - na de prescrição: a Lei 14.010/2020;
   - na do FGTS: a MP 946/2020.

   O advogado não tinha acesso ao texto dos trechos. Então nesses casos o erro não é inventar a norma: é tirar uma lei de uma decisão, muitas vezes uma regra temporária da pandemia, e apresentá-la como regra atual. Quem pega isso é o alerta `lei_citada_com_decisao`, junto com as regras 18 e 23 do prompt.
3. **Regra distorcida, recall, ruído, precedente e fronteira não são detectáveis por regra.** Distorcer a condição de uma súmula ou contar um prazo errado exige conhecimento jurídico: isso fica com o prompt v3 e com o juiz. Recall, ruído, precedente e fronteira são problemas da busca e do corpus: base de precedentes, recuperação em bloco e bases curadas.
''')

md('int06_depois_texto', '''
## 6. Depois: nova geração com o prompt v3

**Procedimento:**
1. **Feito:** as 111 respostas foram geradas de novo com o prompt v3 (regras 16 a 23), com as **mesmas fontes** dos pedidos atuais. Assim, só o prompt mudou.
   - O modelo, a temperatura 0 e a semente são os mesmos.
   - O hash de cada resposta confere com o do pedido v3 enviado.
2. **Feito:** as respostas foram revisadas com o validador v3: `python avaliacao/scripts/avaliar_validador_v3.py --respostas dados/output/kaggle/geracao_v3/resultados/respostas.jsonl --pedidos dados/output/kaggle/geracao_v3/dataset/pedidos.jsonl --rotulo v3`.
3. **A fazer:** julgar as respostas v3 com o Gemma 3 27B. Essa etapa é feita depois, à parte.

**Ressalva:** os pedidos v3 foram montados antes da atualização da legislação com a EC 141/2026 e antes da regra 24 (notas de vigência). As fontes são as antigas, e a comparação mede só o efeito das regras 16 a 23.
''')
code('int06_depois', r'''
if depois is None:
    print('Nova geração com o prompt v3 ainda não executada.')
else:
    comp = pd.DataFrame({
        'prompt v1 (atual)': [int(antes.bloqueada_v3.sum())] + [int((antes[c] > 0).sum()) for c in CODIGOS],
        'prompt v3': [int(depois.bloqueada_v3.sum())] + [int((depois[c] > 0).sum()) for c in CODIGOS],
    }, index=['bloqueadas pelo validador v3'] + [ROTULOS[c] for c in CODIGOS])
    display(comp)
    ax = comp.plot.barh(figsize=(9, 4.2), color=['#7f7f7f', '#1f77b4'])
    ax.set_xlabel('Respostas')
    ax.set_title('Validador v3: respostas com prompt v1 × prompt v3')
    plt.tight_layout()
    plt.savefig(CORRECOES / 'validador_v3_antes_depois.png', dpi=150)
    plt.show()
''')

md('int06_depois_mudancas_texto', '''
**Resolvidas e novas.** Os totais escondem as trocas: uma resposta pode deixar de ter um alerta e outra passar a ter. A tabela abaixo mostra, para cada alerta, quantas respostas o tinham no v1 e deixaram de ter no v3, e o contrário.
''')
code('int06_depois_mudancas', r'''
if depois is not None:
    mm = antes.merge(depois, on='id', suffixes=('_v1', '_v3'))
    trocas = pd.DataFrame([{'alerta': ROTULOS[c], 'v1': int((mm[c + '_v1'] > 0).sum()), 'v3': int((mm[c + '_v3'] > 0).sum()),
                            'resolvidas no v3': int(((mm[c + '_v1'] > 0) & (mm[c + '_v3'] == 0)).sum()),
                            'novas no v3': int(((mm[c + '_v1'] == 0) & (mm[c + '_v3'] > 0)).sum())} for c in CODIGOS])
    display(trocas)
    print(f"Bloqueadas pelo validador v3: v1 {int(mm.bloqueada_v3_v1.sum())} -> v3 {int(mm.bloqueada_v3_v3.sum())} "
          f"(nas duas: {int((mm.bloqueada_v3_v1 & mm.bloqueada_v3_v3).sum())}; só no v3: {int((~mm.bloqueada_v3_v1 & mm.bloqueada_v3_v3).sum())})")
    display(depois[depois.bloqueada_v3][['id', 'bloqueantes_v3', 'normas_fora']].reset_index(drop=True))

    # Marcações de fonte e tamanho (respostas ficam fora do Git, em dados/output/kaggle; a célula pula se não existirem)
    import json, re, statistics
    arquivos = {'v1': ROOT / 'dados/output/kaggle/geracao/resultados/respostas.jsonl',
                'v3': ROOT / 'dados/output/kaggle/geracao_v3/resultados/respostas.jsonl'}
    if all(a.exists() for a in arquivos.values()):
        marca = lambda t: len(re.findall(r'\[Fonte \d+\]', t))
        linhas = []
        for rot, arq in arquivos.items():
            textos = [json.loads(l)['resposta'] for l in arq.read_text(encoding='utf-8').splitlines() if l.strip()]
            linhas.append({'prompt': rot, 'respostas': len(textos), 'caracteres (média)': int(statistics.mean(map(len, textos))),
                           '[Fonte N] por resposta (média)': round(statistics.mean(map(marca, textos)), 1),
                           'sem nenhum [Fonte N]': sum(marca(t) == 0 for t in textos)})
        display(pd.DataFrame(linhas).set_index('prompt'))
''')

md('int06_depois_leitura', '''
**Leitura.**

1. **O prompt v3 reduziu os bloqueios de 34 para 8.** As duas falhas bloqueantes caíram:
   - respostas sem marcação de fonte: de 21 para 1. Com a regra 22, quase toda resposta passou a marcar `[Fonte N]`, em média 4,5 por resposta contra 3,2;
   - normas citadas fora das fontes: de 14 para 4, com a regra 17.
2. **As 4 normas fora das fontes que sobraram são erros reais** (conferidas uma a uma):

   | Resposta | O que a resposta diz | Problema |
   |---|---|---|
   | q09_p1_JUS-031 | "art. 114, § 1º, da CLT" para a prescrição de 2 anos | Artigo errado, de memória. A prescrição está no art. 7º, XXIX, da CF e no art. 11 da CLT |
   | q09_p2_FAQ30 | "Art. 602 da CLT" | A fonte entregue é o art. 602 do **Código Civil**, atribuído à CLT |
   | q09_p2_FAQ40 | "art. 7º, XIII, da CF: 44 horas semanais" | Não está nas fontes. E, depois da EC 141/2026, a redação mudou: hoje a resposta precisa da nota de vigência |
   | juris_023 | "art. 7º, XXIX, da CF" | O conteúdo está certo, mas a citação é de memória. A regra 17 pede para não citar o que não está nas fontes |

   Os outros 3 bloqueios vêm do guardrail original (`dispositivo_inconsistente`).
3. **"Lei sustentada só por decisão" subiu de 30 para 35.** As respostas v3 citam mais fontes por frase. Com isso, aparecem mais leis ao lado de marcações de acórdãos. Foram 13 respostas resolvidas e 18 novas: a regra 18 ainda não é seguida de forma consistente. É o próximo ponto a atacar, no prompt ou na entrega das fontes.
4. **Abertura condicionada caiu de 28 para 20** (regra 19).
5. **Nas 25 respostas da amostra do advogado,** o validador bloquearia 1 resposta v3, contra 12 no v1, e alertaria em 11, contra 20. É um sinal do validador, não um veredito de qualidade: o advogado avaliou as respostas v1, não as v3. A qualidade jurídica das respostas v3 será medida pelo juiz 27B, numa etapa feita depois.
''')

md('int06_v31_texto', '''
## 6b. Geração v3.1: legislação atualizada (EC 141/2026) e regra 24

**O que mudou em relação à v3:**
- **Legislação:** as 3 fontes de legislação de cada pedido foram buscadas de novo na versão `ec141_2026_notas`, que tem o art. 7º da CF atualizado e notas de vigência em 5 artigos.
- **Prompt:** é o v3 com a **regra 24**, que manda usar a nota de vigência comparando com a data atual.
- **O que não mudou:** as decisões judiciais, o modelo, a temperatura, a semente e as perguntas.

**Controle:** antes da troca, a mesma busca na versão `original` reproduziu exatamente as fontes de legislação dos 111 pedidos (`avaliacao/scripts/preparar_geracao_v3_1.py`). As 111 respostas conferem com o hash dos pedidos v3.1.
''')
code('int06_v31', r'''
if depois is not None and depois31 is not None:
    tres = pd.DataFrame({
        'v1': [int(antes.bloqueada_v3.sum())] + [int((antes[c] > 0).sum()) for c in CODIGOS],
        'v3': [int(depois.bloqueada_v3.sum())] + [int((depois[c] > 0).sum()) for c in CODIGOS],
        'v3.1': [int(depois31.bloqueada_v3.sum())] + [int((depois31[c] > 0).sum()) for c in CODIGOS],
    }, index=['bloqueadas pelo validador v3'] + [ROTULOS[c] for c in CODIGOS])
    display(tres)
    trocas31 = pd.read_csv(CORRECOES / 'geracao_v3_1_fontes_trocadas.csv')
    print(f"Pedidos com a legislação alterada: {int(trocas31.legislacao_mudou.sum())} de {len(trocas31)} "
          f"(artigos diferentes em {int(trocas31.artigos_mudaram.sum())}; com nota de vigência: {int((trocas31.com_nota_vigencia > 0).sum())}; "
          f"com artigo da EC 141: {int((trocas31.com_ec141 > 0).sum())})")
    x = depois.merge(depois31, on='id', suffixes=('_v3', '_v31'))
    print(f"Bloqueadas nas duas: {int((x.bloqueada_v3_v3 & x.bloqueada_v3_v31).sum())} · só na v3: "
          f"{int((x.bloqueada_v3_v3 & ~x.bloqueada_v3_v31).sum())} · só na v3.1: {int((~x.bloqueada_v3_v3 & x.bloqueada_v3_v31).sum())}")
    display(depois31[depois31.bloqueada_v3][['id', 'bloqueantes_v3', 'normas_fora']].reset_index(drop=True))
else:
    print('Geração v3.1 ainda não avaliada.')
''')
md('int06_v31_leitura', '''
**Leitura.**

1. **A diferença entre v3 e v3.1 é variação do modelo, não efeito da atualização.**
   - Em 107 das 111 perguntas, a única mudança foi o texto do prompt (a regra 24), e mesmo assim só 1 resposta saiu idêntica.
   - Os bloqueios se cruzam: 5 aparecem nas duas gerações, 3 só na v3 e 8 só na v3.1.
   - A diferença de 8 para 13 bloqueios está dentro dessa variação. Mudanças pequenas no prompt reescrevem as respostas mesmo com temperatura 0.
2. **Este conjunto de perguntas quase não toca a EC 141.**
   - A legislação mudou em só 4 pedidos.
   - Os 2 que receberam o art. 7º com nota de vigência não eram sobre jornada nem repouso: o artigo veio por causa de outros incisos. O modelo, corretamente, não usou a nota.
3. **A pergunta sobre jornada continua com erro, e a causa é a busca.** Na pergunta sobre escala 5x2 (q09_p2_FAQ40), a busca não entregou o art. 7º da CF nem a EC 141, e o modelo citou "44 horas semanais" de memória. O validador bloqueou a resposta (norma fora das fontes). A base atualizada só ajuda quando a busca traz o artigo certo.
4. **Para medir o efeito da EC 141 e da regra 24, é preciso um teste dirigido:**
   - um conjunto pequeno de perguntas sobre jornada semanal, repouso e domésticos, com a resposta esperada para antes e depois de 16/12/2026;
   - a investigação de por que a busca não traz o art. 7º da CF em perguntas sobre jornada semanal.
''')

md('int06_conclusao', '''
## 7. Conclusões até aqui

1. **As correções da geração estão implementadas sem quebrar o que existe.** O prompt v3 e o validador v3 são versões novas, escolhidas no pedido. O prompt original reproduz os 111 pedidos já exportados, e os testes de guardrails e geração passam.
2. **Hoje, o validador v3 bloquearia 34 das 111 respostas (31%),** contra 1 do guardrail original. Os motivos (uma resposta tem os dois):
   - 21 respostas sem nenhuma marcação de fonte. O notebook 04 contou 28 porque só aceitava `[Fonte N]` entre colchetes; o validador aceita também "(Fonte N)" e "Fonte N";
   - 14 com norma citada sem estar nas fontes (todas conferidas: são citações sem base, algumas também erradas no conteúdo).

   Nas 25 respostas que o advogado reprovou, o validador bloquearia 12 e alertaria em 20. Das 15 que a regra fixa do juiz tinha aprovado, ele bloquearia 8.
3. **Lei sustentada só por decisão é o alerta mais frequente (30 respostas).** A revisão das fontes mostrou que boa parte das "leis de memória" do diagnóstico vinha dos acórdãos entregues. A correção principal é a regra 18 do prompt.
4. **O prompt v3 funcionou no que é verificável** (seção 6):
   - os bloqueios caíram de 34 para 8;
   - as respostas sem `[Fonte N]` caíram de 21 para 1;
   - as normas fora das fontes caíram de 14 para 4, e as 4 que sobraram são erros reais.

   O ponto fraco que sobra é a lei sustentada só por decisão, que foi de 30 para 35.
5. **A geração v3.1, com a legislação atualizada e a regra 24, não mudou o quadro** (seção 6b). As diferenças em relação à v3 são variação do modelo, e este conjunto de perguntas quase não toca a EC 141.
6. **Pendências:**
   - julgar as respostas v3 e v3.1 com o juiz 27B (etapa feita depois, à parte);
   - fazer um teste dirigido da EC 141, com perguntas sobre jornada, repouso e domésticos, e verificar por que a busca não traz o art. 7º da CF nessas perguntas;
   - decidir a ação quando o validador bloqueia: fallback para o Llama ou nova geração com o motivo do bloqueio.
''')

notebook = dict(cells=celulas,
                metadata=dict(kernelspec=dict(display_name='Python 3', language='python', name='python3'),
                              language_info=dict(name='python', version='3.14.6')),
                nbformat=4, nbformat_minor=5)
DESTINO.write_text(json.dumps(notebook, indent=2, ensure_ascii=False), encoding='utf-8')
print(f'Notebook criado em {DESTINO}')
