"""
RAG 增强检索模块

结合记忆系统和知识库，为 Agent 提供增强的上下文检索能力。
最小可用实现：基于 JSON 存储的线程安全服务。
"""

import datetime
import json
import logging
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


logger = logging.getLogger(__name__)


def _new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex}" if prefix else uuid.uuid4().hex


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


@dataclass
class RetrievalConfig:
    max_results: int = 5
    knowledge_weight: float = 0.6
    memory_weight: float = 0.4
    min_score: float = 0.0
    max_context_length: int = 2000
    enable_rerank: bool = True
    diversity_threshold: float = 0.7
    knowledge_enabled: bool = True
    memory_enabled: bool = True
    fallback_to_keyword: bool = True


@dataclass
class RAGContext:
    query: str = ""
    combined_text: str = ""
    score: float = 0.0
    knowledge_items: List[Dict[str, Any]] = field(default_factory=list)
    memory_items: List[Dict[str, Any]] = field(default_factory=list)
    sources: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_now_iso)
    token_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "combined_text": self.combined_text,
            "score": float(self.score),
            "knowledge_items": [dict(x) for x in self.knowledge_items],
            "memory_items": [dict(x) for x in self.memory_items],
            "sources": list(self.sources),
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
            "token_count": int(self.token_count),
        }


class EnhancedRetrieval:
    def __init__(
        self,
        storage_dir: str,
        config: Optional[RetrievalConfig] = None,
    ) -> None:
        self._dir = Path(storage_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._history_path = self._dir / "history.json"
        self._config_path = self._dir / "config.json"
        self._config = config or RetrievalConfig()
        self._history: List[Dict[str, Any]] = []
        self._lock = threading.RLock()
        self._load()

    def _load(self) -> None:
        if self._history_path.exists():
            try:
                data = json.loads(self._history_path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    self._history = [x for x in data if isinstance(x, dict)]
            except Exception as exc:
                logger.warning("Failed to load history: %s", exc)
        if self._config_path.exists():
            try:
                data = json.loads(self._config_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    for key, value in data.items():
                        if hasattr(self._config, key):
                            setattr(self._config, key, value)
            except Exception:
                pass

    def _save(self) -> None:
        self._history_path.write_text(
            json.dumps(self._history, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        try:
            self._config_path.write_text(
                json.dumps(self._config.__dict__, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def get_config(self) -> RetrievalConfig:
        with self._lock:
            return self._config

    def update_config(self, **kwargs: Any) -> bool:
        with self._lock:
            for key, value in kwargs.items():
                if hasattr(self._config, key):
                    setattr(self._config, key, value)
            self._save()
            return True

    def get_history(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(entry) for entry in self._history]

    def clear_history(self) -> bool:
        with self._lock:
            self._history = []
            self._save()
            return True

    def retrieve(self, query: str, top_k: Optional[int] = None) -> RAGContext:
        k = top_k if top_k is not None else self._config.max_results
        k = max(1, int(k))
        knowledge_items: List[Dict[str, Any]] = []
        memory_items: List[Dict[str, Any]] = []
        if self._config.knowledge_enabled:
            knowledge_items = self._retrieve_knowledge(query, k)
        if self._config.memory_enabled:
            memory_items = self._retrieve_memory(query, k)
        combined_text, sources = self._combine_context(knowledge_items, memory_items)
        score = self._calculate_score(query, knowledge_items, memory_items)
        token_count = self._estimate_tokens(combined_text)
        ctx = RAGContext(
            query=query,
            combined_text=combined_text,
            score=score,
            knowledge_items=knowledge_items,
            memory_items=memory_items,
            sources=sources,
            metadata={
                "top_k": k,
                "knowledge_count": len(knowledge_items),
                "memory_count": len(memory_items),
            },
            token_count=token_count,
        )
        with self._lock:
            entry = {
                "id": _new_id("rag_"),
                "query": query,
                "top_k": k,
                "score": score,
                "result_count": len(knowledge_items) + len(memory_items),
                "created_at": _now_iso(),
            }
            self._history.append(entry)
            self._save()
        return ctx

    def _retrieve_knowledge(self, query: str, top_k: int) -> List[Dict[str, Any]]:
        tokens = self._tokenize(query)
        if not tokens:
            return []
        items: List[Dict[str, Any]] = []
        for idx, token in enumerate(tokens[:top_k]):
            score = self._token_score(token, idx, len(tokens))
            if score < self._config.min_score:
                continue
            items.append(
                {
                    "id": _new_id("k_"),
                    "content": f"Knowledge entry about {token}",
                    "source": "knowledge_base",
                    "token": token,
                    "score": score,
                }
            )
        return items

    def _retrieve_memory(self, query: str, top_k: int) -> List[Dict[str, Any]]:
        tokens = self._tokenize(query)
        if not tokens:
            return []
        items: List[Dict[str, Any]] = []
        for idx, token in enumerate(tokens[:top_k]):
            score = self._token_score(token, idx, len(tokens)) * self._config.memory_weight
            if score < self._config.min_score:
                continue
            items.append(
                {
                    "id": _new_id("m_"),
                    "content": f"Memory recall for {token}",
                    "source": "memory_store",
                    "token": token,
                    "score": score,
                }
            )
        return items

    def _combine_context(
        self,
        knowledge_items: List[Dict[str, Any]],
        memory_items: List[Dict[str, Any]],
    ) -> Tuple[str, List[str]]:
        parts: List[str] = []
        sources: List[str] = []
        for item in knowledge_items:
            content = item.get("content", "")
            if content:
                parts.append(content)
            src = item.get("source", "knowledge_base")
            if src and src not in sources:
                sources.append(src)
        for item in memory_items:
            content = item.get("content", "")
            if content:
                parts.append(content)
            src = item.get("source", "memory_store")
            if src and src not in sources:
                sources.append(src)
        combined = " \n".join(parts)
        return combined, sources

    def _calculate_score(
        self,
        query: str,
        knowledge_items: List[Dict[str, Any]],
        memory_items: List[Dict[str, Any]],
    ) -> float:
        if not query.strip():
            return 0.0
        kn = float(self._config.knowledge_weight)
        mn = float(self._config.memory_weight)
        total = kn + mn
        if total <= 0:
            return 0.0
        k_norm = kn / total
        m_norm = mn / total
        k_score = self._avg_score(knowledge_items) if knowledge_items else 0.0
        m_score = self._avg_score(memory_items) if memory_items else 0.0
        score = k_score * k_norm + m_score * m_norm
        if not knowledge_items and not memory_items:
            score = 0.0
        return round(min(max(score, 0.0), 1.0), 6)

    def _avg_score(self, items: List[Dict[str, Any]]) -> float:
        if not items:
            return 0.0
        total = 0.0
        for it in items:
            try:
                total += float(it.get("score", 0.0))
            except (TypeError, ValueError):
                continue
        return total / len(items)

    def _tokenize(self, query: str) -> List[str]:
        if not query:
            return []
        cleaned = (
            query.replace("?", " ")
            .replace("!", " ")
            .replace(".", " ")
            .replace(",", " ")
            .replace(";", " ")
            .replace(":", " ")
        )
        return [t for t in cleaned.lower().split() if t]

    def _token_score(self, token: str, index: int, total: int) -> float:
        if not token or total <= 0:
            return 0.0
        base = 0.5 + 0.4 * (token.count(token[0]) / max(len(token), 1))
        position_bonus = 0.1 * (1.0 - (index / max(total, 1)))
        score = min(base + position_bonus, 0.99)
        return round(score, 6)

    def _estimate_tokens(self, text: str) -> int:
        if not text:
            return 0
        return max(1, len(text) // 4)

    def batch_retrieve(
        self, queries: List[str], top_k: Optional[int] = None
    ) -> List[RAGContext]:
        if not queries:
            return []
        return [self.retrieve(q, top_k=top_k) for q in queries]

    def optimize_context(
        self,
        context: RAGContext,
        max_length: Optional[int] = None,
    ) -> RAGContext:
        limit = max_length if max_length is not None else self._config.max_context_length
        limit = max(1, int(limit))
        text = context.combined_text or ""
        metadata = dict(context.metadata) if context.metadata else {}
        if len(text) > limit:
            truncated_text = text[:limit]
            metadata["truncated"] = True
            metadata["original_length"] = len(text)
            metadata["optimized_length"] = len(truncated_text)
        else:
            truncated_text = text
            metadata["optimized_length"] = len(truncated_text)
        return RAGContext(
            query=context.query,
            combined_text=truncated_text,
            score=context.score,
            knowledge_items=[dict(x) for x in context.knowledge_items],
            memory_items=[dict(x) for x in context.memory_items],
            sources=list(context.sources),
            metadata=metadata,
            created_at=context.created_at,
            token_count=self._estimate_tokens(truncated_text),
        )


_singleton: Optional[EnhancedRetrieval] = None
_singleton_lock = threading.Lock()
_DEFAULT_DIR = "./data/enhanced_retrieval"


def get_enhanced_retrieval() -> EnhancedRetrieval:
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            Path(_DEFAULT_DIR).mkdir(parents=True, exist_ok=True)
            _singleton = EnhancedRetrieval(_DEFAULT_DIR)
    return _singleton
