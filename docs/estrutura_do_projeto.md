# Estrutura do projeto

O repositório usa a organização do projeto Lexai final. O código da aplicação, os pipelines de ingestão e evidência, a avaliação, a infraestrutura e os dados ficam separados por responsabilidade.

```text
.
├── avaliacao/
│   ├── dados/             # Conjuntos e artefatos de avaliação
│   ├── notebooks/         # Auditoria, EDA, integração e experimentos
│   └── scripts/           # Geração, juiz e utilitários de avaliação
├── backend/               # API e serviços
├── configs/               # Configurações versionadas
├── contratos/             # Contratos e modelos compartilhados
├── corpus/                # Instruções e metadados para obter corpora
├── dados/
│   ├── chunks/            # Trechos para recuperação
│   ├── output/            # Saídas locais e artefatos de execução
│   ├── processed/         # Dados processados
│   ├── raw/               # Fontes locais, não versionadas
│   └── relatorios/        # Relatórios e resultados
├── docs/
│   ├── agentes/           # Documentação dos agentes
│   └── legado/            # Documentação e requisitos herdados
├── entregas/              # Materiais de entrega
├── frontend/              # Interface web
├── infra/                 # Docker e configuração de infraestrutura
├── prompts/               # Prompts versionados
├── scripts/               # Utilitários de operação do projeto final
├── tests/
│   └── legado/            # Testes migrados do projeto anterior
├── treino/                # Treinamento e MLOps
└── worker/
    ├── evidencia/         # Recuperação, guardas, geração e agentes
    └── ingestao/          # Ingestão e preparação de fontes jurídicas
```

## Dados e privacidade

- Dados de avaliação ficam sob `avaliacao/dados/`.
- Dados de origem, derivados e saídas ficam sob `dados/`; dados locais e saídas sensíveis são ignorados pelo Git.
- Respostas reais de avaliação permanecem apenas locais em `avaliacao/dados/legislacao/feedback_pos_teste/`.
- Manifestos DVC descrevem alguns dados compartilhados. O remoto deve estar configurado antes de executar `dvc pull`.

## Multiagentes

Há duas implementações intencionalmente preservadas:

- `worker/evidencia/agentes/`: protótipo multiagente importado do repositório final.
- `worker/evidencia/langgraph/`: implementação LangGraph anterior, com ferramentas, contratos, registro e CLI.

Essas arquiteturas coexistem; a reorganização não as funde nem substitui uma pela outra.

## Referências

- [Estado da integração](./estado_integracao.md)
- [Manual de arquitetura](./manual.md)
- [Execução multiagente no Kaggle](./execucao_multiagentes_kaggle.md)
