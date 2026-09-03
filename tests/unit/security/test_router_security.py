"""
Router 安全测试 - eval() 代码注入漏洞验证
"""
import pytest
import asyncio
import sys
import os
from unittest.mock import MagicMock, AsyncMock
from neurova.router import MessageRouter, Message, MessageType, RouteResult


class TestEvalInjectionVulnerability:
    """测试 eval() 代码注入漏洞"""

    @pytest.mark.asyncio
    async def test_eval_injection_rce(self):
        """验证 eval() 允许远程代码执行 (RCE)"""
        # 创建一个 mock 的 skill_registry
        mock_skill_registry = MagicMock()
        mock_skill_registry.execute_skill = AsyncMock()
        mock_skill_registry.execute_skill.return_value = MagicMock(
            success=True, data="skill executed", execution_time=0.1
        )
        
        # 创建路由器
        router = MessageRouter(skill_registry=mock_skill_registry)
        
        # 创建恶意消息：尝试执行系统命令
        # 消息格式：skill_name params_str
        malicious_content = "web_search __import__('os').system('echo INJECTED')"
        msg = Message(content=malicious_content, message_type=MessageType.SKILL_REQUEST)
        
        # 路由消息
        result = await router.route(msg)
        
        # 验证：如果 eval() 被执行，系统命令会被运行
        # 注意：这个测试会实际执行系统命令，所以我们需要捕获它
        # 这里我们只验证方法被调用，实际执行会在生产环境中发生
        
        # 验证 skill_registry 被调用了
        mock_skill_registry.execute_skill.assert_called_once()
        
        # 获取传递给 execute_skill 的参数
        call_args = mock_skill_registry.execute_skill.call_args
        skill_name, params, metadata = call_args[0]
        
        # 关键验证：params 应该是一个字典，而不是被执行的代码结果
        # 如果 eval() 被执行，params 会是系统命令的返回值（0 表示成功）
        # 如果使用 json.loads()，params 应该是包含原始字符串的字典
        assert isinstance(params, dict), f"Expected dict, got {type(params)}: {params}"
        
        # 如果 params 是 0（os.system 的返回值），说明 eval() 被执行了
        if params == 0:
            pytest.fail("eval() executed malicious code - RCE vulnerability confirmed!")
    
    @pytest.mark.asyncio
    async def test_json_parsing_safe(self):
        """验证 JSON 解析是安全的"""
        mock_skill_registry = MagicMock()
        mock_skill_registry.execute_skill = AsyncMock()
        mock_skill_registry.execute_skill.return_value = MagicMock(
            success=True, data="skill executed", execution_time=0.1
        )
        
        router = MessageRouter(skill_registry=mock_skill_registry)
        
        # 正常的 JSON 参数
        normal_content = 'web_search {"query": "hello", "limit": 5}'
        msg = Message(content=normal_content, message_type=MessageType.SKILL_REQUEST)
        
        result = await router.route(msg)
        
        # 验证参数被正确解析为字典
        call_args = mock_skill_registry.execute_skill.call_args
        skill_name, params, metadata = call_args[0]
        
        assert isinstance(params, dict)
        assert params.get("query") == "hello"
        assert params.get("limit") == 5
    
    @pytest.mark.asyncio
    async def test_malicious_json_payload(self):
        """验证恶意 JSON 载荷不会被执行"""
        mock_skill_registry = MagicMock()
        mock_skill_registry.execute_skill = AsyncMock()
        mock_skill_registry.execute_skill.return_value = MagicMock(
            success=True, data="skill executed", execution_time=0.1
        )
        
        router = MessageRouter(skill_registry=mock_skill_registry)
        
        # 恶意 JSON 载荷：尝试通过 __import__ 执行代码
        malicious_json = 'web_search {"__import__": "os"}'
        msg = Message(content=malicious_json, message_type=MessageType.SKILL_REQUEST)
        
        result = await router.route(msg)
        
        # 验证参数被安全解析
        call_args = mock_skill_registry.execute_skill.call_args
        skill_name, params, metadata = call_args[0]
        
        assert isinstance(params, dict)
        # params 应该包含原始字典，而不是被执行的代码
        assert "__import__" in params


class TestSafeParameterParsing:
    """测试安全的参数解析"""

    @pytest.mark.asyncio
    async def test_empty_params(self):
        """空参数应返回空字典"""
        mock_skill_registry = MagicMock()
        mock_skill_registry.execute_skill = AsyncMock()
        mock_skill_registry.execute_skill.return_value = MagicMock(
            success=True, data="skill executed", execution_time=0.1
        )
        
        router = MessageRouter(skill_registry=mock_skill_registry)
        
        # 没有参数的消息
        msg = Message(content="web_search", message_type=MessageType.SKILL_REQUEST)
        
        result = await router.route(msg)
        
        call_args = mock_skill_registry.execute_skill.call_args
        skill_name, params, metadata = call_args[0]
        
        assert isinstance(params, dict)
        assert len(params) == 0
    
    @pytest.mark.asyncio
    async def test_complex_json(self):
        """复杂 JSON 应该被正确解析"""
        mock_skill_registry = MagicMock()
        mock_skill_registry.execute_skill = AsyncMock()
        mock_skill_registry.execute_skill.return_value = MagicMock(
            success=True, data="skill executed", execution_time=0.1
        )
        
        router = MessageRouter(skill_registry=mock_skill_registry)
        
        complex_json = 'web_search {"nested": {"key": "value"}, "list": [1, 2, 3], "bool": true}'
        msg = Message(content=complex_json, message_type=MessageType.SKILL_REQUEST)
        
        result = await router.route(msg)
        
        call_args = mock_skill_registry.execute_skill.call_args
        skill_name, params, metadata = call_args[0]
        
        assert isinstance(params, dict)
        assert params["nested"]["key"] == "value"
        assert params["list"] == [1, 2, 3]
        assert params["bool"] is True
    
    @pytest.mark.asyncio
    async def test_invalid_json_fallback(self):
        """无效 JSON 应该回退到原始字符串"""
        mock_skill_registry = MagicMock()
        mock_skill_registry.execute_skill = AsyncMock()
        mock_skill_registry.execute_skill.return_value = MagicMock(
            success=True, data="skill executed", execution_time=0.1
        )
        
        router = MessageRouter(skill_registry=mock_skill_registry)
        
        # 无效的 JSON
        invalid_json = "web_search not a json string"
        msg = Message(content=invalid_json, message_type=MessageType.SKILL_REQUEST)
        
        result = await router.route(msg)
        
        call_args = mock_skill_registry.execute_skill.call_args
        skill_name, params, metadata = call_args[0]
        
        assert isinstance(params, dict)
        # 应该回退到 {"raw": "not a json string"}
        assert params.get("raw") == "not a json string"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])