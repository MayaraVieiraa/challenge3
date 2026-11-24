"""Contratos JSON puros dos dois agentes e validação contextual do feedback."""
from __future__ import annotations

import re


# multiagentes-v3 (2026-11-23): analista com o prompt v3 (regras 16 a 25 e data atual), 3 bases na busca e
# revisão automática pelo validador v3. multiagentes-v2: prompt v1 e 2 bases.
VERSAO_PROMPTS = 'multiagentes-v3'
MAX_RESPOSTA = 12000
MAX_PROBLEMAS = 20
MAX_TEXTO_FEEDBACK = 2000


class ErroContrato(ValueError):
    """A mensagem não respeita o contrato da etapa; não é uma reprovação jurídica."""


BUSCA_SCHEMA = {
    'type': 'object',
    'additionalProperties': False,
    'required': ['acao', 'argumentos'],
    'properties': {
        'acao': {'type': 'string', 'enum': ['buscar_evidencias']},
        'argumentos': {
            'type': 'object',
            'additionalProperties': False,
            'required': ['consulta'],
            'properties': {
                'consulta': {'type': 'string', 'minLength': 1, 'maxLength': 400},
            },
        },
    },
}

REDACAO_SCHEMA = {
    'type': 'object',
    'additionalProperties': False,
    'required': ['acao', 'resposta'],
    'properties': {
        'acao': {'type': 'string', 'enum': ['responder', 'evidencia_insuficiente']},
        'resposta': {'type': 'string', 'minLength': 1, 'maxLength': MAX_RESPOSTA},
    },
}

FEEDBACK_SCHEMA = {
    'type': 'object',
    'additionalProperties': False,
    'required': ['decisao', 'evidencia_suficiente', 'problemas', 'resumo'],
    'properties': {
        'decisao': {'type': 'string', 'enum': ['aprovar', 'revisar', 'evidencia_insuficiente']},
        'evidencia_suficiente': {'type': 'boolean'},
        'problemas': {
            'type': 'array',
            'maxItems': MAX_PROBLEMAS,
            'items': {
                'type': 'object',
                'additionalProperties': False,
                'required': ['codigo', 'trecho', 'fontes', 'correcao_solicitada'],
                'properties': {
                    'codigo': {'type': 'string', 'minLength': 1, 'maxLength': 64},
                    'trecho': {'type': 'string', 'maxLength': MAX_TEXTO_FEEDBACK},
                    'fontes': {
                        'type': 'array',
                        'maxItems': 64,
                        'items': {'type': 'integer', 'minimum': 1},
                    },
                    'correcao_solicitada': {
                        'type': 'string', 'minLength': 1, 'maxLength': MAX_TEXTO_FEEDBACK,
                    },
                },
            },
        },
        'resumo': {'type': 'string', 'minLength': 1, 'maxLength': MAX_TEXTO_FEEDBACK},
    },
}

_THINK = re.compile(r'</?\s*think\b[^>]*>', re.IGNORECASE)
_CODIGO = re.compile(r'[a-z][a-z0-9_]{0,63}\Z')


def _objeto(dados, chaves, campo):
    if not isinstance(dados, dict):
        raise ErroContrato(f'{campo}: esperado um objeto JSON.')
    if set(dados) != set(chaves):
        raise ErroContrato(f'{campo}: campos obrigatórios ausentes ou campos desconhecidos.')


def _texto(valor, campo, maximo, *, vazio=False):
    if not isinstance(valor, str):
        raise ErroContrato(f'{campo}: esperado texto.')
    if len(valor) > maximo or (not vazio and not valor.strip()):
        raise ErroContrato(f'{campo}: texto vazio ou maior que o limite de {maximo} caracteres.')
    if _THINK.search(valor):
        raise ErroContrato(f'{campo}: contém marcação de raciocínio interno.')
    return valor


def _contagem_fontes(numero_fontes):
    if type(numero_fontes) is not int or numero_fontes < 0:
        raise ErroContrato('numero_fontes: esperado inteiro não negativo, diferente de booleano.')


def validar_busca(dados):
    """Valida a única ferramenta permitida e retorna a consulta sem alterar o objeto."""
    _objeto(dados, ('acao', 'argumentos'), 'busca')
    if dados['acao'] != 'buscar_evidencias':
        raise ErroContrato('busca.acao: ferramenta não permitida.')
    argumentos = dados['argumentos']
    _objeto(argumentos, ('consulta',), 'busca.argumentos')
    return _texto(argumentos['consulta'], 'busca.consulta', 400).strip()


def validar_redacao(dados, numero_fontes):
    """Valida formato; erros jurídicos e de citação seguem aos controles semânticos.

    Uma referência como [Fonte 99] é texto bem formado, mas pode estar incorreta.
    Ela deve acionar os guardrails e a revisão, sem consumir uma tentativa técnica.
    """
    _contagem_fontes(numero_fontes)
    _objeto(dados, ('acao', 'resposta'), 'redacao')
    if dados['acao'] not in ('responder', 'evidencia_insuficiente'):
        raise ErroContrato('redacao.acao: permitido apenas responder ou evidencia_insuficiente.')
    resposta = _texto(dados['resposta'], 'redacao.resposta', MAX_RESPOSTA)
    return {'acao': dados['acao'], 'resposta': resposta}


def validar_feedback(dados, numero_fontes):
    """Valida JSON, índices de fontes e coerência entre decisão e problemas."""
    _contagem_fontes(numero_fontes)
    _objeto(dados, ('decisao', 'evidencia_suficiente', 'problemas', 'resumo'), 'feedback')
    decisao = dados['decisao']
    if decisao not in ('aprovar', 'revisar', 'evidencia_insuficiente'):
        raise ErroContrato('feedback.decisao: valor não permitido.')
    suficiente = dados['evidencia_suficiente']
    if type(suficiente) is not bool:
        raise ErroContrato('feedback.evidencia_suficiente: esperado booleano.')
    problemas = dados['problemas']
    if not isinstance(problemas, list) or len(problemas) > MAX_PROBLEMAS:
        raise ErroContrato(f'feedback.problemas: esperada lista com até {MAX_PROBLEMAS} itens.')
    validados = []
    for indice, problema in enumerate(problemas):
        campo = f'feedback.problemas[{indice}]'
        _objeto(problema, ('codigo', 'trecho', 'fontes', 'correcao_solicitada'), campo)
        codigo = _texto(problema['codigo'], f'{campo}.codigo', 64)
        if not _CODIGO.fullmatch(codigo):
            raise ErroContrato(f'{campo}.codigo: usar letras minúsculas, números e sublinhado.')
        trecho = _texto(problema['trecho'], f'{campo}.trecho', MAX_TEXTO_FEEDBACK, vazio=True)
        correcao = _texto(problema['correcao_solicitada'], f'{campo}.correcao_solicitada', MAX_TEXTO_FEEDBACK)
        fontes = problema['fontes']
        if not isinstance(fontes, list) or len(fontes) > 64:
            raise ErroContrato(f'{campo}.fontes: esperada lista com até 64 índices.')
        if any(type(fonte) is not int or not 1 <= fonte <= numero_fontes for fonte in fontes):
            raise ErroContrato(f'{campo}.fontes: índice inexistente ou diferente de inteiro.')
        if len(set(fontes)) != len(fontes):
            raise ErroContrato(f'{campo}.fontes: índices repetidos.')
        validados.append({'codigo': codigo, 'trecho': trecho, 'fontes': list(fontes),
                          'correcao_solicitada': correcao})
    resumo = _texto(dados['resumo'], 'feedback.resumo', MAX_TEXTO_FEEDBACK)
    if decisao == 'aprovar' and (not suficiente or problemas):
        raise ErroContrato('feedback: aprovar exige evidência suficiente e nenhum problema.')
    if decisao == 'revisar' and (not suficiente or not problemas):
        raise ErroContrato('feedback: revisar exige evidência suficiente e correção acionável.')
    if decisao == 'evidencia_insuficiente' and suficiente:
        raise ErroContrato('feedback: evidencia_insuficiente exige evidencia_suficiente=false.')
    return {'decisao': decisao, 'evidencia_suficiente': suficiente,
            'problemas': validados, 'resumo': resumo}
