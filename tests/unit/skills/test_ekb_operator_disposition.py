"""工单 015 · `experience_records` 的人工处置通路（审核 / 降权 / 隐藏 / 恢复）。

006-008 之后库里第一次有了真质量数据（`adoption_outcome` / `evidence_state`），
但运营侧只有"查看相似 + 删除"一个动作：看得见问题、只能删。删除是不可逆的，
而"这条先别再注入 prompt"和"这条永不许再出现"是两件事。

落定契约（`operator_disposition` 列，NULL = 未处置）：

- `demoted`：检索分数在采纳证据档之下再扣一档，注入优先级落到 45 —— 判据必须
  **真的动**（复用 007 的两个接缝），不是只改一个 UI 标记；
- `suppressed`：从检索结果里出局，但行还在（硬删仍是 `DELETE`，不混进本通路）；
- `endorsed`：只登记人工确认这件事，**不得**把 `unevidenced` 洗成 `success`——
  采纳证据列与 `quality_snapshot()` 读数一个字节都不许变；
- 恢复（`None`）：回到未处置态，前后分数一致，全程不删行。

排序口径（007 登记给本票）：运营列表按"待处置优先、其次写入序"，
否则要么新条目沉底看不见，要么处置完的还堵在最前面。
"""

from __future__ import annotations

import pytest

from neurova.skills.experience_knowledge_base import (
    ExperienceKnowledgeBase,
    ExperienceRecord,
)

QUERY = "PDF 报告 导出"


@pytest.fixture()
def ekb(tmp_path):
    yield ExperienceKnowledgeBase(db_path=str(tmp_path / "ekb.db"))


def _seed(ekb, tail: str, *, success: bool = True, adopted=None, agent_id="default") -> int:
    rid = ekb.add_experience_record(
        "chat",
        ExperienceRecord(
            skill_name="chat",
            context={"user_input": f"{QUERY} {tail}"},
            result={"reply_excerpt": "r"},
            success=success,
        ),
        agent_id=agent_id,
        evidence=True,
    )
    if adopted is not None:
        ekb.record_injection_adoption([rid], adopted)
    return rid


def _rank(ekb):
    return [r["id"] for r in ekb.find_similar_experiences(context={"user_input": QUERY}, limit=10)]


def _score(ekb, rid):
    for r in ekb.find_similar_experiences(context={"user_input": QUERY}, limit=10):
        if r["id"] == rid:
            return r["similarity_score"]
    return None


class TestDemoteBitesTheRetrievalSeam:
    def test_demoted_row_ranks_below_an_undisposed_failure_row(self, ekb):
        """同证据档的两条，被人工降权的那条必须落到后面（判据咬合，不是查得到就行）。"""
        x = _seed(ekb, "甲", adopted=False)
        y = _seed(ekb, "乙", adopted=False)
        assert _rank(ekb) == [x, y], "前置：两条同处 failure 档、分数相等时按写入序"

        ekb.set_operator_disposition([x], "demoted")

        assert _rank(ekb) == [y, x], "降权必须真的改写检索顺序"
        assert _score(ekb, x) < _score(ekb, y)

    def test_demoted_score_is_strictly_below_the_failure_tier(self, ekb):
        """降权档必须低于 failure 档：人工判断压在客观证据之下，不是并列。"""
        failure = _seed(ekb, "甲", adopted=False)
        demoted_success = _seed(ekb, "乙", adopted=True)
        ekb.set_operator_disposition([demoted_success], "demoted")

        assert _score(ekb, demoted_success) < _score(ekb, failure)

    def test_restore_returns_the_original_score(self, ekb):
        """处置可逆：恢复后分数与处置前逐位相同（不留下"降过一次"的暗记）。"""
        rid = _seed(ekb, "甲", adopted=True)
        baseline = _score(ekb, rid)

        ekb.set_operator_disposition([rid], "demoted")
        assert _score(ekb, rid) != baseline

        ekb.set_operator_disposition([rid], None)
        assert _score(ekb, rid) == baseline


class TestSuppressHidesWithoutDeleting:
    def test_suppressed_row_leaves_retrieval_but_stays_in_the_table(self, ekb):
        rid = _seed(ekb, "甲", adopted=False)
        other = _seed(ekb, "乙", adopted=True)

        ekb.set_operator_disposition([rid], "suppressed")

        assert _rank(ekb) == [other], "隐藏必须真出局，否则运营只能靠删除"
        assert ekb.get_record_by_id(rid) is not None, "隐藏 ≠ 删除：行必须还在"

    def test_unsuppress_brings_it_back(self, ekb):
        rid = _seed(ekb, "甲", adopted=False)
        ekb.set_operator_disposition([rid], "suppressed")
        assert _rank(ekb) == []

        ekb.set_operator_disposition([rid], None)
        assert _rank(ekb) == [rid]


class TestEndorseNeverLaunderEvidence:
    def test_endorse_leaves_adoption_and_quality_readings_untouched(self, ekb):
        """反向锁：人工"审核通过"不是客观成功票。

        `adoption_outcome` / `evidence_state` / `quality_snapshot()` 三处读数在
        处置前后必须完全一致——把它们改成 success 等于把人的判断写成执行证据，
        007 的排序与 008 的告警会一起被污染。
        """
        rid = _seed(ekb, "甲")  # evidence=True, 未回写采纳 ⇒ adoption_outcome IS NULL
        before_row = ekb.get_record_by_id(rid)
        before_snapshot = ekb.quality_snapshot()
        before_score = _score(ekb, rid)

        ekb.set_operator_disposition([rid], "endorsed")

        after_row = ekb.get_record_by_id(rid)
        assert after_row["adoption_outcome"] == before_row["adoption_outcome"]
        assert after_row["evidence_state"] == before_row["evidence_state"]
        assert ekb.quality_snapshot() == before_snapshot
        assert _score(ekb, rid) == before_score, "审核通过不改检索分数（它不是证据）"

    def test_endorse_on_unevidenced_row_does_not_report_a_decision(self, ekb):
        rid = _seed(ekb, "甲", success=True)
        ekb.record_injection_adoption([rid], None)  # 注入过但本轮无回执 ⇒ unevidenced
        assert ekb.get_record_by_id(rid)["adoption_outcome"] == "unevidenced"

        ekb.set_operator_disposition([rid], "endorsed")

        snap = ekb.quality_snapshot()
        assert snap["adoption_decisions"] == 0, "审核不得凭空造出一次采纳决策"
        assert snap["adoption_unevidenced"] == 1


class TestDispositionBoundaries:
    def test_unknown_disposition_rejected(self, ekb):
        rid = _seed(ekb, "甲")
        with pytest.raises(ValueError):
            ekb.set_operator_disposition([rid], "bananas")

    def test_missing_ids_report_zero_rows_updated(self, ekb):
        _seed(ekb, "甲")
        assert ekb.set_operator_disposition([9999], "demoted") == 0

    def test_empty_id_list_is_a_no_op(self, ekb):
        rid = _seed(ekb, "甲")
        assert ekb.set_operator_disposition([], "demoted") == 0
        assert ekb.get_record_by_id(rid)["operator_disposition"] is None

    def test_no_disposition_column_value_changes_row_count(self, ekb):
        """任何处置动作都不得增删行（增删各有自己的通路）。"""
        ids = [_seed(ekb, t) for t in ("甲", "乙", "丙")]
        for state in ("demoted", "suppressed", "endorsed", None):
            ekb.set_operator_disposition(ids, state)
        assert len(ekb.get_experience_records(agent_id="default")) == 3


class TestOperationsListOrdering:
    """007 登记给本票的口径：运营列表"待处置优先、其次写入序"。"""

    def test_rows_needing_attention_surface_first(self, ekb):
        """播种序刻意让"最新的一条恰好不需要处置"——纯写入序会把待处置那条埋在中段。"""
        oldest_clean = _seed(ekb, "甲", adopted=True)
        pending_failure = _seed(ekb, "乙", adopted=False)
        newest_clean = _seed(ekb, "丙", adopted=True)

        listed = [r["id"] for r in ekb.get_experience_records(agent_id="default")]
        assert listed == [pending_failure, newest_clean, oldest_clean], (
            "待处置那条必须顶到最前，其余按写入序"
        )

    def test_unevidenced_rows_count_as_needing_attention(self, ekb):
        """无客观凭据（注入过但无回执）与"失败过"同属待处置，不能只盯 failure。"""
        confirmed = _seed(ekb, "甲", adopted=True)
        unadopted = _seed(ekb, "乙")
        ekb.record_injection_adoption([unadopted], None)

        listed = [r["id"] for r in ekb.get_experience_records(agent_id="default")]
        assert listed == [unadopted, confirmed]

    def test_endorsing_a_row_moves_it_out_of_the_pending_front(self, ekb):
        """审核的可观测后果就是这条：它从"待办最前"退回到自然写入序。

        播种序刻意让待处置那条是**较早**的一条，否则 id DESC 本来就会把它顶在前面，
        断言测的就不是处置生效而是插入顺序。
        """
        failure = _seed(ekb, "甲", adopted=False)
        clean = _seed(ekb, "乙", adopted=True)
        assert [r["id"] for r in ekb.get_experience_records(agent_id="default")] == [failure, clean]

        ekb.set_operator_disposition([failure], "endorsed")

        assert [r["id"] for r in ekb.get_experience_records(agent_id="default")] == [clean, failure]

    def test_disposition_is_reported_on_the_row(self, ekb):
        rid = _seed(ekb, "甲")
        ekb.set_operator_disposition([rid], "demoted")
        assert ekb.get_record_by_id(rid)["operator_disposition"] == "demoted"


class TestQualitySnapshotIsStillTheOnlyReadingSource:
    """008 口径：运营视图从新列重建，不得把已删的假聚合请回来。"""

    def test_deleted_aggregates_stay_deleted(self, ekb):
        for gone in ("get_skill_ranking", "evaluate_skill_effectiveness", "recommend_best_practices"):
            assert not hasattr(ExperienceKnowledgeBase, gone), f"{gone} 被复活了"

    def test_rows_expose_the_columns_the_operations_view_needs(self, ekb):
        rid = _seed(ekb, "甲", adopted=False)
        row = ekb.get_record_by_id(rid)
        for column in ("adoption_outcome", "evidence_state", "injected_count", "seen_count", "content_key"):
            assert column in row
