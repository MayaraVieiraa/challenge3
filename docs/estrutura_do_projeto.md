# Estrutura do projeto lex_clt.ai

> Versão 1.0 (13/11/2026). Descreve cada pasta, o que ela guarda e para que serve. Itens marcados **(planejado)** existem como pasta vazia ou ainda não existem.

## Visão geral

```
lex_clt.ai/
├── README.md, requisitos.md, requirements.txt
├── compose.pgvector.yaml, .env.pgvector.example
├── data/        dados de entrada, intermediários e de avaliação
├── notebooks/   experimentos e documentação executável de cada etapa
├── src/         código reutilizável (RAG e armazenamento)
├── scripts/     utilitários de linha de comando
├── tests/       testes automatizados
├── reports/     saídas geradas pelos notebooks e scripts
└── docs/        documentação em texto
```

Padrão: cada pasta de dados e relatórios se divide por corpus (`legislacao/`, `jurisprudencia/`).

---

## Raiz

| Arquivo | Função |
|---|---|
| `README.md` | Visão do projeto, público-alvo, funcionalidades planejadas e arquitetura proposta |
| `requisitos.md` | Requisitos de dados da base de legislação (RF-D01 em diante) |
| `requirements.txt` | Dependências Python (sem versões fixas) |
| `compose.pgvector.yaml` | Sobe o PostgreSQL 17 + pgvector 0.8.7 no Docker, só em `127.0.0.1:15432` |
| `.env.pgvector.example` | Modelo das credenciais locais do banco (o `.env.pgvector.local` real não vai ao git) |
| `.gitignore` | Ignora ambiente virtual, caches, credenciais, `data/raw`, `data/interim`, `data/processed`, `data/chunks`, modelos e logs |

---

## `data/`

| Pasta | Conteúdo | Corpus |
|---|---|---|
| `data/README.md` | Fonte dos dados (LawCodex/br, commit e2a0e14…, obtido em 04/11/2026), licença pendente, como reproduzir | legislação |
| `data/raw/legislacao/` | Cópia bruta dos arquivos do LawCodex. Ignorada no git | legislação |
| `data/raw/jurisprudencia/` | Dados brutos da jurisprudência. Ignorada no git | **(planejado)** |
| `data/processed/legislacao/` | `legislacao_artigos_completos.json`: 5.284 artigos estruturados (artigo › parágrafo › inciso › alínea) | legislação |
| `data/processed/jurisprudencia/` | Decisões e súmulas estruturadas | **(planejado)** |
| `data/chunks/legislacao/` | `chunks_A_artigo.json` (contexto, 1 chunk por artigo) e `chunks_D_paragrafo_completo.json` (busca, por parágrafo) | legislação |
| `data/chunks/jurisprudencia/` | Chunks de jurisprudência | **(planejado)** |
| `data/evaluation/legislacao/` | Perguntas e referências de avaliação (dev e teste), em rascunho e aprovadas; `teste_congelado.json`; `manifesto_avaliacao.json`; anotações; `feedback_pos_teste/` com respostas reais e feedback humano | legislação |
| `data/evaluation/jurisprudencia/` | Dataset de avaliação da jurisprudência | **(planejado)** |

---

## `notebooks/`

Cada notebook documenta uma etapa do pipeline.

| Notebook | Etapa |
|---|---|
| `01_legislacao/01_auditoria_clt.ipynb` | Auditoria dos arquivos: formatos, hashes, duplicados, cobertura |
| `02_eda_legislacao.ipynb` | Análise exploratória: normas, artigos, formatos, preâmbulos, notas |
| `03_limpeza_estruturacao_clt.ipynb` | Limpeza e estruturação hierárquica dos artigos |
| `04_experimentos_chunking.ipynb` | Comparação de 5 estratégias de chunking (escolhida D → A) |
| `05_construcao_base_avaliacao.ipynb` | Perguntas dev/teste e referências, com revisão humana |
| `06_experimentos_recuperacao.ipynb` | BGE-M3, busca lexical, HyDE, RRF e reranker, com Recall, MRR e nDCG |
| `07_integracao_rag_legislacao.ipynb` | Integração completa: recuperação, geração com Ollama, citação e revisão |
| `08_avaliacao_final_rag_legislacao.ipynb` | Teste da configuração congelada e revisão humana das respostas |
| `02_jurisprudencia/` | Notebooks da jurisprudência. Pasta vazia | **(planejado)** |

---

## `src/`

### `src/rag/` — recuperação, geração, revisão e avaliação

| Módulo | Função |
|---|---|
| `workflow_07.py` | Persistência de revisões, correções limitadas, variantes com recuperação real (`VariantRetriever`), diagnóstico |
| `presentation_07.py` | Consulta livre (`InteractiveRAG`), inspeção por frase, tabelas de fontes |
| `review_persistence_07.py` | Persistência de revisões de novas versões de resposta |
| `frozen_config_07.py` | Congelamento da configuração final (hash) |
| `evaluation_08.py` | Execução do teste congelado e métricas sem gabarito no prompt |
| `review_08.py` | Leitura das avaliações escritas nas células do notebook 08 |
| `feedback_08.py` | Exportação de respostas reais e feedback humano |

### `src/storage/` — armazenamento

| Módulo | Função |
|---|---|
| `pgvector_store.py` | Importa embeddings existentes ao PostgreSQL, verifica vetor↔chunk por hash, busca por similaridade |
| `parent_documents.py` | Expande o chunk de busca (D) para o artigo completo (A) e formata o contexto |

### `src/jurisprudencia/` **(planejado)**
Só tem `__init__.py` e `.gitkeep`. Receberá o código da jurisprudência (esquema, chunking, recuperação, geração).

---

## `scripts/`

| Script | Função |
|---|---|
| `configure_local_pgvector.py` | Gera credenciais locais para o Docker, sem imprimir senhas |
| `import_existing_pgvector.py` | Valida e importa vetores existentes; nunca recalcula embeddings |
| `run_notebook_07.py` | Executa as células do 07 e salva as saídas |
| `testar_integracao_07.py` | Executa as células novas da integração e uma consulta livre |
| `congelar_configuracao_07.py` | Acrescenta e executa o congelamento da configuração |
| `run_context_review.py` | Executa a revisão de contexto |
| `validar_notebook_08_leitura.py` | Valida o notebook 08 em modo leitura, sem geração |

---

## `tests/`

| Teste | O que cobre |
|---|---|
| `test_pgvector_store.py` | Importação e verificação de vetores |
| `test_parent_documents.py` | Expansão filho → pai |
| `test_rag_presentation.py` | Apresentação e inspeção de respostas |
| `test_rag_review_workflow.py` | Fluxo de revisão |
| `test_generated_review_persistence.py` | Persistência de revisões geradas |
| `test_evaluation_08.py` | Métricas e execução da avaliação |
| `test_feedback_08.py` | Exportação de feedback |
| `test_jurisprudencia_*.py` | **(planejado)** |

---

## `reports/`

Saídas geradas. Em `reports/legislacao/`:

| Subpasta | Conteúdo |
|---|---|
| `auditoria/` | Resumo, cobertura, duplicados e arquivos auxiliares da auditoria |
| `eda/` | Estatísticas de normas, artigos, formatos, preâmbulos, notas e rastreabilidade |
| `estruturacao/` | Decisões de revisão, alertas por norma, validação de preservação e pendências do parser |
| `chunking/` | Manifesto, cortes estruturais, limites de tokens, comparação entre estratégias |
| `avaliacao/` | Validação das referências, pendências de revisão e distribuição do catálogo |
| `recuperacao/` | Matriz de recuperação, rankings, métricas por pergunta e comparações (A, D→A, HyDE, RRF, reranker) |
| `pgvector/` | Manifestos de importação e correspondência vetor↔chunk, por estratégia |
| `integracao_rag/` | Respostas do RAG, revisões, correções, variantes, validação por frase, configuração congelada e diagnóstico |
| `avaliacao_final/<hash>/` | Teste final: respostas, métricas, revisões humanas, conclusão e manifestos, por hash de configuração |

Em `reports/jurisprudencia/` **(planejado, vazio)**: `auditoria`, `eda`, `estruturacao`, `chunking`, `recuperacao`, `pgvector`, `avaliacao`.

---

## `docs/`

| Documento | Conteúdo |
|---|---|
| `semana2_base_conhecimento_e_rag.md` | Entregáveis da semana 2: arquitetura, base, ingestão, chunking, embeddings, banco, recuperação, geração |
| `pgvector.md` | Como subir e importar o PostgreSQL com pgvector |
| `execucao_reproducao.md` | Como reproduzir o ambiente e os experimentos |
| `06_demonstracao_rag_trabalhista.md` | Demonstração com uma consulta real (`q_test_01`) |
| `jurisprudencia_planejamento.md` | Planejamento da parte de jurisprudência |
| `estrutura_do_projeto.md` (este documento) | Mapa das pastas |

---

## Pontos a observar

- `docs/semana2_base_conhecimento_e_rag.md` cita PostgreSQL 16, mas o `compose.pgvector.yaml` usa a imagem `pg17`.
- `src/rag/workflow_07.py` reutiliza código dos notebooks por `exec` de células. Isso foi combinado para ficar para depois.
- `requirements.txt` não fixa versões.
- A jurisprudência só tem a estrutura de pastas; nenhuma etapa foi iniciada.
