"""Consulta o índice semântico local sem executar os agentes ou depender de Ollama."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, help="JSON original dos artigos completos.")
    parser.add_argument("--cache-embeddings", type=Path, help="Diretório para persistir os embeddings.")
    parser.add_argument("--device-embeddings", choices=("cpu", "cuda", "mps"), default="cpu")
    parser.add_argument("--top-k", type=int, default=6, help="Número máximo de fontes, de 1 a 6.")
    parser.add_argument("--score-minimo", type=float, default=0.35)
    parser.add_argument("--pergunta", help="Pergunta para recuperar fontes.")
    parser.add_argument("--preparar-indice", action="store_true",
                        help="Prepara/confere o cache mesmo sem fazer uma consulta.")
    parser.add_argument("--mostrar-texto", action="store_true",
                        help="Inclui os artigos completos na saída; padrão: apenas referências.")
    args = parser.parse_args(argv)
    if not args.preparar_indice and not (args.pergunta and args.pergunta.strip()):
        parser.error("Informe --pergunta ou --preparar-indice.")
    if args.pergunta is not None and not args.pergunta.strip():
        parser.error("--pergunta não pode ser vazia.")
    if args.mostrar_texto and args.pergunta is None:
        parser.error("--mostrar-texto exige --pergunta.")

    from worker.evidencia.langgraph.buscador_local import BuscadorLocal

    busca = None
    try:
        busca = BuscadorLocal(
            args.corpus, root=ROOT, cache_dir=args.cache_embeddings,
            device=args.device_embeddings, top_k=args.top_k,
            score_minimo=args.score_minimo,
        )
        # A preparação explícita permite comparar cache frio e reutilizado
        # sem calcular um embedding de consulta nem chamar uma LLM.
        busca.preparar_indice()
        fontes = busca.buscar(args.pergunta) if args.pergunta is not None else []
        referencias = []
        for fonte in fontes:
            referencia = {nome: fonte[nome] for nome in (
                "unidade", "fonte", "artigo_ref", "caminho_relativo", "similaridade",
                "source", "date", "retrieved", "status_declarado",
            ) if nome in fonte}
            if args.mostrar_texto:
                referencia["conteudo"] = fonte["conteudo"]
            referencias.append(referencia)
        print(json.dumps({"diagnostico": busca.diagnostico, "fontes": referencias},
                         ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except Exception as erro:
        print(
            f"Não foi possível consultar o índice local ({type(erro).__name__}). "
            "Confira o JSON dos artigos, o diretório de cache e as dependências do buscador. "
            "Se a base deste clone usa DVC, obtenha os dados com dvc pull.",
            file=sys.stderr,
        )
        return 2
    finally:
        if busca is not None:
            busca.fechar()


if __name__ == "__main__":
    raise SystemExit(main())
