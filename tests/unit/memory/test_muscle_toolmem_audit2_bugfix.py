"""
muscle_memory.py 与 tool_memory_integration.py 15 个 bug 的 TDD 修复测试

方法论: 红绿灯 TDD — 每个测试对应一个 bug，先 RED（失败）再 GREEN（修复后通过）。

Bug 列表:
- muscle_memory.py: 1-8
- tool_memory_integration.py: 9-15
"""
import inspect
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import pytest

from neurova.cognitive_layers.memory_layer.muscle_memory import (
    MuscleMemory,
    MuscleMemoryItem,
    MemoryLevel,
)
from neurova.cognitive_layers.memory_layer import muscle_memory as muscle_memory_module
from neurova.cognitive_layers.memory_layer import tool_memory_integration as tmi_module
from neurova.cognitive_layers.memory_layer.tool_memory_integration import (
    ToolMemoryIntegration,
    ToolUsageRecord,
)


# ============================================================
# Bug 1 (HIGH): match()/match_by_query() 无锁遍历共享字典
# ============================================================


class TestBug1ConcurrentMatchNoLock:
    def test_match_methods_acquire_lock(self):
        """match/match_by_query/_match_l1/l2/l3 应获取 self._lock 保证线程安全"""
        for method_name in (
            "match",
            "match_by_query",
            "_match_l1",
            "_match_l2",
            "_match_l3",
        ):
            source = inspect.getsource(getattr(MuscleMemory, method_name))
            assert "self._lock" in source, (
                f"{method_name} 应获取 self._lock 以保证遍历共享字典时的线程安全"
            )

    def test_concurrent_record_and_match_no_runtime_error(self):
        """并发 record_usage + match/match_by_query 不应抛 RuntimeError（结构+行为双保险）"""
        mm = MuscleMemory()
        for i in range(10):
            mm.record_usage(
                tool_name=f"tool_{i % 3}",
                query=f"query number {i}",
                parameters={},
                success=True,
            )

        errors: list = []

        def worker_record():
            try:
                for i in range(80):
                    mm.record_usage(
                        tool_name=f"tool_{i % 3}",
                        query=f"query number {i}",
                        parameters={},
                        success=True,
                    )
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        def worker_match():
            try:
                for i in range(80):
                    mm.match(tool_name=f"tool_{i % 3}", query=f"query number {i}")
                    mm.match_by_query(query=f"query number {i}")
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=worker_record) for _ in range(3)]
        threads += [threading.Thread(target=worker_match) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"并发操作抛出异常: {errors}"


# ============================================================
# Bug 2 (MEDIUM): _vector_index 死代码
# ============================================================


class TestBug2VectorIndexDeadCode:
    def test_vector_index_removed_or_used(self):
        """_vector_index 定义后从未写入也从未读取，应被移除"""
        source = inspect.getsource(MuscleMemory)
        assert "_vector_index" not in source, (
            "_vector_index 是死代码（定义后从未写入或读取），应删除"
        )


# ============================================================
# Bug 3 (MEDIUM): _keyword_index 维护但从不查询
# ============================================================


class TestBug3KeywordIndexDeadCode:
    def test_keyword_index_used_or_removed(self):
        """_keyword_index 仅被 _add/_remove 维护，match 路径从不查询，应使用或删除"""
        match_path_source = (
            inspect.getsource(MuscleMemory.match)
            + inspect.getsource(MuscleMemory.match_by_query)
            + inspect.getsource(MuscleMemory._match_l1)
            + inspect.getsource(MuscleMemory._match_l2)
            + inspect.getsource(MuscleMemory._match_l3)
        )
        class_source = inspect.getsource(MuscleMemory)

        uses_in_match = "_keyword_index" in match_path_source
        index_removed = "_keyword_index" not in class_source

        assert uses_in_match or index_removed, (
            "_keyword_index 是死代码：仅被维护但 match 路径从不查询"
        )


# ============================================================
# Bug 4 (MEDIUM): _find_item 忽略 vector_fp 参数
# ============================================================


class TestBug4FindItemIgnoresVectorFp:
    def test_find_item_respects_vector_fp(self):
        """两条相同 fingerprint 但不同 vector_fp 的记录不应合并"""
        mm = MuscleMemory()
        item1 = MuscleMemoryItem(
            id="id1",
            tool_name="t1",
            query_fingerprint="fp",
            vector_fingerprint="v1",
        )
        mm._l3["id1"] = item1
        mm._add_to_tool_index(item1)

        # 查询相同 fingerprint 但不同 vector_fp，不应返回 item1
        found = mm._find_item("t1", "fp", "v2")
        assert found is None or found.id != "id1", (
            f"_find_item 应尊重 vector_fp 参数；返回了 {found}"
        )


# ============================================================
# Bug 5 (HIGH): check_forgotten 中 L1/L2 阈值相同导致级联降级
# ============================================================


class TestBug5CascadeDemote:
    def test_no_cascade_demote_l1_to_l3(self):
        """30 天未用的 L1 条目应只降到 L2，不应级联降到 L3"""
        mm = MuscleMemory()
        old_time = time.time() - 31 * 86400  # 31 天前
        item = MuscleMemoryItem(
            id="old1",
            tool_name="t1",
            query_fingerprint="fp",
            level=MemoryLevel.L1,
            last_used=old_time,
        )
        mm._l1["old1"] = item
        mm._add_to_tool_index(item)

        mm.check_forgotten()

        assert "old1" in mm._l2, (
            f"应降级到 L2 而非 L3；L1={'old1' in mm._l1}, "
            f"L2={'old1' in mm._l2}, L3={'old1' in mm._l3}"
        )
        assert "old1" not in mm._l3


# ============================================================
# Bug 6 (LOW): _compute_confidence 空指纹匹配
# ============================================================


class TestBug6EmptyFingerprintFalseMatch:
    def test_empty_fingerprint_no_high_confidence(self):
        """两个空指纹条目不应产生高置信度匹配"""
        mm = MuscleMemory()
        item = MuscleMemoryItem(
            id="i1",
            tool_name="t1",
            query_fingerprint="",
            vector_fingerprint="",
        )
        conf = mm._compute_confidence(item, "", "")
        assert conf < 0.5, (
            f"空指纹不应产生高置信度；当前 conf={conf}"
        )


# ============================================================
# Bug 7 (LOW): 三个死代码方法
# ============================================================


class TestBug7DeadCodeMethods:
    def test_dead_methods_removed(self):
        """_extract_param_template/_item_to_result/_get_vector_store 应删除"""
        source = inspect.getsource(MuscleMemory)
        for dead_method in (
            "_extract_param_template",
            "_item_to_result",
            "_get_vector_store",
        ):
            assert dead_method not in source, (
                f"死方法 {dead_method} 应被删除"
            )


# ============================================================
# Bug 8 (LOW): _generate_item_id 用 time.time() 碰撞
# ============================================================


class TestBug8ItemIdCollision:
    def test_generate_item_id_no_collision_same_time(self):
        """同一时刻生成两个 ID 不应碰撞（使用 uuid4）"""
        mm = MuscleMemory()
        with patch.object(muscle_memory_module.time, "time", return_value=12345.0):
            id1 = mm._generate_item_id("tool1", "query1")
            id2 = mm._generate_item_id("tool1", "query1")
        assert id1 != id2, (
            f"同一 time.time() 下生成相同 ID={id1}，应加入 uuid4 防碰撞"
        )


# ============================================================
# Bug 9 (HIGH): ToolMemoryIntegration 全类无锁
# ============================================================


class TestBug9NoLock:
    def test_has_rlock_attribute(self):
        """ToolMemoryIntegration 应有 self._lock (RLock)"""
        tmi = ToolMemoryIntegration()
        assert hasattr(tmi, "_lock"), "ToolMemoryIntegration 应有 self._lock"
        # RLock 支持 acquire/release 且可重入
        assert hasattr(tmi._lock, "acquire"), "self._lock 应是 Lock/RLock 对象"

    def test_record_and_read_methods_acquire_lock(self):
        """record_tool_usage/get_tool_stats/get_tool_recommendations 应获取 self._lock"""
        for method_name in (
            "record_tool_usage",
            "get_tool_stats",
            "get_tool_recommendations",
        ):
            source = inspect.getsource(getattr(ToolMemoryIntegration, method_name))
            assert "self._lock" in source, (
                f"{method_name} 应获取 self._lock 保证并发安全"
            )

    def test_concurrent_record_and_stats_no_error(self):
        """并发 record_tool_usage + get_tool_stats/get_tool_recommendations 不应崩溃"""
        mock_mm = MagicMock()
        tmi = ToolMemoryIntegration(muscle_memory=mock_mm)

        errors: list = []

        def worker_record():
            try:
                for i in range(80):
                    tmi.record_tool_usage(tool_name=f"tool_{i % 5}", success=True)
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        def worker_read():
            try:
                for _ in range(80):
                    tmi.get_tool_stats()
                    tmi.get_tool_recommendations()
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=worker_record) for _ in range(4)]
        threads += [threading.Thread(target=worker_read) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"并发操作抛出异常: {errors}"


# ============================================================
# Bug 10 (HIGH): _cleanup_deprecated_tools 属性名全错
# ============================================================


class TestBug10CleanupAttributeNames:
    def test_cleanup_deprecated_tools_can_access_layers(self):
        """_cleanup_deprecated_tools 应能访问到三层存储（_l1/_l2/_l3）"""
        from neurova.evolution.tool_lifecycle import (
            ToolLifecycleManager,
            ToolLifecycleState,
        )

        mm = MuscleMemory()
        item = MuscleMemoryItem(
            id="dep1",
            tool_name="deprecated_tool",
            query_fingerprint="fp",
            level=MemoryLevel.L1,
        )
        mm._l1["dep1"] = item
        mm._add_to_tool_index(item)

        lifecycle = ToolLifecycleManager()
        lifecycle.register_tool("deprecated_tool")
        lifecycle._entries["deprecated_tool"].state = ToolLifecycleState.ARCHIVED

        tmi = ToolMemoryIntegration(muscle_memory=mm, tool_lifecycle=lifecycle)
        cleaned = tmi._cleanup_deprecated_tools()

        assert cleaned >= 1, f"应清理至少 1 个废弃工具条目；实际 cleaned={cleaned}"
        assert "dep1" not in mm._l1, "废弃工具条目应从 L1 移除"


# ============================================================
# Bug 11 (MEDIUM): record_tool_usage 中 tool_name=None 污染 tool_stats
# ============================================================


class TestBug11ToolNameNonePollution:
    def test_tool_name_none_uses_unknown_key(self):
        """传 tool_name=None 时 tool_stats 的键应为 'unknown' 而非 None"""
        mock_mm = MagicMock()
        tmi = ToolMemoryIntegration(muscle_memory=mock_mm)
        tmi.record_tool_usage(tool_name=None, success=True)

        assert "unknown" in tmi.tool_stats, (
            f"应使用 'unknown' 作键；实际 tool_stats keys={list(tmi.tool_stats.keys())}"
        )
        assert None not in tmi.tool_stats, "None 不应作为 tool_stats 的键"


# ============================================================
# Bug 12 (MEDIUM): record_tool_usage 吞所有异常
# ============================================================


class TestBug12SwallowExceptions:
    def test_type_error_is_reraised(self):
        """TypeError/AttributeError 是编程错误，应 re-raise"""
        mock_mm = MagicMock()
        mock_mm.record_usage.side_effect = TypeError("type error")
        tmi = ToolMemoryIntegration(muscle_memory=mock_mm)

        with pytest.raises(TypeError):
            tmi.record_tool_usage(tool_name="t1", success=True)


# ============================================================
# Bug 13 (MEDIUM): muscle_memory_hits 永远为 0
# ============================================================


class TestBug13MuscleMemoryHitsAlwaysZero:
    def test_muscle_memory_hits_incremented_after_match(self):
        """命中肌肉记忆路径后 muscle_memory_hits 应 > 0"""
        mock_mm = MagicMock()
        mock_item = MagicMock()
        mock_item.tool_name = "file_read"
        mock_item.parameters = {"path": "/tmp"}
        mock_item.metadata = {"tool_source": "skill_system"}
        mock_item.level.value = "l1"
        mock_mm.match_by_query.return_value = [(mock_item, 0.9)]

        tmi = ToolMemoryIntegration(muscle_memory=mock_mm, confidence_threshold=0.8)
        tmi.check_tool_memory("读取文件")

        feedback = tmi.get_feedback()
        assert feedback["muscle_memory_hits"] > 0, (
            f"命中肌肉记忆后 muscle_memory_hits 应 > 0；实际={feedback['muscle_memory_hits']}"
        )


# ============================================================
# Bug 14 (LOW): _should_demote_from_muscle_memory 静默吞异常
# ============================================================


class TestBug14ShouldDemoteSilentExcept:
    def test_should_demote_logs_exception(self):
        """异常应被记录而非静默吞掉"""
        mock_mm = MagicMock()
        mock_lifecycle = MagicMock()
        mock_lifecycle.get_state.side_effect = RuntimeError("db error")

        tmi = ToolMemoryIntegration(
            muscle_memory=mock_mm, tool_lifecycle=mock_lifecycle
        )

        with patch.object(tmi_module, "logger") as mock_logger:
            result = tmi._should_demote_from_muscle_memory("any_tool")

        # 仍应返回 False（不阻断流程）
        assert result is False
        # 但应有日志记录
        mock_logger.exception.assert_called_once()


# ============================================================
# Bug 15 (LOW): get_tool_recommendations 未持锁排序
# ============================================================


class TestBug15RecommendationsNoLock:
    def test_get_tool_recommendations_acquires_lock(self):
        """get_tool_recommendations 中的 sorted() 应在 self._lock 保护下执行"""
        source = inspect.getsource(ToolMemoryIntegration.get_tool_recommendations)
        assert "self._lock" in source, (
            "get_tool_recommendations 应获取 self._lock 保护 sorted() 防止并发字典大小变化"
        )

    def test_concurrent_record_and_recommendations_no_crash(self):
        """并发 record_tool_usage + get_tool_recommendations 不应抛 RuntimeError"""
        mock_mm = MagicMock()
        tmi = ToolMemoryIntegration(muscle_memory=mock_mm)
        # 预填充 stats 让 sorted 有数据
        for i in range(5):
            tmi.record_tool_usage(tool_name=f"tool_{i}", success=True)

        errors: list = []

        def worker_record():
            try:
                for i in range(120):
                    tmi.record_tool_usage(
                        tool_name=f"tool_{i % 5}", success=(i % 2 == 0)
                    )
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        def worker_recom():
            try:
                for _ in range(120):
                    tmi.get_tool_recommendations()
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=worker_record) for _ in range(4)]
        threads += [threading.Thread(target=worker_recom) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"并发操作抛出异常: {errors}"
