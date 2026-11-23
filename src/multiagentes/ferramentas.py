"""Buscas sintética, lexical portátil e adaptador do recuperador já existente."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import json
import math
from pathlib import Path
import re
import unicodedata

from .buscador_local import BuscadorLocal


_STOPWORDS = frozenset('''a ao aos aquela aquelas aquele aqueles aquilo as ate com como contra da das de
dela delas dele deles depois do dos e ela elas ele eles em entre era eram essa essas esse esses esta
estao estas estava estavam este estes estou eu foi foram ha isso isto ja lhe lhes mais mas me mesmo
meu meus minha minhas muito na nas nem no nos nossa nossas nosso nossos num numa o os ou para pela
pelas pelo pelos por porque qual quais quando quanto quantas quantos que quem sao se sem seu seus
sua suas tambem te tem temos tendo tenho ter teu teus toda todas todo todos tua tuas um uma umas uns
voce voces pode podem poderia quais seria seriam ser sobre favor acordo segundo'''.split())


def _termos_portugues(texto):
    normalizado = ''.join(c for c in unicodedata.normalize('NFD', texto.casefold())
                          if unicodedata.category(c) != 'Mn')
    palavras = set(re.findall(r'[a-z]{3,}', normalizado)) - _STOPWORDS
    # Números e sufixos distinguem "art. 129-A". Uma entrada só com números
    # permanece sem termos de busca para evitar consultas numéricas sem tema.
    return palavras | set(re.findall(r'\d+(?:-[a-z])?', normalizado)) if palavras else set()


def _ordem_estrutural(fonte):
    """Desempata artigos pela ordem da norma, sem mudar o escore lexical."""
    caminho = (fonte.get('caminho_relativo') or '').replace('\\', '/').casefold()
    referencia = (fonte.get('artigo_ref') or '').strip().casefold()
    artigo = re.fullmatch(
        r'(?:art(?:igo)?\.?\s*)?(\d+)\s*[º°ª]?(?:\s*[-–—]\s*([a-z]+))?\.?',
        referencia,
    )
    if artigo:
        return (caminho, 0, int(artigo[1]), artigo[2] or '', '', fonte['unidade'])
    # Referências ausentes ou não reconhecidas continuam com ordenação estável.
    return (caminho, 1, 0, '', referencia, fonte['unidade'])


class BuscaCorpus:
    """Busca lexical IDF em fontes portáteis; não usa embeddings, banco ou reranker.

    A entrada é uma lista JSON no formato de ``fonte_para_prompt``. O índice é
    preparado na primeira consulta com termos; documentos preservam seu texto
    integral e cada unidade aparece no máximo uma vez no resultado. Somente em
    empate de escore, a ordenação usa caminho da norma, número/sufixo do artigo
    e, por último, o identificador da unidade.
    """

    def __init__(self, caminho: Path):
        self.caminho = Path(caminho)
        self._fontes = None
        self._termos = None
        self._idf = None

    def _carregar(self):
        if self._fontes is not None:
            return
        try:
            recebidas = json.loads(self.caminho.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError, UnicodeError):
            raise ValueError('Não foi possível ler o corpus portátil como JSON UTF-8.') from None
        if not isinstance(recebidas, list):
            raise ValueError('O corpus portátil deve ser uma lista de fontes.')
        fontes = {}
        for fonte in recebidas:
            if not isinstance(fonte, dict) or fonte.get('fonte') != 'legislacao':
                raise ValueError('O corpus portátil aceita somente fontes de legislação no formato canônico.')
            unidade = fonte.get('unidade')
            texto = fonte.get('conteudo')
            if not isinstance(unidade, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:/#-]{0,255}', unidade):
                raise ValueError('Fonte do corpus com identificador ausente ou inválido.')
            if not isinstance(texto, str) or not texto.strip():
                raise ValueError('Fonte do corpus com conteúdo ausente ou vazio.')
            for campo in ('artigo_ref', 'caminho_relativo', 'contexto', 'titulo'):
                if fonte.get(campo) is not None and not isinstance(fonte[campo], str):
                    raise ValueError('Metadado textual inválido no corpus portátil.')
            if unidade in fontes:
                if fontes[unidade]['conteudo'] != texto:
                    raise ValueError('Identificador repetido com conteúdo divergente no corpus portátil.')
                continue
            fontes[unidade] = deepcopy(fonte)
        termos = {
            unidade: _termos_portugues(' '.join(
                fonte.get(campo) or '' for campo in ('conteudo', 'artigo_ref', 'contexto', 'titulo')
            ))
            for unidade, fonte in fontes.items()
        }
        frequencias = Counter(termo for conjunto in termos.values() for termo in conjunto)
        total = len(fontes)
        self._idf = {
            termo: math.log(1 + (total - frequencia + 0.5) / (frequencia + 0.5))
            for termo, frequencia in frequencias.items()
        }
        self._termos = termos
        self._fontes = fontes

    def buscar(self, consulta):
        if not isinstance(consulta, str):
            raise ValueError('A consulta deve ser um texto.')
        termos = _termos_portugues(consulta)
        if not termos:
            return []
        self._carregar()
        pontuadas = []
        for unidade, termos_documento in self._termos.items():
            comuns = termos & termos_documento
            if comuns:
                # A ordenação dos termos evita diferenças de soma por hash seed.
                escore = math.fsum(self._idf[termo] for termo in sorted(comuns))
                if escore > 0:
                    pontuadas.append((escore, unidade))
        pontuadas.sort(key=lambda par: (-par[0], _ordem_estrutural(self._fontes[par[1]])))
        return [deepcopy(self._fontes[unidade]) for _, unidade in pontuadas[:6]]

    def fechar(self):
        self._fontes = self._termos = self._idf = None


class BuscaSintetica:
    """Material de teste; não contém legislação, decisão ou orientação jurídica."""

    def __init__(self, caso='ferias'):
        if caso not in ('ferias', 'sem_evidencia'):
            raise ValueError('Caso sintético desconhecido.')
        self.caso = caso

    def buscar(self, consulta):
        if not isinstance(consulta, str):
            raise ValueError('A consulta deve ser um texto.')
        texto = ''.join(c for c in unicodedata.normalize('NFD', consulta.casefold())
                        if unicodedata.category(c) != 'Mn')
        if self.caso == 'sem_evidencia' or not re.search(r'\bferias\b', texto):
            return []
        return [dict(
            fonte='legislacao', unidade='sintetica-ferias-001', sintetica=True,
            titulo='Material fictício — teste de fluxo',
            contexto='Material educativo fictício de teste sobre a leitura de informações sobre férias.',
            conteudo=('Este material educativo de teste explica como organizar a leitura de informações sobre férias. '
                      'As condições devem ser conferidas nas fontes oficiais. Não define prazos, valores ou direitos.'),
            caminho_relativo='fixtures/material_ficticio_ferias.txt', artigo_ref=None,
            status_declarado='ficticio_sem_valor_juridico',
        )]

    def fechar(self):
        pass


FONTES_BUSCA = ('legislacao', 'jurisprudencia', 'precedentes')


def intercalar_por_fonte(fontes):
    """Ordena as fontes alternando as bases (1º artigo, 1ª decisão, 1º precedente, 2º artigo...).

    O orquestrador guarda as fontes em ordem até o orçamento de bytes (`max_bytes_fontes`). Na ordem da busca
    (3 artigos, depois 3 decisões, depois 3 precedentes), os artigos ocupavam quase todo o orçamento e as outras
    bases ficavam de fora. Intercaladas, cada base tem a sua melhor fonte antes da segunda de qualquer outra.
    A ordem dentro de cada base é mantida.
    """
    grupos = {}
    for fonte in fontes:
        grupos.setdefault(fonte.get('fonte'), []).append(fonte)
    ordem = [f for f in FONTES_BUSCA if f in grupos] + [f for f in grupos if f not in FONTES_BUSCA]
    saida = []
    for i in range(max((len(g) for g in grupos.values()), default=0)):
        saida += [grupos[f][i] for f in ordem if i < len(grupos[f])]
    return saida


class BuscaReal:
    """Abre banco e modelos apenas quando uma busca for efetivamente solicitada."""

    def __init__(self, root: Path, device='cpu'):
        self.root = Path(root)
        self.device = device
        self._recuperador = None

    def _abrir(self):
        if self._recuperador is None:
            from src.integracao.recuperacao import Recuperador
            from src.storage.pgvector_store import load_database_url

            conexao = load_database_url(self.root / '.env.pgvector.local')
            self._recuperador = Recuperador(conexao, device=self.device, carregar_reranker=True)
        return self._recuperador

    def buscar(self, consulta):
        if not isinstance(consulta, str) or not consulta.strip():
            raise ValueError('A consulta deve ser um texto não vazio.')
        from src.integracao.geracao import fonte_para_prompt
        from src.integracao.recuperacao import Configuracao

        # 3 bases, como a configuração padrão da integração (2026-11-23): 3 artigos, 3 decisões e 3 precedentes,
        # união no reranker nos precedentes e sinônimos jurídicos. Antes, os multiagentes usavam só 2 bases.
        configuracao = Configuracao(fontes=FONTES_BUSCA,
                                    entrega_por_fonte={'legislacao': 3, 'jurisprudencia': 3, 'precedentes': 3},
                                    top_k=10, lexical_modo='idf', reranker_max_length=256,
                                    uniao_reranker=('precedentes',), expandir_sinonimos=True)
        unidades, _ = self._abrir().buscar(consulta, configuracao)
        return intercalar_por_fonte([fonte_para_prompt(unidade) for unidade in unidades])

    def preparar_lexico(self):
        """Preparação explícita para banco já provisionado; não roda nas buscas."""
        return self._abrir().preparar_lexico()

    def fechar(self):
        if self._recuperador is not None:
            self._recuperador.fechar()
            self._recuperador = None
