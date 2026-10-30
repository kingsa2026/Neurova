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
            self._queryNorm = {"retrievals": 0, "with_matches": 0, "matched_subjects_total": 0}
            self._graphShadow = {
                "retrievals_with_candidates": 0,
                "candidates_total": 0,
                "top5_reach": 0,
                "top1_reach": 0,
            }

    def recordQueryNormalization(self, *, matchedSubjects: int) -> None:
        """查询侧别名归一读数（specs/2026-10-30 W1）：只在 shadow/on 生效时被调。"""
        with self._lock:
            self._queryNorm["retrievals"] += 1
            if int(matchedSubjects) > 0:
                self._queryNorm["with_matches"] += 1
                self._queryNorm["matched_subjects_total"] += int(matchedSubjects)

    def record(
        self,
        *,
        hits: int,
        elapsedMs: float,
        routeCounts: Optional[Dict[str, int]] = None,
        error: bool = False,
        graphShadow: Optional[Dict[str, Any]] = None,
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
            if graphShadow:
                self._graphShadow["retrievals_with_candidates"] += 1
                self._graphShadow["candidates_total"] += max(0, int(
                    graphShadow.get("candidates", 0) or 0
                ))
                rank = graphShadow.get("top_candidate_final_rank")
                if rank is not None:
                    if int(rank) <= 5:
                        self._graphShadow["top5_reach"] += 1
                    if int(rank) == 1:
                        self._graphShadow["top1_reach"] += 1

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
                **(
                    {"query_normalization": dict(self._queryNorm)}
                    if self._queryNorm["retrievals"] > 0
                    else {}
                ),
                **(
                    {"graph_shadow": dict(self._graphShadow)}
                    if self._graphShadow["retrievals_with_candidates"] > 0
                    else {}
                ),
                "uninstrumented": {
                    "refusal_rate": "本进程只统计 finish_reason=content_filter；safety_refusal/tool_failure 等完成态见 /v1/quality/metrics",
                    "human_takeover_rate": "接管事件按 /v1/quality/metrics 的 channel_event/console_mark/api 分账，不在检索进程指标内",
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
