# -*- coding: utf-8 -*-
"""语音工具族（asr_transcribe / tts_synthesize / voice_memory_search）。

从 neurova.tool_executor 拆出；修复漂移 schema 已注册但分派链缺失。
`_builtin_dispatch` 目标 `_execute_asr_transcribe` / `_execute_tts_synthesize` /
`_execute_voice_memory_search` 不变。`_agent` 由 ToolExecutor 提供。
不顶层 import `neurova.tool_executor`。
"""
import asyncio
from typing import Dict

from neurova.core.logger import get_logger

__all__ = ["VoiceToolsMixin"]

logger = get_logger(__name__)


class VoiceToolsMixin:
    """ASR/TTS/voice_memory_search built-ins."""

    async def _execute_asr_transcribe(self, params: Dict) -> Dict:
        """语音识别：Base64 音频 → 文本（经 agent.asr_manager）"""
        import base64

        audio_b64 = params.get("audio_data", "")
        if not audio_b64:
            return {"error": "缺少 audio_data 参数（Base64 编码音频）"}
        manager = getattr(self._agent, "asr_manager", None)
        if manager is None:
            return {"error": "ASR 未启用（asr_manager 不存在），请先在 Agent 配置中开启 asr"}

        try:
            audio_bytes = base64.b64decode(audio_b64, validate=True)
        except Exception as e:
            return {"error": f"audio_data 不是有效的 Base64: {e}"}

        try:
            if not getattr(manager, "is_initialized", False):
                await manager.initialize()
            result = await manager.transcribe(audio_bytes, language=params.get("language", "zh"))
        except Exception as e:
            return {"error": f"语音识别失败: {e}"}

        if isinstance(result, dict):
            if result.get("error") and not result.get("text"):
                return {"error": f"语音识别失败: {result['error']}"}
            return {
                "success": True,
                "text": result.get("text", ""),
                "language": result.get("language"),
                "duration_sec": result.get("duration_sec"),
            }
        return {"success": True, "text": str(result)}

    async def _execute_tts_synthesize(self, params: Dict) -> Dict:
        """语音合成：文本 → 音频文件（经 agent.tts_manager）

        音频写入临时文件，只回传路径与元信息——把 base64 音频塞进
        LLM 上下文会撑爆 token（与 computer_screenshot 只回元信息同理）。
        voice/engine 在 manager 初始化时已配置，且部分引擎的 synthesize
        签名不接受额外 kwargs，故不透传。
        """
        import os
        import tempfile

        text = params.get("text", "")
        if not text:
            return {"error": "缺少 text 参数"}
        manager = getattr(self._agent, "tts_manager", None)
        if manager is None:
            return {"error": "TTS 未启用（tts_manager 不存在），请先在 Agent 配置中开启 tts"}

        try:
            if not getattr(manager, "is_initialized", False):
                await manager.initialize()
            audio = await manager.synthesize(text)
        except Exception as e:
            return {"error": f"语音合成失败: {e}"}
        if not audio:
            return {"error": "语音合成失败: 引擎返回空数据"}

        # 按文件头识别音频格式
        suffix = ".bin"
        if audio.startswith(b"RIFF"):
            suffix = ".wav"
        elif audio.startswith(b"ID3") or audio[:1] == b"\xff":
            suffix = ".mp3"
        elif audio.startswith(b"OggS"):
            suffix = ".ogg"

        try:
            out_dir = os.path.join(tempfile.gettempdir(), "neurova_tts")
            os.makedirs(out_dir, exist_ok=True)
            fd, audio_path = tempfile.mkstemp(suffix=suffix, prefix="tts_", dir=out_dir)
            with os.fdopen(fd, "wb") as f:
                f.write(audio)
        except OSError as e:
            return {"error": f"音频文件写入失败: {e}"}

        return {
            "success": True,
            "audio_path": audio_path,
            "bytes": len(audio),
            "format": suffix.lstrip("."),
            "text": text[:100],
        }

    async def _execute_voice_memory_search(self, params: Dict) -> Dict:
        """执行语音转写记忆搜索"""
        try:
            query = params.get("query", "")
            limit = params.get("limit", 5)

            if not query:
                return {"error": "缺少搜索查询"}

            # 获取 MemoryManager
            memory_manager = None
            if hasattr(self._agent, "memory_manager") and self._agent.memory_manager:
                memory_manager = self._agent.memory_manager
            else:
                try:
                    from neurova.cognitive_layers.memory_layer.manager import MemoryManager

                    memory_manager = MemoryManager()
                except ImportError:
                    logger.warning("MemoryManager 模块不可用")
                    return {"results": [], "query": query, "count": 0}

            # 搜索语音转写记忆（使用 category 过滤）
            # 与 memory_search 同一 recall 路径（同步 SQLite/向量 I/O），故同处置：
            # 下沉线程池。本工具已声明可并行，留在事件循环里会在成组批中
            # 连累同批全部兄弟——那比串行更差。
            memories = await asyncio.to_thread(
                memory_manager.recall,
                query=query,
                category="voice_transcription",  # 语音转写类别
                limit=limit,
            )

            # 格式化结果
            results = []
            for memory in memories:
                results.append(
                    {
                        "id": memory.get("id", ""),
                        "content": memory.get("content", ""),
                        "category": memory.get("category", ""),
                        "transcription": memory.get("metadata", {}).get("transcription", ""),
                        "timestamp": memory.get("created_at", ""),
                    }
                )

            return {
                "success": True,
                "results": results,
                "query": query,
                "count": len(results),
            }
        except Exception as e:
            logger.error("语音记忆搜索执行失败: %s", e)
            return {"error": f"语音记忆搜索执行失败: {str(e)}", "results": [], "count": 0}
