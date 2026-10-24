"""Supervisor-Worker 编排：扇出、幂等、重试、失败隔离、RRF 聚合、trace 回放。

设计边界（升级设计 §6.7）：
- 复用 ACP/现有检索结果形状，不新造第二套消息协议；
- `task_id` 是幂等键：同一编排器内重复派发直接回放上次结果；
- 单 worker 失败只落该任务，不拖垮整场；
- 聚合复用 `knowledge.hybrid.rrf_fusion`，权重按 worker 单源配置。
"""
from __future__ import annotations

import asyncio
import copy
import time
import uuid
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

from .contracts import SupervisorTask, WorkerResult

logger = get_logger(__name__)


class SupervisorOrchestrator:
    def __init__(
        self, bus: Any, workerWeights: Optional[Dict[str, float]] = None,
        ledger: Any = None,
    ):
        self._bus = bus
        self._weights = dict(workerWeights or {})
        self._ledger = ledger
        self._cache: Dict[str, WorkerResult] = {}
        self._lock = asyncio.Lock()

    def resetIdempotencyCache(self) -> None:
        self._cache.clear()
        if self._ledger is not None:
            try:
                self._ledger.clear()
            except Exception as exc:  # noqa: BLE001 - 清理失败不阻断调用方
                logger.debug("Supervisor 幂等账本清理失败: %s", exc)

    async def dispatch(
        self,
        tasks: List[SupervisorTask],
        workers: Optional[List[str]] = None,
        aggregate: bool = True,
        traceId: str = "",
    ) -> Dict[str, Any]:
        traceId = traceId or "trace-%s" % uuid.uuid4().hex[:16]
        assignments = self._assign(tasks, workers or [])
        results = await asyncio.gather(
            *(self._runOne(task, workerId, traceId) for task, workerId in assignments)
        )
        aggregated: List[Dict[str, Any]] = []
        if aggregate:
            aggregated = self._aggregate([r for r in results if r.success])
        report = {
            "trace_id": traceId,
            "success": all(r.success for r in results) if results else True,
            "tasks": [r.toDict() for r in results],
            "aggregate": aggregated,
        }
        publishMemory = getattr(self._bus, "publishMemoryUpdate", None)
        if callable(publishMemory):
            # 只有跨进程传输（MQTT）暴露该能力；进程内总线不加这条广播。
            try:
                publishMemory({
                    "trace_id": traceId,
                    "success": report["success"],
                    "task_count": len(results),
                    "document_ids": [row["id"] for row in aggregated[:20]],
                })
            except Exception as exc:  # noqa: BLE001 - 记忆广播失败不影响任务结果
                logger.debug("记忆更新广播失败: %s", exc)
        return report

    @staticmethod
    def _assign(
        tasks: List[SupervisorTask], workers: List[str]
    ) -> List[tuple]:
        assignments = []
        for index, task in enumerate(tasks):
            workerId = task.worker_id
            if not workerId and workers:
                workerId = workers[index % len(workers)]
            assignments.append((task, workerId))
        return assignments

    async def _runOne(self, task: SupervisorTask, workerId: str, traceId: str) -> WorkerResult:
        if not workerId:
            return WorkerResult(
                task_id=task.task_id, success=False,
                error="no_worker_assigned", trace_id=traceId,
            )
        if task.trace_id != traceId:
            task.trace_id = traceId
        cached = await self._cached(task.task_id)
        if cached is not None:
            replay = copy.deepcopy(cached)
            replay.replayed = True
            return replay

        started = time.monotonic()
        attempts = max(int(task.max_retries), 0) + 1
        lastError = ""
        for attempt in range(1, attempts + 1):
            try:
                result = await asyncio.wait_for(
                    self._bus.dispatch(workerId, task, task.deadline),
                    timeout=max(float(task.deadline), 0.001) + 0.05,
                )
            except asyncio.TimeoutError:
                result = WorkerResult(
                    task_id=task.task_id, worker_id=workerId, success=False,
                    error="deadline_exceeded", trace_id=traceId,
                )
            except Exception as exc:  # noqa: BLE001 - 单任务异常隔离
                result = WorkerResult(
                    task_id=task.task_id, worker_id=workerId, success=False,
                    error="dispatch_error:%s" % exc, trace_id=traceId,
                )
            result.attempts = attempt
            result.duration = time.monotonic() - started
            result.trace_id = traceId
            if result.success:
                await self._remember(task.task_id, result)
                return result
            lastError = result.error
            logger.debug(
                "Worker %s 任务 %s 第 %d/%d 次失败: %s",
                workerId, task.task_id, attempt, attempts, lastError,
            )
        final = WorkerResult(
            task_id=task.task_id, worker_id=workerId, success=False,
            error=lastError or "worker_failed", attempts=attempts,
            duration=time.monotonic() - started, trace_id=traceId,
        )
        await self._remember(task.task_id, final)
        return final

    async def _cached(self, taskId: str) -> Optional[WorkerResult]:
        if self._ledger is not None:
            try:
                stored = self._ledger.get(taskId)
                if stored:
                    return WorkerResult(**stored)
            except Exception as exc:  # noqa: BLE001 - 账本故障降级到内存
                logger.warning("Supervisor 幂等账本读取失败，降级内存: %s", exc)
        async with self._lock:
            return self._cache.get(taskId)

    async def _remember(self, taskId: str, result: WorkerResult) -> None:
        async with self._lock:
            self._cache[taskId] = copy.deepcopy(result)
        if self._ledger is not None:
            try:
                self._ledger.save(taskId, result.toDict())
            except Exception as exc:  # noqa: BLE001 - 持久化失败仍保留内存幂等
                logger.warning("Supervisor 幂等账本写入失败: %s", exc)

    def _aggregate(self, results: List[WorkerResult]) -> List[Dict[str, Any]]:
        from neurova.knowledge.hybrid import rrf_fusion

        routes: Dict[str, List[tuple]] = {}
        for result in results:
            rows = []
            for item in result.items:
                docId = str(
                    item.get("id") or item.get("knowledge_id")
                    or item.get("memory_id") or ""
                )
                if not docId:
                    continue
                rows.append((docId, float(item.get("score") or 0.0)))
            if rows:
                routes[result.worker_id] = rows
        if not routes:
            return []
        weights = {
            route: float(self._weights.get(route, 1.0)) for route in routes
        }
        return [
            {"id": docId, "score": round(score, 6)}
            for docId, score in rrf_fusion(routes, weights)
        ]
