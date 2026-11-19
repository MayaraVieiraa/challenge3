"""Empacotamento determinístico sem modelos, banco, rede ou credenciais."""
from contextlib import redirect_stdout
from copy import deepcopy
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from scripts import preparar_multiagentes_kaggle as pacote


def artigo(numero, *, caminho=pacote.CLT_CAMINHO, texto=None):
    referencia = f'Art. {numero}'
    return {
        'artigo_id': sha256(f'{caminho}|{referencia}'.encode()).hexdigest(),
        'caminho_relativo': caminho,
        'identificador_artigo': referencia,
        'caminho_hierarquico': 'CLT > capítulo de teste > ' + referencia,
        'texto_artigo_completo': texto if texto is not None else f'##### {referencia}\nTexto integral de teste.\n\n',
        'status_declarado': 'in_force',
        'source': 'https://www.planalto.gov.br/ccivil_03/decreto-lei/del5452.htm',
        'sha256_fonte': 'a' * 64,
        'tem_alerta_parser': False,
    }


class TestPacoteKaggle(unittest.TestCase):
    def setUp(self):
        self.tempo = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempo.cleanup)
        self.root = Path(self.tempo.name) / 'projeto'
        self.root.mkdir()
        self.patch_root = patch.object(pacote, 'ROOT', self.root)
        self.patch_root.start()
        self.addCleanup(self.patch_root.stop)
        self.registros = [artigo(n) for n in (58, '58-A', 59, '59-A', 73, 75, '75-B',
                                               129, 130, '130-A', 134, 145, 153, 154, 392, 473, 477, 487)]
        # Artigo homônimo de outra norma não pode entrar no recorte.
        self.registros.append(artigo(129, caminho='codigos/codigo-civil-lei-10406-2002.md'))
        self._gravar_base(self.registros)
        for nome in ('__init__.py', 'analista.py', 'contratos.py', 'ferramentas.py'):
            self._gravar(Path('src/multiagentes') / nome, b'"""Modulo permitido de teste."""\n')
        for nome in pacote._INTEGRACAO:
            self._gravar(Path('src/integracao') / nome, b'"""Integracao pura de teste."""\n')
        self._gravar(Path('requirements-multiagentes.txt'), b'langgraph==1.2.22\n')
        self._gravar(pacote.NOTEBOOK_RELATIVO,
                     json.dumps({'nbformat': 4, 'nbformat_minor': 5, 'metadata': {}, 'cells': []}).encode())
        # Arquivos privados próximos dos módulos permanecem fora do ZIP.
        self._gravar(Path('.env.pgvector.local'), b'SENHA_PRIVADA_NAO_EMPACA\n')
        self._gravar(Path('.kaggle/kaggle.json'), b'TOKEN_PRIVADO_NAO_EMPACA\n')
        self._gravar(Path('src/multiagentes/config.env'), b'SEGREDO_PRIVADO_NAO_EMPACA\n')
        self._gravar(Path('src/integracao/nao_permitido.py'), b'NAO_DEVE_ENTRAR\n')

    def _gravar(self, relativo, dados):
        destino = self.root / relativo
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(dados)

    def _gravar_base(self, registros):
        self._gravar(pacote.BASE_RELATIVA, json.dumps(registros, ensure_ascii=False).encode())

    def _preparar(self, tema='ferias', nome='saida'):
        return pacote.preparar_pacote(self.root / nome, tema=tema)

    def test_corpus_preserva_artigos_completos_e_proveniencia(self):
        original = (self.root / pacote.BASE_RELATIVA).read_bytes()
        destino = self._preparar()
        corpus = json.loads((destino / 'corpus_legislacao.json').read_bytes())
        esperados = {r['artigo_id']: r for r in self.registros
                     if r['caminho_relativo'] == pacote.CLT_CAMINHO
                     and r['identificador_artigo'] in ('Art. 129', 'Art. 130', 'Art. 130-A',
                                                       'Art. 134', 'Art. 145', 'Art. 153')}
        self.assertEqual(len(corpus), len(esperados))
        for fonte in corpus:
            registro = esperados[fonte['unidade']]
            self.assertEqual(fonte['conteudo'], registro['texto_artigo_completo'])
            self.assertEqual(fonte['artigo_ref'], registro['identificador_artigo'])
            self.assertEqual(fonte['source'], registro['source'])
            self.assertEqual(fonte['sha256_fonte'], registro['sha256_fonte'])
            self.assertEqual(fonte['fonte'], 'legislacao')
        self.assertEqual((self.root / pacote.BASE_RELATIVA).read_bytes(), original)

    def test_manifesto_cobre_hashes_ids_base_notebook_e_inventario(self):
        destino = self._preparar()
        manifesto = json.loads((destino / 'manifesto_pacote.json').read_bytes())
        self.assertEqual(manifesto['modo'], 'corpus')
        self.assertEqual(set(manifesto['arquivos']),
                         {'runtime.zip', 'corpus_legislacao.json', 'LEIA_ME.md', pacote.NOTEBOOK_PACOTE})
        for nome, identidade in manifesto['arquivos'].items():
            dados = (destino / nome).read_bytes()
            self.assertEqual(identidade, {'sha256': sha256(dados).hexdigest(), 'bytes': len(dados)})
        base = (self.root / pacote.BASE_RELATIVA).read_bytes()
        self.assertEqual(manifesto['base']['sha256'], sha256(base).hexdigest())
        self.assertEqual(manifesto['base']['bytes'], len(base))
        corpus = json.loads((destino / 'corpus_legislacao.json').read_bytes())
        self.assertEqual(manifesto['selecao']['quantidade_artigos'], len(corpus))
        for selecionado, fonte in zip(manifesto['selecao']['artigos'], corpus):
            self.assertEqual(selecionado['unidade'], fonte['unidade'])
            self.assertEqual(selecionado['sha256_conteudo'], sha256(fonte['conteudo'].encode()).hexdigest())
        with ZipFile(destino / 'runtime.zip') as runtime:
            self.assertEqual(set(runtime.namelist()), set(manifesto['runtime']['arquivos']))
            for nome in runtime.namelist():
                dados = runtime.read(nome)
                self.assertEqual(manifesto['runtime']['arquivos'][nome],
                                 {'sha256': sha256(dados).hexdigest(), 'bytes': len(dados)})
            self.assertTrue(all(not nome.endswith('/') and not nome.startswith('/') for nome in runtime.namelist()))

    def test_runtime_nao_inclui_credenciais_arquivos_aleatorios_ou_cache(self):
        destino = self._preparar()
        with ZipFile(destino / 'runtime.zip') as runtime:
            nomes = runtime.namelist()
            conteudo = b''.join(runtime.read(n) for n in nomes)
            self.assertNotIn('src/integracao/nao_permitido.py', nomes)
            self.assertFalse(any('.env' in n or '.kaggle' in n or '__pycache__' in n for n in nomes))
            for segredo in (b'SENHA_PRIVADA', b'TOKEN_PRIVADO', b'SEGREDO_PRIVADO', b'NAO_DEVE_ENTRAR'):
                self.assertNotIn(segredo, conteudo)

    def test_pacote_e_reproduzivel_e_nao_remove_arquivo_existente(self):
        destino = self.root / 'saida'
        destino.mkdir()
        outro = destino / 'nao_remover.txt'
        outro.write_text('preservar')
        self._preparar()
        antes = {p.name: p.read_bytes() for p in destino.iterdir()}
        self._preparar()
        self.assertEqual(antes, {p.name: p.read_bytes() for p in destino.iterdir()})
        self.assertEqual(outro.read_text(), 'preservar')

    def test_temas_preservam_sufixos_e_limitam_noturno(self):
        esperados = {
            'noturno': {'Art. 73'},
            'jornada': {'Art. 58', 'Art. 58-A', 'Art. 59', 'Art. 59-A', 'Art. 73', 'Art. 75', 'Art. 75-B'},
        }
        for tema, referencias in esperados.items():
            with self.subTest(tema=tema):
                destino = self._preparar(tema, nome=tema)
                corpus = json.loads((destino / 'corpus_legislacao.json').read_bytes())
                self.assertEqual({f['artigo_ref'] for f in corpus}, referencias)
        destino = self._preparar('todos', nome='todos')
        referencias = {f['artigo_ref'] for f in json.loads((destino / 'corpus_legislacao.json').read_bytes())}
        self.assertTrue({'Art. 392', 'Art. 473', 'Art. 477', 'Art. 487'}.issubset(referencias))
        self.assertNotIn('Art. 154', referencias)

    def test_limites_recusam_corpus_sem_truncar_nem_criar_saida(self):
        self._gravar_base([artigo(129, texto='x' * pacote.MAX_BYTES_CORPUS)])
        with self.assertRaisesRegex(ValueError, 'excede'):
            self._preparar()
        self.assertFalse((self.root / 'saida').exists())

    def test_base_invalida_sem_texto_ou_com_id_duplicado_e_recusada(self):
        invalido = artigo(129)
        for base in ({'errado': []}, [dict(invalido, texto_artigo_completo='')], [invalido, deepcopy(invalido)]):
            with self.subTest(base=type(base).__name__):
                self._gravar_base(base)
                with self.assertRaises(ValueError):
                    self._preparar()

    def test_notebook_obrigatorio_e_recusado_se_ausente(self):
        (self.root / pacote.NOTEBOOK_RELATIVO).unlink()
        with self.assertRaisesRegex(ValueError, 'obrigatório ausente'):
            self._preparar()
        self.assertFalse((self.root / 'saida').exists())

    def test_symlink_de_runtime_nao_empacota_arquivo_externo(self):
        fora = Path(self.tempo.name) / 'fora.py'
        fora.write_text('credencial externa')
        (self.root / 'src/multiagentes/atalho.py').symlink_to(fora)
        with self.assertRaisesRegex(ValueError, 'não regular'):
            self._preparar()

    def test_main_aceita_destino_e_tema_e_nao_faz_upload(self):
        destino = self.root / 'linha_comando'
        saida = StringIO()
        with redirect_stdout(saida):
            pacote.main(['--destino', str(destino), '--tema', 'noturno'])
        self.assertTrue((destino / 'runtime.zip').is_file())
        self.assertIn('Nenhum arquivo foi enviado', saida.getvalue())


if __name__ == '__main__':
    unittest.main()
