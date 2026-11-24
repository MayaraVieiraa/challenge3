import unittest

from worker.evidencia import comparacao as c

CLT = 'codigos/consolidacao-das-leis-do-trabalho-clt-del-5452-1943.md'


class TestReferencias(unittest.TestCase):
    def test_formas_de_citacao(self):
        casos = {
            'CLT art. 73 (trabalho noturno, hora reduzida e adicional)': [('clt', '73')],
            'CLT arts. 130 e 134 (duração e concessão das férias)': [('clt', '130'), ('clt', '134')],
            'Lei 8.036/1990, art. 18 (multa de 40%) e art. 20 (hipóteses de saque)': [('lei-8036', '18'), ('lei-8036', '20')],
            'Lei 8.213/1991, arts. 22 (CAT), 60 (afastamento) e 118 (estabilidade acidentária)':
                [('lei-8213', '22'), ('lei-8213', '60'), ('lei-8213', '118')],
            'CF art. 7º, XIII (8 h diárias e 44 h semanais); CLT arts. 58 e 59': [('cf', '7'), ('clt', '58'), ('clt', '59')],
            'CLT art. 791-A (honorários de sucumbência); STF, ADI 5766': [('clt', '791-A')],
            'Lei 7.998/1990 (seguro-desemprego: requisitos e suspensão por novo vínculo)': [('lei-7998', None)],
            'Consulta processual no PJe do TRT; portal Jus.br': [],
            'Convenção coletiva da categoria (piso salarial); CLT art. 818 (ônus da prova)': [('clt', '818')],
        }
        for texto, esperado in casos.items():
            with self.subTest(texto=texto[:30]):
                self.assertEqual(c.referencias(texto), esperado)

    def test_norma_do_caminho(self):
        self.assertEqual(c.norma_do_caminho(CLT), 'clt')
        self.assertEqual(c.norma_do_caminho('leis/1990/lei-8036-1990.md'), 'lei-8036')
        self.assertEqual(c.norma_do_caminho('leis-complementares/2015/lcp-150-2015.md'), 'lc-150')
        self.assertEqual(c.norma_do_caminho('constituicao/constituicao-1988.md'), 'cf')


class TestMetricas(unittest.TestCase):
    fontes = [dict(caminho_relativo='leis-complementares/2015/lcp-150-2015.md', artigo_ref='Art. 14', conteudo='...'),
              dict(caminho_relativo=CLT, artigo_ref='Art. 73', conteudo='Art. 73 ...'),
              dict(caminho_relativo='leis/1973/lei-5889-1973.md', artigo_ref='Art. 7º', conteudo='...')]

    def test_recall(self):
        self.assertEqual(c.recall_em_3([('clt', '73')], self.fontes), 1)
        self.assertEqual(c.recall_em_3([('clt', '74')], self.fontes), 0)
        self.assertEqual(c.recall_em_3([('lei-5889', None)], self.fontes), 1)
        self.assertIsNone(c.recall_em_3([], self.fontes))

    def test_cita_referencia(self):
        self.assertEqual(c.cita_referencia('O adicional está no art. 73 da CLT.', [('clt', '73')]), 1)
        self.assertEqual(c.cita_referencia('Conforme o Art. 791-A, há honorários.', [('clt', '791-A')]), 1)
        self.assertEqual(c.cita_referencia('Conforme o art. 7º da Lei 5.889.', [('clt', '73')]), 0)
        self.assertIsNone(c.cita_referencia('qualquer', []))

    def test_resposta_busca_e_seguranca(self):
        self.assertIn('[Fonte 2]', c.resposta_busca(self.fontes))
        self.assertEqual(c.seguro([dict(codigo='afirmacao_sem_fonte')]), 1)
        self.assertEqual(c.seguro([dict(codigo='promessa_resultado')]), 0)


if __name__ == '__main__':
    unittest.main()
