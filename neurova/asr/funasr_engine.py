"""
FunASR Engine - FunASR 音频理解引擎

基于阿里达摩院 FunASR 的本地语音识别。
支持语音识别、音频理解、音频描述等任务。
"""

import asyncio
from neurova.core.logger import get_logger
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict

from neurova.asr.base import ASRBase

if TYPE_CHECKING:
    import numpy as np

logger = get_logger(__name__)


class FunASREngine(ASRBase):
    """
    FunASR 音频理解引擎

    基于 FunASR 的本地语音识别。
    支持语音识别、音频问答、音频描述等任务。
    """

    def __init__(
        self,
        model_dir: str = "models/asr/funasr",
        model_name: str = "funasr",
        device: str = "auto",
        auto_download: bool = True,
    ):
        """
        初始化 FunASREngine

        Args:
            model_dir: 模型目录
            model_name: 模型名称
            device: 推理设备 (auto / cpu / cuda / mps)
            auto_download: 是否自动下载模型
        """
        super().__init__()
        self._model_dir = Path(model_dir)
        self._model_name = model_name
        self._device = device
        self._auto_download = auto_download

        self._model = None
        self._processor = None
        self._lock = threading.Lock()

        # 推理统计
        self._total_requests = 0
        self._total_inference_ms = 0.0

    @property
    def stats(self) -> Dict[str, Any]:
        """推理统计"""
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
        """
        初始化引擎

        流程：
        1. 检查设备可用性
        2. 自动下载模型（如果不存在）
        3. 加载模型和处理器
        """
        try:
            # 检查 FunASR 是否可用
            try:
                import funasr

                self._funasr = funasr
            except ImportError:
                # 诚实降级（补课 4.1）：未安装≠初始化成功——假成功会让
                # manager 选中本引擎后返回"模拟识别结果"污染上层
                self._logger.warning("FunASR 未安装，请运行: pip install funasr")
                self._initialized = False
                return False

            # 检查设备
            if self._device == "auto":
                try:
                    import torch

                    if torch.cuda.is_available():
                        self._device = "cuda"
                    else:
                        self._device = "cpu"
                except ImportError:
                    self._device = "cpu"

            if self._device == "cpu":
                self._logger.info("FunASR 在 CPU 上运行")

            # 加载模型（补课 4.2 续：FunASR 真实现——Paraformer 中文优先）
            try:
                self._logger.info("加载 FunASR 模型: %s", self._model_dir)

                # FunASR AutoModel：默认 paraformer-zh（ModelScope 自动下载到
                # model_dir）。非自回归架构，CPU 上中文识别比 whisper 快一个量级
                AutoModel = self._funasr.AutoModel
                model_kwargs = {
                    "model": self._model_name if "/" in self._model_name else "paraformer-zh",
                    "device": self._device,
                }
                # hub 参数：ModelScope 下载缓存对齐本仓 models/asr/funasr 约定
                self._model = AutoModel(**model_kwargs)
                self._initialized = True
                self._logger.info(
                    "FunASR 初始化完成 | 模型=%s | 设备=%s",
                    model_kwargs["model"],
                    self._device,
                )
                return True

            except Exception as e:
                self._logger.error("FunASR 模型加载失败（诚实降级，交由下一引擎）: %s", e)
                self._model = None
                self._initialized = False
                return False

        except Exception as e:
            self._logger.error(f"FunASR 初始化失败: {e}", exc_info=True)
            return False

    def _load_audio(self, audio_bytes: bytes):
        """加载音频为 numpy 数组"""
        try:
            import io

            import numpy as np
            import soundfile as sf

            with io.BytesIO(audio_bytes) as buf:
                audio, sr = sf.read(buf, dtype="float32")

            # 转单声道
            if audio.ndim == 2:
                audio = audio.mean(axis=1)

            # 重采样到 16kHz（FunASR 的标准采样率）
            target_sr = 16000
            if sr != target_sr:
                duration = len(audio) / sr
                target_len = int(duration * target_sr)
                indices = np.linspace(0, len(audio) - 1, target_len)
                audio = np.interp(indices, np.arange(len(audio)), audio).astype(np.float32)

            return audio

        except Exception as e:
            self._logger.error("音频加载失败: %s", e)
            raise

    async def transcribe(
        self,
        audio_bytes: bytes,
        language: str = "zh",
    ) -> Dict[str, Any]:
        """
        语音识别（ASR）
        """
        if not self._initialized:
            raise RuntimeError("FunASR 未初始化")

        # 检查 FunASR 是否真正可用
        if not hasattr(self, "_funasr") or self._model is None:
            return {
                "text": "",
                "error": "FunASR 未安装或模型未加载",
                "language": language,
                "duration_sec": 0.0,
            }

        start_time = time.time()

        try:
            audio = self._load_audio(audio_bytes)

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

    def _transcribe_sync(self, audio: "np.ndarray", language: str) -> Dict[str, Any]:
        """同步转写（真实现：FunASR AutoModel.generate）。

        AutoModel.generate 返回 list[dict]，键含 text（Paraformer 输出
        已带标点）。language 参数 Paraformer-zh 不消费（模型固定中文+
        英文混合），保留入参供多语种模型切换。
        """
        loop = asyncio.new_event_loop()
        try:
            # generate 是同步阻塞调用，audio 已是 16kHz float32 numpy
            res = self._model.generate(
                input=audio,
                batch_size_s=60,
            )
        except Exception as e:
            self._logger.error("FunASR generate 失败: %s", e)
            return {"text": "", "error": str(e), "language": language}

        text = ""
        if isinstance(res, list) and res:
            text = (res[0].get("text") or "").strip()
        return {
            "text": text,
            "language": language,
            "duration_sec": round(len(audio) / 16000, 2),
        }

    async def shutdown(self) -> None:
        """关闭引擎，释放资源"""
        self._model = None
        self._processor = None
        self._initialized = False

        self._logger.info("FunASREngine 已关闭 | 统计: %s", self.stats)
