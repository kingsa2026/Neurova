"""C-19/C-20 回归测试：tool_engine 死代码删除。

C-19: `cached` 装饰器（裸 dict 无上限）在 neurova 内零使用点 → 按死代码
教义删除（连带其唯一消费的 cache_token）。
C-20: `_validate_parameters` 零调用点；且 _extract_parameters 对自动提取
参数统一标 type="string"，接入 execute 会把数值/布尔参数误判为类型错误
（行为破坏），required 校验已由 prepare_arguments 覆盖 → 删除死代码。
"""

import asyncio

import neurova.execution_engine.tool_engine as tool_engine_module
from neurova.execution_engine.tool_engine import ToolEngine


def test_cached_decorator_removed():
    assert not hasattr(tool_engine_module, "cached")


def test_cache_token_removed():
    assert not hasattr(tool_engine_module, "cache_token")


def test_validate_parameters_removed():
    assert not hasattr(ToolEngine, "_validate_parameters")


def test_execute_still_works_after_removal():
    engine = ToolEngine()
    engine.register_tool("add", lambda a, b: a + b)
    result = asyncio.run(engine.execute("add", {"a": 1, "b": 2}))
    assert result == 3


def test_execute_missing_required_param_still_rejected():
    # required 语义由 prepare_arguments 覆盖（C-20 删除后不得回退）
    engine = ToolEngine()

    def needs_arg(x):
        return x

    engine.register_tool("needs_arg", needs_arg)
    try:
        asyncio.run(engine.execute("needs_arg", {}))
    except ValueError as e:
        assert "缺少必需参数" in str(e)
    else:
        raise AssertionError("缺少必需参数应被拒绝")
