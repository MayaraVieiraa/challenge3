"""Módulo de Prompt Caching e Otimização de Prefixo para o Agente."""
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
import hashlib
import json
import time


class PromptCache:
    """Gerenciador de cache local de prompts e respostas para evitar chamadas redundantes."""

    def __init__(self, cache_dir: Optional[Path] = None, ttl_segundos: int = 86400):
        self.cache_dir = cache_dir or Path('reports/agente/cache')
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.arquivo_cache = self.cache_dir / 'prompt_cache.json'
        self.ttl = ttl_segundos
        self.memoria: Dict[str, Dict[str, Any]] = self._carregar()
        self.hits = 0
        self.misses = 0

    def _carregar(self) -> Dict[str, Dict[str, Any]]:
        if self.arquivo_cache.exists():
            try:
                return json.loads(self.arquivo_cache.read_text(encoding='utf-8'))
            except Exception:
                return {}
        return {}

    def _salvar(self):
        try:
            self.arquivo_cache.write_text(json.dumps(self.memoria, indent=2, ensure_ascii=False), encoding='utf-8')
        except Exception:
            pass

    @staticmethod
    def gerar_chave(modelo: str, mensagens: list, tools: Optional[list] = None, opcoes: Optional[dict] = None) -> str:
        """Gera hash SHA-256 canônico a partir do prefixo de mensagens, modelo e schemas de tools."""
        payload = {
            'modelo': modelo,
            'mensagens': mensagens,
            'tools': tools or [],
            'opcoes': opcoes or {}
        }
        texto = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(texto.encode('utf-8')).hexdigest()

    def obter(self, chave: str) -> Optional[Dict[str, Any]]:
        """Busca resposta em cache se não tiver expirado."""
        item = self.memoria.get(chave)
        if not item:
            self.misses += 1
            return None
        agora = time.time()
        if agora - item.get('criado_em', 0) > self.ttl:
            del self.memoria[chave]
            self.misses += 1
            return None
        self.hits += 1
        return item.get('resposta')

    def gravar(self, chave: str, resposta: Dict[str, Any], tokens_entrada: int = 0, tokens_saida: int = 0):
        """Armazena resposta no cache com timestamp."""
        self.memoria[chave] = {
            'resposta': resposta,
            'criado_em': time.time(),
            'tokens_entrada': tokens_entrada,
            'tokens_saida': tokens_saida
        }
        self._salvar()

    def metricas(self) -> Dict[str, Any]:
        total = self.hits + self.misses
        taxa = (self.hits / total * 100) if total > 0 else 0.0
        tokens_economizados = sum(item.get('tokens_entrada', 0) + item.get('tokens_saida', 0)
                                  for item in self.memoria.values())
        return {
            'total_requisicoes': total,
            'cache_hits': self.hits,
            'cache_misses': self.misses,
            'taxa_acerto_pct': round(taxa, 2),
            'itens_armazenados': len(self.memoria),
            'tokens_potencialmente_economizados': tokens_economizados
        }
