"""007 · 检索按质量截断，失败经验不得与成功经验同权重（红绿灯 TDD）。

根因：`find_similar_experiences` 的相关性门是布尔的
（`if keyword_score > 0 or topic_score > 0`）—— 查询与 stored 文本只共一个
2-gram 也算命中；算出来的 `similarity_score` 除排序外无人读，而质量在分数里
只占 10% 且取自那个 002 之前恒为 1 的位。006 有了采纳后证据，这里必须让它
真的参与"能不能被注入"的决策。

落定契约：
1. 门落在**相关性**上（`relevance = 0.6*keyword + 0.3*topic ≥ min_relevance`），
   质量分不得替无关条目买路；单 token 重叠必须出局；
2. 采纳后证据参与排序：`success > 无采纳记录 > unevidenced > failure`，
   四条都仍然可见（D1：降权不是消失），但绝不与确证成功同权；
3. 反向锁：真实相关的查询必须仍然命中（阈值不得高到"永远查不到经验"）；
4. 阈值是可拨的旋钮（`min_relevance` 形参），默认值写在生产装配点上。
"""

from __future__ import annotations

import pytest

from neurova.skills.experience_knowledge_base import (
    ExperienceKnowledgeBase,
    ExperienceRecord,
)

QUERY = "PDF 报告 导出"
STORED = {
    "A": "PDF 报告 导出 甲",
    "B": "PDF 报告 导出 乙",
    "C": "PDF 报告 导出 丙",
    "D": "PDF 报告 导出 丁",
}


@pytest.fixture()
def ekb(tmp_path):
    yield ExperienceKnowledgeBase(db_path=str(tmp_path / "ekb.db"))


def _seed(ekb, text: str, success: bool = True, evidence: bool = True) -> int:
    """默认按"有形成侧回执"播种（工单 010 之后的口径）。

    `evidence` 参数在 007 交付时不存在 —— 那时 `success` 位就等价于"有证据"。
    010 把两者分开：无服务端票据的 `success=1` 是自述，检索侧不得再当成功票。
    本文件的 D 行要当的是"无采纳记录、但形成侧确有回执"这一档，不补 `evidence`
    就等于让一条无据自述去当基准，排序断言测的不再是 007 想测的东西。
    """
    return ekb.add_experience_record(
        "chat",
        ExperienceRecord(
            skill_name="chat",
            context={"user_input": text},
            result={"reply_excerpt": "r"},
            success=success,
        ),
        agent_id="default",
        evidence=evidence,
    )


def _inputs(hits) -> list:
    return [h["context"]["user_input"] for h in hits]


class TestRelevanceGate:
    def test_single_token_overlap_is_cut(self, ekb):
        _seed(ekb, STORED["A"])
        hits = ekb.find_similar_experiences(
            context={"user_input": "报告和摘要和结论和附录"}, agent_id="default", limit=5
        )
        assert hits == [], f"只共一个实词片的查询不得入选，实际 {hits}"

    def test_genuine_relevance_still_injects(self, ekb):
        """反向锁：门不能高到永远查不到经验。"""
        _seed(ekb, STORED["A"])
        hits = ekb.find_similar_experiences(
            context={"user_input": QUERY}, agent_id="default", limit=5
        )
        assert _inputs(hits) == [STORED["A"]]

    def test_threshold_is_a_live_knob(self, ekb):
        _seed(ekb, STORED["A"])
        cut = ekb.find_similar_experiences(
            context={"user_input": "报告和摘要和结论和附录"}, agent_id="default",
            limit=5, min_relevance=0.0,
        )
        assert len(cut) == 1, "把阈值拨到 0 必须能放进来（证明门吃的是参数不是硬编码）"


class TestAdoptionEvidenceRanks:
    @pytest.fixture()
    def four_rows(self, ekb):
        ids = {k: _seed(ekb, text) for k, text in STORED.items()}
        ekb.record_injection_adoption([ids["A"]], True)     # 采纳后成功
        ekb.record_injection_adoption([ids["B"]], False)    # 采纳后失败
        ekb.record_injection_adoption([ids["C"]], None)     # 采纳过但无回执
        # D 从未被采纳，只带形成侧的 success=1
        return ekb, ids

    def test_order_puts_confirmed_first_and_failure_last(self, four_rows):
        ekb, _ids = four_rows
        hits = ekb.find_similar_experiences(
            context={"user_input": QUERY}, agent_id="default", limit=5
        )
        assert _inputs(hits) == [STORED[k] for k in ("A", "D", "C", "B")], (
            "证据为正 > 无采纳记录 > 无回执 > 证据为负；四条都必须仍可见"
        )

    def test_failure_row_is_not_erased(self, four_rows):
        """D1：降权不是消失——失败经验仍要能被查到（它教会我们别这么做）。"""
        ekb, _ids = four_rows
        hits = ekb.find_similar_experiences(
            context={"user_input": QUERY}, agent_id="default", limit=5
        )
        assert STORED["B"] in _inputs(hits)

    def test_scores_are_exposed_for_the_injection_side(self, four_rows):
        ekb, _ids = four_rows
        hits = ekb.find_similar_experiences(
            context={"user_input": QUERY}, agent_id="default", limit=5
        )
        assert [h["adoption_outcome"] for h in hits] == ["success", None, "unevidenced", "failure"]
        scores = [h["similarity_score"] for h in hits]
        assert scores == sorted(scores, reverse=True), "分数与顺序必须自洽"
