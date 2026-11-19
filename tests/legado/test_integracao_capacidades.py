import json
import tempfile
import unittest
from pathlib import Path

from worker.evidencia.context_window import ContextWindowExceeded, validar_janela_contexto
from worker.evidencia.explicador import (
    FORMATO_SAIDA,
    analisar_saida_estruturada,
    montar_pedido,
    renderizar_saida_estruturada,
    validar_resposta,
)
from worker.evidencia.observabilidade import Observabilidade
from worker.evidencia.stracting import extrair_fatos, rotear_intencao
from avaliacao.juiz import pedido_kaggle


class TestStracting(unittest.TestCase):
    def test_extrai_fatos_explicitos_sem_calcular(self):
        fatos = extrair_fatos(
            "Fui admitida em 02/01/2020 e demitida sem justa causa em 10/03/2024. "
            "Meu salário era R$ 3.500,00. Fazia horas extras e tenho férias vencidas."
        )
        self.assertEqual(fatos.salario_mensal, 3500)
        self.assertEqual(fatos.data_admissao, "2020-01-02")
        self.assertEqual(fatos.data_demissao, "2024-03-10")
        self.assertEqual(fatos.motivo_rescisao, "sem_justa_causa")
        self.assertIs(fatos.horas_extras_mencionadas, True)
        self.assertIs(fatos.ferias_vencidas_mencionadas, True)
        self.assertIn("ferias", fatos.pedidos_mencionados)

    def test_nao_inventa_dado_ausente_e_valida_data(self):
        fatos = extrair_fatos("Tenho dúvida sobre férias; comecei em 31/02/2020.")
        self.assertIsNone(fatos.salario_mensal)
        self.assertIsNone(fatos.data_admissao)
        self.assertIsNone(fatos.data_demissao)
        self.assertEqual(fatos.pedidos_mencionados, ("ferias",))

    def test_classifica_intencoes_sem_disparar_calculos(self):
        self.assertEqual(rotear_intencao("Quanto tempo tenho para entrar com processo?").intencao, "PRESCRICAO")
        calculo = rotear_intencao("Quanto vou receber na rescisão?")
        self.assertEqual(calculo.intencao, "CALCULO")
        self.assertIn("nenhum cálculo", calculo.justificativa)
        self.assertEqual(rotear_intencao("Quais são meus direitos sobre férias?").intencao, "CONSULTA_JURIDICA")


class TestContextWindow(unittest.TestCase):
    def test_reserva_orcamento_para_saida_e_margem(self):
        budget = validar_janela_contexto(
            [{"role": "user", "content": "Explique férias."}],
            max_context_tokens=4096,
            max_output_tokens=500,
            safety_tokens=256,
        )
        self.assertEqual(budget.max_input_tokens, 3340)
        self.assertLessEqual(budget.estimated_input_tokens, budget.max_input_tokens)

    def test_nao_trunca_prompt_juridico_que_excede_limite(self):
        mensagem = [{"role": "user", "content": "evidência " * 4000}]
        with self.assertRaises(ContextWindowExceeded) as contexto:
            validar_janela_contexto(
                mensagem,
                max_context_tokens=4096,
                max_output_tokens=800,
                safety_tokens=256,
            )
        self.assertGreater(contexto.exception.budget.estimated_input_tokens, 3040)


class TestStructuredOutput(unittest.TestCase):
    def setUp(self):
        self.saida = {
            "resposta_direta": "A regra geral depende dos fatos informados. [Fonte 1]",
            "fundamentacao": ["A CLT estabelece o requisito aplicável. [Fonte 1]"],
            "ressalvas": ["Confirme as datas antes de avaliar o caso concreto."],
        }
        self.pedido = {"pedido_sha256": "abc", "formato": FORMATO_SAIDA}

    def test_valida_schema_e_renderiza_texto_para_guardrail(self):
        estrutura = analisar_saida_estruturada(json.dumps(self.saida, ensure_ascii=False))
        texto = renderizar_saida_estruturada(estrutura)
        self.assertIn("Fundamentação:", texto)
        self.assertIn("Limitações e ressalvas:", texto)
        resposta = {"pedido_sha256": "abc", "resposta": json.dumps(self.saida, ensure_ascii=False)}
        self.assertEqual(validar_resposta(self.pedido, resposta), [])

    def test_rejeita_campos_ausentes_extras_e_tipo_invalido(self):
        with self.assertRaises(ValueError):
            analisar_saida_estruturada('{"resposta_direta":"ok"}')
        with self.assertRaises(ValueError):
            analisar_saida_estruturada(json.dumps(dict(self.saida, calculos={}), ensure_ascii=False))
        with self.assertRaises(ValueError):
            analisar_saida_estruturada(json.dumps(dict(self.saida, fundamentacao="texto"), ensure_ascii=False))

    def test_montar_pedido_anexa_extracao_formato_e_orcamento(self):
        class RecuperadorFake:
            def buscar(self, pergunta, config):
                return (
                    [{"fonte": "legislacao", "unidade": "Art. 73", "texto": "Art. 73. Texto legal.",
                      "metadata": {"artigo_ref": "Art. 73"}}],
                    {"segundos": 0.1},
                )

        pedido = montar_pedido(
            "pergunta-1",
            "Meu salário é R$ 3.500,00. Quanto vou receber na rescisão?",
            RecuperadorFake(),
            config=None,
        )
        self.assertEqual(pedido["intencao"], "CALCULO")
        self.assertEqual(pedido["fatos_extraidos"]["salario_mensal"], 3500)
        self.assertEqual(pedido["formato"], FORMATO_SAIDA)
        self.assertIn("FATOS EXTRAÍDOS AUTOMATICAMENTE", pedido["mensagens"][1]["content"])
        self.assertIn("não faça cálculo individualizado", pedido["mensagens"][1]["content"].lower())
        self.assertIn("estimated_input_tokens", pedido["janela_contexto"])
        self.assertEqual(len(pedido["pedido_sha256"]), 64)

    def test_julgamento_tambem_respeita_orcamento_de_contexto(self):
        pedido = pedido_kaggle("j-1", "Pergunta curta.", "responder", [], "Resposta curta.")
        self.assertIn("estimated_input_tokens", pedido["janela_contexto"])
        with self.assertRaises(ContextWindowExceeded):
            pedido_kaggle("j-2", "pergunta " * 12000, "responder", [], "resposta " * 12000)


class TestObservabilidade(unittest.TestCase):
    def test_registra_metricas_sem_texto_ou_identificador_original(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "trace.jsonl"
            observabilidade = Observabilidade(caminho, run_id="run-test")
            observabilidade.registrar(
                "geracao",
                status="ok",
                duracao_ms=12.5,
                pergunta_id="pergunta-identificavel",
                metricas={"prompt_tokens": 120, "aprovada": True},
            )
            registro = json.loads(caminho.read_text(encoding="utf-8"))
            self.assertEqual(registro["etapa"], "geracao")
            self.assertNotIn("pergunta-identificavel", caminho.read_text(encoding="utf-8"))
            self.assertEqual(len(registro["pergunta_id_sha256"]), 64)
            self.assertEqual(registro["metricas"]["prompt_tokens"], 120)

    def test_rejeita_metricas_com_conteudo_textual(self):
        with tempfile.TemporaryDirectory() as pasta:
            observabilidade = Observabilidade(Path(pasta) / "trace.jsonl")
            with self.assertRaises(TypeError):
                observabilidade.registrar("geracao", status="ok", metricas={"prompt": "texto privado"})


if __name__ == "__main__":
    unittest.main()
