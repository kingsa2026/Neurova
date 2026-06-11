"""记忆检索通道插件化基础设施"""
from .base import BaseChannel, ChannelMetadata, ChannelResult, ChannelState
from .registry import ChannelRegistry, get_channel_registry
from .centroid import CentroidInitializer
from .threshold import ThresholdConfig
from .processor import UnifiedResultProcessor
from .conflict import ConflictDetector, ConflictPair
from .temporal import TemporalDecay
from .weight import WeightAdjuster

__all__ = [
    "BaseChannel", "ChannelMetadata", "ChannelResult", "ChannelState",
    "ChannelRegistry", "get_channel_registry",
    "CentroidInitializer", "ThresholdConfig",
    "UnifiedResultProcessor", "ConflictDetector", "ConflictPair",
    "TemporalDecay", "WeightAdjuster",
]
