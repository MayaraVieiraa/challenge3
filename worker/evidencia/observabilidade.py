"""Eventos de execução sem prompts, respostas ou outros dados de usuário."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import uuid


class Observabilidade:
    def __init__(self, caminho: Path, run_id: str | None = None):
        self.caminho = Path(caminho)
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id or str(uuid.uuid4())

    def registrar(
        self,
        etapa: str,
        *,
        status: str,
        duracao_ms: float | None = None,
        pergunta_id: str | None = None,
        metricas: dict[str, int | float | bool] | None = None,
        tipo_erro: str | None = None,
    ) -> None:
        metricas = metricas or {}
        if not etapa.strip() or not status.strip():
            raise ValueError("Etapa e status são obrigatórios.")
        if duracao_ms is not None and (not math.isfinite(duracao_ms) or duracao_ms < 0):
            raise ValueError("A duração deve ser um número finito não negativo.")
        for nome, valor in metricas.items():
            if not nome.strip() or not isinstance(valor, (int, float, bool)):
                raise TypeError("Métricas devem ter nomes e valores numéricos ou booleanos.")
            if isinstance(valor, float) and not math.isfinite(valor):
                raise ValueError("Métricas numéricas devem ser finitas.")

        evento = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "run_id": self.run_id,
            "etapa": etapa,
            "status": status,
            "duracao_ms": round(duracao_ms, 2) if duracao_ms is not None else None,
            "pergunta_id_sha256": hashlib.sha256(pergunta_id.encode("utf-8")).hexdigest() if pergunta_id else None,
            "metricas": metricas,
            "tipo_erro": tipo_erro,
        }
        with self.caminho.open("a", encoding="utf-8", newline="\n") as arquivo:
            arquivo.write(json.dumps(evento, ensure_ascii=False, allow_nan=False) + "\n")
