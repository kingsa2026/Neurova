"""
BrowserBackendCapability 单元测试

测试目标：
1. BrowserBackendCapability 类的能力描述
2. 能力查询
3. LLM 上下文生成
"""

import pytest
from unittest.mock import MagicMock, patch
import sys

# 导入被测模块
from neurova.tool_layers.browser_capability import BrowserBackendCapability


class TestBrowserBackendCapability:
    """BrowserBackendCapability 类测试"""

    def test_initialization(self):
        """测试初始化"""
        capability = BrowserBackendCapability(
            backend_name="playwright",
            capabilities=["click", "type", "navigate", "screenshot"],
            limitations=["no_mobile", "no_geolocation"],
            best_for=["web_automation", "testing"],
            max_pages=10,
            supports_mobile=False,
            supports_geolocation=False
        )
        
        assert capability.backend_name == "playwright"
        assert "click" in capability.capabilities
        assert "no_mobile" in capability.limitations
        assert "web_automation" in capability.best_for
        assert capability.max_pages == 10
        assert capability.supports_mobile == False
        assert capability.supports_geolocation == False

    def test_defaults(self):
        """测试默认值"""
        capability = BrowserBackendCapability(backend_name="simple_browser")
        
        assert capability.backend_name == "simple_browser"
        assert capability.capabilities == []
        assert capability.limitations == []
        assert capability.best_for == []
        assert capability.max_pages == 1
        assert capability.supports_mobile == False
        assert capability.supports_geolocation == False

    def test_has_capability(self):
        """测试能力检查"""
        capability = BrowserBackendCapability(
            backend_name="test_browser",
            capabilities=["click", "type", "navigate"]
        )
        
        assert capability.has_capability("click") == True
        assert capability.has_capability("type") == True
        assert capability.has_capability("navigate") == True
        assert capability.has_capability("screenshot") == False
        assert capability.has_capability("mobile") == False

    def test_has_any_capability(self):
        """测试任一能力检查"""
        capability = BrowserBackendCapability(
            backend_name="test_browser",
            capabilities=["click", "type", "navigate"]
        )
        
        assert capability.has_any_capability(["click", "screenshot"]) == True
        assert capability.has_any_capability(["screenshot", "mobile"]) == False
        assert capability.has_any_capability([]) == False

    def test_has_all_capabilities(self):
        """测试所有能力检查"""
        capability = BrowserBackendCapability(
            backend_name="test_browser",
            capabilities=["click", "type", "navigate"]
        )
        
        assert capability.has_all_capabilities(["click", "type"]) == True
        assert capability.has_all_capabilities(["click", "type", "navigate"]) == True
        assert capability.has_all_capabilities(["click", "screenshot"]) == False
        assert capability.has_all_capabilities([]) == True

    def test_is_suitable_for(self):
        """测试适用性检查"""
        capability = BrowserBackendCapability(
            backend_name="test_browser",
            best_for=["web_automation", "testing"]
        )
        
        assert capability.is_suitable_for("web_automation") == True
        assert capability.is_suitable_for("testing") == True
        assert capability.is_suitable_for("mobile_app") == False

    def test_get_limitations(self):
        """测试获取限制"""
        capability = BrowserBackendCapability(
            backend_name="test_browser",
            limitations=["no_mobile", "no_geolocation", "slow"]
        )
        
        limitations = capability.get_limitations()
        assert "no_mobile" in limitations
        assert "no_geolocation" in limitations
        assert "slow" in limitations

    def test_to_dict(self):
        """测试转换为字典"""
        capability = BrowserBackendCapability(
            backend_name="playwright",
            capabilities=["click", "type"],
            limitations=["no_mobile"],
            best_for=["testing"],
            max_pages=5,
            supports_mobile=False,
            supports_geolocation=False
        )
        
        data = capability.to_dict()
        assert data["backend_name"] == "playwright"
        assert data["capabilities"] == ["click", "type"]
        assert data["limitations"] == ["no_mobile"]
        assert data["best_for"] == ["testing"]
        assert data["max_pages"] == 5
        assert data["supports_mobile"] == False
        assert data["supports_geolocation"] == False

    def test_to_llm_context(self):
        """测试生成 LLM 上下文"""
        capability = BrowserBackendCapability(
            backend_name="playwright",
            capabilities=["click", "type", "navigate", "screenshot"],
            limitations=["no_mobile"],
            best_for=["web_automation", "testing"],
            max_pages=10,
            supports_mobile=False,
            supports_geolocation=False
        )
        
        context = capability.to_llm_context()
        
        assert "playwright" in context
        assert "click" in context
        assert "type" in context
        assert "navigate" in context
        assert "screenshot" in context
        assert "no_mobile" in context
        assert "web_automation" in context
        assert "testing" in context
        assert "10" in context

    def test_from_dict(self):
        """测试从字典创建"""
        data = {
            "backend_name": "selenium",
            "capabilities": ["click", "type", "navigate"],
            "limitations": ["slow"],
            "best_for": ["legacy_testing"],
            "max_pages": 5,
            "supports_mobile": True,
            "supports_geolocation": True
        }
        
        capability = BrowserBackendCapability.from_dict(data)
        
        assert capability.backend_name == "selenium"
        assert "click" in capability.capabilities
        assert "slow" in capability.limitations
        assert "legacy_testing" in capability.best_for
        assert capability.max_pages == 5
        assert capability.supports_mobile == True
        assert capability.supports_geolocation == True

    def test_serialization_roundtrip(self):
        """测试序列化往返"""
        original = BrowserBackendCapability(
            backend_name="test_browser",
            capabilities=["cap1", "cap2"],
            limitations=["lim1"],
            best_for=["use1"],
            max_pages=3,
            supports_mobile=True,
            supports_geolocation=False
        )
        
        data = original.to_dict()
        restored = BrowserBackendCapability.from_dict(data)
        
        assert restored.backend_name == original.backend_name
        assert restored.capabilities == original.capabilities
        assert restored.limitations == original.limitations
        assert restored.best_for == original.best_for
        assert restored.max_pages == original.max_pages
        assert restored.supports_mobile == original.supports_mobile
        assert restored.supports_geolocation == original.supports_geolocation

    def test_multiple_capabilities(self):
        """测试多个能力"""
        capabilities = [
            "click", "type", "navigate", "screenshot", "scroll",
            "wait", "select", "upload", "download", "execute_js"
        ]
        
        capability = BrowserBackendCapability(
            backend_name="full_browser",
            capabilities=capabilities
        )
        
        assert len(capability.capabilities) == 10
        for cap in capabilities:
            assert capability.has_capability(cap) == True

    def test_edge_cases(self):
        """测试边界情况"""
        # 空能力列表
        capability = BrowserBackendCapability(backend_name="empty")
        assert capability.has_capability("anything") == False
        assert capability.has_any_capability(["anything"]) == False
        assert capability.has_all_capabilities([]) == True
        
        # 空适用场景
        assert capability.is_suitable_for("anything") == False
        
        # 空限制
        assert capability.get_limitations() == []

    def test_context_generation_quality(self):
        """测试上下文生成质量"""
        capability = BrowserBackendCapability(
            backend_name="advanced_browser",
            capabilities=["click", "type", "navigate", "screenshot", "mobile"],
            limitations=["no_geolocation"],
            best_for=["mobile_testing", "responsive_design"],
            max_pages=20,
            supports_mobile=True,
            supports_geolocation=False
        )
        
        context = capability.to_llm_context()
        
        # 验证上下文包含所有重要信息
        assert "advanced_browser" in context
        assert "click" in context
        assert "mobile" in context
        assert "no_geolocation" in context
        assert "mobile_testing" in context
        assert "responsive_design" in context
        assert "20" in context
        assert "True" in context  # supports_mobile
        assert "False" in context  # supports_geolocation


if __name__ == "__main__":
    pytest.main([__file__, "-v"])