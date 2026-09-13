"""SSH 远程命令执行（computer_ssh_exec）

验收：
- ssh_runner：client_factory 注入，key/password 认证参数正确，返回 rc/stdout/stderr
- 缺 host/command → 结构化错误
- 运行档：computer_ssh_exec=high 风险；review→审批，full/sandbox/auto→放行（远程已隔离）
- 执行方法：解析凭据→跑 SSH→返回紧凑结果 + 推 terminal 事件
"""

import pytest

from neurova.computer_use.runtime_policy import classify_risk, decide_desktop
from neurova.computer_use.ssh_runner import run_ssh_command


class FakeChannel:
    def recv_exit_status(self):
        return 0


class FakeStd:
    def __init__(self, data=b""):
        self._d = data
        self.channel = FakeChannel()

    def read(self):
        return self._d


class FakeSSHClient:
    def __init__(self):
        self.connect_kwargs = None
        self.closed = False

    def set_missing_host_key_policy(self, p):
        pass

    def connect(self, **kw):
        self.connect_kwargs = kw

    def exec_command(self, cmd, timeout=None):
        return (None, FakeStd(b"out-data"), FakeStd(b"err-data"))

    def close(self):
        self.closed = True


class TestSSHRunner:
    def test_key_auth_kwargs(self):
        c = FakeSSHClient()
        out = run_ssh_command("h1", "ls", user="root", key_path="/k", client_factory=lambda: c)
        assert out["returncode"] == 0
        assert out["stdout"] == "out-data"
        assert out["stderr"] == "err-data"
        assert c.connect_kwargs["username"] == "root"
        assert c.connect_kwargs["key_filename"] == "/k"
        assert "password" not in c.connect_kwargs
        assert c.closed is True

    def test_password_auth_kwargs(self):
        c = FakeSSHClient()
        run_ssh_command("h1", "ls", user="u", password="pw", client_factory=lambda: c)
        assert c.connect_kwargs["password"] == "pw"
        assert "key_filename" not in c.connect_kwargs

    def test_missing_host(self):
        out = run_ssh_command("", "ls")
        assert out["returncode"] == -1 and "host" in out["stderr"]

    def test_connect_failure_structured(self):
        class Boom:
            def set_missing_host_key_policy(self, p): pass
            def connect(self, **kw): raise RuntimeError("refused")
            def close(self): pass

        out = run_ssh_command("h", "ls", client_factory=lambda: Boom())
        assert out["returncode"] == -1 and "refused" in out["stderr"]


class TestRuntimePolicyForSSH:
    def test_classified_high(self):
        assert classify_risk("computer_ssh_exec") == "high"

    def test_review_requires_approval(self):
        assert decide_desktop("review", "computer_ssh_exec")["action"] == "require_approval"

    def test_full_sandbox_auto_proceed(self):
        # 远程命令已在远端执行，"进沙箱"无意义 → 非 review 档一律放行
        for mode in ("full", "sandbox", "auto"):
            assert decide_desktop(mode, "computer_ssh_exec")["action"] == "proceed", mode


class TestSSHExecMethod:
    @pytest.mark.asyncio
    async def test_returns_compact_and_emits_terminal(self, monkeypatch):
        from neurova.tool_executor import ToolExecutor

        inst = ToolExecutor.__new__(ToolExecutor)
        inst._agent = type("A", (), {"current_session_id": "s1", "_current_user_id": "u1"})()

        monkeypatch.setattr(
            "neurova.computer_use.ssh_runner.run_ssh_command",
            lambda *a, **k: {"returncode": 0, "stdout": "hello", "stderr": ""},
        )
        monkeypatch.setattr(
            "neurova.computer_use.ssh_runner.resolve_ssh_credentials",
            lambda u, h: {"user": "root", "port": 22, "key_path": "/k", "password": None},
        )
        emitted = {}

        async def fake_emit(self, tool, params, result, screenshot_base64=None, terminal=None):
            emitted["tool"] = tool
            emitted["terminal"] = terminal

        monkeypatch.setattr(ToolExecutor, "_emit_computer_event", fake_emit)
        out = await inst._execute_computer_ssh_exec({"host": "h1", "command": "echo hi"})
        assert out["success"] is True and out["stdout"] == "hello"
        assert emitted["tool"] == "computer_ssh_exec"
        assert emitted["terminal"]["command"] == "echo hi"
        assert emitted["terminal"]["stdout"] == "hello"

    @pytest.mark.asyncio
    async def test_missing_host(self, monkeypatch):
        from neurova.tool_executor import ToolExecutor

        inst = ToolExecutor.__new__(ToolExecutor)
        inst._agent = type("A", (), {"current_session_id": None})()
        out = await inst._execute_computer_ssh_exec({"command": "ls"})
        assert "host" in out["error"]

    @pytest.mark.asyncio
    async def test_no_credential_waits_then_times_out(self, monkeypatch):
        """无凭据 → 弹卡 + 轮询等待；等待超时才以 needs_credential 终止，且绝不发起连接。"""
        from neurova.tool_executor import ToolExecutor

        inst = ToolExecutor.__new__(ToolExecutor)
        inst._agent = type("A", (), {"current_session_id": None, "_current_user_id": "u1"})()

        monkeypatch.setattr("neurova.computer_use.ssh_runner.resolve_ssh_credentials", lambda u, h: {})
        # 模拟等待超时（不真睡 90s）
        async def fake_await(self, user_id, host, **k):
            return {}

        monkeypatch.setattr(ToolExecutor, "_await_ssh_credential", fake_await)
        ran = {}

        def boom(*a, **k):
            ran["called"] = True
            return {}

        monkeypatch.setattr("neurova.computer_use.ssh_runner.run_ssh_command", boom)

        async def fake_emit(self, *a, **k):
            return None

        monkeypatch.setattr(ToolExecutor, "_emit_computer_event", fake_emit)
        out = await inst._execute_computer_ssh_exec({"host": "9.9.9.9", "command": "ls"})
        assert out["needs_credential"] is True and out["success"] is False
        assert not ran.get("called"), "等待超时不得发起连接"

    @pytest.mark.asyncio
    async def test_credential_appears_during_wait_replays_in_turn(self, monkeypatch):
        """当场续跑：卡弹出后用户填了凭据 → 轮询命中 → 同一轮内执行命令返回真实结果。"""
        from neurova.tool_executor import ToolExecutor

        inst = ToolExecutor.__new__(ToolExecutor)
        inst._agent = type("A", (), {"current_session_id": None, "_current_user_id": "u1"})()

        # 首次无凭据（触发卡），等待后返回填好的凭据
        monkeypatch.setattr("neurova.computer_use.ssh_runner.resolve_ssh_credentials", lambda u, h: {})

        async def fake_await(self, user_id, host, **k):
            return {"user": "root", "port": 22, "key_text": "K", "password": None}

        monkeypatch.setattr(ToolExecutor, "_await_ssh_credential", fake_await)
        ran = {}

        def fake_run(host, command, **kw):
            ran["kw"] = kw
            return {"returncode": 0, "stdout": "ran-after-cred", "stderr": ""}

        monkeypatch.setattr("neurova.computer_use.ssh_runner.run_ssh_command", fake_run)

        async def fake_emit(self, *a, **k):
            return None

        monkeypatch.setattr(ToolExecutor, "_emit_computer_event", fake_emit)
        out = await inst._execute_computer_ssh_exec({"host": "h1", "command": "uptime"})
        assert out["success"] is True and out["stdout"] == "ran-after-cred"
        assert "needs_credential" not in out
        assert ran["kw"]["user"] == "root" and ran["kw"]["key_text"] == "K"

    @pytest.mark.asyncio
    async def test_await_ssh_credential_polls_until_present(self, monkeypatch):
        """_await_ssh_credential 本身：轮询到凭据出现即返回；超时返回 {}。interval=0 使 sleep(0) 瞬时。"""
        from neurova.tool_executor import ToolExecutor

        inst = ToolExecutor.__new__(ToolExecutor)

        seq = [{}, {}, {"user": "root"}]
        it = iter(seq)
        monkeypatch.setattr("neurova.computer_use.ssh_runner.resolve_ssh_credentials", lambda u, h: next(it))
        got = await inst._await_ssh_credential("u1", "h", timeout=10, interval=0)
        assert got == {"user": "root"}

        # 超时路径：timeout=0 → 循环立即不进入 → {}（不 patch monotonic，避免干扰 asyncio 内部计时）
        monkeypatch.setattr("neurova.computer_use.ssh_runner.resolve_ssh_credentials", lambda u, h: {})
        assert await inst._await_ssh_credential("u1", "h", timeout=0, interval=0) == {}


    @pytest.mark.asyncio
    async def test_needs_credential_reaches_ws_payload(self, monkeypatch):
        """按需卡真实触发通道是 WS computer_action（主聊天 SSE 不发 tool_result）：
        _emit_computer_event 必须把 needs_credential + host 放进事件 payload。"""
        from neurova.tool_executor import ToolExecutor

        inst = ToolExecutor.__new__(ToolExecutor)
        inst._agent = type("A", (), {"current_session_id": "s1", "_current_user_id": "u1"})()

        captured = {}

        class FakeMgr:
            def register_or_create_session(self, **k):
                pass

            async def broadcast_event(self, session_id, event):
                captured["payload"] = event.payload

        import neurova.sync.session_sync_manager as ssm

        monkeypatch.setattr(ssm, "get_session_sync_manager", lambda *a, **k: FakeMgr())
        await inst._emit_computer_event(
            "computer_ssh_exec", {"host": "9.9.9.9"},
            {"success": False, "needs_credential": True, "host": "9.9.9.9", "error": "x"},
        )
        assert captured["payload"].get("needs_credential") is True
        assert captured["payload"].get("host") == "9.9.9.9"

    @pytest.mark.asyncio
    async def test_explicit_user_bypasses_needs_credential(self, monkeypatch):
        """调用方显式给 user（可能靠系统 agent 密钥）→ 不拦，照常尝试连接。"""
        from neurova.tool_executor import ToolExecutor

        inst = ToolExecutor.__new__(ToolExecutor)
        inst._agent = type("A", (), {"current_session_id": None, "_current_user_id": "u1"})()
        monkeypatch.setattr("neurova.computer_use.ssh_runner.resolve_ssh_credentials", lambda u, h: {})
        monkeypatch.setattr(
            "neurova.computer_use.ssh_runner.run_ssh_command",
            lambda *a, **k: {"returncode": 0, "stdout": "ok", "stderr": ""},
        )

        async def fake_emit(self, *a, **k):
            return None

        monkeypatch.setattr(ToolExecutor, "_emit_computer_event", fake_emit)
        out = await inst._execute_computer_ssh_exec({"host": "h", "command": "ls", "user": "root"})
        assert out["success"] is True and "needs_credential" not in out

    @pytest.mark.asyncio
    async def test_credential_bucket_key_matches_jwt_user(self, monkeypatch):
        """闭环关键：工具读凭据的用户桶必须 == 凭据 API 的 JWT user_id
        （identity_context），否则按需卡存到真实用户桶、工具读 default 桶白存。"""
        from neurova.tool_executor import ToolExecutor

        inst = ToolExecutor.__new__(ToolExecutor)
        # agent 身份回退会是 "default"（_current_user_id 未设），但请求级身份是 alice
        inst._agent = type("A", (), {"current_session_id": None})()

        from neurova.core import identity_context

        monkeypatch.setattr(identity_context, "get_request_user_id", lambda: "alice")
        seen = {}

        def fake_resolve(uid, host):
            seen["uid"] = uid
            return {"user": "root", "port": 22, "key_text": "K", "password": None}

        monkeypatch.setattr("neurova.computer_use.ssh_runner.resolve_ssh_credentials", fake_resolve)
        monkeypatch.setattr(
            "neurova.computer_use.ssh_runner.run_ssh_command",
            lambda *a, **k: {"returncode": 0, "stdout": "ok", "stderr": ""},
        )

        async def fake_emit(self, *a, **k):
            return None

        monkeypatch.setattr(ToolExecutor, "_emit_computer_event", fake_emit)
        await inst._execute_computer_ssh_exec({"host": "h", "command": "ls"})
        assert seen["uid"] == "alice", "凭据桶键须用请求级 JWT user，非 agent 回退 default"
