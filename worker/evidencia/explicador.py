"""Geração das respostas do fluxo integrado: pedidos para a LLM, respostas fixas e validação do retorno.

Fluxo por pergunta:
  1. guardrail de entrada (`guardrails.verificar_entrada`) → ação e pergunta sanitizada;
  2. ações `responder` e `orientar_sem_aconselhar`: recuperação conjunta com a configuração padrão e montagem do
     prompt jurídico (`prompt_juridico`) com as fontes entregues;
  3. demais ações (institucional, consulta individual, fora do escopo, outra jurisdição): resposta fixa, sem LLM;
  4. a LLM roda fora daqui (Kaggle, GPU T4, Ollama) sobre os pedidos exportados;
  5. no retorno, `validar_resposta` confere integridade e formato, e `guardrails.verificar_saida` revisa o conteúdo.

Fallback (LLM B): quando a resposta da LLM A (Qwen3 8B) falha tecnicamente (erro, vazia, cortada, raciocínio
exposto) ou é reprovada por um guardrail bloqueante, o mesmo prompt vai para a LLM B (Llama 3.1 8B, outra família
e diferente do juiz Gemma). Se a B também falhar, a resposta é a RESPOSTA_SEGURA. `gerar_com_fallback` aplica isso
a uma pergunta (uso em tempo real); na avaliação em lote, `motivo_fallback` decide quais pedidos vão para a B
(avaliacao/scripts/preparar_fallback_kaggle.py) e a importação escolhe a resposta final com `escolher_resposta`.
"""
from __future__ import annotations

import hashlib
import json
import re

from . import guardas as g
from .context_window import validar_janela_contexto
from .prompt_juridico import SYSTEM_PROMPT_LEGAL, build_rag_prompt
from .stracting import extrair_fatos, rotear_intencao

MODELO_GERACAO = 'qwen3:8b-q8_0'
# num_ctx 16384: o maior prompt (6 fontes, artigos longos) passa de 10 mil tokens; com 8192 o Ollama cortaria o início.
OPCOES_GERACAO = dict(temperature=0, seed=42, num_predict=1200, num_ctx=16384)
ACOES_COM_BUSCA = ('responder', 'orientar_sem_aconselhar')
FORMATO_SAIDA = {
    'type': 'object',
    'properties': {
        'resposta_direta': {'type': 'string'},
        'fundamentacao': {'type': 'array', 'items': {'type': 'string'}},
        'ressalvas': {'type': 'array', 'items': {'type': 'string'}},
    },
    'required': ['resposta_direta', 'fundamentacao', 'ressalvas'],
    'additionalProperties': False,
}
INSTRUCAO_SAIDA_ESTRUTURADA = (
    '\n\nFORMATO OBRIGATÓRIO: responda somente com um objeto JSON válido que siga exatamente o schema solicitado. '
    'Escreva a resposta principal em "resposta_direta", a fundamentação com as citações [Fonte N] em "fundamentacao" '
    '(uma afirmação por item) e limites ou perguntas necessárias em "ressalvas". Não inclua campos adicionais.'
)
# LLM B (fallback): Llama 3.1 8B, sem modo de raciocínio. Contexto de 16384 como a A (o Llama 3.1 aceita até 128k).
MODELO_FALLBACK = 'llama3.1:8b'
OPCOES_FALLBACK = dict(OPCOES_GERACAO)
RESPOSTA_SEGURA = ('Não consegui formular uma resposta confiável para esta pergunta com base nas fontes disponíveis. '
                   'Para orientação sobre o seu caso, procure um advogado, a Defensoria Pública ou o sindicato da sua '
                   'categoria.')

RESPOSTAS_FIXAS = {
    'institucional': ('Esta pergunta é sobre o funcionamento da plataforma, e não sobre Direito do Trabalho. '
                      'As informações sobre uso, privacidade e funcionalidades estão na página de ajuda da LexIA. '
                      'Se quiser, faça uma pergunta sobre seus direitos trabalhistas que eu explico com base na legislação '
                      'e na jurisprudência.'),
    'consulta_individual': ('Não tenho acesso a processos, contas ou registros pessoais, então não consigo informar a '
                            'situação do seu caso. Consulte o processo pelo número no site do tribunal (sistema PJe), ou '
                            'fale com o advogado que acompanha a ação. Para o FGTS, o extrato fica no aplicativo FGTS da '
                            'Caixa. Não envie aqui seu CPF, número do processo ou documentos.'),
    'fora_escopo': ('Só consigo responder perguntas sobre Direito do Trabalho brasileiro. Para outros assuntos, procure '
                    'um profissional da área ou a Defensoria Pública.'),
    'outra_jurisdicao': ('Só consigo responder sobre o Direito do Trabalho brasileiro. Para as regras de outro país, '
                         'consulte a legislação local ou um profissional habilitado nesse país.'),
}
NOTA_CASO_CONCRETO = ('\nA pergunta descreve uma situação concreta. Explique a regra geral aplicável com base nas fontes, '
                      'indique o que costuma ser verificado em casos assim e recomende procurar um advogado, a Defensoria '
                      'Pública ou o sindicato. Não diga o que a pessoa deve fazer nem preveja o resultado.\n')


def _processo_formatado(numero):
    d = re.sub(r'\D', '', str(numero or ''))
    return f'{d[:7]}-{d[7:9]}.{d[9:13]}.{d[13]}.{d[14:16]}.{d[16:20]}' if len(d) == 20 else (numero or None)


def _valor(meta, chave):
    v = meta.get(chave)
    return None if v in (None, '', 'None', 'nan') else v


def fonte_para_prompt(unidade):
    """Converte uma unidade entregue pelo Recuperador no formato de `build_rag_prompt` e dos guardrails."""
    meta = unidade.get('metadata') or {}
    if unidade['fonte'] == 'precedentes':
        return dict(fonte='precedentes', unidade=unidade['unidade'], conteudo=unidade['texto'],
                    nome_citacao=meta.get('nome_citacao'), tipo_precedente={'sumula': 'súmula', 'orientacao_jurisprudencial': 'orientação jurisprudencial', 'tema_repetitivo': 'tema de recurso repetitivo'}.get(meta.get('tipo')),
                    situacao=meta.get('situacao'), alerta_vigencia=meta.get('alerta_vigencia'),
                    alerta_lei_posterior=meta.get('alerta_lei_posterior'), artigo_ref=None)
    if unidade['fonte'] == 'legislacao':
        return dict(fonte='legislacao', unidade=unidade['unidade'], conteudo=unidade['texto'],
                    caminho_relativo=_valor(meta, 'caminho_relativo'), artigo_ref=_valor(meta, 'artigo_ref'),
                    contexto=_valor(meta, 'contexto'), status_declarado=_valor(meta, 'status_declarado'))
    return dict(fonte='jurisprudencia', unidade=unidade['unidade'], conteudo=unidade['texto'],
                tribunal=_valor(meta, 'tribunal'), processo=_processo_formatado(_valor(meta, 'processo_cnj')),
                orgao_julgador=_valor(meta, 'orgao_julgador'),
                data_julgamento=_valor(meta, 'data_julgamento') or _valor(meta, 'data_publicacao') or _valor(meta, 'data_assinatura'),
                artigo_ref=None)


def _hash(*partes):
    return hashlib.sha256(json.dumps(partes, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()


def montar_pedido(pergunta_id, pergunta, recuperador, config, versao_prompt='v1', data_atual=None):
    """Devolve o pedido de uma pergunta: com prompt para a LLM ou com resposta fixa.

    `versao_prompt='v3'` usa as regras novas do prompt (precisa de `data_atual`) e, na revisão, o validador v3.
    """
    entrada = g.verificar_entrada(pergunta)
    fatos = extrair_fatos(entrada.pergunta_sanitizada)
    intencao = rotear_intencao(entrada.pergunta_sanitizada)
    base = dict(pergunta_id=pergunta_id, acao=entrada.acao, sinais=entrada.sinais, motivo=entrada.motivo,
                pergunta_sanitizada=entrada.pergunta_sanitizada, intencao=intencao.intencao,
                fatos_extraidos=fatos.para_dict())
    if entrada.acao not in ACOES_COM_BUSCA:
        return dict(base, precisa_llm=False, fontes=[], resposta_fixa=RESPOSTAS_FIXAS[entrada.acao])
    entregues, diag = recuperador.buscar(entrada.pergunta_sanitizada, config)
    fontes = [fonte_para_prompt(u) for u in entregues]
    sistema, usuario = build_rag_prompt(entrada.pergunta_sanitizada, fontes, versao=versao_prompt, data_atual=data_atual)
    sistema += INSTRUCAO_SAIDA_ESTRUTURADA
    fatos_presentes = {k: v for k, v in fatos.para_dict().items() if v not in (None, [], ())}
    if fatos_presentes:
        usuario += (
            '\n\nFATOS EXTRAÍDOS AUTOMATICAMENTE (rascunho, não são confirmação independente):\n'
            + json.dumps(fatos_presentes, ensure_ascii=False, sort_keys=True)
            + '\nUse o relato original como fonte principal. Não trate inferências da extração como fatos confirmados; '
              'se um dado for essencial e ambíguo, peça confirmação em "ressalvas".'
        )
    if intencao.intencao == 'CALCULO':
        usuario += (
            '\nA intenção estimada é cálculo de verbas. Não faça cálculo individualizado nem invente dados; '
            'explique as regras gerais e peça os fatos essenciais ausentes.'
        )
    if entrada.acao == 'orientar_sem_aconselhar':
        usuario += NOTA_CASO_CONCRETO
    mensagens = [dict(role='system', content=sistema), dict(role='user', content=usuario)]
    janela = validar_janela_contexto(
        mensagens,
        max_context_tokens=OPCOES_GERACAO['num_ctx'],
        max_output_tokens=OPCOES_GERACAO['num_predict'],
    )
    pedido = dict(base, precisa_llm=True, fontes=fontes, mensagens=mensagens, segundos_recuperacao=round(diag['segundos'], 1),
                  formato=FORMATO_SAIDA, janela_contexto=janela.para_dict(),
                  pedido_sha256=_hash(MODELO_GERACAO, OPCOES_GERACAO, mensagens, FORMATO_SAIDA))
    if versao_prompt != 'v1':   # pedidos v1 continuam idênticos aos já exportados
        pedido['versao_prompt'] = versao_prompt
    return pedido


def analisar_saida_estruturada(texto):
    """Valida o JSON de geração e devolve o objeto com o schema ativo."""
    try:
        dados = json.loads(texto)
    except json.JSONDecodeError as e:
        raise ValueError(f'Saída estruturada não contém JSON válido: {e.msg}.') from None
    if not isinstance(dados, dict):
        raise ValueError('A saída estruturada deve ser um objeto JSON.')
    esperadas = set(FORMATO_SAIDA['required'])
    faltando = esperadas - dados.keys()
    extras = dados.keys() - esperadas
    if faltando or extras:
        raise ValueError(f'Campos inválidos; ausentes={sorted(faltando)}, extras={sorted(extras)}.')
    if not isinstance(dados['resposta_direta'], str) or not dados['resposta_direta'].strip():
        raise ValueError('"resposta_direta" deve ser texto não vazio.')
    for campo in ('fundamentacao', 'ressalvas'):
        valores = dados[campo]
        if not isinstance(valores, list) or any(not isinstance(item, str) or not item.strip() for item in valores):
            raise ValueError(f'"{campo}" deve ser uma lista de textos não vazios.')
    return dados


def renderizar_saida_estruturada(dados):
    """Converte a resposta validada em texto para os guardrails existentes."""
    secoes = [dados['resposta_direta'].strip()]
    if dados['fundamentacao']:
        secoes.append('Fundamentação:\n' + '\n'.join(f'- {item.strip()}' for item in dados['fundamentacao']))
    if dados['ressalvas']:
        secoes.append('Limitações e ressalvas:\n' + '\n'.join(f'- {item.strip()}' for item in dados['ressalvas']))
    return '\n\n'.join(secoes)


def validar_resposta(pedido, resposta):
    """Problemas de integridade/formato de uma resposta da LLM (lista vazia = válida)."""
    problemas = []
    if resposta.get('pedido_sha256') != pedido.get('pedido_sha256'):
        problemas.append('hash do pedido diferente')
    texto = (resposta.get('resposta') or '').strip()
    if len(texto) < 80:
        problemas.append('resposta vazia ou curta')
    if resposta.get('done_reason') == 'length':
        problemas.append('resposta cortada no limite de tokens')
    if re.search(r'</?think>', texto):
        problemas.append('raciocínio interno na resposta')
    if pedido.get('formato') == FORMATO_SAIDA:
        try:
            analisar_saida_estruturada(texto)
        except ValueError as e:
            problemas.append(f'saída estruturada inválida: {e}')
    return problemas


def revisar(pedido, texto):
    """Guardrail de saída com as fontes do pedido."""
    if pedido.get('formato') == FORMATO_SAIDA:
        try:
            texto = renderizar_saida_estruturada(analisar_saida_estruturada(texto))
        except ValueError:
            pass
    fontes = [dict(texto=f['conteudo'], artigo_ref=f.get('artigo_ref'), processo=f.get('processo'), tipo=f.get('fonte'),
                   caminho=f.get('caminho_relativo'), contexto=f.get('contexto'), nome_citacao=f.get('nome_citacao'),
                   situacao=f.get('situacao'), alerta_vigencia=f.get('alerta_vigencia'),
                   alerta_lei_posterior=f.get('alerta_lei_posterior'))
              for f in pedido['fontes']]
    entrada = g.ResultadoEntrada(pedido['acao'], pedido['pergunta_sanitizada'], pedido['sinais'], pedido['motivo'])
    return g.verificar_saida(texto, fontes, entrada, versao=versao_guardrail(pedido))


def versao_guardrail(pedido):
    """Pedidos com prompt v3 são revisados pelo validador v3; os demais, pelo guardrail original."""
    return 'v3' if pedido.get('versao_prompt') == 'v3' else 'v1'


def motivo_fallback(pedido, resposta):
    """Por que a resposta de uma LLM não serve (None = serve). `resposta`: registro no formato do kernel ou None.

    Falha técnica: sem resposta, vazia/curta, cortada, raciocínio exposto. Conteúdo: guardrail bloqueante.
    """
    if resposta is None or not (resposta.get('resposta') or '').strip():
        return 'tecnico: sem resposta'
    problemas = validar_resposta(pedido, resposta)
    if problemas:
        return 'tecnico: ' + '; '.join(problemas)
    saida = revisar(pedido, resposta['resposta'])
    lista = g.BLOQUEANTES_V3 if versao_guardrail(pedido) == 'v3' else g.BLOQUEANTES
    bloqueantes = sorted({a['codigo'] for a in saida.alertas if a['codigo'] in lista})
    return 'guardrail: ' + ', '.join(bloqueantes) if bloqueantes else None


def pedido_fallback(pedido):
    """Mesmo pedido para a LLM B (mesmas mensagens; modelo, opções e hash próprios)."""
    return dict(pedido, modelo=MODELO_FALLBACK, opcoes=OPCOES_FALLBACK, think=None, papel='fallback',
                pedido_sha256=_hash(MODELO_FALLBACK, OPCOES_FALLBACK, pedido['mensagens']))


def escolher_resposta(pedido, resposta_a, resposta_b=None):
    """Resposta final de uma pergunta com LLM: A se servir; senão B se servir; senão a RESPOSTA_SEGURA.

    Devolve dict(texto, modelo, motivo_a, motivo_b, resposta_segura). `resposta_b` é None quando a B não rodou.
    """
    motivo_a = motivo_fallback(pedido, resposta_a)
    if motivo_a is None:
        return dict(texto=resposta_a['resposta'], modelo=MODELO_GERACAO, motivo_a=None, motivo_b=None, resposta_segura=False)
    if resposta_b is None:
        return dict(texto=RESPOSTA_SEGURA, modelo=None, motivo_a=motivo_a, motivo_b='nao executada', resposta_segura=True)
    motivo_b = motivo_fallback(pedido_fallback(pedido), resposta_b)
    if motivo_b is None:
        return dict(texto=resposta_b['resposta'], modelo=MODELO_FALLBACK, motivo_a=motivo_a, motivo_b=None,
                    resposta_segura=False)
    return dict(texto=RESPOSTA_SEGURA, modelo=None, motivo_a=motivo_a, motivo_b=motivo_b, resposta_segura=True)


def gerar_com_fallback(pedido, chamar_llm):
    """Fluxo em tempo real para uma pergunta: LLM A → (se falhar) LLM B → (se falhar) resposta segura.

    `chamar_llm(pedido)` recebe o pedido (com `modelo`, `opcoes`, `mensagens`, `think`) e devolve um registro com
    `resposta`, `done_reason` e `pedido_sha256` (formato do kernel); exceções contam como falha técnica.
    """
    def tentar(p):
        try:
            return chamar_llm(p)
        except Exception as erro:
            return dict(resposta=None, erro=str(erro)[:300], pedido_sha256=p['pedido_sha256'])

    resposta_a = tentar(pedido)
    if motivo_fallback(pedido, resposta_a) is None:
        return escolher_resposta(pedido, resposta_a)
    return escolher_resposta(pedido, resposta_a, tentar(pedido_fallback(pedido)))
