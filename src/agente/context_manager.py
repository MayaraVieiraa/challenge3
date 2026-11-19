"""Gerenciador da Janela de Contexto (Context Window Management, Sliding Window e Orçamento de Tokens)."""
from typing import List, Dict, Any, Optional
import copy


class ContextManager:
    """Controla o orçamento de tokens, janela deslizante e compressão de histórico da conversa."""

    def __init__(self,
                 max_context_tokens: int = 16384,
                 max_output_tokens: int = 1500,
                 max_turnos_historico: int = 8,
                 teto_retorno_tool_tokens: int = 3000):
        self.max_context_tokens = max_context_tokens
        self.max_output_tokens = max_output_tokens
        self.max_turnos = max_turnos_historico
        self.teto_tool_tokens = teto_retorno_tool_tokens

    @staticmethod
    def estimar_tokens(texto: str) -> int:
        """Estimativa aproximada de tokens para textos em português (cerca de 3.5 caracteres por token)."""
        if not texto:
            return 0
        return max(1, int(len(texto) / 3.5))

    def estimar_tokens_mensagens(self, mensagens: List[Dict[str, Any]]) -> int:
        total = 0
        for m in mensagens:
            total += self.estimar_tokens(m.get('content', ''))
            # Se houver tool_calls ou chamada estruturada
            if 'tool_calls' in m:
                total += self.estimar_tokens(str(m['tool_calls']))
        return total

    def podar_retorno_tool(self, conteudo: str) -> str:
        """Garante que o retorno de uma ferramenta não extrapole o teto de tokens reservado."""
        tokens = self.estimar_tokens(conteudo)
        if tokens <= self.teto_tool_tokens:
            return conteudo
        # Trunca proporcionalmente preservando o início e a conclusão
        limite_chars = int(self.teto_tool_tokens * 3.5)
        corte = limite_chars // 2
        return (conteudo[:corte] +
                f"\n\n[... Trecho intermediário podado para respeitar a janela de contexto ({tokens} tokens) ...]\n\n" +
                conteudo[-corte:])

    def preparar_janela(self,
                        mensagens: List[Dict[str, Any]],
                        fatos_caso_resumo: Optional[str] = None) -> List[Dict[str, Any]]:
        """Aplica Sliding Window e orçamento rigoroso antes de enviar para a LLM."""
        if not mensagens:
            return []

        # Preserva a mensagem de sistema inicial (se houver)
        tem_sistema = mensagens[0].get('role') == 'system'
        sistema = mensagens[0] if tem_sistema else None
        historico = mensagens[1:] if tem_sistema else mensagens

        # 1. Aplica Sliding Window por turnos (mantém os últimos N turnos)
        if len(historico) > self.max_turnos * 2:
            turnos_removidos = historico[:-self.max_turnos * 2]
            historico = historico[-self.max_turnos * 2:]

            # Insere nota de contexto resumindo os turnos anteriores para não perder continuidade
            nota_resumo = "Resumo dos turnos anteriores da conversa: O usuário relatou seu caso trabalhista e foram realizadas consultas prévias."
            if fatos_caso_resumo:
                nota_resumo += f" Fatos essenciais consolidados: {fatos_caso_resumo}"

            mensagem_memoria = {
                'role': 'system',
                'content': f"[MEMÓRIA CONTEXTUAL]: {nota_resumo}"
            }
            historico = [mensagem_memoria] + historico

        # 2. Orçamento estrito de tokens: verifica se ultrapassa o teto
        mensagens_finais = ([sistema] if sistema else []) + historico
        tokens_atuais = self.estimar_tokens_mensagens(mensagens_finais)
        teto_entrada = self.max_context_tokens - self.max_output_tokens

        # Se ainda estourar, vai descartando mensagens intermediárias mais antigas (preservando sistema e última pergunta)
        while tokens_atuais > teto_entrada and len(historico) > 2:
            historico.pop(0)  # remove a mais antiga do histórico
            mensagens_finais = ([sistema] if sistema else []) + historico
            tokens_atuais = self.estimar_tokens_mensagens(mensagens_finais)

        return mensagens_finais

    def relatorio_orcamento(self, mensagens: List[Dict[str, Any]]) -> Dict[str, Any]:
        tokens_atuais = self.estimar_tokens_mensagens(mensagens)
        teto_entrada = self.max_context_tokens - self.max_output_tokens
        return {
            'tokens_estimados': tokens_atuais,
            'teto_entrada_disponivel': teto_entrada,
            'margem_seguranca_tokens': max(0, teto_entrada - tokens_atuais),
            'ocupacao_janela_pct': round((tokens_atuais / self.max_context_tokens) * 100, 1),
            'total_mensagens': len(mensagens)
        }
