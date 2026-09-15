"""P0-1 技能质量漏斗

契约：
- selections   = LLM 调用技能、通过治理预检进入技能派发（execute_skill_tool）
- applications = 技能实际进入执行（registry.execute_skill 被调到）
- completions  = applied ∧ 执行成功 ∧ 本轮任务完成
- fallbacks    = applied ∧ ¬completions——**技能执行失败但本轮靠其它工具
  "兜底完成不得给技能记功"）

数据流：tool_executor.execute_skill_tool 写轮次账本（turn_context ContextVar，
P0-B1 并发契约）→ PostChatPipeline 回合收尾读账本+任务完成口径 → SkillService
record_skill_funnel 写穿 manifest usage（与 C11 use_count 同层，不替代）。
"""

import json

import pytest

from neurova.core import turn_context
from neurova.skills.skill_service import SkillService, compute_skill_funnel_update


# ── 纯归因函数：compute_skill_funnel_update ──────────────────


def test_funnel_completed():
    """执行成功且任务完成 → completion。"""
    entries = [{"skill_id": "s1", "applied": True, "ok": True, "pool": "agent", "owner_key": ""}]
    updates = compute_skill_funnel_update(entries, task_completed=True)
    assert updates == {
        "s1": {"selections": 1, "applications": 1, "completions": 1, "fallbacks": 0}
    }


def test_funnel_fallback_recovery_gets_no_credit():
    """归因防污染核心：技能执行失败，本轮靠兜底完成 → fallbacks，不是 completions。"""
    entries = [{"skill_id": "s1", "applied": True, "ok": False, "pool": "agent", "owner_key": ""}]
    updates = compute_skill_funnel_update(entries, task_completed=True)
    u = updates["s1"]
    assert u["completions"] == 0
    assert u["fallbacks"] == 1
    assert u["applications"] == 1


def test_funnel_task_incomplete_no_credit():
    """技能执行成功但任务未完成 → 不得记 completion。"""
    entries = [{"skill_id": "s1", "applied": True, "ok": True, "pool": "agent", "owner_key": ""}]
    updates = compute_skill_funnel_update(entries, task_completed=False)
    assert updates["s1"]["completions"] == 0
    assert updates["s1"]["fallbacks"] == 1


def test_funnel_unapplied_selection_only():
    """选中但未执行（查无此技能/未初始化）→ 只计 selection。"""
    entries = [{"skill_id": "s1", "applied": False, "ok": False}]
    updates = compute_skill_funnel_update(entries, task_completed=True)
    assert updates["s1"] == {
        "selections": 1, "applications": 0, "completions": 0, "fallbacks": 0
    }


def test_funnel_aggregates_same_skill():
    """同一技能多条目聚合计数。"""
    entries = [
        {"skill_id": "s1", "applied": True, "ok": True, "pool": "agent", "owner_key": ""},
        {"skill_id": "s1", "applied": True, "ok": False, "pool": "agent", "owner_key": ""},
        {"skill_id": "s2", "applied": False, "ok": False},
        {"skill_id": "", "applied": True, "ok": True},  # 无身份丢弃
    ]
    updates = compute_skill_funnel_update(entries, task_completed=True)
    assert updates["s1"] == {
        "selections": 2, "applications": 2, "completions": 1, "fallbacks": 1
    }
    assert updates["s2"]["selections"] == 1
    assert "" not in updates


def test_funnel_empty_entries():
    assert compute_skill_funnel_update([], task_completed=True) == {}
    assert compute_skill_funnel_update(None, task_completed=True) == {}


# ── SkillService 落盘：record_skill_funnel / get_skill_usage ──


@pytest.fixture
def svc(tmp_path):
    skills_dir = tmp_path / "skills"
    service = SkillService(agent_id="t", skills_dir=str(skills_dir))
    service.register_auto_skill("deploy_helper", name="deploy_helper", description="d")
    return service, skills_dir


def test_record_funnel_persists_to_manifest(svc):
    service, skills_dir = svc
    assert service.record_skill_funnel(
        "deploy_helper", selections=1, applications=1, completions=1
    )
    manifest = json.loads((skills_dir / "manifest.json").read_text(encoding="utf-8"))
    usage = manifest["deploy_helper"]["usage"]
    assert usage["selections"] == 1
    assert usage["applications"] == 1
    assert usage["completions"] == 1
    assert usage["fallbacks"] == 0


def test_record_funnel_accumulates(svc):
    service, _ = svc
    service.record_skill_funnel("deploy_helper", selections=2, applications=2, completions=1, fallbacks=1)
    service.record_skill_funnel("deploy_helper", selections=1, applications=1, fallbacks=1)
    usage = service.get_skill_usage("deploy_helper")
    assert usage["selections"] == 3
    assert usage["applications"] == 3
    assert usage["completions"] == 1
    assert usage["fallbacks"] == 2


def test_record_funnel_unknown_skill_returns_false(svc):
    service, _ = svc
    assert service.record_skill_funnel("nope", selections=1) is False


def test_record_funnel_clamps_negative_and_garbage(svc):
    service, _ = svc
    service.record_skill_funnel("deploy_helper", selections=-5, applications="x", completions=1)
    usage = service.get_skill_usage("deploy_helper")
    assert usage["selections"] == 0
    assert usage["applications"] == 0


def test_get_skill_usage_backcompat_and_rates(svc):
    """存量消费面（use_count 等键）不破坏；新键 + 派生率增量出现。"""
    service, _ = svc
    service.record_skill_usage("deploy_helper", success=True)  # C11 存量通道
    service.record_skill_funnel("deploy_helper", selections=2, applications=2, completions=1, fallbacks=1)
    usage = service.get_skill_usage("deploy_helper")
    # 存量键保持
    assert usage["use_count"] == 1
    assert "success_count" in usage and "last_used_at_ms" in usage
    # 漏斗派生率
    assert usage["applied_rate"] == 1.0
    assert usage["completion_rate"] == 0.5
    assert usage["fallback_rate"] == 0.5
    assert usage["effective_rate"] == 0.5


def test_get_skill_usage_zero_division_safe():
    class _Empty:
        pass

    service = SkillService.__new__(SkillService)
    service._skills = {}
    usage = service.get_skill_usage("ghost")
    assert usage["completions"] == 0
    assert usage["applied_rate"] == 0.0
    assert usage["completion_rate"] == 0.0


# ── 轮次账本：turn_context ──────────────────────────────────


def test_turn_funnel_record_and_snapshot():
    turn_context.reset_turn_tool_messages()  # 轮次起点：账本与工具消息一并重置
    turn_context.record_turn_skill_funnel("s1", applied=True, ok=True)
    turn_context.record_turn_skill_funnel("s1", applied=True, ok=False)
    snap = turn_context.get_turn_skill_funnel()
    assert snap == [
        {"skill_id": "s1", "applied": True, "ok": True, "pool": "agent", "owner_key": ""},
        {"skill_id": "s1", "applied": True, "ok": False, "pool": "agent", "owner_key": ""},
    ]
    # 快照是副本，改不污染
    snap.clear()
    assert len(turn_context.get_turn_skill_funnel()) == 2
    turn_context.reset_turn_tool_messages()
    assert turn_context.get_turn_skill_funnel() == []


# ── 采集点：tool_executor.execute_skill_tool ────────────────


def _make_registry(skill_obj=None):
    """最小注册表替身：skills dict + AsyncMock execute_skill。"""
    from unittest.mock import AsyncMock, MagicMock

    registry = MagicMock()
    registry.skills = {} if skill_obj is None else {"deploy_helper": skill_obj}
    registry.execute_skill = AsyncMock()
    return registry


def _make_skill():
    from neurova.skills.models import Skill, SkillSource

    return Skill(
        id="deploy_helper",
        name="deploy_helper",
        version="1.0.0",
        description="d",
        source=SkillSource.LOCAL,
        enabled=True,
        config={},
    )


@pytest.fixture(autouse=True)
def _clean_turn():
    turn_context.reset_turn_tool_messages()
    yield
    turn_context.reset_turn_tool_messages()


@pytest.mark.asyncio
async def test_execute_skill_records_applied_success():
    from unittest.mock import MagicMock

    from neurova.skill_system import SkillResult
    from neurova.tool_executor import ToolExecutor

    registry = _make_registry(_make_skill())
    registry.execute_skill.return_value = SkillResult(success=True, output="ok")
    agent = MagicMock()
    agent._skill_registry = registry

    executor = ToolExecutor(agent)
    result = await executor.execute_skill_tool("deploy_helper", {})
    assert result.get("success") is True

    entries = turn_context.get_turn_skill_funnel()
    assert entries == [{"skill_id": "deploy_helper", "applied": True, "ok": True, "pool": "agent", "owner_key": ""}]


@pytest.mark.asyncio
async def test_execute_skill_records_applied_failure():
    from unittest.mock import MagicMock

    from neurova.skill_system import SkillResult
    from neurova.tool_executor import ToolExecutor

    registry = _make_registry(_make_skill())
    registry.execute_skill.return_value = SkillResult(success=False, error="boom")
    agent = MagicMock()
    agent._skill_registry = registry

    executor = ToolExecutor(agent)
    await executor.execute_skill_tool("deploy_helper", {})

    entries = turn_context.get_turn_skill_funnel()
    assert entries == [{"skill_id": "deploy_helper", "applied": True, "ok": False, "pool": "agent", "owner_key": ""}]


@pytest.mark.asyncio
async def test_execute_skill_records_selection_without_apply():
    """技能查不到：有 selection 无 application（漏斗两阶段可分）。"""
    from unittest.mock import MagicMock

    from neurova.tool_executor import ToolExecutor

    registry = _make_registry(None)
    agent = MagicMock()
    agent._skill_registry = registry

    executor = ToolExecutor(agent)
    result = await executor.execute_skill_tool("deploy_helper", {})
    assert "error" in result

    entries = turn_context.get_turn_skill_funnel()
    assert entries == [{"skill_id": "deploy_helper", "applied": False, "ok": False, "pool": "agent", "owner_key": ""}]


@pytest.mark.asyncio
async def test_execute_skill_exception_records_applied_failure():
    """执行期异常（ValueError 未注册等）：已尝试执行 → applied, ok=False。"""
    from unittest.mock import MagicMock

    from neurova.tool_executor import ToolExecutor

    registry = _make_registry(_make_skill())
    registry.execute_skill.side_effect = RuntimeError("crash")
    agent = MagicMock()
    agent._skill_registry = registry

    executor = ToolExecutor(agent)
    await executor.execute_skill_tool("deploy_helper", {})

    entries = turn_context.get_turn_skill_funnel()
    assert entries == [{"skill_id": "deploy_helper", "applied": True, "ok": False, "pool": "agent", "owner_key": ""}]


@pytest.mark.asyncio
async def test_no_registry_records_nothing():
    from unittest.mock import MagicMock

    from neurova.tool_executor import ToolExecutor

    agent = MagicMock()
    agent._skill_registry = None
    executor = ToolExecutor(agent)
    await executor.execute_skill_tool("deploy_helper", {})
    assert turn_context.get_turn_skill_funnel() == []


# ── 回写点：PostChatPipeline flush step ─────────────────────


@pytest.mark.asyncio
async def test_post_chat_flush_writes_funnel_to_manifest(tmp_path, monkeypatch):
    """账本+回合完成 → manifest 漏斗键落盘（走 SkillService 真实实现，目录指 tmp）。"""
    from unittest.mock import MagicMock

    import neurova.skills.skill_service as skill_service_mod
    from neurova.post_chat_pipeline import PostChatPipeline

    # 隔离落盘目录：测试绝不写 data/ 真库（EKB 3920 事故教训）
    real_cls = skill_service_mod.SkillService

    class _TmpService(real_cls):
        def __init__(self, agent_id, skills_dir=None):
            super().__init__(agent_id=agent_id, skills_dir=str(tmp_path / "skills"))

    monkeypatch.setattr(skill_service_mod, "SkillService", _TmpService)
    _TmpService(agent_id="funnel-agent").register_auto_skill(
        "deploy_helper", name="deploy_helper", description="d"
    )

    turn_context.record_turn_skill_funnel("deploy_helper", applied=True, ok=True)
    turn_context.record_turn_skill_funnel("deploy_helper", applied=True, ok=False)

    agent = MagicMock()
    agent.config.agent_id = "funnel-agent"
    pipeline = PostChatPipeline(agent)
    await pipeline._step_skill_funnel_flush("本轮回复正常完成")

    manifest = json.loads((tmp_path / "skills" / "manifest.json").read_text(encoding="utf-8"))
    usage = manifest["deploy_helper"]["usage"]
    assert usage["selections"] == 2
    assert usage["applications"] == 2
    # 一成一败：completion 只记 1，失败的不得记功
    assert usage["completions"] == 1
    assert usage["fallbacks"] == 1


@pytest.mark.asyncio
async def test_post_chat_flush_empty_reply_no_completion(tmp_path, monkeypatch):
    """回合未完成（空回复）：成功的执行也不得记 completion。"""
    from unittest.mock import MagicMock

    import neurova.skills.skill_service as skill_service_mod
    from neurova.post_chat_pipeline import PostChatPipeline

    real_cls = skill_service_mod.SkillService

    class _TmpService(real_cls):
        def __init__(self, agent_id, skills_dir=None):
            super().__init__(agent_id=agent_id, skills_dir=str(tmp_path / "skills"))

    monkeypatch.setattr(skill_service_mod, "SkillService", _TmpService)
    _TmpService(agent_id="funnel-agent").register_auto_skill(
        "deploy_helper", name="deploy_helper", description="d"
    )

    turn_context.record_turn_skill_funnel("deploy_helper", applied=True, ok=True)

    agent = MagicMock()
    agent.config.agent_id = "funnel-agent"
    pipeline = PostChatPipeline(agent)
    await pipeline._step_skill_funnel_flush("   ")

    usage = json.loads((tmp_path / "skills" / "manifest.json").read_text(encoding="utf-8"))[
        "deploy_helper"
    ]["usage"]
    assert usage["completions"] == 0
    assert usage["fallbacks"] == 1


@pytest.mark.asyncio
async def test_post_chat_flush_noop_without_entries(tmp_path, monkeypatch):
    """无账本条目时不得触碰 SkillService（普通对话轮零开销）。"""
    from unittest.mock import MagicMock

    import neurova.skills.skill_service as skill_service_mod
    from neurova.post_chat_pipeline import PostChatPipeline

    calls = []
    real_cls = skill_service_mod.SkillService

    class _Spy(real_cls):
        def __init__(self, *a, **k):
            calls.append(a)
            super().__init__(*a, skills_dir=str(tmp_path / "skills"))

    monkeypatch.setattr(skill_service_mod, "SkillService", _Spy)
    agent = MagicMock()
    agent.config.agent_id = "x"
    pipeline = PostChatPipeline(agent)
    await pipeline._step_skill_funnel_flush("reply")
    assert calls == []
