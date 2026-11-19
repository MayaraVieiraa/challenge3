"""Cliente Ollama sem dependências externas para o protótipo de dois agentes.

Uma chamada corresponde a uma única tentativa. O orquestrador controla o orçamento;
o cliente não repete pedidos nem registra prompts ou conteúdo de erros HTTP.
"""
from __future__ import annotations

import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request


class ErroLLM(RuntimeError):
    """Falha resumida que pode ser registrada sem expor a entrada do modelo."""

    def __init__(self, mensagem: str, *, retryable: bool = False):
        super().__init__(mensagem)
        self.retryable = retryable


def _validar_schema(valor, schema):
    """Valida o subconjunto de JSON Schema usado pelos contratos do protótipo."""
    if isinstance(schema, bool):
        if not schema:
            raise ValueError('schema recusou o valor')
        return
    if not isinstance(schema, dict):
        raise ValueError('schema inválido')
    permitidos = {'type', 'properties', 'required', 'additionalProperties', 'items', 'enum',
                  'minLength', 'maxLength', 'minimum', 'maximum', 'minItems', 'maxItems',
                  'description', 'title', '$schema'}
    if set(schema) - permitidos:
        raise ValueError('restrição de schema não suportada')
    tipos = {
        'object': lambda v: isinstance(v, dict),
        'array': lambda v: isinstance(v, list),
        'string': lambda v: isinstance(v, str),
        'integer': lambda v: type(v) is int,
        'number': lambda v: type(v) in (int, float) and math.isfinite(v),
        'boolean': lambda v: type(v) is bool,
        'null': lambda v: v is None,
    }
    tipo = schema.get('type')
    if tipo is not None:
        lista = tipo if isinstance(tipo, list) else [tipo]
        if not lista or any(t not in tipos for t in lista) or not any(tipos[t](valor) for t in lista):
            raise ValueError('tipo incompatível')
    if 'enum' in schema:
        # bool não é um número em JSON Schema, embora True == 1 em Python.
        if not any(valor == opcao and isinstance(valor, bool) == isinstance(opcao, bool)
                   for opcao in schema['enum']):
            raise ValueError('valor fora do enum')
    if isinstance(valor, dict):
        propriedades = schema.get('properties', {})
        if any(c not in valor for c in schema.get('required', [])):
            raise ValueError('campo obrigatório ausente')
        adicionais = schema.get('additionalProperties', True)
        for chave, conteudo in valor.items():
            if chave in propriedades:
                _validar_schema(conteudo, propriedades[chave])
            elif adicionais is False:
                raise ValueError('campo adicional')
            elif isinstance(adicionais, dict):
                _validar_schema(conteudo, adicionais)
    if isinstance(valor, list):
        if len(valor) < schema.get('minItems', 0) or len(valor) > schema.get('maxItems', math.inf):
            raise ValueError('tamanho de lista incompatível')
        for item in valor:
            _validar_schema(item, schema.get('items', True))
    if isinstance(valor, str):
        if len(valor) < schema.get('minLength', 0) or len(valor) > schema.get('maxLength', math.inf):
            raise ValueError('tamanho de texto incompatível')
    if type(valor) in (int, float):
        if not math.isfinite(valor) or valor < schema.get('minimum', -math.inf) or valor > schema.get('maximum', math.inf):
            raise ValueError('número incompatível')


def _json_estrito(texto):
    def rejeitar_constante(_):
        raise ValueError('constante JSON inválida')

    def sem_chaves_duplicadas(pares):
        resultado = {}
        for chave, valor in pares:
            if chave in resultado:
                raise ValueError('chave JSON duplicada')
            resultado[chave] = valor
        return resultado

    return json.loads(texto, parse_constant=rejeitar_constante, object_pairs_hook=sem_chaves_duplicadas)


def _timeout_valido(timeout):
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise ErroLLM('O timeout do modelo deve ser um número positivo.')
    return timeout


class ClienteOllama:
    def __init__(self, url='http://127.0.0.1:11434', timeout=180):
        try:
            partes = urllib.parse.urlsplit(url)
            valido = (partes.scheme in ('http', 'https') and partes.hostname and partes.port != 0
                      and partes.username is None and partes.password is None
                      and not partes.query and not partes.fragment)
        except (TypeError, ValueError, AttributeError):
            valido = False
        if not valido:
            raise ErroLLM('Configure uma URL HTTP ou HTTPS do Ollama sem credenciais, consulta ou fragmento.')
        self.url = url.rstrip('/') + '/api/chat'
        self.timeout = _timeout_valido(timeout)

    def gerar(self, *, modelo, mensagens, schema, opcoes, think=None, timeout=None):
        prazo = self.timeout if timeout is None else _timeout_valido(timeout)
        if not isinstance(modelo, str) or not modelo.strip() or not isinstance(mensagens, list):
            raise ErroLLM('Parâmetros inválidos para a chamada do modelo.')
        if (not isinstance(schema, dict) or not isinstance(opcoes, dict)
                or (think is not None and type(think) is not bool)):
            raise ErroLLM('Parâmetros inválidos para a chamada do modelo.')
        corpo = dict(model=modelo, messages=mensagens, stream=False, format=schema,
                     options=dict(opcoes, temperature=0), keep_alive=0)
        if think is not None:
            corpo['think'] = think
        try:
            dados_pedido = json.dumps(corpo, ensure_ascii=False, allow_nan=False).encode('utf-8')
            pedido = urllib.request.Request(self.url, dados_pedido, {'Content-Type': 'application/json'}, method='POST')
        except (TypeError, ValueError):
            raise ErroLLM('Não foi possível codificar os parâmetros da chamada do modelo.') from None
        inicio = time.monotonic()
        try:
            with urllib.request.urlopen(pedido, timeout=prazo) as resposta:
                status = getattr(resposta, 'status', 200)
                if status != 200:
                    raise ErroLLM(f'Ollama respondeu com HTTP {status}.', retryable=status == 429 or status >= 500)
                recebido = _json_estrito(resposta.read())
        except urllib.error.HTTPError as erro:
            codigo = erro.code
            erro.close()
            raise ErroLLM(f'Ollama respondeu com HTTP {codigo}.',
                          retryable=codigo == 429 or codigo >= 500) from None
        except (TimeoutError, urllib.error.URLError, OSError):
            raise ErroLLM('Não foi possível concluir a chamada ao Ollama no tempo disponível.', retryable=True) from None
        except (ValueError, UnicodeError):
            raise ErroLLM('Ollama devolveu uma resposta HTTP com JSON inválido.') from None
        if not isinstance(recebido, dict) or recebido.get('error') or recebido.get('done') is not True:
            raise ErroLLM('Ollama não devolveu uma resposta concluída válida.')
        if recebido.get('done_reason') == 'length':
            raise ErroLLM('A resposta do modelo foi cortada pelo limite de tokens.')
        if recebido.get('done_reason') not in (None, 'stop'):
            raise ErroLLM('O modelo encerrou a resposta por um motivo não suportado.')
        mensagem = recebido.get('message')
        if not isinstance(mensagem, dict) or mensagem.get('role') != 'assistant' or mensagem.get('tool_calls'):
            raise ErroLLM('Ollama devolveu uma mensagem inválida para o contrato do agente.')
        conteudo = mensagem.get('content')
        if not isinstance(conteudo, str) or not conteudo.strip():
            raise ErroLLM('Ollama devolveu uma mensagem vazia ou inválida.')
        if mensagem.get('thinking') or '<think' in conteudo.lower() or '</think' in conteudo.lower():
            raise ErroLLM('A resposta contém raciocínio interno e foi recusada.')
        try:
            dados = _json_estrito(conteudo)
        except (ValueError, UnicodeError):
            raise ErroLLM('O modelo devolveu conteúdo que não é JSON válido.', retryable=True) from None
        if not isinstance(dados, dict):
            raise ErroLLM('O modelo deve devolver um objeto JSON.', retryable=True)
        try:
            _validar_schema(dados, schema)
        except (ValueError, TypeError, KeyError):
            raise ErroLLM('A resposta do modelo não atende ao esquema JSON solicitado.', retryable=True) from None
        uso = {}
        for destino, origem in (('tokens_entrada', 'prompt_eval_count'), ('tokens_saida', 'eval_count')):
            numero = recebido.get(origem, 0)
            if type(numero) is not int or numero < 0:
                raise ErroLLM('Ollama devolveu contagens de tokens inválidas.')
            uso[destino] = numero
        modelo_retornado = recebido.get('model', modelo)
        if not isinstance(modelo_retornado, str) or not modelo_retornado.strip():
            raise ErroLLM('Ollama devolveu uma identificação de modelo inválida.')
        return dict(dados=dados, modelo=modelo_retornado, uso=uso,
                    segundos=round(time.monotonic() - inicio, 6))
