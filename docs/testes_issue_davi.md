# Roteiro de teste da issue do Davi

Conferido em **19/11/2026**, a partir do texto da issue enviado na conversa.

A issue pede recuperação local, cache de embeddings, um recorte de jurisprudência anonimizado e checagem dos dados pessoais do material da demo. Sua parte precisa funcionar isoladamente e depois integrar o fluxo da equipe.

**Atualização:** o `BuscadorLocal` e seu cache agora estão implementados neste workspace. Consulte [implementação e comandos](buscador_local.md). As execuções antigas do Kaggle citadas neste roteiro continuam sendo as do corpus lexical; não foram reclassificadas como execuções do novo buscador.

## Atenção ao repositório e à branch

Este workspace está em `paiva-l/lex_clt.ai`, branch `main`. A issue aponta para `femathrl0/Lexai`, branch `entrega/multiagente`. Essa branch não aparece nas referências locais. O endereço de `docs/agentes/arquitetura.md` indicado na issue retornou HTTP 404 nesta consulta; seu conteúdo não pôde ser conferido.

Por isso, os comandos abaixo validam **o protótipo deste workspace**. Não comprovam o estado da branch de entrega do outro repositório. Não troque de branch ou copie arquivos por cima do trabalho atual para executar estes testes.

## 1. Testar o código atual sem GPU

Na raiz deste projeto, com o ambiente Python ativado:

```bash
source .venv/bin/activate
python -m unittest discover -s tests -p "test_multiagentes*.py" -v
python -m unittest discover -s tests -p "test_buscador_local*.py" -v
```

Se estiver preparando um ambiente novo, crie o virtualenv e instale antes:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r docs/legado/requirements/requirements-multiagentes.txt
```

Os 68 testes multiagentes anteriores passaram. A segunda suíte cobre agora o buscador local, suas CLIs e o empacotamento para Kaggle. Os testes usam fakes ou transporte substituído e não precisam de Ollama, GPU, PostgreSQL ou acesso à rede durante sua execução.

Para conferir também os controles e o juiz anteriores:

```bash
python -m unittest discover -s tests -p "test_integracao_guardrails.py" -v
python -m unittest discover -s tests -p "test_integracao_juiz.py" -v
```

Essas duas suítes também foram executadas nesta conferência: 28 testes de guardrails e 3 do juiz, todos aprovados. Com os 52 novos testes do buscador, o total atualizado é **151 testes locais aprovados**.

Os cenários existentes incluem:

| Cenário | Teste existente | O que comprova |
|---|---|---|
| Caminho aprovado | `test_aprovacao_exige_busca_redacao_e_validacao` | Consulta, busca, redação e aprovação antes de liberar a resposta |
| Refazer frase | `test_feedback_chega_ao_analista_e_revisao_e_revalidada` | Feedback chega ao Analista e a nova versão passa pelo Validador |
| Revisão esgotada | `test_segunda_reprovacao_encerra_sem_exibir_candidato` | Uma segunda reprovação encerra sem publicar o candidato |
| Citação inexistente | `test_guardrail_veta_citacao_inexistente_mesmo_com_aprovacao_do_validador` | O controle veta a saída mesmo quando o modelo a aprova |
| Nenhuma fonte | `test_busca_sem_fontes_encerra_sem_inventar_resposta` | O protótipo encerra com limitação; **não** realiza outra pesquisa |
| Pergunta com CPF/e-mail fictícios | `test_dados_pessoais_nao_sao_enviados_aos_agentes_ou_busca` | Esses padrões são mascarados antes das chamadas; não cobre toda a demo |
| Recuperação lexical | Classe `TestBuscaCorpus`, em `tests/test_multiagentes_cliente.py` | Ranking, acentos, desempate, deduplicação e validação do corpus portátil |
| Registro | `test_exportacao_inclui_hashes_e_nao_sobrescreve` | Artefatos possuem hashes e a exportação não substitui um registro existente |

Os nomes dos testes de fluxo estão em `tests/test_multiagentes.py`, exceto os de recuperação e registro indicados na tabela.

## 2. Experimentar a busca sem executar os agentes

Para a recuperação semântica nova, instale as dependências e faça duas preparações do índice:

```bash
python -m pip install -r docs/legado/requirements/requirements-buscador-local.txt
python worker/evidencia/scripts/consultar_buscador_local.py --preparar-indice
python worker/evidencia/scripts/consultar_buscador_local.py --preparar-indice
python worker/evidencia/scripts/consultar_buscador_local.py --pergunta "Como funciona o adicional noturno no trabalho urbano?"
```

Se ainda não existir cache compatível, a primeira preparação gera os embeddings. A segunda deve apresentar `cache_reutilizado: true`, sem recodificar os artigos. A consulta calcula seu próprio embedding. O modelo real pode ser baixado na primeira utilização; a execução dos agentes continua no comando separado `executar_multiagentes.py --modo local`.

O teste lexical antigo permanece abaixo para reprodução da primeira demo.

O JSON original disponível neste checkout está em `dados/processed/legislacao/legislacao_artigos_completos.json`. O novo buscador prefere o caminho `dados/processed/...` da issue e aceita `dados/processed/...` como alternativa. A obtenção por DVC ainda não está configurada aqui.

Prepare um pacote separado do usado na execução já registrada:

```bash
python avaliacao/scripts/preparar_multiagentes_kaggle.py --tema ferias --destino dados/output/multiagentes/teste-busca
```

Depois execute, ainda na raiz do projeto:

```bash
python - <<'PY'
from pathlib import Path
from worker.evidencia.langgraph.ferramentas import BuscaCorpus

busca = BuscaCorpus(Path("dados/output/multiagentes/teste-busca/corpus_legislacao.json"))
try:
    fontes = busca.buscar("regras gerais sobre férias")
    assert fontes, "A consulta não recuperou fontes."
    assert len({f["unidade"] for f in fontes}) == len(fontes)
    assert all(f["fonte"] == "legislacao" and f["conteudo"].strip() for f in fontes)
    print("Busca OK. Fontes recuperadas:", len(fontes))
    for fonte in fontes:
        print(fonte["artigo_ref"], fonte["unidade"])
finally:
    busca.fechar()
PY
```

Esse teste usa textos reais da base local, mas a recuperação é **lexical**. Ele não verifica embeddings nem cache e não equivale ao `BuscadorLocal` solicitado.

O comando acima foi conferido nesta máquina: recuperou seis artigos, de 129 a 133, incluindo 130-A. A busca retorna o texto da base, inclusive as marcações de revogação existentes; recuperar um artigo não certifica sua vigência.

## 3. Repetir a demonstração com os modelos no Kaggle

1. Abra o [notebook privado autorizado](https://www.kaggle.com/code/withysphinx/lexia-multiagentes-gpu-20261117-154606).
2. Confira o dataset de entrada, Internet habilitada e GPU T4 selecionada.
3. Na primeira célula de código, ajuste `PERGUNTA` para uma pergunta coberta pelo recorte de férias. Mantenha `EXECUTAR = True`.
4. Execute todas as células e confira os eventos, as fontes, o candidato e a decisão do Validador.
5. Baixe `multiagentes_resultados.zip`. Confira `estado.json`, `eventos.jsonl`, `fontes.json`, `resposta.txt` e `manifesto.json`.

O resultado da nova inferência pode variar. `aprovada`, `limitada` e `falha_tecnica` devem ser registrados como ocorrerem. A execução já observada e aprovada está em [resultados_multiagentes.md](resultados_multiagentes.md).

Uma consulta fora do recorte demonstra, no máximo, uma limitação daquele corpus; não demonstra ausência de fonte na base jurídica inteira.

Para demonstrar a revisão com erro deliberado, existe `EXECUTAR_DEMO_REVISAO = True`. Essa rodada usa material fictício e identifica a falha inserida; ela deve ser apresentada separadamente da execução com legislação. Ela não demonstra o laço de nova pesquisa, que ainda está ausente.

## 4. Critérios específicos para aceitar o BuscadorLocal

Os testes de leitura, persistência e recuperação abaixo foram implementados com fakes em `tests/test_buscador_local.py`, com integração de CLI/grafo e pacote nos outros arquivos `test_buscador_local*.py`. A obtenção por DVC, a avaliação de pertinência revisada e a jurisprudência ainda exigem trabalho e comprovação na branch de entrega. Use a base e o modelo reais na avaliação de recuperação.

| Caso | Preparação e resultado esperado |
|---|---|
| Dados disponíveis | Em um clone da branch de entrega, `dvc pull` recupera o JSON configurado. Conferir o caminho e a versão dos dados. Aqui não existe configuração DVC para executar essa etapa. |
| Leitura do formato original | Uma fixture pequena com o esquema do JSON original produz documentos com texto, identificador e proveniência preservados. |
| Primeira indexação | O embedder fake recebe os textos dos artigos e o buscador grava um cache em um diretório temporário equivalente a `dados/output/`. |
| Reutilização do cache | Uma nova instância usa o mesmo cache sem recalcular embeddings dos artigos. O embedding de uma nova consulta pode ser calculado normalmente. |
| Cache invalidado | Alterar o texto do corpus ou a identidade/configuração do modelo impede reutilizar embeddings antigos. Conferir dimensão e correspondência entre vetores e documentos. |
| Cache incompleto ou corrompido | O buscador reconstrói com segurança ou apresenta erro claro; não consulta uma matriz inconsistente. |
| Consulta conhecida | Uma pergunta revisada pelo par recupera os identificadores esperados no `top_k`, com texto e metadados. O teste usa referências previamente conferidas, sem inferir validade jurídica apenas do ranking. |
| Sem evidência | Retorna ausência de evidência conforme o contrato, sem criar fonte ou atribuir metadados inexistentes. |
| Entrada inválida | Arquivo ausente, JSON inválido, texto vazio e consulta vazia têm comportamento explícito e testado. |
| Jurisprudência | O recorte revisado retorna cada trecho com fonte verificável, data identificada e tipo de fonte. A origem dessas datas deve ser clara; não preencher datas ausentes por suposição. |

O novo `BuscadorLocal` é uma implementação separada de `BuscaCorpus`: persiste vetores normalizados em SQLite e verifica sua compatibilidade e integridade antes da reutilização. Os testes conferem que uma segunda instância não recodifica os artigos.

## 5. Conferir a integração com o fluxo da equipe

| Fluxo exigido pela issue | Situação neste workspace |
|---|---|
| Triagem → Pesquisa → Análise → Comunicação → Validação | O protótipo tem dois agentes: Analista e Validador. Os papéis não estão separados como no fluxo informado. |
| Validação → Análise, refazer frase no máximo uma vez | Existe um laço de revisão com revalidação e teste. |
| Validação → Pesquisa, sem fonte no máximo uma vez | Não implementado; as fontes são congeladas após uma busca. |
| Validador como último portão | O candidato só é liberado com aprovação do Validador e dos controles. Se Comunicação for separada na integração, o texto comunicado também precisa passar por essa validação. |

Na integração da equipe, acrescente um teste com pesquisa fake que retorna primeiro evidência insuficiente e depois evidência adequada. Confira duas buscas, uma única volta para Pesquisa e nova validação antes da saída. Teste também a segunda insuficiência: deve encerrar sem uma terceira pesquisa e sem liberar conclusão sem apoio. Os limites de revisão da frase e de nova pesquisa precisam de contadores independentes.

## 6. Evidência para concluir a issue

- Registrar os comandos e resultados dos testes na branch `entrega/multiagente` e no commit que será apresentado.
- Demonstrar criação e reaproveitamento do cache, além de uma recuperação com metadados conferidos.
- Separar e revisar o recorte de jurisprudência. O mascaramento de CPFs existente no projeto não equivale a anonimização integral.
- Conferir os arquivos que efetivamente aparecerão na demo: perguntas, trechos recuperados, respostas, rastros exportados e gravação. A checagem automática por padrões deve ser acompanhada de revisão humana do material selecionado, incluindo nomes e outros identificadores.
- Registrar revisão pelo par e revisão jurídica, sem confundi-las com aprovação automática do modelo.
- Conferir o CI do commit de entrega: teste local passando não comprova CI verde. Não há workflow `.github` neste checkout.
- Mostrar a recuperação na demo de sexta. A tag `entrega-multiagente-2026-11-20` e o envio ao Teams pertencem ao fechamento da entrega, depois dessas verificações; não foram realizados neste roteiro.

**Conclusão desta conferência:** o buscador semântico com cache, os testes com fakes e sua integração com os agentes foram implementados. Permanecem a configuração DVC aplicável à equipe, a preparação/revisão do recorte de jurisprudência, a avaliação de recuperação e a comprovação de revisão/CI/demo na branch de entrega. O laço adicional de Pesquisa não faz parte desta implementação do buscador.
