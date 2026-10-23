"""知识检索进程内指标（在线快照，不持久化）。

只记录检索链实际产生的读数：请求数、命中数、空结果、异常、延迟、各路命中数，
以及回答完成态里可识别的 model_refusal（finish_reason=content_filter）。
token 成本按命中事实均分归因（knowledge_token_usage，非逐条真实成本）；
人工接管与一般拒答仍需要上游结构化事件，未接前在 uninstrumented 点名。
"""
from __future__ import annotations

import threading
from typing import Any, Dict, Optional


class RetrievalMetrics:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self._requests = 0
            self._hits = 0
            self._empty = 0
            self._errors = 0
            self._latency_ms_sum = 0.0
            self._latency_ms_max = 0.0
            self._routes: Dict[str, int] = {}
            self._outcomes: Dict[str, int] = {"model_refusal": 0}

    def record(
        self,
        *,
        hits: int,
        elapsedMs: float,
        routeCounts: Optional[Dict[str, int]] = None,
        error: bool = False,
    ) -> None:
        with self._lock:
            self._requests += 1
            self._hits += max(0, int(hits))
            if hits <= 0:
                self._empty += 1
            if error:
                self._errors += 1
            elapsed = max(0.0, float(elapsedMs))
            self._latency_ms_sum += elapsed
            self._latency_ms_max = max(self._latency_ms_max, elapsed)
            for route, count in (routeCounts or {}).items():
                if int(count) > 0:
                    self._routes[route] = self._routes.get(route, 0) + int(count)

    def recordOutcome(self, kind: str, count: int = 1) -> None:
        """记录回答完成态的硬信号；只收本层真能识别的 kind。"""
        with self._lock:
            if kind in self._outcomes:
                self._outcomes[kind] += max(0, int(count))

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            measured = self._requests > 0
            return {
                "measure_state": "measured" if measured else "unevidenced",
                "requests": self._requests,
                "hits": self._hits,
                "empty": self._empty,
                "errors": self._errors,
                "latency_ms": {
                    "avg": round(self._latency_ms_sum / self._requests, 3) if measured else None,
                    "max": round(self._latency_ms_max, 3) if measured else None,
                },
                "route_hits": dict(sorted(self._routes.items())),
                "outcomes": dict(self._outcomes),
                "uninstrumented": {
                    "refusal_rate": "仅统计 finish_reason=content_filter 的模型拒绝；无答案/其他拒答未归档",
                    "human_takeover_rate": "渠道人工接管事件未进入检索域",
                },
                "note": "进程内自启动以来累计；重启清零。缺的指标在 uninstrumented 里点名，不伪造 0。",
            }


_metrics = RetrievalMetrics()
_metrics_lock = threading.Lock()


def get_retrieval_metrics() -> RetrievalMetrics:
    return _metrics


def reset_retrieval_metrics() -> None:
    with _metrics_lock:
        _metrics.reset()
