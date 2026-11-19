import io
import json
from pathlib import Path
import socket
import sys
import tempfile
from types import SimpleNamespace
import unittest
import urllib.error
from unittest.mock import patch

from src.multiagentes.cliente_llm import ClienteOllama, ErroLLM
from src.multiagentes.ferramentas import BuscaCorpus, BuscaReal, BuscaSintetica


SCHEMA = dict(type='object', properties={
    'acao': dict(type='string', enum=['responder']),
    'resposta': dict(type='string', minLength=1, maxLength=100),
    'fontes': dict(type='array', minItems=1, items=dict(type='integer', minimum=1)),
}, required=['acao', 'resposta', 'fontes'], additionalProperties=False)
CONTEUDO = dict(acao='responder', resposta='Material de teste.', fontes=[1])


def retorno(conteudo=None, **extras):
    dados = dict(done=True, done_reason='stop', model='modelo:teste', prompt_eval_count=12, eval_count=8,
                 message=dict(role='assistant', content=json.dumps(CONTEUDO if conteudo is None else conteudo)))
    dados.update(extras)
    return io.BytesIO(json.dumps(dados).encode())


class TestClienteOllama(unittest.TestCase):
    def chamar(self, cliente=None, **extras):
        parametros = dict(modelo='modelo:teste', mensagens=[dict(role='user', content='PROMPT_PRIVADO')],
                          schema=SCHEMA, opcoes=dict(num_ctx=2048, temperature=0.9), think=False)
        parametros.update(extras)
        return (cliente or ClienteOllama()).gerar(**parametros)

    def test_pedido_e_retorno_sem_servico(self):
        with patch('urllib.request.urlopen', return_value=retorno()) as abrir:
            resultado = self.chamar(timeout=7)
        pedido = abrir.call_args.args[0]
        corpo = json.loads(pedido.data)
        self.assertEqual(pedido.full_url, 'http://127.0.0.1:11434/api/chat')
        self.assertEqual(pedido.method, 'POST')
        self.assertFalse(corpo['stream'])
        self.assertFalse(corpo['think'])
        self.assertEqual(corpo['format'], SCHEMA)
        self.assertEqual(corpo['keep_alive'], 0)
        self.assertEqual(corpo['options']['temperature'], 0)
        self.assertEqual(abrir.call_args.kwargs['timeout'], 7)
        self.assertEqual(resultado['dados'], CONTEUDO)
        self.assertEqual(resultado['uso'], dict(tokens_entrada=12, tokens_saida=8))
        self.assertGreaterEqual(resultado['segundos'], 0)

    def test_timeout_e_sem_retry(self):
        with patch('urllib.request.urlopen', side_effect=socket.timeout('PROMPT_PRIVADO')) as abrir:
            with self.assertRaises(ErroLLM) as erro:
                self.chamar(ClienteOllama(timeout=3))
        self.assertTrue(erro.exception.retryable)
        self.assertNotIn('PROMPT_PRIVADO', str(erro.exception))
        abrir.assert_called_once()

    def test_http_nao_expoe_corpo_nem_url(self):
        erro_http = urllib.error.HTTPError('http://usuario:SEGREDO@host/', 503, 'PROMPT_PRIVADO', {},
                                          io.BytesIO(b'CORPO_PRIVADO'))
        with patch('urllib.request.urlopen', side_effect=erro_http):
            with self.assertRaises(ErroLLM) as erro:
                self.chamar()
        self.assertEqual(str(erro.exception), 'Ollama respondeu com HTTP 503.')
        self.assertTrue(erro.exception.retryable)

    def test_url_com_credencial_recusada_sem_expor_valor(self):
        with self.assertRaises(ErroLLM) as erro:
            ClienteOllama('http://usuario:SEGREDO@localhost:11434')
        self.assertNotIn('SEGREDO', str(erro.exception))

    def test_timeouts_invalidos(self):
        for prazo in (0, -1, True, float('inf'), '180'):
            with self.subTest(timeout=prazo), self.assertRaises(ErroLLM):
                ClienteOllama(timeout=prazo)

    def test_done_e_motivo(self):
        for extras in (dict(done=False), dict(done_reason='length'), dict(done_reason='cancelled')):
            with self.subTest(extras=extras), patch('urllib.request.urlopen', return_value=retorno(**extras)):
                with self.assertRaises(ErroLLM):
                    self.chamar()
        with patch('urllib.request.urlopen', return_value=retorno(done_reason=None)):
            self.assertEqual(self.chamar()['dados'], CONTEUDO)

    def test_json_http_e_mensagem_invalidos(self):
        for bruto in (b'{', b'[]', b'{"done": true, "message": {}}',
                      b'{"done": true, "done": false}', b'{"done": NaN}'):
            with self.subTest(bruto=bruto), patch('urllib.request.urlopen', return_value=io.BytesIO(bruto)):
                with self.assertRaises(ErroLLM):
                    self.chamar()

    def test_conteudo_precisa_ser_json_estrito_sem_raciocinio(self):
        for mensagem in (
            dict(role='assistant', content='{"resposta":'),
            dict(role='assistant', content='```json\n{}\n```'),
            dict(role='assistant', content='{"acao":"responder"}', thinking='raciocínio privado'),
            dict(role='assistant', content='{"resposta":"<think>conteúdo</think>"}'),
            dict(role='assistant', content='{"resposta":NaN}'),
            dict(role='assistant', content='[]'),
            dict(role='assistant', content=json.dumps(CONTEUDO), tool_calls=[{}]),
        ):
            with self.subTest(mensagem=mensagem), patch('urllib.request.urlopen', return_value=retorno(message=mensagem)):
                with self.assertRaises(ErroLLM):
                    self.chamar()

    def test_valida_contrato_recursivo(self):
        for dados in (
            dict(CONTEUDO, acao='executar'), dict(CONTEUDO, resposta=''), dict(CONTEUDO, resposta='x' * 101),
            dict(CONTEUDO, fontes=[0]), dict(CONTEUDO, fontes=[True]), dict(CONTEUDO, fontes=[]),
            dict(CONTEUDO, fontes='1'), dict(CONTEUDO, extra='nao permitido'), dict(acao='responder'),
        ):
            with self.subTest(dados=dados), patch('urllib.request.urlopen', return_value=retorno(dados)):
                with self.assertRaises(ErroLLM):
                    self.chamar()

    def test_tokens_invalidos(self):
        with patch('urllib.request.urlopen', return_value=retorno(eval_count=-1)):
            with self.assertRaises(ErroLLM):
                self.chamar()


class TestFerramentas(unittest.TestCase):
    def test_busca_sintetica_usa_tema_e_devolve_copia(self):
        busca = BuscaSintetica()
        fontes = busca.buscar('Como organizar a leitura sobre FÉRIAS?')
        self.assertEqual(len(fontes), 1)
        self.assertTrue(fontes[0]['sintetica'])
        self.assertIn('Não define prazos, valores ou direitos.', fontes[0]['conteudo'])
        fontes[0]['conteudo'] = 'alterado'
        self.assertNotEqual(busca.buscar('férias')[0]['conteudo'], 'alterado')
        self.assertEqual(busca.buscar('insalubridade'), [])

    def test_busca_sem_evidencia(self):
        self.assertEqual(BuscaSintetica('sem_evidencia').buscar('férias'), [])

    def test_busca_real_nao_abre_recursos_ao_construir_ou_fechar(self):
        busca = BuscaReal(Path('/tmp/projeto'), device='cpu')
        self.assertIsNone(busca._recuperador)
        busca.fechar()
        self.assertIsNone(busca._recuperador)

    def test_busca_real_lazy_cotas_adaptacao_e_fechamento(self):
        from unittest.mock import Mock

        recurso = Mock()
        recurso.buscar.return_value = ([{'unidade': 'teste'}], {'segundos': 0})
        fabricar = Mock(return_value=recurso)
        conexao = Mock(return_value='conexao_ficticia')
        adaptar = Mock(return_value={'conteudo': 'teste', 'fonte': 'legislacao', 'unidade': 'teste'})
        modulos = {
            'src.integracao.recuperacao': SimpleNamespace(Recuperador=fabricar, Configuracao=SimpleNamespace),
            'src.storage.pgvector_store': SimpleNamespace(load_database_url=conexao),
            'src.integracao.geracao': SimpleNamespace(fonte_para_prompt=adaptar),
        }
        with patch.dict(sys.modules, modulos):
            busca = BuscaReal(Path('/tmp/projeto'), device='cpu')
            fabricar.assert_not_called()
            self.assertEqual(busca.buscar('férias')[0]['unidade'], 'teste')
            busca.buscar('jornada')
            fabricar.assert_called_once_with('conexao_ficticia', device='cpu', carregar_reranker=True)
            conexao.assert_called_once_with(Path('/tmp/projeto/.env.pgvector.local'))
            recurso.preparar_lexico.assert_not_called()
            config = recurso.buscar.call_args.args[1]
            self.assertEqual(config.entrega_por_fonte, {'legislacao': 3, 'jurisprudencia': 3})
            self.assertEqual(config.lexical_modo, 'idf')
            self.assertEqual(config.reranker_max_length, 256)
            busca.fechar()
            recurso.fechar.assert_called_once()
            self.assertIsNone(busca._recuperador)


class TestBuscaCorpus(unittest.TestCase):
    def criar(self, dados):
        pasta = tempfile.TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        caminho = Path(pasta.name) / 'corpus.json'
        caminho.write_text(json.dumps(dados, ensure_ascii=False), encoding='utf-8')
        return BuscaCorpus(caminho)

    @staticmethod
    def fonte(unidade, conteudo, **extras):
        # Textos neutros de indexação: estas fixtures não formulam normas jurídicas.
        fonte = dict(fonte='legislacao', unidade=unidade, conteudo=conteudo,
                     caminho_relativo='codigos/clt.md', artigo_ref=None)
        fonte.update(extras)
        return fonte

    def test_carregamento_lazy_e_consulta_sem_termos(self):
        busca = BuscaCorpus(Path('/tmp/corpus_portatil_inexistente.json'))
        self.assertIsNone(busca._fontes)
        self.assertEqual(busca.buscar(''), [])
        self.assertEqual(busca.buscar('de a e os como qual'), [])
        self.assertEqual(busca.buscar('12 § 1º'), [])
        self.assertIsNone(busca._fontes)
        with self.assertRaises(ValueError):
            busca.buscar('férias')

    def test_normalizacao_acentos_e_sem_resultado(self):
        busca = self.criar([self.fonte('clt-1', 'Férias: registro de referência documental.')])
        self.assertEqual(busca.buscar('COMO consultar FÉRIAS?')[0]['unidade'], 'clt-1')
        self.assertEqual(busca.buscar('ferias')[0]['unidade'], 'clt-1')
        self.assertEqual(busca.buscar('insalubridade'), [])
        self.assertEqual(self.criar([]).buscar('férias'), [])

    def test_ranking_idf_favorece_termo_raro(self):
        busca = self.criar([
            self.fonte('a', 'Férias referência comum.'),
            self.fonte('b', 'Teletrabalho referência específica.'),
            self.fonte('c', 'Férias documento adicional.'),
            self.fonte('d', 'Férias documento complementar.'),
        ])
        self.assertEqual([f['unidade'] for f in busca.buscar('férias teletrabalho')], ['b', 'a', 'c', 'd'])
        self.assertEqual(busca.buscar('férias férias teletrabalho'), busca.buscar('férias teletrabalho'))

    def test_empate_deterministico_e_limite_seis(self):
        fontes = [self.fonte(str(i), 'Férias documento.') for i in range(9, 0, -1)]
        busca = self.criar(fontes)
        self.assertEqual([f['unidade'] for f in busca.buscar('férias')], ['1', '2', '3', '4', '5', '6'])

    def test_empate_usa_ordem_natural_por_norma_sem_depender_do_id(self):
        especificacoes = [
            ('a0', 'normas/b.md', 'Art. 1'),
            ('a1', 'normas/a.md', 'Art. 10'),
            ('m7', 'normas/a.md', 'Art. 2-B'),
            ('z9', 'normas/b.md', 'Art. 12'),
            ('b3', 'normas/a.md', 'Art. 2-A'),
            ('z8', 'normas/a.md', 'Art. 2'),
        ]
        fontes = [self.fonte(unidade, 'Jornada: referência documental.',
                             caminho_relativo=norma, artigo_ref=artigo)
                  for unidade, norma, artigo in especificacoes]
        esperado = ['z8', 'b3', 'm7', 'a1', 'a0', 'z9']
        for entrada in (fontes, list(reversed(fontes))):
            with self.subTest(ordem=[f['unidade'] for f in entrada]):
                busca = self.criar(entrada)
                resultado = busca.buscar('jornada')
                self.assertEqual([f['unidade'] for f in resultado], esperado)
                resultado[0]['artigo_ref'] = 'alterado'
                self.assertEqual(busca.buscar('jornada')[0]['artigo_ref'], 'Art. 2')

    def test_pontuacao_precede_desempate_por_artigo(self):
        busca = self.criar([
            self.fonte('a', 'Jornada registro.', artigo_ref='Art. 1'),
            self.fonte('b', 'Jornada registro.', artigo_ref='Art. 2'),
            self.fonte('z', 'Jornada compensação registro.', artigo_ref='Art. 20'),
        ])
        self.assertEqual([f['unidade'] for f in busca.buscar('jornada compensação')], ['z', 'a', 'b'])

    def test_numero_de_artigo_na_consulta_continua_contando_no_escore(self):
        busca = self.criar([
            self.fonte('a', 'Jornada registro.', artigo_ref='Art. 2'),
            self.fonte('z', 'Jornada registro.', artigo_ref='Art. 20'),
        ])
        self.assertEqual([f['unidade'] for f in busca.buscar('art. 20 jornada')], ['z', 'a'])

    def test_dedup_e_copia_profunda(self):
        fonte = self.fonte('clt-1', 'Férias documento.', etiquetas=['preservar'])
        busca = self.criar([fonte, fonte])
        resultado = busca.buscar('férias')
        self.assertEqual(len(resultado), 1)
        resultado[0]['conteudo'] = 'alterado'
        resultado[0]['etiquetas'].append('alterada')
        novamente = busca.buscar('férias')
        self.assertEqual(novamente[0]['conteudo'], fonte['conteudo'])
        self.assertEqual(novamente[0]['etiquetas'], ['preservar'])
        busca.fechar()
        self.assertIsNone(busca._fontes)

    def test_estrutura_ids_textos_e_metadados_invalidos(self):
        boa = self.fonte('clt-1', 'Documento de férias.')
        for dados in (
            {}, [None], [dict(boa, fonte='jurisprudencia')],
            [dict(boa, unidade='')], [dict(boa, unidade='id com espaços')],
            [dict(boa, unidade=1)], [dict(boa, conteudo=' ')],
            [dict(boa, conteudo=None)], [dict(boa, artigo_ref=3)],
            [boa, dict(boa, conteudo='Conteúdo divergente.')],
        ):
            with self.subTest(dados=dados), self.assertRaises(ValueError):
                self.criar(dados).buscar('férias')

    def test_json_incompleto_e_tipo_consulta(self):
        busca = self.criar([])
        busca.caminho.write_text('[{', encoding='utf-8')
        with self.assertRaises(ValueError):
            busca.buscar('férias')
        with self.assertRaises(ValueError):
            busca.buscar(None)


if __name__ == '__main__':
    unittest.main()
