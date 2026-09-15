# -*- coding: utf-8 -*-
"""P0-3 会话式 shell（exec_command + write_stdin）。

- exec_command 启动常驻进程，yield_time_ms 内未结束返回 session_id+running
- write_stdin 向同一会话写输入并轮询新输出；进程结束返回 exit_code
- 输出按 token 预算 head+tail 截断，带 original_chars/truncated 元数据
- 进程数上限 64；僵尸会话按 TTL 回收；kill_all 兜底清理
"""
import subprocess
import sys

import pytest


@pytest.fixture()
def manager():
    from neurova.execution_engine.shell_sessions import ShellSessionManager

    return ShellSessionManager()


def _py(code: str) -> str:
    # list2cmdline 产出 cmd.exe/POSIX 双兼容的双引号包裹（单引号在 cmd.exe 会被当字面量）
    return subprocess.list2cmdline([sys.executable, "-c", code])


class TestShellSessions:
    @pytest.mark.asyncio
    async def test_quick_command_completes_with_output(self, manager):
        out = await manager.start_session(_py("print('hello-session')"), yield_time_ms=8000)
        assert out["status"] == "completed"
        assert out["exit_code"] == 0
        assert "hello-session" in out["output"]

    @pytest.mark.asyncio
    async def test_long_running_returns_session_then_stdin(self, manager):
        # 单行 -c 代码：cmd.exe 下多行参数会被换行截断（实测），一律单行
        code = "import sys,time;print('ready',flush=True);line=sys.stdin.readline();print('got:'+line.strip(),flush=True)"
        first = await manager.start_session(_py(code), yield_time_ms=600)
        assert first["status"] == "running"
        assert first["session_id"] > 0
        assert "ready" in first["output"]

        second = await manager.poll_session(
            first["session_id"], chars="hi\n", yield_time_ms=8000
        )
        assert second["status"] == "completed"
        assert "got:hi" in second["output"]

    @pytest.mark.asyncio
    async def test_poll_unknown_session(self, manager):
        out = await manager.poll_session(99999, yield_time_ms=100)
        assert out["status"] == "not_found"

    @pytest.mark.asyncio
    async def test_output_token_cap_head_tail(self, manager):
        code = "print('H' * 20 + 'X' * 80000 + 'T' * 20)"
        out = await manager.start_session(_py(code), yield_time_ms=15000, max_output_tokens=100)
        assert out["truncated"] is True
        assert out["original_chars"] > 80000
        assert "H" * 20 in out["output"]      # 头部保留
        assert "T" * 20 in out["output"]      # 尾部保留
        assert "X" * 1000 not in out["output"]  # 中段丢弃
        assert "截断" in out["output"]

    @pytest.mark.asyncio
    async def test_session_limit(self, manager, monkeypatch):
        monkeypatch.setattr(manager, "max_sessions", 2)
        a = await manager.start_session(_py("import time; time.sleep(3)"), yield_time_ms=200)
        b = await manager.start_session(_py("import time; time.sleep(3)"), yield_time_ms=200)
        assert a["status"] == "running" and b["status"] == "running"
        c = await manager.start_session(_py("print('no room')"), yield_time_ms=200)
        assert c["status"] == "rejected"
        await manager.kill_all()

    @pytest.mark.asyncio
    async def test_reap_expired_finished_sessions(self, manager, monkeypatch):
        done = await manager.start_session(_py("print('done')"), yield_time_ms=8000)
        assert done["status"] == "completed"
        # 把 TTL 调成 0 → 下一次 start 回收该已完成会话
        monkeypatch.setattr(manager, "finished_ttl_seconds", 0)
        total_before = len(manager.list_sessions())
        await manager.start_session(_py("print('again')"), yield_time_ms=8000)
        ids = {s["session_id"] for s in manager.list_sessions()}
        assert done["session_id"] not in ids or total_before == 0

    @pytest.mark.asyncio
    async def test_kill_all_cleans_up(self, manager):
        await manager.start_session(_py("import time; time.sleep(30)"), yield_time_ms=200)
        await manager.kill_all()
        assert manager.list_sessions() == []

    @pytest.mark.asyncio
    async def test_workdir_anchored(self, manager, tmp_path):
        (tmp_path / "marker.txt").write_text("ANCHORED", encoding="utf-8")
        out = await manager.start_session(
            _py("print(open('marker.txt', encoding='utf-8').read())"),
            workdir=str(tmp_path),
            yield_time_ms=8000,
        )
        assert "ANCHORED" in out["output"]


class TestSchemaAndDispatchWiring:
    def test_schemas_registered(self):
        from neurova.builtin_tools import _BUILTIN_SCHEMAS

        for name in ("exec_command", "write_stdin"):
            assert name in _BUILTIN_SCHEMAS, f"{name} 缺 schema"
        assert "command" in _BUILTIN_SCHEMAS["exec_command"]["parameters"]["required"]
        assert "session_id" in _BUILTIN_SCHEMAS["write_stdin"]["parameters"]["required"]

    def test_dispatch_registered(self):
        from neurova.tool_executor import ToolExecutor

        assert ToolExecutor._builtin_dispatch.get("exec_command") == "_execute_exec_command"
        assert ToolExecutor._builtin_dispatch.get("write_stdin") == "_execute_write_stdin"

    def test_exec_command_declares_sandbox(self):
        from neurova.builtin_tools import get_builtin_tool_sandbox_declaration

        assert get_builtin_tool_sandbox_declaration("exec_command") is True

    def test_write_stdin_not_concurrency_safe(self):
        """write_stdin 触碰共享会话状态，禁止声明并行安全。"""
        from neurova.agent.tool_coordinator import is_concurrency_safe

        assert is_concurrency_safe("write_stdin") is False
        assert is_concurrency_safe("exec_command") is False

    @pytest.mark.asyncio
    async def test_end_to_end_via_tool_executor(self):
        """经 ToolExecutor 真链路：exec_command → write_stdin。"""
        from unittest.mock import MagicMock

        from neurova.tool_executor import ToolExecutor

        agent = MagicMock()
        agent.config.workspace_path = ""
        executor = ToolExecutor(agent)
        code = "import sys;print('ready',flush=True);sys.stdin.readline();print('pong',flush=True)"
        first = await executor._execute_exec_command(
            {"command": _py(code), "yield_time_ms": 600}
        )
        assert first.get("status") == "running", first
        second = await executor._execute_write_stdin(
            {"session_id": first["session_id"], "chars": "ping\n", "yield_time_ms": 8000}
        )
        assert "pong" in second.get("output", ""), second


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestSandboxEnforcePassThrough:
    @pytest.mark.asyncio
    async def test_session_shell_not_hijacked_by_sandbox_verdict(self, monkeypatch):
        """断点③核验：enforce 场景下 SANDBOX 裁决不再劫持会话 shell——
        exec_command/write_stdin 直通自有执行器（审计已在上游落账）。"""
        from unittest.mock import MagicMock

        from neurova.security.governance import GovernanceDecision
        from neurova import tool_executor as te

        class _FakeVerdict:
            decision = GovernanceDecision.SANDBOX
            severity = None
            reasons = ["policy"]

            def to_dict(self):
                return {"decision": "sandbox"}

        class _FakeGov:
            def evaluate_tool_call(self, *a, **k):
                return _FakeVerdict()

        monkeypatch.setattr(
            "neurova.security.governance.get_governance", lambda: _FakeGov()
        )
        agent = MagicMock()
        agent.config.user_id = "u1"
        agent.config.agent_id = "a1"
        executor = te.ToolExecutor(agent)
        for name, params in (
            ("exec_command", {"command": "echo hi"}),
            ("write_stdin", {"session_id": 1, "chars": "x"}),
        ):
            result = await executor._governance_precheck(name, params)
            assert result is None, f"{name} 被沙箱裁决劫持"
