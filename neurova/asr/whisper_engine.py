"""
Whisper Engine - OpenAI Whisper 音频理解引擎

基于 openai-whisper 的本地语音识别。
支持语音识别、音频理解、音频描述等任务。
"""

import asyncio
from neurova.core.logger import get_logger
import threading
import time
from pathlib import Path
from typing import Any, Dict

from neurova.asr.base import ASRBase

logger = get_logger(__name__)


class WhisperEngine(ASRBase):
    """
    Whisper 音频理解引擎

    基于 OpenAI Whisper 的本地语音识别。
    支持语音识别、音频问答、音频描述等任务。
    """

    def __init__(
        self,
        model_dir: str = "models/asr/whisper",
        model_name: str = "base",
        device: str = "auto",
        auto_download: bool = True,
    ):
        super().__init__()
        self._model_dir = Path(model_dir)
        self._model_name = model_name
        self._device = device
        self._auto_download = auto_download

        self._model = None
        self._lock = threading.Lock()

        self._total_requests = 0
        self._total_inference_ms = 0.0

    @property
    def stats(self) -> Dict[str, Any]:
        avg_ms = self._total_inference_ms / self._total_requests if self._total_requests > 0 else 0
        return {
            "model_name": self._model_name,
            "initialized": self._initialized,
            "device": self._device,
            "total_requests": self._total_requests,
            "total_inference_ms": round(self._total_inference_ms, 2),
            "avg_inference_ms": round(avg_ms, 2),
        }

    async def initialize(self) -> bool:
        try:
            try:
                import whisper

                self._whisper = whisper
            except ImportError:
                self._logger.warning("whisper 未安装，请运行: pip install openai-whisper")
                self._initialized = True
                return True

            if self._device == "auto":
                try:
                    import torch

                    if torch.cuda.is_available():
                        self._device = "cuda"
                    else:
                        self._device = "cpu"
                except ImportError:
                    self._device = "cpu"

            try:
                self._model = self._whisper.load_model(self._model_name, device=self._device)
                self._initialized = True
                self._logger.info("Whisper 初始化完成 | 模型=%s | 设备=%s", self._model_name, self._device)
                return True
            except Exception as e:
                self._logger.error("Whisper 模型加载失败: %s", e)
                return False

        except Exception as e:
            self._logger.error(f"Whisper 初始化失败: {e}", exc_info=True)
            return False

    def _load_audio(self, audio_bytes: bytes):
        """加载音频"""
        import io

        try:
            import soundfile as sf

            with io.BytesIO(audio_bytes) as buf:
                audio, sr = sf.read(buf, dtype="float32")
            if audio.ndim == 2:
                audio = audio.mean(axis=1)
            return audio, sr
        except Exception as e:
            self._logger.error("音频加载失败: %s", e)
            raise

    async def transcribe(
        self,
        audio_bytes: bytes,
        language: str = "zh",
    ) -> Dict[str, Any]:
        if not self._initialized:
            raise RuntimeError("Whisper 未初始化")

        if not hasattr(self, "_whisper") or self._model is None:
            return {
                "text": "",
                "error": "Whisper 未安装或模型未加载",
                "language": language,
                "duration_sec": 0.0,
            }

        start_time = time.time()

        try:
            audio, sr = self._load_audio(audio_bytes)

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, self._transcribe_sync, audio, language)

            inference_ms = (time.time() - start_time) * 1000
            with self._lock:
                self._total_requests += 1
                self._total_inference_ms += inference_ms

            result["inference_ms"] = round(inference_ms, 2)
            return result

        except Exception as e:
            self._logger.error(f"转写失败: {e}", exc_info=True)
            return {"text": "", "error": str(e)}

    def _transcribe_sync(self, audio, language: str) -> Dict[str, Any]:
        """同步转写"""
        # Whisper 需要 numpy 数组
        try:
            import numpy as np

            if not isinstance(audio, np.ndarray):
                audio = np.array(audio, dtype=np.float32)
        except ImportError:
            return {"text": "", "error": "numpy 未安装"}

        lang = language if language != "auto" else None
        result = self._model.transcribe(audio, language=lang)

        return {
            "text": result.get("text", "").strip(),
            "language": result.get("language", language),
            "duration_sec": round(len(audio) / 16000, 2),
        }

    async def shutdown(self) -> None:
        self._model = None
        self._initialized = False
        self._logger.info("WhisperEngine 已关闭 | 统计: %s", self.stats)
