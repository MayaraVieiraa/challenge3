# Demonstração dos agentes no Kaggle

Registro atualizado em **19/11/2026**. As execuções usam LangGraph, Qwen3 8B como Analista e Gemma 3 12B como Validador. O atendimento utiliza um corpus portátil de 26 artigos da CLT sobre férias, com busca lexical. Não utiliza o índice completo de jurisprudência.

## Primeira execução completa — versão 6

O notebook privado concluiu a inferência em 17/11/2026. Os resultados foram baixados e seus hashes conferidos na retomada de 19/11.

| Medida | Observado |
|---|---|
| Pergunta | Quais são as regras gerais sobre férias segundo as fontes fornecidas? |
| Ambiente | Python 3.13.16, LangGraph 1.2.22, Ollama 0.40.16 |
| GPU | Duas Tesla T4, 15.360 MiB por dispositivo |
| Modelos | `qwen3:8b-q8_0` e `gemma3:12b` |
| Chamadas LLM | 5 |
| Revisões semânticas | 1 |
| Tentativas técnicas adicionais | 0 |
| Duração do atendimento | 327,927 segundos, sem incluir instalação e downloads |
| Resultado | `limitada`, motivo `revisao_esgotada` |
| Falha inserida deliberadamente | Não |

A colaboração foi registrada integralmente:

```text
Analista: consulta → ferramenta: busca → Analista: rascunho
→ Validador: revisar → Analista: revisão → Validador: revisar
→ orquestrador: bloquear a resposta e apresentar a limitação
```

O Analista recebeu o feedback e alterou o texto. Como a segunda versão ainda foi reprovada, o sistema não apresentou o candidato jurídico como resposta final.

### Problemas observados e correções

1. **Seleção das fontes:** os escores lexicais da pergunta genérica empataram. O desempate pelo identificador hash trouxe os artigos 133, 144 e 140 antes da introdução ao tema. A busca passou a desempatar pela norma e ordem natural dos artigos, mantendo a relevância como primeiro critério e sem acrescentar um peso específico para férias.
2. **Citações após o ponto final:** o segmentador separava a frase de sua citação, gerando o alerta incorreto de quatro afirmações sem fonte. A correção associa citações pospostas à frase anterior, respeitando a fronteira de parágrafos.
3. **Política do Validador:** o modelo pediu a remoção do aviso informativo acrescentado pelo próprio sistema. A política agora explica que esse aviso é obrigatório e não representa uma afirmação jurídica a fundamentar. Um pedido explícito para remover o aviso integral é recusado como conflito de contrato.

As correções foram acompanhadas de testes de regressão. O registro original da versão 6 permanece intacto; alterações posteriores não substituem suas respostas, avaliações ou métricas.

Essa pergunta foi utilizada no desenvolvimento das correções. Uma nova execução da mesma pergunta é uma comparação de desenvolvimento, não uma avaliação independente da qualidade jurídica.

## Nova rodada após as correções

O pacote atualizado, com `VERSAO_PROMPTS=multiagentes-v2`, foi executado na **versão 7** do mesmo notebook privado em **19/11/2026**. O Kaggle concluiu a sessão e os artefatos foram baixados e conferidos.

| Medida | Versão 6 | Versão 7 |
|---|---|---|
| Resultado | `limitada` | `aprovada` |
| Motivo | `revisao_esgotada` | `controles_aprovados` |
| Chamadas LLM | 5 | 3 |
| Revisões | 1 | 0 |
| Tentativas técnicas | 0 | 0 |
| Duração do atendimento | 327,927 s | 260,712 s |
| Artigos entregues | 133, 144 e 140 | 129, 130, 130-A e 132 |

A pergunta, a consulta produzida pelo Analista e o corpus permaneceram iguais. O novo desempate trouxe os artigos introdutórios ao contexto. O Analista identificou a marca de revogação presente no texto do artigo 130-A e preservou o aviso informativo obrigatório. O Validador aprovou o candidato sem problemas; os guardrails também o aprovaram.

O aviso foi acrescentado pelos controles e submetido ao Validador como parte do candidato. A resposta final salva é exatamente esse candidato aprovado. Foram conferidos os hashes dos artefatos, o hash do snapshot das fontes e a correspondência entre os três eventos de chamada LLM e o contador final.

O fluxo da rodada aprovada foi:

```text
Analista: consulta → ferramenta: quatro fontes completas
→ Analista: resposta → guardrails: candidato
→ Validador: aprovar → orquestrador: liberar a resposta
```

O registro completo é `kaggle-corpus-20261119-114147-f369a1`. O atendimento durou aproximadamente **4 minutos e 21 segundos**, sem contar instalação e download dos modelos.

### Modelos registrados na versão 7

| Modelo | Quantização | Digest registrado pelo Ollama |
|---|---|---|
| `qwen3:8b-q8_0` | Q8_0 | `e56358ca25dd14db6853a9f68a92d717aaa6f0a94250a72d1a0f3d86a9f30130` |
| `gemma3:12b` | Q4_K_M | `b92b218582c521ba287f38f1d6057dcd3c6cbff036f13cac97b5d861f5e58ec3` |

Runtime da versão 7: `bae65032871bf30961dc7d44d6ee7ff4d550316e0ba80790d12f09a7fdedb709`. Corpus: `f06279c425ae67f5c551459a51c1bc810b7aad53b14d9715106f12b7b7ed65c8`.

Os tempos e decisões acima são observações de duas execuções de desenvolvimento. Não são uma estimativa de desempenho geral nem uma avaliação jurídica independente. A versão 6 demonstra o ciclo de feedback e bloqueio; a versão 7 demonstra a liberação de um candidato aprovado.

## Evidências e reprodução

- [Notebook de execução no Kaggle](../notebooks/04_multiagentes/02_execucao_kaggle_multiagentes.ipynb).
- [Instruções de execução](execucao_multiagentes_kaggle.md).
- [Arquitetura e comandos](sistema_multiagentes.md).
- [Notebook privado na conta autorizada](https://www.kaggle.com/code/withysphinx/lexia-multiagentes-gpu-20261117-154606).

Os arquivos detalhados ficam em `output/kaggle/multiagentes/envio-20261117-154606/`, ignorado pelo Git:

- Primeira execução completa: `resultados-v6/multiagentes/kaggle-corpus-20261117-204403-46af53/`.
- Execução aprovada: `resultados-v7/dados/kaggle-corpus-20261119-114147-f369a1/`.
- Pacote da execução aprovada: `resultados-v7/multiagentes_resultados.zip`.

Cada registro contém estado, eventos, fontes, resposta final e manifesto. Os artefatos permitem inspecionar as ações e o feedback, sem solicitar raciocínio interno dos modelos. Os 99 testes locais executados após as correções passaram: 68 do sistema multiagentes, 28 dos guardrails e 3 do juiz anterior.

A conclusão técnica do notebook é diferente da aprovação de uma resposta. A aprovação pelos controles do protótipo também não substitui revisão humana especializada.
