# Estado da integração (03_integracao)

Este é o documento de passagem para retomar o trabalho em outra sessão ou máquina. Atualizado em 2026-11-22.

**Próximos passos, em ordem:**
1. **Base de precedentes:** integrar como **terceira fonte** da busca. O notebook 06 de avaliação está pronto (ver a seção sobre ele). O que integrar:
   - busca híbrida + reranker, com o conjunto do reranker vindo da **união** dos primeiros da busca semântica e da busca por palavras;
   - cota inicial de 3 precedentes;
   - citação pelo nome no prompt ("Súmula 338, I, do TST");
   - dicionário de sinônimos jurídicos na pergunta ("13º salário" = "gratificação natalina").
2. **Feito pela usuária, à parte:** juiz Gemma 3 27B nas respostas v3 e v3.1. Não rodar.
3. **Testes num conjunto maior de perguntas, decididos pela usuária para depois:**
   - EC 141/2026 e regra 24 (jornada, repouso e domésticos);
   - diagnóstico da busca por jornada semanal (a pergunta FAQ40 não recebe o art. 7º da CF);
   - normalização do índice de palavras na legislação e na jurisprudência;
   - cotas de entrega (2+2 × 3+3 × 5+5);
   - básico + decisões × híbrido nas 111 perguntas.
4. **Correções que ficaram em aberto:**
   - critérios novos do juiz, detectáveis por regra;
   - ação quando o validador bloqueia: fallback para o Llama ou nova geração com o motivo do bloqueio;
   - o alerta "lei sustentada só por decisão", que subiu na v3.
5. **Pendências de fonte, que dependem da usuária:**
   - livro oficial de súmulas e OJs do TST de 2026, ou a resolução dos cancelamentos, para confirmar os 22 enunciados em quarentena;
   - divisor 220 da LC 150, ligado às 44 horas.

## Atualização de 2026-11-22 (noite): avaliação da base de precedentes (notebook 06) e quadros de dados

**Notebook `06_avaliacao_recuperacao_precedentes`** (`scripts/criar_notebook_precedentes_06.py`, `src/precedentes/avaliacao.py`). Ele leva cerca de 80 minutos na CPU, sobretudo por causa do reranker.

**Gabarito A, especialista:** 7 perguntas reais em que o advogado apontou o precedente que faltou.
- Com a busca híbrida + reranker, ficam em 1º as Súmulas 338, 276, 378 e 6 e o Tema 58. Na base de jurisprudência, eram da 8ª à 3.370ª posição.
- A semântica sozinha acha 6 dos 7 até o 3º lugar.
- Falhas:
  - **Súmula 60:** a fusão com a busca por palavras a levou ao 21º lugar, fora dos 20 que o reranker reordena;
  - **Súmula 45:** "13º salário" × "gratificação natalina", um sinônimo que nenhuma busca ligou.

**Gabarito B, prata:** 300 trechos de acórdãos que citam exatamente um precedente, com a citação mascarada e sem transcrição, no máximo 3 por precedente.

| Busca | Hit@1 | Hit@3 | MRR@10 |
|---|---|---|---|
| **Híbrida + reranker** | 0,33 | 0,53 | 0,44 |
| Semântica | 0,29 | 0,46 | 0,40 |
| Híbrida sem reranker | 0,27 | 0,43 | 0,37 |
| Por palavras | 0,17 | 0,30 | 0,25 |

- **Por que B é conservador:** muitos erros são súmulas processuais (126, 333, 422), e parte deles é um precedente vizinho correto (Súmula 438 e Tema 211).
- **Relatórios:** `reports/precedentes/avaliacao/`, só com identificadores, nomes de precedentes e posições.

**Quadros "Dados desta etapa"** (pedido da usuária):
- **Onde estão:** em todos os notebooks de dados, ou seja, legislação 01 a 06, jurisprudência 01 a 06 e precedentes 00 a 06.
- **O que mostram:** entrada e saída com caminho no repositório, formato, quantidade e se o arquivo é versionado, mais as notas "Lê/Grava" antes das células que gravam.
- **Formatos:**
  - precedentes: a base é **JSONL**, não CSV, porque os registros têm campos com listas;
  - legislação: Parquet, CSV e JSON;
  - jurisprudência: Parquet canônico e exportação em JSONL.
- **Como foram inseridos:** só como células novas, sem reexecutar.
  - Na jurisprudência, pela API de preservação (`AGENTS.md`), com cópia em `reports/jurisprudencia/versoes_notebooks/`.
  - O diff mostra 286 linhas acrescentadas e 0 removidas.
- **Cuidado:** os geradores sobrescrevem o notebook executado. Depois de rodar um gerador, é preciso reexecutar o notebook.

## Atualização de 2026-11-22 (noite): base de precedentes do TST, notebooks 00 a 05

Pasta `notebooks/05_docs_precedentes/`, com os notebooks 00 a 05 executados e o `README.md`. **Os notebooks da pasta ainda não foram commitados, a pedido da usuária.** O código, os scripts geradores e os relatórios estão no Git (commits `57d1fe9` e `a0f314a`).

| Notebook | O que faz | Resultado |
|---|---|---|
| `00_introducao_precedentes` | Por que criar a terceira base, os três tipos de documento, os documentos recebidos, as respostas sem precedente e o teste de posição | Na base de jurisprudência, a súmula certa ficaria entre a 8ª e a 3.370ª posição |
| `01_auditoria_precedentes` | Inventário com hash, papel de cada documento, extração bruta, numeração e vigência | 10 PDFs (8 distintos + 2 cópias "(1)"); séries completas, sem falta de número |
| `02_eda_precedentes` | Volume, tokens, ruído do texto bruto, cor do título × tese, normas citadas e cobertura | 7 de 8 precedentes das respostas reprovadas estão nos documentos; o 8º é do STF |
| `03_limpeza_estruturacao_precedentes` | Campos, vigência, quarentena e o **JSONL único** | 1.493 registros: 463 súmulas, 709 OJs e 321 temas; 1.022 buscáveis |
| `04_chunking_precedentes` | Um trecho por enunciado ou item, com cabeçalho e caput repetido; limite de 220 tokens | 1.268 trechos |
| `05_embeddings_indexacao_precedentes` | BGE-M3 na mesma revisão; schema `lex_precedentes`; índice de palavras normalizado | Versão `bdf048e6…` validada |

**Fontes:**
- **Súmulas e OJs:** coletânea do TRT-3 com a jurisprudência do TST, atualizada até 28/06/2024, páginas 65 a 256.
- **Temas:** índice de IRR do TST de 19/11/2026, páginas 12 a 121.
- **Fora desta base:**
  - o índice de repercussão geral do STF, que fica para uma etapa posterior;
  - o acórdão 168, que tem dados pessoais;
  - a coletânea do TRT-2 de 2021;
  - a EC 141, que foi para a base de legislação.

**Vigência:**

| Situação | Quantidade | Na busca? |
|---|---|---|
| Vigente | 323 súmulas e 401 OJs | sim, menos as que estão em quarentena |
| Cancelada | 138 súmulas e 308 OJs | não, mas fica registrada |
| Suspensa pelo STF | 2 (Súmulas 228 e 277) | não |
| Tese fixada | 221 temas | sim |
| Afetado sem tese | 98 temas | sim |
| Tese superada | 2 temas | não |

A notícia do cancelamento de 36 enunciados não é fonte oficial. Ela vira alerta. Os **22** enunciados que ela dá como cancelados por inteiro ficam fora da busca (quarentena). Os 3 com cancelamento parcial (Súmulas 6, 331 e 372) ficam na busca, com o alerta.

**Correções feitas na estruturação, depois de conferir os casos:**
- **Parênteses de situação seguidos:** o cabeçalho às vezes tem dois, e todos passaram a ser lidos. Com isso, a Súmula 164 e as OJs 331 e 338 da SBDI-1 passaram a canceladas. Antes, estavam como vigentes e buscáveis.
- **Nova situação `suspensa`:** criada para as Súmulas 228 e 277.
- **"º" e "ª":** não contam mais como minúscula no teste do título, o que causava vazamento do cabeçalho em 9 registros.
- **Itens numerados como "I.":** passaram a ser reconhecidos (Súmula 85).
- **Caput antes dos itens:** passou a se repetir em cada trecho por item (OJ 225 da SBDI-1).
- **Hashes:** o JSONL é gravado com LF, e o hash é calculado sobre os bytes.

**Busca por palavras** (`src/precedentes/normalizacao.py`, versão `normalizacao-lexica-v1`):
- **Onde vale:** só no índice e na pergunta. O texto guardado e entregue ao modelo continua o oficial.
- **Normalizações:**
  - "§" vira "paragrafo" e "art." vira "artigo";
  - "nº" sai antes de número;
  - o ordinal sai ("7º" = "7");
  - o ponto de milhar sai e a barra entre números é separada ("8.036/1990" = "8036 / 1990");
  - o numeral romano vira uma marca própria ("XIII" = "inc13"; antes, o índice juntava os incisos XII e XIII);
  - tudo fica em minúsculas e sem acento.
- **Sem stopwords** (pedido da usuária): configuração `lex_precedentes.pt_sem_stopwords`, que mantém o radicalizador. O padrão em português descartava "não", e "é devido" e "não é devido" ficavam iguais.
- **Peso IDF:** cada palavra pesa pela raridade, como no BM25, e as palavras comuns quase não contam.
- **Trechos e vetores continuam valendo:** a normalização não muda o texto de onde eles são gerados.

**Testes de funcionamento:**
- cada trecho acha a si mesmo em 50 de 50 casos;
- três perguntas de exemplo, escritas para o teste e não tiradas da curadoria:

| Pergunta de exemplo | Busca semântica | Busca por palavras |
|---|---|---|
| Súmula 338 | 1º | 1º |
| Tema 58 | 1º | 1º |
| Súmula 60 | 3º | 4º |
| "Lei 8036 saque do FGTS" | — | OJ 42 em 1º |

A medida que vale, com gabarito, fica no notebook 06.

**Como reproduzir:**
1. PDFs em `data/raw/precedentes/`, fora do Git. O hash de cada um está em `reports/precedentes/auditoria/inventario_documentos.csv`.
2. `python scripts/criar_notebook_precedentes_00.py`, `scripts/criar_notebooks_precedentes_01_03.py` e `scripts/criar_notebooks_precedentes_04_05.py`.
3. Executar na ordem, de 00 a 05, com `python scripts/executar_notebook_integracao.py notebooks/05_docs_precedentes/<notebook>.ipynb`. O 05 precisa do Postgres no Docker. Os vetores levam cerca de 9 minutos na CPU e depois ficam em cache, em `data/processed/precedentes/vetores_bge_m3.npy`.
4. A cadeia confere os hashes: o 04 confere o JSONL do 03, e o 05 confere os trechos do 04. Se o texto mudar, nasce uma nova versão de `lex_precedentes`, e a anterior passa a `substituido`.

## Atualização de 2026-11-22: geração v3 medida (notebook 06, seção 6)

A geração `lexia-geracao-qwen3-v3` terminou: 111 de 111 respostas válidas, com média de 27 s por resposta. O hash de cada resposta confere com o do pedido v3. As respostas ficam em `output/kaggle/geracao_v3/resultados/`, fora do Git.

| Validador v3 | v1 | v3 |
|---|---|---|
| Bloqueadas | 34 | 8 |
| Norma fora das fontes | 14 | 4 (as 4 conferidas: erros reais) |
| Sem [Fonte N] | 21 | 1 |
| Lei sustentada só por decisão | 30 | 35 (ponto fraco que sobra) |
| Abertura condicionada | 28 | 20 |

- O CSV está em `reports/integracao/correcoes/validador_v3_respostas_v3.csv`.
- **O juiz 27B nas respostas v3 fica para a usuária fazer depois.** Não rodar.
- Os pedidos v3 usam a legislação antiga e as regras 16 a 23.

**Geração v3.1 (`lexia-geracao-qwen3-v3-1`, notebook 06, seção 6b):**
- **Configuração:** legislação `ec141_2026_notas` e prompt v3 com a regra 24. As decisões judiciais são as mesmas da v3.
- **Controle:** a versão `original` reproduziu as fontes de legislação dos 111 pedidos.
- **Script:** `scripts/preparar_geracao_v3_1.py`. As trocas estão em `reports/integracao/correcoes/geracao_v3_1_fontes_trocadas.csv`.
- **Validador v3:** 13 bloqueadas, contra 8 na v3. É variação do modelo: só 1 resposta saiu idêntica à v3, e os bloqueios se cruzam (5 nas duas, 3 só na v3, 8 só na v3.1).
- **Efeito da EC 141:** a legislação mudou em só 4 pedidos, e nenhum deles é sobre jornada.
- **Pergunta 5x2 (FAQ40):** continua citando 44 h de memória, porque a busca não entrega o art. 7º da CF.
- **Testes da EC 141 e da regra 24:** decisão da usuária (2026-11-22) de fazê-los depois, num conjunto maior de perguntas, junto do diagnóstico da busca por jornada semanal. Não criar testes avulsos antes disso.

## Atualização de 2026-11-22: legislação com a EC 141/2026 (jornada de 40 horas e dois dias de repouso)

A Emenda Constitucional nº 141, de 16/10/2026, mudou o art. 7º da CF. A base de legislação **não foi sobrescrita**: foram criadas versões novas dos dois datasets, e as antigas continuam no banco.

| Versão (`VERSOES_LEGISLACAO` em `src/integracao/recuperacao.py`) | D_paragrafo_completo | A_artigo |
|---|---|---|
| `original` (notebooks publicados até aqui) | `036e49f3…` (10.971 trechos) | `508abda2…` (5.284) |
| `ec141_2026` (art. 7º da CF e os 10 artigos da EC) | `2f1ab3f0…` (10.983) | `4cbd0071…` (5.294) |
| `ec141_2026_notas` (**padrão da busca**: a versão anterior mais as notas de vigência em 5 artigos) | `dca7b51d…` (10.983) | `d61d07a5…` (5.294) |

**Trechos que mudaram:**
- Art. 7º da CF:
  - inciso XIII, com 8 horas diárias e 40 semanais e uma nota de vigência para a transição: 44 horas até 15/12/2026, 42 horas a partir de 16/12/2026 e 40 horas a partir de 16/12/2027;
  - inciso XV, com dois dias de repouso a partir de 16/12/2026;
  - o parágrafo único passou a ser o § 1º, e foram incluídos os §§ 2º e 3º.
- Os 10 artigos da EC entraram como documento próprio (`constituicao/emendas/emc-141-2026.md`). Eles tratam de:
  - irredutibilidade salarial;
  - perda de efeito das cláusulas coletivas incompatíveis;
  - transição;
  - exceção para quem tem nível superior e salário alto (art. 8º);
  - contratos públicos.

**Como foi gerado:**
- Só os trechos novos receberam embedding: BGE-M3, mesma revisão, sobre o texto completo, como na base original.
- Os demais trechos foram copiados com o mesmo vetor.

**Onde está registrado:**
- Script: `scripts/atualizar_legislacao_ec141.py`. Ele é idempotente; `--verificar` confere os hashes.
- Transcrição: `data/atualizacoes_legislacao/ec_141_2026/ec_141_2026.md`. O PDF do Planalto é só imagem, por isso a transcrição foi manual.
- Relatório: `reports/legislacao/atualizacoes/ec_141_2026.json`.

**Atenção:**
- **A visão lexical acompanha a versão:** `lex_integracao.lexico_legislacao` guarda o ID do dataset no comentário. O `Recuperador` recria a visão quando a versão muda. Para reproduzir um notebook antigo, use `Recuperador(..., versao_legislacao='original')`.
- **A geração v3 que está no Kaggle não muda:** ela foi preparada com as fontes antigas, nos pedidos já montados. Por isso fica comparável com a v1.
- **Limpeza do banco:** as duas versões intermediárias das notas (2 e 4 notas) foram apagadas, porque nunca foram usadas. Use conexão com `autocommit=True` para apagar. Com uma consulta antes do `transaction()`, a exclusão fica numa transação externa que não é confirmada.

**Notas de vigência** (versão `ec141_2026_notas`, padrão da busca):
- **Script:** `scripts/atualizar_legislacao_notas_ec141.py`. As notas ficam em `reports/legislacao/atualizacoes/ec_141_2026_notas.json`.
- **Onde há nota:**
  - LC 150/2015, art. 2º: transição de 44, 42 e 40 horas para os domésticos, pelo § 1º do art. 7º da CF;
  - Lei 605/1949, art. 1º; LC 150/2015, art. 16; e CLT, arts. 67 e 385: 2 dias de repouso a partir de 16/12/2026, no lugar das 24 horas.
  - Uma busca na base inteira não encontrou mais nenhum artigo com 44 horas ou 24 horas de repouso sem nota.
- **Como a nota funciona:** o texto da lei não muda. A nota vem entre colchetes logo depois do dispositivo e cita "art. 7º, XIII/XV, da CF", para que o validador v3 aceite a citação da CF feita a partir dela. Ela só traz o que a EC e a CF dizem. A "regulamentação por decreto" de um texto recebido pela usuária ficou de fora, porque não está na EC.
- **Prompt v3:** ganhou a **regra 24**. O modelo deve usar a nota, comparar com a DATA ATUAL e apresentar primeiro a regra nova.
  - A geração v3 enviada ao Kaggle usou as regras 16 a 23; a v3.1 usou a regra 24.
- **Teste de ponta a ponta:** nas perguntas sobre jornada dos domésticos, repouso de 24 horas e folgas da doméstica, todos os artigos com a regra antiga chegaram com a nota.
- **Em aberto:** o divisor 220 da LC 150, art. 2º, § 2º, corresponde às 44 horas. A EC não trata disso; ver a Súmula 431 do TST quando os precedentes entrarem na busca.

## Atualização de 2026-11-22 (Windows): validação com advogado revisor e notebook 04

Um advogado revisor avaliou às cegas 25 das 111 respostas do Qwen (sorteadas com semente fixa: 15 aprovadas e 10 reprovadas pela regra), numa página local gerada por `scripts/montar_revisao_juiz_html.py`. Ele não viu nada do juiz. O notebook `notebooks/03_integracao/04_avaliacao.ipynb` foi reescrito com o juiz 27B e as seções novas 7 (validação com especialista), 8 (diagnóstico) e 9 (por onde corrigir). Commit `64851a0`.

| | Advogado | Regra fixa | Veredito do modelo |
|---|---|---|---|
| Aprovadas (de 25) | 0 | 15 | 25 |
| Concordância com o advogado | — | 10 de 25 (40%) | 0 de 25 |

- **Vereditos:** 15 foram marcados na página. Os outros 10 foram lidos nas observações (`INFERIDO` no importador), e 4 dessas leituras são incertas. Só com as 15 marcadas, a regra concorda em 5.
- **Leitura:** o juiz é brando diante de um especialista. A aprovação do juiz (67 de 111 pela regra) deve ser lida como um teto otimista. O veredito do próprio modelo fica descartado de vez. Como não houve nenhuma aprovação humana, não se mede se a regra reprova respostas boas.
- **Cuidados:** os critérios são diferentes. O juiz confere contra as fontes e a referência; o advogado, contra o direito inteiro. Há um revisor só, e as observações têm sinais de apoio de IA (restos de citação de sites; a observação da FAQ13 trata de outro assunto). Vale pedir ao revisor que confirme os 10 vereditos em branco.
- **Diagnóstico** (classificação manual das 25 observações, em `DIAGNOSTICO` no importador):
  - geração em 24 respostas: citação errada 18, regra distorcida 17, conteúdo de memória 11, abertura contraditória 7, escopo ou fonte ignorada 5;
  - recuperação em 19: fonte por palavra solta 14, norma central ausente 13;
  - corpus em 13: falta súmula ou tema do TST 8, fora do corpus ou produto 5.
- **O juiz não enxerga essas falhas:** nas 11 respostas com conteúdo de memória, deu fidelidade média 2,00 e marcou afirmação sem apoio em só 3. Entre as 15 aprovadas pela regra, 10 têm citação errada.
- **Marcação de fontes:** 28 das 111 respostas da geração (8 das 25) não têm nenhum `[Fonte N]`.
- **Exemplo de falha de geração:** na pergunta do saque do FGTS (q09_p1_JUS-007), o art. 20-A, § 2º, II, da Lei 8.036 estava nas fontes e diz que o saque-aniversário não libera o saldo na demissão. A resposta omitiu essa regra e falou de "poupança digital", que não está nas fontes. Já o art. 20 chegou inteiro, com 16 mil caracteres, e a regra da rescisão ficou diluída.

**Decisões da usuária nesta sessão:**

- **Juiz:** continua o Gemma 3 27B com a regra fixa. Não testar o Llama como juiz. Na comparação como gerador, o Llama foi mais rápido (22,8 s × 36,8 s), mas pior: 66 × 44 reprovadas e correção 1,46 × 1,71.
- **Número de fontes:** não reduzir para 1 fonte no contexto do modelo. O Hit@1 dos artigos é só 0,39–0,42, contra 0,58 de Hit@3. Exibir uma fonte principal ao usuário continua como opção. A cota deve ser ajustada por teste (2+2 × 3+3 × 5+5).
- **Base de precedentes:** súmulas, OJs e temas de recursos repetitivos do TST vão para uma **terceira base**, `lex_precedentes`, e não para a de jurisprudência.
  - **Teste de ranking com BGE-M3:** misturada aos 303 mil chunks de acórdãos, a súmula certa ficou além da 100ª posição em 4 de 5 perguntas. Os textos das súmulas foram digitados de memória, só para o teste.
  - **Por que separar:** anexar também exigiria validar de novo o dataset congelado e quebraria a reprodutibilidade dos notebooks 01, 04 e 05.
  - **Pasta:** `notebooks/05_docs_precedentes/`, com 00 introdução, 01 auditoria, 02 EDA, 03 limpeza e estruturação, 04 chunking, 05 embeddings e indexação, 06 avaliação da recuperação. Não renumerar as pastas 03 e 04.
  - **Documentos:** recebidos, em `data/raw/precedentes/`. Os notebooks 00 a 05 estão prontos (ver a seção da noite de 2026-11-22).

**Como reproduzir:**

1. Colocar o JSON exportado pelo revisor (`avaliacao_respostas_marcacoes_<nome>.json`) em `output/integracao/revisao_juiz/`, pasta que fica fora do Git.
2. Rodar `python scripts/importar_revisao_juiz.py`. Ele grava em `reports/integracao/juiz/` os arquivos `concordancia_humano_27b.csv`, `diagnostico_especialista_27b.csv` e `marcacao_fontes_geracao.csv`, só com identificadores, vereditos e marcações. O nome do revisor fica só no JSON.
3. Rodar `python scripts/criar_notebook_integracao_04.py` e depois `python scripts/executar_notebook_integracao.py notebooks/03_integracao/04_avaliacao.ipynb`.

## Atualização de 2026-11-22 (Windows): notebook 05, comparação RAG × LLM

`notebooks/03_integracao/05_comparacao_rag_llm.ipynb` é o validador e observador da qualidade: responde às 40 perguntas JUS da curadoria que seguem para a busca de cinco formas e mede todas com as mesmas métricas (recuperação, tríade do RAG e qualidade do LLM), com um painel de limites mínimos (validador) e o diagnóstico da etapa em que cada resposta reprovada falha (observador). Commit `53c8547`.

| Configuração | Busca | Entrega |
|---|---|---|
| RAG isolado (`busca_sem_llm`) | híbrida | texto dos 3 artigos, sem LLM |
| LLM isolado (`llm_isolado`) | — | Qwen3 8B sem fontes (`PROMPT_ISOLADO`) |
| RAG + LLM básico (`rag_basico`) | só semântica (BGE-M3), sem lexical, RRF ou reranker | 5 artigos |
| RAG + LLM básico + decisões (`rag_basico_jur`) | só semântica | 3 artigos + 3 decisões |
| RAG + LLM híbrido (`rag_hibrido`) | configuração padrão | 3 artigos + 3 decisões |

As três configurações RAG + LLM usam o mesmo modelo, as mesmas opções e o mesmo prompt; só as fontes mudam. As variantes básicas reaproveitam o pedido de geração original do RAG híbrido (texto livre, anterior à saída estruturada v2) e trocam só as fontes. O script confere que o prompt e o pedido do juiz originais continuam reproduzíveis com o código atual antes de montar os novos. O juiz é o Gemma 3 27B com a rubrica da comparação (`SISTEMA_JUIZ_COMPARACAO`) e veredito pela regra fixa. Os 200 julgamentos são válidos.

| | Básico | Básico + decisões | Híbrido |
|---|---|---|---|
| Hit@3 dos artigos | 0,58 | 0,58 | 0,58 |
| Correção (0–2) | 1,62 | 1,75 | 1,78 |
| Afirmações sem apoio | 22% | 14% | 14% |
| Decisões pertinentes | — | 85% | 85% |
| Aprovadas pela regra (de 40) | 16 | 18 | 17 |
| Tempo de busca / latência total | 0,2 s / 34 s | 0,85 s / 41 s | 16 s / 58 s |

- **Achado principal:** o ganho do RAG híbrido sobre o básico vem das 3 decisões, não do algoritmo de busca. Com a mesma entrega, a busca semântica pura e a híbrida ficam praticamente iguais (correção melhor em 6 perguntas e pior em 5), e a semântica é cerca de 19 vezes mais rápida. É um indício, não uma decisão: 40 perguntas e um único juiz. O próximo passo é repetir básico + decisões × híbrido nas 111 perguntas da geração.
- **Referência:** LLM isolado com correção 1,00 e 53% de afirmações sem apoio; RAG isolado com 91% de afirmações apoiadas, mas correção de 1,23. A segurança fica em 100% em todas as configurações.
- **Validador:** todas as configurações com RAG ficam abaixo de dois limites, Hit@3 ≥ 0,70 e afirmações sem apoio ≤ 10%. Os limites foram declarados, não calibrados.
- **Veredito:** a regra fixa é muito mais rígida que o veredito do próprio modelo (LLM isolado: 4 aprovadas pela regra contra 29 pelo modelo). Usar sempre a regra.

**Como reproduzir** (`scripts/comparacao_rag_basico.py`; a variante padrão é `rag_basico`):

1. `buscar --variante V`: busca local (precisa do Postgres no Docker) e grava os pedidos em `output/kaggle/comparacao/<V>/`.
2. Subir o dataset e o kernel (`lexia-comparacao-rag-basico[-jur]`) e esperar a geração.
3. `julgar --variante V`: monta os pedidos do juiz em `output/kaggle/comparacao/juiz_basico[_jur]/`. Subir e rodar o kernel `lexia-comparacao-juiz-basico[-jur]`.
4. `importar`: baixa todas as saídas e grava `reports/integracao/comparacao/metricas_rag_llm_por_resposta.csv` e `recuperacao_rag_por_pergunta.csv` (só IDs, notas e tempos).
5. `python scripts/criar_notebook_05_comparacao_rag_llm.py` e depois `python scripts/executar_notebook_jurisprudencia.py notebooks/03_integracao/05_comparacao_rag_llm.ipynb`. As conclusões ficam em `scripts/notebook_05_comparacao_rag_llm_conclusoes.md`.

**Observações da execução:**

- O CSV da curadoria (`perguntas_consolidadas_pre09.csv`) não existe no Windows. O script tira os 40 IDs e a referência da curadoria dos pedidos do juiz original (dataset `lexia-comparacao-juiz-pedidos`, baixado automaticamente).
- Um pedido do juiz (`rag_basico_jur|q09_p1_JUS-038`) passou do limite estimado de contexto. Foi aceito pela contagem `cl100k` bruta (14.595 ≤ 16.384), sem truncar fontes, e a exceção ficou registrada no pedido. Nos 120 julgamentos originais, os tokens reais do Gemma ficaram entre 0,90 e 0,98 da contagem bruta. O módulo `context_window.py` não foi alterado.
- O construtor anterior do Mac (`scripts/criar_notebook_integracao_05.py`, 3 configurações, `05_comparacao.ipynb`) continua no repositório, mas o notebook dele nunca foi versionado e depende do CSV da curadoria. O notebook novo cobre as mesmas 3 configurações e mais as 2 variantes básicas.

## Extensão multiagentes

A primeira implementação com LangGraph está em `src/multiagentes/`: Analista Qwen3 8B, Validador Gemma 3 12B, ferramenta de busca e uma revisão máxima com feedback. Há CLI, contratos, registros locais e testes de controle. A primeira execução completa dos modelos ocorreu no Kaggle; os artefatos foram conferidos na retomada de 19/11/2026.

A demonstração usa o Kaggle com corpus portátil de legislação e busca lexical, sem o banco local. O adaptador da busca híbrida no pgvector continua disponível como outro modo. Consulte [Sistema multiagentes](sistema_multiagentes.md), [Execução no Kaggle](execucao_multiagentes_kaggle.md) e [Resultados observados](resultados_multiagentes.md). A integração descrita nas seções seguintes permanece como registro do fluxo anterior.

Também foi implementado o [BuscadorLocal](buscador_local.md): leitura do JSON original, embeddings BGE-M3 com revisão fixa, cache SQLite em `dados/output/buscador_local/`, CLI de consulta independente e integração ao grafo por `--modo local`. A base local de 5.284 artigos foi validada estruturalmente. Os testes usam encoders fake para verificar recuperação, persistência, invalidação e integração; essa verificação não representa uma nova avaliação jurídica. A configuração de um remoto DVC e o recorte de jurisprudência da issue da equipe permanecem pendentes neste checkout.

## Atualização de 2026-11-18 (Windows)

- **Juiz Gemma 3 27B importado.** Os kernels `lexia-juiz-gemma3-27b` (9 de calibração + 111 respostas do Qwen) e `lexia-juiz-gemma3-27b-llama` (111 respostas do Llama) estavam concluídos no Kaggle, mas o resultado não tinha sido importado. Agora: `julgamentos_27b.csv`, `julgamentos_27b_llama.csv` e `calibracao_27b.csv` (vereditos iguais aos de antes; só mudaram os tempos). Todos os 231 julgamentos são válidos, com média de 59 s cada.
- **Calibração:** o veredito do modelo acerta 7 de 9 e detecta 1 das 3 reprovadas; a regra fixa acerta 8 de 9 e detecta as 3. Vale a regra.
- **Qwen × Llama (veredito pela regra, 111 respostas cada):**

  | | Qwen3 8B | Llama 3.1 8B |
  |---|---|---|
  | Reprovadas pela regra | 44 | 66 |
  | Reprovadas pelo veredito do modelo | 4 | 4 |
  | Fidelidade (0 a 2) | 1,80 | 1,68 |
  | Correção | 1,71 | 1,46 |
  | Comportamento | 1,77 | 1,76 |
  | Clareza | 1,93 | 1,80 |

  O Qwen fica como gerador principal.
- **Guardrails × juiz:** os guardrails aprovaram as 111 respostas do Qwen, mas a regra do juiz reprova 44. Essas 44 são as primeiras a revisar à mão e podem compor a validação com 20 a 30 respostas rotuladas por pessoa.
- **Importar sem os pedidos locais:** quando `output/kaggle/juiz_27b*/dataset/` não existe na máquina, baixe os pedidos do dataset privado (`lexia-juiz-27b-pedidos` ou `lexia-juiz-27b-llama-pedidos`) para essa pasta e as saídas do kernel para `resultados/`. Depois rode o `importar_juiz_kaggle.py --sem-download --27b`, com `--llama` para o Llama.
- **Token do Kaggle no Windows:** o arquivo `~/.kaggle/access_token` precisa ficar sem extensão; o Bloco de Notas salva como `.txt`.

## Atualização de 2026-11-17 (tarde, no Mac)

- **Geração concluída no Kaggle:** 111 de 111 respostas válidas (Qwen3 8B, média de 36,8 s). Os guardrails não bloquearam nenhuma; 79 deixam a maioria das frases jurídicas sem `[Fonte N]`. Notebook `notebooks/03_integracao/03_geracao.ipynb`.
- **Guardrail corrigido:** `sem_fontes` reprovava as respostas fixas de recusa; agora vale só para ações com busca. A concordância com a revisora continua 9 de 9.
- **Fallback (LLM B = Llama 3.1 8B):** `geracao.gerar_com_fallback` (tempo real) e `escolher_resposta` (lote). Gatilhos: falha técnica ou guardrail bloqueante; se a B falhar, resposta segura. Não foi acionado nesta rodada. O Llama gerou as mesmas 111 respostas para comparação: todas válidas, 22,8 s em média, mas cita menos as fontes (2,3 × 3,6 citações por resposta).
- **Juiz:** o Gemma 3 12B foi descartado (aprovou as 3 respostas que a revisora reprovou). O **Gemma 3 27B** (2 GPUs T4) com a regra fixa `juiz.veredito_regra` acertou 8 de 9 e detectou as 3 reprovadas, mas parte das notas contradiz a justificativa. Adotado com cautela; falta validar com 20–30 respostas novas rotuladas por pessoa.
- **Sem a pasta `avaliacao_09`** nesta máquina: as referências da curadoria vêm de `data/evaluation/legislacao/perguntas_consolidadas_pre09.csv` (cópia de um backup antigo, fora do Git; só as FAQ têm resposta).
- **Mac:** `.venv` com Python 3.14, token do Kaggle em `~/.kaggle/access_token`. O executor de notebooks agora aceita o estado gravado com caminhos do Windows.

## O que está pronto

| Etapa | Onde | Situação |
|---|---|---|
| Recuperação conjunta | `notebooks/03_integracao/01_recuperacao_conjunta.ipynb`, `src/integracao/recuperacao.py` | concluída |
| Guardrails de entrada e saída | `notebooks/03_integracao/02_guardrails.ipynb`, `src/integracao/guardrails.py` | concluída |
| Geração estruturada (Qwen3 8B) | `src/integracao/geracao.py`, `scripts/*geracao*`, `notebooks/03_integracao/03_geracao.ipynb` | integração v2 em validação; saídas em `geracao_v2` |
| Juiz (Gemma 3 27B) | `src/integracao/juiz.py`, `scripts/*juiz*`, `reports/integracao/juiz/*_27b*.csv` | validado com advogado revisor (25 respostas): concorda em 10 de 25, brando diante do especialista; faltam critérios novos detectáveis por regra |
| Avaliação e diagnóstico (notebook 04) | `notebooks/03_integracao/04_avaliacao.ipynb`, `scripts/criar_notebook_integracao_04.py`, `scripts/importar_revisao_juiz.py` | concluída com juiz 27B, validação com especialista e prioridades de correção |
| Correções (notebook 06) | `notebooks/03_integracao/06_correcoes.ipynb`, `src/integracao/prompt_juridico.py` (v3, regras 16 a 24), `src/integracao/guardrails.py` (validador v3) | concluída a medição de v3 e v3.1 no validador. Faltam o juiz 27B (feito pela usuária) e os critérios novos do juiz |
| Legislação versionada (EC 141/2026) | `VERSOES_LEGISLACAO` em `src/integracao/recuperacao.py`, `scripts/atualizar_legislacao_*.py` | concluída: versão `ec141_2026_notas` é o padrão da busca, e a `original` está preservada |
| Base de precedentes do TST | `notebooks/05_docs_precedentes/`, `src/precedentes/`, schema `lex_precedentes` | notebooks 00 a 06 prontos; versão `bdf048e6…` validada e avaliada (gabarito A: 5 de 7 em 1º; gabarito B: Hit@3 0,53). Falta a integração como terceira fonte. Os notebooks não estão commitados |
| Comparação RAG × LLM (notebook 05) | `notebooks/03_integracao/05_comparacao_rag_llm.ipynb`, `scripts/comparacao_rag_basico.py`, `reports/integracao/comparacao/` | concluída com 5 configurações; falta repetir básico + decisões × híbrido em mais perguntas |
| Sistema multiagentes | `src/multiagentes/`, `notebooks/04_multiagentes/` | implementação e testes recebidos da branch remota |
| Buscador local | `src/multiagentes/buscador_local.py`, `scripts/consultar_buscador_local.py` | busca local implementada; avaliação jurídica não substituída |

## Resultados e decisões

### Recuperação

- **Configuração padrão** (`Configuracao()`):
  - busca semântica com BGE-M3 e busca lexical com pesos IDF, fundidas por RRF (k=60);
  - 10 candidatos por fonte e reranker `bge-reranker-v2-m3` com 256 tokens;
  - entrega com cotas: 3 artigos de legislação e 3 decisões.
- **Legislação** (16 perguntas): Hit@3 = 1,00, MRR = 0,93.
- **Jurisprudência** (17 perguntas): Hit@10 = 0,29, MRR = 0,13.
  - O gabarito é estreito; falta julgar a pertinência das decisões, o que o juiz vai fazer.
  - Ponto a investigar: sem reranker, a jurisprudência teve MRR = 0,21.
- **Tempo:** 15 a 21 s por pergunta na CPU.
- **Notebook 05:** nas 33 perguntas JUS da curadoria com artigo de referência, a busca só semântica empata com a híbrida na legislação (Hit@3 = 0,58; MRR@3 = 0,48 × 0,49), e a resposta final também fica praticamente igual quando as duas entregam 3 artigos + 3 decisões. Os conjuntos e os gabaritos são diferentes dos 16 acima, por isso os Hit@3 não se contradizem.

### Guardrails

- **Classificação de entrada** (100 perguntas da curadoria):

  | Conjunto | Acurácia | Acerto em "segue para a busca ou não" |
  |---|---|---|
  | Ajuste | 0,80 | 0,96 |
  | Teste | 0,75 | 0,84 |

  - Fraquezas no teste: `institucional` acerta 0,45 e `orientar_sem_aconselhar` acerta 0,33.
- **Outros casos de entrada:** 4 de 4 perguntas negativas e 20 de 20 casos sintéticos corretos.
- **Saída:** concordância de 9 de 9 com a revisora. Essas 9 respostas foram usadas na calibração.
- **Regras acrescentadas depois do teste com o 8B:**
  - `consulta_individual_pede_dados`, que bloqueia a resposta;
  - `artigo_sem_fonte`, que só alerta.
- Números de processo das decisões entregues como fonte não são mascarados.

### Geração

- **Modelo:** `qwen3:8b-q8_0` no Ollama 0.40.16, na GPU T4 do Kaggle, sem modo de raciocínio.
- **Opções:** temperatura 0, semente 42, `num_ctx` de 16384 tokens (o maior prompt tem cerca de 10 mil).
- **Volume:** 137 perguntas da base.
  - 111 vão para a LLM: 99 `responder` e 12 `orientar_sem_aconselhar`.
  - 26 recebem resposta fixa, sem LLM: institucional, consulta individual, fora do escopo e outra jurisdição.
- **Prompt de sistema:** `SYSTEM_PROMPT_LEGAL` do grupo, sem alteração (`src/integracao/prompt_juridico.py`).

### Juiz e Avaliação Final

- **Modelo:** Gemma 3 27B no Kaggle, dividido entre as 2 GPUs T4. É gratuito e de outra família que o gerador. O 12B foi descartado. O veredito vale pela regra fixa `juiz.veredito_regra`.
- **Calibração:** antes de valer, o juiz é comparado com as 9 decisões da revisora, sem ver essas decisões.
- **Referências:** resposta-ouro da curadoria, ou pontos esperados e limites dos conjuntos aprovados.
- **Alternativa paga:** a classe `Juiz` chama a DeepSeek pela API, com a variável de ambiente `DEEPSEEK_API_KEY`.
- **Histórico:** os resultados do Gemma 3 12B e das 111 respostas são registros da execução anterior; não devem ser tratados como validação do novo formato estruturado v2.

## Comandos executados

1. Geração importada e validada via `scripts/importar_geracao_kaggle.py`.
2. Julgamento importado e cruzado via `scripts/importar_juiz_kaggle.py`.
3. Notebooks 03 e 04 gerados e executados via `scripts/executar_notebook_integracao.py`.

Como o contrato mudou, esses resultados históricos não validam a saída estruturada v2. Antes de concluir uma nova avaliação, executar novamente os fluxos v2 e revisar manualmente respostas amostradas; não enviar dados sensíveis para repositórios públicos.

Use caminhos absolutos no `kaggle datasets create` e no `kaggle kernels push`. Com caminho relativo, o upload falha no Windows. No Git Bash, o caminho com barras normais (`C:/...`) também falha; rode pelo PowerShell com o caminho do Windows (`(Resolve-Path ...).Path`).

## Atualização do fluxo de geração (v2)

O fluxo agora prepara novas execuções em `output/kaggle/geracao_v2/` e `output/kaggle/juiz_v2/`. Os dados antigos em `output/kaggle/geracao/` e `output/kaggle/juiz/` não são sobrescritos. Os datasets e kernels Kaggle usam sufixo `-v2`.

- **Stracting:** `src/integracao/stracting.py` extrai fatos explicitamente mencionados e classifica a intenção (`CALCULO`, `PRESCRICAO`, `TRIAGEM` ou `CONSULTA_JURIDICA`). A classificação é determinística, não executa cálculos e não substitui os guardrails. Fatos ambíguos ou ausentes não são completados.
- **Saída estruturada:** os pedidos para o modelo de geração solicitam JSON Schema com `resposta_direta`, `fundamentacao` e `ressalvas`. A importação valida chaves e tipos antes de renderizar o texto para os guardrails de saída.
- **Janela de contexto:** `src/integracao/context_window.py` estima tokens com `cl100k_base`, aplica margem de 25% e reserva 1.200 tokens para geração (2.500 para o juiz) e 512 para segurança dentro do `num_ctx` de 16.384. A estimativa não é o tokenizer exato do Qwen/Gemma. Se o limite estimado for excedido, o pedido não é truncado nem enviado; fica marcado como erro de contexto. O fluxo atual é de uma pergunta por pedido, sem histórico de conversa para janela deslizante.
- **Observabilidade:** preparação, inferência e validação registram duração, contagem de tokens, tentativas, status e tipo de erro. Os registros usam hash do identificador da pergunta e não incluem pergunta, prompt, fontes ou resposta.
- **Prompt caching:** não foi adicionado cache de respostas do agente. O cache existente de julgamentos idênticos do juiz foi mantido.
- **Escopo deliberado:** tool calling e cálculos automáticos do agente não foram migrados. Perguntas identificadas como cálculo recebem instrução para não estimar valores individualizados e para explicitar fatos faltantes.

Como o contrato mudou, os resultados antigos em texto livre não servem como validação do novo schema. Para uma nova execução, use `scripts/preparar_geracao_kaggle.py`, o kernel configurado em `output/kaggle/geracao_v2/kernel/`, e depois `scripts/importar_geracao_kaggle.py`. A avaliação atualizada do juiz usa os artefatos v2 correspondentes.

## Para retomar em outra máquina

Os itens abaixo não estão no GitHub e precisam ser recriados ou copiados.

- **PostgreSQL com pgvector (Docker):**
  - contêiner `lex-clt-postgres-1`, porta 15432, credenciais em `.env.pgvector.local`;
  - recriar o banco com os notebooks de indexação (legislação e jurisprudência 06), ou exportar o volume do Docker;
  - criar as visões lexicais com `Recuperador.preparar_lexico()`;
  - legislação com a EC 141: rodar `scripts/atualizar_legislacao_ec141.py` e depois `scripts/atualizar_legislacao_notas_ec141.py`. Os dois são idempotentes e recriam as mesmas versões;
  - base de precedentes: executar os notebooks 03, 04 e 05 de `notebooks/05_docs_precedentes/`. O 05 recria o schema `lex_precedentes` e o índice de palavras.
- **PDFs dos precedentes** em `data/raw/precedentes/`, fora do Git. São 10 arquivos, e o hash de cada um está no inventário da auditoria.
- **Gerações v3 e v3.1:** pedidos e respostas em `output/kaggle/geracao_v3/` e `output/kaggle/geracao_v3_1/`, fora do Git. Datasets privados `lexia-geracao-v3-pedidos` e `lexia-geracao-v3-1-pedidos`; kernels `lexia-geracao-qwen3-v3` e `lexia-geracao-qwen3-v3-1`.
- **Modelos do Hugging Face** em cache local: `BAAI/bge-m3` (revisão `5617a9f`) e `BAAI/bge-reranker-v2-m3`.
- **Token do Kaggle** em `~/.kaggle`.
- **Pedidos e respostas antigos** em `output/kaggle/geracao/` e `output/kaggle/juiz/`; novos artefatos estruturados ficam em `output/kaggle/geracao_v2/` e `output/kaggle/juiz_v2/`. Todos estão fora do Git porque podem conter trechos de decisões e perguntas protegidas.
  - Os pedidos novos são destinados aos datasets privados `laisapaiva93/lexia-geracao-pedidos-v2` e `laisapaiva93/lexia-juiz-pedidos-v2`.
- **Revisão do advogado:** página e JSON exportado em `output/integracao/revisao_juiz/` (fora do Git, com as observações e o nome do revisor). Sem o JSON, o notebook 04 continua executável pelos resumos em `reports/integracao/juiz/`.
- **Comparação do notebook 05:** pedidos e respostas em `output/kaggle/comparacao/` (fora do Git). Datasets privados `lexia-comparacao-{isolado,juiz,rag-basico,juiz-basico,rag-basico-jur,juiz-basico-jur}-pedidos`; o `importar` baixa as saídas dos kernels de mesmo nome.
- **Histórico da branch remota:** datasets privados antigos `lexia-geracao-pedidos`, `lexia-juiz-27b-pedidos` e `lexia-juiz-27b-llama-pedidos`; novos datasets usam nomes com sufixo `-v2`.
- **Regra do repositório:** commits sem a linha de atribuição do Claude.
