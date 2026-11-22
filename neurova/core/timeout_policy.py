"""工具/命令执行超时的单一事实源（资源治理 P1-1）。

三层同源契约——任何一层拿到的超时都必须经 `clampToolTimeoutSeconds`
收进 `[TOOL_TIMEOUT_MIN_S, TOOL_TIMEOUT_MAX_S]`：

1. 声明层：builtin schema `runtime.default_timeout_ms`（既有
   `clampRuntimeTimeoutMs` 的 [1000, 800000]ms 与本模块秒级口径同界）；
2. 解析层：`ToolExecutor._resolveToolTimeoutSeconds` / per-tool 超时表
   （`agent/tool_coordinator.TOOL_TIMEOUTS_S`）；
3. 执行层：`ToolExecutor._execute_run_code` 的用户参 `timeout`（此前
   未钳制直通运行时/容器沙箱，是本契约封堵的旁路）。

本模块只依赖标准库——tool_coordinator/tool_executor 是早加载链上的
模块，任何层引用本单源都不引入额外依赖。
"""

from __future__ import annotations

import math

#: 超时下限（秒）：0/负值没有语义，一律收进 1s。
TOOL_TIMEOUT_MIN_S = 1.0
#: 超时上限（秒）：与声明层 clampRuntimeTimeoutMs 的 800_000ms 同界。
TOOL_TIMEOUT_MAX_S = 800.0
#: 缺省超时（秒）：与 tool_coordinator.TOOL_DEFAULT_TIMEOUT_S 同值，
#: 此处为策略层的规范缺省（非法/缺失输入的回落点）。
TOOL_TIMEOUT_DEFAULT_S = 60.0


def clampToolTimeoutSeconds(value, default: float = TOOL_TIMEOUT_DEFAULT_S) -> float:
    """把任意来源的超时值钳进 [1, 800] 秒。

    - None / 非数值 / NaN / 无穷大 → `default`（default 自身非法时回落
      `TOOL_TIMEOUT_DEFAULT_S`，绝不产出 NaN）；
    - bool 按非法处理（True/False 不是时长语义）；
    - <1s 收进 1s；>800s 收进 800s；其余原样（float）。
    """
    fallback = TOOL_TIMEOUT_DEFAULT_S
    try:
        fallback = float(default)
    except (TypeError, ValueError):
        fallback = TOOL_TIMEOUT_DEFAULT_S
    if math.isnan(fallback) or math.isinf(fallback):
        fallback = TOOL_TIMEOUT_DEFAULT_S
    fallback = min(max(fallback, TOOL_TIMEOUT_MIN_S), TOOL_TIMEOUT_MAX_S)

    if isinstance(value, bool):
        return fallback
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return fallback
    if math.isnan(seconds) or math.isinf(seconds):
        return fallback
    return min(max(seconds, TOOL_TIMEOUT_MIN_S), TOOL_TIMEOUT_MAX_S)
