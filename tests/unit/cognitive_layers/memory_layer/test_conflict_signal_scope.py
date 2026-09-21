"""Issue #72 残余项 · 记忆侧冲突信号必须落在「同一命题的否证」上（红绿灯 TDD）。

现状取证（本文件编写时实测，规则模式 `use_semantic=False`）：

- `_has_negation` 是**子串包含**判断，"不错"里的"不"被当成否定词
  ⇒「今天天气不错」被判为"含否定词"，与任何不含"不"的正面表述构成
  `negation_conflict`（实测 `('今天天气不错','今天天气很好')` 相似度 0.429 即报冲突）。
- `is_conflict = similarity >= 0.3 or contradiction_score >= 0.5`：0.3 的门几乎
  等于"只要有点像就算冲突"，同一轮的复述（`"用户: 今天天气不错"` 与其加长版）
  实测相似度 0.643，也报 `negation_conflict`。
- 于是这条链的产物是噪声：真矛盾的"正常/故障"（实测相似度 0.2）与寒暄复述
  （0.643）混在同一批 `negation_conflict` 里，下游无从分辨——这正是它只能
  "纯观测"的根因（判不出哪条为准，因为根本判不出哪些是真冲突）。

契约（本文件锁定）：
- 信号必须建立在**同一命题**之上：把否定词折掉后命题仍近乎相同，才谈得上
  "一方否证了另一方"（`我喜欢咖啡` vs `我不喜欢咖啡` 是真否证；
  `今天天气不错` vs `今天天气很好` 不是）。
- 矛盾词对（`正常/故障`、`提升/下降`）仍是独立信号，但要求两侧**共享同一对象**：
  `性能提升了` vs `性能下降了` 是矛盾；`成本增加了` vs `效率减少了` 不是。
- 一轮对话是两个说话人的两段话，矛盾住在**子句**里：`"用户: X\\n助手: Y"`
  必须能与其子句逐条对上，不能整团比较。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from neurova.cognitive_layers.memory_layer.conflict import LegacyConflictDetector


@pytest.fixture()
def detector():
    return LegacyConflictDetector(use_semantic=False)


def _pair(detector, left: str, right: str):
    return detector._check_pair_conflict(
        SimpleNamespace(id="a", content=left),
        SimpleNamespace(id="b", content=right),
    )


class TestNegationIsNotSubstringPresence:
    def test_positivePhraseWithNegatorInsideAWordIsNotANegation(self, detector):
        """「不错」是正面表述：与其近义表达不得被判成一方否证了另一方。"""
        assert _pair(detector, "今天天气不错", "今天天气很好") is None

    def test_samePropositionRestatedIsNotAConflict(self, detector):
        """复述同一件事（同一轮加长版）不是冲突。"""
        assert _pair(detector, "用户: 我喜欢咖啡\n助手: 好的", "用户: 我喜欢咖啡") is None
        assert _pair(detector, "用户: 今天天气不错\n助手: 嗯哼", "用户: 今天天气不错") is None
        assert _pair(detector, "建议先加护栏\n助手: 同意", "建议先加护栏\n助手: 同意") is None


class TestRealNegationStillFires:
    def test_asymmetricNegationOverTheSamePropositionFires(self, detector):
        conflict = _pair(detector, "我喜欢咖啡", "我不喜欢咖啡")
        assert conflict is not None, "同一命题的否证必须报出"
        assert conflict["type"] == "negation_conflict"

    def test_speakerPrefixedTurnStillFires(self, detector):
        """带说话人前缀的一整轮，仍要能与被否证的那条对上。"""
        conflict = _pair(detector, "用户: 我不喜欢咖啡\n助手: 好的", "用户喜欢咖啡")
        assert conflict is not None, "子句级对不上就等于这条链看不见真矛盾"
        assert conflict["type"] == "negation_conflict"

    def test_contradictionPairFiresWithoutSimilarPropositions(self, detector):
        conflict = _pair(detector, "系统运行正常", "系统出故障了")
        assert conflict is not None
        assert conflict["type"] == "semantic_contradiction"

        # 同一对象的两极取值才算矛盾；两个不同对象各自变化（成本增加/效率减少）
        # 不是矛盾，不得报出。
        sameObject = _pair(detector, "性能提升了", "性能下降了")
        assert sameObject is not None
        assert sameObject["type"] == "semantic_contradiction"

        assert _pair(detector, "成本增加了", "效率减少了") is None


class TestSignalCarriesItsOwnProvision:
    def test_conflictNamesTheClauseItCompared(self, detector):
        """报出的冲突必须自带"凭哪两句话认定的"——下游的裁决依据从这里来。

        依据只留一个字段（`basis`），逐字带出被比较的两个子句：多留一份结构化的
        子句等于同一件事两份定义，且没有读方。
        """
        conflict = _pair(detector, "用户: 系统怎么样\n助手: 系统出故障了", "系统运行正常")

        assert conflict is not None
        assert conflict.get("basis"), "未记下判定依据"
        assert "故障" in conflict["basis"], "依据里要点名新说法的子句"
        assert "正常" in conflict["basis"], "依据里要点名既有说法的子句"


class TestDetectConflictAggregatesClauseLevel:
    def test_turnIsComparedClauseByClause(self, detector):
        from neurova.cognitive_layers.memory_layer.models import Memory

        new_memory = Memory(id="n1", content="用户: 我不喜欢咖啡\n助手: 好的")
        existing = [Memory(id="e1", content="用户喜欢咖啡")]

        conflicts = detector.detect_conflict(new_memory, existing)

        assert len(conflicts) == 1
        assert conflicts[0]["memory2_id"] == "e1"
