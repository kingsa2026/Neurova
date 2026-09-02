# -*- coding: utf-8 -*-
"""Remote Whisper Engine — OpenAI 兼容 /audio/transcriptions 远程调用。

补课对比文档"抄 QP 的 ASR 双模架构"落地：本地 FunASR 中文首选，
远程 Whisper 多语言（无需本地 torch/模型），本地 whisper 离线兜底。

配置（env）:
- NEUROVA_ASR_REMOTE_BASE_URL  默认 https://api.openai.com/v1
  （任何 OpenAI 兼容转写端点可替换：Groq/SiliconFlow/自建等）
- NEUROVA_ASR_REMOTE_API_KEY   优先；缺省回落 OPENAI_API_KEY
- NEUROVA_ASR_REMOTE_MODEL     默认 whisper-1

诚实语义：无 key → initialize False；key 无效（探测 401）→ False；
调用失败返回 {"text": "", "error": ...} 不产假文本。
"""
import asyncio
import time
from typing import Any, Dict, Optional

from neurova.asr.base import ASRBase
from neurova.core.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_BASE_URL = "https://api.openai.com/v1"
_PROBE_TIMEOUT = 10.0
_TRANSCRIBE_TIMEOUT = 60.0


class RemoteWhisperEngine(ASRBase):
    """远程 Whisper（OpenAI 兼容转写 API）。

    ASRManager.transcribe(audio_bytes, language) 只传字节流——远程 API
    需要文件名推断格式，默认 audio.wav（浏览器 MediaRecorder 的 webm
    场景由前端先走本地 funasr 主链，远程兜底按 wav 传）。
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: str = "whisper-1",
        timeout: float = _TRANSCRIBE_TIMEOUT,
    ):
        super().__init__()
        import os

        self._base_url = (
            base_url
            or os.environ.get("NEUROVA_ASR_REMOTE_BASE_URL")
            or _DEFAULT_BASE_URL
        ).rstrip("/")
        self._api_key = api_key or os.environ.get("NEUROVA_ASR_REMOTE_API_KEY") or os.environ.get(
            "OPENAI_API_KEY"
        )
        self._model = model
        self._timeout = timeout

        self._total_requests = 0
        self._total_inference_ms = 0.0

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    async def initialize(self) -> bool:
        """就绪探测：无 key 诚实 False；用 GET /models 轻校验 key（401=False）。"""
        import os

        if not self._api_key:
            self._logger.warning(
                "RemoteWhisper 无 API key（NEUROVA_ASR_REMOTE_API_KEY/OPENAI_API_KEY），跳过"
            )
            self._initialized = False
            return False
        # 测试态跳过网络探测（key 形式已足够；真连通性由首次调用验证）
        if os.environ.get("NEUROVA_ENV") == "test":
            self._initialized = True
            return True

        try:
            import requests

            resp = await asyncio.to_thread(
                lambda: requests.get(
                    f"{self._base_url}/models",
                    headers=self._headers(),
                    timeout=_PROBE_TIMEOUT,
                )
            )
            if resp.status_code in (401, 403):
                self._logger.warning(
                    "RemoteWhisper key 校验失败（%s），跳过远程引擎", resp.status_code
                )
                self._initialized = False
                return False
            # 非 401/403 的异常状态（网络差/网关拦截）不武断否定——放行，
            # 转写失败时仍有 error 兜底
            self._initialized = True
            self._logger.info("RemoteWhisper 就绪: %s (model=%s)", self._base_url, self._model)
            return True
        except Exception as e:
            self._logger.warning("RemoteWhisper 探测失败（%s），跳过远程引擎", e)
            self._initialized = False
            return False

    async def transcribe(
        self,
        audio_bytes: bytes,
        language: str = "zh",
    ) -> Dict[str, Any]:
        """multipart POST /audio/transcriptions（线程池执行，不阻塞事件循环）。"""
        if not self._initialized or not self._api_key:
            return {"text": "", "error": "RemoteWhisper 未就绪", "language": language}

        start_time = time.time()
        try:
            import requests

            data: Dict[str, Any] = {"model": self._model}
            if language and language != "auto":
                data["language"] = language

            def _post():
                return requests.post(
                    f"{self._base_url}/audio/transcriptions",
                    headers=self._headers(),
                    files={"file": ("audio.wav", audio_bytes, "audio/wav")},
                    data=data,
                    timeout=self._timeout,
                )

            resp = await asyncio.to_thread(_post)
            inference_ms = (time.time() - start_time) * 1000

            if resp.status_code != 200:
                return {
                    "text": "",
                    "error": f"远程转写失败 HTTP {resp.status_code}: {resp.text[:200]}",
                    "language": language,
                }

            payload = resp.json()
            text = (payload.get("text") or "").strip()
            with_safe_stats = {"text": text, "language": language}
            self._total_requests += 1
            self._total_inference_ms += inference_ms
            with_safe_stats["inference_ms"] = round(inference_ms, 2)
            return with_safe_stats

        except Exception as e:
            self._logger.error("RemoteWhisper 转写失败: %s", e)
            return {"text": "", "error": str(e), "language": language}

    async def shutdown(self) -> None:
        self._initialized = False
        self._logger.info("RemoteWhisperEngine 已关闭 | 统计: %s", self.stats)

    @property
    def stats(self) -> Dict[str, Any]:
        avg_ms = (
            self._total_inference_ms / self._total_requests if self._total_requests else 0.0
        )
        return {
            "engine": "remote_whisper",
            "initialized": self._initialized,
            "model": self._model,
            "base_url": self._base_url,
            "total_requests": self._total_requests,
            "avg_inference_ms": round(avg_ms, 2),
        }
