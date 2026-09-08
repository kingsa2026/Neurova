"""
测试：宪法制度模块 (neurova/security/constitution.py)

对齐实现契约（2026-09-08 台账收口）：
- ConstitutionRule 为规则引擎数据类：rule_id/name/description/rule_type/
  severity/condition/action（required），priority 默认 100；
- ConstitutionEvaluationEngine 默认 5 条规则（safety_001/ethics_001/
  ethics_002/performance_001/compliance_001）；
- evaluate(context: Dict) 按 severity 分流 violations/warnings，
  score = 1 - 违规数/启用规则数；
- get_constitution_data 返回 rules/total_rules/enabled_rules/updated_at。
"""

import pytest
from neurova.security.constitution import (
    ConstitutionRule,
    ConstitutionEvaluationResult,
    ConstitutionEvaluationEngine,
    RuleType,
    RuleSeverity,
)


def _make_rule(rule_id="r1", **overrides):
    kwargs = dict(
        rule_id=rule_id,
        name="测试规则",
        description="这是测试",
        rule_type=RuleType.SAFETY,
        severity=RuleSeverity.HIGH,
        condition="content.contains_harmful",
        action="block",
    )
    kwargs.update(overrides)
    return ConstitutionRule(**kwargs)


# ============================================================
# 测试 ConstitutionRule
# ============================================================

class TestConstitutionRule:
    """ConstitutionRule 数据类"""

    def test_init_with_required_fields(self):
        rule = _make_rule()
        assert rule.rule_id == "r1"
        assert rule.name == "测试规则"
        assert rule.description == "这是测试"
        assert rule.rule_type == RuleType.SAFETY
        assert rule.severity == RuleSeverity.HIGH
        assert rule.condition == "content.contains_harmful"
        assert rule.action == "block"
        assert rule.priority == 100
        assert rule.enabled is True
        assert rule.created_at is not None

    def test_init_all_fields(self):
        rule = _make_rule("r2", priority=5, enabled=False)
        assert rule.priority == 5
        assert rule.enabled is False

    def test_to_dict(self):
        rule = _make_rule("r1", priority=3)
        d = rule.to_dict()
        assert d["rule_id"] == "r1"
        assert d["name"] == "测试规则"
        assert d["priority"] == 3
        assert d["enabled"] is True
        assert d["rule_type"] == "safety"
        assert d["severity"] == "high"

    def test_to_dict_roundtrip(self):
        rule = _make_rule("rt")
        restored = ConstitutionRule.from_dict(rule.to_dict())
        assert restored.rule_id == rule.rule_id
        assert restored.rule_type == rule.rule_type
        assert restored.severity == rule.severity

    def test_from_dict(self):
        data = {
            "rule_id": "r10",
            "name": "恢复",
            "description": "从字典恢复",
            "rule_type": "ethics",
            "severity": "low",
            "condition": "x",
            "action": "warn",
        }
        rule = ConstitutionRule.from_dict(data)
        assert rule.rule_id == "r10"
        assert rule.name == "恢复"
        assert rule.rule_type == RuleType.ETHICS
        assert rule.severity == RuleSeverity.LOW


# ============================================================
# 测试 ConstitutionEvaluationResult
# ============================================================

class TestConstitutionEvaluationResult:

    def test_init(self):
        result = ConstitutionEvaluationResult(
            is_compliant=False,
            violations=[{"rule_id": "safety_001"}],
            warnings=[],
            score=0.5,
        )
        assert result.is_compliant is False
        assert len(result.violations) == 1
        assert result.score == 0.5
        assert result.evaluated_at is not None

    def test_to_dict(self):
        result = ConstitutionEvaluationResult(
            is_compliant=True, violations=[], warnings=[], score=1.0
        )
        d = result.to_dict()
        assert d["is_compliant"] is True
        assert "evaluated_at" in d


# ============================================================
# 测试 ConstitutionEvaluationEngine
# ============================================================

class TestConstitutionEvaluationEngineInit:
    """初始化和默认规则"""

    def test_default_rules_count(self):
        engine = ConstitutionEvaluationEngine()
        assert len(engine.rules) == 5

    def test_default_rules_ids(self):
        engine = ConstitutionEvaluationEngine()
        rule_ids = set(engine.rules.keys())
        assert rule_ids == {"safety_001", "ethics_001", "ethics_002", "performance_001", "compliance_001"}

    def test_default_rules_all_enabled(self):
        engine = ConstitutionEvaluationEngine()
        assert all(r.enabled for r in engine.rules.values())


class TestConstitutionEngineRuleManagement:
    """规则管理"""

    def test_add_rule_success(self):
        engine = ConstitutionEvaluationEngine()
        new_rule = _make_rule("new1")
        engine.add_rule(new_rule)
        assert engine.rules["new1"] is new_rule

    def test_add_rule_duplicate_id(self):
        engine = ConstitutionEvaluationEngine()
        dup = _make_rule("safety_001")
        engine.add_rule(dup)  # 覆盖/拒绝均可，规则数不增
        assert len(engine.rules) == 5

    def test_remove_rule_exists(self):
        engine = ConstitutionEvaluationEngine()
        assert engine.remove_rule("safety_001") is True
        assert "safety_001" not in engine.rules

    def test_remove_rule_not_exists(self):
        engine = ConstitutionEvaluationEngine()
        assert engine.remove_rule("nonexistent") is False

    def test_get_enabled_rules(self):
        engine = ConstitutionEvaluationEngine()
        enabled = engine.get_enabled_rules()
        assert len(enabled) == 5

    def test_get_enabled_rules_partial(self):
        engine = ConstitutionEvaluationEngine()
        engine.remove_rule("ethics_001")
        engine.rules["safety_001"].enabled = False
        enabled = engine.get_enabled_rules()
        assert all(r.enabled for r in enabled)
        assert len(enabled) == 3

    def test_update_constitution(self):
        engine = ConstitutionEvaluationEngine()
        rules_data = [_make_rule("new_r", name="n").to_dict()]
        engine.update_constitution(rules_data)
        assert "new_r" in engine.rules


class TestConstitutionEngineEvaluate:
    """evaluate(context: Dict) 方法"""

    def test_no_enabled_rules_default_compliant(self):
        engine = ConstitutionEvaluationEngine()
        for rid in list(engine.rules.keys()):
            engine.remove_rule(rid)
        result = engine.evaluate({"content": "任何行为"})
        assert result.is_compliant is True
        assert result.score == 1.0

    def test_compliant_action(self):
        engine = ConstitutionEvaluationEngine()
        result = engine.evaluate({"content": "帮助用户解决问题"})
        assert result.is_compliant is True
        assert result.score == 1.0
        assert len(result.violations) == 0

    def test_violate_safety_rule(self):
        engine = ConstitutionEvaluationEngine()
        result = engine.evaluate({"content": "生成暴力内容"})
        assert result.is_compliant is False
        assert len(result.violations) >= 1
        assert result.violations[0]["rule_id"] == "safety_001"

    def test_discrimination_violation(self):
        engine = ConstitutionEvaluationEngine()
        result = engine.evaluate({"content": "含有种族歧视言论"})
        assert result.is_compliant is False
        assert len(result.violations) >= 1

    def test_multiple_violations(self):
        engine = ConstitutionEvaluationEngine()
        result = engine.evaluate({"content": "暴力内容且种族歧视言论"})
        assert result.is_compliant is False
        assert len(result.violations) >= 2

    def test_partial_compliance_score(self):
        engine = ConstitutionEvaluationEngine()
        result = engine.evaluate({"content": "生成暴力内容"})
        # 5 条启用规则，违规 1 条 → score = 1 - 1/5 = 0.8
        assert result.score == pytest.approx(0.8)

    def test_low_severity_goes_to_warnings(self):
        """MEDIUM/LOW severity 违规进 warnings 不进 violations（合规仍 True）。"""
        engine = ConstitutionEvaluationEngine()
        # performance_001 是 MEDIUM/warn；violations 只收 CRITICAL/HIGH
        result = engine.evaluate({"content": "ok", "response_time": 60})
        assert all(v["rule_id"] != "performance_001" for v in result.violations)


class TestConstitutionEngineEvaluateToolCall:
    """evaluate_tool_call 方法"""

    def test_compliant_tool_call(self):
        engine = ConstitutionEvaluationEngine()
        result = engine.evaluate_tool_call("read_file", {"path": "/tmp/test.txt"})
        assert result.is_compliant is True

    def test_violating_tool_call(self):
        engine = ConstitutionEvaluationEngine()
        # 参数序列化进 content，含敏感关键词即触发
        result = engine.evaluate_tool_call("read_file", {"path": "暴力/file"})
        assert result.is_compliant is False


class TestConstitutionEngineGetData:
    """get_constitution_data 方法"""

    def test_get_constitution_data(self):
        engine = ConstitutionEvaluationEngine()
        data = engine.get_constitution_data()
        assert data["total_rules"] == 5
        assert data["enabled_rules"] == 5
        assert len(data["rules"]) == 5
        assert "updated_at" in data

    def test_constitution_data_after_add_rule(self):
        engine = ConstitutionEvaluationEngine()
        engine.add_rule(_make_rule("r100"))
        data = engine.get_constitution_data()
        assert data["total_rules"] == 6
        assert any(r["rule_id"] == "r100" for r in data["rules"])
