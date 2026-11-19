"""Pacote e bootstrap Kaggle do buscador local, sem rede, GPU ou modelos."""
import ast
from contextlib import redirect_stdout
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from scripts import preparar_multiagentes_kaggle as pacote


NOTEBOOK = Path(__file__).resolve().parents[1] / pacote.NOTEBOOK_RELATIVO


class TestPacoteBuscadorLocalKaggle(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'projeto'
        self.root.mkdir()
        self.patch_root = patch.object(pacote, 'ROOT', self.root)
        self.patch_root.start()
        self.addCleanup(self.patch_root.stop)
        self.registros = [self.artigo('clt-73', 'Art. 73', pacote.CLT_CAMINHO),
                          self.artigo('outra-norma-1', 'Art. 1', 'normas/outra.md')]
        self.gravar(pacote.BASE_RELATIVA, json.dumps(self.registros, ensure_ascii=False).encode())
        self.gravar(pacote.NOTEBOOK_RELATIVO, NOTEBOOK.read_bytes())
        for nome in ('__init__.py', 'buscador_local.py', 'ferramentas.py'):
            self.gravar(Path('src/multiagentes') / nome, b'"""Modulo de teste."""\n')
        for nome in pacote._INTEGRACAO:
            self.gravar(Path('src/integracao') / nome, b'"""Modulo de teste."""\n')
        self.gravar(Path('requirements-multiagentes.txt'), b'langgraph==1.2.22\n')
        self.gravar(Path('requirements-buscador-local.txt'), b'sentence-transformers>=3.4,<6\n')
        # Nem a base nem o cache devem entrar no runtime de código.
        self.gravar(Path('dados/output/buscador_local/privado.sqlite3'), b'CACHE_NAO_EMPACOTAR')

    @staticmethod
    def artigo(unidade, referencia, caminho):
        return {'artigo_id': unidade, 'identificador_artigo': referencia,
                'texto_artigo_completo': 'Texto integral de teste com condição e exceção.\n',
                'caminho_relativo': caminho, 'caminho_hierarquico': 'Norma > ' + referencia,
                'source': 'https://example.org/norma', 'date': '2026-01-01',
                'retrieved': '2026-11-19', 'tem_alerta_parser': False}

    def gravar(self, relativo, dados):
        caminho = self.root / relativo
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_bytes(dados)

    def preparar(self, nome='saida'):
        return pacote.preparar_pacote(self.root / nome, buscador='local')

    def bootstrap(self, destino):
        notebook = json.loads((destino / pacote.NOTEBOOK_PACOTE).read_bytes())
        contexto = {}
        with redirect_stdout(StringIO()):
            exec(''.join(notebook['cells'][1]['source']), contexto)
            contexto['DIRETORIO_DATASET'] = str(destino)
            contexto['WORKING'] = self.root / 'working'
            contexto['WORKING'].mkdir(exist_ok=True)
            exec(''.join(notebook['cells'][4]['source']), contexto)
            exec(''.join(notebook['cells'][5]['source']), contexto)
        return contexto

    def test_base_original_completa_e_preservada_sem_filtro_de_norma(self):
        origem = (self.root / pacote.BASE_RELATIVA).read_bytes()
        destino = self.preparar()
        self.assertEqual((destino / 'legislacao_artigos_completos.json').read_bytes(), origem)
        self.assertFalse((destino / 'corpus_legislacao.json').exists())
        manifesto = json.loads((destino / 'manifesto_pacote.json').read_bytes())
        self.assertEqual(manifesto['modo'], 'local')
        self.assertEqual(manifesto['tema'], 'base_completa')
        self.assertEqual(manifesto['selecao']['quantidade_artigos'], 2)
        self.assertEqual([r['unidade'] for r in manifesto['selecao']['artigos']],
                         ['clt-73', 'outra-norma-1'])

    def test_manifesto_hashes_requisitos_e_runtime_sem_cache(self):
        destino = self.preparar()
        manifesto = json.loads((destino / 'manifesto_pacote.json').read_bytes())
        for nome, identidade in manifesto['arquivos'].items():
            dados = (destino / nome).read_bytes()
            self.assertEqual(identidade, {'bytes': len(dados), 'sha256': sha256(dados).hexdigest()})
        with ZipFile(destino / 'runtime.zip') as runtime:
            self.assertIn('requirements-buscador-local.txt', runtime.namelist())
            self.assertNotIn(b'CACHE_NAO_EMPACOTAR', b''.join(runtime.read(n) for n in runtime.namelist()))
            self.assertEqual(set(runtime.namelist()), set(manifesto['runtime']['arquivos']))

    def test_preferencia_caminho_dados_e_fallback_data(self):
        self.gravar(pacote.BASE_RELATIVA_DADOS, json.dumps([self.registros[1]]).encode())
        destino = self.preparar()
        manifesto = json.loads((destino / 'manifesto_pacote.json').read_bytes())
        self.assertEqual(manifesto['base']['caminho_relativo'], pacote.BASE_RELATIVA_DADOS.as_posix())
        self.assertEqual(manifesto['selecao']['quantidade_artigos'], 1)

    def test_base_completa_nao_tem_o_limite_do_recorte_lexical(self):
        registros = [dict(self.registros[0], artigo_id=f'teste-{i}') for i in range(90)]
        self.gravar(pacote.BASE_RELATIVA, json.dumps(registros).encode())
        manifesto = json.loads((self.preparar() / 'manifesto_pacote.json').read_bytes())
        self.assertEqual(manifesto['selecao']['quantidade_artigos'], 90)

    def test_entrada_invalida_e_requisito_ausente_nao_criam_pacote(self):
        for registros in ([], {}, [dict(self.registros[0], texto_artigo_completo='')],
                          [dict(self.registros[0], date=123)],
                          [self.registros[0], self.registros[0]]):
            with self.subTest(registros=type(registros).__name__):
                self.gravar(pacote.BASE_RELATIVA, json.dumps(registros).encode())
                with self.assertRaises(ValueError):
                    self.preparar()
                self.assertFalse((self.root / 'saida').exists())
        self.gravar(pacote.BASE_RELATIVA, json.dumps(self.registros).encode())
        (self.root / 'requirements-buscador-local.txt').unlink()
        with self.assertRaisesRegex(ValueError, 'obrigatório ausente'):
            self.preparar()
        self.assertFalse((self.root / 'saida').exists())

    def test_cli_local_e_reproducibilidade(self):
        destino = self.root / 'saida'
        with redirect_stdout(StringIO()):
            pacote.main(['--buscador', 'local', '--destino', str(destino)])
        antes = {p.name: p.read_bytes() for p in destino.iterdir()}
        self.preparar()
        self.assertEqual(antes, {p.name: p.read_bytes() for p in destino.iterdir()})

    def test_notebook_valida_e_extrai_pacote_local_zip_ou_expandido(self):
        for expandido in (False, True):
            with self.subTest(expandido=expandido):
                destino = self.preparar('expandido' if expandido else 'zip')
                if expandido:
                    # O conteúdo é uma fixture criada pelo teste, sem entradas externas.
                    with ZipFile(destino / 'runtime.zip') as runtime:
                        for nome in runtime.namelist():
                            caminho = destino / 'runtime' / nome
                            caminho.parent.mkdir(parents=True, exist_ok=True)
                            caminho.write_bytes(runtime.read(nome))
                    (destino / 'runtime.zip').unlink()
                contexto = self.bootstrap(destino)
                self.assertEqual(contexto['MODO_BUSCA'], 'local')
                self.assertEqual(contexto['NOME_CORPUS'], 'legislacao_artigos_completos.json')
                self.assertTrue((contexto['RUNTIME_DIR'] / 'requirements-buscador-local.txt').is_file())

    def test_notebook_recusa_corpus_alterado_antes_da_extracao(self):
        destino = self.preparar()
        (destino / 'legislacao_artigos_completos.json').write_text('[]')
        with self.assertRaisesRegex(RuntimeError, 'Integridade divergente'):
            self.bootstrap(destino)
        self.assertEqual(list((self.root / 'working').iterdir()), [])

    def test_notebook_mantem_compatibilidade_com_pacote_lexical(self):
        destino = pacote.preparar_pacote(self.root / 'lexical', tema='noturno')
        contexto = self.bootstrap(destino)
        self.assertEqual(contexto['MODO_BUSCA'], 'corpus')
        self.assertEqual(contexto['NOME_CORPUS'], 'corpus_legislacao.json')
        self.assertFalse((contexto['RUNTIME_DIR'] / 'requirements-buscador-local.txt').exists())

    def test_notebook_sem_outputs_e_com_codigo_compilavel(self):
        notebook = json.loads(NOTEBOOK.read_bytes())
        for indice, celula in enumerate(notebook['cells']):
            if celula['cell_type'] == 'code':
                ast.parse(''.join(celula['source']), filename=f'celula-{indice}')
                self.assertEqual(celula['outputs'], [])
                self.assertIsNone(celula['execution_count'])


if __name__ == '__main__':
    unittest.main()
