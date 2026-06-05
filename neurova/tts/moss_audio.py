"""
MOSS Audio Engine - MOSS-Audio 音频理解引擎

基于 MOSS-Audio-4B-Instruct / MOSS-Audio-8B-Instruct 的本地音频理解。
支持语音识别、音频理解、音频描述等任务。
"""

import asyncio
import io
import logging
import time
import threading
from pathlib import Path
from typing import Optional, AsyncGenerator, Dict, Any

import numpy as np

from neurova.tts.model_downloader import ModelDownloader, get_model_downloader

logger = logging.getLogger(__name__)


class MOSSAudioEngine:
    """
    MOSS-Audio 音频理解引擎

    基于 Qwen3-4B/8B backbone 的音频理解模型。
    支持语音识别、音频问答、音频描述等任务。

    注意：此引擎需要较大的显存（4B ~8GB, 8B ~16GB），
    仅在有 GPU 可用时启用。
    """

    def __init__(
        self,
        model_dir: str = "models/audio/moss-audio-4b",
        model_name: str = "moss-audio-4b",
        device: str = "auto",
        auto_download: bool = True,
        max_memory_mb: int = 8192,
    ):
        """
        初始化 MOSSAudioEngine

        Args:
            model_dir: 模型目录
            model_name: 模型名称 (moss-audio-4b / moss-audio-8b)
            device: 推理设备 (auto / cpu / cuda / mps)
            auto_download: 是否自动下载模型
            max_memory_mb: 最大显存限制（MB）
        """
        self._model_dir = Path(model_dir)
        self._model_name = model_name
        self._device = device
        self._auto_download = auto_download
        self._max_memory_mb = max_memory_mb
        self._logger = logging.getLogger("MOSSAudioEngine")

        self._model = None
        self._processor = None
        self._downloader: Optional[ModelDownloader] = None
        self._lock = threading.Lock()
        self._initialized = False

        # 推理统计
        self._total_requests = 0
        self._total_inference_ms = 0.0

    @property
    def is_available(self) -> bool:
        """检查引擎是否可用（需要 GPU 和足够的显存）"""
        try:
            import torch
            if torch.cuda.is_available():
                free_mem = torch.cuda.get_device_properties(0).total_mem / (1024 * 1024)
                return free_mem >= self._max_memory_mb
            return False
        except ImportError:
            return False

    @property
    def stats(self) -> Dict[str, Any]:
        """推理统计"""
        avg_ms = (
            self._total_inference_ms / self._total_requests
            if self._total_requests > 0
            else 0
        )
        return {
            "model_name": self._model_name,
            "initialized": self._initialized,
            "device": self._device,
            "total_requests": self._total_requests,
            "total_inference_ms": round(self._total_inference_ms, 2),
            "avg_inference_ms": round(avg_ms, 2),
        }

    async def initialize(self) -> bool:
        """
        初始化引擎

        流程：
        1. 检查 GPU 可用性
        2. 自动下载模型（如果不存在）
        3. 加载模型和处理器
        """
        try:
            # 检查 PyTorch
            try:
                import torch
                self._torch = torch
            except ImportError:
                self._logger.error("PyTorch 未安装，请运行: pip install torch")
                return False

            # 检查 GPU
            if self._device == "auto":
                if torch.cuda.is_available():
                    self._device = "cuda"
                elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                    self._device = "mps"
                else:
                    self._device = "cpu"

            if self._device == "cpu":
                self._logger.warning(
                    "MOSS-Audio 在 CPU 上运行会很慢，建议使用 GPU"
                )

            # 检查显存
            if self._device == "cuda":
                free_mem = torch.cuda.get_device_properties(0).total_mem / (1024 * 1024)
                if free_mem < self._max_memory_mb:
                    self._logger.error(
                        f"显存不足: 需要 {self._max_memory_mb}MB，可用 {free_mem:.0f}MB"
                    )
                    return False

            # 下载模型
            self._downloader = get_model_downloader()
            if self._auto_download:
                self._model_dir = self._downloader.ensure_model(self._model_name)

            # 加载模型
            try:
                from transformers import AutoModelForCausalLM, AutoProcessor

                self._logger.info(f"加载 MOSS-Audio 模型: {self._model_dir}")

                self._processor = AutoProcessor.from_pretrained(
                    str(self._model_dir), trust_remote_code=True
                )
                self._model = AutoModelForCausalLM.from_pretrained(
                    str(self._model_dir),
                    device_map=self._device if self._device != "cpu" else None,
                    torch_dtype=torch.float16 if self._device == "cuda" else torch.float32,
                    trust_remote_code=True,
                )

                self._initialized = True
                self._logger.info(
                    f"MOSS-Audio 初始化完成 | "
                    f"模型={self._model_name} | "
                    f"设备={self._device}"
                )
                return True

            except ImportError:
                self._logger.error("transformers 未安装，请运行: pip install transformers")
                return False

        except Exception as e:
            self._logger.error(f"MOSS-Audio 初始化失败: {e}", exc_info=True)
            return False

    def _load_audio(self, audio_bytes: bytes) -> np.ndarray:
        """加载音频为 numpy 数组"""
        try:
            import soundfile as sf

            with io.BytesIO(audio_bytes) as buf:
                audio, sr = sf.read(buf, dtype="float32")

            # 转单声道
            if audio.ndim == 2:
                audio = audio.mean(axis=1)

            # 重采样到 16kHz（MOSS-Audio 的标准采样率）
            target_sr = 16000
            if sr != target_sr:
                duration = len(audio) / sr
                target_len = int(duration * target_sr)
                indices = np.linspace(0, len(audio) - 1, target_len)
                audio = np.interp(indices, np.arange(len(audio)), audio).astype(np.float32)

            return audio

        except Exception as e:
            self._logger.error(f"音频加载失败: {e}")
            raise

    async def transcribe(
        self,
        audio_bytes: bytes,
        language: str = "zh",
    ) -> Dict[str, Any]:
        """
        语音识别（ASR）

        Args:
            audio_bytes: 音频字节数据
            language: 目标语言 (zh / en / auto)

        Returns:
            {"text": "识别结果", "language": "zh", "duration_sec": float}
        """
        if not self._initialized:
            raise RuntimeError("MOSS-Audio 未初始化")

        start_time = time.time()

        try:
            audio = self._load_audio(audio_bytes)

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, self._transcribe_sync, audio, language
            )

            inference_ms = (time.time() - start_time) * 1000
            with self._lock:
                self._total_requests += 1
                self._total_inference_ms += inference_ms

            result["inference_ms"] = round(inference_ms, 2)
            return result

        except Exception as e:
            self._logger.error(f"转写失败: {e}", exc_info=True)
            return {"text": "", "error": str(e)}

    def _transcribe_sync(self, audio: np.ndarray, language: str) -> Dict[str, Any]:
        """同步转写"""
        prompt = f"请识别以下音频中的语音内容，语言：{language}。只返回识别结果，不要其他内容。"

        inputs = self._processor(
            text=prompt,
            audios=audio,
            return_tensors="pt",
        ).to(self._model.device)

        with self._torch.no_grad():
            outputs = self._model.generate(
                **inputs,
                max_new_tokens=2048,
                temperature=0.1,
                do_sample=False,
            )

        # 解码输出
        generated = outputs[0][inputs["input_ids"].shape[1]:]
        text = self._processor.decode(generated, skip_special_tokens=True)

        return {
            "text": text.strip(),
            "language": language,
            "duration_sec": round(len(audio) / 16000, 2),
        }

    async def understand(
        self,
        audio_bytes: bytes,
        query: str = "这段音频说了什么？",
    ) -> Dict[str, Any]:
        """
        音频理解 + 问答

        Args:
            audio_bytes: 音频字节数据
            query: 关于音频的问题

        Returns:
            {"answer": "...", "duration_sec": float}
        """
        if not self._initialized:
            raise RuntimeError("MOSS-Audio 未初始化")

        start_time = time.time()

        try:
            audio = self._load_audio(audio_bytes)

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, self._understand_sync, audio, query
            )

            inference_ms = (time.time() - start_time) * 1000
            with self._lock:
                self._total_requests += 1
                self._total_inference_ms += inference_ms

            result["inference_ms"] = round(inference_ms, 2)
            return result

        except Exception as e:
            self._logger.error(f"音频理解失败: {e}", exc_info=True)
            return {"answer": "", "error": str(e)}

    def _understand_sync(self, audio: np.ndarray, query: str) -> Dict[str, Any]:
        """同步理解"""
        inputs = self._processor(
            text=query,
            audios=audio,
            return_tensors="pt",
        ).to(self._model.device)

        with self._torch.no_grad():
            outputs = self._model.generate(
                **inputs,
                max_new_tokens=2048,
                temperature=0.3,
                do_sample=True,
            )

        generated = outputs[0][inputs["input_ids"].shape[1]:]
        answer = self._processor.decode(generated, skip_special_tokens=True)

        return {
            "answer": answer.strip(),
            "duration_sec": round(len(audio) / 16000, 2),
        }

    async def caption(self, audio_bytes: bytes) -> Dict[str, Any]:
        """
        音频描述

        Args:
            audio_bytes: 音频字节数据

        Returns:
            {"caption": "音频描述", "duration_sec": float}
        """
        return await self.understand(
            audio_bytes,
            query="请描述这段音频的内容，包括说话人特征、情感、背景声音等。",
        )

    async def shutdown(self) -> None:
        """关闭引擎，释放资源"""
        self._model = None
        self._processor = None
        self._initialized = False

        if self._device == "cuda" and self._torch:
            self._torch.cuda.empty_cache()

        self._logger.info(f"MOSSAudioEngine 已关闭 | 统计: {self.stats}")
