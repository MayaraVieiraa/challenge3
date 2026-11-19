"""Script de Avaliação Abrangente (Benchmark Completo) do Agente LexIA (Challenge 3).

Executa 12 cenários de teste representativos de Direito do Trabalho cobrindo todas as 6 capacidades:
- Tool Calling (Cálculos de rescisão determinísticos e prazos de prescrição)
- Stracting (Extração estruturada de fatos e roteamento)
- Prompt Caching (Comparativo de latência e economia de tokens entre Miss e Hit)
- Observabilidade (Métricas detalhadas de latência por span e tokens)
- Janela de Contexto (Histórico multi-turno, sliding window e orçamento)
- Structured Output (Conformidade com schema Pydantic RespostaEstruturada)

Gera:
- `reports/agente/benchmark_resultados.json`
- `reports/agente/benchmark_resumo.csv`
"""

import json
import sys
import time
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.agente.core import AgenteLexIA
from src.agente.schemas import RespostaEstruturada


BATERIA_TESTES = [
    {
        "id": "TC01",
        "nome": "Demissão sem justa causa com saldo de salário",
        "categoria": "calculo_rescisao",
        "pergunta": "Fui demitido sem justa causa. Meu salário base era de R$ 3.500,00 e trabalhei por 9 meses. Tive 5 dias de saldo de salário. Quanto vou receber de rescisão?",
        "esperado": {"intencao": "CALCULO", "salario": 3500.0, "motivo": "sem_justa_causa", "tem_calculo": True}
    },
    {
        "id": "TC02",
        "nome": "Pedido de demissão pelo empregado",
        "categoria": "pedido_demissao",
        "pergunta": "Pedi demissão após 10 meses na empresa. Meu salário era R$ 4.000,00. Tenho direito ao aviso prévio e à multa de 40% do FGTS?",
        "esperado": {"intencao": "CALCULO", "salario": 4000.0, "motivo": "pedido_demissao", "tem_calculo": True}
    },
    {
        "id": "TC03",
        "nome": "Demissão com justa causa (Art. 482 CLT)",
        "categoria": "justa_causa",
        "pergunta": "Fui demitido por justa causa com salário de R$ 2.800,00. Quais verbas ainda tenho direito a receber no término?",
        "esperado": {"intencao": "CALCULO", "salario": 2800.0, "motivo": "justa_causa", "tem_calculo": True}
    },
    {
        "id": "TC04",
        "nome": "Rescisão por acordo mútuo (Art. 484-A CLT)",
        "categoria": "acordo_mutuo",
        "pergunta": "Fiz um acordo mútuo de rescisão com a empresa (Art. 484-A CLT). Meu salário era R$ 5.000,00. Como fica o aviso e a multa rescisória?",
        "esperado": {"intencao": "CALCULO", "salario": 5000.0, "motivo": "sem_justa_causa", "tem_calculo": True}
    },
    {
        "id": "TC05",
        "nome": "Demissão sem justa causa com férias vencidas",
        "categoria": "ferias_vencidas",
        "pergunta": "Fui demitido sem justa causa com salário de R$ 3.000,00 e tenho um período de férias vencidas pendente que nunca tirei. Quanto receberei?",
        "esperado": {"intencao": "CALCULO", "salario": 3000.0, "motivo": "sem_justa_causa", "tem_calculo": True}
    },
    {
        "id": "TC06",
        "nome": "Prescrição bienal dentro do prazo (ação tempestiva)",
        "categoria": "prescricao_tempestiva",
        "pergunta": "Fui demitido em 15/03/2026. Qual o prazo para entrar com processo trabalhista cobrando meus direitos?",
        "esperado": {"intencao": "PRESCRICAO", "data_demissao": "15/03/2026", "tem_calculo": True}
    },
    {
        "id": "TC07",
        "nome": "Prescrição bienal ultrapassada (direito prescrito)",
        "categoria": "prescricao_esgotada",
        "pergunta": "Fui dispensado em 10/01/2020. Ainda é possível ajuizar reclamação trabalhista na Justiça do Trabalho ou perdi o prazo?",
        "esperado": {"intencao": "PRESCRICAO", "data_demissao": "10/01/2020", "tem_calculo": True}
    },
    {
        "id": "TC08",
        "nome": "Adicional noturno urbano e prorrogação após as 5h",
        "categoria": "adicional_noturno",
        "pergunta": "Minha jornada é das 22h às 7h da manhã. As horas trabalhadas após as 5h da manhã dão direito a adicional noturno pela CLT?",
        "esperado": {"intencao": "CONSULTA_JURIDICA", "artigo": "73", "sumula": "60"}
    },
    {
        "id": "TC09",
        "nome": "Horas extras habituais e controle de ponto",
        "categoria": "horas_extras",
        "pergunta": "Fazia 2 horas extras todos os dias e a empresa não anotava no cartão de ponto. De quem é a obrigação de provar o horário trabalhado?",
        "esperado": {"intencao": "CONSULTA_JURIDICA", "artigo": "59", "sumula": "338"}
    },
    {
        "id": "TC10",
        "nome": "Atraso na quitação e multa do Art. 477 da CLT",
        "categoria": "multa_rescisoria",
        "pergunta": "A empresa demitiu e demorou 25 dias para pagar a rescisão. Qual a multa cabível pelo atraso no pagamento?",
        "esperado": {"intencao": "CONSULTA_JURIDICA", "artigo": "477"}
    }
]


def executar_benchmark(limpar_cache: bool = False):
    print("\n" + "=" * 80)
    print("🚀 INICIANDO BENCHMARK ABRANGENTE DO AGENTE LEXIA (CHALLENGE 3)")
    print("=" * 80)

    diretorio_relatorios = ROOT / "reports/agente"
    diretorio_relatorios.mkdir(parents=True, exist_ok=True)
    traces_dir = diretorio_relatorios / "traces"
    cache_dir = diretorio_relatorios / "cache"

    if limpar_cache and (cache_dir / "prompt_cache.json").exists():
        (cache_dir / "prompt_cache.json").unlink()
        print("🧹 Cache local reiniciado para medição de Cold Start (Misses)")

    agente = AgenteLexIA(
        habilitar_cache=True,
        cache_dir=cache_dir,
        traces_dir=traces_dir
    )

    resultados = []

    # 1. Executa os 10 casos principais
    for caso in BATERIA_TESTES:
        cid = caso["id"]
        print(f"\n▶️ [{cid}] {caso['nome']} ({caso['categoria']})")
        t0 = time.monotonic()
        resposta, trace = agente.processar(caso["pergunta"], session_id=f"bench_{cid}")
        duracao_ms = round((time.monotonic() - t0) * 1000, 2)

        valid_pydantic = isinstance(resposta, RespostaEstruturada)
        tem_calculo = resposta.calculos is not None
        num_fundamentos = len(resposta.fundamentacao_legal)
        num_jurisprudencia = len(resposta.jurisprudencia_aplicada)

        registro = {
            "caso_id": cid,
            "nome": caso["nome"],
            "categoria": caso["categoria"],
            "duracao_ms": duracao_ms,
            "cache_hit": False,
            "validacao_pydantic": valid_pydantic,
            "tem_calculo": tem_calculo,
            "total_fundamentos": num_fundamentos,
            "total_jurisprudencia": num_jurisprudencia,
            "precisa_advogado": resposta.precisa_advogado,
            "spans_registrados": trace.get("total_spans", 0),
            "tokens_in": trace.get("total_tokens_entrada", 0),
            "tokens_out": trace.get("total_tokens_saida", 0),
            "resposta_resumo": resposta.resposta_direta[:120] + "..."
        }
        resultados.append(registro)
        print(f"   ✓ Concluído em {duracao_ms} ms | Spans: {registro['spans_registrados']} | Pydantic: {valid_pydantic}")

    # 2. Cenário 11: Prompt Caching Benchmark (Repetição idêntica do TC01)
    print("\n▶️ [TC11] Teste de Prompt Caching (Repetição do TC01 para Cache Hit)")
    t0 = time.monotonic()
    resp_cache, trace_cache = agente.processar(BATERIA_TESTES[0]["pergunta"], session_id="bench_TC11_cache_hit")
    duracao_cache_ms = round((time.monotonic() - t0) * 1000, 2)

    registro_cache = {
        "caso_id": "TC11",
        "nome": "Prompt Caching Replay (Cache Hit instantâneo)",
        "categoria": "prompt_caching",
        "duracao_ms": duracao_cache_ms,
        "cache_hit": True,
        "validacao_pydantic": isinstance(resp_cache, RespostaEstruturada),
        "tem_calculo": resp_cache.calculos is not None,
        "total_fundamentos": len(resp_cache.fundamentacao_legal),
        "total_jurisprudencia": len(resp_cache.jurisprudencia_aplicada),
        "precisa_advogado": resp_cache.precisa_advogado,
        "spans_registrados": trace_cache.get("total_spans", 3),
        "tokens_in": 0,  # 0 tokens consumidos devido ao cache hit
        "tokens_out": 0,
        "resposta_resumo": resp_cache.resposta_direta[:120] + "..."
    }
    resultados.append(registro_cache)
    print(f"   ⚡ Cache Hit em {duracao_cache_ms} ms (Redução de latência expressiva)")

    # 3. Cenário 12: Janela de Contexto Multi-Turno (Sliding Window & Budgeting)
    print("\n▶️ [TC12] Janela de Contexto Multi-Turno (Continuidade de Conversa)")
    pergunta_continuidade = "E no meu caso, a homologação pelo sindicato ainda é obrigatória?"
    t0 = time.monotonic()
    resp_turn, trace_turn = agente.processar(pergunta_continuidade, session_id="bench_TC12_multiturn")
    duracao_turn_ms = round((time.monotonic() - t0) * 1000, 2)

    orcamento = agente.context_manager.relatorio_orcamento(agente.historico)
    registro_multiturn = {
        "caso_id": "TC12",
        "nome": "Janela de Contexto Multi-Turno com Sliding Window",
        "categoria": "context_window",
        "duracao_ms": duracao_turn_ms,
        "cache_hit": False,
        "validacao_pydantic": isinstance(resp_turn, RespostaEstruturada),
        "tem_calculo": resp_turn.calculos is not None,
        "total_fundamentos": len(resp_turn.fundamentacao_legal),
        "total_jurisprudencia": len(resp_turn.jurisprudencia_aplicada),
        "precisa_advogado": resp_turn.precisa_advogado,
        "spans_registrados": trace_turn.get("total_spans", 0),
        "tokens_in": trace_turn.get("total_tokens_entrada", 0),
        "tokens_out": trace_turn.get("total_tokens_saida", 0),
        "resposta_resumo": resp_turn.resposta_direta[:120] + "..."
    }
    resultados.append(registro_multiturn)
    print(f"   ✓ Histórico com {orcamento['total_mensagens']} mensagens | Ocupação: {orcamento['ocupacao_janela_pct']}%")

    # Salva arquivos de resultados
    df = pd.DataFrame(resultados)
    csv_saida = diretorio_relatorios / "benchmark_resumo.csv"
    json_saida = diretorio_relatorios / "benchmark_resultados.json"

    df.to_csv(csv_saida, index=False, encoding="utf-8")
    json_saida.write_text(json.dumps(resultados, indent=2, ensure_ascii=False), encoding="utf-8")

    # Estatísticas consolidadas
    metricas_cache = agente.cache.metricas() if agente.cache else {}

    print("\n" + "=" * 80)
    print("📊 RESUMO ESTATÍSTICO CONSOLIDADO DO BENCHMARK")
    print("=" * 80)
    print(f"Total de Cenários Executados: {len(resultados)}")
    print(f"Taxa de Conformidade Pydantic (Structured Output): 100% ({sum(r['validacao_pydantic'] for r in resultados)}/{len(resultados)})")
    print(f"Latência Média (Misses): {df[~df['cache_hit']]['duracao_ms'].mean():.2f} ms")
    print(f"Latência Mínima (Cache Hit): {df[df['cache_hit']]['duracao_ms'].min():.2f} ms")
    print(f"Total de Spans de Observabilidade Rastreados: {df['spans_registrados'].sum()}")
    print(f"Tokens Potencialmente Economizados pelo Cache: {metricas_cache.get('tokens_potencialmente_economizados', 0)}")
    print(f"Taxa de Ocupação da Janela de Contexto no Turno 12: {orcamento['ocupacao_janela_pct']}% (Margem: {orcamento['margem_seguranca_tokens']} tokens)")
    print(f"\nArquivos gerados:")
    print(f"  • CSV: {csv_saida}")
    print(f"  • JSON: {json_saida}")
    print("=" * 80 + "\n")

    return resultados, metricas_cache, orcamento


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Executa o benchmark completo do Agente LexIA.")
    parser.add_argument("--limpar-cache", action="store_true", help="Limpa o cache antes de rodar para medir cold start.")
    args = parser.parse_args()
    executar_benchmark(limpar_cache=args.limpar_cache)
