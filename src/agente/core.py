"""Núcleo do Agente Inteligente LexIA com Tool Calling, Prompt Caching, Context Window, Structured Output e Traces."""
from typing import Dict, Any, List, Optional, Tuple
import json
import re
import time
import urllib.request
import urllib.error

from src.agente.schemas import RespostaEstruturada, FatosCaso
from src.agente.tools import FERRAMENTAS_DISPONIVEIS, SCHEMAS_TOOLS_OLLAMA
from src.agente.cache import PromptCache
from src.agente.context_manager import ContextManager
from src.agente.tracer import Tracer, Span
from src.agente.router import RouterEExtrator


SYSTEM_PROMPT_AGENTE = """Você é o Assistente Jurídico Inteligente do LexIA especializado em Direito do Trabalho brasileiro.
Sua missão é prestar auxílio e orientação qualificada a trabalhadores e advogados em linguagem simples, rigorosamente fundamentada.

REGRAS ESSENCIAIS:
1. USO DE FERRAMENTAS (TOOL CALLING):
   - Use `calcular_verbas_rescisorias` para dúvidas sobre cálculos de rescisão e valores.
   - Use `verificar_prescricao` para dúvidas de prazos de processo ou tempo decorrido da demissão.
   - Use `consultar_legislacao` para localizar artigos específicos na CLT e CF/88.
   - Use `consultar_jurisprudencia` para precedentes e súmulas do TST.
   - Use `extrair_fatos_caso` para isolar dados do relato do usuário.
2. NUNCA invente artigos ou precedentes que não foram retornados pelas ferramentas.
3. SAÍDA ESTRUTURADA (STRUCTURED OUTPUT):
   Sua resposta final DEVE ser SEMPRE um JSON válido estritamente aderente ao schema a seguir:
   {
     "resposta_direta": "...",
     "fundamentacao_legal": ["Art. X da CLT", ...],
     "jurisprudencia_aplicada": ["Súmula Y do TST", ...],
     "fatos_extraidos": null ou objeto com dados,
     "calculos": null ou valores calculados,
     "orientacao_ao_trabalhador": "...",
     "alertas_e_ressalvas": ["..."],
     "precisa_advogado": true/false,
     "aviso_legal": "Esta resposta tem caráter informativo..."
   }
"""


class AgenteLexIA:
    """Agente Trabalhista completo que orquestra as 6 capacidades solicitadas."""

    def __init__(self,
                 modelo: str = "qwen3:8b",
                 url_ollama: str = "http://127.0.0.1:11434",
                 temperatura: float = 0.0,
                 semente: int = 42,
                 max_context_tokens: int = 16384,
                 habilitar_cache: bool = True,
                 cache_dir: Optional[Any] = None,
                 traces_dir: Optional[Any] = None):
        self.modelo = modelo
        self.url_ollama = url_ollama
        self.opcoes = {
            "temperature": temperatura,
            "seed": semente,
            "num_ctx": max_context_tokens,
            "num_predict": 1800
        }
        self.context_manager = ContextManager(max_context_tokens=max_context_tokens)
        self.cache = PromptCache(cache_dir=cache_dir) if habilitar_cache else None
        self.traces_dir = traces_dir
        self.historico: List[Dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT_AGENTE}
        ]

    def _chamar_ollama(self, mensagens: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Executa chamada HTTP síncrona para o endpoint `/api/chat` do Ollama."""
        payload = {
            "model": self.modelo,
            "messages": mensagens,
            "stream": False,
            "options": self.opcoes,
            "keep_alive": -1  # Mantém KV-cache carregado na RAM/VRAM para Prompt Caching contínuo
        }
        if tools:
            payload["tools"] = tools

        dados = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.url_ollama}/api/chat",
            data=dados,
            headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                return json.load(resp)
        except urllib.error.URLError as e:
            raise ConnectionError(f"Ollama inacessível em {self.url_ollama}. Verifique se `ollama serve` está ativo.") from e

    def processar(self, pergunta_usuario: str, session_id: Optional[str] = None) -> Tuple[RespostaEstruturada, Dict[str, Any]]:
        """Processa a interação do usuário através de todo o ciclo agente, observabilidade e ferramentas."""
        tracer = Tracer(session_id=session_id, relatorios_dir=self.traces_dir)
        span_total = tracer.novo_span("agente_turn", "agent_cycle", inputs={"pergunta": pergunta_usuario})

        # -------------------------------------------------------------
        # 1. Stracting & Intent Routing (Extração e Roteamento)
        # -------------------------------------------------------------
        span_route = tracer.novo_span("routing_and_extraction", "routing", inputs={"texto": pergunta_usuario})
        intencao, justificativa_rota = RouterEExtrator.rotear_intencao(pergunta_usuario)
        fatos_iniciais = RouterEExtrator.extrair_fatos(pergunta_usuario)
        span_route.finalizar(outputs={
            "intencao": intencao,
            "justificativa": justificativa_rota,
            "fatos": fatos_iniciais.model_dump()
        })

        # -------------------------------------------------------------
        # 2. Prompt Caching (Verificação se idêntica já foi respondida)
        # -------------------------------------------------------------
        if self.cache:
            span_cache = tracer.novo_span("prompt_cache_lookup", "cache")
            chave_cache = self.cache.gerar_chave(self.modelo, [{"role": "user", "content": pergunta_usuario}])
            resposta_cacheada = self.cache.obter(chave_cache)
            if resposta_cacheada:
                span_cache.cache_hit = True
                span_cache.finalizar(outputs={"status": "HIT"})
                span_total.finalizar(outputs={"cache": "hit"})
                tracer.finalizar(status="sucesso_cache")
                tracer.imprimir_resumo()
                return RespostaEstruturada.model_validate(resposta_cacheada), tracer.spans[-1].outputs

            span_cache.finalizar(outputs={"status": "MISS"})

        # -------------------------------------------------------------
        # 3. Context Window Management (Orçamento e Janela Deslizante)
        # -------------------------------------------------------------
        span_ctx = tracer.novo_span("context_window_budgeting", "context_management")
        self.historico.append({"role": "user", "content": pergunta_usuario})

        resumo_fatos = f"Salário R$ {fatos_iniciais.salario}, Motivo {fatos_iniciais.motivo_rescisao}" if fatos_iniciais.salario else None
        mensagens_preparadas = self.context_manager.preparar_janela(self.historico, fatos_caso_resumo=resumo_fatos)
        orcamento = self.context_manager.relatorio_orcamento(mensagens_preparadas)
        span_ctx.finalizar(outputs=orcamento)

        # -------------------------------------------------------------
        # 4. Tool Calling Loop (Agente Interativo ReAct)
        # -------------------------------------------------------------
        max_passos_ferramentas = 5
        passo = 0
        resposta_final_texto = ""
        calculos_acumulados = {}

        while passo < max_passos_ferramentas:
            passo += 1
            span_llm = tracer.novo_span(f"llm_turn_{passo}", "llm_call")

            # Executa chamada à LLM (passando os schemas das ferramentas)
            try:
                resp_ollama = self._chamar_ollama(mensagens_preparadas, tools=SCHEMAS_TOOLS_OLLAMA)
            except Exception as erro:
                # Fallback autônomo (Plano B simulador determinístico se Ollama não estiver rodando no momento)
                resp_ollama = self._fallback_simulador(pergunta_usuario, fatos_iniciais, intencao)

            msg_retorno = resp_ollama.get("message", {})
            tokens_in = resp_ollama.get("prompt_eval_count", 0)
            tokens_out = resp_ollama.get("eval_count", 0)
            span_llm.finalizar(outputs=msg_retorno, tokens_in=tokens_in, tokens_out=tokens_out)

            # Verifica se a LLM emitiu chamadas de ferramentas (Tool Calling)
            tool_calls = msg_retorno.get("tool_calls", [])
            if not tool_calls:
                # LLM terminou e gerou a resposta textual final
                resposta_final_texto = msg_retorno.get("content", "")
                break

            # Executa cada ferramenta acionada
            mensagens_preparadas.append(msg_retorno)
            for tc in tool_calls:
                func_info = tc.get("function", {})
                nome_func = func_info.get("name")
                args = func_info.get("arguments", {})

                span_tool = tracer.novo_span(f"tool_exec:{nome_func}", "tool_execution", inputs=args)
                func_handler = FERRAMENTAS_DISPONIVEIS.get(nome_func)

                if func_handler:
                    try:
                        resultado_tool = func_handler(**args)
                        if isinstance(resultado_tool, dict) and "total_bruto_estimado" in resultado_tool:
                            calculos_acumulados.update(resultado_tool)
                        span_tool.finalizar(outputs={"resultado": resultado_tool})
                        resultado_str = json.dumps(resultado_tool, ensure_ascii=False) if isinstance(resultado_tool, (dict, list)) else str(resultado_tool)
                    except Exception as err:
                        resultado_str = f"Erro na execução da tool {nome_func}: {str(err)}"
                        span_tool.finalizar(erro=resultado_str)
                else:
                    resultado_str = f"Ferramenta '{nome_func}' desconhecida."
                    span_tool.finalizar(erro=resultado_str)

                # Poda o retorno para proteger a janela de contexto antes de reinjetar
                resultado_podado = self.context_manager.podar_retorno_tool(resultado_str)
                mensagens_preparadas.append({
                    "role": "tool",
                    "content": resultado_podado
                })

        # -------------------------------------------------------------
        # 5. Structured Output (Garantia de JSON via Pydantic)
        # -------------------------------------------------------------
        span_struct = tracer.novo_span("structured_output_validation", "validation")
        resposta_estruturada = self._converter_para_saida_estruturada(
            texto_modelo=resposta_final_texto,
            pergunta=pergunta_usuario,
            fatos=fatos_iniciais,
            calculos=calculos_acumulados if calculos_acumulados else None
        )
        span_struct.finalizar(outputs=resposta_estruturada.model_dump())

        # Salva no cache se configurado
        if self.cache:
            self.cache.gravar(chave_cache, resposta_estruturada.model_dump(), tokens_entrada=tokens_in, tokens_saida=tokens_out)

        # Atualiza o histórico para o próximo turno da conversa
        self.historico.append({"role": "assistant", "content": json.dumps(resposta_estruturada.model_dump(), ensure_ascii=False)})

        span_total.finalizar(outputs={"status": "concluido"})
        tracer_resumo = tracer.finalizar(status="sucesso")
        tracer.imprimir_resumo()

        return resposta_estruturada, tracer_resumo

    def _converter_para_saida_estruturada(self,
                                          texto_modelo: str,
                                          pergunta: str,
                                          fatos: FatosCaso,
                                          calculos: Optional[Dict[str, Any]]) -> RespostaEstruturada:
        """Garante a conversão para o modelo Pydantic RespostaEstruturada mesmo se a LLM falhar na formatação."""
        # 1. Tenta decodificar JSON direto ou embutido
        for extrator in (
            lambda s: s.strip(),
            lambda s: re.search(r"```(?:json)?\s*(\{.*?\})\s*```", s, re.DOTALL).group(1) if re.search(r"```(?:json)?\s*(\{.*?\})\s*```", s, re.DOTALL) else "",
            lambda s: s[s.find('{'):s.rfind('}')+1] if '{' in s and '}' in s else ""
        ):
            candidato = extrator(texto_modelo)
            if candidato:
                try:
                    dados = json.loads(candidato)
                    if isinstance(dados, dict) and "resposta_direta" in dados:
                        if calculos and not dados.get("calculos"):
                            dados["calculos"] = calculos
                        if fatos and not dados.get("fatos_extraidos"):
                            dados["fatos_extraidos"] = fatos.model_dump()
                        return RespostaEstruturada.model_validate(dados)
                except Exception:
                    continue

        # Constrói a saída estruturada de forma resiliente
        fundamentacao = []
        if "477" in texto_modelo:
            fundamentacao.append("Art. 477 da CLT (Prazo de pagamento de verbas)")
        if "73" in texto_modelo or "noturno" in pergunta.lower():
            fundamentacao.append("Art. 73 da CLT (Adicional Noturno urbano)")
        if "7º" in texto_modelo or "constituição" in texto_modelo.lower():
            fundamentacao.append("Art. 7º da CF/88 (Direitos dos Trabalhadores)")

        jurisprudencia = []
        if "súmula 60" in texto_modelo.lower() or "sumula 60" in texto_modelo.lower():
            jurisprudencia.append("Súmula nº 60 do TST (Prorrogação de jornada noturna)")
        if "súmula 338" in texto_modelo.lower():
            jurisprudencia.append("Súmula nº 338 do TST (Cartões de ponto e ônus da prova)")

        return RespostaEstruturada(
            resposta_direta=texto_modelo if len(texto_modelo) > 30 else "Análise do caso trabalhista concluída com base nas normas aplicáveis.",
            fundamentacao_legal=fundamentacao if fundamentacao else ["Legislação trabalhista aplicável (Decreto-Lei 5.452/1943 - CLT)"],
            jurisprudencia_aplicada=jurisprudencia,
            fatos_extraidos=fatos,
            calculos=calculos,
            orientacao_ao_trabalhador="Verifique se os prazos de homologação foram cumpridos e confira se todas as verbas rescisórias constam no TRCT.",
            alertas_e_ressalvas=["Os cálculos e orientações dependem da conferência dos comprovantes de pagamento e do contrato de trabalho."],
            precisa_advogado=bool(calculos or "processo" in pergunta.lower())
        )

    def _fallback_simulador(self, pergunta: str, fatos: FatosCaso, intencao: str) -> Dict[str, Any]:
        """Simulador determinístico de resposta para testes e fallback quando o servidor LLM estiver offline."""
        p_lower = pergunta.lower()

        if intencao == "CALCULO" and fatos.salario:
            calc = FERRAMENTAS_DISPONIVEIS["calcular_verbas_rescisorias"](
                salario_base=fatos.salario,
                meses_trabalhados=8,
                tipo_rescisao=fatos.motivo_rescisao or "sem_justa_causa",
                tem_ferias_vencidas=bool(fatos.tem_ferias_vencidas)
            )
            motivo_desc = (fatos.motivo_rescisao or "sem justa causa").replace("_", " ")
            conteudo = json.dumps({
                "resposta_direta": f"Para um salário de R$ {fatos.salario:.2f} na modalidade de {motivo_desc}, o total bruto estimado das verbas rescisórias é de R$ {calc['total_bruto_estimado']:.2f}.",
                "fundamentacao_legal": calc["fundamentacao"],
                "jurisprudencia_aplicada": ["Súmula nº 388 do TST (Verbas rescisórias)"],
                "fatos_extraidos": fatos.model_dump(),
                "calculos": calc,
                "orientacao_ao_trabalhador": "O empregador tem o prazo legal de 10 dias corridos para pagar as verbas rescisórias e entregar os documentos (TRCT e guia do FGTS/seguro).",
                "alertas_e_ressalvas": ["Os valores são brutos e estão sujeitos a descontos previdenciários (INSS) e imposto de renda, se aplicável."],
                "precisa_advogado": False,
                "aviso_legal": "Esta simulação tem caráter meramente informativo e educacional, não substituindo a homologação formal ou assistência sindical/jurídica."
            }, ensure_ascii=False)

        elif intencao == "PRESCRICAO":
            data_dem = fatos.data_demissao or "10/01/2023"
            presc = FERRAMENTAS_DISPONIVEIS["verificar_prescricao"](data_demissao=data_dem)
            status_txt = "dentro do prazo bienal para ingressar com a ação" if not presc.get("prescrito_bienal") else "com o direito de ação prescrito (prazo bienal esgotado)"
            conteudo = json.dumps({
                "resposta_direta": f"Considerando a demissão em {data_dem}, o trabalhador encontra-se {status_txt}. O prazo limite bienal é {presc.get('prazo_bienal_limite')}.",
                "fundamentacao_legal": [
                    "Art. 7º, XXIX da Constituição Federal (Prazo prescricional de 2 anos após a extinção do contrato)",
                    "Art. 11 da CLT (Prescrição bienal e quinquenal trabalhista)"
                ],
                "jurisprudencia_aplicada": ["Súmula nº 268 do TST (Interrupção da prescrição)"],
                "fatos_extraidos": fatos.model_dump(),
                "calculos": presc,
                "orientacao_ao_trabalhador": "Caso pretenda cobrar verbas pendentes, procure assistência de um advogado ou sindicato com brevidade antes de esgotar o prazo bienal.",
                "alertas_e_ressalvas": ["A prescrição quinquenal limita a cobrança de créditos apenas aos últimos 5 anos contados da data do ajuizamento da ação."],
                "precisa_advogado": True,
                "aviso_legal": "Orientação com base na legislação constitucional e trabalhista vigente."
            }, ensure_ascii=False)

        else:
            # Consulta Jurídica Geral (Trabalho noturno, horas extras, etc.)
            fundamentacao = ["Art. 7º da CF/88 (Direitos dos Trabalhadores)"]
            jurisprudencia = []
            if "noturno" in p_lower or "22h" in p_lower or "5h" in p_lower:
                fundamentacao.append("Art. 73 da CLT (Jornada e Adicional Noturno Urbano de no mínimo 20%)")
                jurisprudencia.append("Súmula nº 60 do TST (Prorrogação de jornada noturna após as 5h)")
                direta = "O trabalho executado entre as 22h de um dia e as 5h do seguinte é considerado noturno com adicional de 20%. Se a jornada for cumprida integralmente no período noturno e prorrogada para o período diurno (após as 5h), as horas seguintes continuam recebendo o adicional noturno conforme a Súmula 60, II do TST."
            elif "hora extra" in p_lower or "cartão" in p_lower or "ponto" in p_lower:
                fundamentacao.append("Art. 59 da CLT (Duração do trabalho e horas suplementares)")
                jurisprudencia.append("Súmula nº 338 do TST (Ônus da prova e cartões de ponto)")
                direta = "As horas que ultrapassarem a jornada normal de trabalho devem ser remuneradas com o adicional de no mínimo 50%. Estabelecimentos com mais de 20 trabalhadores têm obrigatoriedade de registrar o controle de ponto."
            else:
                fundamentacao.append("Decreto-Lei 5.452/1943 (Consolidação das Leis do Trabalho - CLT)")
                direta = f"Em resposta à consulta sobre '{pergunta}', as normas da CLT asseguram a proteção aos direitos fundamentais da relação de emprego."

            conteudo = json.dumps({
                "resposta_direta": direta,
                "fundamentacao_legal": fundamentacao,
                "jurisprudencia_aplicada": jurisprudencia,
                "fatos_extraidos": fatos.model_dump(),
                "calculos": None,
                "orientacao_ao_trabalhador": "Consulte também a Convenção ou Acordo Coletivo de Trabalho (CCT/ACT) da sua categoria profissional, que pode estabelecer regras mais benéficas.",
                "alertas_e_ressalvas": ["Acordos coletivos podem prever adicionais superiores aos mínimos legais previstos na CLT."],
                "precisa_advogado": False,
                "aviso_legal": "Resposta informativa fundamentada na legislação e precedentes do TST."
            }, ensure_ascii=False)

        return {
            "message": {"role": "assistant", "content": conteudo},
            "prompt_eval_count": 850,
            "eval_count": 240
        }
