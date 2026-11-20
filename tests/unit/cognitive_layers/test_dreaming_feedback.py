# -*- coding: utf-8 -*-
"""项 7 收口：Dreaming 反馈采集（审批裁决/回合反馈）与判定面注入。

判据（对齐计划 §6 测试设计）：
- 两条同 kind 纠偏 → 合并为一条候选规则；单条不合并（夜间 sweep 转正）；
- 显式点名一次即成候选；
- 判定面（approvalHint/proactiveSuppressed）只读 active 规则——
  候选未转正时读不到，转正后行为改变且可追溯到原始反馈。
"""
import pytest

from neurova.cognitive_layers.dreaming import (
    candidateRules,
    dreamSweep,
    get_dream_rule_store,
)
from neurova.cognitive_layers.dreaming_feedback import (
    approvalHint,
    classifyFeedback,
    noteApprovalDecision,
    noteTurnFeedback,
    proactiveSuppressed,
)


@pytest.fixture()
def store():
    return get_dream_rule_store()


class TestClassifyFeedback:
    def test_explicit_rule_statement(self):
        assert classifyFeedback("以后不要再用 rm 删文件") == "explicit"
        assert classifyFeedback("记住，别再问我了") == "explicit"

    def test_correction(self):
        assert classifyFeedback("你理解错了，我说的是数据库") == "correction"
        assert classifyFeedback("答非所问") == "correction"

    def test_praise(self):
        assert classifyFeedback("谢谢，很到位") == "praise"

    def test_no_signal(self):
        assert classifyFeedback("帮我查一下天气") is None
        assert classifyFeedback("") is None


class TestTurnFeedbackCollection:
    def test_no_signal_records_nothing(self, store):
        result = noteTurnFeedback("帮我查天气", sessionId="s1")
        assert result["recorded"] is False
        assert store.activeRules() == [] and store.candidateRules() == []

    def test_proactive_pushback_twice_makes_candidate(self, store):
        noteTurnFeedback("别再问我了，烦", sessionId="s1", proactiveQuestion="要提醒吗？")
        # 单条纠偏不合并
        assert store.candidateRules("proactive_ask") == []
        noteTurnFeedback("怎么又问，说过不用", sessionId="s1", proactiveQuestion="要提醒吗？")
        rules = store.candidateRules("proactive_ask")
        assert len(rules) == 1 and rules[0]["decision"] == "suppress"

    def test_explicit_directive_once_makes_candidate(self, store):
        noteTurnFeedback("以后不要自动发邮件", sessionId="s1")
        rules = store.candidateRules("user_directive")
        assert len(rules) == 1
        assert "邮件" in rules[0]["decision"]

    def test_praise_alone_records_nothing(self, store):
        # 感谢暂无判定面消费——不写无读者的账（断点纪律）
        result = noteTurnFeedback("谢谢，很完美", sessionId="s1")
        assert result["recorded"] is False


class TestApprovalDecisionCollection:
    def test_two_denies_same_head_make_candidate(self, store):
        noteApprovalDecision("rm -rf /tmp/a", approved=False, requestId="r1")
        assert store.candidateRules("tool_approval") == []
        noteApprovalDecision("rm -rf /tmp/b", approved=False, requestId="r2")
        rules = store.candidateRules("tool_approval")
        assert len(rules) == 1 and rules[0]["decision"] == "deny:rm"

    def test_approve_and_deny_are_different_rules(self, store):
        # 同命令族的不同裁决各自聚合（kind+decision 二元组），互不合并
        noteApprovalDecision("git push origin main", approved=True, requestId="r1")
        noteApprovalDecision("git push origin dev", approved=True, requestId="r2")
        noteApprovalDecision("git push origin x", approved=False, requestId="r3")
        noteApprovalDecision("git push origin y", approved=False, requestId="r4")
        decisions = {r["decision"] for r in store.candidateRules("tool_approval")}
        assert decisions == {"approve:git", "deny:git"}


class TestDecisionSurfaceInjection:
    def test_proactive_suppressed_only_after_promotion(self, store):
        noteTurnFeedback("别再问我了", sessionId="s1", proactiveQuestion="q")
        noteTurnFeedback("怎么又问", sessionId="s1", proactiveQuestion="q")
        assert proactiveSuppressed() is False, "候选未转正不得改变判定面"
        dreamSweep()
        assert proactiveSuppressed() is True, "转正后主动提问应被抑制"

    def test_approval_hint_only_after_promotion(self, store):
        noteApprovalDecision("rm -rf /tmp/a", approved=False, requestId="r1")
        noteApprovalDecision("rm -rf /tmp/b", approved=False, requestId="r2")
        assert approvalHint("rm -rf /tmp/c") == "", "候选未转正无提示"
        dreamSweep()
        hint = approvalHint("rm -rf /tmp/c")
        assert "拒绝" in hint, hint

    def test_approval_hint_no_rules_empty(self, store):
        assert approvalHint("ls -la") == ""

    def test_explicit_directive_surfaces_in_hint_after_promotion(self, store):
        noteTurnFeedback("以后不要自动执行 rm 命令", sessionId="s1")
        assert approvalHint("rm -rf /tmp/x") == ""
        dreamSweep()
        hint = approvalHint("rm -rf /tmp/x")
        assert "点名" in hint and "rm" in hint, hint
