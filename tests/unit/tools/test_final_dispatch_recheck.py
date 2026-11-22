"""U4 派发前最后一刻授权复验（D4 升级计划）。

契约：审批通过后、真正执行前，`_final_dispatch_recheck` 对 ssh/exec/file 写类复验——
- 当前执行入参指纹必须能在审批队列里对上**已批准**的同一对象（防审批后篡改参数）；
- ssh：目标 host 在凭据桶已有条目（或即批准对象本身的 host）；
- exec：命令首段仍过 command_segments 白名单（或即批准对象本身的命令）；
- 文件写：路径仍在会话工作根内（或即批准对象本身的路径）。
不一致 → 转回审批队列并审计，不直接执行。

红（现网行为）：审批后篡改参数，重放仍按旧审批直接执行。
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from neurova.security.governance import GovernanceDecision, GovernanceResult
from neurova.tool_executor import ToolExecutor, _get_approval_manager


@pytest.fixture
def approvalQueueIsolated():
    am = _get_approval_manager()
    am._resetForTests()
    yield am
    am._resetForTests()


def _makeExecutor(monkeypatch, workspace_root=None):
    agent = SimpleNamespace(
        config=SimpleNamespace(user_id="u1", agent_id="a1"),
        tool_memory=MagicMock(),
        tool_lifecycle=None,
        _skill_registry=None,
        tool_router=None,
        _current_user_input="x",
        _tool_messages_list=[],
        append_tool_messages=lambda records: None,
    )
    if workspace_root is not None:
        agent.workspace_path = str(workspace_root)
    executor = ToolExecutor(agent)

    async def _noGovernance(tool_name, params):
        return None

    monkeypatch.setattr(executor, "_governance_precheck", _noGovernance)
    return executor


def _askVerdict() -> GovernanceResult:
    return GovernanceResult(
        decision=GovernanceDecision.ASK, reasons=["单元测试：模拟治理 ASK 裁决"])


class TestFinalDispatchRecheck:
    @pytest.mark.asyncio
    async def test_approvedThenTamperedFileWriteBouncesBack(
        self, monkeypatch, tmp_path, approvalQueueIsolated
    ):
        """红：审批后篡改写路径，重放仍按旧审批执行；
        绿：复验发现不一致 → 转回审批队列 + 审计，不执行。"""
        ws = tmp_path / "ws"
        ws.mkdir(parents=True, exist_ok=True)
        outside = tmp_path / "outside"
        outside.mkdir(parents=True, exist_ok=True)

        executor = _makeExecutor(monkeypatch, workspace_root=ws)
        auditCalls = []
        monkeypatch.setattr(
            executor, "_audit_governance",
            lambda tool_name, info, params: auditCalls.append((tool_name, info)),
        )

        approvedParams = {"file_path": str(ws / "a.txt"), "content": "hello"}
        approval_id = executor._create_approval_request("file_write", approvedParams, _askVerdict())
        assert approval_id
        assert approvalQueueIsolated.approve_request(approval_id, approved_by="tester")

        tampered = {"file_path": str(outside / "evil.txt"), "content": "x"}
        result = await executor._execute_single_tool("file_write", tampered, skip_governance=True)

        assert result.get("pending_approval") is True, f"现网行为（按旧审批执行）: {result}"
        assert not (outside / "evil.txt").exists(), "复验不一致时不得执行写操作"
        assert not (ws / "a.txt").exists()
        assert auditCalls, "复验拒绝必须落审计"
        pending = approvalQueueIsolated.get_pending_requests()
        assert any(
            r.metadata.get("tool_name") == "file_write" and r.status.value == "pending"
            for r in pending
        ), "不一致必须转回审批队列（新待审批单）"

    @pytest.mark.asyncio
    async def test_unchangedApprovedReplayStillExecutes(
        self, monkeypatch, tmp_path, approvalQueueIsolated
    ):
        """反方向守卫：批准对象原样重放必须照常执行（复验不得误伤正常批准链）。"""
        ws = tmp_path / "ws"
        ws.mkdir(parents=True, exist_ok=True)
        executor = _makeExecutor(monkeypatch, workspace_root=ws)

        approvedParams = {"file_path": str(ws / "ok.txt"), "content": "fine"}
        approval_id = executor._create_approval_request("file_write", approvedParams, _askVerdict())
        assert approvalQueueIsolated.approve_request(approval_id, approved_by="tester")

        result = await executor._execute_single_tool(
            "file_write", dict(approvedParams), skip_governance=True)
        assert result.get("success") is True, result
        assert (ws / "ok.txt").read_text(encoding="utf-8") == "fine"

    @pytest.mark.asyncio
    async def test_inTurnWakeupWithTamperedParamsBounces(
        self, monkeypatch, tmp_path, approvalQueueIsolated
    ):
        """红：等待中的原调用被批准唤醒后，若入参已被篡改仍直接执行；
        绿：复验不一致 → 转回审批队列（返回待审批形态，不执行）。

        真实时序：审批单在 ASK 时以**当时**入参建单（指纹落库）→ 阻塞等待；
        唤醒前入参被篡改 → 复验对不上 → 弹回。本测试用 pending future 复现
        "创建 → 篡改 → 批准唤醒" 的时序。"""
        ws = tmp_path / "ws"
        ws.mkdir(parents=True, exist_ok=True)
        executor = _makeExecutor(monkeypatch, workspace_root=ws)

        monkeypatch.setenv("NEUROVA_APPROVAL_WAIT_SECONDS", "5")
        params = {"file_path": str(ws / "b.txt"), "content": "keep"}
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        monkeypatch.setattr(
            "neurova.security.approval_relay.registerApprovalWaiter", lambda rid: fut)

        task = asyncio.create_task(
            executor._awaitApprovalVerdict("file_write", params, _askVerdict()))
        await asyncio.sleep(0)  # 让审批单先以原始入参建单（指纹落库）

        # 审批创建后、批准唤醒前，入参被篡改（跨工作根）
        params["file_path"] = str(tmp_path / "outside" / "evil.txt")
        fut.set_result("approved")
        outcome = await task

        assert outcome is not None, "复验不一致必须拦下，不得放行执行"
        assert outcome.get("pending_approval") is True, outcome
        assert outcome.get("error_code") == "FINAL_DISPATCH_RECHECK_FAILED", outcome
        assert not (tmp_path / "outside" / "evil.txt").exists()

    @pytest.mark.asyncio
    async def test_sshTamperedHostWithoutCredentialsBounces(
        self, monkeypatch, tmp_path, approvalQueueIsolated
    ):
        """ssh 复验：篡改后的目标 host 在凭据桶无条目 → 转回审批队列。"""
        executor = _makeExecutor(monkeypatch, workspace_root=tmp_path / "ws")

        async def _none(tool_name, params):
            return None

        approvedParams = {"host": "good.example", "command": "ls", "user": "ops"}
        approval_id = executor._create_approval_request(
            "computer_ssh_exec", approvedParams, _askVerdict())
        assert approvalQueueIsolated.approve_request(approval_id, approved_by="tester")

        import neurova.computer_use.ssh_runner as ssh_runner

        monkeypatch.setattr(
            ssh_runner, "resolve_ssh_credentials",
            lambda user_id, host: {"user": "ops", "port": 22, "key_text": "k", "password": None}
            if host == "good.example" else {},
        )

        tampered = {"host": "evil.example", "command": "ls", "user": "ops"}
        result = await executor._execute_single_tool(
            "computer_ssh_exec", tampered, skip_governance=True)
        assert result.get("pending_approval") is True, result
        assert result.get("error_code") == "FINAL_DISPATCH_RECHECK_FAILED", result

    @pytest.mark.asyncio
    async def test_execCommandNotWhitelistedWithoutApprovalBounces(
        self, monkeypatch, tmp_path, approvalQueueIsolated
    ):
        """exec 复验（无批准记录的严格档）：命令首段不过白名单 → 拒绝执行并转审批。"""
        executor = _makeExecutor(monkeypatch, workspace_root=tmp_path / "ws")
        result = await executor._execute_single_tool(
            "exec_command", {"command": "rm -rf /tmp/whatever"}, skip_governance=True)
        assert result.get("pending_approval") is True, result
        assert result.get("error_code") == "FINAL_DISPATCH_RECHECK_FAILED", result
