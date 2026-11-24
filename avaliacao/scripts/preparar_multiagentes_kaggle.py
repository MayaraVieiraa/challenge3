"""Prepara um pacote local do protótipo para a GPU do Kaggle, sem acessar a rede.

Usa somente código permitido e artigos completos já existentes na base.
Não envia arquivos, não lê credenciais e não instala dependências.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import re
import sys
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from worker.evidencia.explicador import fonte_para_prompt


BASE_RELATIVA = Path('dados/processed/legislacao/legislacao_artigos_completos.json')
BASE_RELATIVA_DADOS = Path('dados/processed/legislacao/legislacao_artigos_completos.json')
NOTEBOOK_RELATIVO = Path('avaliacao/notebooks/04_multiagentes/02_execucao_kaggle_multiagentes.ipynb')
NOTEBOOK_PACOTE = '01_multiagentes_kaggle.ipynb'
CLT_CAMINHO = 'codigos/consolidacao-das-leis-do-trabalho-clt-del-5452-1943.md'
TEMAS = ('ferias', 'noturno', 'jornada', 'todos')
MAX_ARTIGOS = 80
MAX_BYTES_CORPUS = 256000
MAX_ARTIGOS_LOCAL = 20000
MAX_BYTES_CORPUS_LOCAL = 32 * 1024 * 1024
VERSAO_PACOTE = 'multiagentes-kaggle-v1'
_ARTIGO = re.compile(r'Art\.?\s*(\d+)[ºo°]?(?:-([A-Z]))?\.?', re.IGNORECASE)
# Runtime modules and versioned precedent catalogue required by multiagentes-v3.
_INTEGRACAO = ('__init__.py', 'context_window.py', 'explicador.py', 'guardas.py', 'prompt_juridico.py',
               'prompts.py', 'situacao_precedentes.json', 'stracting.py')


def _json_bytes(valor):
    return (json.dumps(valor, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + '\n').encode('utf-8')


def _identidade(dados):
    return {'sha256': sha256(dados).hexdigest(), 'bytes': len(dados)}


def _ler_arquivo_permitido(relativo):
    caminho = ROOT / relativo
    if caminho.is_symlink() or not caminho.is_file():
        raise ValueError(f'Arquivo obrigatório ausente ou não regular: {relativo.as_posix()}')
    # Não seguir atalhos de diretórios para fora do repositório.
    try:
        caminho.resolve().relative_to(ROOT.resolve())
    except ValueError:
        raise ValueError(f'Arquivo fora do repositório: {relativo.as_posix()}') from None
    return caminho.read_bytes()


def _numero_artigo(registro):
    identificador = registro.get('identificador_artigo')
    if not isinstance(identificador, str):
        return None
    m = _ARTIGO.fullmatch(identificador.strip())
    return (int(m.group(1)), (m.group(2) or '').upper()) if m else None


def _pertence_ao_tema(numero, tema):
    base, sufixo = numero
    ferias = 129 <= base <= 153
    jornada = 58 <= base <= 75
    if tema == 'ferias':
        return ferias
    if tema == 'noturno':
        return base == 73 and not sufixo
    if tema == 'jornada':
        return jornada
    return ferias or jornada or (not sufixo and base in (392, 473, 477, 487))


def _selecionar_corpus(dados_base, tema):
    try:
        registros = json.loads(dados_base)
    except (ValueError, UnicodeError):
        raise ValueError('A base de artigos não contém JSON válido.') from None
    if not isinstance(registros, list):
        raise ValueError('A base de artigos deve ser uma lista de registros.')
    selecionados = []
    for registro in registros:
        if not isinstance(registro, dict):
            raise ValueError('A base contém um registro diferente de objeto JSON.')
        if registro.get('caminho_relativo') != CLT_CAMINHO:
            continue
        numero = _numero_artigo(registro)
        if numero is not None and _pertence_ao_tema(numero, tema):
            selecionados.append((numero, registro))
    if not selecionados:
        raise ValueError(f'Nenhum artigo da CLT encontrado para o tema {tema}.')
    if len(selecionados) > MAX_ARTIGOS:
        raise ValueError(f'O recorte excede o limite de {MAX_ARTIGOS} artigos; nenhum texto foi cortado.')
    selecionados.sort(key=lambda item: item[0])
    corpus, unidades = [], set()
    for _, registro in selecionados:
        unidade = registro.get('artigo_id')
        texto = registro.get('texto_artigo_completo')
        if not isinstance(unidade, str) or not unidade.strip():
            raise ValueError('Artigo selecionado sem identificador estável.')
        if unidade in unidades:
            raise ValueError('A seleção contém identificadores de artigo duplicados.')
        if not isinstance(texto, str) or not texto.strip():
            raise ValueError('Artigo selecionado sem texto completo; nenhum conteúdo foi inventado.')
        unidades.add(unidade)
        metadata = {
            'caminho_relativo': registro['caminho_relativo'],
            'artigo_ref': registro['identificador_artigo'],
            'contexto': registro.get('caminho_hierarquico'),
            'status_declarado': registro.get('status_declarado'),
        }
        fonte = fonte_para_prompt({'fonte': 'legislacao', 'unidade': unidade,
                                   'texto': texto, 'metadata': metadata})
        # Preservar proveniência e alertas existentes, sem certificar vigência.
        for campo in ('source', 'sha256_fonte', 'date', 'retrieved', 'tem_alerta_parser'):
            if campo in registro:
                fonte[campo] = registro[campo]
        corpus.append(fonte)
    dados_corpus = _json_bytes(corpus)
    if len(dados_corpus) > MAX_BYTES_CORPUS:
        raise ValueError(f'O corpus excede {MAX_BYTES_CORPUS} bytes; nenhum artigo foi truncado.')
    return corpus, dados_corpus


def _corpus_local(dados_base):
    """Confere o esquema original sem alterar texto, ordem ou metadados."""
    if len(dados_base) > MAX_BYTES_CORPUS_LOCAL:
        raise ValueError('A base completa excede o limite de 32 MiB do pacote local.')
    try:
        registros = json.loads(dados_base)
    except (ValueError, UnicodeError):
        raise ValueError('A base de artigos não contém JSON válido.') from None
    if not isinstance(registros, list) or not registros:
        raise ValueError('A base completa deve ser uma lista não vazia de artigos.')
    if len(registros) > MAX_ARTIGOS_LOCAL:
        raise ValueError('A base completa excede o limite de artigos do pacote local.')
    unidades, selecao = set(), []
    for registro in registros:
        if not isinstance(registro, dict):
            raise ValueError('A base contém um registro diferente de objeto JSON.')
        unidade = registro.get('artigo_id')
        texto = registro.get('texto_artigo_completo')
        if not isinstance(unidade, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:/#-]{0,255}', unidade):
            raise ValueError('Artigo da base completa sem identificador válido.')
        if unidade in unidades:
            raise ValueError('A base completa contém identificadores de artigo duplicados.')
        if not isinstance(texto, str) or not texto.strip():
            raise ValueError('Artigo da base completa sem texto completo.')
        for campo in ('identificador_artigo', 'caminho_relativo', 'caminho_hierarquico',
                      'status_declarado', 'source', 'date', 'retrieved', 'sha256_fonte'):
            if registro.get(campo) is not None and not isinstance(registro[campo], str):
                raise ValueError('Metadado textual inválido na base completa.')
        if registro.get('tem_alerta_parser') is not None and type(registro['tem_alerta_parser']) is not bool:
            raise ValueError('Alerta de parser inválido na base completa.')
        unidades.add(unidade)
        selecao.append({'unidade': unidade, 'artigo_ref': registro.get('identificador_artigo'),
                        'sha256_conteudo': sha256(texto.encode('utf-8')).hexdigest()})
    return selecao


def _runtime(incluir_buscador_local=False):
    pasta = ROOT / 'worker/evidencia/langgraph'
    if not pasta.is_dir() or pasta.is_symlink():
        raise ValueError('Diretório worker/evidencia/langgraph ausente ou não regular.')
    relativos = sorted(p.relative_to(ROOT) for p in pasta.glob('*.py'))
    if not relativos or Path('worker/evidencia/langgraph/__init__.py') not in relativos:
        raise ValueError('Pacote worker/evidencia/langgraph incompleto: falta __init__.py.')
    relativos += [Path('worker/evidencia') / nome for nome in _INTEGRACAO]
    relativos += [Path('docs/legado/requirements/requirements-multiagentes.txt')]
    if incluir_buscador_local:
        relativos += [Path('docs/legado/requirements/requirements-buscador-local.txt')]
    arquivos = {p.as_posix(): _ler_arquivo_permitido(p) for p in sorted(relativos)}
    buffer = BytesIO()
    with ZipFile(buffer, 'w', compression=ZIP_DEFLATED, compresslevel=9) as pacote:
        for nome, conteudo in arquivos.items():
            # Metadados fixos evitam variar o hash apenas por horário/permissão local.
            info = ZipInfo(nome, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            pacote.writestr(info, conteudo)
    return buffer.getvalue(), {nome: _identidade(dados) for nome, dados in arquivos.items()}


def _leia_me(tema, quantidade):
    return f'''# Pacote local de multiagentes para o Kaggle

Tema: **{tema}**. Recorte de **{quantidade} artigos completos da CLT** da base já processada no projeto.
Os textos foram copiados integralmente; os metadados de origem, status declarado e alertas foram preservados.
Este recorte não inclui jurisprudência nem reproduz o índice PostgreSQL/pgvector.

1. Crie um dataset **privado** no Kaggle com `runtime.zip`, `corpus_legislacao.json`,
   `manifesto_pacote.json` e este `LEIA_ME.md`. O preparo local não faz upload.
2. Importe `{NOTEBOOK_PACOTE}` como notebook no editor do Kaggle, em vez de tratá-lo como script Python.
3. Selecione uma GPU disponível, habilite internet para instalar dependências e baixar Qwen/Gemma,
   e anexe o dataset privado. Execute as células em ordem.
4. O notebook confere os hashes, extrai o runtime e executa os agentes com `BuscaCorpus` no modo `corpus`.
   Os modelos são carregados sequencialmente. A execução pode encerrar com limitação quando faltar evidência.
5. Baixe os resultados da execução. Não confunda o pacote preparado com uma execução dos modelos concluída.

O runtime contém somente módulos Python permitidos e o arquivo de dependências. Não inclui credenciais,
arquivos `.env`, caches, volumes de banco, perguntas protegidas ou decisões judiciais.
O manifesto registra o hash da base local e dos artefatos; sua validação verifica integridade, não autenticidade
da legislação nem vigência atual. Não publique as evidências de atendimento com dados pessoais.

Instruções completas: `docs/execucao_multiagentes_kaggle.md` no repositório.
'''.encode('utf-8')


def _leia_me_local(quantidade):
    return f'''# Pacote de busca semântica local para o Kaggle

Base completa disponível: **{quantidade} artigos**, no esquema original do JSON de legislação.
O arquivo foi copiado integralmente, com os metadados e alertas existentes. Não inclui jurisprudência.

1. Crie ou atualize um dataset **privado** com `runtime.zip`, `legislacao_artigos_completos.json`,
   `manifesto_pacote.json` e este `LEIA_ME.md`. Não misture arquivos de versões diferentes.
2. Importe `{NOTEBOOK_PACOTE}` como notebook e anexe apenas o pacote que deseja executar.
3. Habilite Internet e GPU T4 para Qwen/Gemma. O notebook detecta `modo=local` no manifesto.
4. O BuscadorLocal usa BGE-M3 em CPU por padrão. A primeira indexação baixa o modelo e gera embeddings;
   ela pode demorar e acontece antes do atendimento. O cache fica em
   `/kaggle/working/dados/output/buscador_local/` e é reutilizado dentro da mesma sessão.
5. Altere PERGUNTA, execute as células em ordem e confira as fontes, o status e os resultados exportados.
   Para outra sessão, o cache deve ser restaurado no mesmo diretório para evitar recalcular os artigos.

O runtime contém apenas código permitido e dependências. Não inclui caches, credenciais ou banco.
O manifesto confere integridade; não certifica vigência, pertinência ou correção jurídica das fontes.
Fontes completas são selecionadas pelo orçamento de contexto; nem todo artigo recuperado cabe no prompt.
O limiar de similaridade é heurístico e deve ser avaliado com perguntas revisadas pela equipe.

Instruções completas: `docs/buscador_local.md` no repositório.
'''.encode('utf-8')


def preparar_pacote(destino=None, tema='ferias', *, buscador='lexical') -> Path:
    """Monta os artefatos e retorna a pasta; nenhum upload ou inferência é realizado."""
    if tema not in TEMAS:
        raise ValueError('Tema deve ser ferias, noturno, jornada ou todos.')
    if buscador not in ('lexical', 'local'):
        raise ValueError('Buscador deve ser lexical ou local.')
    destino = Path(destino) if destino is not None else ROOT / 'dados/output/kaggle/multiagentes'
    destino = destino.resolve()
    base_relativa = BASE_RELATIVA_DADOS if (ROOT / BASE_RELATIVA_DADOS).exists() else BASE_RELATIVA
    base = _ler_arquivo_permitido(base_relativa)
    if buscador == 'local':
        selecao = _corpus_local(base)
        dados_corpus = base
        nome_corpus = 'legislacao_artigos_completos.json'
        modo, tema_pacote, norma = 'local', 'base_completa', None
        leia_me = _leia_me_local(len(selecao))
    else:
        corpus, dados_corpus = _selecionar_corpus(base, tema)
        selecao = [{'unidade': f['unidade'], 'artigo_ref': f['artigo_ref'],
                    'sha256_conteudo': sha256(f['conteudo'].encode('utf-8')).hexdigest()} for f in corpus]
        nome_corpus = 'corpus_legislacao.json'
        modo, tema_pacote, norma = 'corpus', tema, CLT_CAMINHO
        leia_me = _leia_me(tema, len(corpus))
    runtime, inventario = _runtime(incluir_buscador_local=buscador == 'local')
    notebook = _ler_arquivo_permitido(NOTEBOOK_RELATIVO)
    try:
        conteudo_notebook = json.loads(notebook)
    except (ValueError, UnicodeError):
        raise ValueError('O notebook versionado não contém JSON válido.') from None
    if (not isinstance(conteudo_notebook, dict) or conteudo_notebook.get('nbformat') != 4
            or not isinstance(conteudo_notebook.get('cells'), list)):
        raise ValueError('O notebook versionado não está no formato Jupyter esperado.')
    artefatos = {
        'runtime.zip': runtime,
        nome_corpus: dados_corpus,
        NOTEBOOK_PACOTE: notebook,
        'LEIA_ME.md': leia_me,
    }
    manifesto = {
        'versao_pacote': VERSAO_PACOTE,
        'modo': modo,
        'tema': tema_pacote,
        'base': {'caminho_relativo': base_relativa.as_posix(), **_identidade(base)},
        'selecao': {
            'norma': norma,
            'quantidade_artigos': len(selecao),
            'artigos': selecao,
        },
        'runtime': {'arquivos': inventario},
        'notebook_origem': NOTEBOOK_RELATIVO.as_posix(),
        'arquivos': {nome: _identidade(dados) for nome, dados in artefatos.items()},
    }
    # Todas as validações acontecem antes de criar ou substituir os artefatos.
    destino.mkdir(parents=True, exist_ok=True)
    for nome, dados in artefatos.items():
        caminho = destino / nome
        if caminho.is_symlink():
            raise ValueError(f'O destino contém um atalho não permitido: {nome}')
        caminho.write_bytes(dados)
    manifesto_path = destino / 'manifesto_pacote.json'
    if manifesto_path.is_symlink():
        raise ValueError('O destino do manifesto é um atalho não permitido.')
    manifesto_path.write_bytes(_json_bytes(manifesto))
    return destino


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destino', type=Path, default=None, help='Pasta dos artefatos locais.')
    parser.add_argument('--tema', choices=TEMAS, default='ferias', help='Recorte dos artigos da CLT.')
    parser.add_argument('--buscador', choices=('lexical', 'local'), default='lexical',
                        help='local inclui a base completa e embeddings; lexical usa o recorte de --tema.')
    args = parser.parse_args(argv)
    try:
        destino = preparar_pacote(args.destino, args.tema, buscador=args.buscador)
    except (OSError, ValueError) as erro:
        parser.exit(2, f'Não foi possível preparar o pacote: {erro}\n')
    print(f'Pacote preparado em {destino}. Nenhum arquivo foi enviado ao Kaggle.')


if __name__ == '__main__':
    main()
