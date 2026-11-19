"""Módulo de Agente Inteligente do LexIA para o Challenge 3.

Implementa as 6 capacidades avançadas de agentes de IA:
1. Tool Calling (Agente autônomo com ferramentas determinísticas e de busca jurídica)
2. Stracting (Extração e Roteamento de entidades e fatos do caso a partir de texto livre)
3. Prompt Caching (Cache canônico SHA-256 e prefix-caching OLLAMA_KEEP_ALIVE)
4. Observabilidade (Traces hierárquicos com Spans, latências, tokens e exportação CSV/JSON)
5. Janela de Contexto (Context Window Management, sliding window e poda de retornos)
6. Structured Output (Saída estrita validada via Pydantic RespostaEstruturada)
"""

from src.agente.schemas import (
    RespostaEstruturada,
    FatosCaso,
    CalculoRescisaoInput,
    CalculoRescisaoOutput,
    VerificarPrescricaoInput,
    VerificarPrescricaoOutput,
)
from src.agente.tracer import Tracer, Span
from src.agente.cache import PromptCache
from src.agente.context_manager import ContextManager
from src.agente.router import RouterEExtrator
from src.agente.tools import (
    FERRAMENTAS_DISPONIVEIS,
    SCHEMAS_TOOLS_OLLAMA,
    calcular_verbas_rescisorias,
    verificar_prescricao,
    consultar_legislacao,
    consultar_jurisprudencia,
    extrair_fatos_caso,
)
from src.agente.core import AgenteLexIA

__all__ = [
    "AgenteLexIA",
    "Tracer",
    "Span",
    "PromptCache",
    "ContextManager",
    "RouterEExtrator",
    "RespostaEstruturada",
    "FatosCaso",
    "CalculoRescisaoInput",
    "CalculoRescisaoOutput",
    "VerificarPrescricaoInput",
    "VerificarPrescricaoOutput",
    "FERRAMENTAS_DISPONIVEIS",
    "SCHEMAS_TOOLS_OLLAMA",
    "calcular_verbas_rescisorias",
    "verificar_prescricao",
    "consultar_legislacao",
    "consultar_jurisprudencia",
    "extrair_fatos_caso",
]
