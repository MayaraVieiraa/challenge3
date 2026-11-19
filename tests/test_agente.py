"""Testes unitários e de integração para o Agente LexIA (Challenge 3).

Cobre as 6 capacidades essenciais:
1. Tool Calling (Cálculos de rescisão e prescrição)
2. Stracting / Routing (Extração de fatos e classificação de intenções)
3. Prompt Caching (Hit/Miss, chave canônica SHA-256 e métricas)
4. Context Window Management (Sliding window, poda de ferramentas e orçamento de tokens)
5. Structured Output (Pydantic RespostaEstruturada e resiliência)
6. Observabilidade (Tracer, Spans, latências e exportação CSV/JSON)
"""

import unittest
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import json
import shutil

from src.agente.schemas import (
    RespostaEstruturada,
    FatosCaso,
    CalculoRescisaoInput,
    CalculoRescisaoOutput,
    VerificarPrescricaoInput,
    VerificarPrescricaoOutput,
)
from src.agente.tools import (
    calcular_verbas_rescisorias,
    verificar_prescricao,
    consultar_legislacao,
    consultar_jurisprudencia,
    extrair_fatos_caso,
    FERRAMENTAS_DISPONIVEIS,
    SCHEMAS_TOOLS_OLLAMA,
)
from src.agente.router import RouterEExtrator
from src.agente.cache import PromptCache
from src.agente.context_manager import ContextManager
from src.agente.tracer import Tracer, Span
from src.agente.core import AgenteLexIA


class TestAgenteTools(unittest.TestCase):
    """1. Testes de Tool Calling e ferramentas determinísticas."""

    def test_calcular_verbas_rescisorias_sem_justa_causa(self):
        res = calcular_verbas_rescisorias(
            salario_base=3000.0,
            meses_trabalhados=6,
            tipo_rescisao="sem_justa_causa",
            dias_saldo_salario=10,
            tem_ferias_vencidas=False
        )
        self.assertIn("total_bruto_estimado", res)
        self.assertIn("saldo_salario", res)
        self.assertEqual(res["saldo_salario"], 1000.0)  # (3000 / 30) * 10
        self.assertEqual(res["aviso_previo"], 3000.0)
        self.assertEqual(res["decimo_terceiro_proporcional"], 1500.0)  # (3000 / 12) * 6
        self.assertEqual(res["ferias_proporcionais_mais_terco"], 2000.0)  # 1500 * (4/3)
        self.assertGreater(res["multa_fgts_estimada"], 0)
        self.assertGreater(res["total_bruto_estimado"], 7000.0)
        self.assertTrue(len(res["fundamentacao"]) >= 3)

    def test_calcular_verbas_rescisorias_pedido_demissao(self):
        res = calcular_verbas_rescisorias(
            salario_base=3000.0,
            meses_trabalhados=6,
            tipo_rescisao="pedido_demissao",
            dias_saldo_salario=0
        )
        self.assertEqual(res["aviso_previo"], 0.0)
        self.assertEqual(res["multa_fgts_estimada"], 0.0)
        self.assertGreater(res["total_bruto_estimado"], 0.0)

    def test_verificar_prescricao_valida_e_prescrita(self):
        # Data recente: dentro do prazo bienal
        hoje = datetime.now()
        data_recente = (hoje - timedelta(days=180)).strftime("%d/%m/%Y")
        res_recente = verificar_prescricao(data_demissao=data_recente)
        self.assertFalse(res_recente["prescrito_bienal"])
        self.assertGreater(res_recente["dias_restantes_estimados"], 500)

        # Data antiga: prescrito
        res_antiga = verificar_prescricao(data_demissao="01/01/2020", data_ajuizamento="01/01/2024")
        self.assertTrue(res_antiga["prescrito_bienal"])
        self.assertEqual(res_antiga["dias_restantes_estimados"], 0)

    def test_consultar_legislacao_artigo(self):
        res = consultar_legislacao(termo="aviso prévio", artigo="477")
        self.assertIsInstance(res, str)
        self.assertTrue(len(res) > 20)

    def test_schemas_ollama_completude(self):
        self.assertEqual(len(SCHEMAS_TOOLS_OLLAMA), 5)
        nomes = [t["function"]["name"] for t in SCHEMAS_TOOLS_OLLAMA]
        self.assertIn("calcular_verbas_rescisorias", nomes)
        self.assertIn("verificar_prescricao", nomes)
        self.assertIn("consultar_legislacao", nomes)
        self.assertIn("consultar_jurisprudencia", nomes)
        self.assertIn("extrair_fatos_caso", nomes)


class TestStractingERouting(unittest.TestCase):
    """2. Testes de Extração Estruturada de Fatos (Stracting) e Roteamento de Intenção."""

    def test_extrair_fatos_salario_e_demissao(self):
        texto = "Fui demitido sem justa causa. Meu salário era de R$ 4.250,00 e trabalhei com horas extras habituais."
        fatos = RouterEExtrator.extrair_fatos(texto)
        self.assertEqual(fatos.salario, 4250.0)
        self.assertEqual(fatos.motivo_rescisao, "sem_justa_causa")
        self.assertTrue(fatos.horas_extras_habituais)

    def test_extrair_fatos_ferias_vencidas_e_datas(self):
        texto = "Trabalhei de 10/01/2021 até 15/06/2023, pedi demissão e tenho férias vencidas."
        fatos = RouterEExtrator.extrair_fatos(texto)
        self.assertEqual(fatos.data_admissao, "10/01/2021")
        self.assertEqual(fatos.data_demissao, "15/06/2023")
        self.assertEqual(fatos.motivo_rescisao, "pedido_demissao")
        self.assertTrue(fatos.tem_ferias_vencidas)

    def test_rotear_intencao(self):
        # Cálculo
        rota, _ = RouterEExtrator.rotear_intencao("Quanto vou receber de rescisão?")
        self.assertEqual(rota, "CALCULO")

        # Prescrição
        rota, _ = RouterEExtrator.rotear_intencao("Qual o prazo para entrar com processo trabalhista?")
        self.assertEqual(rota, "PRESCRICAO")

        # Consulta Jurídica Geral
        rota, _ = RouterEExtrator.rotear_intencao("Como funciona o trabalho noturno na CLT?")
        self.assertEqual(rota, "CONSULTA_JURIDICA")


class TestPromptCache(unittest.TestCase):
    """3. Testes de Prompt Caching e hash canônico."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.cache = PromptCache(cache_dir=Path(self.temp_dir), ttl_segundos=60)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_cache_hit_e_miss(self):
        mensagens = [{"role": "user", "content": "Teste de prompt"}]
        chave = self.cache.gerar_chave("modelo-x", mensagens)

        # 1. Miss inicial
        self.assertIsNone(self.cache.obter(chave))
        self.assertEqual(self.cache.misses, 1)

        # 2. Gravação
        dados = {"resultado": "OK"}
        self.cache.gravar(chave, dados, tokens_entrada=100, tokens_saida=50)

        # 3. Hit subsequente
        cached = self.cache.obter(chave)
        self.assertEqual(cached, dados)
        self.assertEqual(self.cache.hits, 1)

        # 4. Métricas
        metricas = self.cache.metricas()
        self.assertEqual(metricas["total_requisicoes"], 2)
        self.assertEqual(metricas["cache_hits"], 1)
        self.assertEqual(metricas["cache_misses"], 1)
        self.assertEqual(metricas["taxa_acerto_pct"], 50.0)
        self.assertEqual(metricas["tokens_potencialmente_economizados"], 150)

    def test_chave_canonica_deterministica(self):
        chave1 = PromptCache.gerar_chave("qwen3:8b", [{"role": "user", "content": "Olá"}])
        chave2 = PromptCache.gerar_chave("qwen3:8b", [{"role": "user", "content": "Olá"}])
        chave3 = PromptCache.gerar_chave("qwen3:8b", [{"role": "user", "content": "Tchau"}])
        self.assertEqual(chave1, chave2)
        self.assertNotEqual(chave1, chave3)


class TestContextManager(unittest.TestCase):
    """4. Testes de Gerenciamento da Janela de Contexto."""

    def setUp(self):
        self.cm = ContextManager(max_context_tokens=1000, max_output_tokens=200, max_turnos_historico=2, teto_retorno_tool_tokens=50)

    def test_podar_retorno_tool(self):
        texto_longo = "Palavra " * 200  # Cerca de 1400 chars (~400 tokens, excede teto de 50)
        podado = self.cm.podar_retorno_tool(texto_longo)
        self.assertIn("podado para respeitar a janela de contexto", podado)
        self.assertLess(len(podado), len(texto_longo))

    def test_sliding_window_com_resumo_memoria(self):
        historico = [
            {"role": "system", "content": "Prompt do sistema"},
            {"role": "user", "content": "Turno 1"},
            {"role": "assistant", "content": "Resposta 1"},
            {"role": "user", "content": "Turno 2"},
            {"role": "assistant", "content": "Resposta 2"},
            {"role": "user", "content": "Turno 3"},
            {"role": "assistant", "content": "Resposta 3"},
            {"role": "user", "content": "Turno 4"},
            {"role": "assistant", "content": "Resposta 4"},
            {"role": "user", "content": "Turno 5"},
            {"role": "assistant", "content": "Resposta 5"}
        ]
        # Com max_turnos=2, histórico máximo mantido é 4 mensagens + sistema + nota de memória
        preparado = self.cm.preparar_janela(historico, fatos_caso_resumo="Salário 3000")
        self.assertEqual(preparado[0]["role"], "system")
        # Deve haver uma mensagem de memória contextual injetada
        tem_memoria = any("[MEMÓRIA CONTEXTUAL]" in m.get("content", "") for m in preparado)
        self.assertTrue(tem_memoria)

    def test_relatorio_orcamento(self):
        mensagens = [
            {"role": "system", "content": "Sistema"},
            {"role": "user", "content": "Pergunta teste do trabalhador"}
        ]
        relatorio = self.cm.relatorio_orcamento(mensagens)
        self.assertIn("tokens_estimados", relatorio)
        self.assertIn("teto_entrada_disponivel", relatorio)
        self.assertIn("margem_seguranca_tokens", relatorio)
        self.assertGreater(relatorio["margem_seguranca_tokens"], 0)


class TestStructuredOutput(unittest.TestCase):
    """5. Testes de Saída Estruturada (Pydantic RespostaEstruturada)."""

    def test_validacao_sucesso(self):
        dados = {
            "resposta_direta": "O trabalhador tem direito ao saldo de salário e férias proporcionais.",
            "fundamentacao_legal": ["Art. 477 da CLT"],
            "jurisprudencia_aplicada": ["Súmula 60 do TST"],
            "fatos_extraidos": {"salario": 3000.0, "motivo_rescisao": "sem_justa_causa"},
            "calculos": {"total_bruto_estimado": 4500.0},
            "orientacao_ao_trabalhador": "Solicite o TRCT para conferência.",
            "alertas_e_ressalvas": ["Prazo de 10 dias corridos para quitação."],
            "precisa_advogado": False,
            "aviso_legal": "Informativo."
        }
        resp = RespostaEstruturada.model_validate(dados)
        self.assertEqual(resp.fatos_extraidos.salario, 3000.0)
        self.assertFalse(resp.precisa_advogado)

    def test_conversao_resiliente_agente(self):
        agente = AgenteLexIA(habilitar_cache=False)
        fatos = FatosCaso(salario=2500.0, motivo_rescisao="sem_justa_causa")
        texto_livre = "O empregado tem direito a verbas nos termos do artigo 477 da CLT e adicional noturno pelo art. 73."
        resp = agente._converter_para_saida_estruturada(
            texto_modelo=texto_livre,
            pergunta="Trabalho à noite, quanto recebo?",
            fatos=fatos,
            calculos=None
        )
        self.assertIsInstance(resp, RespostaEstruturada)
        self.assertTrue(any("477" in f for f in resp.fundamentacao_legal))
        self.assertTrue(any("73" in f for f in resp.fundamentacao_legal))


class TestObservabilidadeEFluxoCompleto(unittest.TestCase):
    """6. Testes de Observabilidade (Traces, Spans e Execução End-to-End)."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.tracer = Tracer(session_id="test_sess", relatorios_dir=Path(self.temp_dir))

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_tracer_spans_e_exportacao(self):
        s1 = self.tracer.novo_span("passo_1", "routing", inputs={"query": "test"})
        s1.finalizar(outputs={"status": "ok"}, tokens_in=50, tokens_out=20)

        s2 = self.tracer.novo_span("passo_2", "tool_execution", inputs={"tool": "calc"})
        s2.finalizar(outputs={"val": 100})

        resumo = self.tracer.finalizar(status="sucesso")
        self.assertEqual(resumo["total_spans"], 2)
        self.assertEqual(resumo["total_tokens_entrada"], 50)
        self.assertEqual(resumo["total_tokens_saida"], 20)

        # Verifica se o arquivo JSON individual e o CSV consolidado foram criados
        arquivos_json = list(Path(self.temp_dir).glob("trace_*.json"))
        self.assertEqual(len(arquivos_json), 1)
        csv_file = Path(self.temp_dir) / "traces_resumo.csv"
        self.assertTrue(csv_file.exists())

    def test_execucao_agente_completa_com_fallback(self):
        # Executa o ciclo completo do agente em modo offline resiliente
        cache_teste = Path(self.temp_dir) / "cache"
        traces_teste = Path(self.temp_dir) / "traces"
        agente = AgenteLexIA(
            url_ollama="http://127.0.0.1:9999",
            habilitar_cache=True,
            cache_dir=cache_teste,
            traces_dir=traces_teste
        )
        pergunta = "Fui demitido sem justa causa, meu salário era R$ 3.000,00 e trabalhei 8 meses. Quanto vou receber?"

        # 1ª Execução (Miss no cache -> executa fluxo completo)
        resposta, trace = agente.processar(pergunta, session_id="test_run_1")
        self.assertIsInstance(resposta, RespostaEstruturada)
        self.assertIsNotNone(resposta.calculos)
        self.assertGreater(resposta.calculos.get("total_bruto_estimado", 0), 0)

        # 2ª Execução idêntica (Hit no cache -> instantâneo)
        resposta2, trace2 = agente.processar(pergunta, session_id="test_run_2")
        self.assertIsInstance(resposta2, RespostaEstruturada)
        self.assertEqual(resposta.calculos["total_bruto_estimado"], resposta2.calculos["total_bruto_estimado"])
        self.assertEqual(agente.cache.hits, 1)


if __name__ == "__main__":
    unittest.main()
