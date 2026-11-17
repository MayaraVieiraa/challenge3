import unittest

from src.integracao import juiz


class TestVereditoRegra(unittest.TestCase):
    BASE = dict(afirmacoes=[dict(texto='x', fonte=1, suporte='apoiada')], fidelidade=2, correcao=2, comportamento=2,
                clareza=1, jurisprudencia_pertinente=[], veredito='aprovada', justificativa='')

    def test_tudo_2_aprova_mesmo_com_clareza_1(self):
        self.assertEqual(juiz.veredito_regra(self.BASE), 'aprovada')

    def test_nota_1_reprova_mesmo_com_veredito_aprovada(self):
        self.assertEqual(juiz.veredito_regra(dict(self.BASE, comportamento=1)), 'reprovada')

    def test_correcao_nula_nao_reprova(self):
        self.assertEqual(juiz.veredito_regra(dict(self.BASE, correcao=None)), 'aprovada')

    def test_afirmacao_sem_apoio_reprova(self):
        afirmacoes = [dict(texto='x', fonte=None, suporte='sem_apoio')]
        self.assertEqual(juiz.veredito_regra(dict(self.BASE, afirmacoes=afirmacoes)), 'reprovada')

    def test_interpretar_acrescenta_veredito_regra(self):
        import json
        dados = juiz.interpretar(json.dumps(dict(self.BASE, fidelidade=0)))
        self.assertEqual((dados['veredito'], dados['veredito_regra']), ('aprovada', 'reprovada'))


class TestJuiz(unittest.TestCase):
    def test_entrada_inclui_fontes_referencia_e_resposta(self):
        fontes = [dict(fonte='legislacao', caminho_relativo='codigos/clt.md', artigo_ref='Art. 73', conteudo='Art. 73. ... 20%'),
                  dict(fonte='jurisprudencia', tribunal='TRT-2', processo='0001-00.2020.5.02.0001', conteudo='Ementa ...')]
        texto = juiz.montar_entrada('Qual o adicional noturno?', 'responder', fontes, 'É de 20% [Fonte 1].', 'Pelo menos 20%.')
        for trecho in ('[Fonte 1] Legislação — codigos/clt.md Art. 73', '[Fonte 2] Jurisprudência — TRT-2',
                       'RESPOSTA DE REFERÊNCIA', 'RESPOSTA A AVALIAR:\nÉ de 20% [Fonte 1].'):
            self.assertIn(trecho, texto)

    def test_sem_referencia_nao_inclui_bloco(self):
        self.assertNotIn('REFERÊNCIA', juiz.montar_entrada('p', 'responder', [], 'r'))

    def test_validacao_do_json(self):
        valido = dict(afirmacoes=[], fidelidade=2, correcao=None, comportamento=2, clareza=2, jurisprudencia_pertinente=[],
                      veredito='aprovada', justificativa='ok')
        self.assertEqual(juiz._validar(dict(valido)), valido)
        with self.assertRaises(ValueError):
            juiz._validar(dict(valido, veredito='talvez'))
        with self.assertRaises(ValueError):
            juiz._validar({k: v for k, v in valido.items() if k != 'fidelidade'})


if __name__ == '__main__':
    unittest.main()
