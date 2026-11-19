# lex_clt.ai
Aplicação com inteligência artificial para analisar processos trabalhistas, informar direitos e auxiliar trabalhadores na compreensão de sua situação, com respostas fundamentadas na legislação, na jurisprudência e normas.

> 🚧 Projeto em desenvolvimento. As funcionalidades descritas representam o escopo planejado e serão implementadas e avaliadas progressivamente.

## Estrutura Lexai integrada

Este checkout também incorpora a estrutura MLOps e o protótipo multiagente do repositório final. O backend, os contratos, o worker, os prompts e a avaliação estão organizados nos diretórios `backend/`, `contratos/`, `worker/`, `prompts/` e `avaliacao/`. Consulte o [manual de arquitetura](docs/manual.md), a [arquitetura dos agentes](docs/agentes/arquitetura.md) e o [registro da integração](docs/estado_integracao.md).

A implementação existente com LangGraph continua preservada em `worker/evidencia/langgraph/`. O protótipo importado, baseado em contratos Pydantic e orquestração própria, está em `worker/evidencia/agentes/`; as duas implementações coexistem e não foram fundidas nem substituídas. Os arquivos e notebooks anteriores foram migrados para os caminhos do layout atual; as configurações e os recursos Kaggle existentes foram preservados.

Os manifestos DVC foram trazidos, mas o remoto do repositório final apontava para uma pasta local que não existe neste checkout. Os dados já presentes foram preservados; configure um remoto compartilhado antes de executar `dvc pull`. O arquivo de feedback com respostas reais permanece local e ignorado pelo Git.

## Sobre o projeto

A disponibilidade de informações processuais nem sempre significa que elas sejam compreensíveis para quem precisa utilizá-las. Documentos técnicos, termos jurídicos e decisões complexas podem dificultar o acompanhamento de um processo trabalhista.

Este projeto propõe uma aplicação que utiliza Inteligência Artificial para transformar essas informações em explicações claras, contextualizadas e rastreáveis.

A solução pretende auxiliar trabalhadores na leitura de documentos, na compreensão das decisões e na identificação de possíveis próximas etapas, distinguindo o conteúdo dos documentos, as informações das fontes jurídicas e as incertezas da análise.

## Objetivo

Ampliar o acesso à compreensão dos direitos e processos trabalhistas, oferecendo informações em linguagem simples e favorecendo a autonomia dos trabalhadores.

A aplicação terá caráter informativo e de apoio à compreensão. Seu uso não substituirá a análise e a orientação de um profissional jurídico.

## Público-alvo

- Trabalhadores que desejam compreender seus direitos e documentos.
- Pessoas com dificuldade para acompanhar informações de processos trabalhistas.
- Advogados interessados em facilitar a comunicação com seus clientes.

## Funcionalidades planejadas

| Funcionalidade | Descrição |
|---|---|
| Envio de documentos | Receber documentos em PDF ou imagem. |
| Extração de texto | Extrair conteúdo textual e utilizar OCR quando necessário. |
| Identificação de documentos | Reconhecer tipos de documentos processuais. |
| Contextualização processual | Apresentar indícios da fase do processo com base nos documentos disponíveis. |
| Resumos acessíveis | Explicar o conteúdo em linguagem simples. |
| Explicação de decisões | Apresentar os fundamentos expressamente registrados nas decisões. |
| Perguntas e respostas | Esclarecer dúvidas sobre os documentos e termos jurídicos. |
| Consulta a direitos | Recuperar informações pertinentes na legislação e na jurisprudência selecionadas. |
| Próximas etapas possíveis | Explicar caminhos processuais possíveis, indicando limitações e informações ausentes. |
| Organização documental | Apontar documentos mencionados ou potencialmente relevantes para revisão profissional. |
| Referências verificáveis | Relacionar as explicações aos documentos e às fontes utilizadas. |

A identificação da fase processual dependerá da abrangência e da atualidade dos documentos fornecidos. Um documento isolado pode não representar a situação atual do processo.

## Arquitetura proposta

> A arquitetura do projeto e a estrutura atual estão descritas em [docs/estrutura_do_projeto.md](docs/estrutura_do_projeto.md). O material histórico de base de conhecimento está em [docs/legado/semana2_base_conhecimento_e_rag.md](docs/legado/semana2_base_conhecimento_e_rag.md).

O sistema será organizado em dois fluxos principais.

### Preparação das bases jurídicas

1. Coleta ou importação de legislação e jurisprudência.
2. Auditoria das fontes, dos arquivos e das versões.
3. Análise exploratória e avaliação da qualidade.
4. Limpeza e estruturação dos documentos.
5. Divisão em trechos com preservação do contexto.
6. Criação dos índices de recuperação.

Legislação e jurisprudência terão identificação própria, metadados e critérios de atualização.

### Análise e resposta ao usuário

1. Recebimento dos documentos e da pergunta.
2. Extração do texto, com OCR quando necessário.
3. Organização do conteúdo e de suas referências.
4. Recuperação de trechos pertinentes nos documentos e nas bases jurídicas.
5. Reordenação dos candidatos com um cross-encoder.
6. Geração de uma explicação com uma LLM.
7. Apresentação das fontes, limitações e informações ausentes.

### Componentes de Inteligência Artificial

| Componente | Papel no sistema |
|---|---|
| OCR | Reconhecer texto em imagens e documentos digitalizados. |
| Embeddings | Representar textos para recuperação por similaridade semântica. |
| Busca lexical | Recuperar termos exatos, expressões e referências a dispositivos. |
| Recuperação híbrida | Combinar resultados da busca lexical e da busca vetorial. |
| Cross-encoder | Reordenar os trechos recuperados conforme sua relevância para a pergunta. |
| LLM | Elaborar explicações a partir do contexto selecionado. |
| Classificador, se necessário | Auxiliar na identificação de tipos documentais, conforme os resultados dos experimentos. |

O RAG integra a recuperação de informações à geração das respostas. O cross-encoder atua na seleção dos trechos mais relevantes.

Na primeira versão, poderão ser utilizados modelos pré-treinados. A necessidade de treinamento ou fine-tuning será avaliada a partir dos resultados dos experimentos.

## Organização atual do repositório

```text
.
├── avaliacao/       # Notebooks, scripts e dados de avaliação
├── backend/         # API e serviços
├── configs/         # Configurações
├── contratos/       # Contratos e modelos compartilhados
├── corpus/          # Instruções e metadados para obter corpora
├── dados/           # Dados, artefatos e relatórios
├── docs/            # Documentação atual e legado em docs/legado/
├── entregas/        # Materiais de entrega
├── frontend/        # Interface do usuário
├── infra/           # Infraestrutura local e deploy
├── prompts/         # Prompts versionados
├── scripts/         # Utilitários de operação do projeto final
├── tests/           # Testes da aplicação e legado em tests/legado/
├── treino/          # Componentes de treino e MLOps
└── worker/
    ├── evidencia/   # Recuperação, geração, guardas e agentes
    └── ingestao/    # Ingestão e preparação de fontes jurídicas
```

Os dados de avaliação ficam em `avaliacao/dados/`; dados de trabalho, artefatos e relatórios ficam em `dados/`. As implementações multiagente coexistem em `worker/evidencia/agentes/` e `worker/evidencia/langgraph/`. A descrição detalhada está em [docs/estrutura_do_projeto.md](docs/estrutura_do_projeto.md).

Documentos reais de usuários, credenciais, arquivos de ambiente e índices contendo dados pessoais não deverão ser versionados no repositório.

## Ciência de Dados

Os experimentos serão organizados nos seguintes notebooks:

| Notebook | Objetivo |
|---|---|
| `01_auditoria_clt.ipynb` | Inventariar arquivos e verificar fontes, formatos, duplicações e problemas de extração. |
| `02_eda_clt.ipynb` | Explorar a composição e a estrutura textual do corpus. |
| `03_limpeza_estruturacao_clt.ipynb` | Preparar documentos e metadados preservando o significado jurídico. |
| `04_experimentos_chunking.ipynb` | Comparar estratégias de divisão dos textos. |
| `05_construcao_base_avaliacao.ipynb` | Organizar perguntas e referências esperadas. |
| `06_experimentos_recuperacao.ipynb` | Comparar busca lexical, vetorial e híbrida. |
| `07_integracao_rag_legislacao.ipynb` | Gerar respostas fundamentadas com citação de fontes e validar as citações. |
| `08_avaliacao_rag_llm.ipynb` | Avaliar respostas, citações, limitações e erros do sistema. |

A jurisprudência e a análise de documentos processuais poderão receber notebooks específicos nas etapas seguintes.

## Avaliação

O projeto avaliará tanto o desempenho técnico quanto a utilidade das explicações.

- **Extração:** preservação do conteúdo e identificação de falhas.
- **Recuperação:** Recall@k, MRR e nDCG@k.
- **Reranking:** ganho de relevância e impacto na latência.
- **Respostas:** correção, cobertura da pergunta e suporte nas fontes.
- **Classificação documental:** precisão, recall e F1 por classe, quando implementada.
- **Compreensão:** entendimento dos usuários antes e depois do uso.
- **Usabilidade:** facilidade para realizar as tarefas propostas.
- **Privacidade:** verificação dos controles e do tratamento dos dados.

As metas quantitativas serão definidas após a criação de uma linha de base. A avaliação jurídica das explicações deverá contar com revisão especializada.

## Privacidade e segurança

Documentos processuais podem conter dados pessoais e sensíveis. O desenvolvimento deverá considerar:

- Minimização dos dados coletados.
- Controle de acesso e isolamento entre usuários.
- Proteção dos arquivos armazenados e transmitidos.
- Regras de retenção e exclusão.
- Redução de dados pessoais em logs.
- Avaliação dos provedores utilizados para OCR e modelos.
- Tratamento dos documentos como conteúdo não confiável, incluindo proteção contra instruções maliciosas inseridas nos arquivos.
- Uso de exemplos sintéticos ou devidamente anonimizados em demonstrações públicas.

A adequação à LGPD é um requisito do projeto e dependerá da implementação e da avaliação dos procedimentos adotados.

## Limitações

A aplicação poderá produzir interpretações incorretas, recuperar fontes inadequadas ou deixar de identificar informações relevantes.

As respostas deverão indicar quando:

- Os documentos forem insuficientes ou ilegíveis.
- A atualização das fontes não estiver confirmada.
- Houver divergência entre informações.
- Não existir suporte suficiente para uma conclusão.

Estimativas de resultado, cálculos de prazos e recomendações de estratégia jurídica não fazem parte do MVP inicial.

## Roadmap

- [ ] Definir o escopo inicial e os requisitos.
- [ ] Auditar o repositório de legislação.
- [ ] Realizar a análise exploratória.
- [ ] Estruturar documentos e metadados.
- [ ] Construir a base de avaliação.
- [ ] Implementar e avaliar a recuperação.
- [ ] Integrar e avaliar o cross-encoder.
- [ ] Integrar a LLM com referências verificáveis.
- [ ] Implementar a leitura de documentos enviados.
- [ ] Desenvolver a API e a interface.
- [ ] Realizar revisão jurídica e testes com usuários.

## Como executar

As instruções de instalação e execução serão adicionadas conforme os componentes forem implementados e validados.

## Contribuições

Sugestões de melhoria, relatos de problemas e contribuições técnicas ou de acessibilidade são bem-vindos por meio de issues.

Não inclua dados pessoais, documentos processuais reais ou credenciais nas issues e nos pull requests.

## Licença

A licença do código será definida pelos responsáveis pelo projeto.

As fontes de dados e os modelos utilizados possuem condições próprias de uso, que deverão ser documentadas.


## Legislação: preparação e recuperação

- [Instalação e reprodução](docs/legado/execucao_reproducao.md)
- [Banco PostgreSQL e pgvector](docs/legado/pgvector.md)
- [Arquitetura e base de conhecimento](docs/legado/semana2_base_conhecimento_e_rag.md)

Os notebooks de `avaliacao/notebooks/01_legislacao/` preparam a base da CLT e avaliam a recuperação; a coleção fica no pgvector (schema `lex_clt`). A integração com a LLM segue no fluxo integrado de legislação e jurisprudência, com guardas e avaliação. A versão anterior está preservada na tag `rag-legislacao-v1`. Os prompts versionados ficam em `prompts/`, com carregamento feito por `worker/evidencia/prompts.py`.

## Jurisprudência: notebooks 01 a 04

Os notebooks de `avaliacao/notebooks/02_jurisprudencia/` usam a **base reduzida** de jurisprudência trabalhista: 179.812 registros do TST, dos TRTs 10, 13 e 17 e do STF (somente decisões com sinais de tema trabalhista). A base mantém um documento por processo e limita o TST a 100.000 decisões, por amostragem estratificada por ano e órgão julgador.

| Notebook | Conteúdo |
|---|---|
| `01_auditoria_jurisprudencia` | Inventário dos arquivos de entrada, esquemas, tribunais, qualidade e duplicatas |
| `02_eda_jurisprudencia` | Análise exploratória: composição, tamanhos de texto, datas e completude |
| `03_limpeza_estruturacao_jurisprudencia` | Estruturação, mascaramento de CPFs, PLN leve, proveniência e verificação automática |
| `04_experimentos_chunking_jurisprudencia` | Comparação das estratégias de chunking. Escolhidos: janela fixa de 500 tokens com 100 de sobreposição e BGE-M3 |
| `05_chunking_definitivo_jurisprudencia` | Chunking definitivo de um recorte de indexação de 20.000 documentos (303.257 chunks) |
| `06_embeddings_indexacao_jurisprudencia` | Embeddings BGE-M3 do recorte (Kaggle, FP16) e coleção `lex_jurisprudencia` no pgvector |

### O que é possível fazer a partir do clone

**1. Ler os resultados.** Os notebooks estão salvos com todas as saídas, tabelas e gráficos. Basta abri-los no GitHub, no Jupyter ou no VS Code, sem instalar nada.

**2. Preparar o ambiente e rodar os testes.** Testado com Python 3.14.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    Linux/macOS: source .venv/bin/activate
pip install -r docs/legado/requirements/requirements-chunking-jurisprudencia.txt
python -m unittest discover -s tests -p "test_jurisprudencia_chunking_avancado.py"
```

Os testes usados pelo notebook 04 são `test_avaliacao_complementar.py`, `test_contexto_centrado.py`, `test_finalistas_teste_reservado.py`, `test_jurisprudencia_chunking_avancado.py` e `test_jurisprudencia_piloto_bge.py`.

**3. Usar a base reduzida.** A base fica no dataset **privado** `laaaii/lex_ai`, no Hugging Face. O acesso é concedido pelos responsáveis pelo repositório. O dataset contém:

- `dados/parquet/`: 19 arquivos Parquet, a versão usada pelo pipeline;
- `dados/jsonl/`: a mesma base num único JSONL;
- `manifestos/`: contagens e hashes para conferência.

```bash
pip install huggingface_hub
hf auth login
```

```python
import pandas as pd
df = pd.read_parquet("hf://datasets/laaaii/lex_ai/data/parquet/f01.parquet")
```

> **Atenção:** os CPFs estão mascarados, mas a base **não está anonimizada**: nomes de partes e outros dados pessoais podem permanecer. Não redistribua nem publique os dados. As licenças declaradas pelas fontes são CC BY 4.0 (celsowm e RepoJus) e MIT (TRT-13). A origem do arquivo JSON do TST não foi confirmada.

**4. Reexecutar as células.** As células conferem os hashes dos dados processados e dos relatórios gerados pelo pipeline. Esses arquivos não são versionados (`dados/` e `dados/relatorios/jurisprudencia/`), então é preciso gerá-los primeiro.

- **Notebooks 01 a 03.** É preciso receber dos responsáveis três entradas que não estão no repositório nem no dataset:
  - os 20 arquivos de entrada da base reduzida, em `dados/raw/jurisprudencia/base_reduzida/`;
  - a declaração das origens, em `dados/raw/jurisprudencia/origens_declaradas.json`;
  - a rastreabilidade das fontes, em `dados/relatorios/jurisprudencia/origens_huggingface/`.

  Depois, execute:

  ```bash
  python worker/ingestao/scripts/rodar_pipeline_base_reduzida.py
  python worker/ingestao/scripts/run_auditoria_jurisprudencia.py
  python worker/ingestao/scripts/run_preparacao_jurisprudencia.py --etapa eda
  python worker/ingestao/scripts/run_preparacao_jurisprudencia.py --etapa estrutura
  ```

  No Windows, a renomeação dos CSVs grandes pode ser bloqueada pela sincronização ou pelo antivírus. Nesse caso, o pipeline imprime `FINALIZAR_FORA_DO_PROCESSO` com o script a executar. Execute esse script e retome com `--desde <próxima etapa>`.

- **Notebook 04.** Depende também dos gabaritos de avaliação (`avaliacao/dados/jurisprudencia/`) e dos artefatos dos experimentos, que existem apenas no ambiente de origem. Por isso, ele não pode ser reexecutado só com o clone.

- **Modelo.** O notebook 04 e o chunking usam o tokenizador do BGE-M3 a partir do cache local:

  ```bash
  hf download BAAI/bge-m3 --revision 5617a9f61b028005a4858fdac845db406aefb181
  ```

### Notebook 05 e índice de busca

O notebook `05_chunking_definitivo_jurisprudencia` aplica a estratégia escolhida no 04 (janela fixa de 500 tokens com 100 de sobreposição, tokenizador do BGE-M3) a um **recorte de indexação de 20.000 documentos**, e não aos 169.821 candidatos da base.

| | Base (notebooks 01 a 04) | Índice de busca (notebook 05 em diante) |
|---|---|---|
| Documentos | 179.812 registros, 169.821 candidatos ao RAG | 20.000 documentos (cerca de 12% dos candidatos) |
| Chunks e embeddings | — | 303.257 chunks |

- **Seleção:** os 187 documentos usados nos experimentos do notebook 04 e na avaliação entram obrigatoriamente. Os demais vêm de uma amostra estratificada proporcional por tribunal, ano e órgão julgador, com seed fixa. Composição: TST 11.749, TRT-17 3.226, TRT-10 2.795, TRT-13 1.403 e STF 827.
- **Motivo:** indexar todos os candidatos exigiria cerca de 2,57 milhões de chunks e cerca de 19 h de GPU. O recorte cabe numa sessão de cerca de 2,3 h e torna o projeto reprodutível.
- **Rastreabilidade:** cada chunk e cada embedding guarda o `registro_id` do documento de origem, o mesmo da base. O recorte é gerado por `worker/ingestao/scripts/criar_recorte_indexacao_jurisprudencia.py`, e o hash do arquivo fica registrado na configuração do chunking.
- **Embeddings (notebook 06):** os 303.257 chunks foram vetorizados com o BGE-M3 na GPU T4 do Kaggle, em FP16 (autocast), e gravados em float32. Cada parte foi conferida contra uma amostra em float32 (cosseno mínimo de 0,999813). Os vetores estão no schema `lex_jurisprudencia` do mesmo banco PostgreSQL/pgvector da legislação. Scripts: `exportar_pacotes_kaggle_jurisprudencia.py`, `importar_embeddings_kaggle_jurisprudencia.py` e o notebook portátil `dados/output/kaggle/06_embeddings_gpu_kaggle.ipynb`.
- **Limitação:** a busca só recupera decisões que estão no recorte. O índice pode ser ampliado depois, vetorizando apenas os documentos novos.

Mais detalhes nos [notebooks de jurisprudência](avaliacao/notebooks/02_jurisprudencia/), [relatórios de auditoria](docs/legado/auditoria_jurisprudencia.md), [proteção de CPFs](docs/legado/protecao_cpf_jurisprudencia.md), [PLN leve](docs/legado/pln_leve_jurisprudencia.md) e [avaliação do chunking](docs/legado/avaliacao_chunking_avancada.md).

## Sistema multiagentes com LangGraph

A primeira implementação está em `worker/evidencia/langgraph/`. O **Analista** (Qwen3 8B) escolhe uma consulta, recebe evidências e redige; o **Validador** (Gemma 3 12B) confere o candidato e pode devolver feedback para uma revisão. O LangGraph coordena as etapas, preserva as fontes e impede a liberação de respostas bloqueadas.

- [Arquitetura, comandos e estado da implementação](docs/sistema_multiagentes.md).
- [Guia de planejamento da atividade](docs/plano_sistema_multiagentes.md).
- [Execução dos dois agentes na GPU do Kaggle](docs/execucao_multiagentes_kaggle.md).
- [Buscador local com embeddings persistidos](docs/buscador_local.md).
- [Notebook de demonstração local](avaliacao/notebooks/04_multiagentes/01_demonstracao_multiagentes.ipynb).

Preparar a primeira demonstração no Kaggle, com um corpus portátil da legislação:

```bash
python avaliacao/scripts/preparar_multiagentes_kaggle.py --tema ferias
```

Por padrão, o pacote usa busca lexical no corpus fornecido. Para a base original completa, use `python avaliacao/scripts/preparar_multiagentes_kaggle.py --buscador local`: o notebook prepara embeddings BGE-M3 e cache SQLite antes do atendimento. Na CLI, `--modo local` usa esse buscador sem banco; `--modo real` reaproveita a busca híbrida no pgvector; `--modo sintetico` usa fontes fictícias. Os modelos configurados são chamados quando a pergunta exige inferência. Testes com modelos substitutos ficam restritos a `tests/`.

Para testar somente a busca sem chamar os agentes, instale `docs/legado/requirements/requirements-buscador-local.txt` e execute:

```bash
python worker/evidencia/scripts/consultar_buscador_local.py --preparar-indice
python worker/evidencia/scripts/consultar_buscador_local.py --pergunta "Como funciona o adicional noturno no trabalho urbano?"
```

Para instalar e verificar o código dos agentes:

```bash
python -m pip install -r docs/legado/requirements/requirements-multiagentes.txt
python -m unittest discover -s tests -p "test_multiagentes*.py" -v
```

Os notebooks versionados não contêm respostas inventadas dos modelos. A primeira execução real Qwen/Gemma foi concluída no Kaggle, com feedback e revisão registrados. Veja [os resultados da demonstração](docs/resultados_multiagentes.md), incluindo limitações e correções posteriores ao piloto.
