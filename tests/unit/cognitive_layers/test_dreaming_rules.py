# -*- coding: utf-8 -*-
"""Dreaming 式规则自改进测试（实施计划项 7：夜间 clue→candidate→active）。

锁定四条任务判据（先红后绿）：
a) 两条同 kind clue → 自动生成 candidate 规则；单条不生成；
b) 显式反馈（explicit=True）单次即候选；
c) dreamSweep 转正后 activeRules 可读、判定面读不到 clue；
d) 不同 kind 不互相合并。

另钉住：S16 同闸（敏感判定文本不自动转正，fail-closed 留候审）、
门控 NEUROVA_DREAMING=0 直通、夜间接线点（idle_tracker 睡眠窗口调用 dreamSweep）。
"""
import ast
import io
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
IDLE_TRACKER = PROJECT_ROOT / "neurova" / "core" / "idle_tracker.py"


@pytest.fixture(autouse=True)
def _enableDreaming(monkeypatch):
    """默认开启功能门控（个别用例自行改写）。"""
    monkeypatch.setenv("NEUROVA_DREAMING", "1")


@pytest.fixture()
def store(tmp_path):
    from neurova.cognitive_layers.dreaming import DreamRuleStore

    s = DreamRuleStore(db_path=tmp_path / "dreaming_rules.db")
    yield s
    s.close()


@pytest.fixture()
def dreamingApi(store, monkeypatch):
    """模块级 API 指向临时库（单例注入，不落数据根）。"""
    import neurova.cognitive_layers.dreaming as dreaming

    monkeypatch.setattr(dreaming, "get_dream_rule_store", lambda: store)
    return dreaming


# ──────────────────────────────────────────────────────────────
# a/b/d：clue 记录与候选生成
# ──────────────────────────────────────────────────────────────


class TestClueToCandidate:
    def test_twoSameKindCluesAutoCreateCandidate(self, dreamingApi):
        """a) 同 kind 同 decision 两条 clue → 自动生成 candidate 规则。"""
        first = dreamingApi.recordClue("reply_style", "回复更简洁", evidence_ref="fb-1")
        assert first["rule"] is None, "首条普通 clue 不得生成规则"
        second = dreamingApi.recordClue("reply_style", "回复更简洁", evidence_ref="fb-2")
        rule = second["rule"]
        assert rule is not None
        assert rule["kind"] == "reply_style"
        assert rule["decision"] == "回复更简洁"
        assert rule["status"] == "candidate"
        assert rule["activated_at"] is None, "candidate 尚未转正，不得带生效时刻"
        # 线索聚合计数：同 kind 同 decision 累加到 2，规则可追溯到该线索
        assert second["clue"]["count"] == 2
        assert rule["source_clue_ids"] == [second["clue"]["id"]]

    def test_singleClueDoesNotCreateRule(self, dreamingApi):
        """a) 单条普通 clue 不生成规则。"""
        result = dreamingApi.recordClue("reply_style", "回复更简洁", evidence_ref="fb-1")
        assert result["rule"] is None
        assert dreamingApi.candidateRules() == []
        assert dreamingApi.activeRules() == []

    def test_explicitSingleClueBecomesCandidate(self, dreamingApi):
        """b) 显式反馈（explicit=True）单次即候选。"""
        result = dreamingApi.recordClue(
            "proactive_timing", "静默时段勿打扰", evidence_ref="fb-explicit", explicit=True
        )
        rule = result["rule"]
        assert rule is not None, "显式点名单次即须成候选规则"
        assert rule["status"] == "candidate"
        assert result["clue"]["explicit_count"] == 1

    def test_differentKindsDoNotMerge(self, dreamingApi):
        """d) 不同 kind 即使 decision 相同也不合并计数、不生成规则。"""
        first = dreamingApi.recordClue("kind_a", "同一决策", evidence_ref="fb-a1")
        second = dreamingApi.recordClue("kind_b", "同一决策", evidence_ref="fb-b1")
        assert first["clue"]["id"] != second["clue"]["id"]
        assert first["clue"]["count"] == 1
        assert second["clue"]["count"] == 1, "不同 kind 的计数必须各自独立"
        assert first["rule"] is None and second["rule"] is None

    def test_sameKindDifferentDecisionDoesNotMerge(self, dreamingApi):
        """同 kind 不同 decision 同样不互并（聚合键 = kind+decision 二元组）。"""
        dreamingApi.recordClue("reply_style", "回复更简洁", evidence_ref="fb-1")
        result = dreamingApi.recordClue("reply_style", "先给结论", evidence_ref="fb-2")
        assert result["clue"]["count"] == 1
        assert result["rule"] is None

    def test_emptyKindOrDecisionRejected(self, dreamingApi):
        """fail-closed：kind/decision 缺失当场报错，不落半行。"""
        with pytest.raises(ValueError):
            dreamingApi.recordClue("", "某决策")
        with pytest.raises(ValueError):
            dreamingApi.recordClue("某类", "  ")


# ──────────────────────────────────────────────────────────────
# c：夜间 sweep 转正与判定面读法
# ──────────────────────────────────────────────────────────────


class TestDreamSweepPromotion:
    def test_sweepPromotesCandidateAndJudgementFaceReadsOnlyActive(self, dreamingApi):
        """c) dreamSweep 后 activeRules 可读；判定面读不到 clue。"""
        dreamingApi.recordClue("reply_style", "回复更简洁", evidence_ref="fb-1")
        dreamingApi.recordClue("reply_style", "回复更简洁", evidence_ref="fb-2")

        sweep = dreamingApi.dreamSweep()
        assert sweep["scanned"] == 1
        assert len(sweep["promoted"]) == 1
        assert sweep["promoted"][0]["status"] == "active"
        assert sweep["promoted"][0]["activated_at"] is not None

        active = dreamingApi.activeRules("reply_style")
        assert len(active) == 1
        rule = active[0]
        assert rule["kind"] == "reply_style"
        assert rule["decision"] == "回复更简洁"
        # 判定面只暴露转正规则本身：clue 侧字段（evidence_ref/count）不得出现
        assert "evidence_ref" not in rule
        assert "count" not in rule
        assert "source_clue_ids" in rule, "规则须保留来源线索引用以便追溯"

    def test_unpromotedClueInvisibleToJudgementFace(self, dreamingApi):
        """c) 未达门槛的单条 clue 对判定面不可见。"""
        dreamingApi.recordClue("reply_style", "回复更简洁", evidence_ref="fb-1")
        dreamingApi.dreamSweep()
        assert dreamingApi.activeRules("reply_style") == []
        assert dreamingApi.activeRules() == []

    def test_activeRulesFiltersByKind(self, dreamingApi):
        dreamingApi.recordClue("kind_a", "决策甲", evidence_ref="fb-1", explicit=True)
        dreamingApi.recordClue("kind_b", "决策乙", evidence_ref="fb-2", explicit=True)
        dreamingApi.dreamSweep()
        assert [r["kind"] for r in dreamingApi.activeRules("kind_a")] == ["kind_a"]
        assert {r["kind"] for r in dreamingApi.activeRules()} == {"kind_a", "kind_b"}

    def test_sweepIsIdempotent(self, dreamingApi):
        dreamingApi.recordClue("reply_style", "回复更简洁", evidence_ref="fb-1", explicit=True)
        first = dreamingApi.dreamSweep()
        second = dreamingApi.dreamSweep()
        assert len(first["promoted"]) == 1
        assert second["scanned"] == 0, "已转正规则不得被重复扫描/重复转正"
        assert second["promoted"] == []

    def test_sensitiveDecisionHeldForReviewFailClosed(self, dreamingApi):
        """S16 同闸：判定文本命中敏感模式族 → 不自动转正，留候审（fail-closed）。"""
        dreamingApi.recordClue(
            "credential_note", "password=hunter2 绝不写入回复", evidence_ref="fb-1", explicit=True
        )
        sweep = dreamingApi.dreamSweep()
        assert sweep["promoted"] == [], "敏感命中不得转正"
        assert len(sweep["heldForReview"]) == 1
        held = sweep["heldForReview"][0]
        assert held["rule"]["status"] == "candidate", "敏感候选保持 candidate 待人工处置"
        assert held["reason"], "须给出可解释的拦截原因"
        assert dreamingApi.activeRules("credential_note") == []

    def test_gateDisabledNoops(self, store, monkeypatch):
        """门控 NEUROVA_DREAMING=0：recordClue/dreamSweep 直通不做。"""
        import neurova.cognitive_layers.dreaming as dreaming

        monkeypatch.setenv("NEUROVA_DREAMING", "0")
        monkeypatch.setattr(dreaming, "get_dream_rule_store", lambda: store)
        result = dreaming.recordClue("reply_style", "回复更简洁", evidence_ref="fb-1")
        assert result["recorded"] is False
        sweep = dreaming.dreamSweep()
        assert sweep["promoted"] == [] and sweep["scanned"] == 0
        assert store.activeRules() == []


# ──────────────────────────────────────────────────────────────
# 夜间接线：睡眠窗口调度位必须调用 dreamSweep
# ──────────────────────────────────────────────────────────────


class TestNightWiring:
    def test_idleTrackerConsolidationCallsDreamSweep(self):
        """接线守卫：idle_tracker._trigger_consolidation（睡眠窗口唯一漏斗）
        必须惰性引入并调用 dreamSweep——夜间 sweep 挂既有调度位，不另起定时器。"""
        from neurova.core.ast_scan import parseSource

        source = io.open(IDLE_TRACKER, encoding="utf-8").read()
        tree = parseSource(source)
        sweepCalls = []
        for node in ast.walk(tree):
            if not (isinstance(node, ast.FunctionDef) and node.name == "_trigger_consolidation"):
                continue
            funcSrc = ast.get_source_segment(source, node) or ""
            assert "dreamSweep(" in funcSrc, "睡眠整理漏斗未调用 dreamSweep"
            assert "from neurova.cognitive_layers.dreaming import" in funcSrc, (
                "dreaming 须在函数内惰性引入（§3 深模块纪律，禁模块级直连）"
            )
            assert "dreamingEnabled()" in funcSrc, "接线必须过功能门控"
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call):
                    name = sub.func.attr if isinstance(sub.func, ast.Attribute) else getattr(sub.func, "id", "")
                    if name == "dreamSweep":
                        sweepCalls.append(name)
        assert sweepCalls, "_trigger_consolidation 内必须有 dreamSweep 调用点"
