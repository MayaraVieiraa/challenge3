"""Módulo de Observabilidade (Traces e Spans) para o Agente."""
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
import json
import time
import uuid
import pandas as pd


@dataclass
class Span:
    span_id: str
    nome: str
    tipo: str  # 'llm_call', 'tool_execution', 'routing', 'context_management', 'cache'
    inicio: float
    fim: Optional[float] = None
    duracao_ms: Optional[float] = None
    inputs: Dict[str, Any] = field(default_factory=dict)
    outputs: Dict[str, Any] = field(default_factory=dict)
    tokens_entrada: Optional[int] = None
    tokens_saida: Optional[int] = None
    cache_hit: bool = False
    erro: Optional[str] = None

    def finalizar(self, outputs: Optional[Dict[str, Any]] = None, tokens_in: int = 0, tokens_out: int = 0, erro: Optional[str] = None):
        self.fim = time.monotonic()
        self.duracao_ms = round((self.fim - self.inicio) * 1000, 2)
        if outputs is not None:
            self.outputs = outputs
        if tokens_in:
            self.tokens_entrada = tokens_in
        if tokens_out:
            self.tokens_saida = tokens_out
        if erro:
            self.erro = erro


class Tracer:
    """Gerenciador de observabilidade que registra o grafo de execução do agente."""

    def __init__(self, trace_id: Optional[str] = None, session_id: Optional[str] = None, relatorios_dir: Optional[Path] = None):
        self.trace_id = trace_id or str(uuid.uuid4())
        self.session_id = session_id or 'default_session'
        self.spans: List[Span] = []
        self.inicio_total = time.monotonic()
        self.fim_total: Optional[float] = None
        self.relatorios_dir = relatorios_dir or Path('reports/agente/traces')
        self.relatorios_dir.mkdir(parents=True, exist_ok=True)

    def novo_span(self, nome: str, tipo: str, inputs: Optional[Dict[str, Any]] = None) -> Span:
        span = Span(
            span_id=str(uuid.uuid4())[:8],
            nome=nome,
            tipo=tipo,
            inicio=time.monotonic(),
            inputs=inputs or {}
        )
        self.spans.append(span)
        return span

    def finalizar(self, status: str = 'sucesso') -> Dict[str, Any]:
        self.fim_total = time.monotonic()
        duracao_total_ms = round((self.fim_total - self.inicio_total) * 1000, 2)
        total_tokens_in = sum(s.tokens_entrada or 0 for s in self.spans)
        total_tokens_out = sum(s.tokens_saida or 0 for s in self.spans)

        resumo = {
            'trace_id': self.trace_id,
            'session_id': self.session_id,
            'timestamp': datetime.now().isoformat(),
            'status': status,
            'duracao_total_ms': duracao_total_ms,
            'total_spans': len(self.spans),
            'total_tokens_entrada': total_tokens_in,
            'total_tokens_saida': total_tokens_out,
            'spans': [asdict(s) for s in self.spans]
        }

        # Salva o trace individual em JSON
        arquivo_trace = self.relatorios_dir / f"trace_{self.trace_id}.json"
        arquivo_trace.write_text(json.dumps(resumo, indent=2, ensure_ascii=False), encoding='utf-8')

        # Atualiza a tabela consolidada de traces (CSV)
        resumo_csv = {
            'trace_id': self.trace_id,
            'session_id': self.session_id,
            'timestamp': resumo['timestamp'],
            'status': status,
            'duracao_total_ms': duracao_total_ms,
            'total_spans': len(self.spans),
            'tokens_in': total_tokens_in,
            'tokens_out': total_tokens_out,
            'tools_executadas': ', '.join(s.nome for s in self.spans if s.tipo == 'tool_execution'),
            'cache_hits': sum(1 for s in self.spans if s.cache_hit)
        }
        arquivo_consolidado = self.relatorios_dir / 'traces_resumo.csv'
        df_novo = pd.DataFrame([resumo_csv])
        if arquivo_consolidado.exists():
            df_novo.to_csv(arquivo_consolidado, mode='a', header=False, index=False, encoding='utf-8')
        else:
            df_novo.to_csv(arquivo_consolidado, mode='w', header=True, index=False, encoding='utf-8')

        return resumo

    def imprimir_resumo(self):
        """Imprime no console uma árvore visual de spans e tempos de execução."""
        print(f"\n{'='*70}")
        print(f"📊 TRACE ID: {self.trace_id} | Sessão: {self.session_id}")
        print(f"{'='*70}")
        for s in self.spans:
            status_icone = "❌" if s.erro else ("⚡" if s.cache_hit else "✅")
            tokens_str = f" | {s.tokens_entrada or 0} in / {s.tokens_saida or 0} out" if (s.tokens_entrada or s.tokens_saida) else ""
            print(f"  {status_icone} [{s.tipo:<18}] {s.nome:<30} ➔ {s.duracao_ms or 0:>7.1f} ms{tokens_str}")
            if s.erro:
                print(f"     └─ Erro: {s.erro}")
        duracao = round(((self.fim_total or time.monotonic()) - self.inicio_total) * 1000, 1)
        print(f"{'-'*70}")
        print(f"⏱️ Tempo total: {duracao} ms | Spans registrados: {len(self.spans)}")
        print(f"{'='*70}\n")
