"""Integração da base de precedentes do TST como terceira fonte (sem banco nem modelos: só a lógica)."""
import unittest

from src.integracao import guardrails as g
from src.integracao import geracao
from src.integracao.prompt_juridico import SYSTEM_PROMPT_LEGAL, SYSTEM_PROMPT_LEGAL_V3, build_rag_prompt
from src.integracao.recuperacao import (FONTES, Configuracao, configuracao_com_precedentes, rrf, selecionar_uniao,
                                        texto_precedente)
from src.integracao.sinonimos import expandir, termos_faltantes

SUM_338 = dict(id='TST-SUM-338', tipo='sumula', nome_citacao='Súmula 338 do TST',
               titulo='JORNADA DE TRABALHO. REGISTRO. ÔNUS DA PROVA', situacao='vigente', alerta_vigencia=None,
               texto_busca='I - É ônus do empregador que conta com mais de 10 (dez) empregados o registro da jornada...',
               texto='I - É ônus do empregador... (ex-Súmula nº 338 – alterada pela Res. 121/2003)')
FONTE_PREC = dict(fonte='precedentes', unidade='TST-SUM-338', conteudo=texto_precedente(SUM_338),
                  nome_citacao='Súmula 338 do TST', tipo_precedente='súmula', situacao='vigente', artigo_ref=None)


class TestSinonimos(unittest.TestCase):
    def test_13_salario_ganha_gratificacao_natalina(self):
        self.assertIn('gratificação natalina', expandir('As horas extras entram no 13º salário?'))
        self.assertIn('gratificação natalina', expandir('O décimo terceiro inclui o adicional?'))
        self.assertIn('gratificação natalina', expandir('E o 13o salario?'))

    def test_pergunta_original_preservada_e_idempotente(self):
        p = 'Quanto é o FGTS na demissão sem justa causa?'
        e = expandir(p)
        self.assertTrue(e.startswith(p))
        self.assertEqual(termos_faltantes(e), [])

    def test_ordinal_sozinho_dispara(self):
        # Caso real da avaliação (Súmula 45): a pergunta escreve só "13º", sem "salário".
        self.assertIn('gratificação natalina', expandir('As horas extras entram no 13º?'))
        self.assertIn('gratificação natalina', expandir('Recebo 13° proporcional?'))

    def test_numero_solto_nao_dispara(self):
        for p in ('Fui dispensado no dia 13 de maio.', 'Qual o prazo do aviso prévio?', 'A Lei 13.467/2017 mudou isso?',
                  'Conforme o art. 13º da lei, ...', 'Processo do TRT da 13ª Região.'):
            self.assertEqual(expandir(p), p)


class TestBusca(unittest.TestCase):
    def test_configuracao_padrao_usa_as_3_bases(self):
        c = Configuracao()                                   # padrão desde 2026-11-23
        self.assertEqual(c.fontes, ('legislacao', 'jurisprudencia', 'precedentes'))
        self.assertEqual(c.entrega_por_fonte, {'legislacao': 3, 'jurisprudencia': 3, 'precedentes': 3})
        self.assertEqual(c.uniao_reranker, ('precedentes',))
        self.assertTrue(c.expandir_sinonimos)
        self.assertEqual(c, configuracao_com_precedentes())
        self.assertIsNot(c.entrega_por_fonte, Configuracao().entrega_por_fonte)   # cotas não compartilhadas

    def test_duas_bases_reproduz_os_padroes_anteriores(self):
        from src.integracao.recuperacao import configuracao_duas_bases
        c = configuracao_duas_bases()
        self.assertEqual((c.fontes, c.top_k, c.entrega_por_fonte, c.uniao_reranker, c.expandir_sinonimos),
                         (FONTES, 5, None, (), False))
        self.assertEqual(configuracao_duas_bases(fontes=('legislacao',), top_k=10).fontes, ('legislacao',))

    def test_configuracao_com_precedentes(self):
        c = configuracao_com_precedentes()
        self.assertEqual(c.fontes, ('legislacao', 'jurisprudencia', 'precedentes'))
        self.assertEqual(c.entrega_por_fonte['precedentes'], 3)
        self.assertEqual(c.uniao_reranker, ('precedentes',))
        self.assertTrue(c.expandir_sinonimos)

    def test_uniao_mantem_o_que_a_fusao_perderia(self):
        # Caso da Súmula 60: 3º na semântica, ausente na busca por palavras, 21º na fusão RRF.
        lex = [f'l{i}' for i in range(30)]
        sem = ['s0', 's1', 'sum60'] + [f'l{i}' for i in range(27)]
        ordem, escores = rrf([sem, lex])
        self.assertGreater(ordem.index('sum60'), 9)              # fora dos 10 primeiros da fusão
        self.assertIn('sum60', selecionar_uniao(sem, lex, 10, escores))
        self.assertLessEqual(len(selecionar_uniao(sem, lex, 10, escores)), 20)


class TestEntrega(unittest.TestCase):
    def test_texto_do_precedente(self):
        t = texto_precedente(SUM_338)
        self.assertTrue(t.startswith('Súmula 338 do TST — JORNADA'))
        self.assertNotIn('ex-Súmula', t)                        # usa o texto de busca, sem notas de origem
        alerta = texto_precedente(dict(SUM_338, alerta_vigencia='cancelamento noticiado (fonte não oficial; alcance: Item I)'))
        self.assertIn('[Alerta de vigência:', alerta)
        sem_tese = texto_precedente(dict(SUM_338, situacao='afetado_sem_tese'))
        self.assertIn('ainda sem tese fixada', sem_tese)

    def test_fonte_para_prompt(self):
        unidade = dict(fonte='precedentes', unidade='TST-SUM-338', texto=texto_precedente(SUM_338),
                       metadata=dict(nome_citacao='Súmula 338 do TST', tipo='sumula', situacao='vigente', alerta_vigencia=None))
        f = geracao.fonte_para_prompt(unidade)
        self.assertEqual((f['fonte'], f['nome_citacao'], f['tipo_precedente']), ('precedentes', 'Súmula 338 do TST', 'súmula'))


class TestPrompt(unittest.TestCase):
    def test_v3_identifica_o_precedente(self):
        sistema, usuario = build_rag_prompt('Quem prova as horas extras?', [FONTE_PREC], versao='v3', data_atual='2026-11-22')
        self.assertIn('Tipo de fonte: precedente do TST (súmula)', usuario)
        self.assertIn('Precedente: Súmula 338 do TST', usuario)
        self.assertIn('25. Fontes do tipo "precedente do TST"', sistema)

    def test_v1_nao_ganha_regra_nem_campo(self):
        self.assertNotIn('precedente do TST', SYSTEM_PROMPT_LEGAL)
        self.assertIn('precedente do TST', SYSTEM_PROMPT_LEGAL_V3)
        _, usuario = build_rag_prompt('Pergunta?', [FONTE_PREC], versao='v1')
        self.assertNotIn('Precedente:', usuario)


class TestValidador(unittest.TestCase):
    def alertas(self, resposta, fontes):
        return [a['codigo'] for a in g.verificar_saida(resposta, fontes, versao='v3').alertas]

    def test_sumula_citada_pelo_nome_da_fonte_nao_bloqueia(self):
        fonte = dict(texto=FONTE_PREC['conteudo'].replace('Súmula 338 do TST — ', ''), tipo='precedentes',
                     nome_citacao='Súmula 338 do TST')
        resposta = 'Segundo a Súmula 338, I, do TST [Fonte 1], cabe ao empregador apresentar os controles de ponto.'
        self.assertNotIn('norma_fora_das_fontes', self.alertas(resposta, [fonte]))
        sem_nome = dict(fonte, nome_citacao=None)              # sem o nome, a citação correta seria bloqueada
        self.assertIn('norma_fora_das_fontes', self.alertas(resposta, [sem_nome]))

    def test_tema_e_oj_pelo_nome(self):
        tema = dict(texto='Questão jurídica: ... Tese: A revista meramente visual...', tipo='precedentes',
                    nome_citacao='Tema 58 de IRR do TST')
        self.assertNotIn('norma_fora_das_fontes', self.alertas('O Tema 58 do TST [Fonte 1] afasta o dano moral.', [tema]))
        oj = dict(texto='A majoração do valor do repouso semanal remunerado...', tipo='precedentes',
                  nome_citacao='OJ 394 da SBDI-1 do TST')
        self.assertNotIn('norma_fora_das_fontes', self.alertas('Pela OJ 394 da SBDI-1 [Fonte 1], não repercute.', [oj]))

    def test_revisao_passa_o_nome_de_citacao(self):
        pedido = dict(fontes=[FONTE_PREC], acao='responder', sinais=[], motivo='', pergunta_sanitizada='Quem prova?',
                      versao_prompt='v3', formato=None)
        saida = geracao.revisar(pedido, 'Pela Súmula 338 do TST [Fonte 1], o ônus é do empregador.')
        self.assertNotIn('norma_fora_das_fontes', [a['codigo'] for a in saida.alertas])


class TestAlertasPrecedentes(unittest.TestCase):
    """Os 4 alertas informativos sobre precedentes do TST (validador v3)."""
    LEI = dict(texto='Art. 74. ... § 2º Para os estabelecimentos com mais de 20 trabalhadores...', tipo='legislacao',
               artigo_ref='74', caminho='clt.md')
    SUM = dict(texto='I - É ônus do empregador...', tipo='precedentes', nome_citacao='Súmula 338 do TST',
               situacao='vigente', alerta_vigencia=None)

    def codigos(self, resposta, fontes):
        saida = g.verificar_saida(resposta, fontes, versao='v3')
        return [a['codigo'] for a in saida.alertas], saida.aprovada

    def test_fonte_trocada(self):
        cods, _ = self.codigos('Pela Súmula 338 do TST [Fonte 1], o ônus é do empregador.', [self.LEI, self.SUM])
        self.assertIn('precedente_fonte_trocada', cods)
        cods, _ = self.codigos('Pela Súmula 338 do TST [Fonte 2], o ônus é do empregador.', [self.LEI, self.SUM])
        self.assertNotIn('precedente_fonte_trocada', cods)

    def test_tema_sem_tese(self):
        tema = dict(texto='Questão jurídica: definir se...', tipo='precedentes', nome_citacao='Tema 300 de IRR do TST',
                    situacao='afetado_sem_tese', alerta_vigencia=None)
        cods, _ = self.codigos('Segundo o Tema 300 de IRR do TST [Fonte 1], o empregado tem direito ao adicional.', [tema])
        self.assertIn('tema_sem_tese_como_regra', cods)
        cods, _ = self.codigos('O Tema 300 de IRR do TST [Fonte 1] ainda está pendente: não há tese fixada.', [tema])
        self.assertNotIn('tema_sem_tese_como_regra', cods)

    def test_alerta_de_vigencia(self):
        com_alerta = dict(self.SUM, alerta_vigencia='cancelamento noticiado (fonte não oficial; alcance: Item I)')
        cods, _ = self.codigos('Pela Súmula 338 do TST [Fonte 1], o ônus é do empregador.', [com_alerta])
        self.assertIn('alerta_vigencia_omitido', cods)
        cods, _ = self.codigos('Pela Súmula 338 do TST [Fonte 1], o ônus é do empregador, mas o enunciado pode ter sido '
                               'alterado recentemente.', [com_alerta])
        self.assertNotIn('alerta_vigencia_omitido', cods)
        cods, _ = self.codigos('Pela Súmula 338 do TST [Fonte 1], o ônus é do empregador.', [self.SUM])
        self.assertNotIn('alerta_vigencia_omitido', cods)

    def test_precedente_cancelado(self):
        # Súmula 2 do TST: cancelada. Súmula 228: suspensa. A decisão entregue cita a súmula, então ela está nas fontes.
        decisao = dict(texto='Aplica-se a Súmula 2 do TST e a Súmula 228 do TST ao caso.', tipo='jurisprudencia')
        cods, aprovada = self.codigos('Conforme a Súmula 2 do TST [Fonte 1], o prazo conta assim.', [decisao])
        self.assertIn('precedente_cancelado', cods)
        self.assertTrue(aprovada)                                  # informativo: não bloqueia
        cods, _ = self.codigos('A Súmula 2 do TST [Fonte 1] foi cancelada e não se aplica mais.', [decisao])
        self.assertNotIn('precedente_cancelado', cods)
        self.assertEqual([r for *_, r, _ in g.precedentes_inativos_citados('A Súmula 228 do TST manda...')],
                         ['Súmula 228 do TST'])

    def test_cancelado_sem_falso_positivo(self):
        for texto in ('A Súmula 338 do TST trata do ônus.', 'A Súmula Vinculante 4 do STF veda...',
                      'A Súmula 2 do STJ diz outra coisa.', 'Pela OJ 394 da SBDI-1, não repercute.',
                      'A OJ 1 do TST trata do tema.'):                 # OJ 1: vigente em uma série, cancelada em outras
            self.assertEqual(g.precedentes_inativos_citados(texto), [], texto)
        self.assertTrue(g.precedentes_inativos_citados('Pela OJ 1 da SBDI-1 do TST...'))   # série dita: cancelada
        self.assertTrue(g.precedentes_inativos_citados('Pela OJ 81 do TST...'))            # todas as séries canceladas
        # Súmula 450: quarentena (cancelamento integral noticiado em fonte não oficial); caso real da pergunta FAQ20
        self.assertEqual(g.precedentes_inativos_citados('a Súmula 450 do TST reforça')[0][3], 'cancelamento_noticiado')

    def test_revisao_passa_situacao_e_alerta(self):
        fonte = dict(FONTE_PREC, alerta_vigencia='cancelamento noticiado (fonte não oficial; alcance: integral)')
        pedido = dict(fontes=[fonte], acao='responder', sinais=[], motivo='', pergunta_sanitizada='Quem prova?',
                      versao_prompt='v3', formato=None)
        saida = geracao.revisar(pedido, 'Pela Súmula 338 do TST [Fonte 1], o ônus é do empregador.')
        self.assertIn('alerta_vigencia_omitido', [a['codigo'] for a in saida.alertas])


class TestLeiPosterior(unittest.TestCase):
    """Lei posterior prevalece sobre precedente anterior a ela (decisão de 2026-11-23): regra 25, alerta e nota."""

    def test_regra_25_da_a_ordem_e_pede_a_data(self):
        from src.integracao.prompt_juridico import REGRA_25_V3_2, REGRAS_V3
        self.assertIn('a) A Constituição e a lei posteriores ao precedente', REGRAS_V3)
        self.assertIn('pergunte quando os fatos ocorreram', REGRAS_V3)
        self.assertIn('11/11/2017', REGRAS_V3)
        self.assertNotIn('Alerta de lei posterior', REGRA_25_V3_2)          # texto usado nos pedidos da v3.2
        self.assertNotIn('posteriores ao precedente', SYSTEM_PROMPT_LEGAL)   # v1 intacto

    def test_alerta_entregue_com_o_precedente(self):
        from src.integracao.recuperacao import alerta_lei_posterior
        sum85 = dict(id='TST-SUM-85', nome_citacao='Súmula 85 do TST', titulo='COMPENSAÇÃO DE JORNADA',
                     situacao='vigente', alerta_vigencia=None, texto_busca='I. A compensação de jornada...')
        self.assertIn('Lei 13.467/2017', alerta_lei_posterior('TST-SUM-85'))
        self.assertIn('[Alerta de lei posterior:', texto_precedente(sum85))
        self.assertNotIn('Alerta de lei posterior', texto_precedente(sum85, com_lei_posterior=False))   # reproduz a v3.2
        self.assertIsNone(alerta_lei_posterior('TST-SUM-338'))
        self.assertIn('Emenda Constitucional 141/2026', alerta_lei_posterior('TST-SUM-110'))
        self.assertIsNone(alerta_lei_posterior('TST-SUM-90'))      # em quarentena: não é entregue ao modelo
        self.assertTrue(Configuracao().alerta_lei_posterior)
        self.assertFalse(configuracao_com_precedentes(alerta_lei_posterior=False).alerta_lei_posterior)

    def test_validador_lei_posterior_omitida(self):
        fonte = dict(texto='Súmula 85 do TST — COMPENSAÇÃO DE JORNADA\nI. A compensação...', tipo='precedentes',
                     nome_citacao='Súmula 85 do TST', situacao='vigente', alerta_vigencia=None,
                     alerta_lei_posterior='enunciado anterior à Lei 13.467/2017...')
        cods = lambda r: [a['codigo'] for a in g.verificar_saida(r, [fonte], versao='v3').alertas]
        self.assertIn('lei_posterior_omitida', cods('Pela Súmula 85 do TST [Fonte 1], a compensação exige acordo escrito.'))
        self.assertNotIn('lei_posterior_omitida', cods('Pela Súmula 85 do TST [Fonte 1], a compensação exigia acordo escrito; '
                                                       'desde a Reforma Trabalhista, vale a regra nova.'))

    def test_nota_do_divisor(self):
        import sys
        from pathlib import Path
        from src.integracao.recuperacao import VERSAO_LEGISLACAO, VERSOES_LEGISLACAO
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
        from atualizar_legislacao_nota_divisor_lc150 import NOTA_LC150_DIVISOR
        self.assertEqual(VERSAO_LEGISLACAO, 'ec141_2026_notas_divisor')
        self.assertIn('ec141_2026_notas', VERSOES_LEGISLACAO)               # versão da v3.1 e da v3.2 mantida
        self.assertIn('Súmula 431 do TST', NOTA_LC150_DIVISOR)
        self.assertIn('não há divisor fixado', NOTA_LC150_DIVISOR)          # opção B: nada para 42 horas
        # o modelo pode citar a Súmula 431 e o art. 7º da CF a partir da nota, sem bloqueio
        lei = dict(texto='§ 2º O salário-hora normal ... por 220 (duzentas e vinte) horas ... ' + NOTA_LC150_DIVISOR,
                   tipo='legislacao', artigo_ref='Art. 2º', caminho='leis-complementares/2015/lcp-150-2015.md')
        resposta = ('O divisor da LC 150 é 220 [Fonte 1]; para 40 horas, a Súmula 431 do TST aplica o divisor 200, '
                    'conforme o art. 7º, XIII, da CF [Fonte 1].')
        self.assertNotIn('norma_fora_das_fontes', [a['codigo'] for a in g.verificar_saida(resposta, [lei], versao='v3').alertas])


if __name__ == '__main__':
    unittest.main()
