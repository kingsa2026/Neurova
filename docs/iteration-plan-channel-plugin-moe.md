# 记忆检索通道插件化 + MoE 路由迭代计划

## 1. 背景与目标

### 1.1 当前问题

`neurova_recall.py` 中 6 个检索通道（温度、文本、分类、图、情感、语音）存在以下问题：

- **硬编码耦合**：所有通道实现在同一个 700+ 行文件中
- **无法独立测试**：通道逻辑与检索引擎混合
- **静态执行**：每次查询都执行所有 6 个通道，资源浪费
- **扩展困难**：添加新通道需要修改核心代码

### 1.2 目标架构

```
┌─────────────────────────────────────────────────────────────┐
│                     插件化基础设施                            │
│  BaseChannel (抽象接口)                                      │
│  ├── ChannelRegistry (注册表)                                │
│  ├── ChannelConfig (配置管理)                                │
│  └── ChannelLifecycle (生命周期)                             │
└─────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                     MoE 路由层                               │
│  ChannelMoERouter                                           │
│  ├── VectorGatingNetwork (复用现有门控网络)                   │
│  ├── 质心初始化（从通道描述自动生成）                          │
│  └── 动态选择（查询相关性 + 激活阈值）                        │
└─────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                     统一结果处理                              │
│  UnifiedResultProcessor                                     │
│  ├── 去重（memory_id）                                       │
│  ├── 权重融合（通道权重 × 基础分数 × 激活分数）               │
│  ├── 时序衰减（时间戳）                                       │
│  └── 冲突检测（语义矛盾）                                     │
└─────────────────────────────────────────────────────────────┘
```

### 1.3 预期收益

| 指标 | 当前 | 目标 | 改进幅度 |
|------|------|------|----------|
| 通道执行数 | 6（全部） | 2-3（Top-K） | -50% 计算资源 |
| 新增通道工作量 | 修改核心文件 | 实现接口+注册 | 解耦 |
| 通道独立测试 | 不可能 | 完全支持 | 可测试性 |
| 运行时配置 | 不可能 | 动态启用/禁用 | 灵活性 |

---

## 2. 迭代阶段

### Phase 1: 插件化基础设施（低风险，立即收益）

**目标**：将 6 个通道重构为独立插件，保持现有行为不变

**任务清单**：

| ID | 任务 | 文件 | 预计工时 | 验收标准 |
|----|------|------|----------|----------|
| 1.1 | 定义 BaseChannel 抽象接口 | `neurova/cognitive_layers/memory_layer/channels/base.py` | 2h | 接口完整，包含生命周期方法 |
| 1.2 | 实现 ChannelRegistry 注册表 | `neurova/cognitive_layers/memory_layer/channels/registry.py` | 2h | 支持注册/注销/查询/枚举 |
| 1.3 | 实现 ChannelConfig 配置管理 | `neurova/cognitive_layers/memory_layer/channels/config.py` | 1.5h | 支持 YAML/JSON 配置，运行时更新 |
| 1.4 | 迁移 TemperatureChannel | `neurova/cognitive_layers/memory_layer/channels/builtin/temperature.py` | 1.5h | 行为与原 `_channel_temperature` 完全一致 |
| 1.5 | 迁移 TextChannel | `neurova/cognitive_layers/memory_layer/channels/builtin/text.py` | 1.5h | 行为与原 `_channel_text` 完全一致 |
| 1.6 | 迁移 CategoryChannel | `neurova/cognitive_layers/memory_layer/channels/builtin/category.py` | 1.5h | 行为与原 `_channel_category` 完全一致 |
| 1.7 | 迁移 GraphChannel | `neurova/cognitive_layers/memory_layer/channels/builtin/graph.py` | 2h | 行为与原 `_channel_graph` 完全一致 |
| 1.8 | 迁移 EmotionChannel | `neurova/cognitive_layers/memory_layer/channels/builtin/emotion.py` | 2h | 行为与原 `_channel_emotion` 完全一致 |
| 1.9 | 迁移 VoiceChannel | `neurova/cognitive_layers/memory_layer/channels/builtin/voice.py` | 2h | 行为与原 `_channel_voice` 完全一致 |
| 1.10 | 修改 NeurovaRecallEngine 使用 Registry | `neurova/cognitive_layers/memory_layer/neurova_recall.py` | 3h | 通过 Registry 调用通道，行为不变 |
| 1.11 | 编写单元测试 | `tests/unit/test_channel_plugins.py` | 3h | 每个通道独立测试，覆盖率 > 90% |
| 1.12 | 集成测试 | `tests/integration/test_recall_with_plugins.py` | 2h | 端到端行为与重构前一致 |

**总工时**：~25 小时

**风险**：
- 低风险：行为完全保持，只是代码结构调整
- 缓解：TDD 方法，先写测试再重构

---

### Phase 2: MoE 通道路由（中等风险，性能收益）

**目标**：叠加 MoE 路由层，动态选择激活哪些通道

**任务清单**：

| ID | 任务 | 文件 | 预计工时 | 验收标准 |
|----|------|------|----------|----------|
| 2.1 | 实现 ChannelMoERouter | `neurova/cognitive_layers/memory_layer/channels/moe_router.py` | 4h | 复用 VectorGatingNetwork，支持通道选择 |
| 2.2 | 通道质心初始化 | `neurova/cognitive_layers/memory_layer/channels/centroid.py` | 2.5h | 从通道描述自动生成质心向量 |
| 2.3 | 通道激活阈值配置 | `neurova/cognitive_layers/memory_layer/channels/threshold.py` | 1.5h | 支持 per-channel 阈值配置 |
| 2.4 | 通道执行超时控制 | `neurova/cognitive_layers/memory_layer/channels/timeout.py` | 2h | asyncio.wait_for + 降级策略 |
| 2.5 | 修改 NeurovaRecallEngine 集成 MoE | `neurova/cognitive_layers/memory_layer/neurova_recall.py` | 3h | Phase 1 使用 MoE 路由 |
| 2.6 | 性能基准测试 | `tests/performance/test_channel_moe_performance.py` | 2h | 对比全通道 vs Top-K 通道耗时 |
| 2.7 | 准确性回归测试 | `tests/unit/test_moe_channel_accuracy.py` | 2.5h | MoE 选择通道的准确性 > 85% |

**总工时**：~17.5 小时

**风险**：
- 中等风险：MoE 路由可能选择错误的通道
- 缓解：
  - 设置 `top_k=4`（默认激活 4 个通道，只跳过最不相关的 2 个）
  - 提供 fallback 模式（MoE 失败时回退到全通道）
  - 质心漂移自适应（使用越多，选择越准）

---

### Phase 3: 统一结果处理（中等风险，质量收益）

**目标**：实现统一的结果处理管道，包含去重、权重、时序、冲突检测

**任务清单**：

| ID | 任务 | 文件 | 预计工时 | 验收标准 |
|----|------|------|----------|----------|
| 3.1 | 实现 UnifiedResultProcessor | `neurova/cognitive_layers/memory_layer/channels/processor.py` | 4h | 去重+权重+时序+冲突检测 |
| 3.2 | 冲突检测算法 | `neurova/cognitive_layers/memory_layer/channels/conflict.py` | 4h | 语义矛盾检测（NLI 或关键词） |
| 3.3 | 时序衰减函数优化 | `neurova/cognitive_layers/memory_layer/channels/temporal.py` | 2h | 支持多种衰减曲线（指数、线性、对数） |
| 3.4 | 通道权重动态调整 | `neurova/cognitive_layers/memory_layer/channels/weight.py` | 2.5h | 基于用户反馈调整权重 |
| 3.5 | 集成到 NeurovaRecallEngine | `neurova/cognitive_layers/memory_layer/neurova_recall.py` | 2h | 替换现有融合逻辑 |
| 3.6 | 冲突检测准确性测试 | `tests/unit/test_conflict_detection.py` | 3h | 冲突检测准确率 > 80% |
| 3.7 | 端到端集成测试 | `tests/integration/test_unified_processor.py` | 2.5h | 完整流程测试 |

**总工时**：~20 小时

**风险**：
- 中等风险：冲突检测可能误判
- 缓解：
  - 提供多种冲突检测策略（关键词、NLI、规则）
  - 冲突标记而非删除（用户可查看冲突组）
  - 渐进式启用（先只做去重+权重，冲突检测可选）

---

## 3. 详细设计

### 3.1 BaseChannel 抽象接口

```python
# neurova/cognitive_layers/memory_layer/channels/base.py

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


class ChannelState(Enum):
    """通道状态"""
    INACTIVE = "inactive"    # 未激活
    ACTIVE = "active"        # 已激活
    ERROR = "error"          # 错误状态
    DISABLED = "disabled"    # 已禁用


@dataclass
class ChannelMetadata:
    """通道元数据"""
    name: str                          # 通道名称
    display_name: str                  # 显示名称
    description: str                   # 通道描述（用于质心生成）
    version: str = "1.0.0"             # 版本号
    author: str = "system"             # 作者
    semantic_centroid: Optional[List[float]] = None  # 语义质心（运行时填充）
    capabilities: List[str] = field(default_factory=list)  # 能力标签


@dataclass
class ChannelResult:
    """通道检索结果"""
    memory_id: str
    content: str
    score: float
    channel: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: Optional[str] = None


class BaseChannel(ABC):
    """通道抽象基类

    所有检索通道必须实现此接口。
    通道是自包含的检索单元，负责：
    1. 执行特定维度的记忆检索
    2. 返回标准化的 ChannelResult 列表
    3. 管理自身生命周期
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self._config = config or {}
        self._state = ChannelState.INACTIVE
        self._logger = logging.getLogger(f"channel.{self.metadata.name}")

    @property
    @abstractmethod
    def metadata(self) -> ChannelMetadata:
        """返回通道元数据"""
        pass

    @abstractmethod
    async def retrieve(
        self,
        query: str,
        limit: int = 10,
        weight: float = 1.0,
        **kwargs
    ) -> List[ChannelResult]:
        """执行检索

        Args:
            query: 查询文本
            limit: 返回数量限制
            weight: 通道权重（由 MoE 路由分配）
            **kwargs: 额外参数

        Returns:
            ChannelResult 列表
        """
        pass

    async def initialize(self) -> bool:
        """初始化通道

        Returns:
            初始化是否成功
        """
        self._state = ChannelState.ACTIVE
        return True

    async def shutdown(self) -> None:
        """关闭通道"""
        self._state = ChannelState.INACTIVE

    def get_state(self) -> ChannelState:
        """获取通道状态"""
        return self._state

    def update_config(self, config: Dict[str, Any]) -> None:
        """更新配置"""
        self._config.update(config)
```

### 3.2 ChannelRegistry 注册表

```python
# neurova/cognitive_layers/memory_layer/channels/registry.py

from typing import Dict, List, Optional, Type
import threading
import logging

from .base import BaseChannel, ChannelMetadata, ChannelState

logger = logging.getLogger(__name__)


class ChannelRegistry:
    """通道注册表

    管理所有检索通道的生命周期：
    - 注册/注销通道
    - 查询通道（按名称、能力、状态）
    - 枚举所有通道
    - 线程安全
    """

    _instance: Optional['ChannelRegistry'] = None
    _lock = threading.Lock()

    def __new__(cls) -> 'ChannelRegistry':
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._channels: Dict[str, BaseChannel] = {}
                    cls._instance._metadata: Dict[str, ChannelMetadata] = {}
        return cls._instance

    def register(self, channel: BaseChannel) -> bool:
        """注册通道

        Args:
            channel: 通道实例

        Returns:
            注册是否成功
        """
        name = channel.metadata.name
        if name in self._channels:
            logger.warning(f"通道 {name} 已存在，将被覆盖")

        self._channels[name] = channel
        self._metadata[name] = channel.metadata
        logger.info(f"注册通道: {name}")
        return True

    def unregister(self, name: str) -> bool:
        """注销通道

        Args:
            name: 通道名称

        Returns:
            注销是否成功
        """
        if name not in self._channels:
            logger.warning(f"通道 {name} 不存在")
            return False

        channel = self._channels[name]
        if channel.get_state() == ChannelState.ACTIVE:
            logger.warning(f"通道 {name} 仍处于活跃状态，建议先关闭")

        del self._channels[name]
        del self._metadata[name]
        logger.info(f"注销通道: {name}")
        return True

    def get(self, name: str) -> Optional[BaseChannel]:
        """按名称获取通道"""
        return self._channels.get(name)

    def get_all(self) -> List[BaseChannel]:
        """获取所有通道"""
        return list(self._channels.values())

    def get_active(self) -> List[BaseChannel]:
        """获取所有活跃通道"""
        return [
            ch for ch in self._channels.values()
            if ch.get_state() == ChannelState.ACTIVE
        ]

    def get_by_capability(self, capability: str) -> List[BaseChannel]:
        """按能力获取通道"""
        return [
            ch for ch in self._channels.values()
            if capability in ch.metadata.capabilities
        ]

    def get_metadata(self, name: str) -> Optional[ChannelMetadata]:
        """获取通道元数据"""
        return self._metadata.get(name)

    def get_all_metadata(self) -> Dict[str, ChannelMetadata]:
        """获取所有通道元数据"""
        return self._metadata.copy()

    async def initialize_all(self) -> Dict[str, bool]:
        """初始化所有通道

        Returns:
            {channel_name: success}
        """
        results = {}
        for name, channel in self._channels.items():
            try:
                success = await channel.initialize()
                results[name] = success
            except Exception as e:
                logger.error(f"初始化通道 {name} 失败: {e}")
                results[name] = False
        return results

    async def shutdown_all(self) -> None:
        """关闭所有通道"""
        for name, channel in self._channels.items():
            try:
                await channel.shutdown()
            except Exception as e:
                logger.error(f"关闭通道 {name} 失败: {e}")


def get_channel_registry() -> ChannelRegistry:
    """获取通道注册表单例"""
    return ChannelRegistry()
```

### 3.3 ChannelMoERouter

```python
# neurova/cognitive_layers/memory_layer/channels/moe_router.py

from typing import Dict, List, Optional, Any
import asyncio
import logging

from .base import BaseChannel, ChannelResult
from .registry import ChannelRegistry
from ..moe_router import VectorGatingNetwork
from ..unified_vector_store import UnifiedVectorStore

logger = logging.getLogger(__name__)


class ChannelMoERouter:
    """MoE 通道路由器

    使用向量门控网络动态选择激活哪些通道。
    复用现有的 VectorGatingNetwork 实现。
    """

    def __init__(
        self,
        registry: ChannelRegistry,
        vector_store: Optional[UnifiedVectorStore] = None,
        top_k: int = 4,
        activation_threshold: float = 0.3,
        fallback_to_all: bool = True,
        channel_timeout: float = 5.0,
    ):
        """
        Args:
            registry: 通道注册表
            vector_store: 向量存储（用于门控网络）
            top_k: 激活通道数量
            activation_threshold: 激活阈值
            fallback_to_all: MoE 失败时是否回退到全通道
            channel_timeout: 单个通道执行超时（秒）
        """
        self.registry = registry
        self.top_k = top_k
        self.activation_threshold = activation_threshold
        self.fallback_to_all = fallback_to_all
        self.channel_timeout = channel_timeout

        # 初始化门控网络
        self.vector_store = vector_store or UnifiedVectorStore()
        self.gating = VectorGatingNetwork(
            vector_store=self.vector_store,
            top_k=top_k,
            activation_threshold=activation_threshold,
        )

        logger.info(
            f"ChannelMoERouter 初始化完成，"
            f"top_k={top_k}, threshold={activation_threshold}"
        )

    async def retrieve(
        self,
        query: str,
        limit: int = 10,
    ) -> List[ChannelResult]:
        """通过 MoE 路由检索

        Args:
            query: 查询文本
            limit: 返回数量限制

        Returns:
            合并后的结果列表
        """
        # Step 1: 向量编码
        query_vec = self.vector_store.encode(query)

        # Step 2: MoE 路由选择通道
        activated_channels = await self._route_channels(query_vec)

        if not activated_channels and self.fallback_to_all:
            logger.debug("MoE 未激活任何通道，回退到全通道模式")
            activated_channels = {
                ch.metadata.name: 1.0
                for ch in self.registry.get_active()
            }

        # Step 3: 并行执行激活的通道
        results = await self._execute_channels(
            query, limit, activated_channels
        )

        return results

    async def _route_channels(
        self,
        query_vec: List[float],
    ) -> Dict[str, float]:
        """路由选择通道

        Returns:
            {channel_name: activation_score}
        """
        # 确保质心已初始化
        await self._ensure_centroids()

        # 使用门控网络选择
        activated = await self.gating.route(query_vec)

        # 过滤掉不在注册表中的通道
        valid_activated = {
            name: score
            for name, score in activated.items()
            if name in [ch.metadata.name for ch in self.registry.get_active()]
        }

        logger.debug(f"MoE 激活通道: {valid_activated}")
        return valid_activated

    async def _ensure_centroids(self) -> None:
        """确保所有通道的质心已初始化"""
        centroids = self.vector_store.get_expert_centroids()

        for channel in self.registry.get_active():
            name = channel.metadata.name
            if name not in centroids:
                # 使用通道描述生成质心
                description = channel.metadata.description
                centroid = self.vector_store.encode(description)
                self.vector_store.register_centroid(name, centroid)
                logger.debug(f"初始化通道 {name} 质心")

    async def _execute_channels(
        self,
        query: str,
        limit: int,
        activated_channels: Dict[str, float],
    ) -> List[ChannelResult]:
        """并行执行通道"""
        tasks = []
        for channel_name, weight in activated_channels.items():
            channel = self.registry.get(channel_name)
            if channel:
                task = self._execute_single_channel(
                    channel, query, limit, weight
                )
                tasks.append(task)

        # 并行执行，带超时
        results = []
        done, pending = await asyncio.wait(
            tasks,
            timeout=self.channel_timeout,
            return_when=asyncio.ALL_COMPLETED,
        )

        # 收集结果
        for task in done:
            try:
                channel_results = task.result()
                results.extend(channel_results)
            except Exception as e:
                logger.warning(f"通道执行失败: {e}")

        # 取消超时的任务
        for task in pending:
            task.cancel()
            logger.warning(f"通道执行超时，已取消")

        return results

    async def _execute_single_channel(
        self,
        channel: BaseChannel,
        query: str,
        limit: int,
        weight: float,
    ) -> List[ChannelResult]:
        """执行单个通道"""
        try:
            results = await channel.retrieve(
                query=query,
                limit=limit,
                weight=weight,
            )
            return results
        except Exception as e:
            logger.error(f"通道 {channel.metadata.name} 执行失败: {e}")
            return []
```

---

## 4. 测试策略

### 4.1 单元测试

```python
# tests/unit/test_channel_plugins.py

import pytest
from neurova.cognitive_layers.memory_layer.channels.base import (
    BaseChannel, ChannelMetadata, ChannelResult, ChannelState
)
from neurova.cognitive_layers.memory_layer.channels.registry import ChannelRegistry


class MockChannel(BaseChannel):
    """模拟通道"""

    @property
    def metadata(self) -> ChannelMetadata:
        return ChannelMetadata(
            name="mock",
            display_name="Mock Channel",
            description="A mock channel for testing",
        )

    async def retrieve(self, query, limit=10, weight=1.0, **kwargs):
        return [
            ChannelResult(
                memory_id="mem_1",
                content=f"Mock result for: {query}",
                score=0.8 * weight,
                channel="mock",
            )
        ]


@pytest.fixture
def registry():
    return ChannelRegistry()


@pytest.fixture
def mock_channel():
    return MockChannel()


class TestChannelRegistry:
    """注册表测试"""

    def test_register(self, registry, mock_channel):
        assert registry.register(mock_channel) is True
        assert registry.get("mock") is mock_channel

    def test_unregister(self, registry, mock_channel):
        registry.register(mock_channel)
        assert registry.unregister("mock") is True
        assert registry.get("mock") is None

    def test_get_active(self, registry, mock_channel):
        registry.register(mock_channel)
        active = registry.get_active()
        assert len(active) == 1
        assert active[0] is mock_channel

    def test_get_by_capability(self, registry, mock_channel):
        mock_channel.metadata.capabilities = ["text", "semantic"]
        registry.register(mock_channel)
        result = registry.get_by_capability("text")
        assert len(result) == 1


class TestMockChannel:
    """模拟通道测试"""

    @pytest.mark.asyncio
    async def test_retrieve(self, mock_channel):
        results = await mock_channel.retrieve("test query", limit=5)
        assert len(results) == 1
        assert results[0].memory_id == "mem_1"

    @pytest.mark.asyncio
    async def test_initialize(self, mock_channel):
        assert await mock_channel.initialize() is True
        assert mock_channel.get_state() == ChannelState.ACTIVE
```

### 4.2 集成测试

```python
# tests/integration/test_recall_with_plugins.py

import pytest
from neurova.cognitive_layers.memory_layer.neurova_recall import (
    NeurovaRecallEngine, RecallResult
)


@pytest.fixture
def recall_engine():
    """创建配置了插件通道的检索引擎"""
    # 这里会使用真实的通道实现
    engine = NeurovaRecallEngine(...)
    return engine


class TestRecallWithPlugins:
    """使用插件通道的检索测试"""

    @pytest.mark.asyncio
    async def test_recall_returns_results(self, recall_engine):
        results = await recall_engine.recall("test query")
        assert isinstance(results, RecallResult)
        assert len(results.memories) > 0

    @pytest.mark.asyncio
    async def test_recall_maintains_behavior(self, recall_engine):
        """验证重构后行为不变"""
        # 与重构前的结果进行对比
        results_before = [...]  # 重构前的结果
        results_after = await recall_engine.recall("same query")
        # 验证结果一致性
```

### 4.3 性能测试

```python
# tests/performance/test_channel_moe_performance.py

import time
import pytest


class TestMoEPerformance:
    """MoE 路由性能测试"""

    @pytest.mark.asyncio
    async def test_moe_vs_all_channels(self):
        """对比 MoE 路由 vs 全通道执行时间"""
        # MoE 路由模式
        start = time.time()
        results_moe = await moe_router.retrieve("test query")
        time_moe = time.time() - start

        # 全通道模式
        start = time.time()
        results_all = await all_channels.retrieve("test query")
        time_all = time.time() - start

        # MoE 应该更快
        assert time_moe < time_all
        print(f"MoE: {time_moe:.3f}s, All: {time_all:.3f}s")
```

---

## 5. 迁移策略

### 5.1 渐进式迁移

1. **Phase 1 期间**：
   - 保留 `neurova_recall.py` 中的原通道方法
   - 新插件通道与原方法并存
   - 通过配置开关切换

2. **Phase 1 完成后**：
   - 删除 `neurova_recall.py` 中的原通道方法
   - 全部使用插件通道

3. **Phase 2 期间**：
   - 默认使用 MoE 路由
   - 保留全通道模式作为 fallback

### 5.2 配置开关

```yaml
# config/memory_channels.yaml
channels:
  mode: "moe"  # "all" | "moe" | "manual"
  
  moe:
    top_k: 4
    activation_threshold: 0.3
    fallback_to_all: true
    channel_timeout: 5.0
  
  manual:
    enabled:
      - temperature
      - text
      - emotion
  
  builtin:
    temperature:
      enabled: true
      weight: 1.0
    text:
      enabled: true
      weight: 1.0
    category:
      enabled: true
      weight: 0.8
    graph:
      enabled: true
      weight: 0.8
    emotion:
      enabled: true
      weight: 0.9
    voice:
      enabled: true
      weight: 0.7
```

---

## 6. 依赖关系

```
Phase 1 (插件化)
  ├── BaseChannel ← 所有通道依赖
  ├── ChannelRegistry ← NeurovaRecallEngine 依赖
  └── 6 个内置通道实现

Phase 2 (MoE 路由)
  ├── Phase 1 完成
  ├── VectorGatingNetwork ← 复用现有
  └── ChannelMoERouter

Phase 3 (统一结果处理)
  ├── Phase 2 完成
  ├── UnifiedResultProcessor
  └── ConflictDetector
```

---

## 7. 风险与缓解

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|----------|
| 插件化后行为不一致 | 高 | 低 | TDD，行为测试覆盖 |
| MoE 路由选择错误通道 | 中 | 中 | top_k=4，fallback 模式 |
| 通道执行超时 | 中 | 中 | asyncio.wait_for，超时降级 |
| 冲突检测误判 | 低 | 高 | 标记而非删除，用户可查看 |
| 性能下降 | 中 | 低 | 基准测试，性能回归检测 |

---

## 8. 验收标准

### Phase 1 验收

- [ ] BaseChannel 接口完整，包含生命周期方法
- [ ] ChannelRegistry 支持注册/注销/查询/枚举
- [ ] 6 个内置通道独立可测试
- [ ] NeurovaRecallEngine 通过 Registry 调用通道
- [ ] 所有现有测试通过（行为不变）
- [ ] 新增单元测试覆盖率 > 90%

### Phase 2 验收

- [ ] ChannelMoERouter 正确选择通道
- [ ] 通道执行超时降级正常工作
- [ ] MoE 路由准确性 > 85%
- [ ] 性能提升 > 30%（Top-K vs 全通道）

### Phase 3 验收

- [ ] UnifiedResultProcessor 正确去重
- [ ] 权重融合逻辑正确
- [ ] 时序衰减函数可配置
- [ ] 冲突检测准确率 > 80%

---

## 9. 后续演进

### 9.1 插件市场

- 支持第三方通道插件
- 插件版本管理
- 插件依赖管理

### 9.2 自适应路由

- 基于用户反馈调整通道权重
- 质心漂移自适应
- 通道性能监控

### 9.3 分布式通道

- 远程通道执行
- 通道负载均衡
- 通道缓存共享

---

## 10. 参考资料

- [MoE 记忆路由器实现](../neurova/cognitive_layers/memory_layer/moe_router.py)
- [统一检索器实现](../neurova/cognitive_layers/memory_layer/unified_retriever.py)
- [意图感知检索实现](../neurova/cognitive_layers/memory_layer/neurova_recall.py)
- [代码简化原则](../../.agents/skills/code-simplifier/SKILL.md)
