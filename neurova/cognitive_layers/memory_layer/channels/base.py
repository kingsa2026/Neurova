"""
BaseChannel 抽象接口 — 所有检索通道的基类

通道是自包含的检索单元，负责：
1. 执行特定维度的记忆检索
2. 返回标准化的 ChannelResult 列表
3. 管理自身生命周期
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
import logging


class ChannelState(Enum):
    """通道状态"""
    INACTIVE = "inactive"
    ACTIVE = "active"
    ERROR = "error"
    DISABLED = "disabled"


@dataclass
class ChannelMetadata:
    """通道元数据"""
    name: str
    display_name: str
    description: str
    version: str = "1.0.0"
    author: str = "system"
    semantic_centroid: Optional[List[float]] = None
    capabilities: List[str] = field(default_factory=list)


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
    """通道抽象基类"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self._config = config or {}
        self._state = ChannelState.INACTIVE
        self._logger = logging.getLogger(f"channel.{self.metadata.name}")

    @property
    @abstractmethod
    def metadata(self) -> ChannelMetadata:
        pass

    @abstractmethod
    async def retrieve(
        self,
        query: str,
        limit: int = 10,
        weight: float = 1.0,
        **kwargs
    ) -> List[ChannelResult]:
        pass

    async def initialize(self) -> bool:
        self._state = ChannelState.ACTIVE
        return True

    async def shutdown(self) -> None:
        self._state = ChannelState.INACTIVE

    def get_state(self) -> ChannelState:
        return self._state

    def update_config(self, config: Dict[str, Any]) -> None:
        self._config.update(config)
