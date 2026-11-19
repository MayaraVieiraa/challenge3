"""Estimativa e limite fail-closed para prompts do fluxo integrado."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import tiktoken


_ENCODING = tiktoken.get_encoding("cl100k_base")
_SAFETY_FACTOR = 1.25


@dataclass(frozen=True)
class ContextBudget:
    estimated_input_tokens: int
    raw_estimated_tokens: int
    max_input_tokens: int
    max_context_tokens: int
    max_output_tokens: int
    safety_tokens: int

    def para_dict(self) -> dict:
        return asdict(self)


class ContextWindowExceeded(ValueError):
    def __init__(self, budget: ContextBudget):
        self.budget = budget
        super().__init__(
            "Prompt excede o orçamento estimado de contexto "
            f"({budget.estimated_input_tokens} > {budget.max_input_tokens} tokens). "
            "O prompt e as evidências não foram truncados; ajuste o contexto ou reduza as fontes."
        )


def estimar_tokens(mensagens: list[dict]) -> int:
    """Conta tokens aproximados com cl100k_base; não representa o tokenizer exato do Qwen."""
    total = 0
    for mensagem in mensagens:
        if not isinstance(mensagem.get("content"), str):
            raise TypeError("O conteúdo de cada mensagem deve ser texto.")
        total += len(_ENCODING.encode(mensagem["content"]))
        total += 4
    return total + 2


def validar_janela_contexto(
    mensagens: list[dict],
    *,
    max_context_tokens: int,
    max_output_tokens: int,
    safety_tokens: int = 512,
) -> ContextBudget:
    if max_context_tokens <= 0 or max_output_tokens < 0 or safety_tokens < 0:
        raise ValueError("Os limites de contexto, saída e segurança devem ser não negativos.")
    if max_output_tokens + safety_tokens >= max_context_tokens:
        raise ValueError("A saída máxima e a margem de segurança devem caber no contexto.")

    bruto = estimar_tokens(mensagens)
    estimado = math.ceil(bruto * _SAFETY_FACTOR)
    max_entrada = max_context_tokens - max_output_tokens - safety_tokens
    budget = ContextBudget(
        estimated_input_tokens=estimado,
        raw_estimated_tokens=bruto,
        max_input_tokens=max_entrada,
        max_context_tokens=max_context_tokens,
        max_output_tokens=max_output_tokens,
        safety_tokens=safety_tokens,
    )
    if estimado > max_entrada:
        raise ContextWindowExceeded(budget)
    return budget
