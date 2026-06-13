"""内置通道插件"""

from .category import CategoryChannel
from .emotion import EmotionChannel
from .graph import GraphChannel
from .temperature import TemperatureChannel
from .text import TextChannel
from .voice import VoiceChannel

BUILTIN_CHANNELS = [
    TemperatureChannel,
    TextChannel,
    CategoryChannel,
    GraphChannel,
    EmotionChannel,
    VoiceChannel,
]

__all__ = [
    "TemperatureChannel",
    "TextChannel",
    "CategoryChannel",
    "GraphChannel",
    "EmotionChannel",
    "VoiceChannel",
    "BUILTIN_CHANNELS",
]
