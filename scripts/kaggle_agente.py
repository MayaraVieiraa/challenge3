"""Kernel do Kaggle (GPU T4) / Execução Local para o Agente LexIA (Challenge 3).

Executa em lote o ciclo completo do Agente com as 6 capacidades:
1. Tool Calling (Agente autônomo com ferramentas matemáticas determinísticas e jurídicas)
2. Stracting (Extração estruturada de entidades e roteamento de intenção)
3. Prompt Caching (Prefix caching OLLAMA_KEEP_ALIVE: -1 e cache canônico SHA-256)
4. Observabilidade (Spans com latência, contagem de tokens e traces JSON/CSV)
5. Janela de Contexto (Context Window Management, sliding window e orçamento de tokens)
6. Structured Output (Validação estrita Pydantic e persistência JSONL)
"""

import glob
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# Adiciona o diretório do projeto ao sys.path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.agente.core import AgenteLexIA
from src.agente.schemas import RespostaEstruturada


OLLAMA_VERSAO = '0.40.16'
URL_OLLAMA = 'http://127.0.0.1:11434'
EH_KAGGLE = Path('/kaggle/working').exists()
DIRETORIO_SAIDA = Path('/kaggle/working') if EH_KAGGLE else (ROOT / 'reports/agente')


def sh(comando: str):
    print('$', comando, flush=True)
    subprocess.run(comando, shell=True, check=True)


def garantir_ollama_ativo(modelo: str):
    """Inicia o daemon do Ollama se estiver no ambiente Kaggle com GPU T4."""
    if EH_KAGGLE:
        sh('apt-get install -y -q zstd > /dev/null 2>&1 || true')
        sh(f'curl -fsSL https://ollama.com/install.sh | OLLAMA_VERSION={OLLAMA_VERSAO} sh')
        log = open('/kaggle/working/ollama.log', 'w')
        subprocess.Popen(['ollama', 'serve'], env={**os.environ, 'OLLAMA_KEEP_ALIVE': '-1'}, stdout=log, stderr=log)
        time.sleep(3)
        sh(f'ollama pull {modelo}')


def carregar_pedidos() -> list:
    """Carrega pedidos de dataset do Kaggle ou usa bateria representativa de testes."""
    arquivos_kaggle = glob.glob('/kaggle/input/**/pedidos_agente.jsonl', recursive=True)
    if arquivos_kaggle:
        return [json.loads(l) for l in open(arquivos_kaggle[0], encoding='utf-8') if l.strip()]

    # Bateria padrão representativa cobrindo os casos de uso de Direito do Trabalho
    return [
        {
            "pergunta_id": "ped_agente_001",
            "pergunta": "Fui demitido sem justa causa. Meu salário era de R$ 3.000,00 e trabalhei por 8 meses. Tenho direito a aviso prévio e multa do FGTS? Quanto vou receber?",
            "categoria": "calculo_rescisao"
        },
        {
            "pergunta_id": "ped_agente_002",
            "pergunta": "Fui dispensado em 10/01/2023. Até quando posso ingressar com uma reclamação trabalhista na Justiça do Trabalho sem perder o direito?",
            "categoria": "prescricao"
        },
        {
            "pergunta_id": "ped_agente_003",
            "pergunta": "Minha jornada era das 22h às 7h da manhã. O adicional noturno deve incidir também nas horas trabalhadas após as 5h?",
            "categoria": "adicional_noturno_sumula60"
        },
        {
            "pergunta_id": "ped_agente_004",
            "pergunta": "Pedi demissão com 1 ano e 2 meses de empresa, com salário de R$ 2.500,00. Tenho direito a sacar o FGTS e receber seguro-desemprego?",
            "categoria": "pedido_demissao"
        },
        {
            "pergunta_id": "ped_agente_005",
            "pergunta": "A empresa atrasou o pagamento das minhas verbas rescisórias em mais de 15 dias. Há alguma multa aplicável prevista na CLT?",
            "categoria": "multa_art477"
        }
    ]


def main():
    modelo = os.environ.get("MODELO_AGENTE", "qwen3:8b")
    print(f"🚀 Iniciando Agente no ambiente: {'KAGGLE' if EH_KAGGLE else 'LOCAL (Mac/Metal)'}")
    print(f"📌 Modelo: {modelo} | Diretório de Saída: {DIRETORIO_SAIDA}")

    DIRETORIO_SAIDA.mkdir(parents=True, exist_ok=True)
    arquivo_respostas = DIRETORIO_SAIDA / "respostas_agente.jsonl"
    traces_dir = DIRETORIO_SAIDA / "traces"
    traces_dir.mkdir(parents=True, exist_ok=True)

    garantir_ollama_ativo(modelo)

    pedidos = carregar_pedidos()
    print(f"📦 Total de pedidos a processar: {len(pedidos)}")

    agente = AgenteLexIA(
        modelo=modelo,
        url_ollama=URL_OLLAMA,
        habilitar_cache=True,
        cache_dir=DIRETORIO_SAIDA / "cache",
        traces_dir=traces_dir
    )

    feitos = set()
    if arquivo_respostas.exists():
        feitos = {json.loads(l)["pergunta_id"] for l in arquivo_respostas.read_text(encoding="utf-8").splitlines() if l.strip()}

    pendentes = [p for p in pedidos if p["pergunta_id"] not in feitos]
    print(f"⏳ Pendentes de processamento: {len(pendentes)}")

    with arquivo_respostas.open("a", encoding="utf-8") as saida:
        for i, ped in enumerate(pendentes, 1):
            pid = ped["pergunta_id"]
            texto = ped["pergunta"]
            print(f"\n[{i}/{len(pendentes)}] Processando {pid}...")

            t_ini = time.monotonic()
            resposta, trace = agente.processar(texto, session_id=f"sessao_{pid}")
            duracao = round(time.monotonic() - t_ini, 3)

            registro = {
                "pergunta_id": pid,
                "categoria": ped.get("categoria", "geral"),
                "pergunta": texto,
                "duracao_segundos": duracao,
                "resposta_estruturada": resposta.model_dump(),
                "trace_resumo": trace
            }

            saida.write(json.dumps(registro, ensure_ascii=False) + "\n")
            saida.flush()
            print(f"   ➔ Concluído em {duracao:.2f}s | Status: {trace.get('status', 'OK')}")

    print("\n" + "=" * 80)
    print("🎉 Lote de processamento do Agente concluído com sucesso!")
    print(f"📄 Respostas gravadas em: {arquivo_respostas}")
    print(f"📊 Traces consolidados em: {traces_dir / 'traces_resumo.csv'}")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
