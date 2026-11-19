# Estado da integração (03_integracao)

Este é o documento de passagem para retomar o trabalho em outra sessão ou máquina. Atualizado em 2026-11-19.

## O que está pronto

| Etapa | Onde | Situação |
|---|---|---|
| Recuperação conjunta | `notebooks/03_integracao/01_recuperacao_conjunta.ipynb`, `src/integracao/recuperacao.py` | concluída |
| Guardrails de entrada e saída | `notebooks/03_integracao/02_guardrails.ipynb`, `src/integracao/guardrails.py` | concluída |
| Geração (Qwen3 8B no Kaggle) | `notebooks/03_integracao/03_geracao.ipynb`, `src/integracao/geracao.py` | concluída |
| Juiz (Gemma 3 12B no Kaggle) | `notebooks/03_integracao/04_avaliacao.ipynb`, `src/integracao/juiz.py` | concluída |
| Notebooks 03 (geração) e 04 (avaliação) | `notebooks/03_integracao/` | concluídos |

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

- **Modelo:** Gemma 3 12B no Kaggle (Ollama 0.40.16, GPU T4).
- **Calibração:** 6 de 9 concordâncias com a revisora humana nas perguntas de calibração cega.
- **Resultado das 111 respostas geradas:**
  - 70,3% aprovadas (78 de 111), 29,7% reprovadas (33 de 111).
  - Notas médias (0 a 2): Clareza 2,00, Fidelidade 1,56, Comportamento 1,21, Correção 1,14.
  - Alucinações: 80,5% das afirmações apoiadas nas fontes; 19,5% sem apoio direto.
  - **Pertinência da jurisprudência:** 93,0% das 201 decisões entregues foram julgadas pertinentes pelo juiz.
- **Notebooks concluídos:**
  - `notebooks/03_integracao/03_geracao.ipynb`
  - `notebooks/03_integracao/04_avaliacao.ipynb`

## Comandos executados

1. Geração importada e validada via `scripts/importar_geracao_kaggle.py`.
2. Julgamento importado e cruzado via `scripts/importar_juiz_kaggle.py`.
3. Notebooks 03 e 04 gerados e executados via `scripts/executar_notebook_integracao.py`.

Use caminhos absolutos no `kaggle datasets create` e no `kaggle kernels push`. Com caminho relativo, o upload falha no Windows.

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
  - criar as visões lexicais com `Recuperador.preparar_lexico()`.
- **Modelos do Hugging Face** em cache local: `BAAI/bge-m3` (revisão `5617a9f`) e `BAAI/bge-reranker-v2-m3`.
- **Token do Kaggle** em `~/.kaggle`.
- **Pedidos e respostas antigos** em `output/kaggle/geracao/` e `output/kaggle/juiz/`; novos artefatos estruturados ficam em `output/kaggle/geracao_v2/` e `output/kaggle/juiz_v2/`. Todos estão fora do Git porque podem conter trechos de decisões e perguntas protegidas.
  - Os pedidos novos são destinados aos datasets privados `laisapaiva93/lexia-geracao-pedidos-v2` e `laisapaiva93/lexia-juiz-pedidos-v2`.
- **Regra do repositório:** commits sem a linha de atribuição do Claude.
