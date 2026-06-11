"""内置通道插件"""
from .temperature import TemperatureChannel
from .text import TextChannel
from .category import CategoryChannel
from .graph import GraphChannel
from .emotion import EmotionChannel
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
    "TemperatureChannel", "TextChannel", "CategoryChannel",
    "GraphChannel", "EmotionChannel", "VoiceChannel",
    "BUILTIN_CHANNELS",
]
