"""Geração em duas etapas (v3.4): escolha de até 2 fontes e redação só com elas (sem modelos)."""
import importlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from src.integracao import duas_etapas as de

FONTES = [dict(fonte='legislacao', unidade=f'leg{i}', conteudo=f'Art. {i}. Texto da lei {i}.', artigo_ref=f'Art. {i}',
               caminho_relativo='codigos/consolidacao-das-leis-do-trabalho-clt-del-5452-1943.md') for i in range(1, 4)] + \
         [dict(fonte='precedentes', unidade='TST-SUM-338', conteudo='Súmula 338 do TST — JORNADA\nI - É ônus...',
               nome_citacao='Súmula 338 do TST', tipo_precedente='súmula', situacao='vigente', artigo_ref=None)]
PEDIDO = dict(pergunta_id='q1', pedido_sha256='h', pergunta_sanitizada='Quem prova a jornada?', fontes=FONTES,
              data_atual='2026-11-22', opcoes=dict(temperature=0, seed=42, num_predict=1200, num_ctx=16384),
              redacao=dict(complemento='\nAÇÃO DE ENTRADA: responder'))
PEDIDO['escolha'] = dict(zip(('mensagens', 'formato'), de.montar_escolha(PEDIDO['pergunta_sanitizada'], FONTES, '2026-11-22')))


class TestEscolha(unittest.TestCase):
    def test_esquema_so_aceita_fontes_entregues_e_no_maximo_duas(self):
        e = de.esquema_escolha(9)
        self.assertEqual(e['properties']['fontes']['items']['enum'], list(range(1, 10)))
        self.assertEqual(e['properties']['fontes']['maxItems'], 2)
        self.assertEqual(sorted(e['required']), ['fontes', 'nao_coberto'])

    def test_mensagens_da_escolha_trazem_todas_as_fontes(self):
        mensagens, _ = de.montar_escolha('Quem prova a jornada?', FONTES, '2026-11-22')
        self.assertIn('NÃO responde à pergunta', mensagens[0]['content'])
        self.assertIn('[Fonte 4]', mensagens[1]['content'])
        self.assertIn('Precedente: Súmula 338 do TST', mensagens[1]['content'])

    def test_interpretar_descarta_o_que_nao_vale(self):
        self.assertEqual(de.interpretar_escolha('{"fontes": [4, 1], "nao_coberto": ""}', 4), ([4, 1], ''))
        self.assertEqual(de.interpretar_escolha('{"fontes": [14, 4, 4, 2, 1], "nao_coberto": " prazo "}', 4), ([4, 2], 'prazo'))
        self.assertEqual(de.interpretar_escolha('{"fontes": [true, "2"], "nao_coberto": 3}', 4), ([], ''))
        self.assertEqual(de.interpretar_escolha('não é JSON', 4), ([], ''))
        self.assertEqual(de.interpretar_escolha(None, 4), ([], ''))


class TestRedacao(unittest.TestCase):
    def test_escolhidas_viram_fonte_1_e_2(self):
        mensagens, sel = de.montar_redacao('Quem prova?', FONTES, [4, 1], '2026-11-22', '\nAÇÃO DE ENTRADA: responder')
        self.assertEqual([f['unidade'] for f in sel], ['TST-SUM-338', 'leg1'])
        usuario = mensagens[1]['content']
        self.assertIn('[Fonte 1]\nTipo de fonte: precedente do TST (súmula)', usuario)
        self.assertIn('[Fonte 2]', usuario)
        self.assertNotIn('[Fonte 3]', usuario)
        self.assertIn('26. Esta resposta usa no máximo duas fontes', mensagens[0]['content'])
        self.assertIn('EXEMPLOS DE FORMA', mensagens[0]['content'])
        self.assertTrue(usuario.endswith('AÇÃO DE ENTRADA: responder'))

    def test_notas_de_falta_e_de_nenhuma_fonte(self):
        m, _ = de.montar_redacao('Q?', FONTES, [1], '2026-11-22', nao_coberto='o prazo de prescrição')
        self.assertIn('as fontes entregues não cobrem: "o prazo de prescrição"', m[1]['content'])
        m, sel = de.montar_redacao('Q?', FONTES, [], '2026-11-22')
        self.assertEqual(sel, [])
        self.assertIn('nenhuma das fontes consultadas trata da pergunta', m[1]['content'])


class TestGerar(unittest.TestCase):
    def test_fluxo_com_chat_simulado(self):
        chamadas = []

        def chat(mensagens, opcoes, formato):
            chamadas.append((opcoes, formato))
            if formato is not None:
                return '{"fontes": [4], "nao_coberto": ""}', dict(segundos=1.0)
            return 'Pela Súmula 338, I, do TST [Fonte 1], o ônus é do empregador.', dict(segundos=20.0)

        r = de.gerar(PEDIDO, chat)
        self.assertEqual((r['escolhidas'], r['fontes_redacao']), ([4], ['TST-SUM-338']))
        self.assertEqual(chamadas[0][0]['num_predict'], 200)          # escolha curta
        self.assertEqual(chamadas[1][0]['num_predict'], 1200)         # redação com as opções do pedido
        self.assertIsNotNone(chamadas[0][1])
        self.assertIsNone(chamadas[1][1])
        self.assertIn('[Fonte 1]', r['mensagens_redacao'][1]['content'])

    def test_modulo_funciona_fora_do_pacote_como_no_kaggle(self):
        raiz = Path(__file__).resolve().parents[1] / 'src/integracao'
        with tempfile.TemporaryDirectory() as pasta:
            for nome in ('duas_etapas.py', 'prompt_juridico.py'):
                shutil.copy(raiz / nome, pasta)
            sys.path.insert(0, pasta)
            try:
                for nome in ('duas_etapas', 'prompt_juridico'):
                    sys.modules.pop(nome, None)
                mod = importlib.import_module('duas_etapas')
                m, _ = mod.montar_escolha('Q?', FONTES, '2026-11-22')
                self.assertEqual(json.loads(json.dumps(m))[0]['role'], 'system')
            finally:
                sys.path.remove(pasta)
                for nome in ('duas_etapas', 'prompt_juridico'):
                    sys.modules.pop(nome, None)



class TestLimiteDeFontes(unittest.TestCase):
    def test_alerta_mais_de_duas_fontes(self):
        from src.integracao import guardrails as g
        fontes = [dict(texto=f'Art. {i}. Texto {i}.', tipo='legislacao', artigo_ref=f'Art. {i}') for i in range(1, 5)]
        codigos = lambda t: [a['codigo'] for a in g.verificar_saida(t, fontes, versao='v3').alertas]
        self.assertNotIn('mais_de_duas_fontes', codigos('Regra A [Fonte 1]. Regra B [Fonte 2]. De novo [Fonte 1].'))
        self.assertIn('mais_de_duas_fontes', codigos('Regra A [Fonte 1]. Regra B [Fonte 2]. Regra C [Fonte 3].'))
        saida = g.verificar_saida('Regra A [Fonte 1]. Regra B [Fonte 2]. Regra C [Fonte 3].', fontes, versao='v3')
        self.assertNotIn('mais_de_duas_fontes', g.BLOQUEANTES_V3)          # informativo


if __name__ == '__main__':
    unittest.main()
