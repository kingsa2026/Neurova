"""
CentroidInitializer — 从通道描述自动生成质心向量

在 MoE 路由中，每个通道需要一个质心向量来计算查询相关性。
质心从通道的 description 字段自动生成。
"""

import logging
from typing import Any

from .registry import ChannelRegistry

logger = logging.getLogger(__name__)


class CentroidInitializer:
    """通道质心初始化器"""

    def __init__(self, vector_store: Any):
        """
        Args:
            vector_store: UnifiedVectorStore 实例（用于编码和存储质心）
        """
        self.vector_store = vector_store

    def generate_centroids(self, registry: ChannelRegistry) -> int:
        """为所有缺少质心的通道生成质心

        Args:
            registry: 通道注册表

        Returns:
            新生成的质心数量
        """
        existing = self.vector_store.get_expert_centroids()
        count = 0

        for channel in registry.get_all():
            name = channel.metadata.name
            if name in existing:
                continue

            description = channel.metadata.description
            if not description:
                logger.warning("通道 %s 无描述，跳过质心生成", name)
                continue

            centroid = self.vector_store.encode(description)
            self.vector_store.register_centroid(name, centroid)
            count += 1
            logger.debug("为通道 %s 生成质心", name)

        return count
