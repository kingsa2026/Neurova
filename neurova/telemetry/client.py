"""遥测客户端（P2-13）：缓冲、批量导出、DCL 单例。

- 显式开关：``NEUROVA_TELEMETRY_ENABLED``（默认 **0=关**；显式 1 才开）；
- 端点：``NEUROVA_TELEMETRY_ENDPOINT``（OTLP/HTTP JSON logs）；
- 服务名：``NEUROVA_TELEMETRY_SERVICE_NAME``（默认 neurova）；
- fail-open：导出失败只计 dropped，绝不阻断调用方；
- 单例：懒创建 DCL + RLock（AGENTS.md §3 口径）。
"""

from __future__ import annotations

import os
import queue
import threading
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger
from neurova.telemetry.otlp import buildOtlpLogsPayload, exportOtlpLogs
from neurova.telemetry.sanitize import sanitizeValue

logger = get_logger(__name__)

_ENABLED_ENV = "NEUROVA_TELEMETRY_ENABLED"
_ENDPOINT_ENV = "NEUROVA_TELEMETRY_ENDPOINT"
_SERVICE_ENV = "NEUROVA_TELEMETRY_SERVICE_NAME"


def telemetryEnabled() -> bool:
    """env 显式 1/true/on 才开；默认关（隐私优先，与仓内开关口径一致）。"""
    return os.environ.get(_ENABLED_ENV, "").strip().lower() in ("1", "true", "yes", "on")


class TelemetryClient:
    """缓冲-批量-导出的遥测客户端（后台线程定时/足量即发）。"""

    def __init__(self, batchSize: int = 50, flushInterval: float = 2.0, timeout: float = 3.0):
        self._enabled = telemetryEnabled()
        self._endpoint = os.environ.get(_ENDPOINT_ENV, "")
        self._serviceName = os.environ.get(_SERVICE_ENV, "neurova")
        self._batchSize = max(1, batchSize)
        self._flushInterval = max(0.5, flushInterval)
        self._timeout = timeout
        self._queue: "queue.Queue[Dict[str, Any]]" = queue.Queue(maxsize=10000)
        self._stats = {"recorded": 0, "exported": 0, "dropped": 0}
        self._stop = threading.Event()
        self._lock = threading.RLock()
        self._worker: Optional[threading.Thread] = None

    def record(self, entry: Dict[str, Any]) -> bool:
        """记录一条事件；关=丢弃返回 False，开=入队返回 True（fail-open）。"""
        if not self._enabled:
            self._stats["dropped"] += 1
            return False
        if not isinstance(entry, dict):
            self._stats["dropped"] += 1
            return False
        try:
            clean = sanitizeValue(entry)
            self._queue.put_nowait(clean)
            self._stats["recorded"] += 1
            self._ensureWorker()
            return True
        except Exception as e:  # noqa: BLE001 - 队列满/进程退出期等：丢弃不抛
            self._stats["dropped"] += 1
            logger.debug("遥测入队失败（丢弃）: %s", e)
            return False

    def recordBatch(self, entries: List[Dict[str, Any]]) -> bool:
        """批量记录；任一条入队成功即 True。"""
        sent = False
        for entry in entries or []:
            if self.record(entry):
                sent = True
        return sent

    def flush(self, timeout: float = 10.0) -> None:
        """阻塞把当前缓冲全部导出（测试与关停用）。"""
        import time as _time

        deadline = _time.time() + max(0.0, timeout)
        while not self._queue.empty() and _time.time() < deadline:
            self._flushOnce()
        self._flushOnce()

    @property
    def stats(self) -> Dict[str, int]:
        """导出计数读数（recorded/exported/dropped）。"""
        return dict(self._stats)

    def _ensureWorker(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                return
            self._worker = threading.Thread(
                target=self._workerLoop, name="neurova-telemetry", daemon=True
            )
            self._worker.start()

    def _workerLoop(self) -> None:
        while not self._stop.is_set():
            # 先等再发：避免后台线程与调用方的 flush 赛跑抢同一批
            if self._stop.wait(self._flushInterval):
                break
            try:
                self._flushOnce()
            except Exception as e:  # noqa: BLE001 - 后台线程绝不让异常外溢
                logger.debug("遥测后台导出异常: %s", e)

    def _flushOnce(self) -> None:
        batch: List[Dict[str, Any]] = []
        try:
            while len(batch) < self._batchSize:
                batch.append(self._queue.get_nowait())
        except queue.Empty:
            pass
        if not batch:
            return
        payload = buildOtlpLogsPayload(batch, self._serviceName)
        if exportOtlpLogs(self._endpoint, payload, timeout=self._timeout):
            self._stats["exported"] += len(batch)
        else:
            self._stats["dropped"] += len(batch)


_client: Optional[TelemetryClient] = None
_clientLock = threading.RLock()


def getTelemetryClient() -> TelemetryClient:
    """DCL 单例（AGENTS.md §3）。"""
    global _client
    if _client is None:
        with _clientLock:
            if _client is None:
                _client = TelemetryClient()
    return _client


def resetTelemetryClient(force: bool = False) -> None:
    """测试/关停用：清空单例（force 语义与仓内其余 reset 一致）。"""
    global _client
    with _clientLock:
        _client = None
