# BuscadorLocal — legislação com embeddings em cache

O `BuscadorLocal` pesquisa os artigos do JSON original de legislação e entrega fontes no mesmo formato usado pelo Analista e pelo Validador. Ele consulta a base disponível inteira, em vez de depender do recorte de férias. A saída continua sujeita aos limites de contexto e à validação dos agentes.

## Arquivos e responsabilidades

- `src/multiagentes/buscador_local.py`: leitura da base, backend de embeddings, cache persistido e ranking por similaridade.
- `scripts/consultar_buscador_local.py`: preparação do índice e consulta isolada, sem executar os modelos de linguagem.
- `scripts/executar_multiagentes.py --modo local`: integração da busca semântica com os agentes.
- `scripts/preparar_multiagentes_kaggle.py --buscador local`: pacote da base original e código para o Kaggle.
- `requirements-buscador-local.txt`: dependência opcional de Sentence Transformers; os testes com fakes não precisam instalá-la.

## Base original e DVC

Sem `--corpus`, o buscador procura primeiro:

```text
dados/processed/legislacao/legislacao_artigos_completos.json
```

Neste checkout, o arquivo disponível fica no caminho alternativo:

```text
data/processed/legislacao/legislacao_artigos_completos.json
```

O segundo caminho é utilizado quando o primeiro está ausente. Para escolher explicitamente outra cópia, informe `--corpus /caminho/legislacao_artigos_completos.json`.

A entrada é uma lista no esquema original, com `artigo_id` e `texto_artigo_completo`; os metadados disponíveis, como `identificador_artigo`, `caminho_relativo`, `source`, `date` e `retrieved`, são preservados nas fontes. O texto de cada artigo é devolvido integralmente, sem criar referências ou datas ausentes.

Se a branch da equipe já tiver DVC e o remoto configurados, obtenha a base com `dvc pull` antes da execução. Este checkout não fornece uma configuração de remoto DVC: o buscador lê a base local e informa a ausência do arquivo; não instala DVC nem tenta baixar dados por conta própria.

## Instalação e primeira indexação

Na raiz do projeto:

```bash
source .venv/bin/activate
python -m pip install -r requirements-buscador-local.txt
python scripts/consultar_buscador_local.py --preparar-indice
```

O backend real utiliza `BAAI/bge-m3`, revisão `5617a9f61b028005a4858fdac845db406aefb181`, com vetores de 1.024 dimensões. O carregamento é tardio: importar o módulo ou consultar um cache já pronto sem gerar uma consulta não carrega o modelo. A primeira indexação pode baixar o modelo e consome tempo de processamento. A execução padrão usa CPU; `--device-embeddings cuda` ou `mps` seleciona outro dispositivo quando disponível no ambiente.

O código usa a API de [SentenceTransformer](https://sbert.net/docs/package_reference/sentence_transformer/model.html); as características do modelo estão na [documentação do BGE-M3](https://huggingface.co/BAAI/bge-m3). A faixa da dependência está declarada no arquivo de requisitos; a versão efetivamente instalada deve ser registrada na execução real.

## Conferir o reaproveitamento do cache

Execute a preparação duas vezes, em processos separados:

```bash
python scripts/consultar_buscador_local.py --preparar-indice
python scripts/consultar_buscador_local.py --preparar-indice
```

Na primeira criação, o diagnóstico informa `cache_reutilizado: false`. Na segunda, com o mesmo corpus e configuração, informa `cache_reutilizado: true`. Os embeddings dos artigos não são recalculados nessa segunda abertura. Uma consulta nova ainda precisa de seu próprio embedding.

O diretório padrão é:

```text
dados/output/buscador_local/
```

Use `--cache-embeddings /outro/diretorio` para alterar o destino. O cache é SQLite, com vetores numéricos, metadados de identidade e verificações de integridade; não utiliza pickle. Sua identidade depende da base, do modelo/revisão, da dimensão e da configuração de processamento. Mudanças nesses itens geram outro índice. Um arquivo incompleto ou inconsistente é reconstruído antes de ser utilizado; a gravação substitui o arquivo somente após concluir o novo índice.

Cada instância trabalha com um snapshot carregado. Para refletir uma alteração no JSON feita durante o processo, feche o buscador e abra outra instância. Os arquivos antigos de cache podem continuar no diretório, mas não são escolhidos para uma identidade diferente.

## Fazer uma consulta sem os agentes

```bash
python scripts/consultar_buscador_local.py \
  --pergunta "Como funciona o adicional noturno no trabalho urbano?"
```

O JSON de saída mostra o diagnóstico, os identificadores, as referências, os metadados disponíveis e os escores. O texto completo aparece somente com `--mostrar-texto`.

```bash
python scripts/consultar_buscador_local.py \
  --pergunta "Quais fontes tratam da jornada de trabalho?" \
  --top-k 4 --score-minimo 0.35 --mostrar-texto
```

O ranking usa similaridade de cosseno. O limiar padrão `0.35` é uma heurística inicial, não uma medida de validade jurídica nem um detector garantido de falta de evidência. Ajustá-lo exige avaliar perguntas e fontes esperadas, revisadas pela equipe. Mesmo com um escore alto, o conteúdo pode ser insuficiente para a pergunta; o Validador continua necessário.

O buscador retorna no máximo seis artigos. Na integração, o orquestrador seleciona fontes completas dentro do orçamento de contexto; artigos longos podem ser omitidos por inteiro e essa omissão é registrada. Recuperação na base inteira não significa enviar a base inteira ao modelo.

## Executar com os agentes

Com as dependências de LangGraph instaladas, Ollama disponível e os modelos Qwen/Gemma preparados:

```bash
python scripts/executar_multiagentes.py --modo local \
  --pergunta "Como funciona o adicional noturno no trabalho urbano?"
```

É possível informar `--corpus`, `--cache-embeddings` e `--device-embeddings`. Os agentes recebem somente as fontes recuperadas e selecionadas. A ferramenta semântica não altera o número de agentes, não adiciona uma volta para Pesquisa e não cria um fluxo de jurisprudência. Esses itens continuam sendo tarefas separadas da arquitetura da equipe.

## Executar no Kaggle

Gere um pacote separado para preservar o pacote lexical anterior:

```bash
python scripts/preparar_multiagentes_kaggle.py --buscador local \
  --destino output/kaggle/multiagentes/buscador-local
```

Esse modo inclui a base original completa, sem o filtro de tema. A opção `--tema` pertence ao modo lexical e não restringe a base quando `--buscador local` é selecionado.

Envie os quatro arquivos do pacote para um dataset privado:

```text
runtime.zip
legislacao_artigos_completos.json
manifesto_pacote.json
LEIA_ME.md
```

Importe também a cópia `01_multiagentes_kaggle.ipynb` no editor do Kaggle. Use a cópia atualizada: uma versão anterior do notebook aceita apenas o formato lexical. Anexe o dataset atualizado, selecione GPU T4 e habilite Internet. Se houver vários pacotes anexados, preencha `DIRETORIO_DATASET` na primeira célula de código.

O notebook detecta `modo: local` pelo manifesto, confere os hashes e o inventário, e aceita tanto `runtime.zip` quanto a pasta `runtime/` expandida automaticamente pelo Kaggle. Instala a dependência extra apenas nesse modo. A configuração padrão mantém o BGE-M3 em CPU, separado da memória de GPU de Qwen/Gemma.

Para indexar na GPU, configure `DISPOSITIVO_EMBEDDINGS = "cuda"` na primeira célula de código. `BATCH_SIZE_EMBEDDINGS = 2` limita o lote para reduzir o pico de memória dos artigos longos; a indexação acontece antes do atendimento, mas o modelo de embeddings também será usado para a consulta. O cache é reutilizado automaticamente quando a identidade coincide; não é necessário habilitar um flag de reutilização.

A preparação do índice acontece antes do atendimento, fora do orçamento de tempo dos agentes. Ela pode demorar na primeira execução. O diagnóstico é exibido e registrado em `ambiente_kaggle.buscador_local`. Mudar a pergunta e executar novamente na mesma sessão reutiliza os embeddings dos artigos, desde que a base e a configuração sejam as mesmas.

As saídas incluem:

- `multiagentes_resultados.zip`: estados, fontes, decisões, resposta final e manifestos dos atendimentos.
- `buscador_local_cache.zip`: cópia separada do cache de artigos, para restaurar em outra sessão.

Para restaurar o cache, copie seu conteúdo para `/kaggle/working/dados/output/buscador_local/` antes da preparação. A verificação da identidade e dos vetores continua obrigatória. O cache e os modelos baixados são artefatos diferentes; restaurar apenas o cache não evita carregar ou baixar o modelo necessário para uma nova pergunta.

O modo padrão do empacotador continua sendo lexical, com `--tema ferias`, `noturno`, `jornada` ou `todos`. A documentação das execuções anteriores continua descrevendo esses resultados históricos; ela não comprova uma execução real do novo backend.

## Testes e evidências

```bash
python -m unittest discover -s tests -p "test_buscador_local*.py" -v
python -m unittest discover -s tests -p "test_multiagentes*.py" -v
```

Os testes usam embeddings fake controlados para verificar criação e reutilização do cache entre instâncias, invalidação, ranking, rejeição de vetores inválidos, preservação dos metadados e integração. Os testes Kaggle verificam empacotamento, compatibilidade com o modo lexical e bootstrap de integridade sem instalar modelos ou executar uma GPU.

Verificação local em 19/11/2026: **151 testes aprovados** — 52 do buscador/CLIs/pacote, 68 multiagentes, 28 dos guardrails e 3 do juiz anterior. A leitura da base original também foi conferida: 5.284 artigos em 25 arquivos de normas, SHA-256 `5e6d7dd4e275b72b64707a0fdf93cbdfe19b04baec3931847f77cf22b8eb7dcb`.

Esses testes comprovam comportamento do código. A qualidade do ranking com BGE-M3 precisa de uma execução com o backend real e avaliação das fontes recuperadas. O JSON de legislação pode conter artigos revogados e normas de outros ramos: os metadados são preservados, o escopo trabalhista dos agentes permanece e não há certificação automática de vigência.

Para concluir a issue da equipe, ainda é necessário revisar o recorte de jurisprudência e os dados pessoais do material da demo, conferir a integração na branch de entrega, registrar revisão pelo par e verificar o CI do commit apresentado.
