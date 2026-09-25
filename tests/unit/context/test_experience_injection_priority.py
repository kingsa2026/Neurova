"""007 · 注入侧优先级必须吃质量，而不是硬编码 70/80（红绿灯 TDD）。

根因：`dedupe_experience_sources`（`context/orchestrator.py:1737`）给所有普通经验
固定 priority=70、给结晶产物固定 80，与条目本身是好是坏无关；`chat_pipeline` 对
失败经验也只加一个 `✗` 前缀就算处置完了。于是"上次照这条经验做砸了"与
"上次照这条经验做成了"在 prompt 里同权争位。

落定契约：优先级由 006 的采纳后证据决定
（`success 78 > 无记录 70 > unevidenced 65 > failure 55`），
结晶产物的 80 基准不动（其生命周期归 017）；证据缺席一律回落到 70，
不得凭"没测到"升权也不得凭"没测到"降权。
"""

from __future__ import annotations

from neurova.context.orchestrator import dedupe_experience_sources


def _prio_by_outcome(outcome):
    item = {"content": "同一条经验", "adoption_outcome": outcome}
    return dedupe_experience_sources([item], [])[0][2]


class TestInjectionPriorityFollowsEvidence:
    def test_confirmed_adopted_outranks_never_adopted(self):
        assert _prio_by_outcome("success") > _prio_by_outcome(None)

    def test_failure_is_downweighted_below_unevidenced(self):
        assert _prio_by_outcome("failure") < _prio_by_outcome("unevidenced")

    def test_unevidenced_is_visible_but_below_unadopted(self):
        """D1：无回执既不消失，也不与"至少确证过成功"的条目同权。"""
        assert _prio_by_outcome(None) > _prio_by_outcome("unevidenced") > _prio_by_outcome("failure")

    def test_absent_field_falls_back_to_baseline_not_bonus(self):
        """缺字段（旧条目/其他生产者）不得被当成"证据为负"而降权。"""
        item = {"content": "没有采纳字段的经验"}
        prio = dedupe_experience_sources([item], [])[0][2]
        assert prio == _prio_by_outcome(None) == 70

    def test_crystallized_baseline_unchanged(self):
        tag, _content, prio = dedupe_experience_sources([], [{"content": "结晶模式"}])[0]
        assert (tag, prio) == ("[结晶经验] ", 80)

    def test_dedup_still_prefers_crystallized_copy(self):
        """同内容并存时仍只留一份，且留的是结晶那份（007 不得把去重打回去）。"""
        out = dedupe_experience_sources(
            [{"content": "先抓取再解析", "adoption_outcome": "success"}],
            [{"content": "先抓取再解析"}],
        )
        assert len(out) == 1 and out[0][0] == "[结晶经验] "


class TestOperatorDispositionPriorityRidesTheSameSeam:
    """工单 015：人工处置接进 007 的优先级机制，而不是另建一套池子。

    优先级表只多一档 `demoted 45`（压在 failure 55 之下）；`endorsed` **不占档**——
    人工说"这条我看过了、可以用"不等于"这条被执行成功过"，让它冒领 78 就是把
    判断洗成证据（008 的 `adoption_success_rate` 会跟着一起被骗）。
    """

    def _prio(self, outcome, disposition):
        item = {"content": "同一条经验", "adoption_outcome": outcome, "operator_disposition": disposition}
        return dedupe_experience_sources([item], [])[0][2]

    def test_demoted_falls_below_every_evidence_tier(self):
        demoted = self._prio("failure", "demoted")
        assert demoted < min(
            _prio_by_outcome(t) for t in ("success", "unevidenced", "failure", None)
        ), "降权档必须低于全部证据档，否则降了等于没降"
        assert demoted == 45

    def test_demote_bites_regardless_of_the_evidence_tier(self):
        """反向锁：确证成功的条目被降权后也要掉下来，不能靠高档位免疫。"""
        assert self._prio("success", "demoted") == 45 < _prio_by_outcome("success")

    def test_endorsed_does_not_buy_the_success_tier(self):
        assert self._prio(None, "endorsed") == _prio_by_outcome(None) == 70
        assert self._prio("unevidenced", "endorsed") == _prio_by_outcome("unevidenced") == 65

    def test_restored_disposition_returns_to_its_evidence_tier(self):
        assert self._prio("failure", None) == _prio_by_outcome("failure") == 55
