"""CamofoxSupervisor 单元测试

TDD 步骤(红→绿):
- 红:本文件先写,验证未实现时的失败状态
- 绿:实现 CamofoxSupervisor 直到测试通过

Mock 策略:
- 替换 subprocess.Popen 为 MagicMock(检查 spawn 行为)
- 替换 httpx.AsyncClient.get 为 AsyncMock(模拟 /health 返回)
- 临时目录用 tmp_path 隔离文件系统影响
- 不引入 respx(项目无此依赖)
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── 帮助函数 ──


def _http_response(payload: dict | None = None, content: bytes = b"{}") -> MagicMock:
    r = MagicMock()
    r.status_code = 200
    r.content = content
    r.json = MagicMock(return_value=payload or {})
    r.raise_for_status = MagicMock(return_value=None)
    return r


def _healthy_response(rss: int = 100) -> MagicMock:
    return _http_response({"ok": True, "browserRunning": True, "memory": {"rssMb": rss}})


def _make_process_mock(*, poll_return=None, returncode=0, pid=12345) -> MagicMock:
    """构造一个 subprocess.Popen 替身"""
    p = MagicMock()
    p.pid = pid
    p.poll = MagicMock(return_value=poll_return)  # None 表示还在跑
    p.terminate = MagicMock(return_value=None)
    p.kill = MagicMock(return_value=None)
    p.wait = MagicMock(return_value=returncode)
    p.returncode = returncode
    return p


def _make_supervisor(
    *,
    config: dict | None = None,
    process_mock: MagicMock | None = None,
    health_response: MagicMock | None = None,
    env_overrides: dict | None = None,
) -> tuple:
    """构造 supervisor 实例并 patch subprocess.Popen + httpx.AsyncClient"""
    from neurova.computer_use import camofox_supervisor as mod

    env = env_overrides or {}
    for k, v in env.items():
        os.environ[k] = str(v)

    proc = process_mock or _make_process_mock()
    health = health_response or _healthy_response()

    # patch Popen 让其返回我们的 mock
    with patch.object(mod, "subprocess") as mock_subproc:
        mock_subproc.Popen = MagicMock(return_value=proc)
        mock_subproc.TimeoutExpired = TimeoutExpired
        from neurova.computer_use.camofox_supervisor import CamofoxSupervisor

        s = CamofoxSupervisor(config or {})

    # patch httpx.AsyncClient 使 /health 返回健康
    original_init = s.__class__

    return s, proc


class TimeoutExpired(Exception):
    pass


# ── 测试类 ──


class TestCamofoxSupervisorInit:
    """构造与配置读取"""

    def test_default_command_is_npx(self, monkeypatch):
        monkeypatch.delenv("NEUROVA_CAMOFOX_COMMAND", raising=False)
        from neurova.computer_use.camofox_supervisor import (
            CamofoxSupervisor,
            DEFAULT_COMMAND,
        )

        s = CamofoxSupervisor()
        assert s._command == DEFAULT_COMMAND
        assert s._command == ["npx", "-y", "@askjo/camofox-browser"]

    def test_env_command_overrides_default(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_CAMOFOX_COMMAND", "node /path/to/server.js")
        from neurova.computer_use.camofox_supervisor import CamofoxSupervisor

        s = CamofoxSupervisor()
        assert s._command == ["node", "/path/to/server.js"]

    def test_cfg_overrides_env(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_CAMOFOX_COMMAND", "npx -y foo")
        from neurova.computer_use.camofox_supervisor import CamofoxSupervisor

        s = CamofoxSupervisor({"command": ["node", "custom.js"]})
        assert s._command == ["node", "custom.js"]

    def test_default_timeouts(self, monkeypatch):
        for k in [
            "NEUROVA_CAMOFOX_IDLE_TIMEOUT",
            "NEUROVA_CAMOFOX_STARTUP_TIMEOUT",
            "NEUROVA_CAMOFOX_KILL_GRACE",
        ]:
            monkeypatch.delenv(k, raising=False)
        from neurova.computer_use.camofox_supervisor import CamofoxSupervisor

        s = CamofoxSupervisor()
        assert s._idle_timeout == 300
        assert s._startup_timeout == 90
        assert s._kill_grace == 5

    def test_env_overrides_defaults(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_CAMOFOX_IDLE_TIMEOUT", "120")
        monkeypatch.setenv("NEUROVA_CAMOFOX_AUTOSTART", "false")
        monkeypatch.setenv("NEUROVA_CAMOFOX_CLEANUP_ON_STOP", "false")
        from neurova.computer_use.camofox_supervisor import CamofoxSupervisor

        s = CamofoxSupervisor()
        assert s._idle_timeout == 120
        assert s._autostart is False
        assert s._cleanup_on_stop is False

    def test_user_id_from_env(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_CAMOFOX_USER", "my-agent")
        from neurova.computer_use.camofox_supervisor import CamofoxSupervisor

        s = CamofoxSupervisor()
        assert s._user_id == "my-agent"

    def test_user_id_default(self, monkeypatch):
        monkeypatch.delenv("NEUROVA_CAMOFOX_USER", raising=False)
        from neurova.computer_use.camofox_supervisor import CamofoxSupervisor

        s = CamofoxSupervisor()
        assert s._user_id == "neurova"


class TestEnsureStarted:
    """ensure_started 行为:进程在/不在,autostart 开关,enabled 开关"""

    @pytest.mark.asyncio
    async def test_returns_true_if_already_running(self):
        from neurova.computer_use.camofox_supervisor import CamofoxSupervisor

        s = CamofoxSupervisor()
        proc = _make_process_mock()  # poll() 返回 None → 在跑
        s._process = proc
        s._last_activity = 0.0  # stale,但 is_running=True 优先

        ok = await s.ensure_started()
        assert ok is True
        # 刷新了 last_activity
        assert s._last_activity > 0
        assert s._managed_by_supervisor is False  # 没动这个标志

    @pytest.mark.asyncio
    async def test_disabled_supervisor_probes_health_only(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_CAMOFOX_SUPERVISOR", "false")
        from neurova.computer_use.camofox_supervisor import CamofoxSupervisor

        s = CamofoxSupervisor()
        with patch.object(s, "_probe_health", AsyncMock(return_value=True)) as mock_probe:
            ok = await s.ensure_started()
            assert ok is True
            mock_probe.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_autostart_false_returns_false(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_CAMOFOX_AUTOSTART", "false")
        from neurova.computer_use.camofox_supervisor import CamofoxSupervisor

        s = CamofoxSupervisor()
        ok = await s.ensure_started()
        assert ok is False


class TestSpawnAndWaitReady:
    """_spawn_and_wait_ready:启动 → 轮询 /health → ready"""

    @pytest.mark.asyncio
    async def test_spawn_subprocess_called(self):
        from neurova.computer_use.camofox_supervisor import CamofoxSupervisor
        from neurova.computer_use import camofox_supervisor as mod

        s = CamofoxSupervisor()
        proc = _make_process_mock()
        with patch.object(mod, "subprocess") as mock_subproc:
            mock_subproc.Popen = MagicMock(return_value=proc)
            with patch.object(s, "_probe_health_via_client", AsyncMock(return_value=True)):
                ok = await s._spawn_and_wait_ready()
                assert ok is True
                mock_subproc.Popen.assert_called_once()
                assert s._process is proc

    @pytest.mark.asyncio
    async def test_kill_when_health_never_ready(self):
        from neurova.computer_use.camofox_supervisor import CamofoxSupervisor
        from neurova.computer_use import camofox_supervisor as mod

        s = CamofoxSupervisor({"startup_timeout": 1})  # 短超时
        proc = _make_process_mock()
        with patch.object(mod, "subprocess") as mock_subproc:
            mock_subproc.Popen = MagicMock(return_value=proc)
            mock_subproc.TimeoutExpired = TimeoutExpired
            # probe 永远 False
            with patch.object(s, "_probe_health_via_client", AsyncMock(return_value=False)):
                ok = await s._spawn_and_wait_ready()
                assert ok is False
                proc.terminate.assert_called()  # 超时后被 kill

    @pytest.mark.asyncio
    async def test_process_exits_immediately_returns_false(self):
        from neurova.computer_use.camofox_supervisor import CamofoxSupervisor
        from neurova.computer_use import camofox_supervisor as mod

        s = CamofoxSupervisor()
        # poll 返回 1 → 进程立即死了
        proc = _make_process_mock(poll_return=1, returncode=1)
        with patch.object(mod, "subprocess") as mock_subproc:
            mock_subproc.Popen = MagicMock(return_value=proc)
            ok = await s._spawn_and_wait_ready()
            assert ok is False


class TestRecordActivity:
    """record_activity:刷新 _last_activity"""

    def test_record_activity_updates_timestamp(self):
        from neurova.computer_use.camofox_supervisor import CamofoxSupervisor

        s = CamofoxSupervisor()
        s._process = _make_process_mock()  # 在跑
        s._last_activity = 0.0

        before = time.time()
        s.record_activity()
        after = time.time()

        assert before <= s._last_activity <= after

    def test_record_activity_noop_if_not_running(self):
        from neurova.computer_use.camofox_supervisor import CamofoxSupervisor

        s = CamofoxSupervisor()
        s._last_activity = 0.0
        s.record_activity()
        assert s._last_activity == 0.0  # 没动


class TestIdleCheck:
    """_check_idle:超时则请求停止"""

    def test_idle_check_triggers_stop_event(self):
        from neurova.computer_use.camofox_supervisor import CamofoxSupervisor

        s = CamofoxSupervisor({"idle_timeout": 1})
        s._process = _make_process_mock()
        s._last_activity = time.time() - 100  # 100 秒前

        s._check_idle()
        assert s._stop_requested.is_set()

    def test_idle_check_noop_when_fresh(self):
        from neurova.computer_use.camofox_supervisor import CamofoxSupervisor

        s = CamofoxSupervisor({"idle_timeout": 1000})
        s._process = _make_process_mock()
        s._last_activity = time.time()  # 刚刚活跃

        s._check_idle()
        assert not s._stop_requested.is_set()

    def test_idle_check_noop_when_not_running(self):
        from neurova.computer_use.camofox_supervisor import CamofoxSupervisor

        s = CamofoxSupervisor({"idle_timeout": 1})
        s._process = None  # 没跑
        s._check_idle()
        assert not s._stop_requested.is_set()


class TestCleanupTempTraces:
    """_cleanup_temp_traces:只删 traces(超 TTL)+ uploads,保留 profiles/cookies"""

    def test_noop_when_cleanup_disabled(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NEUROVA_CAMOFOX_CLEANUP_ON_STOP", "false")
        from neurova.computer_use.camofox_supervisor import CamofoxSupervisor

        s = CamofoxSupervisor({"user_id": "neurova"})
        # 模拟 traces/<user>/ 存在一个 zip
        user_dir = tmp_path / ".camofox" / "traces" / s._user_dir_name()
        user_dir.mkdir(parents=True)
        (user_dir / "old.zip").write_bytes(b"x" * 100)

        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        cleaned = s._cleanup_temp_traces()
        # cleanup_on_stop=false 早返回,字典保持初始 4 键全 0
        assert cleaned == {"traces_zip": 0, "uploads": 0, "bytes": 0, "users": 0}
        assert (user_dir / "old.zip").exists()  # 没动

    def test_deletes_old_zip_keeps_recent(self, tmp_path, monkeypatch):
        from neurova.computer_use.camofox_supervisor import CamofoxSupervisor

        s = CamofoxSupervisor({"user_id": "neurova", "trace_ttl_hours": 1})
        user_dir = tmp_path / ".camofox" / "traces" / s._user_dir_name()
        user_dir.mkdir(parents=True)

        # 旧 zip(2 小时前)应被删
        old_zip = user_dir / "old.zip"
        old_zip.write_bytes(b"x" * 100)
        old_time = time.time() - 7200
        os.utime(old_zip, (old_time, old_time))

        # 新 zip(刚刚)保留
        new_zip = user_dir / "new.zip"
        new_zip.write_bytes(b"y" * 50)

        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        cleaned = s._cleanup_temp_traces()
        assert cleaned["traces_zip"] == 1
        assert cleaned["bytes"] == 100
        assert not old_zip.exists()
        assert new_zip.exists()

    def test_deletes_uploads_directory(self, tmp_path, monkeypatch):
        from neurova.computer_use.camofox_supervisor import CamofoxSupervisor

        s = CamofoxSupervisor({"user_id": "neurova"})
        uploads = tmp_path / ".camofox" / "uploads"
        uploads.mkdir(parents=True)
        (uploads / "data.txt").write_bytes(b"hello" * 100)

        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        cleaned = s._cleanup_temp_traces()
        assert cleaned["uploads"] == 1
        assert cleaned["bytes"] > 0
        assert not uploads.exists()

    def test_preserves_profiles(self, tmp_path, monkeypatch):
        """profiles/<user>/ 不能被删——那是登录态"""
        from neurova.computer_use.camofox_supervisor import CamofoxSupervisor

        s = CamofoxSupervisor({"user_id": "neurova"})
        profiles = tmp_path / ".camofox" / "profiles" / s._user_dir_name()
        profiles.mkdir(parents=True)
        (profiles / "storage-state.json").write_text('{"loggedIn":true}')

        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        s._cleanup_temp_traces()
        # profiles 仍在
        assert (profiles / "storage-state.json").exists()

    def test_handles_missing_traces_dir(self, tmp_path, monkeypatch):
        """不存在 ~/.camofox/ 时不抛"""
        from neurova.computer_use.camofox_supervisor import CamofoxSupervisor

        s = CamofoxSupervisor({"user_id": "neurova"})
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        cleaned = s._cleanup_temp_traces()
        # 不存在 traces 目录时无操作,但 users 计数仍然 +1(fallback user 走了流程)
        assert cleaned == {"traces_zip": 0, "uploads": 0, "bytes": 0, "users": 1}

    def test_user_dir_name_matches_camofox_convention(self):
        """sha256(userId)[:32]——必须与 camofox persistence 插件命名一致"""
        import hashlib

        from neurova.computer_use.camofox_supervisor import CamofoxSupervisor

        s = CamofoxSupervisor({"user_id": "neurova"})
        expected = hashlib.sha256(b"neurova").hexdigest()[:32]
        assert s._user_dir_name() == expected


class TestStop:
    """stop:顺序——清理 → 杀进程;只在 managed 时杀"""

    @pytest.mark.asyncio
    async def test_stop_calls_cleanup_then_kill(self):
        from neurova.computer_use.camofox_supervisor import CamofoxSupervisor

        s = CamofoxSupervisor({"cleanup_on_stop": True})
        proc = _make_process_mock()
        s._process = proc
        s._managed_by_supervisor = True

        with patch.object(s, "_cleanup_temp_traces", return_value={"traces_zip": 0, "uploads": 0, "bytes": 0}) as mock_cleanup:
            await s.stop()
            mock_cleanup.assert_called_once()
            proc.terminate.assert_called()
            assert s._process is None
            assert s._managed_by_supervisor is False

    @pytest.mark.asyncio
    async def test_stop_skips_external_process(self):
        """用户手动起的 camofox-browser 不能杀——靠 _managed_by_supervisor=False"""
        from neurova.computer_use.camofox_supervisor import CamofoxSupervisor

        s = CamofoxSupervisor()
        proc = _make_process_mock()
        s._process = proc
        s._managed_by_supervisor = False  # 不是 supervisor 拉起的

        await s.stop()
        proc.terminate.assert_not_called()
        proc.kill.assert_not_called()
        # 进程记录仍在
        assert s._process is proc

    @pytest.mark.asyncio
    async def test_stop_handles_already_dead(self):
        from neurova.computer_use.camofox_supervisor import CamofoxSupervisor

        s = CamofoxSupervisor()
        proc = _make_process_mock(poll_return=1, returncode=1)  # 已死
        s._process = proc
        s._managed_by_supervisor = True

        await s.stop()  # 不抛
        proc.terminate.assert_not_called()

    @pytest.mark.asyncio
    async def test_stop_stops_monitor_thread(self):
        from neurova.computer_use.camofox_supervisor import CamofoxSupervisor

        s = CamofoxSupervisor()
        mock_thread = MagicMock()
        mock_thread.is_alive = MagicMock(return_value=True)
        s._monitor_thread = mock_thread
        s._monitor_running = True

        await s.stop()
        assert s._monitor_running is False
        mock_thread.join.assert_called_with(timeout=2.0)


class TestKillProcess:
    """_kill_process:terminate → wait(grace) → kill -9"""

    @pytest.mark.asyncio
    async def test_kill_graceful(self):
        from neurova.computer_use.camofox_supervisor import CamofoxSupervisor

        s = CamofoxSupervisor({"kill_grace": 1})
        proc = _make_process_mock()
        s._process = proc
        s._managed_by_supervisor = True

        await s._kill_process()
        proc.terminate.assert_called_once()
        proc.wait.assert_called()
        proc.kill.assert_not_called()  # 优雅退出不需要 SIGKILL

    @pytest.mark.asyncio
    async def test_kill_force_after_timeout(self, monkeypatch):
        from neurova.computer_use.camofox_supervisor import CamofoxSupervisor
        from neurova.computer_use import camofox_supervisor as mod

        # 强制走 POSIX 路径(避开 Windows taskkill 分支)
        monkeypatch.setattr("neurova.computer_use.camofox_supervisor.sys.platform", "linux")

        s = CamofoxSupervisor({"kill_grace": 0})

        # wait 第一次超时(grace 满),第二次 OK
        wait_calls = [
            TimeoutExpired("cmd", 0),  # wait(timeout=0) 超时
            0,  # kill 后 wait 返回
        ]
        proc = MagicMock()
        proc.terminate = MagicMock(return_value=None)
        proc.kill = MagicMock(return_value=None)
        proc.wait = MagicMock(side_effect=wait_calls)
        proc.poll = MagicMock(return_value=None)
        s._process = proc

        with patch.object(mod, "subprocess") as mock_subproc:
            mock_subproc.TimeoutExpired = TimeoutExpired
            await s._kill_process()
            proc.terminate.assert_called_once()
            proc.kill.assert_called_once()


class TestSingletonLifecycle:
    """get_camofox_supervisor / reset_camofox_supervisor"""

    def test_get_returns_singleton(self):
        from neurova.computer_use.camofox_supervisor import (
            get_camofox_supervisor,
            reset_camofox_supervisor,
        )

        reset_camofox_supervisor()
        s1 = get_camofox_supervisor()
        s2 = get_camofox_supervisor()
        assert s1 is s2
        reset_camofox_supervisor()

    def test_reset_clears_instance(self):
        from neurova.computer_use.camofox_supervisor import (
            get_camofox_supervisor,
            reset_camofox_supervisor,
        )

        reset_camofox_supervisor()
        s1 = get_camofox_supervisor()
        reset_camofox_supervisor()
        s2 = get_camofox_supervisor()
        assert s1 is not s2


class TestIsRunning:
    """is_running / pid 属性"""

    def test_is_running_true_when_process_alive(self):
        from neurova.computer_use.camofox_supervisor import CamofoxSupervisor

        s = CamofoxSupervisor()
        s._process = _make_process_mock()  # poll() → None
        assert s.is_running is True
        assert s.pid == 12345

    def test_is_running_false_when_process_dead(self):
        from neurova.computer_use.camofox_supervisor import CamofoxSupervisor

        s = CamofoxSupervisor()
        s._process = _make_process_mock(poll_return=0)  # 已死
        assert s.is_running is False
        assert s.pid is None

    def test_is_running_false_when_no_process(self):
        from neurova.computer_use.camofox_supervisor import CamofoxSupervisor

        s = CamofoxSupervisor()
        assert s.is_running is False
        assert s.pid is None