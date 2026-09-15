"""P0-2 信任生命周期两态

契约：
- 进化产物出生 provisional（register_auto_skill）；导入/安装/用户技能默认 trusted
- 可归因失败即刻降级 provisional 并清零晋升计数
- 晋升需 ≥2 个**独立任务**观测成功（同一 task_id 去重，一票制）
- 与 active→stale→archived 时间轴正交（trust 只进 usage.trust，不触 state）
"""

import json

import pytest

from neurova.core import turn_context
from neurova.skills.skill_service import (
    SkillService,
    compute_trust_observations,
    compute_trust_transition,
)


# ── 纯状态迁移 ──────────────────────────────────────────────


def test_transition_failure_demotes_immediately():
    state, count = compute_trust_transition("trusted", "failure", 5)
    assert state == "provisional"
    assert count == 0


def test_transition_needs_two_independent_successes():
    state, count = compute_trust_transition("provisional", "success", 0)
    assert (state, count) == ("provisional", 1)
    state, count = compute_trust_transition("provisional", "success", 1)
    assert state == "trusted"
    assert count == 0  # 晋升后计数清零


def test_transition_trusted_stays_on_success():
    assert compute_trust_transition("trusted", "success", 0) == ("trusted", 0)


def test_transition_no_observation_no_change():
    assert compute_trust_transition("provisional", "", 1) == ("provisional", 1)


def test_transition_min_successes_one():
    state, _ = compute_trust_transition("provisional", "success", 0, min_successes=1)
    assert state == "trusted"


# ── 回合观测归因（从 P0-1 派发账本派生）─────────────────────


def test_observation_success():
    entries = [{"skill_id": "s1", "applied": True, "ok": True}]
    assert compute_trust_observations(entries, True) == {"s1": "success"}


def test_observation_failure_beats_success_same_turn():
    """同回合混合成败 → 保守记 failure（晋升证据必须干净，不给混合轮记功）"""
    entries = [
        {"skill_id": "s1", "applied": True, "ok": True},
        {"skill_id": "s1", "applied": True, "ok": False},
    ]
    assert compute_trust_observations(entries, True) == {"s1": "failure"}


def test_observation_success_but_task_incomplete_is_failure():
    entries = [{"skill_id": "s1", "applied": True, "ok": True}]
    assert compute_trust_observations(entries, False) == {"s1": "failure"}


def test_observation_selection_only_no_vote():
    entries = [{"skill_id": "s1", "applied": False, "ok": False}]
    assert compute_trust_observations(entries, True) == {}


# ── 服务层：出生态 / 落盘 / 去重 ────────────────────────────


@pytest.fixture
def svc(tmp_path):
    service = SkillService(agent_id="trust-t", skills_dir=str(tmp_path / "skills"))
    return service, tmp_path / "skills" / "manifest.json"


def test_auto_skill_born_provisional(svc):
    service, _ = svc
    service.register_auto_skill("auto1", name="auto1")
    assert service.get_skill_usage("auto1")["trust_state"] == "provisional"


def test_imported_skill_defaults_trusted(svc):
    """存量/导入技能无 trust 记录 → 视为 trusted"""
    service, manifest = svc
    src = manifest.parent.parent / "imp1"
    src.mkdir(parents=True, exist_ok=True)
    (src / "manifest.json").write_text(
        json.dumps({"id": "imp1", "name": "imp1", "version": "1.0.0"}), encoding="utf-8"
    )
    service.install_skill(str(src), skill_id="imp1")
    usage = service.get_skill_usage("imp1")
    assert usage["trust_state"] == "trusted"


def test_promotion_after_two_independent_successes(svc):
    service, _ = svc
    service.register_auto_skill("auto1", name="auto1")
    service.record_trust_observation("auto1", "success", task_id="t1")
    assert service.get_skill_usage("auto1")["trust_state"] == "provisional"
    ok = service.record_trust_observation("auto1", "success", task_id="t2")
    assert ok is True
    usage = service.get_skill_usage("auto1")
    assert usage["trust_state"] == "trusted"
    assert usage["trust_transitions"][-1]["event"] == "trust_promoted"


def test_same_task_observation_deduped(svc):
    """一票制：同一 task_id 重复上报不得重复计数晋升"""
    service, _ = svc
    service.register_auto_skill("auto1", name="auto1")
    service.record_trust_observation("auto1", "success", task_id="t1")
    service.record_trust_observation("auto1", "success", task_id="t1")
    assert service.get_skill_usage("auto1")["trust_state"] == "provisional"


def test_failure_demotes_and_resets(svc):
    service, _ = svc
    service.register_auto_skill("auto1", name="auto1")
    service.record_trust_observation("auto1", "success", task_id="t1")
    service.record_trust_observation("auto1", "success", task_id="t2")
    assert service.get_skill_usage("auto1")["trust_state"] == "trusted"
    service.record_trust_observation("auto1", "failure", task_id="t3")
    usage = service.get_skill_usage("auto1")
    assert usage["trust_state"] == "provisional"
    assert usage["trust_transitions"][-1]["event"] == "trust_demoted"
    # 降级后须再攒 2 次独立成功
    service.record_trust_observation("auto1", "success", task_id="t4")
    assert service.get_skill_usage("auto1")["trust_state"] == "provisional"


def test_trust_persisted_to_manifest(svc):
    service, manifest = svc
    service.register_auto_skill("auto1", name="auto1")
    service.record_trust_observation("auto1", "success", task_id="t1")
    raw = json.loads(manifest.read_text(encoding="utf-8"))
    assert raw["auto1"]["identity"]["trust"]["state"] == "provisional"
    assert raw["auto1"]["identity"]["trust"]["successes_since_failure"] == 1


def test_record_trust_unknown_skill(svc):
    service, _ = svc
    assert service.record_trust_observation("ghost", "success", task_id="t1") is False


def test_observed_task_ids_bounded(svc):
    service, _ = svc
    service.register_auto_skill("auto1", name="auto1")
    for i in range(30):
        service.record_trust_observation("auto1", "failure", task_id=f"t{i}")
    info = service.get_skill_info("auto1")
    assert len(info["identity"]["trust"]["observed_task_ids"]) <= 20


# ── post-chat flush 集成（账本 → 观测 → 落盘）───────────────


@pytest.mark.asyncio
async def test_flush_records_trust_with_task_identity(tmp_path, monkeypatch):
    """两次不同回合（session#turn 身份）成功 → 晋升 trusted。"""
    from unittest.mock import MagicMock

    import neurova.skills.skill_service as ss_mod
    from neurova.post_chat_pipeline import PostChatPipeline

    real_cls = ss_mod.SkillService

    class _TmpService(real_cls):
        def __init__(self, agent_id, skills_dir=None):
            super().__init__(agent_id=agent_id, skills_dir=str(tmp_path / "skills"))

    monkeypatch.setattr(ss_mod, "SkillService", _TmpService)
    _TmpService(agent_id="flush-t").register_auto_skill("auto1", name="auto1")

    agent = MagicMock()
    agent.config.agent_id = "flush-t"
    pipeline = PostChatPipeline(agent)

    for turn in range(2):
        turn_context.reset_turn_tool_messages()
        turn_context.set_turn_identity("输入", "sess-a")
        turn_context.increment_turn_count()
        turn_context.record_turn_skill_funnel("auto1", applied=True, ok=True)
        await pipeline._step_skill_funnel_flush("完成", actual_session_id="sess-a")

    raw = json.loads((tmp_path / "skills" / "manifest.json").read_text(encoding="utf-8"))
    assert raw["auto1"]["identity"]["trust"]["state"] == "trusted"
