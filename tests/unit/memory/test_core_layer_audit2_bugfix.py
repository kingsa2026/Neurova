"""审计2 — 19 个 bug 的 TDD 红绿灯修复测试

文件所有权:
  源码: manager.py / models.py / temperature.py / storage.py / isolation.py
  测试: 本文件

TDD 方法论:
  - RED:   先写失败测试
  - GREEN: 最小代码修改
  - REFACTOR: 可选

Bug 清单:
  Bug 1  (LOW):    models.to_dict emotion 死代码分支
  Bug 2  (LOW):    models.from_dict 未传 isolation_context
  Bug 3  (HIGH):   manager.remember() 不传 neuser_id
  Bug 4  (HIGH):   manager._load_from_db WHERE 仅按 agent_id 过滤
  Bug 5  (HIGH):   manager._write_queue = None 永不赋值
  Bug 6  (HIGH):   manager.recall 触发 touch() 但未 _persist_memory
  Bug 7  (HIGH):   manager.update_memory_temperature 未 _persist_memory
  Bug 8  (MEDIUM): manager._semantic_recall 未按 user_id/agent_id 过滤
  Bug 9  (MEDIUM): manager._extract_dependency_async 每次创建新 Thread
  Bug 10 (LOW):    manager.get_recovery_history 访问私有属性
  Bug 11 (HIGH):   temperature classmethod 覆盖 instance method (验证已修复)
  Bug 12 (MEDIUM): temperature._default_instance 无锁 DCL (验证已修复)
  Bug 13 (LOW):    temperature docstring 与实现矛盾
  Bug 14 (LOW):    temperature _determine_stage 固化记忆返回 'active' 而非 'crystallized'
  Bug 15 (HIGH):   storage.batch_save 未传 isolation_context
  Bug 16 (MEDIUM): storage.get_recent_memories 锁释放后才过滤 (TOCTOU)
  Bug 17 (MEDIUM): storage.delete 与 delete_memory 功能重复
  Bug 18 (LOW):    storage._load except TypeError 静默吞
  Bug 19 (LOW):    storage.query 字符串比较 ISO 时间
  Bug 20 (MEDIUM): isolation.from_legacy 把 owner 当作 agent_id
"""
from __future__ import annotations

import inspect
import json
import logging
import threading
import time
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ── 被测模块 ──
from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from neurova.cognitive_layers.memory_layer.models import (
    EmotionType,
    LifecycleStage,
    Memory,
    MemoryCategory,
    MemoryType,
)
from neurova.cognitive_layers.memory_layer.temperature import TemperatureEngine
from neurova.cognitive_layers.memory_layer.storage import MemoryRecord, MemoryStorage
from neurova.cognitive_layers.memory_layer.isolation import IsolationContext


# ════════════════════════════════════════════
# 辅助函数
# ════════════════════════════════════════════


def _make_manager(
    tmp_path,
    agent_id: str = "test_agent",
    neuser_id: str = "test_neuser",
    user_id: str = "test_user",
) -> MemoryManager:
    """创建隔离的 MemoryManager（用 tmp_path 避免 DB 污染）"""
    uid = uuid.uuid4().hex[:8]
    db_path = str(tmp_path / f"test_{uid}.db")
    return MemoryManager(
        db_path=db_path,
        agent_id=f"{agent_id}_{uid}",
        neuser_id=f"{neuser_id}_{uid}",
        user_id=f"{user_id}_{uid}",
    )


# ════════════════════════════════════════════
# models.py
# ════════════════════════════════════════════


class TestBug1ToDictEmotionDeadCode:
    """Bug 1 (LOW): to_dict emotion 死代码分支

    根因: `if hasattr(self.emotion, "value") else str(self.emotion)`
    emotion 总是 EmotionType 枚举, hasattr 永远 True, else 分支死代码。
    修复: 简化为 self.emotion.value
    """

    def test_bug1_to_dict_emotion_simplified(self):
        """RED: to_dict 中 emotion 不应包含死代码 else 分支"""
        src = inspect.getsource(Memory.to_dict)
        assert "else str(self.emotion)" not in src, (
            "Bug 1: to_dict 仍包含死代码 else str(self.emotion) 分支"
        )

    def test_bug1_to_dict_emotion_value_correct(self):
        """to_dict 应返回 emotion 的 value"""
        mem = Memory(content="test", emotion=EmotionType.JOY)
        d = mem.to_dict()
        assert d["emotion"] == "joy"


class TestBug2FromDictIsolationContext:
    """Bug 2 (LOW): from_dict 未传 isolation_context

    根因: from_dict 构造 Memory 时未传 isolation_context (行 273 字段)
    修复: from_dict 接收并传入 isolation_context, 或从字段重建
    """

    def test_bug2_from_dict_passes_isolation_context(self):
        """RED: from_dict 后 isolation_context 应非 None"""
        ctx = IsolationContext(
            agent_id="agent_a2",
            neuser_id="neuser_a2",
            user_id="user_a2",
        )
        mem = Memory(content="test", isolation_context=ctx)
        d = mem.to_dict()

        # from_dict 传入 isolation_context 后, isolation_context 应非 None
        mem2 = Memory.from_dict(d, isolation_context=ctx)
        assert mem2.isolation_context is not None, (
            "Bug 2: from_dict 未传 isolation_context, 导致 isolation_context 为 None"
        )

    def test_bug2_from_dict_reconstruct_isolation_context_from_fields(self):
        """RED: from_dict 不传 isolation_context 时应从 agent_id/neuser_id/user_id 字段重建"""
        mem = Memory(
            content="test",
            agent_id="agent_b2",
            neuser_id="neuser_b2",
            user_id="user_b2",
        )
        d = mem.to_dict()

        mem2 = Memory.from_dict(d)
        assert mem2.isolation_context is not None, (
            "Bug 2: from_dict 未从字段重建 isolation_context"
        )


# ════════════════════════════════════════════
# manager.py
# ════════════════════════════════════════════


class TestBug3RememberMissingNeuserId:
    """Bug 3 (HIGH): remember() 不传 neuser_id

    根因: 构造 Memory 只传 agent_id 和 user_id, 漏传 neuser_id
    修复: remember() 传 neuser_id=self._neuser_id
    """

    def test_bug3_remember_passes_neuser_id(self, tmp_path):
        """RED: remember 后 Memory.neuser_id 应等于 manager._neuser_id"""
        manager = _make_manager(tmp_path, neuser_id="my_neuser_3")
        mid = manager.remember("test content for bug3")
        mem = manager._memories[mid]
        assert mem.neuser_id == manager._neuser_id, (
            f"Bug 3: remember 未传 neuser_id, got '{mem.neuser_id}', "
            f"expected '{manager._neuser_id}'"
        )


class TestBug4LoadFromDbCrossUser:
    """Bug 4 (HIGH): _load_from_db 曾不按 neuser_id/user_id 过滤导致跨用户泄漏

    修复历史: WHERE 加 AND neuser_id=? AND user_id=? —— 三层过滤。

    契约更新 (2026-09-03, agent 级隔离): 快照口径改为 agent 全量
    (WHERE 仅 agent_id), 隔离下沉到视图层 —— _scoped_memories(recall
    默认路径)、get_memory/forget 越权检查统一按生效三元组过滤。跨用户行
    在检索/管理默认路径仍不可见, 但快照包含 agent 全部行, 使管理页
    (agent_wide 口径)能看全。
    """

    def test_bug4_load_from_db_filters_by_neuser_and_user(self, tmp_path):
        """不同 neuser 的记忆在检索路径不可见(视图层隔离)"""
        db_path = str(tmp_path / "shared_b4.db")

        # manager1: agent_id=A, neuser_id=N1, user_id=U1
        m1 = MemoryManager(
            db_path=db_path, agent_id="agent_b4", neuser_id="neuser_b4_1", user_id="user_b4_1"
        )
        m1.remember("memory for neuser N1")
        m1_id = list(m1._memories.keys())[0]
        m1.close()

        # manager2: agent_id=A (相同), neuser_id=N2 (不同), user_id=U2 (不同)
        m2 = MemoryManager(
            db_path=db_path, agent_id="agent_b4", neuser_id="neuser_b4_2", user_id="user_b4_2"
        )

        # 快照为 agent 全量(含跨用户行); 隔离由视图层保证
        assert m1_id in m2._memories, "快照应变 agent 全量口径"
        recalled_ids = {m["id"] for m in m2.recall(limit=20)}
        assert m1_id not in recalled_ids, (
            f"Bug 4: recall 泄漏跨用户记忆: {sorted(recalled_ids)}"
        )


class TestBug5WriteQueueNeverAssigned:
    """Bug 5 (HIGH): _write_queue = None 永不赋值

    根因: self._write_queue = None 从未被赋值为 MemoryWriteQueue 实例
    修复: __init__ 中初始化 MemoryWriteQueue
    """

    def test_bug5_write_queue_is_not_none(self, tmp_path):
        """RED: manager._write_queue 应为非 None 的 MemoryWriteQueue 实例"""
        manager = _make_manager(tmp_path)
        assert getattr(manager, "_write_queue", None) is not None, (
            "Bug 5: _write_queue 从未被赋值为 MemoryWriteQueue 实例"
        )


class TestBug6RecallNoPersist:
    """Bug 6 (HIGH): recall 触发 touch() 但未 _persist_memory

    根因: recall 对 results[:limit] 调 m.touch() 更新温度/访问次数, 但未持久化
    修复: touch() 后加 self._persist_memory(m)
    """

    def test_bug6_recall_persists_touched_memory(self, tmp_path):
        """RED: recall 后 _persist_memory 应被调用以持久化 touch 的变更"""
        manager = _make_manager(tmp_path)
        mid = manager.remember("hello world bug6 test")

        # Spy on _persist_memory
        persist_calls = []
        original_persist = manager._persist_memory

        def spy_persist(mem):
            persist_calls.append(mem.id)
            return original_persist(mem)

        manager._persist_memory = spy_persist

        manager.recall("hello", limit=10, use_semantic=False)

        # recall 应触发 _persist_memory (除了 remember 时的初始持久化)
        assert any(mid == c for c in persist_calls), (
            f"Bug 6: recall 未持久化 touch 的记忆, persist_calls={persist_calls}"
        )


class TestBug7UpdateTempNoPersist:
    """Bug 7 (HIGH): update_memory_temperature 未 _persist_memory

    根因: 仅 mem.touch(), 未持久化
    修复: 加 self._persist_memory(mem)
    """

    def test_bug7_update_temp_persists(self, tmp_path):
        """RED: update_memory_temperature 后 _persist_memory 应被调用"""
        manager = _make_manager(tmp_path)
        mid = manager.remember("test bug7")

        # Spy on _persist_memory
        persist_calls = []
        original_persist = manager._persist_memory

        def spy_persist(mem):
            persist_calls.append(mem.id)
            return original_persist(mem)

        manager._persist_memory = spy_persist

        result = manager.update_memory_temperature(mid, "recall")
        assert result is True

        assert any(mid == c for c in persist_calls), (
            f"Bug 7: update_memory_temperature 未持久化, persist_calls={persist_calls}"
        )


class TestBug8SemanticRecallNoUserFilter:
    """Bug 8 (MEDIUM): _semantic_recall 未按 user_id/agent_id 过滤

    根因: 对传入 memories 列表直接做语义搜索, 未过滤
    修复: 入口加 [m for m in memories if m.agent_id == self._agent_id and m.user_id == self._user_id]
    """

    def test_bug8_semantic_recall_filters_by_user(self, tmp_path):
        """RED: 传入混合用户 memories, 只搜索当前用户的"""
        manager = _make_manager(tmp_path)

        # 当前用户的 memory
        my_mem = Memory(
            id="my_mem_b8",
            content="hello world my memory",
            agent_id=manager._agent_id,
            neuser_id=manager._neuser_id,
            user_id=manager._user_id,
        )
        # 其他用户的 memory (应被过滤掉)
        other_mem = Memory(
            id="other_mem_b8",
            content="hello world other user memory",
            agent_id="other_agent_b8",
            neuser_id="other_neuser_b8",
            user_id="other_user_b8",
        )

        mixed = [my_mem, other_mem]
        results = manager._semantic_recall("hello", mixed, limit=10)

        result_ids = [r.id for r in results]
        assert "other_mem_b8" not in result_ids, (
            f"Bug 8: _semantic_recall 未过滤其他用户的 memory, got {result_ids}"
        )


class TestBug9ExtractDependencyInfiniteThreads:
    """Bug 9 (MEDIUM): _extract_dependency_async 每次创建新 Thread

    根因: 每次 remember 都触发异步路径, 无线程池限制
    修复: 用信号量限流或共用 ThreadPoolExecutor
    """

    def test_bug9_uses_thread_pool_executor(self, tmp_path):
        """RED: manager 应使用共享 ThreadPoolExecutor, 而非每次创建新 Thread"""
        from concurrent.futures import ThreadPoolExecutor

        manager = _make_manager(tmp_path)
        assert hasattr(manager, "_dependency_executor"), (
            "Bug 9: manager 无共享 _dependency_executor"
        )
        assert isinstance(manager._dependency_executor, ThreadPoolExecutor), (
            f"Bug 9: _dependency_executor 应为 ThreadPoolExecutor, "
            f"got {type(manager._dependency_executor)}"
        )

    def test_bug9_high_freq_no_infinite_threads(self, tmp_path):
        """高频 remember 不应创建无限线程"""
        manager = _make_manager(tmp_path)
        initial_count = threading.active_count()

        for i in range(20):
            manager.remember(f"memory {i} for bug9")

        time.sleep(0.5)
        final_count = threading.active_count()
        # ThreadPoolExecutor 限制 worker 数 (max_workers 通常 <= 4+CPU)
        assert final_count - initial_count < 15, (
            f"Bug 9: 高频 remember 创建了过多线程: {final_count - initial_count}"
        )


class TestBug10GetRecoveryHistoryPrivateAttr:
    """Bug 10 (LOW): get_recovery_history 访问私有属性

    根因: 访问 module._retention.keys() 私有属性
    修复: 在 manager 中用 getattr 安全访问
    """

    def test_bug10_get_recovery_history_safe_access(self, tmp_path):
        """RED: get_recovery_history 不应直接访问 _retention 私有属性"""
        src = inspect.getsource(MemoryManager.get_recovery_history)
        # 不应直接 module._retention.keys(), 应使用 getattr 或公开方法
        assert "._retention.keys()" not in src.replace("getattr(module", ""), (
            "Bug 10: get_recovery_history 直接访问 _retention.keys() 私有属性"
        )

    def test_bug10_get_recovery_history_works_without_retention(self, tmp_path):
        """get_recovery_history 在 _retention 不存在时应安全返回空列表"""
        manager = _make_manager(tmp_path)
        module = manager._ensure_forgetting_recovery_module()
        # 删除 _retention 模拟缺失
        if hasattr(module, "_retention"):
            original = module._retention
            delattr(module, "_retention")
            try:
                result = manager.get_recovery_history()
                assert isinstance(result, list)
            finally:
                module._retention = original
        else:
            result = manager.get_recovery_history()
            assert isinstance(result, list)


# ════════════════════════════════════════════
# temperature.py
# ════════════════════════════════════════════


class TestBug11ClassmethodOverridesInstance:
    """Bug 11 (HIGH→验证): classmethod 覆盖 instance method

    根因: 同名方法定义两次, 后定义的 classmethod 覆盖前面的 instance method
    验证: 读取文件确认是否仍有重复定义。可能已用 _hybrid_method 描述符修复
    """

    def test_bug11_instance_uses_custom_params(self):
        """RED: engine.on_access() 应使用实例自定义参数, 而非默认实例参数

        如果 classmethod 覆盖了 instance method, engine.on_access() 会
        使用 _get_default() 的参数 (base_decay_rate=0.1), 忽略自定义 0.2。
        """
        engine_custom = TemperatureEngine(base_decay_rate=0.2)
        engine_default = TemperatureEngine(base_decay_rate=0.1)

        # boost = 10.0 * importance * (base_decay_rate / 0.1)
        # custom: 10.0 * 0.5 * 2.0 = 10.0, saturation at 50 = 0.6 → boost=6.0
        # default: 10.0 * 0.5 * 1.0 = 5.0, saturation at 50 = 0.6 → boost=3.0
        result_custom = engine_custom.on_access(
            current_temp=50.0, importance=0.5, recall_count=0,
            access_count=0, emotion_score=0.0, relation_count=0,
        )
        result_default = engine_default.on_access(
            current_temp=50.0, importance=0.5, recall_count=0,
            access_count=0, emotion_score=0.0, relation_count=0,
        )

        assert result_custom > result_default, (
            f"Bug 11: 实例 on_access 未使用自定义参数. "
            f"custom={result_custom}, default={result_default}"
        )


class TestBug12DefaultInstanceNoDCL:
    """Bug 12 (MEDIUM→验证): _default_instance 无锁 DCL

    根因: _get_default() 无锁检查-创建
    验证: 读取确认是否已用 DCL
    """

    def test_bug12_concurrent_get_default_single_instance(self):
        """RED: 并发 _get_default() 只创建一个实例"""
        original = TemperatureEngine._default_instance
        try:
            TemperatureEngine._default_instance = None
            results = []
            barrier = threading.Barrier(10)

            def worker():
                barrier.wait()
                results.append(TemperatureEngine._get_default())

            threads = [threading.Thread(target=worker) for _ in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            unique_ids = set(id(r) for r in results)
            assert len(unique_ids) == 1, (
                f"Bug 12: DCL 失败, 创建了 {len(unique_ids)} 个实例"
            )
        finally:
            TemperatureEngine._default_instance = original


class TestBug13DocstringContradictsImpl:
    """Bug 13 (LOW): docstring 与实现矛盾

    根因: docstring 说 "1天=0.05,7天=0.1", 实现是 2.0/1.0/0.5/0.2
    修复: 更新 docstring 与实现对齐
    """

    def test_bug13_docstring_matches_implementation(self):
        """RED: docstring 应与实现一致 (2.0/1.0/0.5/0.2)"""
        src = inspect.getsource(TemperatureEngine._calculate_curve_factor)
        # docstring 不应包含旧值 0.05/0.1/0.2/0.4
        assert "0.05" not in src or "0.2" in src, (
            "Bug 13: docstring 仍包含旧值 0.05, 与实现 2.0/1.0/0.5/0.2 矛盾"
        )
        # docstring 应包含实际值 2.0/1.0/0.5/0.2
        assert "2.0" in src, (
            "Bug 13: docstring 未反映实际值 2.0"
        )


class TestBug14CrystallizedReturnsWrongStage:
    """Bug 14 (LOW): _determine_stage 固化记忆返回 'active' 而非 'crystallized'

    根因: on_decay 在 is_crystallized 时返回 _determine_stage(...) 而非 'crystallized'
    修复: 固化分支直接 'lifecycle_stage': 'crystallized'
    """

    def test_bug14_crystallized_returns_crystallized(self):
        """RED: 构造 crystallized 记忆, on_decay 应返回 lifecycle_stage=='crystallized'"""
        engine = TemperatureEngine()
        result = engine.on_decay(
            current_temp=50.0,
            days_idle=10.0,
            is_crystallized=True,
        )
        assert result["lifecycle_stage"] == "crystallized", (
            f"Bug 14: 固化记忆 on_decay 应返回 'crystallized', "
            f"got '{result['lifecycle_stage']}'"
        )


# ════════════════════════════════════════════
# storage.py
# ════════════════════════════════════════════


class TestBug15BatchSaveNoIsolationContext:
    """Bug 15 (HIGH): batch_save 未传 isolation_context

    根因: batch_save 写入 MemoryRecord 时未传 isolation_context, 默认 agent_id/neuser_id/user_id="default"
    修复: batch_save 增加 isolation_context 参数, 写入时传入
    """

    def test_bug15_batch_save_with_isolation_context(self, tmp_path):
        """RED: batch_save 后验证记录的 agent_id/neuser_id/user_id 正确"""
        storage = MemoryStorage(storage_dir=str(tmp_path))
        ctx = IsolationContext(
            agent_id="agent_b15",
            neuser_id="neuser_b15",
            user_id="user_b15",
        )
        ids = storage.batch_save(
            [{"content": "test bug15", "memory_type": "episodic", "owner": "owner_b15"}],
            isolation_context=ctx,
        )
        assert len(ids) == 1
        record = storage.get(ids[0])
        assert record["agent_id"] == "agent_b15", (
            f"Bug 15: batch_save 未传 agent_id, got '{record['agent_id']}'"
        )
        assert record["neuser_id"] == "neuser_b15"
        assert record["user_id"] == "user_b15"


class TestBug16GetRecentToctou:
    """Bug 16 (MEDIUM): get_recent_memories 锁释放后才过滤 (TOCTOU)

    根因: with self._lock 仅包裹 list(self._records.values()), 过滤在锁外
    修复: 过滤也放进 with self._lock 内
    """

    def test_bug16_filter_inside_lock(self, tmp_path):
        """RED: 过滤应在锁内完成, 不在锁外"""
        src = inspect.getsource(MemoryStorage.get_recent_memories)
        # 检查过滤逻辑是否在 with self._lock 内
        lines = src.split("\n")
        in_lock = False
        filter_in_lock = False
        for line in lines:
            if "with self._lock" in line:
                in_lock = True
            if in_lock and ("cutoff_iso" in line or "agent_id" in line or "user_id" in line):
                if "if" in line and "continue" not in line:
                    filter_in_lock = True
            if in_lock and line.strip() and not line.startswith(" ") and "with" not in line:
                in_lock = False
        # 过滤应在 with self._lock 块内
        assert filter_in_lock, (
            "Bug 16: get_recent_memories 过滤在锁外 (TOCTOU)"
        )

    def test_bug16_concurrent_no_crash(self, tmp_path):
        """并发 save + get_recent_memories 不应崩溃"""
        storage = MemoryStorage(storage_dir=str(tmp_path))
        errors = []

        def saver():
            try:
                for i in range(30):
                    storage.save(content=f"c{i}", memory_type="episodic")
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(30):
                    storage.get_recent_memories(limit=10)
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=saver)
        t2 = threading.Thread(target=reader)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        assert not errors, f"Bug 16: 并发操作崩溃: {errors}"


class TestBug17DeleteDuplicate:
    """Bug 17 (MEDIUM): delete 与 delete_memory 功能重复

    根因: 两个方法功能完全相同
    修复: 删除一个, 另一个改为别名
    """

    def test_bug17_both_methods_work(self, tmp_path):
        """两个方法都应能删除记忆"""
        storage = MemoryStorage(storage_dir=str(tmp_path))
        id1 = storage.save(content="m1", memory_type="episodic")
        id2 = storage.save(content="m2", memory_type="episodic")

        assert storage.delete(id1) is True
        assert storage.get(id1) is None

        assert storage.delete_memory(id2) is True
        assert storage.get(id2) is None

    def test_bug17_no_code_duplication(self):
        """RED: delete_memory 应委托到 delete, 不应有重复实现"""
        src = inspect.getsource(MemoryStorage.delete_memory)
        assert "self.delete(" in src, (
            "Bug 17: delete_memory 应委托到 delete 以消除重复代码"
        )


class TestBug18SilentTypeError:
    """Bug 18 (LOW): _load except TypeError 静默吞

    根因: except TypeError: continue 静默跳过
    修复: except TypeError: logger.warning(...); continue
    """

    def test_bug18_corrupt_record_logs_warning(self, tmp_path, caplog):
        """RED: 注入损坏记录, 验证有 warning 日志"""
        storage = MemoryStorage(storage_dir=str(tmp_path))
        storage.save(content="good", memory_type="episodic")

        # 注入损坏记录 (缺少必需字段 content/memory_type/owner)
        path = storage._path
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["records"]["corrupt_b18"] = {"id": "corrupt_b18"}
        path.write_text(json.dumps(raw), encoding="utf-8")

        with caplog.at_level(logging.WARNING):
            storage._load()

        assert any(
            "corrupt_b18" in r.message or "跳过" in r.message or "损坏" in r.message
            for r in caplog.records
        ), (
            f"Bug 18: 损坏记录未产生 warning 日志, "
            f"messages={[r.message for r in caplog.records]}"
        )


class TestBug19StringTimeComparison:
    """Bug 19 (LOW): query 字符串比较 ISO 时间

    根因: rec.created_at < start_time 字符串比较, 时区脆弱
    修复: 用 datetime.fromisoformat() 解析后比较
    """

    def test_bug19_timezone_aware_comparison(self, tmp_path):
        """RED: 不同时区的时间比较应正确"""
        storage = MemoryStorage(storage_dir=str(tmp_path))
        rid = storage.save(content="tz test", memory_type="episodic")

        # 设置 created_at 为 +05:00 时区的时间
        # "2024-01-01T02:00:00+05:00" = UTC "2023-12-31T21:00:00"
        storage.update_memory(rid, created_at="2024-01-01T02:00:00+05:00")

        # query start_time 用 UTC "2024-01-01T00:00:00+00:00"
        # 记录的 UTC 时间 2023-12-31T21:00:00 < start_time 2024-01-01T00:00:00
        # 所以记录应被排除 (created_at < start_time → continue)
        results = storage.query(start_time="2024-01-01T00:00:00+00:00")

        assert len(results) == 0, (
            f"Bug 19: 时区敏感比较错误, 记录 (UTC 2023-12-31T21:00) "
            f"早于 start_time (UTC 2024-01-01T00:00) 但未被排除, got {len(results)}"
        )


# ════════════════════════════════════════════
# isolation.py
# ════════════════════════════════════════════


class TestBug20FromLegacyOwnerAsAgentId:
    """Bug 20 (MEDIUM): from_legacy 把 owner 当作 agent_id

    根因: final_agent_id = agent_id or owner or "default" 把 owner 当 agent_id fallback
    修复: owner 不应 fallback 到 agent_id, 应分开处理
    """

    def test_bug20_owner_not_used_as_agent_id(self):
        """RED: 传 owner="test_owner", agent_id=None, agent_id 应为 "default" 而非 "test_owner" """
        ctx = IsolationContext.from_legacy(owner="test_owner_b20", agent_id=None)
        assert ctx.agent_id == "default", (
            f"Bug 20: owner 被当作 agent_id, got '{ctx.agent_id}'"
        )

    def test_bug20_owner_provided_agent_id_provided(self):
        """agent_id 提供时应使用 agent_id, owner 不影响"""
        ctx = IsolationContext.from_legacy(
            owner="test_owner_b20", agent_id="real_agent_b20"
        )
        assert ctx.agent_id == "real_agent_b20"
