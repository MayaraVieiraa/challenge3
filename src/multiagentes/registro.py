"""Exportação local de uma execução; não é um mecanismo de checkpoints."""
from __future__ import annotations

from copy import deepcopy
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import platform
import re

from .contratos import VERSAO_PROMPTS


def salvar_execucao(estado, diretorio, *, diagrama=None):
    """Cria um diretório novo por run_id, sem sobrescrever execuções anteriores.

    Pode conter evidências privadas. O diretório padrão da CLI é ignorado pelo
    Git. Arquivos exportados permitem auditoria, não retomada automática.
    """
    run_id = estado.get("run_id")
    if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", run_id):
        raise ValueError("Identificador de execução inválido.")
    destino = Path(diretorio) / run_id
    dados = deepcopy(estado)
    dados.pop("inicio_monotonic", None)
    serializado = json.dumps(dados, ensure_ascii=False, indent=2, allow_nan=False)
    eventos = "".join(
        json.dumps(e, ensure_ascii=False, allow_nan=False) + "\n"
        for e in dados["eventos"]
    )
    artefatos = {
        "estado.json": serializado,
        "eventos.jsonl": eventos,
        "fontes.json": json.dumps(
            dados.get("fontes_snapshot", {}), ensure_ascii=False, indent=2, allow_nan=False,
        ),
        "resposta.txt": dados["resposta_final"] + "\n",
    }
    if diagrama is not None:
        artefatos["grafo.mmd"] = diagrama
    manifesto = {
        "run_id": run_id,
        "modo": dados["modo"],
        "status": dados["status"],
        "chamadas_llm": dados["chamadas_llm"],
        "falha_injetada": dados["falha_injetada"],
        "python": platform.python_version(),
        "langgraph": version("langgraph"),
        "versao_prompts": VERSAO_PROMPTS,
        "artefatos_sha256": {
            nome: hashlib.sha256(conteudo.encode("utf-8")).hexdigest()
            for nome, conteudo in artefatos.items()
        },
    }
    destino.mkdir(parents=True, exist_ok=False, mode=0o700)
    for nome, conteudo in artefatos.items():
        (destino / nome).write_text(conteudo, encoding="utf-8")
    (destino / "manifesto.json").write_text(
        json.dumps(manifesto, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    return destino
