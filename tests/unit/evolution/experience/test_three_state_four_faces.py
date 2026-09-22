"""004 残留 · 三态在**四个面**各自独立可分辨（含票末要求的对照表与反向锁）。

票据 004 的验收标准原文：「三种输入（真失败 / 真成功 / 无票无回执）在**四个面**
（EKB 行、权重表、结晶器、API 展示）各自独立可分辨；用一张对照表贴进票末，
缺一格不算完」，并要求「把 `success=NULL` 手工写成 0 ⇒ 至少一条用例必须红」。

前一轮只补了 EKB 罚分档与权重表两格：结晶器面与 API 展示面**零用例**，
于是"库里三分、界面两分"无人发现。本文件把四格一次钉齐：

| 输入 | EKB 行 success | 权重表投票 | 结晶器投票 | API outcome 词 |
|---|---|---|---|---|
| 真成功 | 1 | success_count+1 | 计入分子分母 | `success` |
| 真失败 | 0 | failure_count+1 | 计入分子分母 | `failure` |
| 无票无回执 | NULL | 不投票 | 不进分子分母 | `unevidenced` |

写入一律走生产路径（`ExperienceKnowledgeBase.add_experience_record`），
读数一律走生产取数口（`_outcome_word` 是 `/ranking` 契约的唯一产出点）。
"""

from __future__ import annotations

import sqlite3
from typing import Any, Dict

from neurova.api.endpoints.experience_knowledge_api import _outcome_word
from neurova.cognitive_layers.memory_layer.pattern_crystallizer import PatternCrystallizer
from neurova.evolution.closed_loop import AdaptiveToolWeights
from neurova.skills.experience_knowledge_base import ExperienceKnowledgeBase
from neurova.skills.models import ExperienceRecord

from .conftest import RecordingEngine

TOOL = "pdf_export"
INPUTS: Dict[str, Any] = {"真成功": True, "真失败": False, "无票无回执": None}


def _seed(db_file, cases=(("真成功", True), ("真失败", False), ("无票无回执", None))):
    """经生产写入路径落三行，返回 {标签: 行}。"""
    kb = ExperienceKnowledgeBase(db_path=str(db_file))
    rows: Dict[str, Dict[str, Any]] = {}
    for label, success in cases:
        record_id = kb.add_experience_record(
            skill_name=TOOL,
            exp=ExperienceRecord(skill_name=TOOL, context={"user_input": "导出季度报表"},
                                 result={"reply_excerpt": "已导出"}, success=success),
            agent_id="agent-probe-01",
            evidence=success,
        )
        rows[label] = kb.get_record_by_id(record_id)
    return rows


class TestEkbFace:
    def test_three_states_are_distinct_in_the_column(self, tmp_path):
        rows = _seed(tmp_path / "ekb.db")
        assert rows["真成功"]["success"] == 1
        assert rows["真失败"]["success"] == 0
        assert rows["无票无回执"]["success"] is None, (
            f"未测量落库时被折叠成 {rows['无票无回执']['success']!r}"
        )

    def test_evidence_state_separates_measured_from_unmeasured(self, tmp_path):
        rows = _seed(tmp_path / "ekb.db")
        assert rows["真成功"]["evidence_state"] == "evidenced"
        assert rows["真失败"]["evidence_state"] == "evidenced"
        assert rows["无票无回执"]["evidence_state"] == "unevidenced"


class TestWeightFace:
    def test_unevidenced_votes_neither_way_but_measured_ones_do(self):
        weights = AdaptiveToolWeights()
        for label, success in INPUTS.items():
            weights.update_weight(f"{TOOL}::{label}", success)
        assert weights.get_weight(f"{TOOL}::真成功").success_count == 1
        assert weights.get_weight(f"{TOOL}::真失败").failure_count == 1
        unmeasured = weights.get_weight(f"{TOOL}::无票无回执")
        if unmeasured is not None:
            assert (unmeasured.success_count, unmeasured.failure_count) == (0, 0), (
                f"未测量投了票：{unmeasured.to_dict()}"
            )


class TestCrystallizerFace:
    """结晶器面：`None` 观察不进成功率分子分母，且**不把成功票挤出去**。"""

    @staticmethod
    def _observe(outcomes):
        engine = RecordingEngine()
        crystal = PatternCrystallizer(engine=engine)
        for success in outcomes:
            crystal.observe(tool_name=TOOL, context="导出季度报表", success=success)
        return crystal, engine

    def test_unmeasured_does_not_dilute_a_confirmed_success(self):
        crystal, engine = self._observe([None, True, None])
        candidates = crystal.list_pending() or list(engine.stored)
        assert candidates, (
            "确证成功被两次未测量观察稀释后越不过门槛（等于把 NULL 记成了失败票）"
        )
        candidate = candidates[0]
        rate = getattr(candidate, "rate", None)
        if rate is None:
            rate = candidate["rate"]
        assert rate == 1.0, (
            f"确证口径的成功率被未测量观察拉低了（rate={rate}）：NULL 进了分母"
        )

    def test_confirmed_failure_still_blocks(self):
        crystal, engine = self._observe([False, False, None])
        assert not (crystal.list_pending() or engine.stored), "确证失败仍须拦得住"


class TestApiFace:
    def test_outcome_words_are_three_distinct_values(self):
        assert _outcome_word(True) == "success"
        assert _outcome_word(False) == "failure"
        assert _outcome_word(None) == "unevidenced", (
            "API 展示面把未测量演成了失败（`if row.get('success')` 旧写法）"
        )

    def test_contract_row_reads_the_column_not_truthiness(self, tmp_path):
        """端到端：落库三行 ⇒ `/ranking` 契约三词各归各位。"""
        from neurova.api.endpoints.experience_knowledge_api import _to_contract

        rows = _seed(tmp_path / "ekb.db")
        words = {label: _to_contract(row, 1)["outcome"] for label, row in rows.items()}
        assert words == {"真成功": "success", "真失败": "failure", "无票无回执": "unevidenced"}, (
            f"四面对照表在 API 面塌了：{words}"
        )


class TestReverseLock:
    """反向锁：把 `success=NULL` 手工写成 0 ⇒ 判据必须转红。

    这条不是"再测一遍 NULL"，而是证明上面几格的断言**真的在区分 NULL 与 0**——
    否则"三分退两分"无人发现（票面点名的失效模式）。
    """

    def test_writing_null_as_zero_is_detected(self, tmp_path):
        db_file = tmp_path / "ekb.db"
        _seed(db_file)
        conn = sqlite3.connect(str(db_file))
        before = conn.execute(
            "select success from experience_records where success is null"
        ).fetchall()
        assert before, "样本里没有 NULL 行，反向锁无法成立"
        conn.execute("update experience_records set success = 0 where success is null")
        conn.commit()
        conn.close()

        from neurova.api.endpoints.experience_knowledge_api import _to_contract

        kb = ExperienceKnowledgeBase(db_path=str(db_file))
        folded = [r for r in kb.get_experience_records() if r["success"] == 0]
        words = [_to_contract(r, 1)["outcome"] for r in folded]
        assert "unevidenced" not in words, "折叠后仍显示 unevidenced，断言失去了区分力"
        assert words and all(w == "failure" for w in words), (
            "把 NULL 写成 0 之后 API 面应转成 failure —— 这正是断言要抓住的退化"
        )
