import unittest

from avaliacao import juiz
from worker.evidencia import revisao

FONTES = [dict(fonte='legislacao', caminho_relativo='codigos/clt.md', artigo_ref='Art. 73',
               conteudo='Art. 73. O trabalho noturno terá remuneração superior à do diurno, com acréscimo de 20 % '
                        '(vinte por cento), pelo menos, sobre a hora diurna.\n\n§ 2º Considera-se noturno o trabalho '
                        'executado entre as 22 horas de um dia e as 5 horas do dia seguinte.'),
          dict(fonte='jurisprudencia', tribunal='TST', processo='123', texto='Súmula nº 60 do TST: prorrogação noturna.')]


class TestSepararEntrada(unittest.TestCase):
    def test_desfaz_montar_entrada(self):
        texto = juiz.montar_entrada('Pergunta?', 'responder', FONTES, 'Resposta [Fonte 1].', 'Referência.')
        e = revisao.separar_entrada(texto)
        self.assertEqual((e['pergunta'], e['acao'], e['referencia'], e['resposta']),
                         ('Pergunta?', 'responder', 'Referência.', 'Resposta [Fonte 1].'))
        self.assertEqual([f['n'] for f in e['fontes']], [1, 2])
        self.assertIn('Art. 73', e['fontes'][0]['rotulo'])
        self.assertTrue(e['fontes'][1]['texto'].startswith('Súmula'))

    def test_sem_fontes_e_sem_referencia(self):
        e = revisao.separar_entrada(juiz.montar_entrada('P', 'orientar_sem_aconselhar', [], 'R'))
        self.assertEqual((e['fontes'], e['referencia'], e['resposta']), ([], None, 'R'))


class TestChecagem(unittest.TestCase):
    def setUp(self):
        self.fontes = revisao.separar_entrada(juiz.montar_entrada('P', 'responder', FONTES, 'R'))['fontes']

    def test_referencias_normalizadas(self):
        refs = revisao.referencias('Art. 73 da CLT, Súmula nº 60 e Lei nº 13.467, acréscimo de 20%')
        self.assertTrue({'art 73', 'sumula 60', 'lei 13467', 'n 20'} <= refs)

    def test_numero_ausente_nas_fontes(self):
        c = revisao.checar_afirmacao(dict(texto='O adicional noturno é de 40% sobre a hora diurna.', fonte=1,
                                          suporte='sem_apoio'), self.fontes)
        self.assertEqual(c['sinal'], 'referencia_ausente')
        self.assertIn('n 40', c['referencias_ausentes'])

    def test_afirmacao_presente_na_fonte(self):
        c = revisao.checar_afirmacao(dict(texto='O trabalho noturno tem acréscimo de 20% sobre a hora diurna.',
                                          fonte=1, suporte='sem_apoio'), self.fontes)
        self.assertEqual(c['sinal'], 'apoio_textual')
        self.assertIn('vinte por cento', c['trecho'])

    def test_contradita_nunca_e_falso_alarme(self):
        c = revisao.checar_afirmacao(dict(texto='O trabalho noturno tem acréscimo de 20% sobre a hora diurna.',
                                          fonte=1, suporte='contradita'), self.fontes)
        self.assertEqual(c['sinal'], 'inconclusivo')

    def test_sem_relacao_com_as_fontes(self):
        c = revisao.checar_afirmacao(dict(texto='O empregado doméstico tem direito ao seguro-desemprego.',
                                          fonte=None, suporte='sem_apoio'), self.fontes)
        self.assertEqual(c['sinal'], 'pouco_apoio')


class TestTriar(unittest.TestCase):
    def setUp(self):
        self.fontes = revisao.separar_entrada(juiz.montar_entrada('P', 'responder', FONTES, 'R'))['fontes']
        self.base = dict(fidelidade=1, correcao=2, comportamento=2, veredito='aprovada',
                         afirmacoes=[dict(texto='Trabalho noturno: acréscimo de 20% sobre a hora diurna.', fonte=1,
                                          suporte='sem_apoio'),
                                     dict(texto='Considera-se noturno o trabalho entre 22 e 5 horas.', fonte=1,
                                          suporte='apoiada')])

    def test_falso_alarme(self):
        t = revisao.triar(self.base, self.fontes)
        self.assertEqual(t['triagem'], 'provavel_falso_alarme')
        self.assertEqual(len(t['checagens']), 1)
        self.assertIn('fidelidade = 1', t['motivos'])

    def test_comportamento_baixo_exige_leitura(self):
        self.assertEqual(revisao.triar(dict(self.base, comportamento=1), self.fontes)['triagem'], 'revisar_notas')

    def test_numero_inventado_confirma_reprovacao(self):
        afirmacoes = [dict(texto='O adicional noturno é de 65% sobre a hora diurna.', fonte=1, suporte='sem_apoio')]
        t = revisao.triar(dict(self.base, afirmacoes=afirmacoes), self.fontes)
        self.assertEqual(t['triagem'], 'provavel_reprovacao_correta')


if __name__ == '__main__':
    unittest.main()
