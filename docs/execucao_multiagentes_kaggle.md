# Executar os dois agentes no Kaggle

O pacote executa o **Analista, Qwen3 8B**, e o **Validador, Gemma 3 12B**, na GPU da sessão do Kaggle. O Analista escolhe uma consulta e usa a ferramenta de busca; o Validador recebe a pergunta, as mesmas fontes, a resposta candidata e os alertas dos guardrails. Quando solicita uma correção, o feedback volta ao Analista para uma única revisão.

O notebook principal é [02_execucao_kaggle_multiagentes.ipynb](../notebooks/04_multiagentes/02_execucao_kaggle_multiagentes.ipynb). Ele está sem execuções e sem resultados preenchidos. O roteiro abaixo prepara uma execução real dos modelos, usando o recorte de legislação do pacote. Não é necessário executar o servidor ou os modelos na máquina local.

Para pesquisar a **base original completa com embeddings**, também há o pacote `python scripts/preparar_multiagentes_kaggle.py --buscador local --destino output/kaggle/multiagentes/buscador-local`. Ele usa `legislacao_artigos_completos.json` no lugar de `corpus_legislacao.json` e exige importar o notebook atualizado. O manifesto seleciona automaticamente esse modo. Veja [BuscadorLocal](buscador_local.md) para instalar/preparar o cache, escolher CPU/GPU e conferir os arquivos. As instruções de recorte e busca lexical abaixo descrevem o modo padrão.

## Preparar os arquivos locais

Na raiz do projeto, execute:

```bash
python3 scripts/preparar_multiagentes_kaggle.py --tema ferias
```

No Windows, use o comando `python` do ambiente do projeto. Esse script monta os arquivos localmente, sem acessar a rede, instalar dependências ou enviar dados ao Kaggle.

Os arquivos ficam em `output/kaggle/multiagentes/`:

| Arquivo | Uso |
|---|---|
| `01_multiagentes_kaggle.ipynb` | Cópia portátil do notebook; importar no editor de notebooks do Kaggle |
| `runtime.zip` | Código Python necessário e requisitos do protótipo |
| `corpus_legislacao.json` | Artigos completos da CLT selecionados da base já preparada no projeto |
| `manifesto_pacote.json` | Inventário, seleção dos artigos, tamanhos e hashes SHA-256 |
| `LEIA_ME.md` | Instruções que acompanham o pacote |

O tema padrão é `ferias`. O empacotador também aceita `noturno`, `jornada` e `todos`. Se escolher outro tema, ajuste a pergunta na primeira célula do notebook para corresponder ao recorte. O manifesto identifica exatamente os artigos e a origem utilizada. O pacote preserva o texto e os metadados da base, incluindo seus alertas; a seleção não constitui uma nova validação de vigência.

O conteúdo de `output/` é gerado e não é versionado. Para reconstruir o pacote após uma alteração no código ou no notebook, execute novamente o empacotador. O notebook versionado permanece em `notebooks/04_multiagentes/`.

## Criar o dataset privado e importar o notebook

1. Entre na sua conta do Kaggle e crie um **dataset privado**.
2. Envie `runtime.zip`, `corpus_legislacao.json`, `manifesto_pacote.json` e `LEIA_ME.md`, mantendo os nomes dos arquivos. Não extraia o ZIP antes do envio.
3. Crie um notebook privado e importe `01_multiagentes_kaggle.ipynb` pelo editor.
4. Adicione o dataset privado como entrada desse notebook. O pacote ficará disponível em `/kaggle/input/`.
5. Nas configurações da sessão, selecione **GPU T4** e habilite **Internet**, necessária para instalar as dependências e baixar os modelos.
6. Execute **Run All** e acompanhe os estados das células.

Esse fluxo é manual e não usa token do Kaggle no notebook. Credenciais do banco, arquivos `.env` e chaves de API não fazem parte do pacote. Mantenha a visibilidade privada também ao salvar uma versão com saídas.

## Configuração e preparação automática

A primeira célula já contém:

```python
EXECUTAR = True
EXECUTAR_DEMO_REVISAO = False
DIRETORIO_DATASET = None
PERGUNTA = "Quais são as regras gerais sobre férias segundo as fontes fornecidas?"
```

O notebook descobre automaticamente um pacote em `/kaggle/input/**`. Se adicionar mais de um pacote, preencha `DIRETORIO_DATASET` com a pasta que contém seu `manifesto_pacote.json`.

Antes de importar o runtime, o notebook confere os tamanhos e hashes de `runtime.zip` e `corpus_legislacao.json`. Também verifica o inventário e os hashes de cada entrada do ZIP. A extração aceita apenas arquivos Python dentro de `src/` e `requirements-multiagentes.txt`, rejeitando caminhos que escapem da pasta, atalhos simbólicos, entradas duplicadas e tipos de arquivo não permitidos. Os hashes detectam divergências em relação ao manifesto; use o pacote produzido pelo projeto como origem.

A preparação instala **LangGraph 1.2.22** no Python do kernel e o **Ollama 0.40.16**, conforme a configuração utilizada pelo projeto. O servidor escuta em `127.0.0.1:11434`. Em seguida, são preparados os modelos, um após o outro:

- Analista: `qwen3:8b-q8_0`;
- Validador: `gemma3:12b`.

O servidor é configurado para um modelo carregado por vez e o cliente envia `keep_alive=0` em cada pedido. Assim, o modelo é descarregado quando o pedido termina. A troca entre modelos envolve carregamento e pode aumentar a duração do atendimento. Os arquivos dos dois modelos continuam ocupando disco na sessão.

As células mostram Python, pip, GPU, LangGraph e versão do servidor Ollama. Não listam variáveis de ambiente nem imprimem credenciais. Os logs ficam em:

- `/kaggle/working/ollama_instalacao.log`;
- `/kaggle/working/ollama.log`;
- `/kaggle/working/ollama_modelos.log`.

## Acompanhar a colaboração

A execução principal usa `modo="corpus"` e `BuscaCorpus(corpus_path)`. Essa ferramenta faz busca lexical com pesos IDF no JSON de legislação, sem depender de PostgreSQL, embeddings ou do índice de jurisprudência. As chamadas aos dois modelos são reais.

O caminho normal contém três chamadas de modelo: planejamento da consulta, redação e validação. Com revisão, contém cinco. Há um limite total de **seis chamadas**, incluindo no máximo **uma tentativa técnica adicional** compartilhada entre as etapas. O timeout por chamada é de **600 segundos** e o limite do atendimento é de **3.600 segundos**; a preparação e o download dos modelos ocorrem antes desse atendimento.

Após a busca, a ordem e o conteúdo das fontes ficam congelados. Há um orçamento de contexto: fontes que não cabem são omitidas por inteiro e registradas em `fontes_omitidas`. A presença de artigos no corpus não garante que todos sejam enviados aos agentes ou que sejam suficientes para responder.

O notebook mostra:

1. Os eventos do Analista, ferramenta, guardrails, Validador e orquestrador.
2. O rascunho original, o candidato após os controles e o feedback de cada versão.
3. A revisão, quando efetivamente solicitada, e sua nova validação.
4. O status, o motivo do encerramento e a resposta final.

| Status | Significado no protótipo |
|---|---|
| `aprovada` | Validador e controles permitiram liberar o candidato |
| `limitada` | Evidência insuficiente, reprovação persistente ou outro limite de liberação |
| `resposta_fixa` | A entrada foi encaminhada para uma resposta prevista, sem chamadas desnecessárias aos agentes |
| `falha_tecnica` | O atendimento não pôde ser concluído por problema técnico |

O Validador não recebe resposta-ouro durante esse atendimento. Um status `aprovada` não certifica correção jurídica. Uma revisão natural pode ocorrer, mas o notebook não a força no modo corpus.

## Demonstração opcional de revisão controlada

Para uma segunda execução, altere `EXECUTAR_DEMO_REVISAO = True`. Ela usa `BuscaSintetica`, uma pergunta sobre o material fictício e `modo="sintetico"`, separadamente do atendimento com a CLT.

O mecanismo de teste substitui uma citação do primeiro candidato por `[Fonte 99]` e registra `falha_injetada=true`. O rascunho original é preservado. Os dois agentes continuam sendo os modelos configurados: o feedback e a revisão dependem das respostas que eles produzirem. Se o Analista declarar insuficiência antes da preparação do candidato, a execução termina sem inserir a falha.

Esse caso demonstra o tratamento de um erro deliberado. Ele não deve ser apresentado como erro espontâneo nem como medida da frequência natural de erros. A injeção é proibida nos modos corpus e real.

## Baixar e conferir os resultados

Os resultados são gravados em `/kaggle/working/multiagentes/<run_id>/`. Cada execução contém:

- `estado.json`: entrada sanitizada, fontes congeladas, versões, feedback, decisões, contadores e resumo do ambiente;
- `eventos.jsonl`: sequência de ações observadas;
- `fontes.json`: snapshot das fontes utilizadas;
- `resposta.txt`: resposta final efetivamente liberada ou mensagem de limitação/falha;
- `grafo.mmd`: diagrama Mermaid do fluxo;
- `manifesto.json`: versões e hashes dos artefatos exportados.

A última célula cria `/kaggle/working/multiagentes_resultados.zip`. Baixe esse arquivo pela área de saídas do notebook. Confira o status e os artefatos antes de apresentar o resultado; uma falha técnica ou resposta limitada também deve ser registrada como tal. Se a inicialização ou exportação falhar, o notebook tenta registrar `erro_execucao.json` com a etapa e o tipo de erro, sem expor o conteúdo das exceções.

## Quando a execução não avançar

| Situação | Próximo passo |
|---|---|
| Pacote não encontrado | Adicione o dataset ao notebook e confira os nomes dos três arquivos obrigatórios |
| Mais de um pacote encontrado | Defina `DIRETORIO_DATASET` na configuração |
| Hash ou inventário divergente | Recrie o pacote local e envie os arquivos correspondentes à mesma versão |
| GPU ausente | Habilite GPU T4 na sessão antes de executar novamente |
| Instalação ou download interrompido | Confira Internet, espaço disponível e os logs em `/kaggle/working/` |
| Outra versão do Ollama já ativa | Reinicie a sessão e execute o notebook desde o início |
| `falha_tecnica` após iniciar os agentes | Confira motivo, eventos e logs; o orçamento inclui tentativas com erro |
| `limitada` sem resposta jurídica | Confira as fontes selecionadas, omissões e feedback; não trate a limitação como aprovação |

O uso depende da disponibilidade e dos limites aplicáveis à conta e à sessão do Kaggle. Este roteiro não promete disponibilidade de GPU, duração de sessão ou resultado dos modelos. O pacote portátil cobre a legislação selecionada; a recuperação conjunta com jurisprudência permanece no fluxo do projeto que usa o banco provisionado.
