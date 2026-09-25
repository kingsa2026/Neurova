"""HTTP 请求时长埋点中间件（P1-6）

旧审计 §7 要求的"API 响应时长 p50/p99、吞吐量"基线，此前全仓没有任何
HTTP 时长中间件 —— 唯一接近的是 LoggingMiddleware，它只写日志不导出指标。

本中间件为**纯 ASGI**（与 GlobalAuthMiddleware 同形，不走 BaseHTTPMiddleware）：

- 计时终点是 `http.response.start`（响应头就绪 = TTFB），不是在响应体写完后。
  按"整体写完"计时会把 SSE/流式对话的流存活时间算成服务延迟（chat 流可挂
  数分钟），p99 直接被流长污染、失去诊断意义。
- route label 取 `scope["route"].path`（FastAPI 路由模板，如 `/items/{item_id}`），
  而不是原始 URL path —— 否则 `/items/1`、`/items/2`… 每个都成一条时间线，
  基数爆炸。未匹配到路由（404 / 被外层中间件提前 401）记 `__unmatched__`，
  刻意**不**回落到原始 path。
- 埋点自身失败绝不冒泡：观测代码不得成为请求的失败源。
"""

from __future__ import annotations

import time

from neurova.core.logger import get_logger
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = get_logger(__name__)

UNMATCHED_ROUTE = "__unmatched__"


class HttpMetricsMiddleware:
    """记录每请求的 method / route / status / TTFB。"""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        started = time.perf_counter()
        status_holder = {"status": 0}

        async def _send(message: Message) -> None:
            if message.get("type") == "http.response.start":
                status_holder["status"] = int(message.get("status", 0) or 0)
                self._record(scope, status_holder["status"], started)
            await send(message)

        try:
            await self.app(scope, receive, _send)
        except Exception:
            # 未走到 response.start 就抛错：按 500 计一次（否则异常请求
            # 在指标里彻底消失，错误率被低估）
            if not status_holder["status"]:
                self._record(scope, 500, started)
            raise

    @staticmethod
    def _route_label(scope: Scope) -> str:
        route = scope.get("route")
        path = getattr(route, "path", None)
        return str(path) if path else UNMATCHED_ROUTE

    def _record(self, scope: Scope, status: int, started: float) -> None:
        try:
            from neurova.core.metrics import get_metrics

            get_metrics().record_http_request(
                method=scope.get("method", "?"),
                route=self._route_label(scope),
                status=status,
                duration_s=time.perf_counter() - started,
            )
        except Exception:  # noqa: BLE001 - 埋点不得影响请求链路
            logger.debug("http metrics record failed", exc_info=True)
