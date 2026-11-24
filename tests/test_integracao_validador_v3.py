"""Prompt v3 e validador v3 (regras a partir do diagnóstico do advogado revisor, notebook 04)."""
import unittest

from worker.evidencia import guardas as g
from worker.evidencia.prompt_juridico import SYSTEM_PROMPT_LEGAL, SYSTEM_PROMPT_LEGAL_V3, build_rag_prompt

ART_20A = ('Art. 20-A O titular de contas vinculadas do FGTS estará sujeito a somente uma das seguintes sistemáticas '
           'de saque: I - saque-rescisão; ou II - saque-aniversário.')
ACORDAO = 'Nos termos do art. 11 da CLT e da Súmula 308 do TST, a prescrição é quinquenal.'
FONTES = [
    dict(texto=ART_20A, artigo_ref='Art. 20-A', tipo='legislacao', caminho='leis/1990/lei-8036-1990.md'),
    dict(texto='Art. 3º Considera-se empregado toda pessoa física...', artigo_ref='Art. 3º', tipo='legislacao',
         caminho='codigos/consolidacao-das-leis-do-trabalho-clt-del-5452-1943.md'),
    dict(texto=ACORDAO, artigo_ref=None, tipo='jurisprudencia', processo='0000001-00.2020.5.17.0001'),
]


def codigos(resposta, fontes=FONTES):
    return [a['codigo'] for a in g.verificar_saida(resposta, fontes, versao='v3').alertas]


class TestPromptV3(unittest.TestCase):
    fontes = [dict(fonte='legislacao', conteudo=ART_20A, artigo_ref='Art. 20-A', status_declarado='in_force')]

    def test_v1_continua_identico(self):
        sistema, usuario = build_rag_prompt('O que é FGTS?', self.fontes)
        self.assertEqual(sistema, SYSTEM_PROMPT_LEGAL)
        self.assertIn('Status declarado pela fonte: in_force', usuario)
        self.assertNotIn('DATA ATUAL', usuario)

    def test_v3_acrescenta_regras_tipo_e_data_e_tira_status(self):
        sistema, usuario = build_rag_prompt('O que é FGTS?', self.fontes, versao='v3', data_atual='2026-11-22')
        self.assertEqual(sistema, SYSTEM_PROMPT_LEGAL_V3)
        self.assertTrue(sistema.startswith(SYSTEM_PROMPT_LEGAL))
        self.assertIn('DATA ATUAL: 2026-11-22', usuario)
        self.assertIn('Tipo de fonte: legislação', usuario)
        self.assertNotIn('in_force', usuario)

    def test_v3_tem_regra_de_nota_de_vigencia(self):
        self.assertIn('24. Algumas fontes de legislação trazem uma "[Nota de vigência', SYSTEM_PROMPT_LEGAL_V3)
        self.assertNotIn('Nota de vigência', SYSTEM_PROMPT_LEGAL)

    def test_cf_citada_a_partir_da_nota_nao_e_fora_das_fontes(self):
        nota = ('Todo empregado tem direito ao repouso semanal remunerado de vinte e quatro horas consecutivas. '
                '[Nota de vigência: a partir de 16/12/2026, o art. 7º, XV, da CF, na redação da Emenda Constitucional '
                'nº 141, de 2026, assegura repouso semanal remunerado de 2 (dois) dias.]')
        fontes = [dict(texto=nota, artigo_ref='Art. 1º', tipo='legislacao', caminho='leis/1949/lei-605-1949.md')]
        resposta = 'A partir de 16/12/2026, o art. 7º, XV, da CF garante 2 dias de repouso semanal [Fonte 1].'
        self.assertNotIn('norma_fora_das_fontes', codigos(resposta, fontes))

    def test_v3_exige_data(self):
        with self.assertRaises(ValueError):
            build_rag_prompt('O que é FGTS?', self.fontes, versao='v3')


class TestValidadorV3(unittest.TestCase):
    def test_v1_nao_muda(self):
        resposta = 'Conforme a Lei 13.979/2020, o saque emergencial era possível.'
        self.assertNotIn('norma_fora_das_fontes', [a['codigo'] for a in g.verificar_saida(resposta, FONTES).alertas])

    def test_lei_fora_das_fontes_bloqueia(self):
        r = g.verificar_saida('O saque emergencial foi previsto na Lei 13.979/2020 [Fonte 1].', FONTES, versao='v3')
        self.assertFalse(r.aprovada)
        self.assertIn('lei 13979 não aparece em nenhuma fonte entregue', [a['detalhe'] for a in r.alertas])

    def test_lei_presente_pelo_caminho_da_fonte(self):
        self.assertNotIn('norma_fora_das_fontes', codigos('A Lei nº 8.036/1990 prevê duas sistemáticas de saque [Fonte 1].'))

    def test_sumula_citada_por_decisao_conta_como_presente(self):
        self.assertNotIn('norma_fora_das_fontes', codigos('A Súmula 308 do TST trata da prescrição [Fonte 3].'))

    def test_sumula_com_n_ordinal_na_fonte(self):
        fontes = FONTES + [dict(texto='conforme a Súmula nº 60, II, do C. TST', tipo='jurisprudencia')]
        self.assertNotIn('norma_fora_das_fontes', codigos('A Súmula 60 do TST trata da prorrogação [Fonte 4].', fontes))

    def test_numero_solto_na_fonte_nao_conta_como_lei(self):
        fontes = FONTES + [dict(texto='O valor de R$ 946 foi pago em parcelas.', tipo='jurisprudencia')]
        self.assertIn('norma_fora_das_fontes', codigos('O saque foi regulamentado pela MP 946/2020 [Fonte 4].', fontes))

    def test_lei_citada_por_decisao_nao_e_fora_das_fontes(self):
        fontes = FONTES + [dict(texto='o saque de que trata a Lei nº 13.979, de 6 de fevereiro de 2020', tipo='jurisprudencia')]
        alertas = codigos('O saque emergencial seguiu a Lei 13.979/2020 [Fonte 4].', fontes)
        self.assertNotIn('norma_fora_das_fontes', alertas)
        self.assertIn('lei_citada_com_decisao', alertas)

    def test_codigo_antes_do_artigo_entre_parenteses(self):
        self.assertIn('norma_fora_das_fontes', codigos('A Constituição Federal (Art. 7º, inciso XXIX) prevê o prazo [Fonte 1].'))

    def test_sumula_ausente(self):
        self.assertIn('norma_fora_das_fontes', codigos('A Súmula nº 338 do TST trata do controle de jornada [Fonte 3].'))

    def test_artigo_de_codigo_ausente(self):
        detalhes = [a['detalhe'] for a in g.verificar_saida('O art. 299 do CPC fixa o prazo [Fonte 2].', FONTES, versao='v3').alertas]
        self.assertIn('art. 299 da CPC não aparece em nenhuma fonte entregue', detalhes)

    def test_artigo_de_codigo_presente_na_legislacao_ou_na_decisao(self):
        self.assertNotIn('norma_fora_das_fontes', codigos('O art. 3º da CLT define empregado [Fonte 2].'))
        self.assertNotIn('norma_fora_das_fontes', codigos('CLT, art. 11: a prescrição é de cinco anos [Fonte 3].'))

    def test_sem_marcacao_fonte_bloqueia(self):
        r = g.verificar_saida('O trabalhador tem direito ao saque do FGTS na dispensa sem justa causa.', FONTES, versao='v3')
        self.assertFalse(r.aprovada)
        self.assertIn('sem_marcacao_fonte', [a['codigo'] for a in r.alertas])

    def test_lei_citada_so_com_decisao(self):
        self.assertIn('lei_citada_com_decisao', codigos('O art. 11 da CLT fixa a prescrição de cinco anos [Fonte 3].'))
        self.assertNotIn('lei_citada_com_decisao', codigos('O art. 3º da CLT define empregado [Fonte 2] [Fonte 3].'))

    def test_citacao_em_lote(self):
        self.assertIn('citacao_em_lote', codigos('O FGTS é um direito do trabalhador [Fonte 1] [Fonte 2] [Fonte 3].'))

    def test_metadado_interno(self):
        self.assertIn('metadado_interno', codigos('Todos os dispositivos estão vigentes, conforme o status in_force [Fonte 1].'))

    def test_abertura_categorica(self):
        resposta = ('Sim, você tem direito ao saque do FGTS [Fonte 1]. '
                    'No entanto, no saque-aniversário o saldo não é liberado na dispensa [Fonte 1].')
        self.assertIn('abertura_categorica', codigos(resposta))
        self.assertNotIn('abertura_categorica', codigos('Depende da sistemática de saque escolhida [Fonte 1]. No saque-aniversário o saldo fica retido [Fonte 1].'))

    def test_informativos_nao_bloqueiam(self):
        r = g.verificar_saida('Sim, a lei prevê o saque [Fonte 1] [Fonte 2] [Fonte 3]. No entanto, depende da sistemática [Fonte 1].',
                              FONTES, versao='v3')
        self.assertTrue(r.aprovada, r.alertas)


if __name__ == '__main__':
    unittest.main()
