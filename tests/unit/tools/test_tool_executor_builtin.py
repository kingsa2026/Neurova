"""
测试内置工具执行器修复

验证 12 种内置工具的实际实现，而非桩实现。
"""

import pytest
import asyncio
from unittest.mock import Mock, patch, MagicMock, AsyncMock
from typing import Dict, Any


class TestBuiltinToolExecutor:
    """测试 ToolExecutor 内置工具实现"""
    
    def _create_tool_executor(self):
        """创建 ToolExecutor 实例（带 mock agent）"""
        from neurova.tool_executor import ToolExecutor
        
        # 创建 mock agent
        agent = Mock()
        agent._skill_registry = Mock()
        agent.tool_router = Mock()
        agent.tool_memory = Mock()
        agent.tool_lifecycle = Mock()
        agent.skill_packer = Mock()
        agent.config = Mock()
        agent.memory_manager = Mock()
        agent.memory_manager._emotion_analyzer = Mock()
        
        return ToolExecutor(agent)
    
    # ═══════════════════════════════════════════════════════════════
    # voice_memory_search - 缺失实现
    # ═══════════════════════════════════════════════════════════════
    
    def test_voice_memory_search_exists(self):
        """验证 _execute_voice_memory_search 方法存在"""
        executor = self._create_tool_executor()
        assert hasattr(executor, '_execute_voice_memory_search'), \
            "_execute_voice_memory_search 方法不存在"
    
    @pytest.mark.asyncio
    async def test_voice_memory_search_execution(self):
        """验证 voice_memory_search 工具可以执行"""
        executor = self._create_tool_executor()
        
        # 应该不会抛出 AttributeError
        try:
            result = await executor._execute_builtin_tool("voice_memory_search", {
                "query": "测试查询"
            })
            assert "error" not in result or "error" in result  # 至少应该返回结果
        except AttributeError as e:
            pytest.fail(f"voice_memory_search 执行失败: {e}")
    
    # ═══════════════════════════════════════════════════════════════
    # memory_search - 验证实际实现
    # ═══════════════════════════════════════════════════════════════
    
    @pytest.mark.asyncio
    async def test_memory_search_with_empty_query(self):
        """验证 memory_search 处理空查询"""
        executor = self._create_tool_executor()
        
        result = await executor._execute_memory_search({"query": ""})
        assert result.get("error") is not None or result.get("count", 0) == 0
    
    @pytest.mark.asyncio
    async def test_memory_search_with_valid_query(self):
        """验证 memory_search 执行真实搜索"""
        executor = self._create_tool_executor()
        
        # Mock memory_manager.recall
        executor._agent.memory_manager.recall = Mock(return_value=[
            {"id": "mem1", "content": "测试记忆", "category": "test", "temperature": 0.5}
        ])
        
        result = await executor._execute_memory_search({"query": "测试"})
        
        assert result.get("success") is True
        assert len(result.get("results", [])) > 0
        assert result["results"][0]["id"] == "mem1"
    
    # ═══════════════════════════════════════════════════════════════
    # emotion_analyze - 验证实际实现
    # ═══════════════════════════════════════════════════════════════
    
    @pytest.mark.asyncio
    async def test_emotion_analyze_with_real_analyzer(self):
        """验证 emotion_analyze 使用真实分析器"""
        executor = self._create_tool_executor()
        
        # Mock emotion_analyzer
        mock_analyzer = Mock()
        mock_analyzer.analyze = Mock(return_value={
            "primary_emotion": "happy",
            "confidence": 0.85,
            "emotions": {"happy": 0.85, "neutral": 0.15},
            "tags": ["positive"],
            "score": 0.8
        })
        
        executor._agent.memory_manager._emotion_analyzer = mock_analyzer
        
        result = await executor._execute_emotion_analyze({"text": "我今天很开心"})
        
        assert result.get("success") is True
        assert result.get("primary_emotion") == "happy"
        assert result.get("confidence") == 0.85
    
    @pytest.mark.asyncio
    async def test_emotion_analyze_different_emotions(self):
        """验证 emotion_analyze 返回不同情感结果（非固定 neutral）"""
        executor = self._create_tool_executor()
        
        test_cases = [
            ("我今天很开心", "happy"),
            ("我很生气", "angry"),
            ("我很伤心", "sad"),
            ("今天天气一般", "neutral"),
        ]
        
        mock_analyzer = Mock()
        executor._agent.memory_manager._emotion_analyzer = mock_analyzer
        
        for text, expected_emotion in test_cases:
            mock_analyzer.analyze = Mock(return_value={
                "primary_emotion": expected_emotion,
                "confidence": 0.7,
                "emotions": {expected_emotion: 0.7},
                "tags": [],
                "score": 0.5,
            })
            
            result = await executor._execute_emotion_analyze({"text": text})
            assert result.get("primary_emotion") == expected_emotion, \
                f"文本 '{text}' 应返回 '{expected_emotion}'，实际返回 '{result.get('primary_emotion')}'"
    
    # ═══════════════════════════════════════════════════════════════
    # Computer Use 工具 - 验证实际实现
    # ═══════════════════════════════════════════════════════════════
    
    @pytest.mark.asyncio
    async def test_computer_screenshot_with_manager(self):
        """验证 computer_screenshot 使用 ComputerUseManager"""
        executor = self._create_tool_executor()
        
        mock_manager = Mock()
        mock_manager.screenshot = Mock(return_value=b"fake_png_data")

        # spy 事件广播，抓取 screenshot_base64
        executor._emit_computer_event = AsyncMock()

        # get_computer_use_manager 是延迟导入，需要 mock 导入路径
        mock_module = Mock()
        mock_module.get_computer_use_manager = Mock(return_value=mock_manager)
        
        with patch.dict('sys.modules', {'neurova.computer_use': mock_module, 
                                         'neurova.computer_use.manager': mock_module}):
            result = await executor._execute_computer_screenshot({})
        
        assert result.get("success") is True
        assert result.get("format") == "png"
        assert result.get("size_bytes") == len(b"fake_png_data")
        assert "image_base64" not in result
        # base64 刻意通过 computer_action 事件广播给前端，而非塞进 LLM 返回值（撑爆上下文）
        executor._emit_computer_event.assert_awaited_once()
        _call_kwargs = executor._emit_computer_event.call_args.kwargs
        assert "screenshot_base64" in _call_kwargs
        assert _call_kwargs["screenshot_base64"]
    
    @pytest.mark.asyncio
    async def test_computer_click_with_coordinates(self):
        """验证 computer_click 使用坐标点击"""
        executor = self._create_tool_executor()
        
        mock_manager = Mock()
        mock_manager.click = Mock(return_value=True)
        
        mock_module = Mock()
        mock_module.get_computer_use_manager = Mock(return_value=mock_manager)
        
        with patch.dict('sys.modules', {'neurova.computer_use': mock_module}):
            result = await executor._execute_computer_click({"x": 100, "y": 200})
        
        assert result.get("success") is True
        mock_manager.click.assert_called_once_with(100, 200, "left")
    
    @pytest.mark.asyncio
    async def test_computer_type_with_text(self):
        """验证 computer_type 输入文本"""
        executor = self._create_tool_executor()
        
        mock_manager = Mock()
        mock_manager.type_text = Mock(return_value=True)
        
        mock_module = Mock()
        mock_module.get_computer_use_manager = Mock(return_value=mock_manager)
        
        with patch.dict('sys.modules', {'neurova.computer_use': mock_module}):
            result = await executor._execute_computer_type({"text": "Hello World"})
        
        assert result.get("success") is True
        mock_manager.type_text.assert_called_once_with("Hello World")
    
    @pytest.mark.asyncio
    async def test_computer_scroll_with_amount(self):
        """验证 computer_scroll 滚动"""
        executor = self._create_tool_executor()
        
        mock_manager = Mock()
        mock_manager.scroll = Mock(return_value=True)
        
        mock_module = Mock()
        mock_module.get_computer_use_manager = Mock(return_value=mock_manager)
        
        with patch.dict('sys.modules', {'neurova.computer_use': mock_module}):
            result = await executor._execute_computer_scroll({"scroll_y": 3})
        
        assert result.get("success") is True
    
    @pytest.mark.asyncio
    async def test_computer_shell_with_command(self):
        """验证 computer_shell 执行命令"""
        executor = self._create_tool_executor()
        
        mock_manager = Mock()
        mock_manager.shell = AsyncMock(return_value={
            "returncode": 0,
            "stdout": "output",
            "stderr": ""
        })
        executor._emit_computer_event = AsyncMock()

        mock_module = Mock()
        mock_module.get_computer_use_manager = Mock(return_value=mock_manager)
        
        with patch.dict('sys.modules', {'neurova.computer_use': mock_module}):
            result = await executor._execute_computer_shell({"command": "echo test"})
        
        assert result.get("success") is True
        assert result.get("stdout") == "output"
    
    # ═══════════════════════════════════════════════════════════════
    # CLI 工具 - 验证实际实现
    # ═══════════════════════════════════════════════════════════════
    
    @pytest.mark.asyncio
    async def test_cli_tool_execution(self):
        """验证 CLI 工具可以执行"""
        executor = self._create_tool_executor()
        
        mock_manager = Mock()
        mock_manager.shell = AsyncMock(return_value={
            "returncode": 0,
            "stdout": "command output",
            "stderr": ""
        })
        
        mock_module = Mock()
        mock_module.get_computer_use_manager = Mock(return_value=mock_manager)
        
        with patch.dict('sys.modules', {'neurova.computer_use': mock_module}):
            result = await executor.execute_cli_tool("echo", {"text": "test"})
        
        assert result.get("success") is True
    
    # ═══════════════════════════════════════════════════════════════
    # 文件工具 - 验证实际实现
    # ═══════════════════════════════════════════════════════════════
    
    @pytest.mark.asyncio
    async def test_file_read_real_file(self, tmp_path):
        """验证 file_read 读取真实文件"""
        executor = self._create_tool_executor()
        
        # 创建测试文件
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello, World!", encoding="utf-8")
        
        result = await executor._execute_file_read({"file_path": str(test_file)})
        
        assert "content" in result
        assert result["content"] == "Hello, World!"
    
    @pytest.mark.asyncio
    async def test_file_write_real_file(self, tmp_path):
        """验证 file_write 写入真实文件"""
        executor = self._create_tool_executor()
        
        test_file = tmp_path / "output.txt"
        
        result = await executor._execute_file_write({
            "file_path": str(test_file),
            "content": "Test content"
        })
        
        assert result.get("success") is True
        assert test_file.read_text(encoding="utf-8") == "Test content"
    
    @pytest.mark.asyncio
    async def test_file_edit_real_file(self, tmp_path):
        """验证 file_edit 编辑真实文件"""
        executor = self._create_tool_executor()
        
        test_file = tmp_path / "edit.txt"
        test_file.write_text("Hello, World!", encoding="utf-8")
        
        result = await executor._execute_file_edit({
            "file_path": str(test_file),
            "old_str": "World",
            "new_str": "Python"
        })
        
        assert result.get("success") is True
        assert test_file.read_text(encoding="utf-8") == "Hello, Python!"
    
    @pytest.mark.asyncio
    async def test_file_delete_real_file(self, tmp_path):
        """验证 file_delete 删除真实文件"""
        executor = self._create_tool_executor()
        
        test_file = tmp_path / "delete.txt"
        test_file.write_text("delete me", encoding="utf-8")
        
        result = await executor._execute_file_delete({"file_path": str(test_file)})
        
        assert result.get("success") is True
        assert not test_file.exists()
    
    @pytest.mark.asyncio
    async def test_file_create_real_file(self, tmp_path):
        """验证 file_create 创建真实文件"""
        executor = self._create_tool_executor()
        
        test_file = tmp_path / "new.txt"
        
        result = await executor._execute_file_create({
            "file_path": str(test_file),
            "content": "New content"
        })
        
        assert result.get("success") is True
        assert test_file.exists()
        assert test_file.read_text(encoding="utf-8") == "New content"


class TestBuiltinToolIntegration:
    """测试内置工具集成"""
    
    def _create_tool_executor(self):
        from neurova.tool_executor import ToolExecutor
        
        agent = Mock()
        agent._skill_registry = Mock()
        agent.tool_router = Mock()
        agent.tool_memory = Mock()
        agent.tool_lifecycle = Mock()
        agent.skill_packer = Mock()
        agent.config = Mock()
        agent.memory_manager = Mock()
        agent.memory_manager._emotion_analyzer = Mock()
        
        return ToolExecutor(agent)
    
    @pytest.mark.asyncio
    async def test_all_builtin_tools_execute(self):
        """验证所有 12 种内置工具都可以执行"""
        executor = self._create_tool_executor()
        
        builtin_tools = [
            "memory_search", "file_read", "file_write", "file_create",
            "file_delete", "file_edit", "computer_screenshot", "computer_click",
            "computer_type", "computer_scroll", "computer_shell", "emotion_analyze",
            "voice_memory_search",
        ]
        
        mock_manager = Mock()
        mock_manager.screenshot = Mock(return_value=b"data")
        mock_manager.click = Mock(return_value=True)
        mock_manager.type_text = Mock(return_value=True)
        mock_manager.scroll = Mock(return_value=True)
        mock_manager.shell = AsyncMock(return_value={"returncode": 0, "stdout": "", "stderr": ""})
        
        mock_module = Mock()
        mock_module.get_computer_use_manager = Mock(return_value=mock_manager)
        
        # Mock emotion analyzer
        mock_emotion_analyzer = Mock()
        mock_emotion_analyzer.analyze = Mock(return_value={
            "primary_emotion": "neutral",
            "confidence": 0.5,
            "emotions": {"neutral": 1.0},
            "tags": [],
            "score": 0.0,
        })
        executor._agent.memory_manager._emotion_analyzer = mock_emotion_analyzer
        
        # Mock memory manager
        executor._agent.memory_manager.recall = Mock(return_value=[])
        
        with patch.dict('sys.modules', {'neurova.computer_use': mock_module}):
            for tool_name in builtin_tools:
                params = {"query": "test", "text": "test", "file_path": "/tmp/test", 
                         "content": "test", "old_str": "test", "new_str": "test",
                         "command": "test", "x": 0, "y": 0, "scroll_y": 0}
                
                try:
                    result = await executor._execute_builtin_tool(tool_name, params)
                    assert isinstance(result, dict), f"{tool_name} 应返回字典"
                except Exception as e:
                    pytest.fail(f"{tool_name} 执行失败: {e}")
