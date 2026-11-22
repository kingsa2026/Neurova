"""U6 动态干预审计注册表（D4 升级计划）。

契约：
- neurova/security/dynamic_interventions.py 声明式规则（工具名 + 参数谓词 + 干预动作）；
- 首批两条：file_delete/file_edit「永久删除」必问（L1）、
  computer_ssh_exec 目标 host 首次出现必问（与 U1 确认卡衔接）；
- ToolExecutor 在治理预检后查注册表，命中转审批链：
  命中产生待审批、批准才执行、全审计。

红（现网行为）：跨会话工作根的 file_delete 无需任何额外确认即执行。
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from neurova.security.dynamic_interventions import (
    DynamicInterventionRegistry,
    evaluateDynamicInterventions,
    getDynamicInterventionRegistry,
)
from neurova.security.ssh_host_store import SshHostStore
from neurova.tool_executor import ToolExecutor


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


@pytest.fixture
def approvalWaitOff(monkeypatch):
    monkeypatch.setenv("NEUROVA_APPROVAL_WAIT_SECONDS", "0")


class TestRegistryRules:
    def test_firstBatchRulesDeclared(self):
        registry = getDynamicInterventionRegistry()
        names = {rule.name for rule in registry.rules}
        assert {"file_permanent_delete", "ssh_host_first_seen"} <= names

    def test_fileDeleteAlwaysHits(self):
        hits = evaluateDynamicInterventions("file_delete", {"file_path": "/tmp/x"}, {})
        assert any(h["rule"] == "file_permanent_delete" for h in hits)
        assert hits[0]["action"] == "ask"
        assert hits[0]["level"] == "L1"

    def test_fileEditPermanentDeletionHits(self):
        """file_edit 的「永久删除」形态：new_str 为空 = 把匹配文本永久删掉。"""
        hits = evaluateDynamicInterventions(
            "file_edit", {"file_path": "/tmp/x", "old_str": "secret", "new_str": ""}, {})
        assert any(h["rule"] == "file_permanent_delete" for h in hits)

    def test_fileEditNormalEditDoesNotHit(self):
        hits = evaluateDynamicInterventions(
            "file_edit", {"file_path": "/tmp/x", "old_str": "a", "new_str": "b"}, {})
        assert hits == []

    def test_sshHostFirstSeenHits(self, tmp_path):
        store = SshHostStore(tmp_path)
        ctx = {"agent_id": "a1", "ssh_host_store": store}
        hits = evaluateDynamicInterventions(
            "computer_ssh_exec", {"host": "new-host.example", "command": "ls"}, ctx)
        assert any(h["rule"] == "ssh_host_first_seen" for h in hits)

    def test_sshHostAlreadyConfirmedDoesNotHit(self, tmp_path):
        store = SshHostStore(tmp_path)
        store.mark_confirmed("a1", "known.example", 22, "SHA256:abc")
        ctx = {"agent_id": "a1", "ssh_host_store": store}
        hits = evaluateDynamicInterventions(
            "computer_ssh_exec", {"host": "known.example", "command": "ls"}, ctx)
        assert hits == []

    def test_registryIsSingleton(self):
        assert getDynamicInterventionRegistry() is getDynamicInterventionRegistry()

    def test_registryRulesAreReadOnlyView(self):
        registry = DynamicInterventionRegistry()
        before = len(registry.rules)
        with pytest.raises(Exception):
            registry.rules.append(object())
        assert len(registry.rules) == before


class TestExecutorWiring:
    @pytest.mark.asyncio
    async def test_fileDeleteOutsideWorkspaceRequiresApproval(
        self, monkeypatch, tmp_path, approvalWaitOff
    ):
        """红：跨会话工作根的删除当前无需额外确认即执行；
        绿：命中注册表 → 产生待审批 + 审计，文件保持完好，批准后才执行。"""
        outside = tmp_path / "elsewhere"
        outside.mkdir(parents=True, exist_ok=True)
        doomed = outside / "doomed.txt"
        doomed.write_text("data", encoding="utf-8")

        executor = _makeExecutor(monkeypatch, workspace_root=tmp_path / "ws")
        auditCalls = []
        monkeypatch.setattr(
            executor, "_audit_governance",
            lambda tool_name, info, params: auditCalls.append((tool_name, info)),
        )

        params = {"file_path": str(doomed)}
        result = await executor.execute("file_delete", params)

        assert result.get("pending_approval") is True, f"现网行为（未审批即执行）: {result}"
        assert doomed.exists(), "未批准前文件必须完好"
        assert result.get("approval_id"), result
        # 全审计：治理审计 + 审批队列各有一条可查记录
        assert any(t == "file_delete" for t, _ in auditCalls)
        from neurova.tool_executor import _get_approval_manager

        pending = _get_approval_manager().get_pending_requests()
        assert any(
            r.metadata.get("tool_name") == "file_delete" and r.status.value == "pending"
            for r in pending
        ), "命中干预必须登记进审批队列"

        # 批准 → 带外重放执行 → 文件才被删除
        approval_id = result["approval_id"]
        assert _get_approval_manager().approve_request(approval_id, approved_by="tester")
        replayed = await executor._execute_single_tool("file_delete", params, skip_governance=True)
        assert replayed.get("success") is True, replayed
        assert not doomed.exists()

    @pytest.mark.asyncio
    async def test_fileEditPermanentDeletionRequiresApproval(
        self, monkeypatch, tmp_path, approvalWaitOff
    ):
        """file_edit「永久删除」形态同样必问。"""
        ws = tmp_path / "ws"
        ws.mkdir(parents=True, exist_ok=True)
        target = ws / "note.txt"
        target.write_text("keep this secret", encoding="utf-8")

        executor = _makeExecutor(monkeypatch, workspace_root=ws)
        result = await executor.execute(
            "file_edit", {"file_path": str(target), "old_str": "secret", "new_str": ""})

        assert result.get("pending_approval") is True, result
        assert "secret" in target.read_text(encoding="utf-8"), "未批准前内容不得被删"

    @pytest.mark.asyncio
    async def test_sshFirstSeenHostRoutesToApproval(
        self, monkeypatch, tmp_path, approvalWaitOff
    ):
        """ssh 目标 host 首次出现必问（与 U1 确认卡衔接：授权在人，密码学确认在卡）。"""
        executor = _makeExecutor(monkeypatch, workspace_root=tmp_path / "ws")
        params = {"host": "first-seen.example", "command": "ls", "user": "ops"}
        result = await executor.execute("computer_ssh_exec", params)
        assert result.get("pending_approval") is True, result
        assert result.get("approval_id"), result

    @pytest.mark.asyncio
    async def test_nonTargetToolPassesThrough(self, monkeypatch, tmp_path, approvalWaitOff):
        """注册表未命中的工具照常执行（首批规则不扩大打击面）。"""
        executor = _makeExecutor(monkeypatch, workspace_root=tmp_path / "ws")
        result = await executor.execute("calculator", {"expression": "1+1"})
        assert result.get("result") == 2, result
