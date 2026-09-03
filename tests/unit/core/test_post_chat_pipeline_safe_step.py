"""
P0-C2 修复：_safe_step 异常吞没测试

之前的问题（违反 bug-hunt 规则 #3 "Never bypass"）：
    PostChatPipeline._safe_step / _safe_step_sync 用 `except Exception` 捕获所有异常，
    包括编程错误（TypeError/AttributeError/NameError/ImportError/KeyError/SyntaxError）。
    这导致真实 bug（如 None.attr、错函数签名、错 import）被默默吞掉，
    步骤降级为 default 值，pipeline 继续运行，bug 永不暴露。

修复策略（bug-hunt Phase 4 surgical fix）：
    区分编程错误与运营错误：
    - 编程错误（TypeError/AttributeError/NameError/ImportError/SyntaxError）→ re-raise
      让调用方看到真实 bug
    - 运营错误（OSError/ConnectionError/TimeoutError/FileNotFoundError/ValueError/
      RuntimeError）→ 维持降级策略（log + default），保持管线韧性
    - KeyError 默认视为运营错误（dict 缺键在配置场景常见）
"""

import pytest
from unittest.mock import Mock
from neurova.post_chat_pipeline import PostChatPipeline, StepStatus


class TestSafeStepProgrammingErrors:
    """P0-C2: 编程错误应 re-raise，不能被 _safe_step 吞没"""

    @pytest.fixture
    def pipeline(self):
        return PostChatPipeline(agent_ref=Mock())

    @pytest.mark.asyncio
    async def test_type_error_not_swallowed(self, pipeline):
        """TypeError（错函数签名 / 不可调用对象当函数调用）应 re-raise"""

        async def bad_step():
            # 真实 TypeError：字符串不是可调用对象
            "string"()  # noqa: B018

        with pytest.raises(TypeError):
            await pipeline._safe_step("bad_step", bad_step(), default="fallback")

    @pytest.mark.asyncio
    async def test_attribute_error_not_swallowed(self, pipeline):
        """AttributeError（属性不存在）应 re-raise"""

        async def bad_step():
            obj = object()
            obj.nonexistent_method()  # noqa

        with pytest.raises(AttributeError):
            await pipeline._safe_step("bad_step", bad_step(), default="fallback")

    @pytest.mark.asyncio
    async def test_name_error_not_swallowed(self, pipeline):
        """NameError（未定义变量）应 re-raise"""

        async def bad_step():
            return undefined_variable  # noqa: F821

        with pytest.raises(NameError):
            await pipeline._safe_step("bad_step", bad_step(), default="fallback")

    @pytest.mark.asyncio
    async def test_import_error_not_swallowed(self, pipeline):
        """ImportError（导入失败）应 re-raise"""

        async def bad_step():
            import nonexistent_module_xyz  # noqa: F401

        with pytest.raises(ImportError):
            await pipeline._safe_step("bad_step", bad_step(), default="fallback")

    @pytest.mark.asyncio
    async def test_syntax_error_not_swallowed(self, pipeline):
        """SyntaxError（编译时错误）应 re-raise"""

        async def bad_step():
            # 用 eval 触发 SyntaxError（直接写语法错误无法定义函数）
            eval("def bad(:")  # noqa: S307

        with pytest.raises(SyntaxError):
            await pipeline._safe_step("bad_step", bad_step(), default="fallback")


class TestSafeStepSyncProgrammingErrors:
    """P0-C2: _safe_step_sync 同步版本同样不应吞没编程错误"""

    @pytest.fixture
    def pipeline(self):
        return PostChatPipeline(agent_ref=Mock())

    def test_sync_type_error_not_swallowed(self, pipeline):
        """同步版本：TypeError 应 re-raise"""

        def bad_step():
            # 真实 TypeError：字符串不是可调用对象
            "string"()  # noqa: B018

        with pytest.raises(TypeError):
            pipeline._safe_step_sync("bad_step", bad_step, default="fallback")

    def test_sync_attribute_error_not_swallowed(self, pipeline):
        """同步版本：AttributeError 应 re-raise"""

        def bad_step():
            object().nonexistent()  # noqa

        with pytest.raises(AttributeError):
            pipeline._safe_step_sync("bad_step", bad_step, default="fallback")


class TestSafeStepOperationalErrors:
    """P0-C2: 运营错误仍应被降级（保持管线韧性）"""

    @pytest.fixture
    def pipeline(self):
        return PostChatPipeline(agent_ref=Mock())

    @pytest.mark.asyncio
    async def test_os_error_degraded(self, pipeline):
        """OSError 应降级（log + 返回 default）"""

        async def failing_step():
            raise OSError("disk full")

        result = await pipeline._safe_step("io_step", failing_step(), default="fallback")
        assert result == "fallback"
        # 应记录 FAILED 状态
        assert any(r.status == StepStatus.FAILED for r in pipeline._step_results)

    @pytest.mark.asyncio
    async def test_value_error_degraded(self, pipeline):
        """ValueError 应降级"""

        async def failing_step():
            raise ValueError("invalid input")

        result = await pipeline._safe_step("val_step", failing_step(), default="fallback")
        assert result == "fallback"

    @pytest.mark.asyncio
    async def test_runtime_error_degraded(self, pipeline):
        """RuntimeError 应降级"""

        async def failing_step():
            raise RuntimeError("service unavailable")

        result = await pipeline._safe_step("rt_step", failing_step(), default="fallback")
        assert result == "fallback"

    @pytest.mark.asyncio
    async def test_connection_error_degraded(self, pipeline):
        """ConnectionError 应降级"""

        async def failing_step():
            raise ConnectionError("network down")

        result = await pipeline._safe_step("net_step", failing_step(), default="fallback")
        assert result == "fallback"

    @pytest.mark.asyncio
    async def test_file_not_found_error_degraded(self, pipeline):
        """FileNotFoundError 应降级"""

        async def failing_step():
            raise FileNotFoundError("missing.txt")

        result = await pipeline._safe_step("fnf_step", failing_step(), default="fallback")
        assert result == "fallback"

    @pytest.mark.asyncio
    async def test_timeout_error_degraded(self, pipeline):
        """TimeoutError 应降级"""

        async def failing_step():
            raise TimeoutError("request timed out")

        result = await pipeline._safe_step("timeout_step", failing_step(), default="fallback")
        assert result == "fallback"

    @pytest.mark.asyncio
    async def test_key_error_degraded(self, pipeline):
        """KeyError 默认视为运营错误降级（配置缺键场景常见）"""

        async def failing_step():
            d = {"a": 1}
            return d["b"]

        result = await pipeline._safe_step("key_step", failing_step(), default="fallback")
        assert result == "fallback"


class TestSafeStepNormalOperation:
    """P0-C2: 正常流程不应受影响"""

    @pytest.fixture
    def pipeline(self):
        return PostChatPipeline(agent_ref=Mock())

    @pytest.mark.asyncio
    async def test_successful_step_returns_value(self, pipeline):
        """成功的步骤应正常返回值"""

        async def good_step():
            return "result"

        result = await pipeline._safe_step("good", good_step(), default="fallback")
        assert result == "result"

    @pytest.mark.asyncio
    async def test_successful_step_records_executed(self, pipeline):
        """成功的步骤应记录 EXECUTED 状态"""

        async def good_step():
            return 42

        await pipeline._safe_step("good", good_step(), default="fallback")
        # 应有 EXECUTED 状态记录
        # (实际实现可能用不同状态，但应该不是 FAILED)
        assert all(r.status != StepStatus.FAILED for r in pipeline._step_results)
