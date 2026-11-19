"""Recuperação semântica de artigos completos, com cache SQLite local.

Importar este módulo não baixa modelos nem exige NumPy/PyTorch. O backend real
é carregado somente ao codificar textos; testes injetam um encoder determinístico.
"""
from __future__ import annotations

from array import array
from copy import deepcopy
from hashlib import sha256
import json
import math
from numbers import Real
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile


MODELO_EMBEDDINGS = 'BAAI/bge-m3'
REVISAO_EMBEDDINGS = '5617a9f61b028005a4858fdac845db406aefb181'
VERSAO_CACHE = 'buscador-local-v1'
BASE_RELATIVA = Path('dados/processed/legislacao/legislacao_artigos_completos.json')
BASE_ALTERNATIVA = Path('data/processed/legislacao/legislacao_artigos_completos.json')
ROOT = Path(__file__).resolve().parents[3]
_CAMPOS_TEXTO = ('caminho_relativo', 'identificador_artigo', 'caminho_hierarquico',
                 'status_declarado', 'source', 'date', 'retrieved', 'sha256_fonte')


def _json(valor):
    return json.dumps(valor, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(',', ':'))


def resolver_corpus(root=None):
    """Prefere o layout atual e aceita ``data/`` como caminho legado."""
    root = Path(root) if root is not None else ROOT
    for relativo in (BASE_RELATIVA, BASE_ALTERNATIVA):
        caminho = root / relativo
        if caminho.is_file():
            return caminho
    raise FileNotFoundError(
        'Base de legislação ausente em dados/processed/ ou data/processed/. '
        'Informe o caminho do JSON; em um clone com DVC configurado, obtenha os dados com dvc pull.'
    )


class EncoderSentenceTransformer:
    """BGE-M3 com revisão fixa, sem código remoto e sem truncamento silencioso."""

    def __init__(self, *, modelo, revisao, max_tokens, batch_size, device):
        self.modelo = modelo
        self.revisao = revisao
        self.max_tokens = max_tokens
        self.batch_size = batch_size
        self.device = device
        self._encoder = None

    def _carregar(self):
        if self._encoder is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError:
                raise RuntimeError(
                    'Instale os embeddings com python -m pip install -r docs/legado/requirements/requirements-buscador-local.txt.'
                ) from None
            try:
                encoder = SentenceTransformer(
                    self.modelo, revision=self.revisao, device=self.device,
                    trust_remote_code=False,
                )
                encoder.max_seq_length = self.max_tokens
            except Exception:
                raise RuntimeError('Não foi possível carregar o modelo de embeddings configurado.') from None
            self._encoder = encoder
        return self._encoder

    def encode(self, textos):
        encoder = self._carregar()
        # A fonte entregue aos agentes permanece integral. Se uma entrada não
        # couber no encoder, falhar explicitamente evita indexar só seu começo.
        for texto in textos:
            tokens = encoder.tokenizer.encode(texto, add_special_tokens=True, truncation=False)
            if len(tokens) > self.max_tokens:
                raise ValueError(
                    'Texto excede o limite de tokens do encoder; prepare segmentação antes de indexar.'
                )
        try:
            return encoder.encode(
                textos, batch_size=self.batch_size, normalize_embeddings=True,
                convert_to_numpy=True, show_progress_bar=False,
            )
        except Exception:
            raise RuntimeError('Não foi possível gerar os embeddings solicitados.') from None

    def fechar(self):
        self._encoder = None


class BuscadorLocal:
    """Busca por cosseno, mantendo artigos completos e metadados da base original.

    Uma instância mantém seu snapshot até ``fechar``. Uma nova instância lê o
    corpus novamente e só reutiliza vetores se toda a identidade do cache bater.
    O limiar de similaridade é uma heurística configurável, não prova jurídica.
    """

    def __init__(self, caminho=None, *, cache_dir=None, embedder=None,
                 modelo=MODELO_EMBEDDINGS, revisao=REVISAO_EMBEDDINGS,
                 dimensao=1024, max_tokens=8192, batch_size=4, device='cpu',
                 top_k=6, score_minimo=0.35, root=None):
        for nome, valor, minimo, maximo in (
            ('dimensao', dimensao, 1, 65536), ('max_tokens', max_tokens, 4, 8192),
            ('batch_size', batch_size, 1, 1024), ('top_k', top_k, 1, 6),
        ):
            if isinstance(valor, bool) or not isinstance(valor, int) or not minimo <= valor <= maximo:
                raise ValueError(f'{nome} fora dos limites permitidos.')
        if (isinstance(score_minimo, bool) or not isinstance(score_minimo, Real)
                or not math.isfinite(score_minimo) or not -1 <= score_minimo <= 1):
            raise ValueError('score_minimo deve ser um número finito entre -1 e 1.')
        if not isinstance(modelo, str) or not modelo.strip() or not isinstance(revisao, str) or not revisao.strip():
            raise ValueError('Modelo e revisão dos embeddings são obrigatórios.')
        if not isinstance(device, str) or not device.strip():
            raise ValueError('Dispositivo de embeddings inválido.')
        if embedder is not None and not callable(getattr(embedder, 'encode', None)):
            raise ValueError('O encoder precisa implementar encode(textos).')
        self.root = Path(root) if root is not None else ROOT
        self.caminho = Path(caminho) if caminho is not None else None
        self.cache_dir = Path(cache_dir) if cache_dir is not None else self.root / 'dados/output/buscador_local'
        self.dimensao, self.top_k, self.score_minimo = dimensao, top_k, float(score_minimo)
        self.embedder = embedder if embedder is not None else EncoderSentenceTransformer(
            modelo=modelo, revisao=revisao, max_tokens=max_tokens,
            batch_size=batch_size, device=device,
        )
        self._config = {
            'versao': VERSAO_CACHE, 'modelo': modelo, 'revisao': revisao,
            'dimensao': dimensao, 'max_tokens': max_tokens,
            'representacao': 'texto_artigo_completo-sem-prefixo-v1',
            'normalizacao': 'l2-float32-le-v1',
            'backend': type(self.embedder).__module__ + '.' + type(self.embedder).__qualname__,
        }
        self._fontes = self._vetores = self._identidade = None
        self._diagnostico = {}

    @property
    def diagnostico(self):
        return deepcopy(self._diagnostico)

    def _ler_corpus(self):
        caminho = self.caminho if self.caminho is not None else resolver_corpus(self.root)
        try:
            dados = caminho.read_bytes()
        except FileNotFoundError:
            raise FileNotFoundError('Arquivo JSON de legislação não encontrado.') from None
        except OSError:
            raise ValueError('Não foi possível ler a base de legislação.') from None
        try:
            registros = json.loads(dados.decode('utf-8-sig'))
        except (ValueError, UnicodeError):
            raise ValueError('A base de legislação deve conter JSON UTF-8 válido.') from None
        if not isinstance(registros, list):
            raise ValueError('A base de legislação deve ser uma lista de artigos.')
        fontes, ids = [], set()
        for registro in registros:
            if not isinstance(registro, dict):
                raise ValueError('Registro da base deve ser um objeto JSON.')
            unidade, texto = registro.get('artigo_id'), registro.get('texto_artigo_completo')
            if not isinstance(unidade, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:/#-]{0,255}', unidade):
                raise ValueError('Artigo sem identificador válido.')
            if unidade in ids:
                raise ValueError('Identificador de artigo duplicado na base.')
            if not isinstance(texto, str) or not texto.strip():
                raise ValueError('Artigo sem texto completo não vazio.')
            for campo in _CAMPOS_TEXTO:
                if registro.get(campo) is not None and not isinstance(registro[campo], str):
                    raise ValueError('Metadado textual inválido na base de legislação.')
            for campo in ('caminho_relativo', 'identificador_artigo'):
                if not isinstance(registro.get(campo), str) or not registro[campo].strip():
                    raise ValueError('Artigo sem norma ou referência do dispositivo.')
            if ('tem_alerta_parser' in registro and not isinstance(registro['tem_alerta_parser'], bool)):
                raise ValueError('Alerta de parser deve ser booleano.')
            ids.add(unidade)
            fonte = dict(
                fonte='legislacao', unidade=unidade, conteudo=texto,
                artigo_ref=registro['identificador_artigo'],
                caminho_relativo=registro['caminho_relativo'],
                contexto=registro.get('caminho_hierarquico'),
                status_declarado=registro.get('status_declarado'),
            )
            for campo in ('source', 'date', 'retrieved', 'sha256_fonte', 'tem_alerta_parser'):
                if campo in registro:
                    fonte[campo] = registro[campo]
            fontes.append(fonte)
        return fontes, sha256(dados).hexdigest()

    def _vetor_normalizado(self, vetor):
        if isinstance(vetor, (str, bytes, dict)):
            raise ValueError('Embedding deve ser uma sequência numérica.')
        try:
            valores = list(vetor)
        except TypeError:
            raise ValueError('Embedding deve ser uma sequência numérica.') from None
        if len(valores) != self.dimensao:
            raise ValueError('Dimensão do embedding incompatível com a configuração.')
        if any(isinstance(v, bool) or not isinstance(v, Real) or not math.isfinite(v) for v in valores):
            raise ValueError('Embedding contém componentes não numéricos ou não finitos.')
        norma = math.hypot(*valores)
        if not math.isfinite(norma) or norma == 0:
            raise ValueError('Embedding tem norma zero ou inválida.')
        return array('f', (v / norma for v in valores))

    def _codificar(self, textos):
        if not textos:
            return []
        recebidos = self.embedder.encode(list(textos))
        if isinstance(recebidos, (str, bytes, dict)):
            raise ValueError('O encoder deve retornar uma matriz de embeddings.')
        try:
            recebidos = list(recebidos)
        except TypeError:
            raise ValueError('O encoder deve retornar uma matriz de embeddings.') from None
        if len(recebidos) != len(textos):
            raise ValueError('Quantidade de embeddings difere da quantidade de textos.')
        return [self._vetor_normalizado(v) for v in recebidos]

    @staticmethod
    def _blob(vetor):
        copia = array('f', vetor)
        if copia.itemsize != 4:
            raise RuntimeError('Esta plataforma não oferece float32 compatível com o cache.')
        if sys.byteorder != 'little':
            copia.byteswap()
        return copia.tobytes()

    def _ler_cache(self, arquivo, identidade, fontes):
        if not arquivo.is_file() or arquivo.is_symlink():
            return None
        conexao = None
        try:
            conexao = sqlite3.connect(arquivo.resolve().as_uri() + '?mode=ro', uri=True)
            linha = conexao.execute("SELECT valor FROM metadados WHERE chave='identidade'").fetchone()
            if linha is None or json.loads(linha[0]) != identidade:
                return None
            registros = conexao.execute(
                'SELECT posicao, unidade, sha256_texto, vetor, sha256_vetor FROM vetores ORDER BY posicao'
            ).fetchall()
            if len(registros) != len(fontes):
                return None
            vetores = []
            for posicao, (registro, fonte) in enumerate(zip(registros, fontes)):
                ordem, unidade, hash_texto, blob, hash_vetor = registro
                if (ordem != posicao or unidade != fonte['unidade']
                        or hash_texto != sha256(fonte['conteudo'].encode('utf-8')).hexdigest()
                        or not isinstance(blob, bytes) or len(blob) != self.dimensao * 4
                        or sha256(blob).hexdigest() != hash_vetor):
                    return None
                vetor = array('f')
                vetor.frombytes(blob)
                if sys.byteorder != 'little':
                    vetor.byteswap()
                if any(not math.isfinite(v) for v in vetor) or not math.isclose(
                    math.hypot(*vetor), 1.0, rel_tol=1e-5, abs_tol=1e-5,
                ):
                    return None
                vetores.append(vetor)
            return vetores
        except (sqlite3.Error, OSError, ValueError, TypeError):
            return None
        finally:
            if conexao is not None:
                conexao.close()

    def _salvar_cache(self, arquivo, identidade, fontes, vetores):
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        descritor, temporario = tempfile.mkstemp(prefix='.indice-', suffix='.sqlite3', dir=self.cache_dir)
        os.close(descritor)
        conexao = None
        try:
            conexao = sqlite3.connect(temporario)
            conexao.execute('CREATE TABLE metadados (chave TEXT PRIMARY KEY, valor TEXT NOT NULL)')
            conexao.execute('CREATE TABLE vetores (posicao INTEGER PRIMARY KEY, unidade TEXT NOT NULL, '
                            'sha256_texto TEXT NOT NULL, vetor BLOB NOT NULL, sha256_vetor TEXT NOT NULL)')
            conexao.execute('INSERT INTO metadados VALUES (?, ?)', ('identidade', _json(identidade)))
            for posicao, (fonte, vetor) in enumerate(zip(fontes, vetores)):
                blob = self._blob(vetor)
                conexao.execute('INSERT INTO vetores VALUES (?, ?, ?, ?, ?)', (
                    posicao, fonte['unidade'], sha256(fonte['conteudo'].encode('utf-8')).hexdigest(),
                    blob, sha256(blob).hexdigest(),
                ))
            conexao.commit()
            conexao.close()
            conexao = None
            os.replace(temporario, arquivo)
        finally:
            if conexao is not None:
                conexao.close()
            Path(temporario).unlink(missing_ok=True)

    def preparar_indice(self):
        if self._fontes is not None:
            return self.diagnostico
        fontes, corpus_sha = self._ler_corpus()
        identidade = dict(self._config, corpus_sha256=corpus_sha, quantidade_artigos=len(fontes))
        chave = sha256(_json(identidade).encode('utf-8')).hexdigest()
        arquivo = self.cache_dir / f'{chave}.sqlite3'
        vetores = self._ler_cache(arquivo, identidade, fontes)
        reutilizado = vetores is not None
        if vetores is None:
            vetores = self._codificar([f['conteudo'] for f in fontes])
            self._salvar_cache(arquivo, identidade, fontes, vetores)
        self._fontes, self._vetores, self._identidade = fontes, vetores, identidade
        self._diagnostico = dict(
            quantidade_artigos=len(fontes), cache_reutilizado=reutilizado,
            cache_arquivo=str(arquivo), corpus_sha256=corpus_sha, dimensao=self.dimensao,
            modelo=self._config['modelo'], revisao=self._config['revisao'],
            max_tokens=self._config['max_tokens'],
        )
        return self.diagnostico

    def buscar(self, consulta):
        if not isinstance(consulta, str):
            raise ValueError('A consulta deve ser um texto.')
        if not consulta.strip():
            return []
        self.preparar_indice()
        if not self._fontes:
            return []
        consulta_vetor = self._codificar([consulta])[0]
        norma_consulta = math.hypot(*consulta_vetor)
        pontuadas = []
        for indice, vetor in enumerate(self._vetores):
            # Corrige o arredondamento da normalização float32. Um vetor
            # idêntico deve atingir cosseno 1, inclusive com limiar igual a 1.
            produto = math.fsum(a * b for a, b in zip(vetor, consulta_vetor))
            escore = max(-1.0, min(1.0, produto / (math.hypot(*vetor) * norma_consulta)))
            if math.isclose(abs(escore), 1.0, rel_tol=0, abs_tol=1e-12):
                escore = math.copysign(1.0, escore)
            if escore >= self.score_minimo:
                pontuadas.append((escore, indice))
        pontuadas.sort(key=lambda par: (-par[0], self._fontes[par[1]]['unidade']))
        fontes = []
        for escore, indice in pontuadas[:self.top_k]:
            fonte = deepcopy(self._fontes[indice])
            fonte['similaridade'] = round(escore, 8)
            fontes.append(fonte)
        return fontes

    def fechar(self):
        self._fontes = self._vetores = self._identidade = None
        self._diagnostico = {}
        fechar = getattr(self.embedder, 'fechar', None)
        if callable(fechar):
            fechar()
