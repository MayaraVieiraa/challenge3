"""Integração do buscador local com as CLIs e o grafo, sem rede ou modelos reais."""
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import consultar_buscador_local, executar_multiagentes
from src.multiagentes.orquestrador import SistemaMultiagentes


PERGUNTA = 'Como funciona o adicional noturno no trabalho urbano?'
CONSULTA = 'adicional noturno urbano CLT artigo 73'
TEXTO = ('Art. 73. O trabalho noturno terá remuneração superior à do diurno, '
         'com acréscimo de 20% sobre a hora diurna, pelo menos.')
RESPOSTA = ('O adicional noturno urbano corresponde a pelo menos 20% sobre a hora '
            'diurna, conforme o Art. 73 da CLT [Fonte 1].')
# caminho real da CLT: o validador v3 dos multiagentes reconhece "art. 73 da CLT" pelo arquivo da fonte
FONTE = dict(fonte='legislacao', unidade='clt-artigo-73-teste', artigo_ref='Art. 73',
             caminho_relativo='codigos/consolidacao-das-leis-do-trabalho-clt-del-5452-1943.md', conteudo=TEXTO, similaridade=0.9,
             source='https://example.org/fonte-ficticia', date='2026-01-01')
DIAGNOSTICO = dict(quantidade_artigos=2, cache_reutilizado=True,
                  corpus_sha256='a' * 64, dimensao=2,
                  modelo='fake-teste', revisao='v1', max_tokens=8192,
                  cache_arquivo='/diretorio/privado/indice.sqlite3')


class BuscaStub:
    def __init__(self, erro=None):
        self.erro = erro
        self.preparada = 0
        self.consultas = []
        self.fechada = False
        self.diagnostico = deepcopy(DIAGNOSTICO)

    def preparar_indice(self):
        self.preparada += 1
        return deepcopy(self.diagnostico)

    def buscar(self, consulta):
        self.consultas.append(consulta)
        if self.erro:
            raise self.erro
        return [deepcopy(FONTE)]

    def fechar(self):
        self.fechada = True


class ClienteEmFila:
    def __init__(self):
        self.respostas = [
            {'acao': 'buscar_evidencias', 'argumentos': {'consulta': CONSULTA}},
            {'acao': 'responder', 'resposta': RESPOSTA},
            {'decisao': 'aprovar', 'evidencia_suficiente': True,
             'problemas': [], 'resumo': 'Resposta apoiada no artigo fornecido.'},
        ]

    def gerar(self, **pedido):
        return dict(dados=deepcopy(self.respostas.pop(0)), modelo=pedido['modelo'],
                    uso={'tokens_entrada': 1, 'tokens_saida': 1}, segundos=0.01)


class TestConsultarBuscadorLocalCLI(unittest.TestCase):
    def executar(self, argumentos, busca=None):
        busca = busca or BuscaStub()
        saida, erro = StringIO(), StringIO()
        with patch('src.multiagentes.buscador_local.BuscadorLocal', return_value=busca) as classe:
            with redirect_stdout(saida), redirect_stderr(erro):
                codigo = consultar_buscador_local.main(argumentos)
        return codigo, saida.getvalue(), erro.getvalue(), busca, classe

    def test_preparar_sem_consulta_nao_chama_buscar(self):
        codigo, saida, erro, busca, _ = self.executar(['--preparar-indice'])
        self.assertEqual(codigo, 0)
        self.assertEqual(erro, '')
        self.assertEqual(busca.preparada, 1)
        self.assertEqual(busca.consultas, [])
        self.assertTrue(busca.fechada)
        self.assertEqual(json.loads(saida)['fontes'], [])

    def test_consulta_mostra_referencias_sem_reproduzir_texto(self):
        codigo, saida, _, busca, classe = self.executar([
            '--pergunta', PERGUNTA, '--corpus', '/teste/artigos.json',
            '--cache-embeddings', '/teste/cache', '--device-embeddings', 'cuda',
            '--top-k', '3', '--score-minimo', '0.5',
        ])
        self.assertEqual(codigo, 0)
        dados = json.loads(saida)
        self.assertEqual(dados['fontes'][0]['unidade'], FONTE['unidade'])
        self.assertEqual(dados['fontes'][0]['similaridade'], 0.9)
        self.assertNotIn('conteudo', dados['fontes'][0])
        self.assertNotIn(TEXTO, saida)
        self.assertEqual(busca.consultas, [PERGUNTA])
        self.assertTrue(busca.fechada)
        self.assertEqual(classe.call_args.args, (Path('/teste/artigos.json'),))
        self.assertEqual(classe.call_args.kwargs['cache_dir'], Path('/teste/cache'))
        self.assertEqual(classe.call_args.kwargs['device'], 'cuda')
        self.assertEqual(classe.call_args.kwargs['top_k'], 3)
        self.assertEqual(classe.call_args.kwargs['score_minimo'], 0.5)

    def test_texto_so_e_exibido_quando_solicitado(self):
        codigo, saida, _, _, _ = self.executar(['--pergunta', PERGUNTA, '--mostrar-texto'])
        self.assertEqual(codigo, 0)
        self.assertEqual(json.loads(saida)['fontes'][0]['conteudo'], TEXTO)

    def test_erro_nao_expoe_conteudo_da_excecao_e_fecha_busca(self):
        codigo, saida, erro, busca, _ = self.executar(
            ['--pergunta', PERGUNTA], BuscaStub(ConnectionError('CREDENCIAL_TESTE')),
        )
        self.assertEqual(codigo, 2)
        self.assertEqual(saida, '')
        self.assertIn('ConnectionError', erro)
        self.assertNotIn('CREDENCIAL_TESTE', erro)
        self.assertTrue(busca.fechada)

    def test_argumentos_insuficientes_ou_incoerentes_sao_recusados(self):
        for argumentos in ([], ['--pergunta', '  '], ['--preparar-indice', '--mostrar-texto']):
            with self.subTest(argumentos=argumentos), redirect_stderr(StringIO()):
                with self.assertRaises(SystemExit) as erro:
                    consultar_buscador_local.main(argumentos)
                self.assertEqual(erro.exception.code, 2)


class TestMultiagentesModoLocal(unittest.TestCase):
    def test_cli_injeta_buscador_local_e_preserva_modo_na_execucao(self):
        busca = BuscaStub()
        cliente = ClienteEmFila()
        saida = StringIO()
        with tempfile.TemporaryDirectory() as pasta:
            with patch('src.multiagentes.buscador_local.BuscadorLocal', return_value=busca) as classe:
                with patch('src.multiagentes.cliente_llm.ClienteOllama', return_value=cliente):
                    with redirect_stdout(saida):
                        codigo = executar_multiagentes.main([
                            '--modo', 'local', '--pergunta', PERGUNTA,
                            '--corpus', '/teste/original.json', '--cache-embeddings', '/teste/cache',
                            '--device-embeddings', 'cpu', '--top-k', '4', '--score-minimo', '0.6',
                            '--saida', pasta,
                        ])
            self.assertEqual(codigo, 0)
            arquivos = list(Path(pasta).glob('*/estado.json'))
            self.assertEqual(len(arquivos), 1)
            estado = json.loads(arquivos[0].read_text())
        self.assertEqual(estado['modo'], 'local')
        self.assertEqual(estado['status'], 'aprovada')
        self.assertEqual(estado['chamadas_llm'], 3)
        self.assertEqual(estado['buscas_usadas'], 1)
        self.assertEqual(busca.consultas, [CONSULTA])
        self.assertEqual(busca.preparada, 1)
        self.assertTrue(busca.fechada)
        self.assertEqual(classe.call_args.kwargs['top_k'], 4)
        self.assertEqual(classe.call_args.kwargs['score_minimo'], 0.6)
        self.assertIn('Modo local:', saida.getvalue())
        self.assertIn('diagnostico_busca', estado)

    def test_rastro_inclui_contadores_e_hash_sem_campos_privados_da_ferramenta(self):
        busca = BuscaStub()
        busca.diagnostico.update(token='SEGREDO_NAO_COPIAR', pergunta_original='PII_NAO_COPIAR')
        estado = SistemaMultiagentes(ClienteEmFila(), busca).executar(PERGUNTA, modo='local')
        self.assertEqual(estado['status'], 'aprovada')
        self.assertEqual(estado['diagnostico_busca'], {
            nome: DIAGNOSTICO[nome] for nome in
            ('quantidade_artigos', 'cache_reutilizado', 'corpus_sha256', 'dimensao',
             'modelo', 'revisao', 'max_tokens')
        })
        evento = next(e for e in estado['eventos'] if e['etapa'] == 'indice_local')
        self.assertEqual(evento['cache_reutilizado'], True)
        serializado = json.dumps(estado)
        self.assertNotIn('SEGREDO_NAO_COPIAR', serializado)
        self.assertNotIn('PII_NAO_COPIAR', serializado)
        self.assertNotIn('/diretorio/privado', serializado)

    def test_modo_local_recusa_injecao_controlada(self):
        with self.assertRaises(ValueError):
            SistemaMultiagentes(ClienteEmFila(), BuscaStub()).executar(
                PERGUNTA, modo='local', caso='revisao_controlada',
            )

    def test_parametros_locais_nao_sao_ignorados_em_outros_modos(self):
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit) as erro:
            executar_multiagentes.main(['--modo', 'corpus', '--corpus', '/teste/corpus.json',
                                       '--cache-embeddings', '/teste/cache'])
        self.assertEqual(erro.exception.code, 2)

    def test_buscador_real_com_encoder_fake_integra_com_fontes_congeladas(self):
        from src.multiagentes.buscador_local import BuscadorLocal

        class EncoderFake:
            def encode(self, textos):
                return [[1.0, 0.0] if 'noturno' in texto else [0.0, 1.0] for texto in textos]

        artigo = dict(artigo_id='clt-artigo-73-teste', identificador_artigo='Art. 73',
                      caminho_relativo='codigos/consolidacao-das-leis-do-trabalho-clt-del-5452-1943.md', texto_artigo_completo=TEXTO,
                      caminho_hierarquico='CLT > Jornada', source='https://example.org/fonte-ficticia')
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / 'artigos.json'
            caminho.write_text(json.dumps([artigo]), encoding='utf-8')
            busca = BuscadorLocal(caminho, cache_dir=Path(pasta) / 'cache',
                                  embedder=EncoderFake(), modelo='fake-teste', revisao='v1',
                                  dimensao=2, score_minimo=0.5)
            self.addCleanup(busca.fechar)
            estado = SistemaMultiagentes(ClienteEmFila(), busca).executar(PERGUNTA, modo='local')
        self.assertEqual(estado['status'], 'aprovada')
        self.assertEqual(estado['fontes_snapshot']['fontes'][0]['conteudo'], TEXTO)
        self.assertEqual(estado['fontes_snapshot']['fontes'][0]['unidade'], artigo['artigo_id'])
        self.assertEqual(estado['diagnostico_busca']['quantidade_artigos'], 1)
        self.assertFalse(estado['diagnostico_busca']['cache_reutilizado'])


if __name__ == '__main__':
    unittest.main()
