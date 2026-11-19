"""Aceitação da recuperação semântica local com embeddings determinísticos.

Os vetores e textos desta suíte são fictícios. Os testes não baixam modelo,
não usam GPU, banco externo nem legislação como gabarito jurídico.
"""
from copy import deepcopy
from hashlib import sha256
import json
import math
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from worker.evidencia.langgraph.buscador_local import BuscadorLocal, EncoderSentenceTransformer


TEXTOS = (
    "FÉRIAS: material fictício para exercitar a recuperação semântica.",
    "JORNADA: segundo material fictício para os testes do índice.",
    "NOTURNO: terceiro material fictício para os testes do índice.",
)
CONSULTA = "descanso anual remunerado"


def artigo(numero, texto):
    return {
        "artigo_id": sha256(f"fixture-artigo-{numero}".encode()).hexdigest(),
        "caminho_relativo": "fixtures/norma_ficticia.md",
        "identificador_artigo": f"Art. {numero}",
        "caminho_hierarquico": f"Norma fictícia > Seção de teste > Art. {numero}",
        "texto_artigo_completo": texto,
        "texto_original": "CAMPO_ORIGINAL_QUE_NAO_DEVE_SUBSTITUIR_O_TEXTO_COMPLETO",
        "status_declarado": "ficticio_sem_valor_juridico",
        "source": "https://example.org/norma-ficticia",
        "date": "2026-01-01",
        "retrieved": "2026-11-19",
        "sha256_fonte": "f" * 64,
        "tem_alerta_parser": False,
    }


class EmbedderFake:
    """Entrega apenas os vetores previstos; registra cada lote recebido."""

    def __init__(self, vetores=None):
        self.vetores = deepcopy(vetores if vetores is not None else {
            TEXTOS[0]: [4.0, 0.0, 0.0],
            TEXTOS[1]: [0.0, 3.0, 0.0],
            TEXTOS[2]: [0.0, 0.0, 2.0],
            CONSULTA: [9.0, 0.0, 0.0],
        })
        self.chamadas = []

    def encode(self, textos):
        self.chamadas.append(list(textos))
        return [deepcopy(self.vetores[texto]) for texto in textos]


class TestBuscadorLocal(unittest.TestCase):
    def setUp(self):
        temporario = tempfile.TemporaryDirectory()
        self.addCleanup(temporario.cleanup)
        self.root = Path(temporario.name)
        self.corpus = self.root / "artigos.json"
        self.cache = self.root / "cache"
        self.artigos = [artigo(numero, texto)
                        for numero, texto in zip((129, 58, 73), TEXTOS)]
        self.gravar(self.artigos)

    def gravar(self, registros):
        self.corpus.write_text(json.dumps(registros, ensure_ascii=False), encoding="utf-8")

    def buscador(self, embedder=None, **extras):
        opcoes = {
            "cache_dir": self.cache,
            "embedder": embedder if embedder is not None else EmbedderFake(),
            "modelo": "modelo-fake-aceitacao",
            "revisao": "fixture-v1",
            "dimensao": 3,
        }
        opcoes.update(extras)
        instancia = BuscadorLocal(self.corpus, **opcoes)
        self.addCleanup(instancia.fechar)
        return instancia

    def test_sinonimo_sem_sobreposicao_lexical_recupera_artigo_por_cosseno(self):
        fake = EmbedderFake()
        busca = self.buscador(fake)

        fontes = busca.buscar(CONSULTA)

        self.assertEqual(len(fontes), 1)
        self.assertEqual(fontes[0]["unidade"], self.artigos[0]["artigo_id"])
        self.assertAlmostEqual(fontes[0]["similaridade"], 1.0, places=6)
        self.assertEqual(fake.chamadas[-1], [CONSULTA])
        textos_indexados = [texto for lote in fake.chamadas[:-1] for texto in lote]
        self.assertCountEqual(textos_indexados, TEXTOS)

    def test_preserva_texto_completo_e_metadados_da_fonte(self):
        fonte = self.buscador().buscar(CONSULTA)[0]
        original = self.artigos[0]

        self.assertEqual(fonte["fonte"], "legislacao")
        self.assertEqual(fonte["conteudo"], original["texto_artigo_completo"])
        self.assertEqual(fonte["artigo_ref"], original["identificador_artigo"])
        self.assertEqual(fonte["contexto"], original["caminho_hierarquico"])
        for campo in ("caminho_relativo", "status_declarado", "source", "date",
                      "retrieved", "sha256_fonte", "tem_alerta_parser"):
            self.assertEqual(fonte[campo], original[campo], campo)
        self.assertNotIn("texto_original", fonte)

    def test_resultados_e_diagnostico_sao_copias(self):
        busca = self.buscador()
        fonte = busca.buscar(CONSULTA)[0]
        fonte["conteudo"] = "ADULTERADO"
        fonte["source"] = "https://example.org/adulterado"
        diagnostico = busca.diagnostico
        diagnostico["quantidade_artigos"] = -1

        nova_fonte = busca.buscar(CONSULTA)[0]

        self.assertEqual(nova_fonte["conteudo"], TEXTOS[0])
        self.assertEqual(nova_fonte["source"], self.artigos[0]["source"])
        self.assertEqual(busca.diagnostico["quantidade_artigos"], 3)

    def test_preparar_indice_cria_cache_e_registra_hash_da_base(self):
        fake = EmbedderFake()
        busca = self.buscador(fake)

        diagnostico = busca.preparar_indice()

        self.assertEqual(diagnostico["quantidade_artigos"], 3)
        self.assertFalse(diagnostico["cache_reutilizado"])
        self.assertEqual(diagnostico["dimensao"], 3)
        self.assertEqual(diagnostico["corpus_sha256"], sha256(self.corpus.read_bytes()).hexdigest())
        caminho = Path(diagnostico["cache_arquivo"])
        self.assertTrue(caminho.is_file())
        self.assertEqual(caminho.parent, self.cache)
        self.assertTrue(fake.chamadas)
        antes = deepcopy(fake.chamadas)
        busca.preparar_indice()
        self.assertEqual(fake.chamadas, antes)

    def test_segunda_instancia_reutiliza_artigos_mas_codifica_nova_consulta(self):
        primeiro = self.buscador()
        cold = primeiro.preparar_indice()
        primeiro.fechar()
        fake = EmbedderFake({CONSULTA: [1.0, 0.0, 0.0]})
        segundo = self.buscador(fake)

        warm = segundo.preparar_indice()
        fontes = segundo.buscar(CONSULTA)

        self.assertTrue(warm["cache_reutilizado"])
        self.assertEqual(warm["cache_arquivo"], cold["cache_arquivo"])
        self.assertEqual(fake.chamadas, [[CONSULTA]])
        self.assertEqual(fontes[0]["unidade"], self.artigos[0]["artigo_id"])

    def test_alterar_texto_do_corpus_invalida_cache(self):
        antigo = self.buscador().preparar_indice()
        self.artigos[0]["texto_artigo_completo"] += " Revisão do texto fictício."
        self.gravar(self.artigos)
        vetores = deepcopy(EmbedderFake().vetores)
        vetores[self.artigos[0]["texto_artigo_completo"]] = [1.0, 0.0, 0.0]
        fake = EmbedderFake(vetores)

        novo = self.buscador(fake).preparar_indice()

        self.assertFalse(novo["cache_reutilizado"])
        self.assertNotEqual(novo["corpus_sha256"], antigo["corpus_sha256"])
        self.assertNotEqual(novo["cache_arquivo"], antigo["cache_arquivo"])
        self.assertIn(self.artigos[0]["texto_artigo_completo"],
                      [texto for lote in fake.chamadas for texto in lote])

    def test_alterar_modelo_revisao_dimensao_ou_limite_de_tokens_invalida_cache(self):
        antigo = self.buscador().preparar_indice()
        for alteracao in ({"modelo": "outro-modelo-fake"}, {"revisao": "fixture-v2"},
                          {"dimensao": 4}, {"max_tokens": 4096}):
            with self.subTest(alteracao=alteracao):
                vetores = deepcopy(EmbedderFake().vetores)
                if alteracao.get("dimensao") == 4:
                    vetores = {texto: vetor + [0.0] for texto, vetor in vetores.items()}
                fake = EmbedderFake(vetores)
                novo = self.buscador(fake, **alteracao).preparar_indice()
                self.assertFalse(novo["cache_reutilizado"])
                self.assertNotEqual(novo["cache_arquivo"], antigo["cache_arquivo"])
                self.assertTrue(fake.chamadas)

    def test_metadado_alterado_e_reordenacao_da_base_nao_usam_snapshot_antigo(self):
        primeiro = self.buscador().preparar_indice()
        self.artigos[0]["source"] = "https://example.org/origem-atualizada"
        self.artigos.reverse()
        self.gravar(self.artigos)

        busca = self.buscador()
        fonte = busca.buscar(CONSULTA)[0]

        self.assertFalse(busca.diagnostico["cache_reutilizado"])
        self.assertNotEqual(busca.diagnostico["corpus_sha256"], primeiro["corpus_sha256"])
        self.assertEqual(fonte["source"], "https://example.org/origem-atualizada")
        self.assertEqual(fonte["conteudo"], TEXTOS[0])

    def test_cache_corrompido_e_reconstruido(self):
        anterior = self.buscador().preparar_indice()
        caminho = Path(anterior["cache_arquivo"])
        caminho.write_bytes(b"Isto nao e um banco SQLite")
        fake = EmbedderFake()
        busca = self.buscador(fake)

        fontes = busca.buscar(CONSULTA)

        self.assertFalse(busca.diagnostico["cache_reutilizado"])
        self.assertEqual(busca.diagnostico["cache_arquivo"], anterior["cache_arquivo"])
        self.assertTrue(fontes)
        self.assertGreater(len(fake.chamadas), 1)

    def test_blob_adulterado_e_detectado_antes_de_usar_vetores(self):
        anterior = self.buscador().preparar_indice()
        with sqlite3.connect(anterior["cache_arquivo"]) as banco:
            banco.execute("UPDATE vetores SET vetor = ? WHERE posicao = 0", (b"VETOR_ADULTERADO",))
        busca = self.buscador()

        fonte = busca.buscar(CONSULTA)[0]

        self.assertFalse(busca.diagnostico["cache_reutilizado"])
        self.assertEqual(fonte["conteudo"], TEXTOS[0])

    def test_id_incorreto_ou_linha_ausente_no_cache_forca_reconstrucao(self):
        for sql, parametros in (
            ("UPDATE vetores SET unidade = ? WHERE posicao = 0", ("id-inexistente",)),
            ("DELETE FROM vetores WHERE posicao = 0", ()),
        ):
            with self.subTest(sql=sql):
                anterior = self.buscador().preparar_indice()
                with sqlite3.connect(anterior["cache_arquivo"]) as banco:
                    banco.execute(sql, parametros)
                busca = self.buscador()
                self.assertEqual(busca.buscar(CONSULTA)[0]["conteudo"], TEXTOS[0])
                self.assertFalse(busca.diagnostico["cache_reutilizado"])

    def test_erro_do_embedder_nao_deixa_cache_parcial(self):
        class EmbedderFalha(EmbedderFake):
            def encode(self, textos):
                raise RuntimeError("Falha de inferência inserida no teste.")

        with self.assertRaises((ValueError, RuntimeError)):
            self.buscador(EmbedderFalha()).preparar_indice()

        self.assertEqual(list(self.cache.iterdir()) if self.cache.exists() else [], [])

    def test_vetores_invalidos_sao_recusados_sem_cache_parcial(self):
        invalidos = ([0.0, 0.0, 0.0], [1.0, 0.0], [math.nan, 0.0, 0.0],
                     [math.inf, 0.0, 0.0], ["invalido", 0.0, 0.0])
        for numero, vetor in enumerate(invalidos):
            with self.subTest(vetor=vetor):
                vetores = deepcopy(EmbedderFake().vetores)
                vetores[TEXTOS[0]] = vetor
                cache = self.root / f"cache-invalido-{numero}"
                with self.assertRaises(ValueError):
                    self.buscador(EmbedderFake(vetores), cache_dir=cache).preparar_indice()
                self.assertEqual(list(cache.iterdir()) if cache.exists() else [], [])

    def test_vetor_de_consulta_invalido_nao_produz_resultados(self):
        fake = EmbedderFake()
        busca = self.buscador(fake)
        busca.preparar_indice()
        fake.vetores[CONSULTA] = [0.0, 0.0, 0.0]

        with self.assertRaises(ValueError):
            busca.buscar(CONSULTA)

    def test_quantidade_incorreta_de_vetores_nao_cria_cache(self):
        class EmbedderIncompleto(EmbedderFake):
            def encode(self, textos):
                return [[1.0, 0.0, 0.0]]

        with self.assertRaisesRegex(ValueError, "Quantidade"):
            self.buscador(EmbedderIncompleto()).preparar_indice()

        self.assertEqual(list(self.cache.iterdir()) if self.cache.exists() else [], [])

    def test_top_k_limita_resultados_sem_duplicar_documentos(self):
        vetores = deepcopy(EmbedderFake().vetores)
        vetores[CONSULTA] = [1.0, 1.0, 1.0]
        busca = self.buscador(EmbedderFake(vetores), top_k=2)

        fontes = busca.buscar(CONSULTA)

        self.assertEqual(len(fontes), 2)
        self.assertEqual(len({f["unidade"] for f in fontes}), 2)
        self.assertTrue(all(0.35 <= f["similaridade"] <= 1.000001 for f in fontes))

    def test_empate_e_deterministico_independente_da_ordem_dos_registros(self):
        vetores = deepcopy(EmbedderFake().vetores)
        vetores[CONSULTA] = [1.0, 1.0, 1.0]
        antes = self.buscador(EmbedderFake(vetores)).buscar(CONSULTA)
        self.gravar(list(reversed(self.artigos)))

        depois = self.buscador(EmbedderFake(vetores)).buscar(CONSULTA)

        self.assertEqual([f["unidade"] for f in antes], [f["unidade"] for f in depois])

    def test_limiar_sem_evidencia_retorna_lista_vazia(self):
        vetores = deepcopy(EmbedderFake().vetores)
        vetores[CONSULTA] = [-1.0, -1.0, -1.0]

        self.assertEqual(self.buscador(EmbedderFake(vetores)).buscar(CONSULTA), [])

    def test_limiar_um_preserva_vetor_identico_apos_arredondamento_float32(self):
        vetores = {
            TEXTOS[0]: [1.0, 1.0, 1.0],
            TEXTOS[1]: [1.0, -1.0, 0.0],
            TEXTOS[2]: [1.0, 0.0, 0.0],
            CONSULTA: [1.0, 1.0, 1.0],
        }

        fontes = self.buscador(EmbedderFake(vetores), score_minimo=1.0).buscar(CONSULTA)

        self.assertEqual(len(fontes), 1)
        self.assertEqual(fontes[0]["unidade"], self.artigos[0]["artigo_id"])
        self.assertEqual(fontes[0]["similaridade"], 1.0)

    def test_consulta_vazia_nao_carrega_corpus_nem_chama_embedder(self):
        fake = EmbedderFake()
        busca = self.buscador(fake)
        self.corpus.unlink()

        self.assertEqual(busca.buscar("  \n\t"), [])
        self.assertEqual(fake.chamadas, [])
        self.assertFalse(self.cache.exists())

    def test_consulta_com_tipo_invalido_e_recusada(self):
        busca = self.buscador()
        for consulta in (None, 73, [CONSULTA]):
            with self.subTest(consulta=consulta), self.assertRaises(ValueError):
                busca.buscar(consulta)

    def test_corpus_vazio_nao_chama_embedder(self):
        self.gravar([])
        fake = EmbedderFake({})
        busca = self.buscador(fake)

        diagnostico = busca.preparar_indice()

        self.assertEqual(diagnostico["quantidade_artigos"], 0)
        self.assertEqual(busca.buscar(CONSULTA), [])
        self.assertEqual(fake.chamadas, [])

    def test_arquivo_ausente_json_invalido_e_raiz_invalida_sao_erros_claros(self):
        self.corpus.unlink()
        fake = EmbedderFake()
        with self.assertRaises((ValueError, FileNotFoundError)):
            self.buscador(fake).preparar_indice()
        for conteudo in ("{", '{"artigos": []}', '["registro-invalido"]'):
            with self.subTest(conteudo=conteudo):
                self.corpus.write_text(conteudo, encoding="utf-8")
                with self.assertRaises(ValueError):
                    self.buscador(fake).preparar_indice()
        self.assertEqual(fake.chamadas, [])

    def test_ids_repetidos_texto_ausente_e_metadados_invalidos_sao_recusados(self):
        for registros in (
            [self.artigos[0], deepcopy(self.artigos[0])],
            [dict(self.artigos[0], artigo_id="")],
            [dict(self.artigos[0], texto_artigo_completo="  ")],
            [dict(self.artigos[0], texto_artigo_completo=None)],
            [dict(self.artigos[0], caminho_relativo=[])],
            [dict(self.artigos[0], identificador_artigo=73)],
            [dict(self.artigos[0], date={"dia": 1})],
        ):
            with self.subTest(registros=registros):
                self.gravar(registros)
                fake = EmbedderFake()
                with self.assertRaises(ValueError):
                    self.buscador(fake).preparar_indice()
                self.assertEqual(fake.chamadas, [])

    def test_resolve_dados_primeiro_e_data_como_compatibilidade(self):
        for pasta in ("dados", "data"):
            with self.subTest(pasta=pasta):
                raiz = self.root / f"projeto-{pasta}"
                caminho = raiz / pasta / "processed/legislacao/legislacao_artigos_completos.json"
                caminho.parent.mkdir(parents=True)
                caminho.write_text(json.dumps(self.artigos), encoding="utf-8")
                fake = EmbedderFake()
                busca = BuscadorLocal(root=raiz, embedder=fake, modelo="modelo-fake-aceitacao",
                                     revisao="fixture-v1", dimensao=3)
                self.addCleanup(busca.fechar)
                self.assertEqual(busca.buscar(CONSULTA)[0]["conteudo"], TEXTOS[0])
                self.assertTrue(Path(busca.diagnostico["cache_arquivo"]).is_relative_to(
                    raiz / "dados/output"))

    def test_caminho_dados_prevalece_quando_as_duas_bases_existem(self):
        for pasta in ("dados", "data"):
            caminho = self.root / pasta / "processed/legislacao/legislacao_artigos_completos.json"
            caminho.parent.mkdir(parents=True)
            caminho.write_text(json.dumps(self.artigos if pasta == "dados" else []), encoding="utf-8")
        busca = BuscadorLocal(root=self.root, embedder=EmbedderFake(),
                             modelo="modelo-fake-aceitacao", revisao="fixture-v1", dimensao=3)
        self.addCleanup(busca.fechar)

        self.assertEqual(busca.preparar_indice()["quantidade_artigos"], 3)

    def test_consulta_nao_e_persistida_no_cache(self):
        consulta = "CONSULTA_PRIVADA_FICTICIA_QUE_NAO_DEVE_SER_PERSISTIDA"
        fake = EmbedderFake(dict(EmbedderFake().vetores, **{consulta: [1.0, 0.0, 0.0]}))
        busca = self.buscador(fake)

        busca.buscar(consulta)

        cache = Path(busca.diagnostico["cache_arquivo"])
        self.assertNotIn(consulta.encode(), cache.read_bytes())


class TestEncoderSentenceTransformer(unittest.TestCase):
    def encoder(self, **extras):
        parametros = dict(modelo="modelo-fake", revisao="revisao-fixa-de-teste",
                          max_tokens=8, batch_size=2, device="cpu")
        parametros.update(extras)
        return EncoderSentenceTransformer(**parametros)

    def test_carregamento_lazy_revisao_fixa_e_tokenizacao_sem_truncar(self):
        tokenizer = SimpleNamespace(encode=Mock(return_value=[1, 2, 3]))
        modelo = SimpleNamespace(tokenizer=tokenizer, encode=Mock(return_value=[[1.0, 0.0, 0.0]]))
        fabrica = Mock(return_value=modelo)
        modulo_fake = SimpleNamespace(SentenceTransformer=fabrica)
        with patch.dict(sys.modules, {"sentence_transformers": modulo_fake}):
            encoder = self.encoder()
            fabrica.assert_not_called()
            resultado = encoder.encode(["texto integral fictício"])

        fabrica.assert_called_once_with(
            "modelo-fake", revision="revisao-fixa-de-teste", device="cpu", trust_remote_code=False)
        self.assertEqual(modelo.max_seq_length, 8)
        tokenizer.encode.assert_called_once_with(
            "texto integral fictício", add_special_tokens=True, truncation=False)
        modelo.encode.assert_called_once_with(
            ["texto integral fictício"], batch_size=2, normalize_embeddings=True,
            convert_to_numpy=True, show_progress_bar=False)
        self.assertEqual(resultado, [[1.0, 0.0, 0.0]])

    def test_texto_acima_do_limite_falha_antes_da_inferencia(self):
        modelo = SimpleNamespace(tokenizer=SimpleNamespace(encode=Mock(return_value=list(range(9)))),
                                 encode=Mock())
        modulo_fake = SimpleNamespace(SentenceTransformer=Mock(return_value=modelo))
        with patch.dict(sys.modules, {"sentence_transformers": modulo_fake}):
            with self.assertRaisesRegex(ValueError, "limite de tokens") as erro:
                self.encoder().encode(["TEXTO_PRIVADO_FICTICIO"])
        modelo.encode.assert_not_called()
        self.assertNotIn("TEXTO_PRIVADO_FICTICIO", str(erro.exception))

    def test_dependencia_opcional_ausente_so_falha_ao_codificar(self):
        with patch.dict(sys.modules, {"sentence_transformers": None}):
            encoder = self.encoder()
            with self.assertRaisesRegex(RuntimeError, "docs/legado/requirements/requirements-buscador-local.txt"):
                encoder.encode(["texto fictício"])

    def test_falha_no_carregamento_nao_expoe_detalhes_do_backend(self):
        fabrica = Mock(side_effect=RuntimeError("TOKEN_PRIVADO_FICTICIO"))
        with patch.dict(sys.modules, {"sentence_transformers": SimpleNamespace(SentenceTransformer=fabrica)}):
            with self.assertRaises(RuntimeError) as erro:
                self.encoder().encode(["texto fictício"])
        self.assertNotIn("TOKEN_PRIVADO_FICTICIO", str(erro.exception))

    def test_falha_de_inferencia_nao_expoe_textos(self):
        modelo = SimpleNamespace(tokenizer=SimpleNamespace(encode=Mock(return_value=[1, 2])),
                                 encode=Mock(side_effect=RuntimeError("TEXTO_PRIVADO_FICTICIO")))
        with patch.dict(sys.modules, {
            "sentence_transformers": SimpleNamespace(SentenceTransformer=Mock(return_value=modelo))
        }):
            with self.assertRaises(RuntimeError) as erro:
                self.encoder().encode(["TEXTO_PRIVADO_FICTICIO"])
        self.assertNotIn("TEXTO_PRIVADO_FICTICIO", str(erro.exception))


if __name__ == "__main__":
    unittest.main()
