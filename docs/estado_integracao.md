# Estado da integração (03_integracao)

Este é o documento de passagem para retomar o trabalho em outra sessão ou máquina. Atualizado em 2026-11-19.

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
| Geração (Qwen3 8B no Kaggle) | `src/integracao/geracao.py`, `scripts/*geracao*`, `scripts/kaggle_gerar_respostas.py`, `notebooks/03_integracao/03_geracao.ipynb` | concluída |
| Juiz (Gemma 3 27B no Kaggle) | `src/integracao/juiz.py`, `scripts/*juiz*`, `reports/integracao/juiz/*_27b*.csv` | concluído e importado; falta validar com rótulos humanos |
| Notebook 04 (avaliação) | — | a fazer |

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

### Juiz

- **Modelo:** Gemma 3 27B no Kaggle, dividido entre as 2 GPUs T4. É gratuito e de outra família que o gerador. O 12B foi descartado. O veredito vale pela regra fixa `juiz.veredito_regra`.
- **Calibração:** antes de valer, o juiz é comparado com as 9 decisões da revisora, sem ver essas decisões.
- **Referências:** resposta-ouro da curadoria, ou pontos esperados e limites dos conjuntos aprovados.
- **Alternativa paga:** a classe `Juiz` chama a DeepSeek pela API, com a variável de ambiente `DEEPSEEK_API_KEY`.

## Próximos comandos

A geração e o juiz já foram executados e importados. Os próximos passos são:

1. Revisar à mão as 44 respostas do Qwen reprovadas pela regra do juiz (`reports/integracao/juiz/julgamentos_27b.csv`, coluna `veredito_regra`) e rotular de 20 a 30 respostas para validar o juiz.
2. Criar o notebook `04_avaliacao` a partir de `reports/integracao/geracao/` e `reports/integracao/juiz/`.

Para rodar o juiz 27B de novo:

```powershell
.venv\Scripts\python.exe scripts\preparar_juiz_kaggle.py --27b          # --27b --llama para as respostas do Llama
kaggle datasets create -p (Resolve-Path output\kaggle\juiz_27b\dataset).Path
kaggle kernels push -p (Resolve-Path output\kaggle\juiz_27b\kernel).Path
# Quando terminar (kaggle kernels status laisapaiva93/lexia-juiz-gemma3-27b):
.venv\Scripts\python.exe scripts\importar_juiz_kaggle.py --27b
```

Use caminhos absolutos no `kaggle datasets create` e no `kaggle kernels push`. Com caminho relativo, o upload falha no Windows.

## Para retomar em outra máquina

Os itens abaixo não estão no GitHub e precisam ser recriados ou copiados.

- **PostgreSQL com pgvector (Docker):**
  - contêiner `lex-clt-postgres-1`, porta 15432, credenciais em `.env.pgvector.local`;
  - recriar o banco com os notebooks de indexação (legislação e jurisprudência 06), ou exportar o volume do Docker;
  - criar as visões lexicais com `Recuperador.preparar_lexico()`.
- **Modelos do Hugging Face** em cache local: `BAAI/bge-m3` (revisão `5617a9f`) e `BAAI/bge-reranker-v2-m3`.
- **Token do Kaggle** em `~/.kaggle`.
- **Pedidos e respostas** em `output/kaggle/geracao/` e `output/kaggle/juiz/`. Estão fora do Git porque contêm trechos de decisões e perguntas protegidas.
  - Os pedidos também estão nos datasets privados `laisapaiva93/lexia-geracao-pedidos`, `lexia-juiz-27b-pedidos` e `lexia-juiz-27b-llama-pedidos`.
- **Regra do repositório:** commits sem a linha de atribuição do Claude.
