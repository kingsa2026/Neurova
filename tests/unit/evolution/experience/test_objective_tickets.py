"""010 · 三条主经验臂同吃服务端客观票据（红绿灯 TDD）。

根因：仓库里唯一真门是 `creation_governance` 的服务端票据（逐工具三重核验
`result is not None` + 非 `is_policy_denial` + `success is True`、失败粘性
`MIN(success)`、按独立任务计数），而三条臂（`PatternCrystallizer` /
`ExperienceFeedback` / EKB 写入）谁都不查它 —— 成败来自模型自述、`tool_result`
聚合与关键词粗分。于是「自述成功」与「服务端确证成功」在库里不可区分。

落定契约（票面 §涉及层 + 开工前置三点）：

1. **票据有结论即覆盖一切自述**（含 002 从 `tool_result.success` 得到的值）：
   票据说失败，本轮工具回执全绿也不算成功；票据说成功，本轮回执含 False 仍以
   票据为准（票据口径更严，答案唯一）；
2. **无票据 ⇒ 记录聚合降为旁路证据**：条目照常入库（D1 不砍量），但
   `evidence_state` 落 `unevidenced`，且 007 的检索不得再把它当成功票；
3. **关键词分类退到最后一格**（票据与记录都没有时才用），只决定洞察标签，
   不决定 `success_rate` 的分子（口径与 005 的观察票一致：记账不投票）；
4. **形状对齐**：本轮 `tool_call` 记录的 `params` 有两种生产者形态
   （`agent/loops/base.py:196-201` 给解析后的 dict；`tool_executor.py:841-849`
   的肌肉记忆通道给模板串），而 `normalize_steps` 只吃 dict，吃字符串直接
   `ValueError: Invalid skill tool/params` ⇒ 查票据前必须 `json.loads`；
   解析失败判「票据不可读」并 WARNING，**不得**降级成「无票据」—— 那会把每一轮
   都标成 `unevidenced`，把「我们读不到证据」误报成「不存在证据」；
5. **装配点唯一**在 `post_chat_pipeline._step_record_experience`（同时握着 agent、
   本轮记录与 002 的三态），`agent_core.py` 零改动（尺寸棘轮 2159 行）。

取证口径：票据一律经生产写入路径（`begin_task → record_tool_execution →
flush_task`）喂入，不在测试里手工写 `EvidenceStore.record()` —— 本票最大的雷就是
读写两侧结构身份形状不一致，只有让生产写入方当对照组才钉得住。
"""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from typing import Any, Dict, List, Tuple

import pytest

from neurova.core.turn_context import set_turn_injected_experiences
from neurova.evolution.objective_evidence import (
    TICKET_ABSENT,
    TICKET_EVIDENCED,
    TICKET_UNREADABLE,
    parse_turn_steps,
    resolve_ticket_evidence,
)
from neurova.skills.creation_governance import (
    begin_task,
    flush_task,
    record_tool_execution,
)
from neurova.skills.experience_knowledge_base import (
    ExperienceKnowledgeBase,
    ExperienceRecord,
)
from neurova.skills.skill_service import SkillService

# conftest 探针的 agent 身份。测试不得改传别的 agent_id 来绕开生产装配点
# （票据按 agent 分库，见 `SkillService.__init__` → `EvidenceStore`）。
PROBE_AGENT_ID = "agent-probe-01"

PDF_TOOL = "pdf_export"
PDF_PARAMS = {"path": "/tmp/report.pdf", "pages": "1-3"}
PDF_PARAMS_JSON = json.dumps(PDF_PARAMS, ensure_ascii=False)
TASK = "把报告导出成 PDF"
MENTION = "pdf_export 已用于导出"


@pytest.fixture(autouse=True)
def _clean_turn_injection_set():
    """本轮注入集是 ContextVar，同线程不自动隔离 —— 前后都清场。"""
    set_turn_injected_experiences(None)
    yield
    set_turn_injected_experiences(None)


def _agent_stub(agent_id: str = PROBE_AGENT_ID) -> SimpleNamespace:
    """只带生产装配点要读的身份字段的 agent 替身（不冒充 Agent 类）。"""
    return SimpleNamespace(config=SimpleNamespace(agent_id=agent_id))


def _record_ticket(steps: List[Tuple[str, Any]], *, success: bool,
                   agent_id: str = PROBE_AGENT_ID, purpose: str = TASK) -> Dict[str, Any]:
    """经生产写入路径落一张服务端票据。

    `steps` 用写入侧的真实形状 `(tool_name, params_dict)` —— 写入侧收的是解析后的
    dict，读取侧（本轮 `tool_call` 记录）收的是 LLM 原始参数，两侧必须由
    `parse_turn_steps` 对齐到同一个 `structure_key`。
    """
    service = SkillService(agent_id=agent_id)
    begin_task()
    for tool_name, params in steps:
        result = {"ok": True} if success else {"error": "工具报错"}
        record_tool_execution(tool_name, params, success, result)
    flushed = flush_task(service, purpose, completed=True)
    assert flushed is not None, "票据未写入（步骤为空？），本用例无法成立"
    return flushed


class TestShapeAlignment:
    """读写两侧结构身份必须对齐（开工前置第 2 点：本票最大的雷）。"""

    def test_string_params_parse_into_the_written_structure(self):
        """本轮 params 是 JSON 串 ⇒ 仍要查到生产写入路径落下的那张票。

        修复前必红：字符串直接喂 `normalize_steps` 抛 `ValueError`，
        于是每一轮都「查无票据」。
        """
        _record_ticket([(PDF_TOOL, PDF_PARAMS)], success=True)
        records = [
            {"type": "tool_call", "tool_name": PDF_TOOL, "params": PDF_PARAMS_JSON,
             "timestamp": "2026-09-20T10:00:00"},
        ]

        evidence = resolve_ticket_evidence(_agent_stub(), records)

        assert evidence.lookup == TICKET_EVIDENCED, (
            f"params 是字符串时查不回票据，结构身份两侧未对齐：{evidence}")
        assert evidence.ticket is True

    def test_dict_params_shape_from_loops_base_matches_too(self):
        """反例配对：params 已是 dict（`agent/loops/base.py` 形态）⇒ 同一张票。

        两种形态必须落到同一个结构身份，否则同一次执行因生产者形态不同而
        一半有票一半没票。
        """
        _record_ticket([(PDF_TOOL, PDF_PARAMS)], success=True)
        records = [
            {"type": "tool_call", "tool_name": PDF_TOOL, "params": dict(PDF_PARAMS),
             "timestamp": "2026-09-20T10:00:00"},
        ]

        assert resolve_ticket_evidence(_agent_stub(), records).ticket is True

    def test_unreadable_params_is_not_reported_as_no_ticket(self, caplog):
        """参数串解不开 ⇒ 判「票据不可读」并出声，不得判「无票据」。

        降级成「无票据」会让全部轮次落 `unevidenced`，读起来像「这个 agent 从来没
        有客观回执」，而真因是我们的解析断了 —— 比现状更糟的假象。
        """
        records = [
            {"type": "tool_call", "tool_name": PDF_TOOL,
             "params": '{"path": "/tmp/report.pdf", ', "timestamp": "2026-09-20T10:00:00"},
        ]

        with caplog.at_level(logging.WARNING,
                             logger="neurova.evolution.objective_evidence"):
            evidence = resolve_ticket_evidence(_agent_stub(), records)

        assert evidence.lookup == TICKET_UNREADABLE, (
            f"解析失败被判成了 {evidence.lookup}，与「查无票据」混为一谈")
        assert evidence.ticket is None
        assert "票据不可读" in caplog.text, "取证断了必须出声，不许静默降级"

    def test_no_ticket_for_this_structure_is_reported_absent(self):
        """反例锁：查得动、库里这条结构确实没票 ⇒ `absent`，不得蹭「不可读」。"""
        _record_ticket([("web_search", {"query": "别的序列"})], success=True)
        records = [
            {"type": "tool_call", "tool_name": PDF_TOOL, "params": PDF_PARAMS_JSON},
        ]

        evidence = resolve_ticket_evidence(_agent_stub(), records)

        assert evidence.lookup == TICKET_ABSENT
        assert evidence.ticket is None

    def test_create_skill_step_excluded_like_the_write_side(self):
        """写入侧 `record_tool_execution` 跳过 `create_skill` ⇒ 读取侧必须同样跳过。

        不跳过则「这轮顺手封装了技能」的结构身份永远查不到票（多一步）。
        """
        _record_ticket([("web_search", {"query": "今日新闻"})], success=True)
        records = [
            {"type": "tool_call", "tool_name": "web_search",
             "params": '{"query": "今日新闻"}'},
            {"type": "tool_call", "tool_name": "create_skill",
             "params": '{"name": "news2pdf"}'},
        ]

        assert resolve_ticket_evidence(_agent_stub(), records).ticket is True

    def test_parse_turn_steps_yields_dict_params_for_normalize(self):
        """`parse_turn_steps` 的产物必须能被 `normalize_steps` 吃下（身份前置）。"""
        from neurova.skills.creation_governance import structure_key

        steps, unreadable = parse_turn_steps([
            {"type": "tool_call", "tool_name": PDF_TOOL, "params": PDF_PARAMS_JSON},
            {"type": "tool_result", "tool_name": PDF_TOOL, "success": True},
        ])

        assert unreadable == []
        assert [s["tool"] for s in steps] == [PDF_TOOL]
        assert structure_key(steps) == structure_key(
            [{"tool": PDF_TOOL, "params": PDF_PARAMS}])

    def test_result_records_never_become_steps(self):
        """只有 `tool_call` 记录进步骤：`tool_result` 是回执不是执行步骤。

        否则同一次调用被算两步，结构身份与写入侧差一倍。
        """
        steps, _ = parse_turn_steps([
            {"type": "tool_call", "tool_name": PDF_TOOL, "params": PDF_PARAMS_JSON},
            {"type": "tool_result", "tool_name": PDF_TOOL, "success": True},
        ])

        assert len(steps) == 1, f"tool_result 被算进了结构身份：{steps}"


class TestTicketOverridesSelfReport:
    """经生产装配点（`_step_record_experience`）驱动三条臂。"""

    def test_ticket_failure_beats_a_green_turn(self, experience_probe, tool_records):
        """票据含失败 ⇒ 条目不得为成功，即使本轮 `tool_result` 全绿。"""
        _record_ticket([(PDF_TOOL, PDF_PARAMS)], success=False)

        result = experience_probe.run_turn(
            user_input=TASK,
            tool_messages=[
                tool_records.call(PDF_TOOL, params=PDF_PARAMS_JSON),
                tool_records.result(PDF_TOOL, True, result="已导出"),
            ],
        )

        row = result["rows"][-1]
        assert result["facade_success"] is False, (
            f"本轮自述的 True 覆盖了票据的失败：{result['facade_success']!r}")
        assert row["success"] == 0, f"票据说失败，条目却记成功：{row}"
        assert row["evidence_state"] == "evidenced", "有票据＝有客观回执，不得标无据"

    def test_ticket_success_wins_over_a_failed_turn_receipt(self, experience_probe,
                                                            tool_records):
        """票据 True + 本轮 `tool_result` 含 False ⇒ 取票据（票面补充判据，答案唯一）。"""
        _record_ticket([(PDF_TOOL, PDF_PARAMS)], success=True)

        result = experience_probe.run_turn(
            user_input=TASK,
            tool_messages=[
                tool_records.call(PDF_TOOL, params=PDF_PARAMS_JSON),
                tool_records.result(PDF_TOOL, False, result="磁盘写入失败"),
            ],
        )

        assert result["facade_success"] is True, "票据口径更严，本轮回执不得反覆盖"
        assert result["rows"][-1]["success"] == 1
        assert result["rows"][-1]["evidence_state"] == "evidenced"

    def test_self_reported_success_without_ticket_is_unevidenced(self, experience_probe,
                                                                tool_records):
        """自述成功（工具回执绿）但无票据 ⇒ 落库 + 标 `unevidenced`。

        修复前必红：002 之后这轮被判成 `evidenced`，007 于是把它当成功票。
        """
        result = experience_probe.run_turn(
            user_input=TASK,
            tool_messages=[
                tool_records.call(PDF_TOOL, params=PDF_PARAMS_JSON),
                tool_records.result(PDF_TOOL, True, result="已导出"),
            ],
        )

        assert result["rows"], "D1：无票据仍要照常入库"
        row = result["rows"][-1]
        assert row["success"] == 1, "旁路证据仍决定成败位（不砍量）"
        assert row["evidence_state"] == "unevidenced", (
            f"无服务端票据的自述成功被标成了有证据：{row}")
        assert row["tags"] == "[]", "不得再把标记塞回 tags 字符串"

    def test_ticket_backed_success_is_not_mislabeled_unevidenced(self, experience_probe,
                                                                 tool_records):
        """反向锁：有票据的正常成功轮不得被误标无证据（否则指标与降权一起失真）。"""
        _record_ticket([(PDF_TOOL, PDF_PARAMS)], success=True)

        result = experience_probe.run_turn(
            user_input=TASK,
            tool_messages=[
                tool_records.call(PDF_TOOL, params=PDF_PARAMS_JSON),
                tool_records.result(PDF_TOOL, True, result="已导出"),
            ],
        )

        assert result["rows"][-1]["evidence_state"] == "evidenced"
        assert result["facade_success"] is True

    def test_another_agents_ticket_does_not_evidence_this_turn(self, experience_probe,
                                                               tool_records):
        """票据按 agent 分库：别的 agent 成功过同一条序列，不给本轮作证。"""
        _record_ticket([(PDF_TOOL, PDF_PARAMS)], success=True, agent_id="agent-other")

        result = experience_probe.run_turn(
            user_input=TASK,
            tool_messages=[
                tool_records.call(PDF_TOOL, params=PDF_PARAMS_JSON),
                tool_records.result(PDF_TOOL, True, result="已导出"),
            ],
        )

        assert result["rows"][-1]["evidence_state"] == "unevidenced", (
            "跨 agent 借票：归属边界被结构身份打穿")

    def test_unreadable_ticket_does_not_silently_join_the_no_ticket_crowd(
            self, experience_probe, tool_records, caplog):
        """解析失败轮：条目仍入库（D1），但观测面必须与「无票据」分得开。"""
        with caplog.at_level(logging.WARNING,
                             logger="neurova.evolution.objective_evidence"):
            result = experience_probe.run_turn(
                user_input=TASK,
                tool_messages=[
                    tool_records.call(PDF_TOOL, params='{"path": "/tmp/report.pdf", '),
                    tool_records.result(PDF_TOOL, True, result="已导出"),
                ],
            )

        assert result["rows"], "取证失败不等于不入库（D1）"
        assert result["rows"][-1]["evidence_state"] == "unevidenced"
        step_data = experience_probe.pipeline._step_results[-1].data
        assert step_data["ticket_state"] == TICKET_UNREADABLE, (
            f"观测面把「票据不可读」报成了「无票据」：{step_data}")
        assert "票据不可读" in caplog.text

    def test_crystallizer_arm_votes_with_the_ticket_not_the_receipt(
            self, experience_probe, tool_records, make_crystallizer):
        """结晶臂吃同一个结论：票据 False 不得被本轮绿回执洗成成功观察。"""
        from neurova.evolution.closed_loop import EvolutionOrchestrator

        crystallizer, _engine = make_crystallizer()
        experience_probe.pipeline._agent.crystallizer = crystallizer
        experience_probe.pipeline._get_dependency = lambda name: (
            EvolutionOrchestrator() if name == "evolution" else None
        )
        _record_ticket([(PDF_TOOL, PDF_PARAMS)], success=False)

        experience_probe.run_turn(
            user_input=TASK,
            tool_messages=[
                tool_records.call(PDF_TOOL, params=PDF_PARAMS_JSON),
                tool_records.result(PDF_TOOL, True, result="已导出"),
            ],
        )

        observed = [e for bucket in crystallizer._buffer.values() for e in bucket]
        assert observed, "结晶臂根本没被喂到，本用例无法判据"
        assert all(e["success"] is False for e in observed), (
            f"票据失败被自述回执洗成成功观察票：{observed}")


class TestQualityReadoutMoves:
    """无票据入库条数必须进 008 指标（读数必须能动）。"""

    @staticmethod
    def _snapshot():
        from neurova.skills.experience_knowledge_base import get_experience_knowledge_base

        return get_experience_knowledge_base().quality_snapshot()

    def test_unevidenced_ratio_rises_with_no_ticket_turns_and_stays_flat_with_tickets(
            self, experience_probe, tool_records):
        """对照：两轮回执同样绿，只差有没有票据 ⇒ `unevidenced_ratio` 必须差得开。

        修复前必红：两行都是 `evidenced`，读数恒 0.0，指标面对这条缺陷失明。
        """
        turn_messages = [
            tool_records.call(PDF_TOOL, params=PDF_PARAMS_JSON),
            tool_records.result(PDF_TOOL, True, result="已导出"),
        ]
        baseline = self._snapshot()
        assert baseline["rows"] == 0, "临时库必须干净，否则对照无意义"
        assert baseline["unevidenced_ratio"] == 0.0

        experience_probe.run_turn(user_input=TASK, tool_messages=turn_messages)
        no_ticket = self._snapshot()
        assert no_ticket["rows"] == 1
        assert no_ticket["unevidenced_ratio"] == pytest.approx(1.0), (
            "无票据入库条数没进读数：008 指标面仍是瞎的")

        _record_ticket([(PDF_TOOL, PDF_PARAMS)], success=True)
        experience_probe.run_turn(user_input=TASK, tool_messages=turn_messages)
        with_ticket = self._snapshot()
        assert with_ticket["rows"] == 1, (
            f"同内容两轮应按 011 的内容门合并成一行，实测 {with_ticket}")
        assert with_ticket["unevidenced_ratio"] == 0.0, (
            f"票据到位后该行仍被计作无据（读数不会动）：{with_ticket}")

    def test_ticket_backed_turn_never_inflates_the_unevidenced_readout(
            self, experience_probe, tool_records):
        """反例锁：全部有票据 ⇒ 读数必须为 0.0，不得跟着上涨（防「一律无据」蒙对）。"""
        _record_ticket([(PDF_TOOL, PDF_PARAMS)], success=True)

        experience_probe.run_turn(user_input=TASK, tool_messages=[
            tool_records.call(PDF_TOOL, params=PDF_PARAMS_JSON),
            tool_records.result(PDF_TOOL, True, result="已导出"),
        ])

        snap = self._snapshot()
        assert snap["rows"] == 1
        assert snap["unevidenced_ratio"] == 0.0


class TestRetrievalDoesNotCreditSelfReport:
    """007 侧：`unevidenced` 的成功行不得当成功票。"""

    @pytest.fixture()
    def ekb(self, tmp_path):
        db = ExperienceKnowledgeBase(db_path=str(tmp_path / "ekb.db"))
        yield db
        db.close()

    @staticmethod
    def _seed(ekb, text: str, *, success: bool, evidence) -> int:
        return ekb.add_experience_record(
            "chat",
            ExperienceRecord(skill_name="chat", context={"user_input": text},
                             result={"reply_excerpt": "r"}, success=success),
            agent_id="default",
            evidence=evidence,
        )

    def test_unevidenced_success_sits_between_evidenced_success_and_failure(self, ekb):
        """相关性相同：确证成功 > 无据成功 > 确证失败。

        修复前必红：无据成功与确证成功同分（自述被当成成功票）。
        同时锁死另一个方向：降权不等于垫底。
        """
        self._seed(ekb, "PDF 报告 导出 甲", success=True, evidence=True)
        self._seed(ekb, "PDF 报告 导出 乙", success=True, evidence=None)
        self._seed(ekb, "PDF 报告 导出 丙", success=False, evidence=False)

        hits = ekb.find_similar_experiences(
            context={"user_input": "PDF 报告 导出"}, agent_id="default", limit=5)

        states = [(h["evidence_state"], h["success"]) for h in hits]
        assert states == [("evidenced", 1), ("unevidenced", 1), ("evidenced", 0)], (
            f"三档顺序失守：{states}")
        scores = [h["similarity_score"] for h in hits]
        assert scores == sorted(scores, reverse=True) and len(set(scores)) == 3, (
            f"分数必须严格分档：{scores}")


class TestKeywordVotesAbstain:
    """关键词分类退到最后一格，且不得进 `success_rate` 分子（票面 §涉及层）。"""

    @staticmethod
    def _assoc(orchestrator):
        associations = orchestrator.experience_feedback._associations.get(TASK, {})
        assert associations, "未产生任务-工具关联，本用例无法判据计数"
        return next(iter(associations.values()))

    def test_keyword_success_without_any_receipt_does_not_vote(self):
        """无票据、无工具回执，只有「成功」两个字 ⇒ 记账但不得投成功票。"""
        from neurova.evolution.closed_loop import EvolutionOrchestrator

        orchestrator = EvolutionOrchestrator()
        orchestrator.on_experience_recorded(
            text=f"{MENTION}，任务执行成功并完成", task=TASK, tools=["pdf_export"],
            success=None,
        )

        assoc = self._assoc(orchestrator)
        assert assoc.success_count == 0, f"关键词自述仍在投成功票：{assoc.to_dict()}"
        assert assoc.total_count == 1, "尝试数照记（003 契约：无回执不得从分母消失）"
        assert orchestrator.experience_feedback.get_feedback()["success_rate"] == 0.0

    def test_keyword_failure_without_any_receipt_does_not_vote(self):
        """对称反例：关键词「失败」同样不得投票 —— 否则门槛只被单向操纵。"""
        from neurova.evolution.closed_loop import EvolutionOrchestrator

        orchestrator = EvolutionOrchestrator()
        orchestrator.on_experience_recorded(
            text=f"{MENTION}，但执行失败并报错", task=TASK, tools=["pdf_export"],
            success=None,
        )

        assert self._assoc(orchestrator).failure_count == 0

    def test_keyword_label_survives(self):
        """反向锁（003 的取向）：退到最后一格 ≠ 一刀砍死，洞察标签仍按关键词分类。"""
        from neurova.evolution.experience_feedback import ExperienceFeedback

        feedback = ExperienceFeedback()
        result = feedback.process_experience(
            experience_text=f"{MENTION}，但执行失败并报错", task_type=TASK)

        assert result["outcome"] == "failure", "关键词标签被顺手删了，003 的反向锁失效"
        assert feedback._insights[-1].outcome == "failure"

    def test_objective_receipt_still_votes_both_ways(self):
        """反向锁：票据/回执给出的成败照常投票，否则「弃权」会变成「一律不记分」。"""
        from neurova.evolution.closed_loop import EvolutionOrchestrator

        good = EvolutionOrchestrator()
        good.on_experience_recorded(text=MENTION, task=TASK, tools=["pdf_export"],
                                    success=True)
        assert self._assoc(good).success_count == 1

        bad = EvolutionOrchestrator()
        bad.on_experience_recorded(text=MENTION, task=TASK, tools=["pdf_export"],
                                   success=False)
        assert self._assoc(bad).failure_count == 1

    def test_three_keyword_successes_cannot_pass_the_crystallization_gate(self):
        """门槛必须买不起自述票：三条「成功」字样不得过 `min_success_rate`。"""
        from neurova.evolution.closed_loop import EvolutionOrchestrator

        self_told = EvolutionOrchestrator()
        for _ in range(3):
            self_told.on_experience_recorded(
                text=f"{MENTION}，任务执行成功", task=TASK, tools=["pdf_export"],
                success=None,
            )
        assert self_told.experience_feedback.get_feedback()["crystallized_patterns"] == 0, (
            "自述成功仍能把结晶门槛喂到过关：G1 形态在该臂未闭合")

        receipted = EvolutionOrchestrator()
        for _ in range(3):
            receipted.on_experience_recorded(
                text=MENTION, task=TASK, tools=["pdf_export"], success=True,
            )
        assert receipted.experience_feedback.get_feedback()["crystallized_patterns"] == 1, (
            "反例失守：客观成功票也被门槛拒了（说明改动没落在分子上）")
