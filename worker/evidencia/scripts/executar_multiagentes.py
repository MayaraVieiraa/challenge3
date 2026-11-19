"""Executa os agentes reais ou verifica o ambiente; não contém LLM simulada."""
from __future__ import annotations

import argparse
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


PERGUNTAS = {
    "ferias": "Como organizar a leitura de informações sobre férias, de acordo com o material fornecido?",
    "revisao_controlada": "Como organizar a leitura de informações sobre férias, de acordo com o material fornecido?",
    "sem_evidencia": "O que as fontes fornecidas dizem sobre banco de horas?",
    "fora_escopo": "Como rescindir um contrato de aluguel residencial?",
}


def verificar_ambiente(url, modelos):
    from worker.evidencia.langgraph.cliente_llm import ClienteOllama

    ClienteOllama(url)  # Valida a URL sem incluir credenciais nos diagnósticos.
    resultado = {
        "langgraph": version("langgraph"),
        "configuracao_banco_presente": bool(
            os.environ.get("DATABASE_URL") or (ROOT / ".env.pgvector.local").is_file()
        ),
        "banco_consultado": False,
        "modelos_necessarios": modelos,
    }
    try:
        for endpoint in ("version", "tags"):
            pedido = urllib.request.Request(url.rstrip("/") + "/api/" + endpoint)
            with urllib.request.urlopen(pedido, timeout=5) as r:
                dados = json.load(r)
            if endpoint == "version":
                resultado["ollama"] = dados.get("version")
            else:
                resultado["modelos_disponiveis"] = [
                    m.get("name") for m in dados.get("models", []) if m.get("name")
                ]
        resultado["modelos_prontos"] = all(
            modelo in resultado["modelos_disponiveis"] for modelo in modelos
        )
    except (OSError, ValueError, urllib.error.URLError):
        resultado["modelos_prontos"] = False
        resultado["erro"] = "Não foi possível consultar o Ollama."
    return resultado


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--modo", choices=("real", "sintetico", "corpus", "local"), default="sintetico")
    parser.add_argument("--corpus", type=Path,
                        help="JSON portátil no modo corpus ou JSON original de artigos no modo local.")
    parser.add_argument("--cache-embeddings", type=Path,
                        help="Diretório do cache do BuscadorLocal (modo local).")
    parser.add_argument("--device-embeddings", choices=("cpu", "cuda", "mps"),
                        help="Dispositivo do modelo de embeddings; padrão: cpu (modo local).")
    parser.add_argument("--score-minimo", type=float,
                        help="Similaridade mínima da busca; padrão: 0.35 (modo local).")
    parser.add_argument("--top-k", type=int,
                        help="Quantidade máxima de fontes, entre 1 e 6 (modo local).")
    parser.add_argument("--caso", choices=tuple(PERGUNTAS), default="ferias")
    parser.add_argument("--pergunta")
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    parser.add_argument("--modelo-analista", default="qwen3:8b-q8_0")
    parser.add_argument("--modelo-validador", default="gemma3:12b")
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--tempo-maximo", type=float, default=900)
    parser.add_argument("--saida", type=Path, default=ROOT / "dados/output/multiagentes")
    parser.add_argument("--verificar-ambiente", action="store_true")
    parser.add_argument("--preparar-lexico", action="store_true")
    args = parser.parse_args(argv)
    try:
        version("langgraph")
    except PackageNotFoundError:
        parser.error("Instale as dependências com python -m pip install -r docs/legado/requirements/requirements-multiagentes.txt.")
    if args.verificar_ambiente:
        resultado = verificar_ambiente(
            args.ollama_url, [args.modelo_analista, args.modelo_validador],
        )
        print(json.dumps(resultado, ensure_ascii=False, indent=2))
        return 0 if resultado["modelos_prontos"] else 2
    if args.modo != "sintetico" and args.caso == "revisao_controlada":
        parser.error("A revisão com erro inserido só é permitida no modo sintetico.")
    if args.modo == "corpus" and args.corpus is None:
        parser.error("--modo corpus exige --corpus com o caminho do pacote de legislação.")
    if args.preparar_lexico and args.modo != "real":
        parser.error("--preparar-lexico só é usado no modo real.")
    if args.modo != "local" and any(valor is not None for valor in (
        args.cache_embeddings, args.device_embeddings, args.score_minimo, args.top_k,
    )):
        parser.error("As opções de embeddings e --top-k só são usadas no modo local.")

    from worker.evidencia.langgraph.cliente_llm import ClienteOllama, ErroLLM
    from worker.evidencia.langgraph.ferramentas import BuscaCorpus, BuscaReal, BuscaSintetica
    from worker.evidencia.langgraph.orquestrador import ConfiguracaoSistema, SistemaMultiagentes
    from worker.evidencia.langgraph.registro import salvar_execucao

    try:
        config = ConfiguracaoSistema(
            timeout_segundos=args.timeout, tempo_maximo_segundos=args.tempo_maximo,
            modelo_analista=args.modelo_analista, modelo_validador=args.modelo_validador,
        )
        cliente = ClienteOllama(args.ollama_url, timeout=args.timeout)
    except (ValueError, ErroLLM):
        parser.error("Configuração de modelos, limites ou URL inválida.")
    try:
        if args.modo == "real":
            busca = BuscaReal(ROOT)
        elif args.modo == "corpus":
            busca = BuscaCorpus(args.corpus)
        elif args.modo == "local":
            from worker.evidencia.langgraph.buscador_local import BuscadorLocal

            opcoes = dict(root=ROOT, cache_dir=args.cache_embeddings)
            for nome, valor in (("device", args.device_embeddings),
                                ("score_minimo", args.score_minimo), ("top_k", args.top_k)):
                if valor is not None:
                    opcoes[nome] = valor
            busca = BuscadorLocal(args.corpus, **opcoes)
        else:
            busca = BuscaSintetica("sem_evidencia" if args.caso == "sem_evidencia" else "ferias")
    except (OSError, ValueError) as erro:
        parser.error(f"Configuração da busca inválida ({type(erro).__name__}). Confira corpus e parâmetros.")
    try:
        if args.preparar_lexico:
            print("Índice lexical:", busca.preparar_lexico())
        if args.modo == "local":
            # A primeira indexação pode ser demorada. Ela ocorre antes do
            # orçamento de atendimento dos agentes e é reaproveitada na busca.
            indice = busca.preparar_indice()
            print("Índice local:", indice["quantidade_artigos"],
                  "artigos | Cache reutilizado:", indice["cache_reutilizado"])
        sistema = SistemaMultiagentes(cliente, busca, config=config)
        pergunta_padrao = (
            "Quais são as regras gerais sobre férias segundo as fontes fornecidas?"
            if args.modo in ("real", "corpus", "local") and args.caso == "ferias"
            else PERGUNTAS[args.caso]
        )
        estado = sistema.executar(
            args.pergunta or pergunta_padrao, modo=args.modo, caso=args.caso,
        )
        diretorio = salvar_execucao(
            estado, args.saida, diagrama=sistema.grafo.get_graph().draw_mermaid(),
        )
    except Exception as erro:
        print(
            f"Não foi possível preparar ou registrar a execução ({type(erro).__name__}). "
            "Confira os pré-requisitos e o diretório de saída.",
            file=sys.stderr,
        )
        return 2
    finally:
        busca.fechar()
    if args.modo == "sintetico":
        print("Modo sintético: fontes fictícias; inferência com os modelos configurados.")
    elif args.modo == "corpus":
        print("Modo corpus: busca lexical na legislação portátil; inferência com os modelos configurados.")
    elif args.modo == "local":
        print("Modo local: busca semântica nos artigos, com cache de embeddings e inferência nos modelos configurados.")
    for evento in estado["eventos"]:
        print(f'{evento["numero"]:02d} {evento["agente"]}: {evento["etapa"]}')
    print(f'\nStatus: {estado["status"]} | Motivo: {estado["motivo"]}')
    print(estado["resposta_final"])
    print(f'\nChamadas: {estado["chamadas_llm"]} | Revisões: {estado["revisoes_usadas"]}')
    print(f"Arquivos da execução: {diretorio}")
    return 2 if estado["status"] == "falha_tecnica" else 0


if __name__ == "__main__":
    raise SystemExit(main())
