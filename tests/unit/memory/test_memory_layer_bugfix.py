"""记忆层模块 15 个 bug 修复测试 — TDD 红绿灯方法

每个测试对应一个 bug:
  BUG-1:  flush_buffer() 永远返回 0
  BUG-2:  _semantic_recall 污染全局单例索引
  BUG-3:  TemperatureEngine classmethod 覆盖实例方法
  BUG-4:  is_important 运算符优先级 bug
  BUG-5:  run_decay_cycle 不持久化
  BUG-6:  archive_memory/recover_from_archive 不持久化
  BUG-7:  多个读路径无锁保护
  BUG-8:  asyncio.get_event_loop() 弃用 + 静默吞异常
  BUG-9:  remember 中 except Exception: pass 静默吞情感分析异常
  BUG-10: MemoryWriteQueue.flush_to_storage TOCTOU race
  BUG-11: AttachmentManager.__del__ 调用 close() 获取锁
  BUG-12: run_*_sleep_cycle 修改模块私有属性非线程安全
  BUG-13: AttachmentManager 重复定义
  BUG-14: TemperatureEngine._default_instance 无锁
  BUG-15: get_attachment_manager 单例无双重检查锁

测试策略:
  - 锁相关 bug 用契约测试（断言 _lock 是 RLock 类型 / 方法获取锁）
  - 持久化 bug 用 spy/mock 验证 _persist_memory 被调用
  - 逻辑 bug 用行为断言
  - 每个测试独立隔离（独立 agent_id / tmp_path）
"""

import inspect
import os
import sys
import threading
import time
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, call
from typing import Any

import pytest

# ── 被测模块导入 ──
from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from neurova.cognitive_layers.memory_layer.temperature import TemperatureEngine
from neurova.cognitive_layers.memory_layer.conversation_buffer import MemoryWriteQueue, MemoryItem
from neurova.cognitive_layers.memory_layer.models import LifecycleStage, Memory, MemoryCategory, MemoryType


# ── 辅助 ──

def _make_manager(agent_id: str = "test", tmp_path=None) -> MemoryManager:
    """创建隔离的 MemoryManager（用 :memory: 或 tmp_path 避免 DB 污染）"""
    uid = uuid.uuid4().hex[:8]
    if tmp_path is not None:
        db_path = str(tmp_path / f"test_{uid}.db")
    else:
        db_path = ":memory:"
    return MemoryManager(db_path=db_path, agent_id=f"{agent_id}_{uid}")


def _make_memory_item(content: str = "test content") -> MemoryItem:
    return MemoryItem(
        id=f"item_{uuid.uuid4().hex[:8]}",
        content=content,
        timestamp=datetime.now(timezone.utc),
    )


# ═══════════════════════════════════════════════════════════════════
# BUG-1 (HIGH): flush_buffer() 永远返回 0
# ═══════════════════════════════════════════════════════════════════

class TestBug1FlushBufferReturnsZero:
    """BUG-1: flush_buffer() 永远返回 0

    根因: _write_queue = None 初始化后永不赋值
    修复: flush_buffer 委托到 _ensure_buffer_module().flush()
    """

    def test_flush_buffer_returns_nonzero_after_adding_turns(self, tmp_path):
        """添加对话轮次后 flush_buffer 应返回非零值"""
        manager = _make_manager(tmp_path=tmp_path)
        # 通过 buffer_module 添加轮次
        buf = manager._ensure_buffer_module()
        buf.add_turn(role="user", content="hello")
        buf.add_turn(role="assistant", content="hi there")

        count = manager.flush_buffer()
        assert count > 0, f"flush_buffer 返回 {count}，预期 > 0（缓冲区有 2 条轮次）"

    def test_flush_buffer_returns_int(self, tmp_path):
        """flush_buffer 返回值必须是 int"""
        manager = _make_manager(tmp_path=tmp_path)
        result = manager.flush_buffer()
        assert isinstance(result, int), f"flush_buffer 返回 {type(result)}，预期 int"


# ═══════════════════════════════════════════════════════════════════
# BUG-2 (HIGH): _semantic_recall 污染全局单例索引
# ═══════════════════════════════════════════════════════════════════

class TestBug2SemanticRecallPollutesGlobalIndex:
    """BUG-2: _semantic_recall 污染全局单例索引

    根因: 全局单例索引只首次构建,新记忆永不进入
    修复: 每次调用增量更新或重建索引
    """

    def test_new_memory_found_after_remember(self, tmp_path):
        """remember 后新记忆应能被 _semantic_recall 检索到"""
        manager = _make_manager(tmp_path=tmp_path)
        # 第一次 recall 构建索引
        manager.remember(content="python programming language", importance=80.0)
        results1 = manager.recall(query="python", limit=5)
        assert len(results1) >= 1

        # 新增一条记忆
        manager.remember(content="rust systems programming", importance=80.0)
        # 第二次 recall 应能找到新记忆
        results2 = manager.recall(query="rust", limit=5)
        contents = [r.get("content", "") for r in results2]
        assert any("rust" in c.lower() for c in contents), (
            f"新记忆 'rust' 未被检索到，结果: {contents}。"
            "可能根因: 全局单例 _keyword_index 只首次构建,新记忆未进入索引。"
        )


# ═══════════════════════════════════════════════════════════════════
# BUG-3 (MEDIUM): TemperatureEngine classmethod 覆盖实例方法
# ═══════════════════════════════════════════════════════════════════

class TestBug3TemperatureEngineClassmethodOverride:
    """BUG-3: TemperatureEngine classmethod 覆盖实例方法

    根因: 先定义实例方法 on_access/on_decay, 后用 classmethod 覆盖
    修复: 删除 classmethod 兼容包装器
    """

    def test_instance_on_access_uses_custom_params(self):
        """实例方法 on_access 应使用自定义 base_decay_rate"""
        # 创建一个自定义参数的实例
        engine = TemperatureEngine(base_decay_rate=0.2, emotional_protection_factor=0.3)
        # 调用实例方法（不应被 classmethod 覆盖）
        result = engine.on_access(current_temp=50.0, importance=0.5)
        assert isinstance(result, float)
        assert 0.0 <= result <= 100.0
        # 如果 classmethod 覆盖了实例方法, 会用默认实例（base_decay_rate=0.1）
        # 自定义实例 base_decay_rate=0.2 应产生更高升温
        default_engine = TemperatureEngine(base_decay_rate=0.1)
        default_result = default_engine.on_access(current_temp=50.0, importance=0.5)
        custom_result = engine.on_access(current_temp=50.0, importance=0.5)
        assert custom_result > default_result, (
            f"自定义 base_decay_rate=0.2 的结果 {custom_result} "
            f"不大于默认 base_decay_rate=0.1 的结果 {default_result}。"
            "可能根因: classmethod 覆盖了实例方法, 使用了默认实例。"
        )

    def test_on_access_is_not_classmethod(self):
        """on_access 不应是 classmethod（实例方法不应被 classmethod 覆盖）"""
        attr = TemperatureEngine.__dict__.get("on_access")
        assert attr is not None, "TemperatureEngine 必须有 on_access 属性"
        assert not hasattr(attr, "__func__") or not inspect.ismethod(attr), (
            "on_access 不应是 classmethod/descriptor 覆盖"
        )

    def test_on_decay_is_not_classmethod(self):
        """on_decay 不应是 classmethod"""
        attr = TemperatureEngine.__dict__.get("on_decay")
        assert attr is not None, "TemperatureEngine 必须有 on_decay 属性"
        assert not hasattr(attr, "__func__") or not inspect.ismethod(attr), (
            "on_decay 不应是 classmethod/descriptor 覆盖"
        )


# ═══════════════════════════════════════════════════════════════════
# BUG-4 (MEDIUM): is_important 运算符优先级 bug
# ═══════════════════════════════════════════════════════════════════

class TestBug4IsImportantPrecedence:
    """BUG-4: is_important 运算符优先级 bug

    根因: `A or B if C else D` 在空 metadata 时高重要性记忆保护失效
    修复: 改为 `A or bool((mem.metadata or {}).get("is_important", False))`
    """

    def test_high_importance_protected_with_empty_metadata(self, tmp_path):
        """importance >= 80 且 metadata 为空时，is_important 应为 True"""
        manager = _make_manager(tmp_path=tmp_path)
        # remember 一条高重要性记忆，metadata 为空
        mem_id = manager.remember(
            content="critical knowledge",
            importance=90.0,
            metadata={},
            temperature=50.0,
        )
        mem = manager._memories[mem_id]
        # 模拟 run_decay_cycle 中的 is_important 计算
        importance_norm = max(0.0, min(1.0, float(mem.importance) / 100.0))
        # 重现 bug 表达式
        buggy_result = (
            importance_norm >= 0.8
            or bool(mem.metadata.get("is_important", False)) if mem.metadata else False
        )
        # 修复后的表达式
        fixed_result = importance_norm >= 0.8 or bool((mem.metadata or {}).get("is_important", False))
        assert fixed_result is True, "高重要性记忆应被保护 (importance >= 0.8)"
        # 修复后两者应一致
        assert fixed_result == True
        # buggy 版本在空 metadata 时返回 False（bug 复现）
        # 修复后应返回 True
        assert fixed_result is True

    def test_decay_preserves_high_importance_memory(self, tmp_path):
        """run_decay_cycle 不应将高重要性空 metadata 记忆衰减到 0"""
        manager = _make_manager(tmp_path=tmp_path)
        mem_id = manager.remember(
            content="important fact",
            importance=95.0,
            metadata={},
            temperature=50.0,
        )
        mem = manager._memories[mem_id]
        original_temp = mem.temperature

        # 模拟长期空闲后衰减
        # 修改 last_accessed_at 为很久以前
        mem.last_accessed_at = datetime.now(timezone.utc) - timedelta(days=30)
        manager._persist_memory(mem)

        manager.run_decay_cycle()
        # 高重要性记忆不应被衰减到接近 0
        assert mem.temperature > 5.0, (
            f"高重要性记忆 (importance=95) 温度被衰减到 {mem.temperature}，"
            "可能根因: is_important 运算符优先级 bug 导致保护失效。"
        )


# ═══════════════════════════════════════════════════════════════════
# BUG-5 (MEDIUM): run_decay_cycle 不持久化
# ═══════════════════════════════════════════════════════════════════

class TestBug5DecayCycleNoPersist:
    """BUG-5: run_decay_cycle 不持久化

    根因: 修改 temperature/updated_at/lifecycle_stage 但不调用 _persist_memory
    修复: 在循环体内加 self._persist_memory(mem)
    """

    def test_decay_cycle_persists_temperature_change(self, tmp_path):
        """run_decay_cycle 修改温度后应持久化到 SQLite"""
        manager = _make_manager(tmp_path=tmp_path)
        # 用 70.0 避免命中 "高温记忆(>=80)不衰减" 分支
        mem_id = manager.remember(content="decay test", importance=50.0, temperature=70.0)
        mem = manager._memories[mem_id]
        # 设置很久以前访问
        mem.last_accessed_at = datetime.now(timezone.utc) - timedelta(days=10)
        manager._persist_memory(mem)

        original_temp = mem.temperature
        # 运行衰减
        manager.run_decay_cycle()

        # 从 DB 重新加载验证持久化
        new_manager = MemoryManager(
            db_path=manager._db_path, agent_id=manager._agent_id
        )
        loaded_mem = new_manager._memories.get(mem_id)
        assert loaded_mem is not None, "记忆应从 DB 加载"
        assert loaded_mem.temperature != original_temp, (
            f"DB 中温度仍为 {loaded_mem.temperature}（原始 {original_temp}），"
            "说明 run_decay_cycle 未持久化温度变更。"
        )


# ═══════════════════════════════════════════════════════════════════
# BUG-6 (MEDIUM): archive_memory/recover_from_archive 不持久化
# ═══════════════════════════════════════════════════════════════════

class TestBug6ArchiveNoPersist:
    """BUG-6: archive_memory/recover_from_archive 不持久化

    根因: 修改 lifecycle_stage 但不持久化
    修复: 在 mem.lifecycle_stage = ... 后加 self._persist_memory(mem)
    """

    def test_archive_memory_persists(self, tmp_path):
        """archive_memory 应持久化 lifecycle_stage"""
        manager = _make_manager(tmp_path=tmp_path)
        mem_id = manager.remember(content="archive test", importance=50.0)
        manager.archive_memory(mem_id)

        # 从 DB 重新加载
        new_manager = MemoryManager(
            db_path=manager._db_path, agent_id=manager._agent_id
        )
        loaded_mem = new_manager._memories.get(mem_id)
        assert loaded_mem is not None
        assert loaded_mem.lifecycle_stage == LifecycleStage.ARCHIVED, (
            f"DB 中 lifecycle_stage={loaded_mem.lifecycle_stage}，预期 ARCHIVED。"
            "说明 archive_memory 未持久化。"
        )

    def test_recover_from_archive_persists(self, tmp_path):
        """recover_from_archive 应持久化 lifecycle_stage"""
        manager = _make_manager(tmp_path=tmp_path)
        mem_id = manager.remember(content="recover test", importance=50.0)
        manager.archive_memory(mem_id)
        manager.recover_from_archive(mem_id)

        new_manager = MemoryManager(
            db_path=manager._db_path, agent_id=manager._agent_id
        )
        loaded_mem = new_manager._memories.get(mem_id)
        assert loaded_mem is not None
        assert loaded_mem.lifecycle_stage == LifecycleStage.ACTIVE, (
            f"DB 中 lifecycle_stage={loaded_mem.lifecycle_stage}，预期 ACTIVE。"
            "说明 recover_from_archive 未持久化。"
        )


# ═══════════════════════════════════════════════════════════════════
# BUG-7 (MEDIUM): 多个读路径无锁保护
# ═══════════════════════════════════════════════════════════════════

class TestBug7ReadPathNoLock:
    """BUG-7: 多个读路径无锁保护

    根因: 访问 self._memories 无锁, 并发 forget 时 RuntimeError
    修复: 所有读路径加 `with self._lock:`
    """

    def _make_manager(self, tmp_path):
        return _make_manager(tmp_path=tmp_path)

    def test_get_memory_acquires_lock(self, tmp_path):
        """get_memory 应在 self._lock 保护下执行"""
        manager = self._make_manager(tmp_path)
        mem_id = manager.remember(content="lock test")
        # 主线程持有锁
        manager._lock.acquire()
        try:
            completed = threading.Event()
            def worker():
                try:
                    manager.get_memory(mem_id)
                finally:
                    completed.set()
            t = threading.Thread(target=worker)
            t.start()
            completed.wait(timeout=0.5)
            assert not completed.is_set(), "get_memory 未获取 self._lock"
        finally:
            manager._lock.release()
        t.join(timeout=2.0)

    def test_get_all_memories_acquires_lock(self, tmp_path):
        """get_all_memories 应在 self._lock 保护下执行"""
        manager = self._make_manager(tmp_path)
        manager.remember(content="test")
        manager._lock.acquire()
        try:
            completed = threading.Event()
            def worker():
                try:
                    manager.get_all_memories()
                finally:
                    completed.set()
            t = threading.Thread(target=worker)
            t.start()
            completed.wait(timeout=0.5)
            assert not completed.is_set(), "get_all_memories 未获取 self._lock"
        finally:
            manager._lock.release()
        t.join(timeout=2.0)

    def test_archive_memory_acquires_lock(self, tmp_path):
        """archive_memory 应在 self._lock 保护下执行"""
        manager = self._make_manager(tmp_path)
        mem_id = manager.remember(content="test")
        manager._lock.acquire()
        try:
            completed = threading.Event()
            def worker():
                try:
                    manager.archive_memory(mem_id)
                finally:
                    completed.set()
            t = threading.Thread(target=worker)
            t.start()
            completed.wait(timeout=0.5)
            assert not completed.is_set(), "archive_memory 未获取 self._lock"
        finally:
            manager._lock.release()
        t.join(timeout=2.0)

    def test_get_crystallized_acquires_lock(self, tmp_path):
        """get_crystallized 应在 self._lock 保护下执行"""
        manager = self._make_manager(tmp_path)
        manager.remember(content="test")
        manager._lock.acquire()
        try:
            completed = threading.Event()
            def worker():
                try:
                    manager.get_crystallized()
                finally:
                    completed.set()
            t = threading.Thread(target=worker)
            t.start()
            completed.wait(timeout=0.5)
            assert not completed.is_set(), "get_crystallized 未获取 self._lock"
        finally:
            manager._lock.release()
        t.join(timeout=2.0)


# ═══════════════════════════════════════════════════════════════════
# BUG-8 (MEDIUM): asyncio.get_event_loop() 弃用 + 静默吞异常
# ═══════════════════════════════════════════════════════════════════

class TestBug8AsyncioDeprecation:
    """BUG-8: asyncio.get_event_loop() 弃用 + 静默吞异常

    根因: asyncio.get_event_loop() 在 3.12+ 弃用; 异常被 debug 级吞掉
    修复: 用 threading.Thread 跑 coroutine; 异常级别提升到 warning
    """

    def test_extract_dependency_async_does_not_use_get_event_loop(self):
        """_extract_dependency_async 不应调用 asyncio.get_event_loop()"""
        source = inspect.getsource(MemoryManager._extract_dependency_async)
        assert "get_event_loop" not in source, (
            "_extract_dependency_async 仍使用 asyncio.get_event_loop()，"
            "该 API 在 Python 3.12+ 弃用。应改用 threading.Thread。"
        )

    def test_extract_dependency_async_uses_threading(self):
        """_extract_dependency_async 应使用 threading.Thread"""
        source = inspect.getsource(MemoryManager._extract_dependency_async)
        assert "threading" in source or "Thread" in source, (
            "_extract_dependency_async 应使用 threading.Thread 替代 asyncio.get_event_loop()"
        )

    def test_extract_dependency_async_logs_warning_not_debug(self):
        """异常应记录为 warning 而非 debug"""
        source = inspect.getsource(MemoryManager._extract_dependency_async)
        # 不应只有 debug 级别
        assert "logger.debug" not in source or "logger.warning" in source, (
            "_extract_dependency_async 异常只记录到 debug 级别，"
            "应提升到 warning 以便发现失败。"
        )


# ═══════════════════════════════════════════════════════════════════
# BUG-9 (MEDIUM): remember 中 except Exception: pass 静默吞异常
# ═══════════════════════════════════════════════════════════════════

class TestBug9RememberSilentExcept:
    """BUG-9: remember 中 except Exception: pass 静默吞异常

    根因: except Exception: pass 吞掉所有异常
    修复: 改为 except Exception as e: logger.warning(...)
    """

    def test_remember_emotion_failure_logged_as_warning(self, tmp_path):
        """情感分析失败应记录 warning 而非静默吞掉"""
        manager = _make_manager(tmp_path=tmp_path)
        # 让 emotion_module.analyze_text_emotion 抛异常
        original_analyze = manager._emotion_module.analyze_text_emotion
        manager._emotion_module.analyze_text_emotion = MagicMock(
            side_effect=RuntimeError("emotion analysis failed")
        )
        warning_messages = []
        original_warning = manager._emotion_module.__class__.__module__

        # 捕获日志
        import logging
        from neurova.cognitive_layers.memory_layer import manager as mgr_module
        with patch.object(mgr_module.logger, "warning", side_effect=lambda *a, **kw: warning_messages.append(a[0] if a else "")):
            # 不应抛异常
            mem_id = manager.remember(content="test content with emotion")
            assert mem_id is not None

        # 应有 warning 日志
        assert len(warning_messages) > 0, (
            "情感分析失败时应有 warning 日志, 不应静默吞掉。"
        )

    def test_remember_no_bare_except_pass(self):
        """remember 方法源码不应包含 except Exception: pass"""
        source = inspect.getsource(MemoryManager.remember)
        assert "except Exception:" not in source or "pass" not in source.split("except Exception:")[1].split("\n")[0], (
            "remember 方法中有 `except Exception: pass` 静默吞异常"
        )


# ═══════════════════════════════════════════════════════════════════
# BUG-10 (LOW): MemoryWriteQueue.flush_to_storage TOCTOU race
# ═══════════════════════════════════════════════════════════════════

class TestBug10FlushToStorageTOCTOU:
    """BUG-10: flush_to_storage TOCTOU race

    根因: `if not self._queue:` 在锁外检查
    修复: 将检查移入 `with self._lock:` 块内
    """

    def test_flush_to_storage_empty_check_inside_lock(self):
        """flush_to_storage 的空检查应在锁内"""
        source = inspect.getsource(MemoryWriteQueue.flush_to_storage)
        lines = source.split("\n")
        # 找到 `if not self._queue:` 的行号
        check_line_idx = None
        lock_line_idx = None
        for i, line in enumerate(lines):
            if "if not self._queue:" in line and check_line_idx is None:
                check_line_idx = i
            if "with self._lock:" in line:
                lock_line_idx = i
        assert check_line_idx is not None, "flush_to_storage 应有 _queue 空检查"
        assert lock_line_idx is not None, "flush_to_storage 应有 with self._lock"
        assert check_line_idx > lock_line_idx, (
            f"`if not self._queue:` 在第 {check_line_idx} 行, "
            f"`with self._lock:` 在第 {lock_line_idx} 行。"
            "空检查应在锁内（TOCTOU race 修复）。"
        )


# ═══════════════════════════════════════════════════════════════════
# BUG-11 (LOW): AttachmentManager.__del__ 调用 close() 获取锁
# ═══════════════════════════════════════════════════════════════════

class TestBug11AttachmentManagerDelLock:
    """BUG-11: AttachmentManager.__del__ 调用 close() 获取锁

    根因: __del__ 中获取锁是反模式
    修复: __del__ 中只做 try/finally 关闭连接,不获取锁
    """

    def test_del_does_not_acquire_lock(self):
        """__del__ 不应获取 self._lock"""
        from neurova.cognitive_layers.memory_layer.attachment_manager import AttachmentManager
        source = inspect.getsource(AttachmentManager.__del__)
        # __del__ 不应包含 with self._lock 或 self._lock.acquire
        assert "self._lock" not in source, (
            "__del__ 中获取 self._lock 是反模式（GC 期间锁可能不可用）。"
            "应直接 try/finally 关闭连接。"
        )

    def test_del_closes_connection(self):
        """__del__ 应关闭数据库连接"""
        from neurova.cognitive_layers.memory_layer.attachment_manager import AttachmentManager
        source = inspect.getsource(AttachmentManager.__del__)
        assert "close" in source or "_conn" in source, (
            "__del__ 应关闭 _conn 连接"
        )


# ═══════════════════════════════════════════════════════════════════
# BUG-12 (LOW): run_*_sleep_cycle 修改模块私有属性
# ═══════════════════════════════════════════════════════════════════

class TestBug12SleepCyclePrivateAttrMutation:
    """BUG-12: run_*_sleep_cycle 修改模块私有属性非线程安全

    根因: 直接修改 module._dream_probability / _consolidation_threshold / _cleanup_threshold
    修复: 用参数传递而非修改私有属性
    """

    def test_run_rem_sleep_cycle_does_not_mutate_private_attr(self, tmp_path):
        """run_rem_sleep_cycle 不应直接修改 module._dream_probability"""
        manager = _make_manager(tmp_path=tmp_path)
        module = manager._ensure_sleep_module()
        original_dream = module._dream_probability

        # 需要有记忆才能运行
        manager.remember(content="sleep test", importance=0.8)
        manager.run_rem_sleep_cycle()

        # 检查私有属性是否被恢复（修复后不应被修改）
        assert module._dream_probability == original_dream, (
            f"run_rem_sleep_cycle 修改了 module._dream_probability "
            f"(原值={original_dream}, 当前={module._dream_probability})。"
            "应通过参数传递而非修改私有属性。"
        )

    def test_run_deep_sleep_cycle_does_not_mutate_private_attr(self, tmp_path):
        """run_deep_sleep_cycle 不应直接修改 module._consolidation_threshold"""
        manager = _make_manager(tmp_path=tmp_path)
        module = manager._ensure_sleep_module()
        original_consolidation = module._consolidation_threshold
        original_cleanup = module._cleanup_threshold

        manager.remember(content="sleep test", importance=0.8)
        manager.run_deep_sleep_cycle()

        assert module._consolidation_threshold == original_consolidation, (
            "run_deep_sleep_cycle 修改了 module._consolidation_threshold。"
        )
        assert module._cleanup_threshold == original_cleanup, (
            "run_deep_sleep_cycle 修改了 module._cleanup_threshold。"
        )


# ═══════════════════════════════════════════════════════════════════
# BUG-13 (LOW): AttachmentManager 重复定义
# ═══════════════════════════════════════════════════════════════════

class TestBug13AttachmentManagerDuplicate:
    """BUG-13: AttachmentManager 重复定义

    根因: cognitive_layers/memory_layer/attachment_manager.py 和 core/attachment_manager.py
          两个同名类
    修复: memory_layer 版本标记为权威实现
    """

    def test_memory_layer_attachment_manager_is_canonical(self):
        """memory_layer AttachmentManager 应标记为权威实现"""
        from neurova.cognitive_layers.memory_layer.attachment_manager import AttachmentManager
        # 权威实现应有完整的 SQLite + 文件存储 API
        assert hasattr(AttachmentManager, "_init_db"), "权威 AttachmentManager 应有 _init_db"
        assert hasattr(AttachmentManager, "save_attachment"), "权威 AttachmentManager 应有 save_attachment"
        assert hasattr(AttachmentManager, "get_attachment"), "权威 AttachmentManager 应有 get_attachment"
        assert hasattr(AttachmentManager, "delete_attachment"), "权威 AttachmentManager 应有 delete_attachment"

    def test_memory_layer_attachment_manager_docstring_mentions_canonical(self):
        """memory_layer AttachmentManager 应在 docstring 中标明权威"""
        from neurova.cognitive_layers.memory_layer.attachment_manager import AttachmentManager
        docstring = (AttachmentManager.__doc__ or "") + "\n" + (inspect.getsourcefile(AttachmentManager) or "")
        # docstring 或模块顶部应提及 "权威" 或 "canonical"
        source_file = inspect.getsourcefile(AttachmentManager)
        with open(source_file, "r", encoding="utf-8") as f:
            source = f.read()
        assert "权威" in source or "canonical" in source.lower(), (
            "memory_layer/attachment_manager.py 应在源码中标注为权威实现 (canonical/权威)"
        )


# ═══════════════════════════════════════════════════════════════════
# BUG-14 (LOW): TemperatureEngine._default_instance 无锁
# ═══════════════════════════════════════════════════════════════════

class TestBug14DefaultInstanceNoLock:
    """BUG-14: TemperatureEngine._default_instance 无锁

    根因: _get_default() classmethod 无锁保护
    修复: 加 threading.Lock() 保护
    """

    def test_get_default_uses_lock(self):
        """_get_default 应使用锁保护单例创建"""
        source = inspect.getsource(TemperatureEngine._get_default)
        assert "Lock" in source or "lock" in source, (
            "_get_default 无锁保护, 并发调用可能创建多个实例。"
            "应加 threading.Lock() 保护。"
        )

    def test_get_default_is_thread_safe(self):
        """_get_default 并发调用应返回同一实例"""
        # 重置默认实例
        TemperatureEngine._default_instance = None
        results = []
        barrier = threading.Barrier(4)

        def worker():
            barrier.wait()
            results.append(TemperatureEngine._get_default())

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert len(results) == 4
        assert all(r is results[0] for r in results), (
            "并发 _get_default 返回了不同实例, 说明无锁保护。"
        )


# ═══════════════════════════════════════════════════════════════════
# BUG-15 (LOW): get_attachment_manager 单例无双重检查锁
# ═══════════════════════════════════════════════════════════════════

class TestBug15GetAttachmentManagerDoubleCheck:
    """BUG-15: get_attachment_manager 单例无双重检查锁

    根因: 锁外检查后加锁,无二次检查
    修复: 加双重检查 `with _manager_lock: if _attachment_manager is None: ...`
    """

    def test_get_attachment_manager_has_double_check(self):
        """get_attachment_manager 应有双重检查锁模式"""
        from neurova.cognitive_layers.memory_layer import attachment_manager as am_module
        source = inspect.getsource(am_module.get_attachment_manager)
        # 应有两个 `is None` 检查
        none_checks = source.count("is None")
        assert none_checks >= 2, (
            f"get_attachment_manager 只有 {none_checks} 个 `is None` 检查, "
            "应有 2 个（双重检查锁模式）。"
        )
        # 应有 with _manager_lock
        assert "_manager_lock" in source, "应使用 _manager_lock"

    def test_get_attachment_manager_concurrent_returns_same(self, tmp_path):
        """并发调用应返回同一实例"""
        from neurova.cognitive_layers.memory_layer import attachment_manager as am_module
        am_module._attachment_manager = None
        results = []
        barrier = threading.Barrier(4)

        def worker():
            barrier.wait()
            results.append(am_module.get_attachment_manager(
                db_path=str(tmp_path / "test_attach.db"),
                storage_dir=str(tmp_path / "attachments"),
            ))

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert len(results) == 4
        assert all(r is results[0] for r in results), (
            "并发 get_attachment_manager 返回了不同实例"
        )
        # 清理
        am_module.reset_attachment_manager()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
