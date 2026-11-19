# Relatório atualizado do estado do projeto

**Data de referência:** 19/11/2026
**Repositório:** `lex_clt.ai`
**Branch local:** `main`

## Resumo executivo

O projeto está em fase de pesquisa e validação técnica, organizado em três frentes: preparação da base de legislação, preparação da base de jurisprudência e integração de recuperação, guardrails, geração e avaliação. Há código reutilizável em `src/`, 16 notebooks, relatórios experimentais e testes automatizados.

A recuperação e o fluxo integrado já têm resultados documentados. O fluxo também conta com extração/roteamento determinístico, saída estruturada validada, limite de contexto fail-closed e observabilidade minimizada. A avaliação registrada aponta oportunidades de melhoria, especialmente na relevância da recuperação de jurisprudência, no comportamento de alguns guardrails e no suporte factual das respostas. Ainda não há uma aplicação de usuário com API e interface no repositório; esses itens permanecem no escopo planejado.

O estado foi conferido no código e no Git em 19/11/2026. Os resultados de modelos e métricas abaixo são os documentados nos artefatos do projeto, não uma nova execução dos experimentos.

## Estado do Git

- `main` estava limpa antes desta rodada de implementação e continua dois commits à frente de `origin/main`; há alterações locais em andamento.
- Os dois commits locais são:
  - `ea502b9` — estrutura inicial para jurisprudência;
  - `5de7a4c` — notebooks de geração e avaliação integradas, com relatórios e gráficos.
- A implementação de agentes não faz parte da árvore de arquivos da `main` ativa.
- A implementação de agente foi removida do estado atual da branch remota `challenge3/main` pelo commit `bedaf12` (84 arquivos removidos da árvore atual). O histórico anterior foi preservado; os commits antigos ainda contêm esses arquivos quando consultados pelo histórico.

## Progresso por frente

| Frente | Situação observada |
|---|---|
| Legislação | Pipeline de preparação e recuperação implementado, com dados estruturados, chunks, conjunto de avaliação, relatórios e persistência pgvector documentados. |
| Jurisprudência | Seis notebooks cobrem auditoria, EDA, estruturação, chunking, preparação do recorte e embeddings/indexação. Há código reutilizável em `src/jurisprudencia/`; os dados brutos não são versionados. |
| Integração | Quatro notebooks e módulos em `src/integracao/` cobrem recuperação conjunta, guardrails, geração e avaliação por juiz. Agora inclui Stracting determinístico, JSON Schema validado, orçamento de contexto e observabilidade sem prompts/respostas. Resultados e limitações estão registrados em `docs/estado_integracao.md`. |
| Aplicação de usuário | API, interface, ingestão de documentos de usuários e OCR aparecem como escopo planejado no README, mas não estão presentes como componentes implementados na raiz atual. |
| Testes | 119 testes passaram na execução local da suíte documentada após a migração de capacidades. |

### Legislação

- O repositório contém seis notebooks em `notebooks/01_legislacao/`.
- A documentação descreve 5.284 artigos estruturados e duas representações de chunks: artigo completo para contexto e parágrafo para busca.
- A recuperação usa embeddings BGE-M3, busca lexical, fusão de resultados e reranking; a configuração e os resultados estão registrados nos relatórios de legislação.
- A antiga integração exclusiva de legislação foi retirada do fluxo ativo para ser refeita junto com jurisprudência. A tag `rag-legislacao-v1` preserva a versão anterior.
- As condições de reutilização da fonte de dados ainda precisam ser confirmadas, conforme `data/README.md`.

### Jurisprudência

- Há seis notebooks em `notebooks/02_jurisprudencia/` e módulos de preparação em `src/jurisprudencia/`.
- O README documenta uma base reduzida de 179.812 registros, com dados do TST, de três TRTs e do STF em recorte trabalhista.
- A documentação do pipeline registra um recorte de indexação de 20.000 documentos, com 303.257 chunks e embeddings BGE-M3.
- A base bruta e os dados processados são externos ou ignorados pelo Git. O diretório de avaliação versionado existe, mas ainda não contém um conjunto aprovado de jurisprudência.
- A origem, a licença, a política de atualização e o conjunto de avaliação revisado continuam sendo pontos importantes a fechar.

### Integração e avaliação

O documento de estado da integração, atualizado em 17/11/2026, registra:

- Recuperação híbrida de legislação e jurisprudência com fusão RRF e reranker.
- Guardrails de entrada e saída, incluindo bloqueio de consultas individuais e alertas de citação sem fonte.
- Geração de 111 respostas com Qwen3 8B no Kaggle; outras 26 perguntas receberam respostas fixas dos guardrails.
- Avaliação das 111 respostas por Gemma 3 12B: 78 aprovadas (70,3%) e 33 reprovadas.
- 80,5% das afirmações avaliadas foram consideradas apoiadas pelas fontes; 19,5% não tiveram apoio direto.
- 93,0% das 201 decisões apresentadas foram julgadas pertinentes pelo juiz.
- Na avaliação da recuperação, a legislação teve Hit@3 de 1,00 e MRR de 0,93. Para jurisprudência, o registro aponta Hit@10 de 0,29 e MRR de 0,13; a pertinência do gabarito é uma limitação reconhecida.
- Os testes dos guardrails mostram desempenho mais fraco em algumas classes, incluindo “institucional” e “orientar_sem_aconselhar”.

Esses números são resultados experimentais documentados, não garantias de qualidade jurídica nem métricas reproduzidas nesta atualização.

### Capacidades migradas para o fluxo ativo

- **Stracting:** extrai fatos explícitos e classifica a intenção; os guardrails continuam decidindo o encaminhamento e não há cálculo automático.
- **Structured output:** geração pede JSON conforme schema e a importação valida o objeto antes de convertê-lo em texto para os guardrails.
- **Janela de contexto:** usa estimativa `cl100k_base` com 25% de margem, reserva para saída e limite; não trunca evidências e rejeita pedidos acima do orçamento.
- **Observabilidade:** registra métricas e status por etapa sem salvar pergunta, prompt, evidências ou resposta nos traces; IDs de pergunta são hasheados.
- **Cache:** não foi migrado o cache de respostas do agente; o cache de avaliações repetidas do juiz permanece.
- **Compatibilidade:** novos pacotes de geração e avaliação usam pastas/datasets/kernel `v2`, preservando resultados antigos. É necessária uma nova execução Kaggle para validar o formato estruturado; os testes unitários não substituem essa execução.

## Verificação executada nesta atualização

Foi executado:

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```

**Resultado:** 119 testes executados, todos aprovados.

O comando `pytest` não está instalado no ambiente virtual local. O runner `unittest` usado acima foi suficiente para executar a suíte existente.

## Riscos e pendências prioritárias

1. **Atualizar a documentação de entrada:** o README ainda apresenta componentes já experimentados como “planejados”, e `docs/estrutura_do_projeto.md` contém descrições antigas de pastas e etapas.
2. **Consolidar a qualidade da integração:** investigar os erros nas respostas reprovadas, o suporte insuficiente de parte das afirmações e o desempenho mais baixo de classes específicas dos guardrails.
3. **Melhorar e revisar a avaliação de jurisprudência:** ampliar e validar referências de ouro com revisão humana; o resultado atual da recuperação não deve ser interpretado sem essa ressalva.
4. **Resolver governança de dados:** confirmar licença e condições de uso das fontes, documentar proveniência e política de atualização de jurisprudência.
5. **Reprodutibilidade:** parte dos dados, credenciais, modelos, banco pgvector e execuções do Kaggle depende de configuração externa ou recursos privados; uma execução limpa em outra máquina exige acesso e preparação adicionais.
6. **Validar v2 em modelo real:** executar os novos kernels Kaggle, medir a taxa de JSON válido e comparar respostas/guardrails com a versão anterior.
7. **Definir o próximo escopo de produto:** API, interface, OCR e fluxo seguro para documentos de usuários ainda precisam de implementação e avaliação antes de qualquer uso como aplicação.
8. **Limite de contexto:** a contagem cl100k é uma estimativa, não o tokenizer do Qwen/Gemma. Os contadores observados do Ollama precisam ser comparados com a estimativa numa execução real.
9. **Branch de agentes:** a árvore atual de `challenge3/main` já não contém a implementação; os commits históricos anteriores continuam disponíveis.

## Referências internas

- [README.md](../README.md) — visão geral e instruções para a base de jurisprudência.
- [docs/estado_integracao.md](./estado_integracao.md) — resultados e decisões do fluxo integrado.
- [docs/jurisprudencia_planejamento.md](./jurisprudencia_planejamento.md) — decisões em aberto para a base de jurisprudência.
- [docs/estrutura_do_projeto.md](./estrutura_do_projeto.md) — mapa do repositório, com trechos que precisam de atualização.
- [data/README.md](../data/README.md) — fonte registrada e pendência de licença.
