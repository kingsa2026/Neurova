"""013 · 遗传臂吃真实成功率，注册门槛可证伪（红绿灯 TDD）。

根因：`PatternMiner.add_sequence` 根本不接收成败 —— `_sequences` 只存工具名列表，
于是 `FrequentPattern` 无从携带成功率，种子消费处
`getattr(pattern, "success_rate", None) or 0.5` 恒 0.5。而注册阈值是 0.8，
`fitness = success_rate × time_penalty + log1p(reuse)×0.1` 在默认零时延、零复用下
等于 success_rate ⇒ 新挖模式当轮必被跳过，只有同一条序列被 `record_reuse`
累计约 20 次后才可能跨过，而 base 仍是错的 0.5。

落定契约（票面 §涉及层 + 010 §给 013 留的接口）：

1. **每条序列带一个客观结果位**（True/False/None），来源是工单 010 的
   `TicketEvidence.ticket`（服务端票据的唯一读口）：有票用票，无票传 None；
   调用方禁止判空兜底、禁止默认 True。
2. **模式成功率 = 含该模式的序列的客观结果聚合** `wins/(wins+losses)`；
   没有任何客观结果 ⇒ None（无证据），既不是 0.5 也不是 0.0。三态口径与
   002/005 一致：无据不投票。
3. **无证据的模式不播种**：`or 0.5` 兜底删除后，None 一律跳过，并计入
   StepResult.data 的 seeded / skipped_unevidenced 以便观测。
4. **落盘 outcomes 与序列按位对齐**，沿用 contexts 的损坏容忍写法；
   旧状态文件没有 outcomes ⇒ restore 得到 None（不得补 False 也不得补 True）。
5. **注册门槛可证伪**：真实 ≥0.8 成功率在零复用时即可跨过阈值；
   0.2 的成功率需要 reuse≈e^6 才够，属真正不可达，必须断得出来。
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from neurova.evolution.closed_loop import EvolutionOrchestrator
from neurova.evolution.evolution_facade import EvolutionFacade
from neurova.evolution.genetic_engine import ToolGeneticEngine, ToolGenotype
from neurova.evolution.objective_evidence import (
    TICKET_ABSENT,
    TICKET_EVIDENCED,
    TicketEvidence,
)
from neurova.evolution.pattern_miner import PatternMiner
from neurova.evolution.rsi.gate_verdict import GateVerdict
from neurova.post_chat_pipeline import PostChatPipeline, StepStatus

ALPHA_BETA = ["alpha", "beta"]
GAMMA_DELTA = ["gamma", "delta"]
TASK = "把报告导出成 PDF"


@pytest.fixture(autouse=True)
def _isolated_step_results():
    """`_step_results` 是 ContextVar，同线程不自动隔离 —— 前后都给一个空列表。"""
    token = PostChatPipeline._step_results_ctx.set([])
    yield
    PostChatPipeline._step_results_ctx.reset(token)


def _feed(miner: PatternMiner, outcomes: List[Optional[bool]],
          tools: List[str] = ALPHA_BETA) -> None:
    """按客观结果位逐条喂序列（`None` = 本轮没有票据）。"""
    for outcome in outcomes:
        miner.add_sequence(list(tools), context=TASK, success=outcome)


def _pattern(patterns, tools: List[str]):
    """从两条出口（FrequentPattern 对象 / dict 契约）里取同一条模式。"""
    return next(
        (p for p in patterns
         if list(p["tools"] if isinstance(p, dict) else p.tools) == list(tools)),
        None)


def _rate(entry) -> Optional[float]:
    return entry["success_rate"] if isinstance(entry, dict) else entry.success_rate


# ────── 逻辑层：PatternMiner 的客观结果台账与成功率 ──────


class TestPatternSuccessRate:
    """模式成功率来自序列的客观结果聚合，不是常量。"""

    def test_nine_wins_one_loss_mine_yields_zero_nine(self):
        """票面验收一：9 成功 1 失败 ⇒ 0.9，而不是恒 0.5。"""
        miner = PatternMiner()
        _feed(miner, [True] * 9 + [False])

        pattern = _pattern(miner.mine(), ALPHA_BETA)

        assert pattern is not None, "模式未被挖掘，本用例不成立"
        assert pattern.success_rate == pytest.approx(0.9), (
            f"成功率没吃到真实成败：{pattern.success_rate}")

    def test_get_top_patterns_carries_the_same_rate(self):
        """第二条出口：get_top_patterns（内部惰性 mine）也必须带成功率。"""
        miner = PatternMiner()
        _feed(miner, [True] * 9 + [False])

        pattern = _pattern(miner.get_top_patterns(k=5), ALPHA_BETA)

        assert pattern.success_rate == pytest.approx(0.9), (
            f"get_top_patterns 丢了成功率：{pattern.success_rate}")

    def test_sequences_without_any_verdict_yield_none_not_half(self):
        """反向锁①：全无客观结果 ⇒ None（无证据），不得当成 0.5 播种。"""
        miner = PatternMiner()
        for _ in range(5):
            miner.add_sequence(list(ALPHA_BETA), context=TASK)

        pattern = _pattern(miner.mine(), ALPHA_BETA)

        assert pattern.success_rate is None, (
            f"无证据被当成有证据：{pattern.success_rate}")

    def test_all_failures_yield_zero_not_none(self):
        """反向锁②：有票但全输 ⇒ 0.0（确证失败），不得与"无证据"混成 None。"""
        miner = PatternMiner()
        _feed(miner, [False, False, False])

        assert _pattern(miner.mine(), ALPHA_BETA).success_rate == 0.0

    def test_unverdict_occurrences_stay_out_of_the_denominator(self):
        """None 既不投成功票也不进分母：5 胜 1 负 4 无票 ⇒ 5/6。"""
        miner = PatternMiner()
        _feed(miner, [True] * 5 + [False] + [None] * 4)

        assert _pattern(miner.mine(), ALPHA_BETA).success_rate == pytest.approx(5 / 6)

    def test_rate_aggregates_only_sequences_containing_the_pattern(self):
        """聚合域：只统计含该模式的序列，别的序列的失败不得摊进来。"""
        miner = PatternMiner()
        _feed(miner, [True, True, True, False])
        _feed(miner, [False, False, False, False], tools=GAMMA_DELTA)

        assert _pattern(miner.mine(), ALPHA_BETA).success_rate == pytest.approx(0.75)


class TestTemplateAndFacadeCarryRate:
    """dict 出口不得继续谎报满分（与 to_skill_template_list 的 `1.0` 同形缺陷）。"""

    def test_skill_template_export_reports_the_real_rate(self):
        miner = PatternMiner()
        _feed(miner, [True] * 9 + [False])

        templates = miner.to_skill_template_list()

        target = _pattern(templates, ALPHA_BETA)
        assert _rate(target) == pytest.approx(0.9), (
            f"导出的模板仍写死满分：{target['success_rate']}")

    def test_skill_template_export_reports_none_without_evidence(self):
        miner = PatternMiner()
        for _ in range(4):
            miner.add_sequence(list(ALPHA_BETA))

        target = _pattern(miner.to_skill_template_list(), ALPHA_BETA)

        assert _rate(target) is None

    def test_facade_frequent_patterns_expose_the_rate(self):
        """facade 的 dict 契约（{"tools","support","context","success_rate"}）带上成功率。"""
        miner = PatternMiner()
        _feed(miner, [True] * 9 + [False])
        orchestrator = EvolutionOrchestrator()
        orchestrator.pattern_miner = miner
        facade = EvolutionFacade(orchestrator)

        target = _pattern(facade.get_frequent_patterns(top_n=5), ALPHA_BETA)

        assert _rate(target) == pytest.approx(0.9)


# ────── 持久化：outcomes 与序列按位对齐 ──────


class TestOutcomePersistence:
    def test_outcomes_roundtrip_through_snapshot(self, tmp_path):
        miner = PatternMiner()
        miner.attach_persistence(tmp_path / "state.json", save_interval=0.0)
        _feed(miner, [True, False, None])

        restored = PatternMiner()
        restored.load(tmp_path / "state.json")

        assert restored._outcomes == [True, False, None]
        assert _pattern(restored.mine(), ALPHA_BETA).success_rate == pytest.approx(0.5)

    def test_legacy_state_without_outcomes_restores_as_no_evidence(self, tmp_path):
        """旧状态文件（无 outcomes 字段）⇒ 全部 None，且不得因此判成失败。

        这是换源后最大的回归面：落 False 会把历史序列全部记成失败票，
        于是老库重启后遗传臂把过去每一次复用都当成客观失败。
        """
        path = tmp_path / "legacy.json"
        path.write_text(
            json.dumps({
                "version": 1,
                "sequences": [ALPHA_BETA, ALPHA_BETA, ALPHA_BETA],
                "contexts": [TASK, TASK, TASK],
            }),
            encoding="utf-8",
        )

        miner = PatternMiner()
        miner.load(path)

        assert miner._outcomes == [None, None, None]
        assert _pattern(miner.mine(), ALPHA_BETA).success_rate is None

    def test_outcomes_align_bitwise_under_damage(self, tmp_path):
        """缺失补 None、超长截断、非布尔值落 None（与 contexts 同一套容错）。"""
        path = tmp_path / "damaged.json"
        path.write_text(
            json.dumps({
                "version": 1,
                "sequences": [ALPHA_BETA, ALPHA_BETA, ALPHA_BETA],
                "contexts": [TASK],
                "outcomes": [True, "yes"],
            }),
            encoding="utf-8",
        )

        miner = PatternMiner()
        miner.load(path)

        assert miner._outcomes == [True, None, None]


# ────── 调用点：接 010 的票据三态 ──────


class TestCallSitesFeedTheLedger:
    def test_closed_loop_records_the_objective_outcome(self):
        """`on_experience_recorded` 的 success 位必须落到台账（装配点已票据优先）。"""
        orchestrator = EvolutionOrchestrator()

        orchestrator.on_experience_recorded(
            text="经验正文", task=TASK, tools=list(ALPHA_BETA), success=True)
        orchestrator.on_experience_recorded(
            text="经验正文", task=TASK, tools=list(ALPHA_BETA), success=False)

        assert orchestrator.pattern_miner._outcomes == [True, False]

    def test_closed_loop_without_a_verdict_records_no_vote(self):
        orchestrator = EvolutionOrchestrator()

        orchestrator.on_experience_recorded(
            text="经验正文", task=TASK, tools=list(ALPHA_BETA), success=None)

        assert orchestrator.pattern_miner._outcomes == [None]

    def test_facade_add_tool_sequence_forwards_the_ticket(self):
        orchestrator = EvolutionOrchestrator()
        facade = EvolutionFacade(orchestrator)

        facade.add_tool_sequence(list(ALPHA_BETA), context=TASK, success=False)

        assert orchestrator.pattern_miner._outcomes == [False]


def _agent_stub(records: List[Dict[str, Any]]) -> SimpleNamespace:
    """只带生产装配点要读的字段的 agent 替身（不冒充 Agent 类）。"""
    return SimpleNamespace(
        config=SimpleNamespace(agent_id="genetic-seed-probe"),
        session_id="session-probe",
        _skill_registry=None,
        _collect_tool_messages=lambda: list(records),
    )


def _pipeline(agent: Any, dependencies: Dict[str, Any]) -> PostChatPipeline:
    pipeline = PostChatPipeline.__new__(PostChatPipeline)
    pipeline._agent = agent
    pipeline._get_dependency = lambda name: dependencies.get(name)
    return pipeline


def _tool_call_records(tools: List[str]) -> List[Dict[str, Any]]:
    """`agent/loops/base.py` 的真实 tool_call 形态（刻意不带 success 键）。"""
    return [{"type": "tool_call", "tool_name": t, "params": "{}"} for t in tools]


def _ticket(verdict: GateVerdict, lookup: str, record: Optional[bool]) -> TicketEvidence:
    return TicketEvidence(verdict=verdict, lookup=lookup, record=record)


class TestPipelineWiring:
    """两个 post_chat 调用点必须接票据三态，且不得拿本轮回执冒充票据。"""

    def test_pattern_mining_records_the_ticket_not_the_receipt(self, monkeypatch):
        import neurova.evolution.objective_evidence as evidence_module

        monkeypatch.setattr(
            evidence_module, "resolve_ticket_evidence",
            lambda agent, records: _ticket(
                GateVerdict.failed(reason="服务端票据含失败"), TICKET_EVIDENCED, True))
        orchestrator = EvolutionOrchestrator()
        pipeline = _pipeline(
            _agent_stub(_tool_call_records(["alpha", "beta"])), {"evolution": orchestrator})

        asyncio.run(pipeline._step_pattern_mining())

        assert orchestrator.pattern_miner._outcomes == [False], (
            "本轮回执的 True 覆盖了票据的失败，遗传臂又洗成成功票")

    def test_pattern_mining_without_a_ticket_records_no_vote(self, monkeypatch):
        import neurova.evolution.objective_evidence as evidence_module

        monkeypatch.setattr(
            evidence_module, "resolve_ticket_evidence",
            lambda agent, records: _ticket(
                GateVerdict.unevidenced(reason="无服务端票据"), TICKET_ABSENT, True))
        orchestrator = EvolutionOrchestrator()
        pipeline = _pipeline(
            _agent_stub(_tool_call_records(["alpha", "beta"])), {"evolution": orchestrator})

        asyncio.run(pipeline._step_pattern_mining())

        assert orchestrator.pattern_miner._outcomes == [None]

    def test_rules_step_records_the_ticket_for_the_same_sequence(self, monkeypatch):
        import neurova.evolution.objective_evidence as evidence_module

        class _RuleExtractorProbe:
            async def extract(self, user_input: str, reply: str, session_id: str):
                return []

        monkeypatch.setenv("NEUROVA_CONVERSATION_RULES", "1")
        monkeypatch.setattr(
            evidence_module, "resolve_ticket_evidence",
            lambda agent, records: _ticket(
                GateVerdict.passed(reason="服务端票据全绿"), TICKET_EVIDENCED, None))
        orchestrator = EvolutionOrchestrator()
        pipeline = _pipeline(
            _agent_stub(_tool_call_records(["alpha", "beta"])),
            {"rule_extractor": _RuleExtractorProbe(),
             "pattern_miner": orchestrator.pattern_miner})

        asyncio.run(pipeline._step_extract_conversation_rules(TASK, "已导出", "session-probe"))

        assert orchestrator.pattern_miner._outcomes == [True]


# ────── 种子消费与注册可达性 ──────


class TestSeedingUsesRealRates:
    def _seed(self, outcomes: List[Optional[bool]]) -> Dict[str, Any]:
        orchestrator = EvolutionOrchestrator()
        _feed(orchestrator.pattern_miner, outcomes)
        pipeline = _pipeline(_agent_stub([]), {"evolution": orchestrator})

        asyncio.run(pipeline._step_genetic_evolution())

        step = next(r for r in pipeline._step_results
                    if r.step_name == "genetic_evolution")
        return {"engine": orchestrator.genetic_engine, "step": step}

    def test_seed_carries_zero_nine_instead_of_the_half_fallback(self):
        """票面验收一（消费侧）：9 成功 1 失败 ⇒ 种子 success_rate == 0.9。"""
        seeded = self._seed([True] * 9 + [False])

        genotype = seeded["engine"].population[0]
        assert genotype.success_rate == pytest.approx(0.9), (
            f"种子仍吃兜底值：{genotype.success_rate}")

    def test_high_rate_seed_crosses_the_registration_gate_at_zero_reuse(self):
        """票面验收二（可达分支）：真实 ≥0.8 在零复用时即可跨过阈值。

        断的是注册处的两个真实操作数（fitness 与 validation_threshold），
        不是"库里能查到一行"。
        """
        seeded = self._seed([True] * 9 + [False])

        genotype = seeded["engine"].population[0]
        assert genotype.reuse_count == 0
        assert genotype.fitness >= seeded["engine"]._validation_threshold, (
            f"注册阈值不可达：fitness={genotype.fitness}")

    def test_unevidenced_patterns_are_not_seeded(self):
        """票面验收三（反向锁）：无客观结果的模式不得被当成 0.5 播种。"""
        seeded = self._seed([None] * 10)

        engine, step = seeded["engine"], seeded["step"]
        assert engine.population == [], "无证据模式被播种进了种群"
        assert step.data["seeded"] == 0
        assert step.data["skipped_unevidenced"] >= 1

    def test_low_rate_seed_is_observable_and_stays_below_the_gate(self):
        seeded = self._seed([True, True] + [False] * 8)

        genotype = seeded["engine"].population[0]
        assert genotype.success_rate == pytest.approx(0.2)
        assert genotype.fitness < seeded["engine"]._validation_threshold


class TestRegistrationGateFalsifiable:
    """注册出口的判据必须两头都能咬。"""

    @pytest.fixture
    def publish_probe(self, monkeypatch):
        """截住落盘闸，只看"哪些个体被注册出口放行"（阈值过滤之后的那一格）。"""
        calls: List[Dict[str, Any]] = []

        def _publish(service, registry, manifest, *, alias_id=""):
            calls.append({"id": manifest.id, "config": dict(manifest.config or {})})
            return {"success": True, "duplicate": False, "skill_id": manifest.id}

        import neurova.skills.creation_governance as governance

        monkeypatch.setattr(governance, "publish_automatic", _publish)
        return calls

    def test_zero_nine_genotype_is_published_with_zero_reuse(self, publish_probe):
        engine = ToolGeneticEngine()
        engine.add_to_population(
            ToolGenotype(tool_sequence=list(ALPHA_BETA), success_rate=0.9))

        count = engine.register_to_skill_registry(None, skill_service=object())

        assert count == 1
        assert publish_probe[0]["config"]["success_rate"] == pytest.approx(0.9)

    def test_zero_two_genotype_never_reaches_the_publish_gate(self, publish_probe):
        engine = ToolGeneticEngine()
        engine.add_to_population(
            ToolGenotype(tool_sequence=list(ALPHA_BETA), success_rate=0.2))

        count = engine.register_to_skill_registry(None, skill_service=object())

        assert count == 0, "低成功率个体被注册，阈值不咬"
        assert publish_probe == []

    def test_low_rate_is_unreachable_at_any_realistic_reuse(self):
        """票面"不得留不可达分支"：0.2 需 reuse≈e^6（约 403）才够 0.8，
        现实复用量级（60 次）仍远在阈下 —— 阈值不是靠刷复用能过的。"""
        realistic = ToolGenotype(
            tool_sequence=list(ALPHA_BETA), success_rate=0.2, reuse_count=60)
        unreachable = ToolGenotype(
            tool_sequence=list(ALPHA_BETA), success_rate=0.2, reuse_count=403)

        assert realistic.fitness < 0.8
        assert unreachable.fitness >= 0.8, (
            "e^6 量级的复用都过不去，阈值就是不可达分支")
