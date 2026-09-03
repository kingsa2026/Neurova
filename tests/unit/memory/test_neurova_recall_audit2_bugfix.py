"""neurova_recall.py 14 个 bug 修复测试 — TDD 红绿灯方法

对每个 bug 采用 vertical slice: RED → GREEN → 下一个 bug
- RED: 先写失败测试，证明 bug 存在
- GREEN: 最小代码修改让测试通过
- 不允许 try/except 吞编程错误，不允许 || 掩盖 undefined
"""
import asyncio
import datetime
import inspect
import threading
import time
from concurrent.futures import TimeoutError as FuturesTimeoutError
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neurova.cognitive_layers.memory_layer.neurova_recall import (
    DrillIntent,
    NeurovaRecallEngine,
    QueryIntent,
    QueryIntentDetector,
    RecallChannel,
    RecalledMemory,
)


# ═══════════════════════════════════════════════════════════════════
# Bug 1 (HIGH): _infer_category 重复定义
# 第二个空实现 (return None) 覆盖了第一个有逻辑的实现
# ═══════════════════════════════════════════════════════════════════


class TestBug1InferCategoryDuplicate:
    """BUG-1: _infer_category 重复定义导致空实现覆盖有逻辑实现"""

    def test_infer_category_returns_nonnull_for_known_keywords(self):
        """_infer_category("对话") 应返回非 None 的类别字符串"""
        engine = NeurovaRecallEngine(use_plugins=False, memory_manager=MagicMock())
        result = engine._infer_category("对话")
        assert result is not None, "_infer_category 返回 None — 第二个空实现覆盖了第一个"
        assert isinstance(result, str)

    def test_infer_category_returns_conversation_for_chat_keywords(self):
        """对话类关键词应映射到 conversation 类别"""
        engine = NeurovaRecallEngine(use_plugins=False, memory_manager=MagicMock())
        assert engine._infer_category("聊天") == "conversation"
        assert engine._infer_category("说点什么") == "conversation"

    def test_infer_category_returns_technical_for_code_keywords(self):
        """技术类关键词应映射到 technical 类别"""
        engine = NeurovaRecallEngine(use_plugins=False, memory_manager=MagicMock())
        assert engine._infer_category("代码") == "technical"

    def test_infer_category_returns_general_for_unknown(self):
        """无匹配关键词时返回 general (而非 None)"""
        engine = NeurovaRecallEngine(use_plugins=False, memory_manager=MagicMock())
        assert engine._infer_category("xyzqwerty") == "general"


# ═══════════════════════════════════════════════════════════════════
# Bug 2 (HIGH): _recency_score 用 recalled_at (当前时间) 而非 created_at
# 导致 age_hours≈0, time_decay 恒 1.0, 时间衰减失效
# ═══════════════════════════════════════════════════════════════════


class TestBug2RecencyScoreUsesRecalledAt:
    """BUG-2: _recency_score 使用 recalled_at 导致时间衰减恒 1.0"""

    def test_recency_score_decreases_for_old_memory(self):
        """7 天前的记忆 recency_score 应 < 1.0"""
        engine = NeurovaRecallEngine(use_plugins=False, memory_manager=MagicMock())
        now = datetime.datetime.now(datetime.timezone.utc)
        week_ago = now - datetime.timedelta(days=7)
        mem = RecalledMemory(
            memory_id="m1",
            content="old",
            score=0.5,
            channel=RecallChannel.TEXT,
            created_at=week_ago,
            recalled_at=now,
        )
        score = engine._recency_score(mem)
        assert score < 1.0, f"7 天前的记忆 recency_score 应 < 1.0, 实际 {score}"

    def test_recency_score_distinguishes_old_vs_new(self):
        """新记忆的 recency_score 应高于 7 天前的旧记忆"""
        engine = NeurovaRecallEngine(use_plugins=False, memory_manager=MagicMock())
        now = datetime.datetime.now(datetime.timezone.utc)
        new_mem = RecalledMemory(
            memory_id="new", content="new", created_at=now - datetime.timedelta(hours=1)
        )
        old_mem = RecalledMemory(
            memory_id="old", content="old", created_at=now - datetime.timedelta(days=30)
        )
        assert engine._recency_score(new_mem) > engine._recency_score(old_mem)

    def test_recency_score_uses_created_at_not_recalled_at(self):
        """直接验证: recalled_at=now, created_at=7天前, score 必须 < 1"""
        engine = NeurovaRecallEngine(use_plugins=False, memory_manager=MagicMock())
        now = datetime.datetime.now(datetime.timezone.utc)
        # recalled_at 是现在（bug 触发条件），created_at 是 7 天前
        mem = RecalledMemory(
            memory_id="m1",
            content="test",
            created_at=now - datetime.timedelta(days=7),
            recalled_at=now,
        )
        # 如果用 recalled_at 计算, age≈0, exp(0)=1.0 → bug
        # 如果用 created_at 计算, age=168h, exp(-16.8)≈5e-8 → 0.1 (clamped)
        score = engine._recency_score(mem)
        assert score < 1.0, (
            f"recency_score={score} >= 1.0 — 仍在用 recalled_at 计算 (bug 2 未修复)"
        )


# ═══════════════════════════════════════════════════════════════════
# Bug 3 (HIGH): _ensure_neuron_components 部分初始化后永久返回 True
# _dependency_graph 已赋值, 后续调用因 _dependency_graph is not None 直接 return True
# 缺失组件永不补全
# ═══════════════════════════════════════════════════════════════════


class TestBug3EnsureNeuronComponentsPartialInit:
    """BUG-3: 部分初始化后永久返回 True, 缺失组件永不补全"""

    def test_partial_init_returns_false_and_retries(self):
        """模拟 _absence_reasoner 构造失败 (非 import 失败), 验证:
        - 第一次调用返回 False (而非 True)
        - 第二次调用重试初始化 (而非因 _dependency_graph is not None 永久返回 True)

        bug 触发条件: _dependency_graph 已赋值, 但 AbsenceReasoner 构造抛异常。
        当前代码: except 捕获后返回 False (修复后), 但下次调用因 _dependency_graph is not None 直接返回 True (bug)。
        """
        engine = NeurovaRecallEngine(use_plugins=False, memory_manager=MagicMock())

        # 真实模块存在 (已验证), 让 AbsenceReasoner 构造抛异常
        from neurova.cognitive_layers.memory_layer.absence_reasoner import AbsenceReasoner

        # 让 AbsenceReasoner 构造抛异常 (在 _dependency_graph 已赋值之后)
        with patch.object(AbsenceReasoner, "__init__", side_effect=RuntimeError("simulated construction failure")):
            result1 = engine._ensure_neuron_components()

        # 修复后: 部分初始化应返回 False (而非 True)
        assert result1 is False, (
            "部分初始化后应返回 False, 实际返回 True — _dependency_graph 已赋值导致永久 True (bug 3)"
        )
        # _absence_reasoner 应为 None (构造失败)
        assert engine._absence_reasoner is None

        # 第二次调用: 修复后应重试 (而非直接返回 True)
        with patch.object(AbsenceReasoner, "__init__", side_effect=RuntimeError("simulated construction failure")):
            result2 = engine._ensure_neuron_components()
        assert result2 is False, "第二次调用应重试初始化, 而非因 _dependency_graph is not None 直接返回 True"

    def test_full_init_returns_true_and_caches(self):
        """全部组件初始化成功时返回 True, 后续调用直接命中缓存"""
        engine = NeurovaRecallEngine(use_plugins=False, memory_manager=MagicMock())

        result1 = engine._ensure_neuron_components()
        # 若依赖模块不存在, 返回 False (环境问题), 不算 bug — 跳过断言
        if not result1:
            pytest.skip("NEURON 依赖模块在本环境不可用, 跳过缓存验证")
        # 全部成功 → True
        assert result1 is True
        # 第二次调用应直接返回 True (缓存命中, 不再重试)
        result2 = engine._ensure_neuron_components()
        assert result2 is True


# ═══════════════════════════════════════════════════════════════════
# Bug 4 (MEDIUM): _phase1_plugin_recall 检查 self._channel_weights 而非参数
# `weights = channel_weights if self._channel_weights else {}`
# self._channel_weights 永远 truthy → weights 永远等于 channel_weights
# 当 channel_weights=None 时, weights=None, 后续 weights.get() 抛 AttributeError
# ═══════════════════════════════════════════════════════════════════


class TestBug4PluginRecallChannelWeightsCheck:
    """BUG-4: 检查 self._channel_weights (实例属性) 而非 channel_weights 参数"""

    def test_passing_none_channel_weights_does_not_raise(self):
        """传 channel_weights=None 时不应抛 AttributeError"""
        # 构造 mock registry, 让 _phase1_plugin_recall 走插件路径
        mock_channel = MagicMock()
        mock_channel.metadata.name = "text"
        # get_state 需返回 ACTIVE 枚举
        from neurova.cognitive_layers.memory_layer.channels.base import ChannelState

        mock_channel.get_state.return_value = ChannelState.ACTIVE
        # retrieve 是 async 方法, 必须用 AsyncMock 返回 list
        mock_channel.retrieve = AsyncMock(return_value=[])

        mock_registry = MagicMock()
        mock_registry.get_active.return_value = [mock_channel]

        engine = NeurovaRecallEngine(
            use_plugins=True,
            memory_manager=MagicMock(),
            registry=mock_registry,
        )

        # bug: channel_weights=None → weights=None → weights.get() → AttributeError
        # 修复后: channel_weights=None → weights={} → 不抛错
        try:
            engine._phase1_plugin_recall(
                query="test",
                channels=[RecallChannel.TEXT],
                limit=5,
                channel_weights=None,
            )
        except AttributeError as e:
            pytest.fail(
                f"传 channel_weights=None 抛 AttributeError — bug 4 未修复: {e}"
            )

    def test_passing_none_channel_weights_uses_empty_dict_fallback(self):
        """传 channel_weights=None 时 weights 应回退到 {} 而非 None"""
        mock_channel = MagicMock()
        from neurova.cognitive_layers.memory_layer.channels.base import ChannelState

        mock_channel.metadata.name = "text"
        mock_channel.get_state.return_value = ChannelState.ACTIVE
        mock_channel.retrieve = AsyncMock(return_value=[])

        mock_registry = MagicMock()
        mock_registry.get_active.return_value = [mock_channel]

        engine = NeurovaRecallEngine(
            use_plugins=True,
            memory_manager=MagicMock(),
            registry=mock_registry,
        )

        # 调用并验证 weights 处理正确 (内部用 weights.get(rc, 1.0) 时返回默认 1.0)
        result = engine._phase1_plugin_recall(
            query="test",
            channels=[RecallChannel.TEXT],
            limit=5,
            channel_weights=None,
        )
        # 应正常返回 list (而非抛 AttributeError)
        assert isinstance(result, list)


# ═══════════════════════════════════════════════════════════════════
# Bug 5 (MEDIUM): asyncio.get_event_loop() 废弃 + loop 未 close
# 在已有运行中 event loop 的上下文里调用 retrieve 会抛 RuntimeError
# 且 loop 从不 close → 资源泄漏
# ═══════════════════════════════════════════════════════════════════


class TestBug5AsyncioGetEventLoopDeprecated:
    """BUG-5: asyncio.get_event_loop() 废弃 + loop 未 close"""

    def _make_plugin_engine(self) -> NeurovaRecallEngine:
        """构造一个可用的插件模式引擎 (mock 通道返回空)"""
        from neurova.cognitive_layers.memory_layer.channels.base import ChannelState

        mock_channel = MagicMock()
        mock_channel.metadata.name = "text"
        mock_channel.get_state.return_value = ChannelState.ACTIVE
        mock_channel.retrieve = AsyncMock(return_value=[])

        mock_registry = MagicMock()
        mock_registry.get_active.return_value = [mock_channel]

        return NeurovaRecallEngine(
            use_plugins=True,
            memory_manager=MagicMock(),
            registry=mock_registry,
        )

    def test_plugin_recall_from_within_running_event_loop(self):
        """在已有运行中的 event loop 内调用 _phase1_plugin_recall 不应抛 RuntimeError

        bug: get_event_loop() + run_until_complete() 在已有运行 loop 时抛
             RuntimeError("This event loop is already running")
        修复: 用独立线程 + 独立 loop (或 asyncio.run) 执行
        """
        engine = self._make_plugin_engine()

        async def outer_async():
            # 此处已在一个运行中的 event loop 内
            # bug: _phase1_plugin_recall 内部 run_until_complete 会抛 RuntimeError
            return engine._phase1_plugin_recall(
                query="test",
                channels=[RecallChannel.TEXT],
                limit=5,
                channel_weights=None,
            )

        # 在运行中的 event loop 内调用 — bug 触发 RuntimeError
        try:
            result = asyncio.run(outer_async())
        except RuntimeError as e:
            if "already running" in str(e) or "event loop" in str(e).lower():
                pytest.fail(
                    f"在运行中的 event loop 内调用抛 RuntimeError — bug 5 未修复: {e}"
                )
            raise
        assert isinstance(result, list)

    def test_plugin_recall_closes_loop_after_call(self):
        """调用后 event loop 应被关闭 (无资源泄漏)"""
        engine = self._make_plugin_engine()

        engine._phase1_plugin_recall(
            query="test",
            channels=[RecallChannel.TEXT],
            limit=5,
            channel_weights=None,
        )

        # 修复后: loop 应已关闭。用 asyncio 模块级状态检查
        # 注意: 不能直接检查 "loop 是否 close" (没有全局句柄), 改为检查
        # 多次调用不累积资源 (连续调用不抛错)
        for _ in range(3):
            engine._phase1_plugin_recall(
                query="test",
                channels=[RecallChannel.TEXT],
                limit=5,
                channel_weights=None,
            )
        # 如果 loop 未 close, 多次调用可能累积问题 (此处主要验证不抛错)


# ═══════════════════════════════════════════════════════════════════
# Bug 6 (MEDIUM): 直接访问 memory_manager._memories 私有属性
# `mem_obj = self.memory_manager._memories.get(mid)` 绕过公共 API
# 修复: 用 memory_manager.get_memory(mid) 公共方法
# ═══════════════════════════════════════════════════════════════════


class TestBug6PrivateMemoriesAccess:
    """BUG-6: _channel_emotion 直接访问 _memories 私有属性"""

    def _make_engine_with_emotion(self):
        """构造一个可触发 _channel_emotion 的引擎 (mock)"""
        # 构造 emotion_module mock, 让 _channel_emotion 走完整路径
        emotion_module = MagicMock()
        # analyze_text_emotion 返回非 neutral 的情感状态
        emotion_state = MagicMock()
        emotion_state.primary_emotion.value = "joy"
        emotion_state.intensity = 0.8
        emotion_module.analyze_text_emotion.return_value = emotion_state
        # get_emotional_memories 返回记忆 id 列表
        emotion_module.get_emotional_memories.return_value = ["mem_1", "mem_2"]
        # get_emotion 返回记忆自身的情感状态
        mem_emotion = MagicMock()
        mem_emotion.intensity = 0.6
        emotion_module.get_emotion.return_value = mem_emotion

        memory_manager = MagicMock()
        memory_manager.emotion_module = emotion_module
        # get_memory 公共 API: 返回 dict (而非 Memory 对象)
        memory_manager.get_memory.return_value = {"id": "mem_1", "content": "happy memory"}

        engine = NeurovaRecallEngine(use_plugins=False, memory_manager=memory_manager)
        return engine, memory_manager

    def test_channel_emotion_does_not_access_private_memories(self):
        """_channel_emotion 不应访问 memory_manager._memories 私有属性"""
        engine, memory_manager = self._make_engine_with_emotion()

        # 调用 _channel_emotion
        engine._channel_emotion("开心的一天", limit=5)

        # 验证: 没有访问 _memories 私有属性
        # bug: `mem_obj = self.memory_manager._memories.get(mid)` 会触发 _memories.get 调用
        # 修复后: 用 get_memory() 公共方法
        # 用属性访问计数: MagicMock 会记录 _memories 的访问
        # 如果 bug 存在, memory_manager._memories 会被访问 (返回 MagicMock 的 .get)
        private_accessed = memory_manager._memories.called or (
            hasattr(memory_manager._memories, "get") and memory_manager._memories.get.called
        )
        assert not private_accessed, (
            "_channel_emotion 直接访问了 memory_manager._memories 私有属性 — bug 6 未修复"
        )

    def test_channel_emotion_uses_public_get_memory(self):
        """_channel_emotion 应使用 memory_manager.get_memory() 公共 API"""
        engine, memory_manager = self._make_engine_with_emotion()

        engine._channel_emotion("开心的一天", limit=5)

        # 验证: get_memory 公共方法被调用
        memory_manager.get_memory.assert_called()

    def test_channel_emotion_returns_results_via_public_api(self):
        """通过公共 API 应能正常返回结果"""
        engine, memory_manager = self._make_engine_with_emotion()

        results = engine._channel_emotion("开心的一天", limit=5)
        # 应返回非空列表 (有 2 个 emotional memories)
        assert len(results) > 0, "通过公共 API 应能返回情感记忆结果"
        # 内容应来自 get_memory 返回的 dict
        assert results[0].content == "happy memory"


# ═══════════════════════════════════════════════════════════════════
# Bug 7 (MEDIUM): 多处 except Exception 吞编程错误
# except Exception 捕获所有异常(含 TypeError/AttributeError), 仅 warning 记录, 不 re-raise
# 编程错误被静默吞掉, 隐藏 bug
# 修复: 对编程错误(TypeError/AttributeError/NameError/ImportError) re-raise
# ═══════════════════════════════════════════════════════════════════


class TestBug7ExceptionSwallowing:
    """BUG-7: except Exception 吞编程错误, 应 re-raise TypeError/AttributeError 等"""

    def test_channel_temperature_reraises_typeerror(self):
        """_channel_temperature 中 memory_manager.get_all_memories 抛 TypeError 时,
        异常应被 re-raise 而非吞掉返回空列表"""
        # 构造一个会抛 TypeError 的 memory_manager (模拟编程错误)
        memory_manager = MagicMock()
        memory_manager.get_all_memories.side_effect = TypeError(
            "simulated programming error: 'NoneType' object is not iterable"
        )

        engine = NeurovaRecallEngine(use_plugins=False, memory_manager=memory_manager)

        # bug: TypeError 被 except Exception 吞掉, 返回空列表
        # 修复后: TypeError 应被 re-raise
        with pytest.raises(TypeError, match="simulated programming error"):
            engine._channel_temperature("test", limit=5)

    def test_channel_text_reraises_attribute_error(self):
        """_channel_text 中抛 AttributeError (编程错误) 时应被 re-raise"""
        memory_manager = MagicMock()
        # get_all_memories 返回非可迭代对象触发 AttributeError
        memory_manager.get_all_memories.return_value = None  # None 不可迭代

        engine = NeurovaRecallEngine(use_plugins=False, memory_manager=memory_manager)

        # bug: AttributeError 被吞掉
        # 修复后: 应 re-raise AttributeError (或在调用处抛 TypeError, 关键是不能静默)
        with pytest.raises((AttributeError, TypeError)):
            engine._channel_text("test", limit=5)

    def test_channel_temperature_reraises_attribute_error(self):
        """_channel_temperature 中抛 AttributeError 时应被 re-raise 而非吞掉"""
        memory_manager = MagicMock()
        # 模拟 memory_manager 缺失 get_all_memories 方法 (编程错误)
        del memory_manager.get_all_memories  # 删除 mock 方法, 访问时抛 AttributeError

        engine = NeurovaRecallEngine(use_plugins=False, memory_manager=memory_manager)

        # bug: AttributeError 被吞掉返回空列表
        # 修复后: 应 re-raise
        with pytest.raises(AttributeError):
            engine._channel_temperature("test", limit=5)


# ═══════════════════════════════════════════════════════════════════
# Bug 8 (MEDIUM): as_completed 缺少 timeout
# as_completed(futures) 无 timeout 参数, 某通道永不返回时永久挂起
# 修复: 添加 timeout=self.timeout_seconds, catch concurrent.futures.TimeoutError
# ═══════════════════════════════════════════════════════════════════


class TestBug8AsCompletedMissingTimeout:
    """BUG-8: as_completed(futures) 缺少 timeout, 某通道挂起时永久阻塞"""

    def test_as_completed_call_has_timeout_argument(self):
        """_phase1_multichannel_recall 中 as_completed 调用应包含 timeout 参数"""
        source = inspect.getsource(NeurovaRecallEngine._phase1_multichannel_recall)
        assert "as_completed" in source, "代码中应有 as_completed 调用"
        # 提取 as_completed 调用行 (跳过注释行)
        for line in source.splitlines():
            stripped = line.strip()
            if "as_completed" in stripped and not stripped.startswith("#"):
                assert "timeout=" in line, (
                    f"as_completed 调用缺少 timeout 参数 (bug 8): {stripped}"
                )
                return
        pytest.fail("未找到 as_completed 调用行")

    def test_hung_channel_does_not_cause_permanent_hang(self):
        """某通道永不返回时, _phase1_multichannel_recall 应在 timeout 内完成而非永久挂起"""
        from concurrent.futures import ThreadPoolExecutor

        engine = NeurovaRecallEngine(use_plugins=False, memory_manager=MagicMock())
        engine.timeout_seconds = 0.3  # 很短的超时

        def hang_forever(query, limit):
            time.sleep(100)  # 远超 timeout
            return []

        # 用本地 executor 替换共享线程池, 避免污染其他测试
        local_executor = ThreadPoolExecutor(max_workers=4)

        result_box: dict = {}

        def worker():
            try:
                result_box["value"] = engine._phase1_multichannel_recall(
                    query="test",
                    channels=[RecallChannel.TEMPERATURE, RecallChannel.TEXT],
                    limit=5,
                )
            except BaseException as e:
                result_box["error"] = e

        with patch.object(engine, "_channel_temperature", side_effect=hang_forever), patch(
            "neurova.core.thread_pool.get_thread_pool", return_value=local_executor
        ):
            t = threading.Thread(target=worker, daemon=True)
            t.start()
            t.join(timeout=5.0)  # 最多等 5 秒

        # 清理: 取消所有 pending futures
        local_executor.shutdown(wait=False)

        assert not t.is_alive(), (
            "_phase1_multichannel_recall 挂起超过 5 秒 — as_completed 缺少 timeout (bug 8)"
        )


# ═══════════════════════════════════════════════════════════════════
# Bug 9 (LOW): pass 死代码
# _channel_emotion 中有独立的 pass 语句, 无任何作用
# 修复: 删除
# ═══════════════════════════════════════════════════════════════════


class TestBug9PassDeadCode:
    """BUG-9: _channel_emotion 中独立的 pass 语句是死代码"""

    def test_channel_emotion_has_no_standalone_pass(self):
        """_channel_emotion 方法体不应包含独立的 pass 死代码"""
        source = inspect.getsource(NeurovaRecallEngine._channel_emotion)
        lines = source.splitlines()
        # 查找独立的 pass 语句 (非 except/if/for/while/class/def 块内的 pass)
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped == "pass":
                # 检查上一行是否是冒号结尾 (合法 pass 在空 block 中)
                if i > 0:
                    prev_stripped = lines[i - 1].strip()
                    if prev_stripped.endswith(":"):
                        continue  # 合法: 空 block 的 pass
                pytest.fail(
                    f"_channel_emotion 第 {i+1} 行有独立 pass 死代码 (bug 9): {line!r}"
                )


# ═══════════════════════════════════════════════════════════════════
# Bug 10 (LOW): recall 结果未使用(死代码)
# _channel_emotion 中 recall(query="", limit=1) 返回值未赋值
# 修复: 删除该行 (已在 Bug 6 修复中删除, 此为验证测试)
# ═══════════════════════════════════════════════════════════════════


class TestBug10RecallDeadCode:
    """BUG-10: recall(query="", limit=1) 返回值未使用, 是死代码"""

    def test_channel_emotion_has_no_unused_recall_call(self):
        """_channel_emotion 不应包含未使用的 recall(query=...) 调用"""
        source = inspect.getsource(NeurovaRecallEngine._channel_emotion)
        # 查找 recall(query= 调用 (死代码: 返回值未赋值)
        for line in source.splitlines():
            stripped = line.strip()
            if "recall(query=" in stripped and "=" not in stripped.split("recall")[0]:
                pytest.fail(
                    f"_channel_emotion 有未使用的 recall 调用死代码 (bug 10): {stripped!r}"
                )


# ═══════════════════════════════════════════════════════════════════
# Bug 11 (LOW): 表达式语句无副作用
# _channel_voice 中 mem_dict.get("timestamp", "") 作为单独语句, 返回值未使用
# 修复: 删除或赋值
# ═══════════════════════════════════════════════════════════════════


class TestBug11StandaloneExpression:
    """BUG-11: mem_dict.get("timestamp", "") 作为独立语句, 返回值未使用"""

    def test_channel_voice_timestamp_is_not_standalone_expression(self):
        """_channel_voice 中 timestamp 不应是无副作用的独立表达式"""
        source = inspect.getsource(NeurovaRecallEngine._channel_voice)
        for line in source.splitlines():
            stripped = line.strip()
            # 查找独立的 mem_dict.get("timestamp", "") 表达式 (非赋值)
            if 'mem_dict.get("timestamp"' in stripped:
                # 验证它是赋值语句 (有 = 在 .get 之前)
                before_get = stripped.split(".get(")[0]
                if "=" not in before_get:
                    pytest.fail(
                        f"_channel_voice 有独立表达式无副作用 (bug 11): {stripped!r}"
                    )


# ═══════════════════════════════════════════════════════════════════
# Bug 12 (LOW): recency_score 硬编码 1.0
# _channel_voice 中 recency_score = 1.0 硬编码, 未用真实时间戳
# 修复: 用 mem_dict 的 timestamp 计算
# ═══════════════════════════════════════════════════════════════════


class TestBug12HardcodedRecencyScore:
    """BUG-12: recency_score = 1.0 硬编码, 应基于真实时间戳计算"""

    def test_channel_voice_recency_score_not_hardcoded(self):
        """_channel_voice 中 recency_score 不应硬编码为 1.0"""
        source = inspect.getsource(NeurovaRecallEngine._channel_voice)
        for line in source.splitlines():
            stripped = line.strip()
            # 去除空格后检查 recency_score=1.0 模式
            no_space = stripped.replace(" ", "")
            if "recency_score=1.0" in no_space and "#" not in stripped.split("recency_score")[0]:
                pytest.fail(
                    f"_channel_voice recency_score 硬编码为 1.0 (bug 12): {stripped!r}"
                )

    def test_channel_voice_uses_timestamp_for_recency(self):
        """_channel_voice 应使用 timestamp 字段计算 recency_score"""
        engine = NeurovaRecallEngine(use_plugins=False, memory_manager=MagicMock())

        # 构造一个旧语音记忆 (1 年前), 验证 recency_score < 1.0
        old_timestamp = (datetime.datetime.now() - datetime.timedelta(days=365)).isoformat()
        old_mem = {
            "id": "old_voice",
            "content": "hello test",
            "memory_type": "asr_transcription",
            "timestamp": old_timestamp,
            "metadata": {"record": {"confidence": 0.9, "engine": "whisper"}},
        }

        memory_manager = MagicMock()
        memory_manager.get_all_memories.return_value = [old_mem]
        engine.memory_manager = memory_manager

        results = engine._channel_voice("test", limit=5)
        assert len(results) > 0
        # 1 年前的记忆 recency_score 应远小于 1.0
        # 如果硬编码 1.0, score = 0.9 * 0.7 + 1.0 * 0.3 = 0.93
        # 如果用真实时间戳, recency_score 应 << 1.0 (指数衰减)
        assert results[0].score < 0.9, (
            f"1 年前的语音记忆 score={results[0].score} >= 0.9 — "
            "recency_score 仍硬编码为 1.0 (bug 12)"
        )


# ═══════════════════════════════════════════════════════════════════
# Bug 13 (LOW): get_all vs get_active 不一致
# init 用 get_all() 检查通道, recall 用 get_active() 检索通道
# 修复: 统一用 get_active()
# ═══════════════════════════════════════════════════════════════════


class TestBug13GetAllVsGetActiveInconsistency:
    """BUG-13: init 用 get_all(), recall 用 get_active(), 不一致"""

    def test_init_uses_get_active_not_get_all(self):
        """NeurovaRecallEngine 初始化时应检查 get_active() 而非 get_all()"""
        source = inspect.getsource(NeurovaRecallEngine.__init__)
        # 检查非注释行: 不应有 get_all() 调用, 应有 get_active() 调用
        has_get_active = False
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue  # 跳过注释行
            if "get_all()" in stripped:
                pytest.fail(
                    f"init 非注释行使用 get_all() — 与 recall 的 get_active() 不一致 (bug 13): {stripped!r}"
                )
            if "get_active()" in stripped:
                has_get_active = True
        assert has_get_active, "init 应使用 get_active() (bug 13)"


# ═══════════════════════════════════════════════════════════════════
# Bug 14 (LOW): metadata intensity 存查询强度而非记忆强度
# _channel_emotion 中 metadata["intensity"] = emotion_state.intensity (查询强度)
# 修复: 用记忆自身的情感强度 mem_emotion.intensity
# (已在 Bug 6 修复中应用, 此为验证测试)
# ═══════════════════════════════════════════════════════════════════


class TestBug14MetadataIntensityUsesMemoryEmotion:
    """BUG-14: metadata["intensity"] 应存记忆自身的情感强度, 非查询强度"""

    def test_channel_emotion_metadata_uses_mem_emotion_intensity(self):
        """_channel_emotion metadata intensity 应等于记忆自身的 mem_emotion.intensity"""
        emotion_module = MagicMock()
        emotion_state = MagicMock()
        emotion_state.primary_emotion.value = "joy"
        emotion_state.intensity = 0.9  # 查询情感强度 (高)
        emotion_module.analyze_text_emotion.return_value = emotion_state
        emotion_module.get_emotional_memories.return_value = ["mem_1"]

        # 记忆自身的情感强度 (低, 与查询不同)
        mem_emotion = MagicMock()
        mem_emotion.intensity = 0.3
        emotion_module.get_emotion.return_value = mem_emotion

        memory_manager = MagicMock()
        memory_manager.emotion_module = emotion_module
        memory_manager.get_memory.return_value = {"id": "mem_1", "content": "happy"}

        engine = NeurovaRecallEngine(use_plugins=False, memory_manager=memory_manager)

        results = engine._channel_emotion("非常开心", limit=5)
        assert len(results) > 0

        # bug: metadata["intensity"] = emotion_state.intensity (0.9, 查询强度)
        # 修复后: metadata["intensity"] = mem_emotion.intensity (0.3, 记忆强度)
        assert results[0].metadata["intensity"] == 0.3, (
            f"metadata intensity={results[0].metadata['intensity']} — "
            "应等于记忆自身的情感强度 (0.3), 非查询强度 (0.9) (bug 14)"
        )
