"""Busca complementar pela norma citada fora das fontes e pedido da segunda passada (sem banco nem modelos)."""
import unittest

from src.integracao import guardrails as g
from src.integracao.complementar import BuscaComplementar, fontes_validador, montar_revisao, normas_faltantes
from src.integracao.prompt_juridico import build_rag_prompt

CLT = 'codigos/consolidacao-das-leis-do-trabalho-clt-del-5452-1943.md'
FGTS = 'leis/1990/lei-8036-1990.md'


class Resultado:
    def __init__(self, linhas):
        self.linhas = linhas

    def fetchall(self):
        return self.linhas

    def fetchone(self):
        return self.linhas[0] if self.linhas else None


class ConexaoFalsa:
    def execute(self, sql, parametros=()):
        if 'SELECT DISTINCT source_path' in sql:
            return Resultado([(CLT,), (FGTS,), ('constituicao/constituicao-1988.md',)])
        if "SELECT DISTINCT article_id, metadata->>'artigo_ref'" in sql:
            return Resultado([('clt-487', 'Art. 487'), ('clt-488', 'Art. 488')] if parametros[1] == CLT else [])
        if 'ORDER BY embedding' in sql:
            return Resultado([('fgts-18',)] if FGTS in parametros[1] else [])
        if 'FROM lex_precedentes.embeddings' in sql:
            return Resultado([(i,) for i in parametros[1] if i == 'TST-SUM-338'])     # a 450 está em quarentena
        return Resultado([])


class RecuperadorFalso:
    legislacao_a, legislacao_d, dataset_precedentes = 'A', 'D', 'P'

    def __init__(self):
        self.conexao = ConexaoFalsa()

    def vetor(self, pergunta):
        return [0.0]

    def artigos(self, ids):
        textos = {'clt-487': ('Art. 487. Não havendo prazo estipulado, a parte que... aviso prévio', CLT, 'Art. 487'),
                  'fgts-18': ('Art. 18. Ocorrendo rescisão do contrato... 40% do montante', FGTS, 'Art. 18')}
        return {i: dict(texto=textos[i][0], metadata=dict(caminho_relativo=textos[i][1], artigo_ref=textos[i][2]))
                for i in ids if i in textos}

    def precedentes(self, ids):
        return {i: dict(id=i, nome_citacao='Súmula 338 do TST', titulo='JORNADA', situacao='vigente', tipo='sumula',
                        texto_busca='I - É ônus do empregador...') for i in ids}


FONTES = [dict(fonte='legislacao', unidade='clt-477', conteudo='Art. 477. Na extinção do contrato...', artigo_ref='Art. 477',
               caminho_relativo=CLT)]
PEDIDO = dict(pergunta_id='q1', pergunta_sanitizada='Quanto recebo na demissão sem justa causa?', fontes=FONTES,
              data_atual='2026-11-22', modelo='qwen3:8b-q8_0', opcoes=dict(temperature=0), pedido_sha256='abc')
_, USUARIO = build_rag_prompt(PEDIDO['pergunta_sanitizada'], FONTES, versao='v3', data_atual='2026-11-22')
PEDIDO['mensagens'] = [dict(role='system', content='s'), dict(role='user', content=USUARIO + '\nAÇÃO DE ENTRADA: responder')]
RESPOSTA = ('Pelo art. 477 da CLT [Fonte 1], as verbas são pagas em 10 dias. A multa do FGTS é de 40% (Lei 8.036/1990) '
            '[Fonte 1], e o aviso prévio segue o art. 487 da CLT [Fonte 1]. A Lei 6.615 também se aplica [Fonte 14].')


class TestNormasFaltantes(unittest.TestCase):
    def test_identifica_o_que_falta(self):
        faltam = normas_faltantes(RESPOSTA, fontes_validador(FONTES))
        self.assertEqual([f['rotulo'] for f in faltam], ['Lei 6615', 'Lei 8036', 'art. 487 da CLT'])
        self.assertEqual(normas_faltantes('Pelo art. 477 da CLT [Fonte 1], ...', fontes_validador(FONTES)), [])


class TestBuscaComplementar(unittest.TestCase):
    def setUp(self):
        self.busca = BuscaComplementar(RecuperadorFalso())

    def test_encontra_artigo_lei_e_precedente(self):
        self.assertEqual(self.busca.artigo_de_codigo('CLT', '487')['unidade'], 'clt-487')
        self.assertIsNone(self.busca.artigo_de_codigo('CLT', '999'))
        self.assertEqual(self.busca.artigo_de_lei('8036', 'multa do FGTS')['unidade'], 'fgts-18')
        self.assertIsNone(self.busca.artigo_de_lei('6615', 'radialista'))          # lei fora da base
        self.assertEqual(self.busca.precedente('sumula', '338')['unidade'], 'TST-SUM-338')
        self.assertIsNone(self.busca.precedente('sumula', '450'))                  # fora da busca: não é entregue

    def test_limite_de_duas_fontes_novas(self):
        faltam = normas_faltantes(RESPOSTA, fontes_validador(FONTES))
        achadas = self.busca.buscar(PEDIDO['pergunta_sanitizada'], faltam)
        self.assertEqual([(f['rotulo'], x and x['unidade']) for f, x in achadas],
                         [('Lei 6615', None), ('Lei 8036', 'fgts-18'), ('art. 487 da CLT', 'clt-487')])
        um = self.busca.buscar(PEDIDO['pergunta_sanitizada'], faltam, limite=1)
        self.assertEqual(sum(x is not None for _, x in um), 1)
        # fonte já entregue não é repetida
        self.assertIsNone(self.busca.buscar('x', [dict(tipo='codigo', codigo='CLT', artigo='487', rotulo='art. 487 da CLT')],
                                            ja_entregues={'clt-487'})[0][1])


class TestMontarRevisao(unittest.TestCase):
    def test_pedido_da_segunda_passada(self):
        busca = BuscaComplementar(RecuperadorFalso())
        saida = g.verificar_saida(RESPOSTA, fontes_validador(FONTES), versao='v3')
        self.assertFalse(saida.aprovada)
        achadas = busca.buscar(PEDIDO['pergunta_sanitizada'], normas_faltantes(RESPOSTA, fontes_validador(FONTES)))
        novo = montar_revisao(PEDIDO, RESPOSTA, saida, achadas)
        self.assertEqual([f['unidade'] for f in novo['fontes']], ['clt-477', 'fgts-18', 'clt-487'])
        usuario = novo['mensagens'][1]['content']
        self.assertIn('[Fonte 2]', usuario)
        self.assertIn('Você citou Lei 8036, que não estava nas fontes. Ela foi buscada na base e agora é a [Fonte 2]', usuario)
        self.assertIn('Você citou Lei 6615, que não está nas fontes entregues', usuario)
        self.assertIn('[Fonte 14], que não existe. As fontes vão de [Fonte 1] a [Fonte 3]', usuario)
        self.assertIn('AÇÃO DE ENTRADA: responder', usuario)                    # complemento do pedido original mantido
        self.assertIn(RESPOSTA[:40], usuario)
        self.assertEqual((novo['passada'], novo['pedido_original_sha256']), (2, 'abc'))
        self.assertNotEqual(novo['pedido_sha256'], 'abc')
        # com as fontes novas, a citação da Lei 8.036 e do art. 487 deixa de estar fora das fontes
        faltam_depois = normas_faltantes(RESPOSTA, fontes_validador(novo['fontes']))
        self.assertEqual([f['rotulo'] for f in faltam_depois], ['Lei 6615'])


if __name__ == '__main__':
    unittest.main()
