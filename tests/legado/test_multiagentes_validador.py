"""Políticas do Validador, sem inferência e sem alterar a execução histórica v6."""
from copy import deepcopy
import json
import unittest

from worker.evidencia.guardas import AVISO_LEGAL
from worker.evidencia.langgraph.contratos import ErroContrato
from worker.evidencia.langgraph.validador import Validador


FONTE = {
    'fonte': 'legislacao', 'unidade': 'fixture-fonte-1', 'artigo_ref': 'Art. 1',
    'conteudo': 'Material fictício de teste: não estabelece prazos ou valores.',
}


def feedback_revisao(trecho, correcao):
    return {
        'decisao': 'revisar', 'evidencia_suficiente': True,
        'problemas': [{'codigo': 'afirmacao_sem_fonte', 'trecho': trecho,
                       'fontes': [], 'correcao_solicitada': correcao}],
        'resumo': 'Corrigir o problema indicado.',
    }


class ClienteControlado:
    def __init__(self, feedback):
        self.feedback = feedback
        self.pedidos = []

    def __call__(self, **pedido):
        self.pedidos.append(deepcopy(pedido))
        return deepcopy(self.feedback)


class TestValidadorPoliticas(unittest.TestCase):
    def validar(self, feedback, *, resposta=None, fontes=None, alertas=None):
        cliente = ClienteControlado(feedback)
        validador = Validador(cliente)
        retorno = validador.validar(
            'O que as fontes permitem concluir?', 'responder',
            [deepcopy(FONTE)] if fontes is None else fontes,
            resposta if resposta is not None else 'Explicação de teste [Fonte 1].\n\n' + AVISO_LEGAL,
            [] if alertas is None else alertas,
        )
        return retorno, cliente

    def test_pedido_de_remover_aviso_obrigatorio_e_falha_de_contrato(self):
        # Reproduz a correção contraditória observada, sem simular acerto de uma LLM.
        feedback = feedback_revisao(
            AVISO_LEGAL,
            'Remover a frase, pois é um aviso legal genérico e não contribui para a resposta.',
        )
        with self.assertRaisesRegex(ErroContrato, 'feedback_conflita_politica'):
            self.validar(feedback)

    def test_aviso_integral_e_reconhecido_com_aspas_espacos_e_pontuacao(self):
        trecho = '  "' + AVISO_LEGAL.replace(' ', '\n ').replace(',', ';') + '"  '
        for correcao in ('Exclua essa frase.', 'Retire o trecho.', 'O aviso deve ser removido.'):
            with self.subTest(correcao=correcao):
                with self.assertRaisesRegex(ErroContrato, 'feedback_conflita_politica'):
                    self.validar(feedback_revisao(trecho, correcao))

    def test_negacao_de_remocao_nao_e_interpretada_como_pedido(self):
        for correcao in ('Não remover o aviso.', 'Não remova a frase.',
                         'Não é necessário remover o aviso.', 'Não se deve excluir o aviso.'):
            with self.subTest(correcao=correcao):
                feedback = feedback_revisao(AVISO_LEGAL, correcao)
                retorno, _ = self.validar(feedback)
                self.assertEqual(retorno, feedback)

    def test_critica_juridica_continua_valida_quando_aviso_esta_em_outra_zona(self):
        alegacao = 'O prazo é de 99 dias [Fonte 1].'
        feedback = feedback_revisao(alegacao, 'Remova o prazo de 99 dias, ausente na fonte; preserve o aviso legal.')
        retorno, _ = self.validar(feedback, resposta=alegacao + '\n\n' + AVISO_LEGAL)
        self.assertEqual(retorno['decisao'], 'revisar')
        self.assertEqual(retorno['problemas'][0]['trecho'], alegacao)

    def test_trecho_maior_com_aviso_nao_e_classificado_pela_regra_limitada(self):
        alegacao = 'Há prazo de 99 dias. '
        feedback = feedback_revisao(alegacao + AVISO_LEGAL, 'Remova a alegação sobre 99 dias.')
        retorno, _ = self.validar(feedback, resposta=alegacao + AVISO_LEGAL)
        self.assertEqual(retorno, feedback)

    def test_contexto_envia_politica_e_candidato_exatos_sem_alterar_fontes(self):
        fontes = [deepcopy(FONTE)]
        antes = deepcopy(fontes)
        candidato = 'A fonte não estabelece esse prazo.\n\n' + AVISO_LEGAL
        feedback = {'decisao': 'evidencia_insuficiente', 'evidencia_suficiente': False,
                    'problemas': [], 'resumo': 'A fonte não contém a regra necessária.'}
        alertas = [{'codigo': 'aviso_legal_ausente', 'detalhe': 'Aviso acrescentado.'}]
        retorno, cliente = self.validar(feedback, fontes=fontes, resposta=candidato, alertas=alertas)
        self.assertEqual(retorno, feedback)
        self.assertEqual(len(cliente.pedidos), 1)
        pedido = cliente.pedidos[0]
        entrada = json.loads(pedido['mensagens'][1]['content'])
        politica = entrada['politicas_prototipo']
        self.assertEqual(politica['aviso_legal_obrigatorio'], AVISO_LEGAL)
        self.assertFalse(politica['aviso_exige_citacao'])
        self.assertFalse(politica['remocao_do_aviso_permitida'])
        self.assertTrue(politica['afirmacoes_juridicas_exigem_suporte'])
        self.assertEqual(entrada['resposta_candidata'], candidato)
        self.assertEqual(entrada['fontes'], [{'fonte_numero': 1, 'evidencia': FONTE}])
        self.assertEqual(entrada['alertas'], alertas)
        self.assertEqual(fontes, antes)
        self.assertIsNone(pedido['think'])

    def test_retorno_aprovado_incompativel_com_contrato_continua_rejeitado(self):
        feedback = feedback_revisao('Afirmação inventada.', 'Remova a afirmação sem suporte.')
        feedback['decisao'] = 'aprovar'
        with self.assertRaises(ErroContrato):
            self.validar(feedback)

    def test_fontes_inexistentes_no_feedback_continuam_rejeitadas(self):
        feedback = feedback_revisao('Afirmação inventada.', 'Remova a afirmação sem suporte.')
        feedback['problemas'][0]['fontes'] = [99]
        with self.assertRaises(ErroContrato):
            self.validar(feedback)


if __name__ == '__main__':
    unittest.main()
