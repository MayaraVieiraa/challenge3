# Migração do lex_clt.ai (commit 9c3f43f)

| Origem | Destino |
|---|---|
| `worker/evidencia/recuperacao.py` | `worker/evidencia/recuperador.py` |
| `worker/evidencia/guardrails.py` | `worker/evidencia/guardas.py` |
| `worker/evidencia/geracao.py` | `worker/evidencia/explicador.py` |
| `worker/evidencia/prompt_juridico.py` | `worker/evidencia/prompts.py` + texto em `prompts/explicador/v1.md` |
| `worker/evidencia/avaliacao_recuperacao.py` | `avaliacao/recuperacao.py` |
| `worker/evidencia/juiz.py` | `avaliacao/juiz.py` |
| `worker/evidencia/indices/*` | `worker/evidencia/indices/` |
| `worker/ingestao/jurisprudencia/*` | `worker/ingestao/jurisprudencia/` |
| `scripts/*` (dados) | `worker/ingestao/scripts/` |
| `scripts/*` (geração, juiz, Kaggle) | `avaliacao/scripts/` |
| `notebooks/*` | `avaliacao/notebooks/` |
| `avaliacao/dados/*` | `avaliacao/dados/` |
| `data/processed`, `data/chunks` | `dados/processed`, `dados/chunks` (DVC) |
| `dados/relatorios/legislacao` | `dados/relatorios/legislacao` (DVC) |
| `dados/relatorios/integracao` | `dados/relatorios/integracao` (Git) |
| `tests/*` | `tests/legado/` |
| `compose.pgvector.yaml` | `infra/docker-compose.yml` |
| `docs/*`, `requisitos.md` | `docs/legado/` |

Reescritas da migração: imports `src.*` foram direcionados aos módulos atuais; `data/` foi dividido entre `dados/` e `avaliacao/dados/`; relatórios e saídas foram movidos para `dados/relatorios/` e `dados/output/`; a profundidade de `ROOT` foi atualizada nos scripts migrados.

Atenção:
- Os manifestos de proveniência antigos registram hashes de código; como os imports mudaram, os hashes dos arquivos migrados não batem mais com os manifestos. Reexecutar a etapa gera manifestos novos.
- `dados/raw/` (LawCodex e base de jurisprudência) não estava no Git do lex_clt.ai; recriar conforme `corpus/README_lawcodex.md` e `docs/legado/execucao_reproducao.md`.
- Os notebooks citam caminhos antigos nas saídas já gravadas; o código das células foi reescrito.
