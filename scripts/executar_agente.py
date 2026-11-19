"""Script de Demonstração e Avaliação Prática do Agente LexIA (Challenge 3).

Demonstra as 6 capacidades operando em conjunto:
1. Tool Calling (Agente autônomo acionando ferramentas matemáticas e jurídicas)
2. Stracting (Extração estruturada de variáveis e roteamento de intenção)
3. Prompt Caching (Cache canônico SHA-256 e comparação de latência Miss vs Hit)
4. Observabilidade (Árvore de Traces, Spans, latências em ms e tokens)
5. Janela de Contexto (Context Window Management, orçamento e histórico multi-turno)
6. Structured Output (Validação estrita Pydantic e exibição do JSON final)
"""

import argparse
import json
import sys
from pathlib import Path

# Adiciona raiz do projeto ao path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.agente.core import AgenteLexIA
from src.agente.cache import PromptCache


CASOS_DEMONSTRACAO = [
    {
        "nome": "Caso 1: Cálculo de Rescisão (Stracting + Tool Calling + Structured Output)",
        "pergunta": "Fui demitido sem justa causa, meu salário base era de R$ 3.500,00 e trabalhei por 9 meses. Tive 5 dias de saldo de salário. Quanto vou receber de rescisão?",
        "descricao": "Extrai salário e tempo de serviço, aciona a ferramenta matemática determinística e retorna valores exatos sem alucinação."
    },
    {
        "nome": "Caso 2: Verificação de Prescrição (Stracting de Datas + Tool de Prazos)",
        "pergunta": "Fui demitido da empresa em 15/03/2023. Ainda estou no prazo para ingressar com uma ação trabalhista cobrando meus direitos?",
        "descricao": "Calcula a prescrição bienal (2 anos) e quinquenal (5 anos) com base na CF/88 e CLT."
    },
    {
        "nome": "Caso 3: Consulta Jurídica (Recuperação de Súmulas e Legislação)",
        "pergunta": "Trabalho das 22h às 7h da manhã. As horas trabalhadas depois das 5h da manhã contam como horário noturno e têm adicional?",
        "descricao": "Roteia para recuperação jurídica, aplicando o Art. 73 da CLT e a Súmula nº 60 do TST."
    }
]


def executar_demonstracao(modelo: str = "qwen3:8b", url_ollama: str = "http://127.0.0.1:11434"):
    print("\n" + "=" * 80)
    print("🤖 INICIANDO DEMONSTRAÇÃO DO AGENTE INTELIGENTE LEXIA (CHALLENGE 3)")
    print(f"📌 Modelo: {modelo} | Backend Ollama: {url_ollama}")
    print("=" * 80)

    agente = AgenteLexIA(
        modelo=modelo,
        url_ollama=url_ollama,
        habilitar_cache=True
    )

    for idx, caso in enumerate(CASOS_DEMONSTRACAO, 1):
        print(f"\n{'─' * 80}")
        print(f"▶️  EXEMPLO {idx}: {caso['nome']}")
        print(f"📝 Descrição: {caso['descricao']}")
        print(f"💬 Pergunta do Usuário:\n   \"{caso['pergunta']}\"")
        print(f"{'─' * 80}")

        resposta, trace = agente.processar(caso['pergunta'], session_id=f"demo_caso_{idx}")

        print("\n📋 SAÍDA ESTRUTURADA (Pydantic RespostaEstruturada):")
        print(f"   • Resposta Direta: {resposta.resposta_direta[:150]}...")
        if resposta.calculos:
            print(f"   • Cálculos Realizados:")
            for k, v in resposta.calculos.items():
                if k != "fundamentacao":
                    print(f"     - {k}: {v}")
        if resposta.fundamentacao_legal:
            print(f"   • Fundamentação Legal: {', '.join(resposta.fundamentacao_legal[:3])}")
        if resposta.jurisprudencia_aplicada:
            print(f"   • Jurisprudência Aplicada: {', '.join(resposta.jurisprudencia_aplicada[:2])}")
        print(f"   • Orientação ao Trabalhador: {resposta.orientacao_ao_trabalhador}")
        print(f"   • Precisa Advogado: {'Sim' if resposta.precisa_advogado else 'Não'}")

    # ========================================================================
    # DEMONSTRAÇÃO DO PROMPT CACHING (Comparação Miss vs Hit)
    # ========================================================================
    print("\n" + "=" * 80)
    print("⚡ DEMONSTRAÇÃO DE PROMPT CACHING (Eficácia de Reutilização de Contexto)")
    print("=" * 80)
    pergunta_repetida = CASOS_DEMONSTRACAO[0]["pergunta"]
    print(f"Repetindo a pergunta do Caso 1 para comprovar o Cache Hit:")
    print(f"💬 \"{pergunta_repetida}\"")

    resp_cached, trace_cached = agente.processar(pergunta_repetida, session_id="demo_cache_hit")

    metricas_cache = agente.cache.metricas() if agente.cache else {}
    print("\n📊 MÉTRICAS CONSOLIDADAS DO PROMPT CACHING:")
    for k, v in metricas_cache.items():
        print(f"   • {k}: {v}")

    # ========================================================================
    # DEMONSTRAÇÃO DA JANELA DE CONTEXTO (Histórico Multi-Turno)
    # ========================================================================
    print("\n" + "=" * 80)
    print("🪟 DEMONSTRAÇÃO DA JANELA DE CONTEXTO (Histórico Multi-Turno & Budgeting)")
    print("=" * 80)
    relatorio_janela = agente.context_manager.relatorio_orcamento(agente.historico)
    for k, v in relatorio_janela.items():
        print(f"   • {k}: {v}")

    print("\n" + "=" * 80)
    print("✅ DEMONSTRAÇÃO CONCLUÍDA COM SUCESSO!")
    print(f"📁 Traces registrados em: reports/agente/traces/traces_resumo.csv")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Executa o Agente LexIA com as 6 capacidades.")
    parser.add_argument("--modelo", default="qwen3:8b", help="Nome do modelo no Ollama (ex.: qwen3:8b)")
    parser.add_argument("--url-ollama", default="http://127.0.0.1:11434", help="URL do servidor Ollama local")
    args = parser.parse_args()

    executar_demonstracao(modelo=args.modelo, url_ollama=args.url_ollama)
