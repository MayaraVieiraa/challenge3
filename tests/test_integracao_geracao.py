import unittest

from src.integracao import geracao as ger

ARTIGO_73 = ('Art. 73. Salvo nos casos de revezamento semanal ou quinzenal, o trabalho noturno terá remuneração superior '
             'a do diurno e, para esse efeito, sua remuneração terá um acréscimo de 20 % (vinte por cento), pelo menos, '
             'sobre a hora diurna.')
BOA = ('O trabalho noturno tem remuneração superior à do diurno, com acréscimo de pelo menos 20% sobre a hora diurna '
       '(art. 73 da CLT) [Fonte 1]. Esta resposta é informativa e não substitui a orientação de um advogado.')
CITACAO_ERRADA = ('O adicional noturno é de 20% sobre a hora diurna, conforme o art. 73 da CLT [Fonte 7]. '
                  'Esta resposta é informativa e não substitui a orientação de um advogado.')


def _pedido():
    mensagens = [dict(role='system', content='sistema'), dict(role='user', content='Qual o adicional noturno?')]
    return dict(pergunta_id='t1', acao='responder', sinais=[], motivo='', pergunta_sanitizada='Qual o adicional noturno?',
                fontes=[dict(fonte='legislacao', conteudo=ARTIGO_73, artigo_ref='Art. 73')], mensagens=mensagens,
                modelo=ger.MODELO_GERACAO, opcoes=ger.OPCOES_GERACAO,
                pedido_sha256=ger._hash(ger.MODELO_GERACAO, ger.OPCOES_GERACAO, mensagens))


class LLMFalsa:
    """Responde por modelo; um valor Exception é levantado. Registra os modelos chamados."""

    def __init__(self, por_modelo):
        self.por_modelo, self.chamados = por_modelo, []

    def __call__(self, pedido):
        self.chamados.append(pedido['modelo'])
        valor = self.por_modelo[pedido['modelo']]
        if isinstance(valor, Exception):
            raise valor
        return dict(resposta=valor, done_reason='stop', pedido_sha256=pedido['pedido_sha256'])


class TestFallback(unittest.TestCase):
    def test_a_boa_nao_chama_b(self):
        llm = LLMFalsa({ger.MODELO_GERACAO: BOA})
        r = ger.gerar_com_fallback(_pedido(), llm)
        self.assertEqual(r['modelo'], ger.MODELO_GERACAO)
        self.assertEqual(llm.chamados, [ger.MODELO_GERACAO])

    def test_erro_tecnico_em_a_usa_b(self):
        llm = LLMFalsa({ger.MODELO_GERACAO: TimeoutError('tempo esgotado'), ger.MODELO_FALLBACK: BOA})
        r = ger.gerar_com_fallback(_pedido(), llm)
        self.assertEqual(r['modelo'], ger.MODELO_FALLBACK)
        self.assertTrue(r['motivo_a'].startswith('tecnico'))
        self.assertEqual(llm.chamados, [ger.MODELO_GERACAO, ger.MODELO_FALLBACK])

    def test_guardrail_bloqueante_em_a_usa_b(self):
        llm = LLMFalsa({ger.MODELO_GERACAO: CITACAO_ERRADA, ger.MODELO_FALLBACK: BOA})
        r = ger.gerar_com_fallback(_pedido(), llm)
        self.assertEqual(r['modelo'], ger.MODELO_FALLBACK)
        self.assertIn('citacao_inexistente', r['motivo_a'])

    def test_a_e_b_falham_resposta_segura(self):
        llm = LLMFalsa({ger.MODELO_GERACAO: CITACAO_ERRADA, ger.MODELO_FALLBACK: ''})
        r = ger.gerar_com_fallback(_pedido(), llm)
        self.assertTrue(r['resposta_segura'])
        self.assertEqual(r['texto'], ger.RESPOSTA_SEGURA)
        self.assertIsNone(r['modelo'])

    def test_resposta_cortada_conta_como_falha(self):
        p = _pedido()
        cortada = dict(resposta=BOA, done_reason='length', pedido_sha256=p['pedido_sha256'])
        self.assertIn('cortada', ger.motivo_fallback(p, cortada))

    def test_pedido_fallback_troca_modelo_e_hash(self):
        p = _pedido()
        b = ger.pedido_fallback(p)
        self.assertEqual(b['modelo'], ger.MODELO_FALLBACK)
        self.assertIsNone(b['think'])
        self.assertEqual(b['mensagens'], p['mensagens'])
        self.assertNotEqual(b['pedido_sha256'], p['pedido_sha256'])

    def test_escolher_sem_b_executada_da_resposta_segura(self):
        p = _pedido()
        r = ger.escolher_resposta(p, dict(resposta=CITACAO_ERRADA, done_reason='stop', pedido_sha256=p['pedido_sha256']))
        self.assertTrue(r['resposta_segura'])
        self.assertEqual(r['motivo_b'], 'nao executada')


if __name__ == '__main__':
    unittest.main()
