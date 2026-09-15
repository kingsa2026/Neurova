# -*- coding: utf-8 -*-
"""P1-7 update_plan 工具。

- schema: {explanation?, plan: [{step, status: pending|in_progress|completed}]}
- 状态机约束：plan 非空、status 词表、**至多一个 in_progress**（违规报错让模型自纠）
- SSE：tool_result 携带 plan 时提取独立 plan_update 事件（前端时间轴渲染）
"""
import pytest

from neurova.api.endpoints.console import _extract_plan_update


class TestSchemaWiring:
    def test_schema_and_dispatch_registered(self):
        from neurova.builtin_tools import _BUILTIN_SCHEMAS
        from neurova.tool_executor import ToolExecutor

        assert "update_plan" in _BUILTIN_SCHEMAS
        assert "plan" in _BUILTIN_SCHEMAS["update_plan"]["parameters"]["required"]
        assert ToolExecutor._builtin_dispatch.get("update_plan") == "_execute_update_plan"


class TestUpdatePlanExecution:
    @pytest.mark.asyncio
    async def test_valid_plan(self):
        from unittest.mock import MagicMock

        from neurova.tool_executor import ToolExecutor

        executor = ToolExecutor(MagicMock())
        result = await executor._execute_update_plan(
            {
                "explanation": "开始调研",
                "plan": [
                    {"step": "读代码", "status": "completed"},
                    {"step": "写测试", "status": "in_progress"},
                    {"step": "实现", "status": "pending"},
                ],
            }
        )
        assert result["success"] is True
        assert len(result["plan"]) == 3
        assert result["plan"][1]["status"] == "in_progress"

    @pytest.mark.asyncio
    async def test_multiple_in_progress_rejected(self):
        from unittest.mock import MagicMock

        from neurova.tool_executor import ToolExecutor

        executor = ToolExecutor(MagicMock())
        result = await executor._execute_update_plan(
            {
                "plan": [
                    {"step": "a", "status": "in_progress"},
                    {"step": "b", "status": "in_progress"},
                ]
            }
        )
        assert result["success"] is False
        assert "in_progress" in result["error"]

    @pytest.mark.asyncio
    async def test_bad_status_rejected(self):
        from unittest.mock import MagicMock

        from neurova.tool_executor import ToolExecutor

        executor = ToolExecutor(MagicMock())
        result = await executor._execute_update_plan(
            {"plan": [{"step": "a", "status": "done"}]}
        )
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_empty_plan_rejected(self):
        from unittest.mock import MagicMock

        from neurova.tool_executor import ToolExecutor

        executor = ToolExecutor(MagicMock())
        result = await executor._execute_update_plan({"plan": []})
        assert result["success"] is False
        result2 = await executor._execute_update_plan({})
        assert result2["success"] is False


class TestPlanEventExtraction:
    def test_plan_result_extracts_event(self):
        import json

        content = json.dumps(
            {
                "success": True,
                "plan": [{"step": "a", "status": "pending"}],
            },
            ensure_ascii=False,
        )
        event = _extract_plan_update(content)
        assert event is not None
        assert event["type"] == "plan_update"
        assert event["plan"] == [{"step": "a", "status": "pending"}]

    def test_non_plan_content_returns_none(self):
        # 惯例与 _extract_approval_payload 一致：不产生事件 = 空 dict（falsy）
        assert not _extract_plan_update('{"success": true, "data": "x"}')
        assert not _extract_plan_update("plain text")
        assert not _extract_plan_update("")

    def test_failed_plan_not_emitted(self):
        import json

        content = json.dumps({"success": False, "error": "x", "plan": []})
        assert not _extract_plan_update(content)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
