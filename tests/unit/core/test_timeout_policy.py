"""资源治理 P1-1：工具超时三层同源 clamp 契约（红→绿）。

契约：所有工具/命令执行超时必须经 neurova.core.timeout_policy 单源钳制——
- 声明层（builtin schema runtime.default_timeout_ms，既有 [1000,800000]ms）
- 解析层（_resolveToolTimeoutSeconds / get_tool_timeout 表值）
- 执行层（_execute_run_code 的用户参 timeout）
任一层越界值一律收进 [1, 800] 秒；非法/缺省回落默认 60s。
"""

import math

from neurova.core.timeout_policy import (
    TOOL_TIMEOUT_DEFAULT_S,
    TOOL_TIMEOUT_MAX_S,
    TOOL_TIMEOUT_MIN_S,
    clampToolTimeoutSeconds,
)


class TestClampToolTimeoutSeconds:
    def test_none_falls_back_to_default(self):
        assert clampToolTimeoutSeconds(None) == 60.0

    def test_missing_value_uses_explicit_default(self):
        assert clampToolTimeoutSeconds(None, default=30.0) == 30.0

    def test_in_range_value_passes_through(self):
        assert clampToolTimeoutSeconds(60) == 60.0
        assert clampToolTimeoutSeconds(1) == 1.0
        assert clampToolTimeoutSeconds(800) == 800.0
        assert clampToolTimeoutSeconds(0.5) == 1.0

    def test_below_minimum_clamped_to_one_second(self):
        assert clampToolTimeoutSeconds(0) == 1.0
        assert clampToolTimeoutSeconds(-5) == 1.0

    def test_above_maximum_clamped_to_800(self):
        assert clampToolTimeoutSeconds(10**9) == 800.0
        assert clampToolTimeoutSeconds(801) == 800.0

    def test_non_numeric_falls_back_to_default(self):
        assert clampToolTimeoutSeconds("abc") == 60.0
        assert clampToolTimeoutSeconds(object()) == 60.0

    def test_nan_falls_back_to_default(self):
        assert clampToolTimeoutSeconds(float("nan")) == 60.0

    def test_bounds_are_the_documented_contract(self):
        assert TOOL_TIMEOUT_MIN_S == 1.0
        assert TOOL_TIMEOUT_MAX_S == 800.0
        assert TOOL_TIMEOUT_DEFAULT_S == 60.0

    def test_bool_is_rejected_as_non_numeric(self):
        # bool 是 int 子类，但 True=1s / False=0s 都不是合法语义，按缺省处理
        assert clampToolTimeoutSeconds(True) == 60.0
        assert clampToolTimeoutSeconds(False) == 60.0

    def test_nan_default_argument_is_sanitized(self):
        # 连 default 都传了 NaN 时不得产出 NaN（后续比较恒 False 的隐患）
        assert clampToolTimeoutSeconds(None, default=float("nan")) == 60.0
        assert math.isnan(clampToolTimeoutSeconds(None, default=float("nan"))) is False
