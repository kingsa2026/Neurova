"""
TDD 修复测试 - 18个bug清单(Bug 18与Bug 6合并)

按红绿灯TDD方法编写。每个测试对应一个bug。
- RED: 测试应失败(修复前)
- GREEN: 修复后通过
- false positive: 测试立即通过→跳过并报告

Bug 清单:
    Bug 1  (HIGH)  WorkingMemoryAugmenter 无锁
    Bug 2  (MEDIUM) get() 无法区分 cache miss vs cached None
    Bug 3  (LOW)   self.memory_manager 死代码
    Bug 4  (HIGH)  chat_pipeline 注入 MemCore(无 recall) 给 CrystallizedExp
    Bug 5  (HIGH)  缓存键无 user_id/agent_id,跨用户污染
    Bug 6/18 (LOW) mem_core 调用 flush_to_long_term_memory (验证 false positive)
    Bug 7  (MEDIUM) _execute_strict 超时后 task 未清理
    Bug 8  (MEDIUM) _execute_elastic 重试覆盖 _running_tasks
    Bug 9  (LOW)   cleanup_completed_contexts 未持锁
    Bug 10 (LOW)   cancel() 后不 await task
    Bug 11 (LOW)   _execute_infinite 双重赋值 context.error
    Bug 12 (MEDIUM) sleep_module TOCTOU
    Bug 13 (MEDIUM) self_model_module substring 匹配
    Bug 14 (MEDIUM) emotion_module 阈值重复定义
    Bug 15 (LOW)   emotion_module _init_db 静默吞异常
    Bug 16 (MEDIUM) meta_cognition_module 并发覆盖
    Bug 17 (MEDIUM) explainability_module 空字典 max
"""

import asyncio
import inspect
import json
import logging
import sqlite3
import threading
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


# ============================================================
# Bug 1: WorkingMemoryAugmenter 完全无锁
# ============================================================


def test_bug1_working_memory_concurrent_add_evict_no_error():
    """Bug 1: 并发 add + _evict 不应抛 RuntimeError"""
    from neurova.cognitive_layers.memory_layer.working_memory import (
        WorkingMemoryAugmenter,
    )

    augmenter = WorkingMemoryAugmenter(capacity=5)
    errors = []

    def worker():
        try:
            tid = threading.current_thread().ident
            for i in range(50):
                augmenter.add(f"key_{tid}_{i}", content=f"value_{i}", importance=0.5)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"并发 add/_evict 抛出错误: {errors}"


def test_bug1_working_memory_has_lock():
    """Bug 1: WorkingMemoryAugmenter 应有 _lock 字段"""
    from neurova.cognitive_layers.memory_layer.working_memory import (
        WorkingMemoryAugmenter,
    )

    augmenter = WorkingMemoryAugmenter()
    assert hasattr(augmenter, "_lock"), "WorkingMemoryAugmenter 应有 _lock 字段"


# ============================================================
# Bug 2: get() 返回 None 无法区分 cache miss vs cached None
# ============================================================


def test_bug2_working_memory_get_distinguishes_miss_from_none():
    """Bug 2: 存 None 值,验证 get 返回 None != miss 的 _MISSING"""
    from neurova.cognitive_layers.memory_layer.working_memory import (
        _MISSING,
        WorkingMemoryAugmenter,
    )

    augmenter = WorkingMemoryAugmenter()

    # 存 None 值
    augmenter.add("key_with_none", content=None)

    # 获取存了 None 的 key - 应返回 None (不是 _MISSING)
    result = augmenter.get("key_with_none")
    assert result is None, f"存了 None 的 key 应返回 None, got {result!r}"

    # 获取不存在的 key - 应返回 _MISSING (不是 None)
    result = augmenter.get("missing_key")
    assert result is _MISSING, (
        f"缺失 key 应返回 _MISSING sentinel 区分 cache miss, got {result!r}"
    )


# ============================================================
# Bug 3: self.memory_manager 死代码
# ============================================================


def test_bug3_working_memory_no_dead_memory_manager_field():
    """Bug 3: 验证 memory_manager 死代码字段已删除"""
    from neurova.cognitive_layers.memory_layer import working_memory

    source = inspect.getsource(working_memory)
    assert "self.memory_manager" not in source, (
        "死代码: self.memory_manager 字段应删除或在 eviction 策略中实际使用"
    )


# ============================================================
# Bug 4: chat_pipeline 注入 MemCore 给 CrystallizedExp,但 MemCore 无 recall()
# ============================================================


@pytest.mark.asyncio
async def test_bug4_chat_pipeline_injects_memory_manager_with_recall():
    """Bug 4: chat_pipeline 应注入有 recall() 的 memory_manager,而非 memory_agent"""
    from neurova.agent.chat_pipeline import ChatPipeline

    class MockMemoryManager:
        """有 recall() 方法的 MemoryManager"""

        def recall(self, query, limit=5):
            return [
                {
                    "id": "1",
                    "content": "test",
                    "importance": 0.5,
                    "temperature": 50.0,
                    "source": "memory",
                }
            ]

    class MockMemCore:
        """无 recall() 方法的 MemCore"""

        pass

    agent = SimpleNamespace(
        memory_agent=MockMemCore(),
        memory_manager=MockMemoryManager(),
        crystallizer=None,
        unified_retriever=None,
        config=SimpleNamespace(agent_id="test-agent"),
    )

    pipeline = ChatPipeline(agent)

    # 验证注入的 memory_manager 有 recall() 方法
    injected = pipeline.crystallized_experience_manager._memory_manager
    assert injected is not None, "应注入 memory_manager"
    assert hasattr(injected, "recall"), (
        f"注入的 memory_manager 应有 recall() 方法, got {type(injected).__name__}"
    )

    # 验证 _fallback_to_memory 不抛 AttributeError
    result = await pipeline.crystallized_experience_manager._fallback_to_memory(
        "test query", limit=5
    )
    assert result is not None


# ============================================================
# Bug 5: 缓存键无 user_id/agent_id,跨用户污染
# ============================================================


def test_bug5_cache_key_includes_user_and_agent_id():
    """Bug 5: 不同 agent/user 相同查询应产生不同缓存键"""
    from neurova.agent.crystallized_experience_manager import (
        CrystallizedExperienceManager,
    )

    manager_a = CrystallizedExperienceManager(agent_id="agent_a", user_id="user_a")
    manager_b = CrystallizedExperienceManager(agent_id="agent_b", user_id="user_b")

    key_a = manager_a._hash_query("same query")
    key_b = manager_b._hash_query("same query")

    assert key_a != key_b, (
        f"不同 agent/user 的相同查询应产生不同缓存键, got {key_a} == {key_b}"
    )


def test_bug5_cache_key_same_agent_user_consistent():
    """Bug 5: 同一 agent/user 的相同查询应产生相同缓存键"""
    from neurova.agent.crystallized_experience_manager import (
        CrystallizedExperienceManager,
    )

    manager = CrystallizedExperienceManager(agent_id="agent_a", user_id="user_a")
    key1 = manager._hash_query("query")
    key2 = manager._hash_query("query")

    assert key1 == key2, "同一 agent/user 相同查询应产生相同缓存键"


# ============================================================
# Bug 6/18: mem_core.py 调用 flush_to_long_term_memory() (验证 false positive)
# ============================================================


def test_bug6_mem_core_uses_flush_not_flush_to_long_term_memory():
    """Bug 6/18: 验证 mem_core.py 调用 flush() 而非 flush_to_long_term_memory()

    注: 此 bug 在 mem_core.py 中已修复(line 657-659 已使用 flush()),
    若测试立即通过 → false positive,跳过并报告。
    使用 AST 检查实际属性访问,排除注释中的字符串。
    """
    import ast

    from neurova import mem_core

    source = inspect.getsource(mem_core)
    tree = ast.parse(source)

    # 遍历 AST,查找实际的 flush_to_long_term_memory 属性访问(排除注释)
    flush_to_ltm_accesses = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "flush_to_long_term_memory":
            flush_to_ltm_accesses.append(node)

    assert not flush_to_ltm_accesses, (
        f"mem_core.py 不应调用 flush_to_long_term_memory(), "
        f"found {len(flush_to_ltm_accesses)} actual attribute accesses"
    )

    # 应有 flush() 属性访问
    flush_accesses = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr == "flush"
    ]
    assert flush_accesses, "mem_core.py 应调用 conversation_buffer.flush()"


# ============================================================
# Bug 7: _execute_strict 超时后 task 未清理
# ============================================================


@pytest.mark.asyncio
async def test_bug7_execute_strict_timeout_cancels_background_task():
    """Bug 7: 超时后后台 task 应被 cancel,不继续运行"""
    from neurova.agent.tool_execution_manager import (
        ExecutionStatus,
        TimeoutStrategy,
        ToolExecutionManager,
    )

    task_was_cancelled = False

    class SlowExecutor:
        async def execute_tool(self, name, params, user_input):
            nonlocal task_was_cancelled
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                task_was_cancelled = True
                raise

    manager = ToolExecutionManager()
    context = await manager.execute(
        tool_name="slow_tool",
        params={},
        user_input="test",
        executor=SlowExecutor(),
        timeout=0.1,
        strategy=TimeoutStrategy.STRICT,
    )

    assert context.status == ExecutionStatus.TIMEOUT

    # 给取消传播时间
    await asyncio.sleep(0.3)

    # Bug 7: 后台 task 应被 cancel
    assert task_was_cancelled, "超时后后台 task 应被 cancel,不应继续运行"


# ============================================================
# Bug 8: _execute_elastic 重试覆盖 _running_tasks
# ============================================================


@pytest.mark.asyncio
async def test_bug8_execute_elastic_retry_cancels_old_task():
    """Bug 8: 重试时应 cancel 旧 task"""
    from neurova.agent.tool_execution_manager import (
        ExecutionStatus,
        TimeoutStrategy,
        ToolExecutionManager,
    )

    cancelled_count = 0

    class SlowExecutor:
        async def execute_tool(self, name, params, user_input):
            nonlocal cancelled_count
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                cancelled_count += 1
                raise

    manager = ToolExecutionManager()
    context = await manager.execute(
        tool_name="slow_tool",
        params={},
        user_input="test",
        executor=SlowExecutor(),
        timeout=0.1,
        strategy=TimeoutStrategy.ELASTIC,
        max_retries=2,
    )

    assert context.status == ExecutionStatus.TIMEOUT

    # Bug 8: 重试时旧 task 应被 cancel (至少 1 次,因为第一次超时后重试)
    assert cancelled_count >= 1, (
        f"重试时旧 task 应被 cancel, got cancelled_count={cancelled_count}"
    )


# ============================================================
# Bug 9: cleanup_completed_contexts 未持锁
# ============================================================


def test_bug9_tool_execution_manager_has_lock():
    """Bug 9: ToolExecutionManager 应有 _lock 字段"""
    from neurova.agent.tool_execution_manager import ToolExecutionManager

    manager = ToolExecutionManager()
    assert hasattr(manager, "_lock"), "ToolExecutionManager 应有 _lock 字段"


def test_bug9_cleanup_completed_contexts_acquires_lock():
    """Bug 9: cleanup_completed_contexts 应在 with self._lock 内遍历"""
    from neurova.agent.tool_execution_manager import ToolExecutionManager

    source = inspect.getsource(ToolExecutionManager.cleanup_completed_contexts)
    assert "with self._lock" in source, (
        f"cleanup_completed_contexts 应在 with self._lock 内遍历+删除\n{source}"
    )


# ============================================================
# Bug 10: cancel() 后不 await task
# ============================================================


def test_bug10_cancel_awaits_task():
    """Bug 10: cancel() 应在 task.cancel() 后 await task

    使用 AST 检查实际 await 语句,排除注释中的 "await task" 字符串。
    """
    import ast
    import textwrap

    from neurova.agent.tool_execution_manager import ToolExecutionManager

    source = textwrap.dedent(inspect.getsource(ToolExecutionManager.cancel))
    tree = ast.parse(source)

    has_cancel = False
    has_await_task = False

    for node in ast.walk(tree):
        # 检查是否有 task.cancel() 调用
        if isinstance(node, ast.Call):
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "cancel"
                and isinstance(func.value, ast.Name)
                and func.value.id == "task"
            ):
                has_cancel = True
        # 检查是否有 await task 语句
        if isinstance(node, ast.Await):
            val = node.value
            if isinstance(val, ast.Name) and val.id == "task":
                has_await_task = True
            # 也接受 await asyncio.wait_for(task, ...)
            elif isinstance(val, ast.Call):
                func = val.func
                if (
                    isinstance(func, ast.Attribute)
                    and func.attr == "wait_for"
                ):
                    has_await_task = True

    assert has_cancel, "cancel() 应调用 task.cancel()"
    assert has_await_task, (
        f"cancel() 应在 task.cancel() 后 await task 避免 pending 警告\n{source}"
    )


# ============================================================
# Bug 11: _execute_infinite 双重赋值 context.error
# ============================================================


def test_bug11_execute_infinite_no_double_error_assignment():
    """Bug 11: _execute_infinite 不应设 context.error(由 execute() 统一设)"""
    from neurova.agent.tool_execution_manager import ToolExecutionManager

    source = inspect.getsource(ToolExecutionManager._execute_infinite)
    assert "context.error" not in source, (
        f"_execute_infinite 不应设 context.error (execute() 已统一处理)\n{source}"
    )


# ============================================================
# Bug 12: sleep_module TOCTOU
# ============================================================


def test_bug12_sleep_module_consolidate_check_inside_lock():
    """Bug 12: consolidate_memory 的 _is_sleeping 检查应在 with self._lock 之后(TOCTOU fix)"""
    from neurova.cognitive_layers.memory_layer.modules.sleep_module import SleepModule

    source = inspect.getsource(SleepModule.consolidate_memory)

    lock_pos = source.find("with self._lock")
    check_pos = source.find("if not self._is_sleeping")

    assert lock_pos != -1, "consolidate_memory 应使用 with self._lock"
    assert check_pos != -1, "consolidate_memory 应检查 _is_sleeping"
    assert check_pos > lock_pos, (
        f"consolidate_memory: _is_sleeping 检查(pos {check_pos})应在 with self._lock"
        f"(pos {lock_pos})之后(锁内),修复 TOCTOU"
    )


def test_bug12_sleep_module_cleanup_check_inside_lock():
    """Bug 12: cleanup_memory 的 _is_sleeping 检查应在 with self._lock 之后"""
    from neurova.cognitive_layers.memory_layer.modules.sleep_module import SleepModule

    source = inspect.getsource(SleepModule.cleanup_memory)

    lock_pos = source.find("with self._lock")
    check_pos = source.find("if not self._is_sleeping")

    assert lock_pos != -1, "cleanup_memory 应使用 with self._lock"
    assert check_pos != -1, "cleanup_memory 应检查 _is_sleeping"
    assert check_pos > lock_pos, (
        f"cleanup_memory: _is_sleeping 检查(pos {check_pos})应在 with self._lock"
        f"(pos {lock_pos})之后(锁内),修复 TOCTOU"
    )


def test_bug12_sleep_module_dream_check_inside_lock():
    """Bug 12: dream 的 _is_sleeping 检查应在 with self._lock 之后"""
    from neurova.cognitive_layers.memory_layer.modules.sleep_module import SleepModule

    source = inspect.getsource(SleepModule.dream)

    lock_pos = source.find("with self._lock")
    check_pos = source.find("if not self._is_sleeping")

    assert lock_pos != -1, "dream 应使用 with self._lock"
    assert check_pos != -1, "dream 应检查 _is_sleeping"
    assert check_pos > lock_pos, (
        f"dream: _is_sleeping 检查(pos {check_pos})应在 with self._lock"
        f"(pos {lock_pos})之后(锁内),修复 TOCTOU"
    )


# ============================================================
# Bug 13: self_model_module substring 匹配
# ============================================================


def test_bug13_self_model_no_substring_false_match():
    """Bug 13: "go" 不应通过子串匹配 "golang\""""
    from neurova.cognitive_layers.memory_layer.modules.self_model_module import (
        SelfModelModule,
    )

    sm = SelfModelModule()
    sm.update_capability("golang", 0.9)

    result = sm.assess_task("build service", requirements=["go"])

    matches = result["capability_matches"]
    matched_caps = [m[1] for m in matches]

    assert "golang" not in matched_caps, (
        f"'go' 不应通过子串匹配 'golang', got matches: {matched_caps}"
    )


def test_bug13_self_model_exact_match_still_works():
    """Bug 13: 精确匹配应仍然工作"""
    from neurova.cognitive_layers.memory_layer.modules.self_model_module import (
        SelfModelModule,
    )

    sm = SelfModelModule()
    sm.update_capability("search", 0.9)

    result = sm.assess_task("search task", requirements=["search"])

    matches = result["capability_matches"]
    matched_caps = [m[1] for m in matches]
    assert "search" in matched_caps, "精确匹配 'search' 应工作"


# ============================================================
# Bug 14: emotion_module 阈值重复定义
# ============================================================


def test_bug14_emotion_threshold_uses_public_property():
    """Bug 14: set_emotion 应使用 emotional_protection_threshold (公开属性)"""
    from neurova.cognitive_layers.memory_layer.modules.emotion_module import (
        EmotionModule,
        EmotionState,
        EmotionType,
    )

    em = EmotionModule()
    # RSI 调整公开阈值
    em.emotional_protection_threshold = 0.3

    # 设置 intensity=0.4 (高于新阈值 0.3,低于旧私有阈值 0.8)
    em.set_emotion(
        "mem1",
        EmotionState(
            primary_emotion=EmotionType.SADNESS,
            intensity=0.4,
            valence=-0.5,
            arousal=0.5,
        ),
    )

    feedback = em.get_feedback()
    # Bug 14: 应使用公开阈值 0.3,所以 protection 应被触发
    assert feedback["protection_triggered"] >= 1, (
        f"intensity 0.4 >= 阈值 0.3 应触发保护, got {feedback}"
    )


def test_bug14_emotion_no_duplicate_threshold_fields():
    """Bug 14: 不应有 _emotional_protection_threshold 和 emotional_protection_threshold 两个阈值"""
    from neurova.cognitive_layers.memory_layer.modules.emotion_module import EmotionModule

    em = EmotionModule()
    # 不应同时存在私有和公开两个阈值字段
    has_private = hasattr(em, "_emotional_protection_threshold")
    has_public = hasattr(em, "emotional_protection_threshold")

    # 修复后应只有一个(公开属性),或两者指向同一值
    if has_private and has_public:
        assert em._emotional_protection_threshold == em.emotional_protection_threshold, (
            f"阈值应统一, got private={em._emotional_protection_threshold}, "
            f"public={em.emotional_protection_threshold}"
        )


# ============================================================
# Bug 15: emotion_module _init_db 静默吞异常
# ============================================================


def test_bug15_emotion_init_db_logs_corrupt_records(tmp_path, caplog):
    """Bug 15: _init_db 应记录损坏记录的 warning"""
    db_path = str(tmp_path / "test_emotion.db")

    # 创建带损坏记录的 DB
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memory_emotions (
            memory_id TEXT PRIMARY KEY,
            emotion_data TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute(
        "INSERT INTO memory_emotions (memory_id, emotion_data) VALUES (?, ?)",
        ("valid_id", json.dumps({"primary_emotion": "joy", "intensity": 0.5})),
    )
    conn.execute(
        "INSERT INTO memory_emotions (memory_id, emotion_data) VALUES (?, ?)",
        ("corrupt_id", "NOT_VALID_JSON{{{"),
    )
    conn.commit()
    conn.close()

    from neurova.cognitive_layers.memory_layer.modules.emotion_module import EmotionModule

    with caplog.at_level(logging.WARNING, logger="neurova.cognitive_layers.memory_layer.modules.emotion_module"):
        EmotionModule(db_path=db_path)

    # Bug 15: 应有 warning 日志记录损坏记录
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any(
        "corrupt_id" in r.getMessage() or "损坏" in r.getMessage() or "跳过" in r.getMessage()
        for r in warnings
    ), f"应记录损坏记录的 warning, got: {[r.getMessage() for r in warnings]}"


# ============================================================
# Bug 16: meta_cognition_module 并发覆盖
# ============================================================


def test_bug16_meta_cognition_concurrent_no_overwrite():
    """Bug 16: 两个并发 start_process 不互相覆盖"""
    from neurova.cognitive_layers.memory_layer.modules.meta_cognition_module import (
        CognitiveProcess,
        MetaCognitionModule,
    )

    mc = MetaCognitionModule()

    # 启动过程 A
    event_a = mc.start_process(CognitiveProcess.RETRIEVAL)

    # 启动过程 B (不同类型)
    event_b = mc.start_process(CognitiveProcess.REASONING)

    # 结束过程 A - 应为 RETRIEVAL 类型
    event_a_result = mc.end_process(event_a, "process A done", success=True)

    # Bug 16: 过程 A 应保持 RETRIEVAL,不被过程 B 覆盖为 REASONING
    assert event_a_result.process_type == CognitiveProcess.RETRIEVAL, (
        f"过程 A 应为 RETRIEVAL, got {event_a_result.process_type} (被过程 B 覆盖)"
    )

    # 结束过程 B - 应为 REASONING
    event_b_result = mc.end_process(event_b, "process B done", success=True)
    assert event_b_result.process_type == CognitiveProcess.REASONING, (
        f"过程 B 应为 REASONING, got {event_b_result.process_type}"
    )


# ============================================================
# Bug 17: explainability_module 空字典 max
# ============================================================


def test_bug17_explainability_empty_factors_no_error():
    """Bug 17: 传空 factors 字典不抛 ValueError"""
    from neurova.cognitive_layers.memory_layer.modules.explainability_module import (
        ExplainabilityModule,
    )

    em = ExplainabilityModule()

    # top_id 对应空 factors 字典 → max() 应抛 ValueError (修复前)
    explanation = em.explain_retrieval(
        query="test",
        retrieved_ids=["mem1"],
        scores={"mem1": 0.9},
        factors={"mem1": {}},  # 空 factors
    )

    assert explanation is not None
    assert len(explanation.reasons) >= 2  # 前两条原因应仍存在


def test_bug17_explainability_no_factors_dict():
    """Bug 17: factors=None 不抛错"""
    from neurova.cognitive_layers.memory_layer.modules.explainability_module import (
        ExplainabilityModule,
    )

    em = ExplainabilityModule()

    explanation = em.explain_retrieval(
        query="test",
        retrieved_ids=["mem1"],
        scores={"mem1": 0.9},
        factors=None,
    )

    assert explanation is not None


def test_bug17_explainability_empty_retrieved_ids():
    """Bug 17: 空 retrieved_ids 不抛错"""
    from neurova.cognitive_layers.memory_layer.modules.explainability_module import (
        ExplainabilityModule,
    )

    em = ExplainabilityModule()

    explanation = em.explain_retrieval(
        query="test",
        retrieved_ids=[],
        scores={},
        factors=None,
    )

    assert explanation is not None
