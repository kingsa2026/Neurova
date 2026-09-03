"""
CrystallizedExperienceManager 单元测试

测试结晶经验检索管理器的所有功能：
1. 基本检索功能
2. 重试机制
3. 降级策略
4. 缓存机制
5. 健康监控
6. 失败回调
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from typing import List, Dict, Any

from neurova.agent.crystallized_experience_manager import (
    CrystallizedExperienceManager,
    CrystallizedExperience,
    RetrievalResult,
    RetrievalStatus,
    HealthStatus,
    RetrievalMetrics,
)


class MockCrystallizer:
    """模拟结晶器"""

    def __init__(self):
        self.retrieve_count = 0
        self.fail_count = 0
        self.results: List[Dict[str, Any]] = []
        self.observe_count = 0

    def retrieve(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """检索结晶经验"""
        self.retrieve_count += 1

        if self.fail_count > 0:
            self.fail_count -= 1
            raise Exception("模拟结晶器检索失败")

        return self.results[:limit]

    def observe(
        self, tool_name: str, context: str, success: bool, result: Any = None
    ) -> None:
        """观察工具使用"""
        self.observe_count += 1


class MockMemoryManager:
    """模拟记忆管理器"""

    def __init__(self):
        self.recall_count = 0
        self.memories: List[Dict[str, Any]] = []
        self.fail = False

    def recall(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """检索记忆"""
        self.recall_count += 1

        if self.fail:
            raise Exception("模拟记忆检索失败")

        return self.memories[:limit]


class TestCrystallizedExperienceManager:
    """CrystallizedExperienceManager 测试类"""

    def setup_method(self):
        """测试前准备"""
        self.crystallizer = MockCrystallizer()
        self.memory_manager = MockMemoryManager()
        self.manager = CrystallizedExperienceManager(
            crystallizer=self.crystallizer,
            memory_manager=self.memory_manager,
            max_retries=2,
            retry_delay_ms=10,  # 快速测试
        )

    def test_initialization(self):
        """测试初始化"""
        manager = CrystallizedExperienceManager()
        assert manager._crystallizer is None
        assert manager._memory_manager is None
        assert manager._max_retries == 2
        assert manager.get_health() == HealthStatus.HEALTHY

    def test_initialization_with_dependencies(self):
        """测试带依赖初始化"""
        manager = CrystallizedExperienceManager(
            crystallizer=self.crystallizer,
            memory_manager=self.memory_manager,
        )
        assert manager._crystallizer is self.crystallizer
        assert manager._memory_manager is self.memory_manager

    def test_retrieve_success(self):
        """测试成功检索"""
        # 设置模拟数据
        self.crystallizer.results = [
            {"id": "1", "content": "测试结晶经验", "method": "tool_a", "confidence": 0.9, "score": 80.0}
        ]

        # 执行检索
        result = asyncio.run(
            self.manager.retrieve("测试查询", limit=5, use_cache=False)
        )

        # 验证结果
        assert result.status == RetrievalStatus.SUCCESS
        assert len(result.experiences) == 1
        assert result.experiences[0].content == "测试结晶经验"
        assert result.source == "pattern_crystallizer"
        assert self.crystallizer.retrieve_count == 1

    def test_retrieve_with_retries(self):
        """测试重试机制"""
        # 设置失败次数
        self.crystallizer.fail_count = 1
        self.crystallizer.results = [
            {"id": "1", "content": "重试成功", "method": "tool_a", "confidence": 0.9, "score": 80.0}
        ]

        # 执行检索
        result = asyncio.run(
            self.manager.retrieve("重试查询", limit=5, use_cache=False)
        )

        # 验证重试
        assert result.status == RetrievalStatus.SUCCESS
        assert self.crystallizer.retrieve_count == 2  # 1次失败 + 1次成功

    def test_retrieve_all_retries_fail(self):
        """测试所有重试失败"""
        # 设置连续失败
        self.crystallizer.fail_count = 3  # 超过 max_retries

        # 执行检索
        result = asyncio.run(
            self.manager.retrieve("失败查询", limit=5, use_cache=False)
        )

        # 验证降级
        assert result.status == RetrievalStatus.DEGRADED
        assert result.source == "memory_fallback"
        assert self.memory_manager.recall_count == 1

    def test_retrieve_without_crystallizer(self):
        """测试结晶器未初始化"""
        manager = CrystallizedExperienceManager(
            crystallizer=None,
            memory_manager=self.memory_manager,
        )

        # 执行检索
        result = asyncio.run(
            manager.retrieve("查询", limit=5, use_cache=False)
        )

        # 验证降级
        assert result.status == RetrievalStatus.DEGRADED
        assert result.source == "memory_fallback"

    def test_retrieve_without_memory_manager(self):
        """测试记忆管理器未初始化"""
        manager = CrystallizedExperienceManager(
            crystallizer=self.crystallizer,
            memory_manager=None,
        )
        self.crystallizer.fail_count = 3  # 连续失败

        # 执行检索
        result = asyncio.run(
            manager.retrieve("查询", limit=5, use_cache=False)
        )

        # 验证完全失败
        assert result.status == RetrievalStatus.FAILED
        assert result.error is not None

    def test_cache_hit(self):
        """测试缓存命中"""
        self.crystallizer.results = [
            {"id": "1", "content": "缓存测试", "method": "tool_a", "confidence": 0.9, "score": 80.0}
        ]

        # 第一次检索（写入缓存）
        result1 = asyncio.run(
            self.manager.retrieve("缓存查询", limit=5, use_cache=True)
        )

        # 第二次检索（命中缓存）
        result2 = asyncio.run(
            self.manager.retrieve("缓存查询", limit=5, use_cache=True)
        )

        # 验证缓存
        assert result1.status == RetrievalStatus.SUCCESS
        assert result2.status == RetrievalStatus.SUCCESS
        assert self.crystallizer.retrieve_count == 1  # 只调用一次

    def test_cache_expiry(self):
        """测试缓存过期"""
        self.crystallizer.results = [
            {"id": "1", "content": "过期测试", "method": "tool_a", "confidence": 0.9, "score": 80.0}
        ]

        # 第一次检索
        asyncio.run(
            self.manager.retrieve("过期查询", limit=5, use_cache=True)
        )

        # 模拟缓存过期
        query_hash = self.manager._hash_query("过期查询")
        self.manager._cache[query_hash] = (
            self.manager._cache[query_hash][0],
            0,  # 时间戳设为0，立即过期
        )

        # 第二次检索（缓存过期，重新检索）
        asyncio.run(
            self.manager.retrieve("过期查询", limit=5, use_cache=True)
        )

        # 验证重新检索
        assert self.crystallizer.retrieve_count == 2

    def test_fallback_to_memory(self):
        """测试降级到记忆检索"""
        # 设置记忆数据
        self.memory_manager.memories = [
            {"id": "m1", "content": "降级记忆", "importance": 0.7, "temperature": 60.0, "source": "memory"}
        ]
        self.crystallizer.fail_count = 3  # 连续失败

        # 执行检索
        result = asyncio.run(
            self.manager.retrieve("降级查询", limit=5, fallback_to_memory=True)
        )

        # 验证降级
        assert result.status == RetrievalStatus.DEGRADED
        assert len(result.experiences) == 1
        assert result.experiences[0].source == "memory_fallback"
        assert result.experiences[0].method == "memory_fallback"

    def test_fallback_disabled(self):
        """测试禁用降级"""
        self.crystallizer.fail_count = 3  # 连续失败

        # 执行检索（禁用降级）
        result = asyncio.run(
            self.manager.retrieve("查询", limit=5, fallback_to_memory=False)
        )

        # 验证完全失败
        assert result.status == RetrievalStatus.FAILED

    def test_observe_forwarding(self):
        """测试观察转发"""
        self.manager.observe("tool_a", "测试上下文", True, None)
        assert self.crystallizer.observe_count == 1

    def test_observe_without_crystallizer(self):
        """测试无结晶器时观察"""
        manager = CrystallizedExperienceManager(crystallizer=None)
        # 不应抛出异常
        manager.observe("tool_a", "测试上下文", True, None)

    def test_health_status_degraded(self):
        """测试健康状态降级"""
        # 模拟连续失败
        self.crystallizer.fail_count = 2
        asyncio.run(
            self.manager.retrieve("查询", limit=5, use_cache=False)
        )

        # 验证健康状态
        assert self.manager.get_health() == HealthStatus.DEGRADED

    def test_health_status_unhealthy(self):
        """测试健康状态不健康"""
        # 模拟连续失败：单次 retrieve 受 max_retries 限制最多触发 3 次尝试，
        # 故需连续两次检索（跨调用累积连续失败）才能达到 >=5 次的不健康阈值
        self.crystallizer.fail_count = 5
        # 第一次检索：3 次尝试全部失败，累计 3 次连续失败
        asyncio.run(
            self.manager.retrieve("查询", limit=5, use_cache=False)
        )
        # 第二次检索：fail_count 剩余 2，再累计 2 次失败，达到 5 次 → UNHEALTHY
        asyncio.run(
            self.manager.retrieve("查询", limit=5, use_cache=False)
        )

        # 验证健康状态
        assert self.manager.get_health() == HealthStatus.UNHEALTHY

    def test_health_status_recovery(self):
        """测试健康状态恢复"""
        # 先失败
        self.crystallizer.fail_count = 2
        asyncio.run(
            self.manager.retrieve("查询", limit=5, use_cache=False)
        )
        assert self.manager.get_health() == HealthStatus.DEGRADED

        # 再成功
        self.crystallizer.results = [
            {"id": "1", "content": "恢复", "method": "tool_a", "confidence": 0.9, "score": 80.0}
        ]
        asyncio.run(
            self.manager.retrieve("查询", limit=5, use_cache=False)
        )

        # 验证恢复
        assert self.manager.get_health() == HealthStatus.HEALTHY

    def test_failure_callback(self):
        """测试失败回调"""
        callback = Mock()
        self.manager.add_failure_callback(callback)

        # 模拟失败
        self.crystallizer.fail_count = 3
        asyncio.run(
            self.manager.retrieve("回调查询", limit=5, use_cache=False)
        )

        # 验证回调被调用
        callback.assert_called_once()
        args = callback.call_args[0]
        assert args[0] == "回调查询"
        assert isinstance(args[1], Exception)

    def test_clear_cache(self):
        """测试清空缓存"""
        self.crystallizer.results = [
            {"id": "1", "content": "缓存", "method": "tool_a", "confidence": 0.9, "score": 80.0}
        ]

        # 写入缓存
        asyncio.run(
            self.manager.retrieve("查询1", limit=5, use_cache=True)
        )
        asyncio.run(
            self.manager.retrieve("查询2", limit=5, use_cache=True)
        )

        # 清空指定缓存
        count = self.manager.clear_cache("查询1")
        assert count == 1

        # 清空所有缓存
        count = self.manager.clear_cache()
        assert count == 1

    def test_statistics(self):
        """测试统计信息"""
        # 执行一些操作
        self.crystallizer.results = [
            {"id": "1", "content": "统计", "method": "tool_a", "confidence": 0.9, "score": 80.0}
        ]
        asyncio.run(
            self.manager.retrieve("统计查询", limit=5, use_cache=False)
        )

        # 获取统计
        stats = self.manager.get_statistics()
        assert stats["total_attempts"] == 1
        assert stats["successful_attempts"] == 1
        assert stats["health_status"] == "healthy"

    def test_crystallized_experience_dataclass(self):
        """测试 CrystallizedExperience 数据类"""
        exp = CrystallizedExperience(
            id="1",
            content="测试内容",
            method="tool_a",
            confidence=0.9,
            score=80.0,
            source="crystallized",
        )
        assert exp.id == "1"
        assert exp.content == "测试内容"
        assert exp.confidence == 0.9

    def test_retrieval_result_dataclass(self):
        """测试 RetrievalResult 数据类"""
        result = RetrievalResult(
            status=RetrievalStatus.SUCCESS,
            experiences=[],
            source="test",
            latency_ms=100.0,
        )
        assert result.status == RetrievalStatus.SUCCESS
        assert result.latency_ms == 100.0


class TestCrystallizedExperienceManagerEdgeCases:
    """边界情况测试"""

    def test_empty_results(self):
        """测试空结果"""
        crystallizer = MockCrystallizer()
        crystallizer.results = []
        manager = CrystallizedExperienceManager(crystallizer=crystallizer)

        result = asyncio.run(
            manager.retrieve("查询", limit=5, use_cache=False)
        )

        assert result.status == RetrievalStatus.SUCCESS
        assert len(result.experiences) == 0

    def test_large_limit(self):
        """测试大数量限制"""
        crystallizer = MockCrystallizer()
        crystallizer.results = [
            {"id": str(i), "content": f"经验{i}", "method": "tool_a", "confidence": 0.9, "score": 80.0}
            for i in range(100)
        ]
        manager = CrystallizedExperienceManager(crystallizer=crystallizer)

        result = asyncio.run(
            manager.retrieve("查询", limit=50, use_cache=False)
        )

        assert len(result.experiences) == 50

    def test_concurrent_retrievals(self):
        """测试并发检索"""
        crystallizer = MockCrystallizer()
        crystallizer.results = [
            {"id": "1", "content": "并发测试", "method": "tool_a", "confidence": 0.9, "score": 80.0}
        ]
        manager = CrystallizedExperienceManager(crystallizer=crystallizer)

        async def concurrent_retrieve():
            tasks = [manager.retrieve(f"查询{i}", limit=5, use_cache=False) for i in range(5)]
            return await asyncio.gather(*tasks)

        results = asyncio.run(concurrent_retrieve())

        assert all(r.status == RetrievalStatus.SUCCESS for r in results)
        assert crystallizer.retrieve_count == 5


class TestCrystallizedExperienceManagerFactory:
    """工厂函数测试"""

    def test_get_singleton(self):
        """测试获取单例"""
        from neurova.agent.crystallized_experience_manager import (
            get_crystallized_experience_manager,
            reset_crystallized_experience_manager,
        )

        reset_crystallized_experience_manager()
        manager1 = get_crystallized_experience_manager()
        manager2 = get_crystallized_experience_manager()

        assert manager1 is manager2

    def test_reset_singleton(self):
        """测试重置单例"""
        from neurova.agent.crystallized_experience_manager import (
            get_crystallized_experience_manager,
            reset_crystallized_experience_manager,
        )

        manager1 = get_crystallized_experience_manager()
        reset_crystallized_experience_manager()
        manager2 = get_crystallized_experience_manager()

        assert manager1 is not manager2