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


# ================================================================
# P1-2 工厂挂载待确认队列（用户 2026-09-04 决策启用）
# ================================================================

class TestBuiltinFactoryPendingStore:
    def test_factory_mounts_pending_store(self, monkeypatch, tmp_path):
        """工厂构造的 memory executor 携带待确认队列——聊天 memory_save
        写入默认进待审，确认后才入主库（Utopia 0018 交互式写入语义）。
        store 指向 tmp（防项目根测试污染），接线契约以 _mount_pending_store
        是否被调用并传入构造为准。"""
        from neurova.memory.pending_memory import PendingMemoryStore
        import neurova.skills.builtin as builtin_pkg

        monkeypatch.setattr(
            builtin_pkg,
            "_mount_pending_store",
            lambda: PendingMemoryStore(db_path=str(tmp_path / "p.db")),
        )
        skills = builtin_pkg.create_builtin_executor_skills()
        memory_skill = next(s for s in skills if s.name == "memory")
        assert memory_skill._executor.pending_store is not None

    def test_factory_mount_failure_degrades_to_direct_write(self, monkeypatch):
        """挂载失败（磁盘/权限等）只降级为直写：技能装配不中断、
        pending_store 为 None——错误方向是"少一个待审项"，不是"聊天坏掉"。"""
        import neurova.skills.builtin as builtin_pkg

        def boom():
            raise RuntimeError("disk full")

        monkeypatch.setattr(builtin_pkg, "_mount_pending_store", boom)
        skills = builtin_pkg.create_builtin_executor_skills()
        memory_skill = next(s for s in skills if s.name == "memory")
        assert memory_skill._executor.pending_store is None
        assert memory_skill._executor.execute({"action": "store", "content": "c"}).success is True

    def test_mounted_store_intercepts_store_action(self, tmp_path):
        """挂载后（默认）store 写入待审队列且不直写主库；confirm=True 按次直写。"""
        from unittest.mock import MagicMock

        from neurova.memory.pending_memory import PendingMemoryStore
        from neurova.skills.builtin import create_builtin_executor_skills

        from unittest import mock

        import neurova.skills.builtin as builtin_pkg

        mm = MagicMock()
        with mock.patch.object(builtin_pkg, "_mount_pending_store", lambda: None):
            skills = builtin_pkg.create_builtin_executor_skills(memory_manager=mm)
        memory_skill = next(s for s in skills if s.name == "memory")
        memory_skill._executor.pending_store = PendingMemoryStore(db_path=str(tmp_path / "p.db"))

        r1 = memory_skill._executor.execute({"action": "store", "content": "需要确认"})
        assert r1.success is True
        assert r1.output.get("pending") is True
        mm.remember.assert_not_called()

        r2 = memory_skill._executor.execute({"action": "store", "content": "强制直写", "confirm": True})
        assert r2.success is True
        assert r2.output == {"stored": True}
        mm.remember.assert_called_once()
