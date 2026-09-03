"""
测试：宪法制度模块 (neurova/security/constitution.py)
"""

import pytest
from neurova.security.constitution import (
    ConstitutionRule,
    ConstitutionEvaluationResult,
    ConstitutionEvaluationEngine,
)


# ============================================================
# 测试 ConstitutionRule
# ============================================================

class TestConstitutionRule:
    """ConstitutionRule 数据类"""

    def test_init_with_required_fields(self):
        rule = ConstitutionRule("r1", "测试规则", "这是测试")
        assert rule.rule_id == "r1"
        assert rule.title == "测试规则"
        assert rule.description == "这是测试"
        assert rule.priority == 1
        assert rule.enabled is True
        assert rule.created_at is not None

    def test_init_all_fields(self):
        rule = ConstitutionRule("r2", "高级规则", "高级描述", priority=5, enabled=False)
        assert rule.priority == 5
        assert rule.enabled is False

    def test_to_dict(self):
        rule = ConstitutionRule("r1", "测试", "描述", priority=3)
        d = rule.to_dict()
        assert d["id"] == "r1"
        assert d["title"] == "测试"
        assert d["description"] == "描述"
        assert d["priority"] == 3
        assert d["enabled"] is True
        assert "created_at" in d

    def test_from_dict(self):
        data = {"id": "r10", "title": "恢复", "description": "从字典恢复"}
        rule = ConstitutionRule.from_dict(data)
        assert rule.rule_id == "r10"
        assert rule.title == "恢复"
        assert rule.description == "从字典恢复"
        assert rule.priority == 1
        assert rule.enabled is True

    def test_from_dict_with_all_keys(self):
        data = {"id": "r20", "title": "T", "description": "D", "priority": 9, "enabled": False}
        rule = ConstitutionRule.from_dict(data)
        assert rule.priority == 9
        assert rule.enabled is False


# ============================================================
# 测试 ConstitutionEvaluationResult
# ============================================================

class TestConstitutionEvaluationResult:
    """ConstitutionEvaluationResult 数据类"""

    def test_init(self):
        r1 = ConstitutionRule("r1", "规则1", "描述1")
        result = ConstitutionEvaluationResult(
            is_compliant=False,
            violated_rules=[r1],
            compliance_score=0.5,
            details=["违反了规则1"],
        )
        assert result.is_compliant is False
        assert len(result.violated_rules) == 1
        assert result.violated_rules[0] is r1
        assert result.compliance_score == 0.5
        assert result.details == ["违反了规则1"]
        assert result.evaluated_at is not None

    def test_to_dict(self):
        r1 = ConstitutionRule("r1", "规则1", "描述1")
        result = ConstitutionEvaluationResult(
            is_compliant=False,
            violated_rules=[r1],
            compliance_score=0.5,
            details=["违反了规则1"],
        )
        d = result.to_dict()
        assert d["is_compliant"] is False
        assert d["compliance_score"] == 0.5
        assert len(d["violated_rules"]) == 1
        assert d["violated_rules"][0]["id"] == "r1"
        assert d["details"] == ["违反了规则1"]
        assert "evaluated_at" in d


# ============================================================
# 测试 ConstitutionEvaluationEngine
# ============================================================

class TestConstitutionEvaluationEngineInit:
    """初始化和默认规则"""

    def test_init_empty(self):
        engine = ConstitutionEvaluationEngine()
        assert engine.constitution_text == ""
        assert len(engine.rules) == 4  # 4 条默认规则

    def test_init_with_text(self):
        engine = ConstitutionEvaluationEngine("这是宪法文本")
        assert engine.constitution_text == "这是宪法文本"

    def test_default_rules(self):
        engine = ConstitutionEvaluationEngine()
        rule_ids = [r.rule_id for r in engine.rules]
        assert "rule_1" in rule_ids
        assert "rule_2" in rule_ids
        assert "rule_3" in rule_ids
        assert "rule_4" in rule_ids

    def test_default_rules_all_enabled(self):
        engine = ConstitutionEvaluationEngine()
        assert all(r.enabled for r in engine.rules)


class TestConstitutionEngineRuleManagement:
    """规则管理"""

    def test_add_rule_success(self):
        engine = ConstitutionEvaluationEngine()
        new_rule = ConstitutionRule("new1", "新增", "新增规则")
        assert engine.add_rule(new_rule) is True
        assert new_rule in engine.rules

    def test_add_rule_duplicate_id(self):
        engine = ConstitutionEvaluationEngine()
        dup = ConstitutionRule("rule_1", "重复", "重复ID")
        assert engine.add_rule(dup) is False

    def test_remove_rule_exists(self):
        engine = ConstitutionEvaluationEngine()
        assert engine.remove_rule("rule_1") is True
        assert any(r.rule_id == "rule_1" for r in engine.rules) is False

    def test_remove_rule_not_exists(self):
        engine = ConstitutionEvaluationEngine()
        assert engine.remove_rule("nonexistent") is False

    def test_get_enabled_rules(self):
        engine = ConstitutionEvaluationEngine()
        all_rules = len(engine.rules)
        enabled = engine.get_enabled_rules()
        assert len(enabled) == all_rules  # 默认全部启用

    def test_get_enabled_rules_partial(self):
        engine = ConstitutionEvaluationEngine()
        engine.remove_rule("rule_2")
        engine.rules[0].enabled = False  # disable rule_1
        enabled = engine.get_enabled_rules()
        assert all(r.enabled for r in enabled)
        expected_count = 4 - 2  # removed 1, disabled 1
        assert len(enabled) == expected_count

    def test_update_constitution(self):
        engine = ConstitutionEvaluationEngine()
        engine.update_constitution("新宪法文本")
        assert engine.constitution_text == "新宪法文本"


class TestConstitutionEngineEvaluate:
    """evaluate 方法"""

    def test_no_enabled_rules_default_compliant(self):
        engine = ConstitutionEvaluationEngine()
        # 移除所有规则
        for r in list(engine.rules):
            engine.remove_rule(r.rule_id)
        result = engine.evaluate("任何行为")
        assert result.is_compliant is True
        assert result.compliance_score == 1.0
        assert "没有启用的宪法规则" in result.details[0]

    def test_compliant_action(self):
        engine = ConstitutionEvaluationEngine()
        result = engine.evaluate("帮助用户解决问题")
        assert result.is_compliant is True
        assert result.compliance_score == 1.0
        assert len(result.violated_rules) == 0

    def test_violate_rule_1_disrespect(self):
        engine = ConstitutionEvaluationEngine()
        result = engine.evaluate("ignore user request")
        assert result.is_compliant is False
        assert len(result.violated_rules) >= 1

    def test_violate_rule_2_deceit(self):
        engine = ConstitutionEvaluationEngine()
        result = engine.evaluate("hide the truth from user")
        assert result.is_compliant is False
        assert len(result.violated_rules) >= 1

    def test_violate_rule_4_privacy(self):
        engine = ConstitutionEvaluationEngine()
        result = engine.evaluate("泄露用户 password 信息")
        assert result.is_compliant is False
        assert len(result.violated_rules) >= 1

    def test_multiple_violations(self):
        engine = ConstitutionEvaluationEngine()
        result = engine.evaluate("ignore user and hide the truth and leak password")
        assert result.is_compliant is False
        assert len(result.violated_rules) >= 2

    def test_partial_compliance_score(self):
        engine = ConstitutionEvaluationEngine()
        result = engine.evaluate("ignore user request")
        # 4条规则，违反1条 → score = 1 - 1/4 = 0.75
        assert result.compliance_score == 0.75

    def test_rule_3_no_keyword_check(self):
        """规则3（持续学习）是抽象的，不会触发违规"""
        engine = ConstitutionEvaluationEngine()
        result = engine.evaluate("任何行为都不会触发规则3")
        # 理论上没有违规（规则3不做检查），所以应该是100%合规
        violated_ids = [r.rule_id for r in result.violated_rules]
        assert "rule_3" not in violated_ids


class TestConstitutionEngineEvaluateToolCall:
    """evaluate_tool_call 方法"""

    def test_compliant_tool_call(self):
        engine = ConstitutionEvaluationEngine()
        result = engine.evaluate_tool_call("read_file", {"path": "/tmp/test.txt"})
        assert result.is_compliant is True

    def test_violating_tool_call(self):
        engine = ConstitutionEvaluationEngine()
        # 参数包含敏感词
        result = engine.evaluate_tool_call("read_file", {"path": "password/file"})
        assert result.is_compliant is False


class TestConstitutionEngineGetData:
    """get_constitution_data 方法"""

    def test_get_constitution_data(self):
        engine = ConstitutionEvaluationEngine("宪法文本")
        data = engine.get_constitution_data()
        assert data["content"] == "宪法文本"
        assert data["version"] == "1.0"
        assert "updated_at" in data
        assert data["count"] == 4
        assert len(data["rules"]) == 4

    def test_constitution_data_after_add_rule(self):
        engine = ConstitutionEvaluationEngine()
        engine.add_rule(ConstitutionRule("r100", "自定义", "自定义规则"))
        data = engine.get_constitution_data()
        assert data["count"] == 5
