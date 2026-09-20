"""改进的最后一米：生效、可观测、跨重启（工单 016）。

三处断点各有一组用例：

**a 队列静默丢**：评审闸默认开 ⇒ `record_experience(source=improver/attribution)`
的产物一律进 `_pending_records`，队列有界 50，**溢出直接截断不留痕**。
后果不只是"改进没回流"，是"回流了多少、丢了多少"这件事不可观测。

**b 写了没人读**：`apply_improvement` 往 `skill.config["improvements"]` 追加记录，
全仓无读取方。行为面已经由经验库（组合进描述）承载，第二条注入口只会造出两套口径。

**附带修正**：`_step_rsi_iteration` 调 `run_skill_experience_maintenance` 时不传
`agent_id`，于是归因按 `"default"` 查台账，而同函数取 ledger 用的是真实 agent ——
`MetaLedger.list_records` 是 `WHERE agent_id=?`，非默认 agent 归因恒 0。
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from neurova.evolution.skill_experience import SkillExperienceStore
from neurova.evolution.skill_improver import ImprovementType, SkillImprovement
from neurova.post_chat_pipeline import PostChatPipeline
from neurova.skill_system import Skill, SkillRegistry

IMPROVER = Path("neurova/evolution/skill_improver.py")

SEQ = ["read_file", "write_file"]
PURPOSE = "读改写同一文件"


class _EchoSkillForRestart(Skill):
    """可注册的最小技能：改进只需 name/config 两项。"""

    def __init__(self, name: str):
        super().__init__(name, "读写组合")
        self.config = {"tool_sequence": list(SEQ)}
        self.version = "1.0.0"

    async def execute(self, params, context=None):  # pragma: no cover - 不进执行链
        raise NotImplementedError


# ────── 附带修正：归因按真实 agent 建账 ──────


@pytest.fixture(autouse=True)
def _isolated_step_results_ctx():
    """`_step_results` 是 ContextVar，set/reset 必须成对，否则泄漏给同 worker 后续用例。"""
    token = PostChatPipeline._step_results_ctx.set([])
    yield
    PostChatPipeline._step_results_ctx.reset(token)


def _make_pipe(agent_id: str):
    pipe = PostChatPipeline.__new__(PostChatPipeline)
    pipe._agent = SimpleNamespace(
        config=SimpleNamespace(agent_id=agent_id),
        turn_count=1,
        _skill_registry=None,
    )
    pipe._get_dependency = lambda name: None
    return pipe


@pytest.mark.asyncio
async def test_maintenance_call_threads_agent_id(monkeypatch):
    """归因调用必须带真实 agent_id（当前必红：恒按 "default" 查台账）。"""
    import neurova.post_chat_pipeline as pcp

    async def _no_improvement_pass(**kwargs):
        return None

    monkeypatch.setattr(pcp, "run_skill_evolution_pass", _no_improvement_pass)
    captured: dict = {}

    def _spy(**kwargs):
        captured.update(kwargs)
        return {"attributed": [], "rebuilt": [], "retired": [], "retire_candidates": []}

    import neurova.evolution.skill_experience as exp_mod

    monkeypatch.setattr(exp_mod, "run_skill_experience_maintenance", _spy)

    pipe = _make_pipe("kai")
    await pipe._step_rsi_iteration()

    assert captured.get("agent_id") == "kai", (
        f"归因未带 agent_id ⇒ MetaLedger 按 'default' 过滤，多 agent 下归因恒 0；实得 {captured}")


# ────── a · pending 队列溢出必须可观测 ──────


def _flood(store: SkillExperienceStore, count: int) -> None:
    for i in range(count):
        store.record_experience(f"skill_{i}", f"指引 {i}", source="improver")


def test_pending_overflow_is_counted(monkeypatch):
    """溢出不得静默丢：丢掉的条数必须留在台账上（当前必红：无此计数）。"""
    monkeypatch.setenv("NEUROVA_SKILL_REVIEW_GATE", "1")
    store = SkillExperienceStore()
    _flood(store, 60)

    assert len(store._pending_records) == 50
    assert store.pending_dropped == 10, (
        f"60 条进队、队列上限 50 ⇒ 应记 10 条丢失，实得 {getattr(store, 'pending_dropped', '无此计数')}")


def test_pending_pressure_verdict_is_three_state(monkeypatch):
    """生效判据走 GateVerdict：没测过就不能报"通过"。"""
    monkeypatch.setenv("NEUROVA_SKILL_REVIEW_GATE", "1")
    from neurova.evolution.rsi.gate_verdict import GateVerdict

    fresh = SkillExperienceStore()
    assert fresh.pending_pressure_verdict().state == GateVerdict.STATE_UNEVIDENCED, (
        "从未有 pending 写入时不得报「队列无压力」")

    ok = SkillExperienceStore()
    _flood(ok, 5)
    assert ok.pending_pressure_verdict().state == GateVerdict.STATE_PASSED

    flooded = SkillExperienceStore()
    _flood(flooded, 60)
    verdict = flooded.pending_pressure_verdict()
    assert verdict.state == GateVerdict.STATE_FAILED
    assert bool(verdict) is False


def test_rsi_status_exposes_pending_channel_pressure(monkeypatch):
    """溢出必须进告警面：`/rsi/status` 读得到回流通道判据（当前必红：状态面无此项）。"""
    from neurova.evolution.rsi.gate_verdict import GateVerdict
    from neurova.evolution.rsi.orchestrator import RSIOrchestrator

    store = SkillExperienceStore()
    monkeypatch.setattr(
        "neurova.evolution.skill_experience.get_skill_experience_store", lambda **k: store
    )
    orchestrator = RSIOrchestrator(
        sleep_system=SimpleNamespace(),
        emotion_system=SimpleNamespace(),
        experience_system=SimpleNamespace(),
        tool_memory_system=SimpleNamespace(),
    )

    assert orchestrator.get_status()["experience_channel"]["state"] == GateVerdict.STATE_UNEVIDENCED

    _flood(store, 60)
    status = orchestrator.get_status()["experience_channel"]
    assert status["state"] == GateVerdict.STATE_FAILED
    assert status["evidence"]["dropped"] == 10


# ────── b · improvements 不得"写了没人读" ──────

def test_improvements_key_is_not_written_without_a_reader():
    """票面二选一：本单选"删除该写入"（行为面已由经验注入口承载）。

    只扫 AST 不扫原文 —— 解释这段历史的注释里必然出现键名，按原文匹配会
    把"写下原因"当成"仍在写数据"。
    """
    tree = ast.parse(IMPROVER.read_text(encoding="utf-8"))
    written = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "setdefault"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            written.add(node.args[0].value)
        elif (
            isinstance(node, ast.Assign)
            and isinstance(node.targets[0], ast.Subscript)
            and isinstance(node.targets[0].slice, ast.Constant)
            and isinstance(node.targets[0].slice.value, str)
        ):
            written.add(node.targets[0].slice.value)
    assert "improvements" not in written, (
        'skill_improver 仍在写 config["improvements"] —— 全仓无读取方 ⇒ 第三态（写了没人读）')
    assert "revisions" in written, "改进留痕必须有落点，revisions 是它的唯一一份"


# ────── 开闸覆盖（票面要求：关闸用例不得成为唯一覆盖）──────


def test_gate_open_record_goes_to_pending_not_straight_to_effect(monkeypatch):
    """评审闸开（默认）时，improver 来源的记录先进待审而非直接生效。"""
    monkeypatch.setenv("NEUROVA_SKILL_REVIEW_GATE", "1")
    store = SkillExperienceStore()
    store.record_experience("skill_gate_open", "先探后写", source="improver")

    assert store.get_records("skill_gate_open") == []
    assert len(store._pending_records) == 1


# ────── c · 改进史跨重启存活 ──────


def _restart_improver(tmp_path, monkeypatch):
    """挂载 → 走一轮真实扫描与改进 → 模拟重启 → 返回新实例与注册表。

    改进史按生产路径造：10 条使用记录（6 失败含 timeout）→ `propose_improvements`
    → `apply_improvement`。手工往 `_improvements` 里塞东西只能证明"序列化对上了"，
    证不了这条链真的跨重启接着算。
    """
    from neurova.evolution import closed_loop
    from neurova.evolution.skill_improver import get_skill_improver, reset_skill_improver

    monkeypatch.setenv("NEUROVA_EVOLUTION_IMPROVEMENTS", str(tmp_path / "skill_improvements.json"))
    reset_skill_improver()
    closed_loop.bootstrap_evolution_persistence(tmp_path / "tool_weights.json")

    registry = SkillRegistry()
    registry.register(_EchoSkillForRestart("sk_a"))
    improver = get_skill_improver()
    for i in range(6):
        improver.record_usage("sk_a", success=False, error_message="timeout 超时", duration=2.0)
    for _ in range(4):
        improver.record_usage("sk_a", success=True, duration=1.5)
    proposals = improver.propose_improvements("sk_a")
    assert proposals, "扫描未产出提案，本用例的前提（走生产路径）不成立"
    improver.create_variant("sk_a", "var_a_1", {"timeout": 10})
    assert improver.apply_improvement(proposals[0], registry) is True
    assert improver.save() is True, "改进史未挂载持久化（bootstrap 只挂五件）"

    reset_skill_improver()
    closed_loop.bootstrap_evolution_persistence(tmp_path / "tool_weights.json")
    return get_skill_improver(), registry


def test_improvement_history_survives_restart(tmp_path, monkeypatch):
    """使用记录 / 改进史 / 变体三样都必须跨重启回来（当前必红：重启归零）。"""
    restarted, _registry = _restart_improver(tmp_path, monkeypatch)

    assert len(restarted.get_usage_history("sk_a")) == 10, (
        "使用记录重启即清 ⇒ propose_improvements 的分母永远从 0 开始")
    assert restarted.get_variant_comparison("sk_a")["variants"], "变体台账重启即清"
    assert len(restarted.get_improvement_history("sk_a")) == 1


def test_applied_signature_dedupe_survives_restart(tmp_path, monkeypatch):
    """同签名去重集必须跨重启存活，否则重启后第一轮就把同一改进再应用一次（版本再 +1）。"""
    restarted, registry = _restart_improver(tmp_path, monkeypatch)
    applied = restarted.get_improvement_history("sk_a")[0]
    same_signature = SkillImprovement(
        improvement_id="imp_resubmitted",
        skill_id="sk_a",
        improvement_type=applied.improvement_type,
        changes=dict(applied.changes),
    )

    assert restarted.apply_improvement(same_signature, registry) is False, (
        "重启后同签名提案被再次应用 ⇒ 版本号每重启一轮再涨，改进史自我膨胀")
    assert registry.get_skill("sk_a").version == "1.0.1", "版本应只涨一次"


def test_approved_skill_survives_restart_and_stays_usable(tmp_path):
    """人工批准的自动技能必须"重启后还在、还能用、不再回待审"。

    实测两跳都断：
    1. `register_to_skill_registry` 走 `create_automatic_skill`，那里的 `enabled`
       只看"source 是自动产物且评审闸开"——不看模板是否已被人批准 ⇒ 落盘即
       enabled=False，下一轮对话用不到刚批准的技能；
    2. 重启后 builder 只从 manifest 认领 `builder_pending` 条目 ⇒ 已批准那条不在
       `_templates` 里，同一模式再被观察到就重封一条待审的（人工批准被撤销）。
    """
    from neurova.evolution.skill_encapsulation import AutoSkillBuilder
    from neurova.skills.skill_service import SkillService

    def _builder():
        service = SkillService(agent_id="restart-probe", skills_dir=str(tmp_path))
        return AutoSkillBuilder(
            min_pattern_occurrences=3,
            min_success_rate=0.7,
            evidence_store=service.creation_evidence,
        ), service

    builder, service = _builder()
    for task_id in ("t1", "t2", "t3"):
        service.creation_evidence.record(task_id, SEQ, PURPOSE, True)
        builder.observe(SEQ, PURPOSE, True, 0.5, {"source_key": task_id})
    template_id = next(iter(builder._templates))
    assert builder.approve_template(template_id) is True
    builder.register_to_skill_registry(SkillRegistry(), skill_service=service)

    assert service.get_skill_info(template_id)["enabled"] is True, (
        "已批准的自动技能落盘即 enabled=False ⇒ 批准没走到「下一轮真的用它」")

    # 模拟重启：新 service + 新 builder，再喂两条新证据观察同一模式
    for task_id in ("t4", "t5"):
        service.creation_evidence.record(task_id, SEQ, PURPOSE, True)
    restarted, _svc2 = _builder()
    for task_id in ("t4", "t5"):
        restarted.observe(SEQ, PURPOSE, True, 0.5, {"source_key": task_id})

    assert restarted.list_pending_templates() == [], (
        f"已批准的自动技能重启后又进待审：{restarted.list_pending_templates()}")
