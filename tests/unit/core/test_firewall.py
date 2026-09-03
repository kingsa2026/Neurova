"""
测试防火墙模块
"""
import pytest
from unittest.mock import patch, MagicMock
from neurova.core.firewall import (
    GlobalRuleSet,
    UserRuleSet,
    AgentFirewall,
    get_firewall,
    reset_firewall,
)


class TestGlobalRuleSet:
    """测试GlobalRuleSet类"""

    def test_init_defaults(self):
        """测试初始化默认值"""
        rules = GlobalRuleSet()

        assert isinstance(rules.blocked_paths, list)
        assert len(rules.blocked_paths) > 0
        assert rules.rate_limit_per_minute == 60
        assert rules.max_input_length == 10000
        assert isinstance(rules.sensitive_output_patterns, list)
        assert isinstance(rules.llm_trust_domains, list)

    def test_to_dict(self):
        """测试转换为字典"""
        rules = GlobalRuleSet()
        data = rules.to_dict()

        assert "blocked_paths" in data
        assert "rate_limit_per_minute" in data
        assert "sensitive_output_patterns" in data
        assert "llm_trust_domains" in data


class TestUserRuleSet:
    """测试UserRuleSet类"""

    def test_init_defaults(self):
        """测试初始化默认值"""
        rules = UserRuleSet()

        assert rules.extra_blocked_paths == []
        assert rules.agent_isolation is True

    def test_to_dict(self):
        """测试转换为字典"""
        rules = UserRuleSet()
        data = rules.to_dict()

        assert "extra_blocked_paths" in data
        assert "agent_isolation" in data


class TestAgentFirewall:
    """测试AgentFirewall类"""

    def test_init(self):
        """测试初始化"""
        firewall = AgentFirewall()

        assert firewall._global_rules is not None
        assert firewall._user_rules == {}
        assert firewall._rate_counters == {}

    def test_get_global_rules(self):
        """测试获取全局规则"""
        firewall = AgentFirewall()
        rules = firewall.get_global_rules()

        assert isinstance(rules, dict)
        assert "blocked_paths" in rules
        assert "rate_limit_per_minute" in rules

    def test_get_user_rules(self):
        """测试获取用户规则"""
        firewall = AgentFirewall()
        rules = firewall.get_user_rules("test_user")

        assert isinstance(rules, dict)
        assert rules == {}

    def test_update_user_rules(self):
        """测试更新用户规则"""
        firewall = AgentFirewall()
        firewall.update_user_rules("test_user", {
            "extra_blocked_paths": ["/custom/path"],
            "agent_isolation": False,
        })

        rules = firewall.get_user_rules("test_user")
        assert "/custom/path" in rules["extra_blocked_paths"]
        assert rules["agent_isolation"] is False

    def test_get_effective_rules(self):
        """测试获取有效规则"""
        firewall = AgentFirewall()
        firewall.update_user_rules("test_user", {
            "extra_blocked_paths": ["/custom/path"],
        })

        effective = firewall.get_effective_rules("test_user")

        assert len(effective["blocked_paths"]) > 0
        assert "/custom/path" in effective["blocked_paths"]

    def test_validate_input_clean(self):
        """测试验证正常输入"""
        firewall = AgentFirewall()
        ok, reason = firewall.validate_input("这是一段正常的文本")

        assert ok is True

    def test_validate_input_too_long(self):
        """测试验证超长输入"""
        firewall = AgentFirewall()
        long_text = "a" * 20000
        ok, reason = firewall.validate_input(long_text)

        assert ok is False
        assert "max length" in reason.lower()

    def test_sanitize_output(self):
        """测试输出脱敏"""
        firewall = AgentFirewall()
        sensitive = "我的API密钥是sk-1234567890abcdef"

        sanitized = firewall.sanitize_output(sensitive)

        assert "sk-1234567890abcdef" not in sanitized

    def test_sanitize_output_no_sensitive(self):
        """测试无敏感信息的输出"""
        firewall = AgentFirewall()
        clean = "这是一段正常的文本"
        sanitized = firewall.sanitize_output(clean)
        assert sanitized == clean

    def test_check_file_access_blocked_path(self):
        """测试检查被阻止的文件路径"""
        firewall = AgentFirewall()

        ok, reason = firewall.check_file_access("/etc/passwd")
        assert ok is False

    def test_check_file_access_allowed(self):
        """测试检查允许的文件路径"""
        firewall = AgentFirewall()

        ok, reason = firewall.check_file_access("/workspace/test_user/file.txt")
        assert ok is True

    def test_check_agent_access_same_user(self):
        """测试检查同一用户的代理访问"""
        firewall = AgentFirewall()

        ok, reason = firewall.check_agent_access("agent1", "agent1", "user1")
        assert ok is True

    def test_check_agent_access_different_user_isolated(self):
        """测试检查不同代理的访问（默认隔离）"""
        firewall = AgentFirewall()

        ok, reason = firewall.check_agent_access("agent1", "agent2", "user1")
        assert ok is False

    def test_check_agent_access_different_no_isolation(self):
        """测试无隔离时的跨代理访问"""
        firewall = AgentFirewall()
        firewall.update_user_rules("test_user", {"agent_isolation": False})

        ok, reason = firewall.check_agent_access("agent1", "agent2", "test_user")
        assert ok is True

    def test_is_llm_internal(self):
        """测试检查是否为LLM内部路径"""
        firewall = AgentFirewall()

        assert firewall.is_llm_internal("api.openai.com") is True
        assert firewall.is_llm_internal("localhost") is True
        assert firewall.is_llm_internal("127.0.0.1") is True
        assert firewall.is_llm_internal("example.com") is False

    def test_check_ip_access(self):
        """测试检查IP访问"""
        firewall = AgentFirewall()

        ok, reason = firewall.check_ip_access("127.0.0.1")
        assert ok is True

    def test_check_rate_limit(self):
        """测试速率限制"""
        firewall = AgentFirewall()

        ok, reason = firewall.check_rate_limit("test_user")
        assert ok is True

    def test_is_agent_isolated(self):
        """测试检查用户隔离状态"""
        firewall = AgentFirewall()

        assert firewall.is_agent_isolated("unknown_user") is True

        firewall.update_user_rules("test_user", {"agent_isolation": False})
        assert firewall.is_agent_isolated("test_user") is False

    def test_update_global_rules(self):
        """测试更新全局规则"""
        firewall = AgentFirewall()
        firewall.update_global_rules({"rate_limit_per_minute": 120})

        rules = firewall.get_global_rules()
        assert rules["rate_limit_per_minute"] == 120


class TestGlobalFunctions:
    """测试全局函数"""

    def test_get_firewall(self):
        """测试获取防火墙实例"""
        reset_firewall()
        firewall1 = get_firewall()
        firewall2 = get_firewall()

        assert firewall1 is firewall2

    def test_reset_firewall(self):
        """测试重置防火墙"""
        reset_firewall()
        firewall1 = get_firewall()
        reset_firewall()
        firewall2 = get_firewall()

        assert firewall1 is not firewall2
