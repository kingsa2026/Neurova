"""
ChannelMoERouter — 通道路由层

使用向量门控网络动态选择激活哪些通道，复用现有 VectorGatingNetwork。
"""
import asyncio
import logging
from typing import Dict, List, Optional

from .base import BaseChannel, ChannelResult
from .registry import ChannelRegistry
from ..moe_router import VectorGatingNetwork
from ..unified_vector_store import UnifiedVectorStore

logger = logging.getLogger(__name__)


class ChannelMoERouter:
    """MoE 通道路由器

    使用向量门控网络动态选择激活哪些通道。
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
        self.registry = registry
        self.top_k = top_k
        self.activation_threshold = activation_threshold
        self.fallback_to_all = fallback_to_all
        self.channel_timeout = channel_timeout

        self.vector_store = vector_store or UnifiedVectorStore()
        self.gating = VectorGatingNetwork(
            vector_store=self.vector_store,
            top_k=top_k,
            activation_threshold=activation_threshold,
        )

        logger.info(
            f"ChannelMoERouter 初始化完成，top_k={top_k}, threshold={activation_threshold}"
        )

    async def retrieve(
        self,
        query: str,
        limit: int = 10,
        memory_manager=None,
    ) -> List[ChannelResult]:
        """通过 MoE 路由检索

        Args:
            query: 查询文本
            limit: 返回数量限制
            memory_manager: 记忆管理器（传递给通道）

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
            query, limit, activated_channels, memory_manager=memory_manager
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
        await self._ensure_centroids()

        activated = await self.gating.route(query_vec)

        valid_names = {ch.metadata.name for ch in self.registry.get_active()}
        valid_activated = {
            name: score
            for name, score in activated.items()
            if name in valid_names
        }

        logger.debug(f"MoE 激活通道: {valid_activated}")
        return valid_activated

    async def _ensure_centroids(self) -> None:
        """确保所有通道的质心已初始化"""
        centroids = self.vector_store.get_expert_centroids()

        for channel in self.registry.get_active():
            name = channel.metadata.name
            if name not in centroids:
                description = channel.metadata.description
                centroid = self.vector_store.encode(description)
                self.vector_store.register_centroid(name, centroid)
                logger.debug(f"初始化通道 {name} 质心")

    async def _execute_channels(
        self,
        query: str,
        limit: int,
        activated_channels: Dict[str, float],
        memory_manager=None,
    ) -> List[ChannelResult]:
        """并行执行通道"""
        tasks = []
        channel_names = []

        for channel_name, ch_weight in activated_channels.items():
            channel = self.registry.get(channel_name)
            if channel:
                tasks.append(
                    self._execute_single_channel(
                        channel, query, limit, ch_weight,
                        memory_manager=memory_manager,
                    )
                )
                channel_names.append(channel_name)

        if not tasks:
            return []

        # 并行执行，带超时
        results = []
        done, pending = await asyncio.wait(
            [asyncio.ensure_future(t) for t in tasks],
            timeout=self.channel_timeout,
            return_when=asyncio.ALL_COMPLETED,
        )

        for task in done:
            try:
                channel_results = await task
                results.extend(channel_results)
            except Exception as e:
                logger.warning(f"通道执行失败: {e}")

        for task in pending:
            task.cancel()
            logger.warning("通道执行超时，已取消")

        return results

    async def _execute_single_channel(
        self,
        channel: BaseChannel,
        query: str,
        limit: int,
        weight: float,
        memory_manager=None,
    ) -> List[ChannelResult]:
        """执行单个通道"""
        try:
            return await channel.retrieve(
                query=query,
                limit=limit,
                weight=weight,
                memory_manager=memory_manager,
            )
        except Exception as e:
            logger.error(f"通道 {channel.metadata.name} 执行失败: {e}")
            return []
