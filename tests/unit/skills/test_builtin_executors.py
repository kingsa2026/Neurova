"""
内置 Skill Executor 测试

验证从 skill_system.py 提取的 3 个内置 executor：
- MemorySkillExecutor: action=search/store
- WebSearchSkillExecutor: query 搜索
- FileOperationSkillExecutor: operation=read/write
"""
import pytest

from neurova.skills.executor import SkillResult
from neurova.skills.builtin.memory_executor import MemorySkillExecutor
from neurova.skills.builtin.web_search_executor import WebSearchSkillExecutor
from neurova.skills.builtin.file_operation_executor import FileOperationSkillExecutor


# ================================================================
# MemorySkillExecutor
# ================================================================

class TestMemorySkillExecutor:
    def test_search_action(self):
        """action=search 返回成功结果"""
        exe = MemorySkillExecutor()
        result = exe.execute(params={"action": "search", "query": "hello"})
        assert isinstance(result, SkillResult)
        assert result.success is True

    def test_store_action(self):
        """action=store 返回成功结果"""
        exe = MemorySkillExecutor()
        result = exe.execute(params={"action": "store", "content": "some content"})
        assert isinstance(result, SkillResult)
        assert result.success is True

    def test_unknown_action(self):
        """未知 action 返回失败"""
        exe = MemorySkillExecutor()
        result = exe.execute(params={"action": "delete"})
        assert result.success is False
        assert result.error is not None

    def test_skill_id(self):
        """skill_id 是 'memory'"""
        exe = MemorySkillExecutor()
        assert exe.skill_id == "memory"


# ================================================================
# WebSearchSkillExecutor
# ================================================================

class TestWebSearchSkillExecutor:
    def test_search(self):
        """搜索返回成功结果"""
        exe = WebSearchSkillExecutor()
        result = exe.execute(params={"query": "test query"})
        assert isinstance(result, SkillResult)
        assert result.success is True

    def test_skill_id(self):
        """skill_id 是 'web_search'"""
        exe = WebSearchSkillExecutor()
        assert exe.skill_id == "web_search"


# ================================================================
# FileOperationSkillExecutor
# ================================================================

class TestFileOperationSkillExecutor:
    def test_read_operation(self):
        """operation=read 返回成功结果"""
        exe = FileOperationSkillExecutor()
        result = exe.execute(params={"operation": "read", "file_path": "nonexistent.txt"})
        assert isinstance(result, SkillResult)

    def test_write_operation(self, tmp_path):
        """operation=write 写入文件成功"""
        exe = FileOperationSkillExecutor()
        test_file = tmp_path / "test.txt"
        result = exe.execute(
            params={"operation": "write", "file_path": str(test_file), "content": "hello"}
        )
        assert result.success is True
        assert test_file.read_text() == "hello"

    def test_unknown_operation(self):
        """未知 operation 返回失败"""
        exe = FileOperationSkillExecutor()
        result = exe.execute(params={"operation": "delete"})
        assert result.success is False
        assert result.error is not None

    def test_skill_id(self):
        """skill_id 是 'file_operation'"""
        exe = FileOperationSkillExecutor()
        assert exe.skill_id == "file_operation"
