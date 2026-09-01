"""
MCP 连接可靠性状态机（P1-3）

对标实施文档 P1-3：per-server 状态机（CONNECTED/DISCONNECTED/OPEN/HALF_OPEN）
+ 指数退避重连（1→60s + 抖动）+ 熔断（5 次连续失败 OPEN，300s 后惰性升级
HALF_OPEN 探测）+ 工具缓存 TTL（断连窗口降级返回缓存）。

设计约束：
- 纯逻辑、时钟可注入（测试确定性）；惰性状态升级免后台定时器
- 状态机不触达网络——接线方（mcp_client）负责会话操作并把结果回投
- 显式断开（disconnect）语义 = 用户意图，接线方必须删除状态机条目并取消重连
- call_tool 无自动重试是接线方职责（副作用安全）；本模块只裁决"允不允许发起"
"""

from __future__ import annotations

import random
import time
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

from neurova.core.logger import get_logger

logger = get_logger(__name__)

# 熔断阈值：连续失败次数
FAIL_THRESHOLD = 5
# 熔断打开时长：超过后半开探测
OPEN_DURATION_S = 300.0
# 工具缓存 TTL（连接态新鲜度）
TOOLS_CACHE_TTL_S = 300.0
# 重连退避：基值与帽值
RECONNECT_BASE_S = 1.0
RECONNECT_CAP_S = 60.0
# 抖动幅度：delay ∈ [base*(1-j), base*(1+j)]
RECONNECT_JITTER = 0.5


class ServerState(str, Enum):
    """服务器连接状态"""

    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    OPEN = "open"  # 熔断打开
    HALF_OPEN = "half_open"  # 探测窗口


def backoff_delay(attempt: int, jitter: float = RECONNECT_JITTER) -> float:
    """指数退避：1,2,4,...,60（帽值），叠加 ±jitter 比例抖动。"""
    base = min(RECONNECT_BASE_S * (2 ** max(0, attempt)), RECONNECT_CAP_S)
    return max(0.0, base * (1 - jitter + 2 * jitter * random.random()))


class ServerResilience:
    """单服务器可靠性状态机（纯逻辑，clock 注入便于测试）"""

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        fail_threshold: int = FAIL_THRESHOLD,
        open_duration_s: float = OPEN_DURATION_S,
        tools_ttl_s: float = TOOLS_CACHE_TTL_S,
    ):
        self._clock = clock
        self._fail_threshold = fail_threshold
        self._open_duration_s = open_duration_s
        self._tools_ttl_s = tools_ttl_s

        self.state = ServerState.DISCONNECTED
        self.consecutive_failures = 0
        self.last_error: Optional[str] = None
        self.opened_at: Optional[float] = None

        # 工具降级缓存（断连窗口可用）
        self.tools_cache: List[Dict[str, Any]] = []
        self.tools_cached_at: Optional[float] = None

    # ── 状态判定 ──

    @property
    def effective_state(self) -> ServerState:
        """OPEN 超时惰性升级为 HALF_OPEN（免后台定时器）。"""
        if (
            self.state == ServerState.OPEN
            and self.opened_at is not None
            and self._clock() - self.opened_at >= self._open_duration_s
        ):
            self.state = ServerState.HALF_OPEN
            logger.info("MCP 熔断窗口结束，进入半开探测")
        return self.state

    def can_attempt_call(self) -> Tuple[bool, Optional[str]]:
        """是否允许发起工具调用（CONNECTED/HALF_OPEN 放行；OPEN 拒绝）。"""
        state = self.effective_state
        if state in (ServerState.CONNECTED, ServerState.HALF_OPEN):
            return True, None
        if state == ServerState.OPEN:
            remaining = max(
                0.0, self._open_duration_s - (self._clock() - (self.opened_at or 0.0))
            )
            return False, f"熔断打开，{remaining:.0f}s 后进入半开探测"
        return False, "未连接"

    # ── 事件回投 ──

    def on_connect_success(self) -> None:
        self.state = ServerState.CONNECTED
        self.consecutive_failures = 0
        self.last_error = None
        self.opened_at = None

    def on_connect_failure(self, error: str) -> None:
        self.last_error = error
        self.consecutive_failures += 1
        if self.consecutive_failures >= self._fail_threshold:
            self._trip_open()

    def on_call_success(self) -> None:
        self.consecutive_failures = 0
        self.last_error = None
        if self.state in (ServerState.HALF_OPEN, ServerState.DISCONNECTED, ServerState.OPEN):
            # 探测成功或意外恢复 → 复位
            if self.state != ServerState.CONNECTED:
                logger.info("MCP 连接恢复（state=%s）", self.state.value)
            self.state = ServerState.CONNECTED
        self.opened_at = None

    def on_call_failure(self, error: str) -> None:
        self.last_error = error
        self.consecutive_failures += 1
        if self.consecutive_failures >= self._fail_threshold:
            self._trip_open()

    def mark_disconnected(self, error: str) -> None:
        """会话死亡/连接丢失（区别于计数累积：立即断连，是否熔断交由后续失败累积）"""
        self.last_error = error
        if self.state in (ServerState.CONNECTED, ServerState.HALF_OPEN):
            self.state = ServerState.DISCONNECTED

    def _trip_open(self) -> None:
        self.state = ServerState.OPEN
        self.opened_at = self._clock()
        logger.warning("MCP 连续失败 %d 次，熔断打开 %.0fs", self.consecutive_failures, self._open_duration_s)

    # ── 工具缓存 ──

    def set_tools_cache(self, tools: List[Dict[str, Any]], now: Optional[float] = None) -> None:
        self.tools_cache = list(tools or [])
        self.tools_cached_at = now if now is not None else self._clock()

    def get_stale_tools(self) -> List[Dict[str, Any]]:
        """断连窗口降级：返回最后已知工具清单（可能过期）。"""
        return list(self.tools_cache)

    def tools_cache_fresh(self) -> bool:
        """连接态缓存新鲜度（TTL 内无需重拉）。"""
        return (
            bool(self.tools_cache)
            and self.tools_cached_at is not None
            and self._clock() - self.tools_cached_at < self._tools_ttl_s
        )
