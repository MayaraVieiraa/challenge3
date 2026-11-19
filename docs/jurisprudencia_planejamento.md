# Jurisprudência — planejamento e encaixe na arquitetura

> Versão 0.1 (13/11/2026). Documento de planejamento: nada aqui está implementado ainda.

## 1. Objetivo

Adicionar ao lex_clt.ai uma base de jurisprudência trabalhista, recuperável e citável com o mesmo rigor da legislação, sem alterar o fluxo já validado (notebooks 01–08).

## 2. Estrutura criada

```
avaliacao/notebooks/02_jurisprudencia/          (já existia)
dados/raw/jurisprudencia/              ignorada no git
dados/processed/jurisprudencia/        ignorada no git
dados/chunks/jurisprudencia/           ignorada no git
avaliacao/dados/jurisprudencia/       versionada
dados/relatorios/jurisprudencia/{auditoria,eda,estruturacao,chunking,recuperacao,pgvector,avaliacao}/
worker/ingestao/jurisprudencia/                   código em módulo (não em notebook)
```

Também foi adicionado `/dados/raw/jurisprudencia/` ao `.gitignore`. Pastas vazias versionadas têm `.gitkeep`.

Ainda por criar: `tests/test_jurisprudencia_*.py` e esta documentação ampliada.

## 3. O que não pode ser reaproveitado como está

| Parte | Problema | Proposta |
|---|---|---|
| `worker/evidencia/indices/pgvector_store.py` | `MODEL`, `STRATEGY='A_artigo'` e a coluna `article_id` fixos | Mesmo container e schema; coluna `corpus` em `vector_datasets` e metadados em `jsonb` (ou tabelas próprias) |
| Metadados | Legislação: artigo, parágrafo, inciso | Jurisprudência: tribunal, tipo (acórdão, súmula, OJ, tese), nº do processo, relator, órgão julgador, data, situação |
| Chunking | Acórdãos são longos e seccionados | Busca na ementa/fundamentação, contexto na decisão inteira (mesma ideia D→A). Súmula, OJ e tese: 1 chunk |
| Vigência | Súmulas são canceladas ou revisadas | Campos `situacao` e `data_vigencia`; filtro na busca |
| Prompt e citação | `SYSTEM_PROMPT_LEGAL` e a checagem por frase pensam em artigos | Formato de citação próprio e separação explícita lei × jurisprudência |
| Avaliação | Referências de ouro são artigos | Dataset dev/teste próprio, com revisão humana, como na legislação |

## 4. Encaixe na arquitetura

- **Dois índices e dois retrievers** (legislação e jurisprudência), unidos depois por fusão ou roteamento.
- Não misturar os dois corpora no mesmo RRF e reranker: scores e tamanhos de trecho não são comparáveis, e a distinção lei/decisão se perderia.
- Mesmo modelo de embedding (BGE-M3, 1.024 dimensões) e mesmo PostgreSQL.
- Código novo em `worker/ingestao/jurisprudencia/` desde o início, para não repetir o acoplamento a notebooks.

## 5. Etapas sugeridas

1. **Fonte e auditoria:** escolher a origem, registrar commit/data/licença em `corpus/README_lawcodex.md`, auditar arquivos e hashes.
2. **EDA:** formatos, campos ausentes, duplicatas, distribuição por tribunal, tipo e ano.
3. **Estruturação:** esquema de documento e chunk com metadados e vigência.
4. **Chunking:** testar 2–3 estratégias, medir em perguntas de desenvolvimento.
5. **Embeddings e pgvector:** importar com verificação de hash vetor↔chunk.
6. **Recuperação:** híbrida (lexical + vetorial) com reranker; medir Recall, MRR e nDCG.
7. **Geração:** prompt e citação para jurisprudência; integração com a legislação.
8. **Avaliação final:** teste congelado, revisão humana, relatório.

## 6. Decisões em aberto

1. **Fonte e licença** (TST, DataJud, LexML, TRTs). Define formato, volume e esforço de coleta.
2. **Escopo:** só TST ou também TRTs; só súmulas/OJs/teses ou acórdãos completos.
3. **Ponto de partida recomendado:** súmulas e OJs do TST. São curtas, estruturadas e de alto valor para o trabalhador, e o piloto custa pouco.
4. **Esquema do banco:** coluna `corpus` na tabela existente ou tabelas separadas.
5. **Fusão:** roteamento por tipo de pergunta ou recuperação nos dois índices com apresentação separada.

## 7. Riscos

- Licença e termos de reutilização da fonte ainda desconhecidos.
- Jurisprudência desatualizada ou cancelada apresentada como vigente.
- Acórdãos longos aumentam custo de embedding e tamanho de contexto.
- Citação de decisão inexistente ou imprecisa pela LLM (exige validação por frase, como na legislação).
- Dataset de avaliação exige revisão humana, que é o gargalo da etapa.
