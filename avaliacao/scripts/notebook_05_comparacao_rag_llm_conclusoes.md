## 7. Conclusões

Resultados das 40 perguntas JUS com busca, julgadas pelo Gemma 3 27B (200 julgamentos válidos).

| | RAG isolado | LLM isolado | RAG + LLM básico | RAG + LLM básico + decisões | RAG + LLM híbrido |
|---|---|---|---|---|---|
| Hit@3 (artigos de lei) | 0,58 | — | 0,58 | 0,58 | 0,58 |
| Correção jurídica (0–2) | 1,23 | 1,00 | 1,62 | 1,75 | **1,78** |
| Fidelidade (0–2) | 1,82 | 0,95 | 1,55 | 1,75 | 1,78 |
| Aderência (0–2) | 1,75 | 1,48 | 1,65 | **1,80** | 1,68 |
| Afirmações apoiadas (média por resposta) | 91% | 37% | 72% | 81% | 83% |
| Afirmações sem apoio (média por resposta) | 9% | 53% | 22% | 14% | 14% |
| Cita o artigo de referência | — | 19% | 52% | **68%** | 61% |
| Decisões pertinentes | — | — | — | 85% | 85% |
| Aprovadas pela regra | 10 | 4 | 16 | **18** | 17 |
| Latência (s) | 16 | 20 | 34 | **41** | 58 |

1. **RAG vale a pena.** Sem fontes, o Qwen3 8B acerta metade do que deveria (correção 1,00) e mais da metade das afirmações não tem apoio. Com qualquer RAG, a correção sobe para 1,6–1,8 e a alucinação cai para menos da metade. A segurança fica em 100% em todas as configurações: os guardrails não dependem da busca.
2. **A busca sozinha é fiel, mas não responde.** O texto dos artigos é a própria fonte (91% apoiado), mas a correção fica em 1,23: os artigos nem sempre respondem ao que foi perguntado, e sem redação a pessoa recebe lei crua. O LLM é o que transforma a fonte em resposta.
3. **O ganho do RAG híbrido sobre o básico vem das decisões, não do algoritmo de busca.** Entregar 3 decisões (e 3 artigos em vez de 5) leva o básico de 1,62 para 1,75 de correção (melhor em 9 perguntas, pior em 4) e de 22% para 14% de afirmações sem apoio. Com a mesma entrega, a busca híbrida (lexical + RRF + reranker) e a semântica pura ficam praticamente iguais: correção 1,78 × 1,75 (6 perguntas melhores, 5 piores), mesmas afirmações sem apoio, mesmas decisões pertinentes (85%) e 17 × 18 aprovadas.
4. **Na legislação, as três buscas empatam** pelo gabarito da curadoria (Hit@3 = 0,58; MRR@3 = 0,48–0,49). A busca semântica pura leva 0,2 s (0,85 s com decisões); a híbrida, 16 s na CPU, quase todo o tempo no reranker.
5. **O validador reprova todas as configurações com RAG nos mesmos 2 critérios**: Hit@3 abaixo de 0,70 e afirmações sem apoio acima de 10%. Das 23 reprovadas do híbrido, a falha está mais na geração (14) e no comportamento (12) do que na busca (7).

**Implicação.** Nesta amostra, o RAG básico + decisões entrega a mesma qualidade do híbrido com 29% menos latência total (41 s × 58 s) e uma busca cerca de 19 vezes mais rápida. A busca lexical e o reranker não se pagam neste conjunto. Antes de simplificar a arquitetura, vale confirmar em mais perguntas: 40 respostas e um único juiz não separam diferenças pequenas (6 × 5 perguntas).

**Próximos passos sugeridos.**

- Repetir a comparação básico + decisões × híbrido num conjunto maior (as 111 perguntas da geração) antes de decidir pela busca mais simples.
- Investigar o reranker na jurisprudência: com 256 tokens por par, ele lê só metade da janela de 500 tokens (o notebook 01 da integração já registrava MRR melhor sem reranker).
- Atacar as afirmações sem apoio na geração (prompt ou guardrail que exija `[Fonte N]` por afirmação) e o comportamento em `orientar_sem_aconselhar`.
- Revisar o gabarito de artigos da curadoria (7 perguntas sem artigo de referência e referências marcadas como pendentes) antes de usar o Hit@3 como critério de corte.
- Validar o juiz com rótulos humanos (20–30 respostas): ele aprova pelo próprio veredito 29 das 40 respostas do LLM isolado, contra 4 pela regra fixa.
