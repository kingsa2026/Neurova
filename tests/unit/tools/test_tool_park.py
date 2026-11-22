# -*- coding: utf-8 -*-
"""U8 长命令 park + 迟交回灌（红→绿）。

契约（实施计划 U8 + 拍板 D-T2=REST 轮询）：
- ssh/exec 类命令超过 soft 阈值（默认 45s，可配）→ 不判失败，转后台继续执行，
  返回 park 信封 ``{parked: true, park_id, poll_after}``；
- 结果落 tool_park_results（进程内 + 落盘）；``GET /v1/tools/park/{park_id}``
  幂等取回完整结果；上限对齐 800s，超上限诚实失败；
- park 开启时 ssh 执行预算放宽到 park 上限（120s 命令不再被缺省 60s 掐死）。

红（现网行为）：长命令超过执行预算即失败，无 park 信封、结果无法取回，
ssh 缺省执行预算仍是 60s。
"""

from __future__ import annotations

import asyncio
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import neurova.computer_use.ssh_runner as ssh_runner  # noqa: E402
import neurova.tool_executor as te  # noqa: E402
from neurova.tool_executor import ToolExecutor, parkResultSnapshot  # noqa: E402

PARK_HOST = "park-host.test"


def _makeExecutor(user_id: str = "u1") -> ToolExecutor:
    agent = SimpleNamespace(
        config=SimpleNamespace(user_id=user_id, agent_id="a1"),
        tool_memory=MagicMock(),
        tool_lifecycle=None,
        _skill_registry=None,
        tool_router=None,
        _current_user_input="x",
        _tool_messages_list=[],
        append_tool_messages=lambda records: None,
    )
    return ToolExecutor(agent)


@pytest.fixture
def parkableSsh(monkeypatch):
    """真实凭据分桶 + 可控时长的 ssh 执行替身（记录收到的执行预算）。"""
    from neurova.web_reach.credentials import get_credential_store

    get_credential_store().set_ssh_host(
        "u1", PARK_HOST, user="tester", password="not-a-real-secret")
    seen: dict = {}
    release = threading.Event()

    def _fakeRun(host, command, **kwargs):
        seen["timeout"] = kwargs.get("timeout")
        # 模拟长命令：跑到测试放行（上限 30s 防挂死），随后交出完整结果
        release.wait(timeout=30)
        return {"returncode": 0, "stdout": "park-done", "stderr": ""}

    monkeypatch.setattr(ssh_runner, "run_ssh_command", _fakeRun)
    return seen, release


@pytest.fixture
def fastPark(monkeypatch):
    """软阈值 0.5s / 上限 800s：让 park 在亚秒级触发（判据不靠真等 45s）。"""
    monkeypatch.setattr(te, "parkSoftTimeoutSeconds", lambda: 0.5)
    monkeypatch.setattr(te, "parkMaxSeconds", lambda: 800.0)


@pytest.fixture
def approvalQueueIsolated():
    from neurova.tool_executor import _get_approval_manager

    am = _get_approval_manager()
    am._resetForTests()
    yield am
    am._resetForTests()


def _governanceOff(executor: ToolExecutor, monkeypatch):
    async def _none(tool_name, params):
        return None

    monkeypatch.setattr(executor, "_governance_precheck", _none)
    monkeypatch.setattr(executor, "_dynamicInterventionCheck", _none)


class TestToolPark:
    @pytest.mark.asyncio
    async def test_sshLongCommandParksAndBackfills(
        self, monkeypatch, parkableSsh, fastPark, approvalQueueIsolated
    ):
        """绿判据：超软阈值 → park 信封；后台跑完 → park_id 取回完整结果；重复查询幂等。"""
        seen, release = parkableSsh
        executor = _makeExecutor()
        _governanceOff(executor, monkeypatch)

        first = await executor._execute_single_tool(
            "computer_ssh_exec", {"host": PARK_HOST, "command": "sleep 120 && echo done"})

        assert first.get("parked") is True, f"超软阈值应返回 park 信封: {first}"
        parkId = first.get("park_id")
        assert parkId, "信封必须带 park_id"
        assert first.get("poll_after") is not None

        # 后台继续执行：放行替身，等观察者回灌
        release.set()
        entry = None
        for _ in range(200):
            entry = parkResultSnapshot(parkId)
            if entry and entry.get("status") == "completed":
                break
            await asyncio.sleep(0.1)
        assert entry and entry.get("status") == "completed", f"迟交结果应回灌: {entry}"
        assert entry["result"].get("stdout") == "park-done", f"应取回完整结果: {entry}"
        assert seen.get("timeout") is not None

        # 幂等：重复查询返回同一份结果
        again = parkResultSnapshot(parkId)
        assert again == entry, "重复查询必须幂等"

    @pytest.mark.asyncio
    async def test_sshBudgetExtendedWhenParkEnabled(self, parkableSsh, fastPark):
        """绿判据：park 开启时 ssh 缺省执行预算放宽到 park 上限（不再 60s 掐死）。"""
        seen, release = parkableSsh
        release.set()  # 预算判据只看执行体收到的 timeout，不要求命令真的长跑
        executor = _makeExecutor()
        # 直接走 ssh 执行体（预算判定在执行体内），不经过治理
        await executor._execute_computer_ssh_exec(
            {"host": PARK_HOST, "command": "sleep 120 && echo done"})
        assert seen.get("timeout") is not None
        assert seen["timeout"] >= 800.0, (
            f"park 开启时 ssh 执行预算应放宽到 park 上限（800s），实际 {seen['timeout']}s"
            "——120s 命令不得被缺省 60s 掐死")

    @pytest.mark.asyncio
    async def test_sshBudgetLegacyWhenParkDisabled(
        self, monkeypatch, parkableSsh
    ):
        """park 关闭（env NEUROVA_TOOL_PARK_DISABLE=1）→ 维持原 60s 缺省预算。"""
        monkeypatch.setenv("NEUROVA_TOOL_PARK_DISABLE", "1")
        seen, release = parkableSsh
        release.set()
        executor = _makeExecutor()
        await executor._execute_computer_ssh_exec(
            {"host": PARK_HOST, "command": "echo quick"})
        assert seen.get("timeout") == 60.0, (
            f"park 关闭时必须维持原缺省 60s 预算，实际 {seen.get('timeout')}s")

    @pytest.mark.asyncio
    async def test_parkResultPersistedToDisk(
        self, monkeypatch, parkableSsh, fastPark, tmp_path
    ):
        """结果落盘：park 完成后数据根 tool_park_results/ 有持久副本。"""
        seen, release = parkableSsh
        executor = _makeExecutor()
        _governanceOff(executor, monkeypatch)
        first = await executor._execute_single_tool(
            "computer_ssh_exec", {"host": PARK_HOST, "command": "sleep 120"})
        parkId = first["park_id"]
        release.set()
        for _ in range(200):
            entry = parkResultSnapshot(parkId)
            if entry and entry.get("status") == "completed":
                break
            await asyncio.sleep(0.1)
        disk = Path(te.dataPath("tool_park_results", f"{parkId}.json"))
        assert disk.exists(), f"park 结果应落盘: {disk}"
        assert "park-done" in disk.read_text(encoding="utf-8")

    @pytest.mark.asyncio
    async def test_parkCapHonestFailure(self, monkeypatch, parkableSsh):
        """超 park 上限 → 诚实失败（不谎报完成）。"""
        seen, release = parkableSsh
        monkeypatch.setattr(te, "parkSoftTimeoutSeconds", lambda: 0.3)
        monkeypatch.setattr(te, "parkMaxSeconds", lambda: 1.0)
        executor = _makeExecutor()
        _governanceOff(executor, monkeypatch)
        first = await executor._execute_single_tool(
            "computer_ssh_exec", {"host": PARK_HOST, "command": "sleep 120"})
        assert first.get("parked") is True
        parkId = first["park_id"]
        entry = None
        for _ in range(200):
            entry = parkResultSnapshot(parkId)
            if entry and entry.get("status") in ("completed", "failed"):
                break
            await asyncio.sleep(0.1)
        assert entry and entry.get("status") == "failed", f"超上限应诚实失败: {entry}"
        assert "上限" in str(entry.get("error")), f"失败原因应点名上限: {entry}"
        release.set()

    @pytest.mark.asyncio
    async def test_parkDisabledEnvRestoresLegacyFlow(
        self, monkeypatch, parkableSsh, approvalQueueIsolated
    ):
        """park 关闭 → 不产生 park 信封（既有超时转后台行为保持）。"""
        monkeypatch.setenv("NEUROVA_TOOL_PARK_DISABLE", "1")
        seen, release = parkableSsh
        release.set()
        executor = _makeExecutor()
        _governanceOff(executor, monkeypatch)
        result = await executor._execute_single_tool(
            "computer_ssh_exec", {"host": PARK_HOST, "command": "echo quick"})
        assert result.get("parked") is not True, f"park 关闭时不得出信封: {result}"


class TestToolParkEndpoint:
    """GET /v1/tools/park/{park_id}（D-T2 REST 轮询取回面）。"""

    def _client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from neurova.api.auth import get_current_user
        from neurova.api.endpoints import tool_park

        app = FastAPI()
        app.include_router(tool_park.router, prefix="/api/v1/tools")
        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": "u1", "username": "tester", "role": "user"}
        return TestClient(app, raise_server_exceptions=False)

    def test_parkModuleRegisteredInEndpointRegistry(self):
        src = (PROJECT_ROOT / "neurova" / "api" / "endpoints" / "__init__.py").read_text(
            encoding="utf-8")
        assert "neurova.api.endpoints.tool_park" in src, (
            "tool_park 必须注册进端点注册表（未挂载路由模块会被 mount 守卫点名）")
        assert '"/v1/tools"' in src

    def test_unknownParkIdIs404(self):
        with self._client() as client:
            resp = client.get("/api/v1/tools/park/park_nonexistent")
            assert resp.status_code == 404, f"未知 park_id 应 404: {resp.status_code}"

    def test_runningAndCompletedAndIdempotent(self, monkeypatch):
        from neurova.tool_executor import recordParkResult

        parkId = "park_endpoint_case"
        recordParkResult(parkId, {
            "park_id": parkId, "tool_name": "computer_ssh_exec",
            "status": "running", "poll_after": 2, "max_wait_s": 800,
            "parked_at": "2026-11-22T00:00:00+00:00",
        })
        with self._client() as client:
            running = client.get(f"/api/v1/tools/park/{parkId}")
            assert running.status_code == 200
            body = running.json()
            assert body["data"]["status"] == "running"
            assert body["data"]["poll_after"] == 2

            recordParkResult(parkId, {
                "park_id": parkId, "tool_name": "computer_ssh_exec",
                "status": "completed", "success": True,
                "result": {"success": True, "stdout": "park-done"},
                "completed_at": "2026-11-22T00:00:05+00:00",
            })
            first = client.get(f"/api/v1/tools/park/{parkId}")
            second = client.get(f"/api/v1/tools/park/{parkId}")
            assert first.status_code == 200 and second.status_code == 200
            assert first.json() == second.json(), "重复查询必须幂等"
            assert first.json()["data"]["result"]["stdout"] == "park-done"

    def test_failedParkReportsHonestError(self):
        from neurova.tool_executor import recordParkResult

        parkId = "park_endpoint_failed"
        recordParkResult(parkId, {
            "park_id": parkId, "tool_name": "exec_command", "status": "failed",
            "error": "命令超过 park 上限 800s 仍未完成，已终止等待（超限诚实失败）",
        })
        with self._client() as client:
            resp = client.get(f"/api/v1/tools/park/{parkId}")
            assert resp.status_code == 200
            data = resp.json()["data"]
            assert data["status"] == "failed" and data["success"] is False
            assert "上限" in data["error"]
