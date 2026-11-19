"""Regressões entre cliente HTTP, contratos, grafo e exportação local."""
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from langsmith import tracing_context
from langsmith.run_helpers import get_tracing_context

from worker.evidencia.langgraph.cliente_llm import ClienteOllama
from worker.evidencia.langgraph.orquestrador import SistemaMultiagentes
from worker.evidencia.langgraph.registro import salvar_execucao


PERGUNTA = "Como ler o material de teste sobre férias?"
FONTE = {
    "fonte": "legislacao", "unidade": "fixture-1",
    "conteudo": "Material fictício para organizar a leitura de informações sobre férias.",
}
PLANO = {"acao": "buscar_evidencias", "argumentos": {"consulta": "material férias"}}
REDACAO = {"acao": "responder", "resposta": "O material organiza a leitura das informações sobre férias [Fonte 1]."}
APROVACAO = {
    "decisao": "aprovar", "evidencia_suficiente": True,
    "problemas": [], "resumo": "O candidato corresponde ao material de teste.",
}


class Busca:
    def buscar(self, consulta):
        return [deepcopy(FONTE)]


class ClienteEmFila:
    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.tracing = []

    def gerar(self, **pedido):
        self.tracing.append(get_tracing_context().get("enabled"))
        return {"dados": deepcopy(self.respostas.pop(0)), "uso": {}, "segundos": 0}


def resposta_http(dados):
    return io.BytesIO(json.dumps({
        "done": True, "done_reason": "stop",
        "message": {"role": "assistant", "content": json.dumps(dados)},
    }).encode())


class TestIntegracaoMultiagentes(unittest.TestCase):
    def test_schema_invalido_do_cliente_real_consumiu_retry_global(self):
        cliente = ClienteOllama()
        invalido = {"acao": "buscar_evidencias", "argumentos": {"consulta": 73}}
        with patch("urllib.request.urlopen", side_effect=[
            resposta_http(invalido), resposta_http(PLANO),
            resposta_http(REDACAO), resposta_http(APROVACAO),
        ]) as abrir:
            estado = SistemaMultiagentes(cliente, Busca()).executar(PERGUNTA)
        self.assertEqual(estado["status"], "aprovada")
        self.assertEqual(estado["chamadas_llm"], 4)
        self.assertEqual(estado["tentativas_tecnicas"], 1)
        self.assertEqual(abrir.call_count, 4)

    def test_tracing_global_nao_recebe_estado_ou_fontes(self):
        cliente = ClienteEmFila([PLANO, REDACAO, APROVACAO])
        with tracing_context(enabled=True):
            estado = SistemaMultiagentes(cliente, Busca()).executar(PERGUNTA)
            self.assertTrue(get_tracing_context()["enabled"])
        self.assertEqual(estado["status"], "aprovada")
        self.assertEqual(cliente.tracing, [False, False, False])

    def test_feedback_cheio_e_guardrail_continuam_revisaveis(self):
        invalida = dict(REDACAO, resposta=REDACAO["resposta"].replace("Fonte 1", "Fonte 99"))
        problemas = [{
            "codigo": f"correcao_{n}", "trecho": "trecho de teste", "fontes": [1],
            "correcao_solicitada": f"Correção de teste {n}.",
        } for n in range(20)]
        revisar = {
            "decisao": "revisar", "evidencia_suficiente": True,
            "problemas": problemas, "resumo": "Revisar o candidato.",
        }
        cliente = ClienteEmFila([PLANO, invalida, revisar, REDACAO, APROVACAO])
        estado = SistemaMultiagentes(cliente, Busca()).executar(PERGUNTA)
        self.assertEqual(estado["status"], "aprovada")
        self.assertEqual(estado["chamadas_llm"], 5)
        self.assertEqual(estado["tentativas_tecnicas"], 0)
        self.assertEqual(len(estado["historico"][0]["feedback"]["problemas"]), 20)
        self.assertLessEqual(len(estado["feedback"]["problemas"]), 20)

    def test_exportacao_inclui_hashes_e_nao_sobrescreve(self):
        cliente = ClienteEmFila([])
        estado = SistemaMultiagentes(cliente, Busca()).executar(
            "Como rescindir contrato de aluguel residencial?", run_id="execucao-teste",
        )
        with tempfile.TemporaryDirectory() as pasta:
            destino = salvar_execucao(estado, Path(pasta), diagrama="graph TD; A-->B;")
            manifesto = json.loads((destino / "manifesto.json").read_text())
            for nome, esperado in manifesto["artefatos_sha256"].items():
                self.assertEqual(hashlib.sha256((destino / nome).read_bytes()).hexdigest(), esperado)
            self.assertNotIn("inicio_monotonic", json.loads((destino / "estado.json").read_text()))
            self.assertEqual(manifesto["chamadas_llm"], 0)
            with self.assertRaises(FileExistsError):
                salvar_execucao(estado, pasta)
            with self.assertRaises(ValueError):
                salvar_execucao(dict(estado, run_id="../outra-pasta"), pasta)


if __name__ == "__main__":
    unittest.main()
