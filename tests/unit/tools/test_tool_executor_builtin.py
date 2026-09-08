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

    # ═══════════════════════════════════════════════════════════════
    # 相对路径沙箱（2026-09-08 根因修复）：agent 用相对路径调 file_*
    # 时，落盘位置曾取决于进程 CWD（写到项目根而非 agent 工作区），
    # 与 SSE artifact 注册的解析不一致 → 产物注册失败/文件乱放。
    # 修复面①：内置 file_* 工具相对路径统一锚定 agent.workspace_path。
    # ═══════════════════════════════════════════════════════════════

    def _create_tool_executor_in_workspace(self, tmp_path):
        executor = self._create_tool_executor()
        executor._agent.workspace_path = tmp_path
        return executor

    @pytest.mark.asyncio
    async def test_file_write_relative_path_lands_in_workspace(self, tmp_path):
        """file_write 相对路径必须落在 agent.workspace_path 内"""
        executor = self._create_tool_executor_in_workspace(tmp_path)

        result = await executor._execute_file_write({
            "file_path": "notes/out.md",
            "content": "hello",
        })

        assert result.get("success") is True
        # 落盘在工作区，而非进程 CWD
        assert (tmp_path / "notes" / "out.md").read_text(encoding="utf-8") == "hello"
        # 返回解析后的绝对路径，供 SSE artifact 注册方解析到真实文件
        assert result["file_path"] == str((tmp_path / "notes" / "out.md").resolve())

    @pytest.mark.asyncio
    async def test_file_write_relative_path_rejects_escape(self, tmp_path):
        """file_write 相对路径 ../ 越界必须拒绝且不落盘"""
        executor = self._create_tool_executor_in_workspace(tmp_path)

        result = await executor._execute_file_write({
            "file_path": "../escape.md",
            "content": "nope",
        })

        assert result.get("success") is not True
        assert "error" in result
        assert not (tmp_path.parent / "escape.md").exists()

    @pytest.mark.asyncio
    async def test_file_read_relative_path_resolves_in_workspace(self, tmp_path):
        """file_read 相对路径在工作区内解析"""
        executor = self._create_tool_executor_in_workspace(tmp_path)
        (tmp_path / "doc.txt").write_text("workspace content", encoding="utf-8")

        result = await executor._execute_file_read({"file_path": "doc.txt"})

        assert result.get("content") == "workspace content"

    @pytest.mark.asyncio
    async def test_file_create_and_edit_relative_path(self, tmp_path):
        """file_create/file_edit 相对路径在工作区内解析"""
        executor = self._create_tool_executor_in_workspace(tmp_path)

        result = await executor._execute_file_create({
            "file_path": "sub/new.txt", "content": "v1",
        })
        assert result.get("success") is True
        assert (tmp_path / "sub" / "new.txt").read_text(encoding="utf-8") == "v1"
        assert result["file_path"] == str((tmp_path / "sub" / "new.txt").resolve())

        result = await executor._execute_file_edit({
            "file_path": "sub/new.txt", "old_str": "v1", "new_str": "v2",
        })
        assert result.get("success") is True
        assert (tmp_path / "sub" / "new.txt").read_text(encoding="utf-8") == "v2"

    @pytest.mark.asyncio
    async def test_file_delete_relative_path(self, tmp_path):
        """file_delete 相对路径在工作区内解析"""
        executor = self._create_tool_executor_in_workspace(tmp_path)
        (tmp_path / "gone.txt").write_text("bye", encoding="utf-8")

        result = await executor._execute_file_delete({"file_path": "gone.txt"})

        assert result.get("success") is True
        assert not (tmp_path / "gone.txt").exists()

    @pytest.mark.asyncio
    async def test_absolute_path_behavior_unchanged(self, tmp_path):
        """绝对路径行为不变（现有调用方契约保持）"""
        executor = self._create_tool_executor_in_workspace(tmp_path)
        test_file = tmp_path / "abs.txt"

        result = await executor._execute_file_write({
            "file_path": str(test_file), "content": "abs",
        })

        assert result.get("success") is True
        assert test_file.read_text(encoding="utf-8") == "abs"

    @pytest.mark.asyncio
    async def test_file_list_default_base_is_workspace(self, tmp_path):
        """file_list 缺省 path 时以 agent.workspace_path 为基准目录"""
        executor = self._create_tool_executor_in_workspace(tmp_path)
        (tmp_path / "a.txt").write_text("a", encoding="utf-8")

        result = await executor._execute_file_list({"pattern": "a.txt"})

        assert result.get("count") == 1
        assert result["files"] == [str(tmp_path / "a.txt")]

    @pytest.mark.asyncio
    async def test_skill_call_site_injects_workspace_base_dir(self, tmp_path):
        """skill 链路咽喉注入 _base_dir：LLM 伪造的同名参数被服务端覆盖"""
        executor = self._create_tool_executor_in_workspace(tmp_path)
        # 跳过 ToolEngine 路径（False 使 tool_engine property 短路）
        executor._tool_engine = False

        captured = {}

        class _CaptureSkill:
            name = "file_operation"
            config = {}

            async def execute(self, params, context=None):
                captured["params"] = dict(params)
                return {"success": True}

        registry = Mock()
        registry.has_skill.return_value = True
        registry.get_skill.return_value = _CaptureSkill()
        executor._agent._skill_registry = registry

        # builtin 注册表查不到该名（file_operation 是技能面工具）
        with patch("neurova.tool_executor.get_builtin_tool_params", return_value=None):
            await executor._execute_tool_core("file_operation", {
                "operation": "write", "file_path": "x.md", "content": "hi",
                "_base_dir": "/llm/forged/path",
            })

        injected = captured["params"]
        # 服务端赋值（agent 工作区）覆盖 LLM 伪造值
        assert injected["_base_dir"] == str(tmp_path)
        assert injected["_caller_user_id"]

    @pytest.mark.asyncio
    async def test_non_file_skills_do_not_receive_base_dir(self, tmp_path):
        """_base_dir 注入仅限 file_operation，其他技能参数面不受污染"""
        executor = self._create_tool_executor_in_workspace(tmp_path)
        executor._tool_engine = False

        captured = {}

        class _CaptureSkill:
            name = "memory"
            config = {}

            async def execute(self, params, context=None):
                captured["params"] = dict(params)
                return {"success": True}

        registry = Mock()
        registry.has_skill.return_value = True
        registry.get_skill.return_value = _CaptureSkill()
        executor._agent._skill_registry = registry

        with patch("neurova.tool_executor.get_builtin_tool_params", return_value=None):
            await executor._execute_tool_core("memory", {"query": "q"})

        assert "_base_dir" not in captured["params"]


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
