"""
TTS Module - 语音合成模块

支持多种TTS引擎：
1. Edge TTS（默认，在线，中文音色好，无需下载模型）
2. MOSS-TTS-Nano（可选，本地，支持中文，自动下载模型）
3. ChatTTS（可选，本地，自然度高）
"""

# tts imports
import neurova.tts.base
import neurova.tts.edge_tts
import neurova.tts.manager
import neurova.tts.moss_nano

pass