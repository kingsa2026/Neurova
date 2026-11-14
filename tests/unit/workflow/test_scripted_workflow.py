# -*- coding: utf-8 -*-
"""P3-14：受限脚本化工作流——静态校验/受限执行/journal 续跑/执行器接线。
"""

import asyncio
import json
from unittest.mock import MagicMock

import pytest

from neurova.workflow.scripted import (
    WorkflowJournal,
    runScriptedWorkflow,
    validateScript,
)

VALID = """
async def main(ctx):
    ctx.log("开始")
    r1 = await ctx.callTool("file_read", {"file_path": "/tmp/a.txt"})
    ctx.setVar("结果", r1)
    await ctx.sleep(0)
"""


class TestValidator:
    def test_valid_script_passes(self):
        assert validateScript(VALID) == []

    def test_import_rejected(self):
        v = validateScript("import os\nasync def main(ctx):\n    ctx.log('x')")
        assert any("import" in v for v in v)

    def test_from_import_rejected(self):
        v = validateScript("from os import path\nasync def main(ctx):\n    pass")
        assert any("import" in v for v in v)

    def test_eval_rejected(self):
        v = validateScript("async def main(ctx):\n    eval('1+1')")
        assert any("eval" in v for v in v)

    def test_open_rejected(self):
        v = validateScript("async def main(ctx):\n    open('/etc/passwd')")
        assert any("open" in v for v in v)

    def test_dunder_rejected(self):
        v = validateScript("async def main(ctx):\n    ctx.__class__")
        assert any("dunder" in v for v in v)

    def test_missing_main_rejected(self):
        assert validateScript("x = 1") != []

    def test_sync_main_rejected(self):
        v = validateScript("def main(ctx):\n    pass")
        assert any("async def main" in v for v in v)

    def test_global_rejected(self):
        v = validateScript("async def main(ctx):\n    global x")
        assert any("global" in v for v in v)


class TestEngine:
    def test_happy_path_journals_calls(self, tmp_path):
        journal = WorkflowJournal("happy")
        calls = []

        async def callTool(name, params):
            calls.append((name, params))
            return {"success": True, "content": f"{name}-结果"}

        script = (
            "async def main(ctx):\n"
            "    ctx.log('开始')\n"
            "    a = await ctx.callTool('file_read', {'p': 1})\n"
            "    b = await ctx.callTool('web_search', {'q': 2})\n"
            "    ctx.setVar('两个', [a, b])\n"
        )
        result = asyncio.run(runScriptedWorkflow(script, callTool, journal))
        assert result["success"] is True
        assert result["vars"]["两个"][0]["content"] == "file_read-结果"
        assert result["logs"] == ["开始"]
        assert len(calls) == 2
        kinds = [r["kind"] for r in journal.readRows()]
        assert kinds.count("callTool") == 2

    def test_resume_reuses_journaled_results(self, tmp_path):
        journal = WorkflowJournal("resume-me")
        liveCalls = []

        async def callTool(name, params):
            liveCalls.append((name, params))
            return {"success": True, "n": len(liveCalls)}

        script = (
            "async def main(ctx):\n"
            "    a = await ctx.callTool('t1', {})\n"
            "    b = await ctx.callTool('t2', {})\n"
            "    c = await ctx.callTool('t3', {})\n"
            "    ctx.setVar('count', c['n'])\n"
        )
        asyncio.run(runScriptedWorkflow(script, callTool, journal))
        assert len(liveCalls) == 3

        # 续跑：journal 里已有 3 次调用——复用结果，不重复执行副作用
        result = asyncio.run(
            runScriptedWorkflow(script, callTool, journal, resumeRows=journal.readRows())
        )
        assert result["success"] is True
        assert result["replayed_calls"] == 3
        assert len(liveCalls) == 3, "续跑不得重复执行已留痕的调用"
        assert result["vars"]["count"] == 3

    def test_timeout_is_honest(self, tmp_path):
        journal = WorkflowJournal("timeout")
        script = (
            "async def main(ctx):\n"
            "    await ctx.sleep(30)\n"
        )
        result = asyncio.run(
            runScriptedWorkflow(script, lambda n, p: None, journal, timeout=5)
        )
        assert result["success"] is False
        assert "超时" in result["error"]

    def test_script_exception_is_honest(self, tmp_path):
        journal = WorkflowJournal("boom")
        script = (
            "async def main(ctx):\n"
            "    ctx.log('before')\n"
            "    raise RuntimeError('炸了')\n"
        )
        result = asyncio.run(runScriptedWorkflow(script, lambda n, p: None, journal))
        assert result["success"] is False
        assert "炸了" in result["error"]
        assert result["logs"] == ["before"]

    def test_invalid_script_rejected_before_exec(self, tmp_path):
        result = asyncio.run(
            runScriptedWorkflow("import os", lambda n, p: None, WorkflowJournal("bad"))
        )
        assert result["success"] is False
        assert result["errors"]


class TestExecutorWiring:
    def _executor(self, monkeypatch, tmp_path):
        from neurova.tool_executor import ToolExecutor
        from neurova.security.approval_manager import ApprovalManager
        from neurova.security.governance import GovernancePolicy
        from neurova.security import governance as gov_mod

        approvals = ApprovalManager(tmp_path)
        monkeypatch.setattr("neurova.tool_executor._get_approval_manager", lambda: approvals)
        monkeypatch.setattr(
            "neurova.security.governance.get_governance",
            lambda: GovernancePolicy(ask_on_high=True),
        )
        agent = MagicMock()
        agent.user_id = "u1"
        agent.agent_id = "a1"
        executor = ToolExecutor(agent)
        executor.on_tool_executed = MagicMock()
        return executor, approvals

    def test_registered_in_builtin_schemas(self):
        from neurova.builtin_tools import get_builtin_tool_params

        assert get_builtin_tool_params("run_scripted_workflow") is not None

    def test_script_calls_tool_through_governance(self, monkeypatch, tmp_path):
        executor, _approvals = self._executor(monkeypatch, tmp_path)
        note = tmp_path / "note.txt"
        note.write_text("脚本读到我了", encoding="utf-8")
        script = (
            "async def main(ctx):\n"
            f"    r = await ctx.callTool('file_read', {{'file_path': {str(note)!r}}})\n"
            "    ctx.log('读到了')\n"
        )

        result = asyncio.run(executor._execute_scripted_workflow({"script": script}))

        assert result["success"] is True
        assert result["logs"] == ["读到了"]
        assert result["run_id"].startswith("scripted_")

    def test_invalid_script_rejected(self, monkeypatch, tmp_path):
        executor, _approvals = self._executor(monkeypatch, tmp_path)
        result = asyncio.run(
            executor._execute_scripted_workflow({"script": "import os"})
        )
        assert result["success"] is False
        assert result["errors"]
