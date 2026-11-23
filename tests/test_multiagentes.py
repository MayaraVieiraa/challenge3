"""Contratos e decisões do atendimento, sem modelos, rede ou banco de dados.

O cliente em fila existe somente nestes testes: a execução do produto continua
dependendo do cliente de LLM configurado.
"""
import copy
import json
import unittest
from unittest.mock import patch

from src.multiagentes.orquestrador import ConfiguracaoSistema, SistemaMultiagentes


PERGUNTA = 'Como funciona o adicional noturno no trabalho urbano?'
CONSULTA = 'adicional noturno urbano CLT artigo 73'
TEXTO_FONTE = (
    'Art. 73. O trabalho noturno terá remuneração superior à do diurno, com '
    'acréscimo de 20% sobre a hora diurna, pelo menos.'
)
RESPOSTA = (
    'O adicional noturno urbano corresponde a pelo menos 20% sobre a hora '
    'diurna, conforme o Art. 73 da CLT [Fonte 1].'
)
RESPOSTA_REVISADA = (
    'Conforme o Art. 73 da CLT, o trabalho noturno urbano recebe acréscimo de '
    'pelo menos 20% sobre a hora diurna [Fonte 1].'
)
CORRECAO = 'Explicite que o percentual é um mínimo e preserve a referência à Fonte 1.'


def plano():
    return {'acao': 'buscar_evidencias', 'argumentos': {'consulta': CONSULTA}}


def redacao(texto=RESPOSTA, acao='responder'):
    return {'acao': acao, 'resposta': texto}


def aprovar():
    return {
        'decisao': 'aprovar',
        'evidencia_suficiente': True,
        'problemas': [],
        'resumo': 'A explicação está apoiada na fonte entregue.',
    }


def revisar(correcao=CORRECAO):
    return {
        'decisao': 'revisar',
        'evidencia_suficiente': True,
        'problemas': [{
            'codigo': 'fundamentacao',
            'trecho': '20% sobre a hora diurna',
            'fontes': [1],
            'correcao_solicitada': correcao,
        }],
        'resumo': 'A explicação exige a correção indicada.',
    }


def insuficiente():
    return {
        'decisao': 'evidencia_insuficiente',
        'evidencia_suficiente': False,
        'problemas': [],
        'resumo': 'As evidências não sustentam a conclusão pedida.',
    }


class ScriptedClient:
    """Devolve contratos predeterminados e registra os pedidos efetivos."""

    def __init__(self, respostas, *, ao_chamar=None):
        self.respostas = list(respostas)
        self.chamadas = []
        self.ao_chamar = ao_chamar or {}

    def gerar(self, **kwargs):
        self.chamadas.append(copy.deepcopy(kwargs))
        numero = len(self.chamadas)
        if numero in self.ao_chamar:
            self.ao_chamar[numero]()
        if not self.respostas:
            raise AssertionError('O fluxo fez uma chamada de LLM não prevista pelo teste.')
        resposta = self.respostas.pop(0)
        if isinstance(resposta, Exception):
            raise resposta
        return {
            'dados': copy.deepcopy(resposta),
            'modelo': kwargs.get('modelo', 'modelo-de-teste'),
            'uso': {'tokens_entrada': 30, 'tokens_saida': 15},
            'segundos': 0.01,
        }


class BuscaFake:
    def __init__(self, fontes=None, *, erro=None):
        self.fontes = copy.deepcopy(fontes) if fontes is not None else [{
            'fonte': 'legislacao',
            'unidade': 'clt-artigo-73-teste',
            'artigo_ref': 'Art. 73',
            # caminho real da CLT: o validador v3 reconhece "art. 73 da CLT" pelo arquivo da fonte (multiagentes-v3)
            'caminho_relativo': 'codigos/consolidacao-das-leis-do-trabalho-clt-del-5452-1943.md',
            'conteudo': TEXTO_FONTE,
        }]
        self.erro = erro
        self.consultas = []
        self.fechada = False

    def buscar(self, consulta):
        self.consultas.append(consulta)
        if self.erro is not None:
            raise self.erro
        # Retorna o próprio objeto para detectar vazamentos de mutabilidade.
        return self.fontes

    def fechar(self):
        self.fechada = True


class TestSistemaMultiagentes(unittest.TestCase):
    def executar(self, respostas, *, busca=None, config=None, pergunta=PERGUNTA,
                 modo='sintetico', caso=None, ao_chamar=None):
        cliente = ScriptedClient(respostas, ao_chamar=ao_chamar)
        busca = busca if busca is not None else BuscaFake()
        sistema = SistemaMultiagentes(cliente, busca, config=config)
        estado = sistema.executar(pergunta, modo=modo, caso=caso, run_id='teste-multiagentes')
        return estado, cliente, busca

    def test_aprovacao_exige_busca_redacao_e_validacao(self):
        estado, cliente, busca = self.executar([plano(), redacao(), aprovar()])

        self.assertEqual(estado['status'], 'aprovada')
        self.assertIn(RESPOSTA, estado['resposta_final'])
        self.assertEqual(busca.consultas, [CONSULTA])
        self.assertEqual(estado['chamadas_llm'], 3)
        self.assertEqual(len(cliente.chamadas), 3)
        self.assertEqual(estado['revisoes_usadas'], 0)
        self.assertEqual(len(estado['historico']), 1)
        agentes = {str(e.get('agente', '')).lower() for e in estado['eventos']}
        self.assertTrue(any('analista' in a for a in agentes))
        self.assertTrue(any('validador' in a for a in agentes))

    def test_feedback_chega_ao_analista_e_revisao_e_revalidada(self):
        estado, cliente, busca = self.executar([
            plano(), redacao(), revisar(), redacao(RESPOSTA_REVISADA), aprovar(),
        ])

        self.assertEqual(estado['status'], 'aprovada')
        self.assertIn(RESPOSTA_REVISADA, estado['resposta_final'])
        self.assertEqual(estado['chamadas_llm'], 5)
        self.assertEqual(estado['revisoes_usadas'], 1)
        self.assertEqual(len(estado['historico']), 2)
        self.assertEqual(estado['historico'][0]['feedback']['decisao'], 'revisar')
        self.assertEqual(estado['historico'][1]['feedback']['decisao'], 'aprovar')
        pedido_revisao = json.dumps(cliente.chamadas[3], ensure_ascii=False)
        self.assertIn(CORRECAO, pedido_revisao)
        self.assertIn(RESPOSTA, pedido_revisao)
        self.assertEqual(busca.consultas, [CONSULTA])

    def test_segunda_reprovacao_encerra_sem_exibir_candidato(self):
        rejeitada = 'EXPLICACAO_REJEITADA: ' + RESPOSTA_REVISADA
        estado, cliente, _ = self.executar([
            plano(), redacao(), revisar(), redacao(rejeitada), revisar(),
        ])

        self.assertEqual(estado['status'], 'limitada')
        self.assertNotIn('EXPLICACAO_REJEITADA', estado['resposta_final'])
        self.assertNotIn(RESPOSTA_REVISADA, estado['resposta_final'])
        self.assertEqual(estado['revisoes_usadas'], 1)
        self.assertEqual(len(cliente.chamadas), 5)
        self.assertIn(rejeitada, estado['historico'][1]['rascunho'])

    def test_guardrail_veta_citacao_inexistente_mesmo_com_aprovacao_do_validador(self):
        invalida = RESPOSTA.replace('[Fonte 1]', '[Fonte 99]')
        estado, _, _ = self.executar(
            [plano(), redacao(invalida), aprovar()],
            config=ConfiguracaoSistema(max_revisoes=0),
        )

        self.assertEqual(estado['status'], 'limitada')
        self.assertNotIn('[Fonte 99]', estado['resposta_final'])
        controles = estado['historico'][0]['guardrails']
        self.assertFalse(controles['aprovada'])
        self.assertTrue(any(a['codigo'] == 'citacao_inexistente' for a in controles['alertas']))

    def test_fora_do_escopo_nao_chama_agentes_nem_busca(self):
        estado, cliente, busca = self.executar(
            [], pergunta='Como rescindir um contrato de aluguel residencial?',
        )

        self.assertEqual(estado['status'], 'resposta_fixa')
        self.assertTrue(estado['resposta_final'])
        self.assertEqual(estado['chamadas_llm'], 0)
        self.assertEqual(cliente.chamadas, [])
        self.assertEqual(busca.consultas, [])

    def test_busca_sem_fontes_encerra_sem_inventar_resposta(self):
        estado, cliente, _ = self.executar([plano()], busca=BuscaFake([]))

        self.assertEqual(estado['status'], 'limitada')
        self.assertEqual(estado['fontes_snapshot']['fontes'], [])
        self.assertEqual(len(cliente.chamadas), 1)
        self.assertNotIn('20%', estado['resposta_final'])
        self.assertNotRegex(estado['resposta_final'], r'\[Fonte\s+\d+\]')

    def test_contrato_invalido_pode_ser_corrigido_uma_vez(self):
        invalido = {'acao': 'buscar_evidencias', 'argumentos': {'consulta': 73}}
        estado, cliente, busca = self.executar([
            invalido, plano(), redacao(), aprovar(),
        ])

        self.assertEqual(estado['status'], 'aprovada')
        self.assertEqual(estado['chamadas_llm'], 4)
        self.assertEqual(len(cliente.chamadas), 4)
        self.assertEqual(busca.consultas, [CONSULTA])

    def test_tentativa_invalida_consumiu_orcamento_e_nao_libera_texto_sem_validacao(self):
        invalido = {'acao': 'buscar_evidencias', 'argumentos': {'consulta': 73}}
        estado, cliente, _ = self.executar(
            [invalido, plano(), redacao()],
            config=ConfiguracaoSistema(max_chamadas_llm=3),
        )

        self.assertEqual(estado['status'], 'falha_tecnica')
        self.assertEqual(estado['chamadas_llm'], 3)
        self.assertEqual(len(cliente.chamadas), 3)
        self.assertNotIn(RESPOSTA, estado['resposta_final'])

    def test_fontes_congeladas_resistem_a_mutacao_do_retorno_da_busca(self):
        busca = BuscaFake()
        busca.fontes.append({
            'fonte': 'jurisprudencia',
            'unidade': 'decisao-sintetica-02',
            'conteudo': 'Decisão fictícia usada apenas para testar a ordem das fontes.',
            'tribunal': 'TRT sintético',
        })
        fontes_originais = copy.deepcopy(busca.fontes)

        def adulterar_fontes_externas():
            busca.fontes[0]['conteudo'] = 'CONTEUDO_ADULTERADO_DEPOIS_DA_BUSCA'
            busca.fontes[0]['unidade'] = 'outra-unidade'
            busca.fontes.reverse()

        estado, cliente, _ = self.executar(
            [plano(), redacao(), revisar(), redacao(RESPOSTA_REVISADA), aprovar()],
            busca=busca, ao_chamar={4: adulterar_fontes_externas},
        )

        self.assertEqual(estado['status'], 'aprovada')
        snapshot = estado['fontes_snapshot']
        self.assertEqual(snapshot['fontes'], fontes_originais)
        self.assertRegex(snapshot['sha256'], r'^[0-9a-f]{64}$')
        ultimos_pedidos = json.dumps(cliente.chamadas[3:], ensure_ascii=False)
        self.assertIn(TEXTO_FONTE, ultimos_pedidos)
        self.assertNotIn('CONTEUDO_ADULTERADO_DEPOIS_DA_BUSCA', ultimos_pedidos)

    def test_dados_pessoais_nao_sao_enviados_aos_agentes_ou_busca(self):
        cpf, email = '123.456.789-09', 'pessoa.teste@example.org'
        pergunta = f'Meu CPF é {cpf} e meu e-mail é {email}. {PERGUNTA}'
        estado, cliente, busca = self.executar(
            [plano(), redacao(), aprovar()], pergunta=pergunta,
        )

        self.assertEqual(estado['status'], 'aprovada')
        dados_enviados = json.dumps([cliente.chamadas, busca.consultas], ensure_ascii=False)
        self.assertNotIn(cpf, dados_enviados)
        self.assertNotIn(email, dados_enviados)
        self.assertIn('[CPF]', dados_enviados)

    def test_falha_de_busca_e_tecnica_e_nao_insuficiencia_de_evidencia(self):
        estado, cliente, _ = self.executar(
            [plano()], busca=BuscaFake(erro=ConnectionError('Banco indisponível')),
        )

        self.assertEqual(estado['status'], 'falha_tecnica')
        self.assertEqual(len(cliente.chamadas), 1)
        self.assertNotIn(RESPOSTA, estado['resposta_final'])

    def test_revisao_controlada_preserva_original_e_identifica_falha_injetada(self):
        estado, _, _ = self.executar(
            [plano(), redacao(), revisar(), redacao(RESPOSTA_REVISADA), aprovar()],
            caso='revisao_controlada',
        )

        self.assertEqual(estado['status'], 'aprovada')
        self.assertTrue(estado['falha_injetada'])
        inicial = estado['historico'][0]
        self.assertEqual(inicial['rascunho'], RESPOSTA)
        self.assertIn('[Fonte 99]', inicial['candidato'])
        self.assertNotIn('[Fonte 99]', estado['resposta_final'])
        self.assertEqual(estado['revisoes_usadas'], 1)

    def test_injecao_controlada_e_recusada_em_modo_real(self):
        cliente, busca = ScriptedClient([]), BuscaFake()
        sistema = SistemaMultiagentes(cliente, busca)

        with self.assertRaises(ValueError):
            sistema.executar(PERGUNTA, modo='real', caso='revisao_controlada')

        self.assertEqual(cliente.chamadas, [])
        self.assertEqual(busca.consultas, [])

    def test_validador_insuficiente_impede_liberar_candidato(self):
        estado, cliente, _ = self.executar([plano(), redacao(), insuficiente()])

        self.assertEqual(estado['status'], 'limitada')
        self.assertNotIn(RESPOSTA, estado['resposta_final'])
        self.assertEqual(estado['revisoes_usadas'], 0)
        self.assertEqual(len(cliente.chamadas), 3)
        self.assertEqual(estado['historico'][0]['feedback']['decisao'], 'evidencia_insuficiente')

    def test_analista_pode_reconhecer_insuficiencia_sem_afirmacao_juridica_final(self):
        texto = 'Estas fontes não permitem responder à pergunta com segurança.'
        estado, cliente, _ = self.executar([
            plano(), redacao(texto, acao='evidencia_insuficiente'),
        ])

        self.assertEqual(estado['status'], 'limitada')
        self.assertNotIn('20%', estado['resposta_final'])
        self.assertEqual(estado['revisoes_usadas'], 0)
        self.assertEqual(len(cliente.chamadas), 2)

    def test_timeout_por_chamada_respeita_tempo_restante_da_execucao(self):
        estado, cliente, _ = self.executar(
            [plano(), redacao(), aprovar()],
            config=ConfiguracaoSistema(timeout_segundos=180, tempo_maximo_segundos=10),
        )

        self.assertEqual(estado['status'], 'aprovada')
        for chamada in cliente.chamadas:
            self.assertGreater(chamada['timeout'], 0)
            self.assertLessEqual(chamada['timeout'], 10)

    def test_tempo_total_esgotado_durante_llm_impede_etapas_seguintes(self):
        relogio = [0.0]

        def esgotar_prazo():
            relogio[0] = 11.0

        with patch('src.multiagentes.orquestrador.time.monotonic', side_effect=lambda: relogio[0]):
            estado, cliente, busca = self.executar(
                [plano()], ao_chamar={1: esgotar_prazo},
                config=ConfiguracaoSistema(tempo_maximo_segundos=10),
            )

        self.assertEqual(estado['status'], 'falha_tecnica')
        self.assertEqual(estado['chamadas_llm'], 1)
        self.assertEqual(len(cliente.chamadas), 1)
        self.assertEqual(busca.consultas, [])
        self.assertNotIn(RESPOSTA, estado['resposta_final'])

    def test_fonte_que_nao_cabe_e_omitida_inteira_sem_truncar_ou_trocar_as_demais(self):
        busca = BuscaFake()
        grande = {
            'fonte': 'jurisprudencia',
            'unidade': 'decisao-grande',
            'conteudo': 'MARCADOR_FONTE_OMITIDA ' + 'x' * 10000 + ' FIM_ORIGINAL',
        }
        pequena = {
            'fonte': 'jurisprudencia',
            'unidade': 'decisao-pequena',
            'conteudo': 'Decisão fictícia de tamanho pequeno para testar a preservação integral.',
        }
        busca.fontes.extend([grande, pequena])
        esperadas = copy.deepcopy([busca.fontes[0], pequena])

        estado, cliente, _ = self.executar([plano(), redacao(), aprovar()], busca=busca)

        self.assertEqual(estado['status'], 'aprovada')
        self.assertEqual(estado['fontes_snapshot']['fontes'], esperadas)
        self.assertEqual(len(estado['fontes_omitidas']), 1)
        self.assertEqual(estado['fontes_omitidas'][0]['posicao_original'], 2)
        enviados = json.dumps(cliente.chamadas, ensure_ascii=False)
        self.assertNotIn('MARCADOR_FONTE_OMITIDA', enviados)
        self.assertIn(pequena['conteudo'], enviados)
        self.assertEqual(busca.fontes[1], grande)

    def test_aprovacao_da_revisao_nao_expoe_texto_da_versao_reprovada(self):
        primeira = 'MARCADOR_CANDIDATO_REPROVADO: ' + RESPOSTA.replace('[Fonte 1]', '[Fonte 99]')
        estado, _, _ = self.executar([
            plano(), redacao(primeira), revisar(), redacao(RESPOSTA_REVISADA), aprovar(),
        ])

        self.assertEqual(estado['status'], 'aprovada')
        self.assertIn(RESPOSTA_REVISADA, estado['resposta_final'])
        self.assertNotIn('MARCADOR_CANDIDATO_REPROVADO', estado['resposta_final'])
        self.assertNotIn('[Fonte 99]', estado['resposta_final'])
        self.assertEqual(estado['historico'][0]['rascunho'], primeira)
        self.assertFalse(estado['historico'][0]['guardrails']['aprovada'])
        self.assertEqual(len(estado['historico']), 2)

    def test_configuracao_rejeita_booleanos_e_limites_invalidos(self):
        casos = [
            {'max_chamadas_llm': True}, {'max_chamadas_llm': 0},
            {'max_chamadas_llm': 7}, {'max_chamadas_llm': '6'},
            {'max_revisoes': False}, {'max_revisoes': 2},
            {'max_tentativas_tecnicas': True}, {'max_tentativas_tecnicas': 2},
            {'max_bytes_fontes': True}, {'max_bytes_fontes': 0},
            {'max_bytes_fontes': 9001}, {'timeout_segundos': True},
            {'timeout_segundos': 0}, {'timeout_segundos': float('inf')},
            {'tempo_maximo_segundos': float('nan')},
        ]
        for parametros in casos:
            with self.subTest(parametros=parametros), self.assertRaises(ValueError):
                ConfiguracaoSistema(**parametros)

    def test_retry_tecnico_e_global_e_nao_reinicia_ao_trocar_de_agente(self):
        plano_invalido = {'acao': 'buscar_evidencias', 'argumentos': {'consulta': 73}}
        feedback_invalido = dict(aprovar(), evidencia_suficiente=False)
        estado, cliente, _ = self.executar([
            plano_invalido, plano(), redacao(), feedback_invalido, aprovar(),
        ])

        self.assertEqual(estado['status'], 'falha_tecnica')
        self.assertEqual(estado['tentativas_tecnicas'], 1)
        self.assertEqual(estado['chamadas_llm'], 4)
        self.assertEqual(len(cliente.chamadas), 4)
        self.assertEqual(len(cliente.respostas), 1)
        self.assertNotIn(RESPOSTA, estado['resposta_final'])

    def test_sexta_chamada_invalida_nao_gera_setima_tentativa_ou_libera_revisao(self):
        plano_invalido = {'acao': 'buscar_evidencias', 'argumentos': {'consulta': 73}}
        feedback_invalido = dict(aprovar(), evidencia_suficiente=False)
        estado, cliente, _ = self.executar([
            plano_invalido, plano(), redacao(), revisar(),
            redacao(RESPOSTA_REVISADA), feedback_invalido, aprovar(),
        ])

        self.assertEqual(estado['status'], 'falha_tecnica')
        self.assertEqual(estado['chamadas_llm'], 6)
        self.assertEqual(len(cliente.chamadas), 6)
        self.assertEqual(estado['revisoes_usadas'], 1)
        self.assertEqual(len(cliente.respostas), 1)
        self.assertNotIn(RESPOSTA_REVISADA, estado['resposta_final'])


if __name__ == '__main__':
    unittest.main()
