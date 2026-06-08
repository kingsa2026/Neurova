"""
MOSS Nano TTS - MOSS-TTS-Nano ONNX 推理引擎

超轻量级中文TTS模型（0.1B参数）
- 48kHz 立体声输出
- CPU 4核即可运行
- 支持零样本声音克隆（~3秒参考音频）
- 自动从 HuggingFace 下载模型
"""

import asyncio
import io
import logging
import struct
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional, AsyncGenerator

try:
    import numpy as np
except ImportError:
    np = None

from neurova.tts.base import TTSBase
from neurova.tts.model_downloader import ModelDownloader, get_model_downloader

logger = logging.getLogger(__name__)


def _create_wav_bytes(
    audio_data: np.ndarray,
    sample_rate: int = 48000,
    channels: int = 2,
    bits_per_sample: int = 16,
) -> bytes:
    """
    将 numpy 音频数组转换为 WAV 格式字节

    Args:
        audio_data: 音频数据 (float32, 归一化到 [-1, 1])
        sample_rate: 采样率
        channels: 声道数
        bits_per_sample: 位深度

    Returns:
        WAV 格式的字节数据
    """
    # 确保数据是 float32
    if audio_data.dtype != np.float32:
        audio_data = audio_data.astype(np.float32)

    # 归一化到 [-1, 1]
    max_val = np.max(np.abs(audio_data))
    if max_val > 1.0:
        audio_data = audio_data / max_val
    elif max_val == 0:
        audio_data = np.zeros_like(audio_data)

    # 转换为 int16
    audio_int16 = (audio_data * 32767).astype(np.int16)

    # 确保是连续的字节
    raw_data = audio_int16.tobytes()
    data_size = len(raw_data)

    # 构建 WAV 头
    byte_rate = sample_rate * channels * (bits_per_sample // 8)
    block_align = channels * (bits_per_sample // 8)

    header = bytearray()
    header.extend(b"RIFF")
    header.extend(struct.pack("<I", 36 + data_size))
    header.extend(b"WAVE")
    header.extend(b"fmt ")
    header.extend(struct.pack("<I", 16))  # fmt chunk size
    header.extend(struct.pack("<H", 1))   # PCM format
    header.extend(struct.pack("<H", channels))
    header.extend(struct.pack("<I", sample_rate))
    header.extend(struct.pack("<I", byte_rate))
    header.extend(struct.pack("<H", block_align))
    header.extend(struct.pack("<H", bits_per_sample))
    header.extend(b"data")
    header.extend(struct.pack("<I", data_size))

    return bytes(header) + raw_data


class MOSSNanTTS(TTSBase):
    """
    MOSS-TTS-Nano 本地推理引擎

    基于 ONNX Runtime，无需 GPU，CPU 4核即可运行。
    首次使用自动从 HuggingFace 下载模型（~200MB）。
    """

    def __init__(
        self,
        model_dir: str = "models/tts/moss-nano",
        tokenizer_dir: str = "models/tts/moss-tokenizer",
        sample_rate: int = 48000,
        channels: int = 2,
        auto_download: bool = True,
    ):
        """
        初始化 MOSSNanTTS

        Args:
            model_dir: TTS 模型目录
            tokenizer_dir: Tokenizer 模型目录（声音克隆需要）
            sample_rate: 输出采样率
            channels: 输出声道数
            auto_download: 是否自动下载模型
        """
        super().__init__()
        self._model_dir = Path(model_dir)
        self._tokenizer_dir = Path(tokenizer_dir)
        self._sample_rate = sample_rate
        self._channels = channels
        self._auto_download = auto_download

        self._tts_session = None
        self._tokenizer_session = None
        self._downloader: Optional[ModelDownloader] = None
        self._lock = threading.Lock()

        # 推理统计
        self._total_syntheses = 0
        self._total_duration_sec = 0.0
        self._total_inference_ms = 0.0

    @property
    def stats(self) -> dict:
        """推理统计"""
        avg_ms = (
            self._total_inference_ms / self._total_syntheses
            if self._total_syntheses > 0
            else 0
        )
        return {
            "total_syntheses": self._total_syntheses,
            "total_audio_duration_sec": round(self._total_duration_sec, 2),
            "total_inference_ms": round(self._total_inference_ms, 2),
            "avg_inference_ms": round(avg_ms, 2),
            "sample_rate": self._sample_rate,
            "channels": self._channels,
        }

    async def initialize(self) -> bool:
        """
        初始化推理引擎

        流程：
        1. 自动下载模型（如果不存在）
        2. 加载 ONNX Runtime Session
        3. 预热模型（一次空推理）
        """
        try:
            self._downloader = get_model_downloader()

            # 自动下载 TTS 模型
            if self._auto_download:
                self._model_dir = self._downloader.ensure_model("moss-tts-nano")
                # 尝试下载 tokenizer（声音克隆用，失败不影响主功能）
                try:
                    self._tokenizer_dir = self._downloader.ensure_model("moss-audio-tokenizer")
                except Exception:
                    logger.warning("Tokenizer 下载失败，声音克隆功能不可用")
            else:
                if not self._downloader.is_model_available("moss-tts-nano"):
                    logger.error(f"模型不存在: {self._model_dir}")
                    return False

            # 加载 ONNX Runtime
            try:
                import onnxruntime as ort
                self._ort = ort
            except ImportError:
                logger.error("onnxruntime 未安装，请运行: pip install onnxruntime")
                return False

            # 加载 TTS 模型
            tts_model_path = self._model_dir / "model.onnx"
            if not tts_model_path.exists():
                # 尝试查找其他常见命名
                onnx_files = list(self._model_dir.glob("*.onnx"))
                if onnx_files:
                    tts_model_path = onnx_files[0]
                else:
                    logger.error(f"TTS ONNX 模型文件不存在: {tts_model_path}")
                    return False

            session_opts = ort.SessionOptions()
            session_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            session_opts.inter_op_num_threads = 4
            session_opts.intra_op_num_threads = 4

            self._tts_session = ort.InferenceSession(
                str(tts_model_path), sess_options=session_opts
            )
            logger.info(f"TTS 模型加载完成: {tts_model_path}")

            # 加载 Tokenizer（可选）
            tokenizer_path = self._tokenizer_dir / "model.onnx"
            if tokenizer_path.exists():
                try:
                    self._tokenizer_session = ort.InferenceSession(
                        str(tokenizer_path), sess_options=session_opts
                    )
                    logger.info(f"Tokenizer 加载完成: {tokenizer_path}")
                except Exception as e:
                    logger.warning(f"Tokenizer 加载失败（声音克隆不可用）: {e}")

            self._initialized = True
            logger.info(
                f"MOSSNanTTS 初始化完成 | "
                f"采样率={self._sample_rate} | "
                f"声道={self._channels} | "
                f"Tokenizer={'OK' if self._tokenizer_session else 'N/A'}"
            )
            return True

        except Exception as e:
            logger.error(f"MOSSNanTTS 初始化失败: {e}", exc_info=True)
            return False

    def _normalize_text(self, text: str) -> str:
        """
        文本预处理

        处理数字、符号等，使其适合 TTS 引擎。
        """
        import re

        # 基础清理
        text = text.strip()
        if not text:
            return ""

        # 移除连续的特殊字符
        text = re.sub(r"[^\w\s\u4e00-\u9fff.,!?，。！？、；：\u201c\u201d\u2018\u2019（）【】《》\\-]", " ", text)

        # 合并多余空格
        text = re.sub(r"\s+", " ", text).strip()

        return text

    def _run_inference(
        self,
        text: str,
        voice_ref_audio: Optional[np.ndarray] = None,
        voice_ref_text: Optional[str] = None,
    ) -> np.ndarray:
        """
        运行 TTS 推理

        Args:
            text: 要合成的文本
            voice_ref_audio: 参考音频（声音克隆用）
            voice_ref_text: 参考文本（声音克隆用）

        Returns:
            音频数据 (float32 numpy array)
        """
        if not self._tts_session:
            raise RuntimeError("TTS 模型未加载")

        # 获取模型输入/输出名称
        input_names = [inp.name for inp in self._tts_session.get_inputs()]
        output_names = [out.name for out in self._tts_session.get_outputs()]

        # 准备输入
        # 注意：实际的输入格式取决于 MOSS-TTS-Nano 的 ONNX 导出方式
        # 这里是通用的 autoregressive TTS 输入模式
        input_dict = {}

        # 文本 token 化（简化处理，实际需要 sentencepiece tokenizer）
        text_tokens = self._text_to_tokens(text)

        for name in input_names:
            if "input_ids" in name or "text" in name or "token" in name:
                input_dict[name] = text_tokens
            elif "language" in name or "lang" in name:
                # 中文语言 ID
                input_dict[name] = np.array([1], dtype=np.int64)
            elif "prompt_audio" in name or "ref_audio" in name:
                if voice_ref_audio is not None:
                    input_dict[name] = voice_ref_audio
            elif "prompt_text" in name or "ref_text" in name:
                if voice_ref_text:
                    ref_tokens = self._text_to_tokens(voice_ref_text)
                    input_dict[name] = ref_tokens

        # 运行推理
        outputs = self._tts_session.run(output_names, input_dict)

        # 提取音频数据
        audio = outputs[0]
        if isinstance(audio, np.ndarray):
            # 确保是 1D 或 2D
            if audio.ndim > 2:
                audio = audio.squeeze()
            if audio.ndim == 1:
                audio = audio.reshape(-1, self._channels) if self._channels > 1 else audio.reshape(-1)

        return audio

    def _text_to_tokens(self, text: str) -> np.ndarray:
        """
        文本转 token IDs

        使用 sentencepiece 分词器，如果不可用则使用简单字符映射。
        """
        try:
            import sentencepiece as spm

            if not hasattr(self, "_sp"):
                # 查找 sentencepiece 模型文件
                sp_model = None
                for pattern in ["*.model", "sp_model.model", "tokenizer.model"]:
                    matches = list(self._model_dir.glob(pattern))
                    if matches:
                        sp_model = str(matches[0])
                        break

                if sp_model:
                    self._sp = spm.SentencePieceProcessor(model_file=sp_model)
                else:
                    self._sp = None

            if self._sp:
                tokens = self._sp.encode(text)
                return np.array([tokens], dtype=np.int64)
        except ImportError:
            pass

        # Fallback: 简单字符到 ID 映射
        tokens = [ord(c) % 30000 for c in text]
        return np.array([tokens], dtype=np.int64)

    async def synthesize(
        self,
        text: str,
        voice_ref_audio: Optional[bytes] = None,
        voice_ref_text: Optional[str] = None,
    ) -> bytes:
        """
        合成语音

        Args:
            text: 要合成的文本
            voice_ref_audio: 参考音频 WAV 字节（声音克隆用，~3秒）
            voice_ref_text: 参考文本（声音克隆用）

        Returns:
            WAV 格式的音频字节数据
        """
        if not self._initialized or not self._tts_session:
            logger.error("MOSSNanTTS 未初始化")
            return b""

        if not self.validate_text(text):
            return b""

        text = self._normalize_text(text)
        if not text:
            return b""

        start_time = time.time()

        try:
            # 处理参考音频
            ref_audio_np = None
            if voice_ref_audio is not None:
                ref_audio_np = self._load_audio_from_bytes(voice_ref_audio)

            # 在线程池中运行推理（避免阻塞事件循环）
            loop = asyncio.get_event_loop()
            audio_data = await loop.run_in_executor(
                None, self._run_inference, text, ref_audio_np, voice_ref_text
            )

            # 转换为 WAV 字节
            wav_bytes = _create_wav_bytes(
                audio_data,
                sample_rate=self._sample_rate,
                channels=self._channels,
            )

            # 更新统计
            inference_ms = (time.time() - start_time) * 1000
            duration_sec = len(audio_data) / self._sample_rate
            with self._lock:
                self._total_syntheses += 1
                self._total_duration_sec += duration_sec
                self._total_inference_ms += inference_ms

            logger.info(
                f"MOSSNanTTS 合成完成 | "
                f"文本={len(text)}字符 | "
                f"音频={duration_sec:.1f}秒 | "
                f"耗时={inference_ms:.0f}ms"
            )

            return wav_bytes

        except Exception as e:
            logger.error(f"MOSSNanTTS 合成失败: {e}", exc_info=True)
            return b""

    async def synthesize_stream(
        self,
        text: str,
        voice_ref_audio: Optional[bytes] = None,
        voice_ref_text: Optional[str] = None,
        chunk_size: int = 4800,
    ) -> AsyncGenerator[bytes, None]:
        """
        流式合成语音

        将长文本分块合成，每块 yield 一次。

        Args:
            text: 要合成的文本
            voice_ref_audio: 参考音频（声音克隆用）
            voice_ref_text: 参考文本（声音克隆用）
            chunk_size: 每个 chunk 的采样点数

        Yields:
            WAV 格式的音频数据块
        """
        if not self._initialized or not self._tts_session:
            logger.error("MOSSNanTTS 未初始化")
            return

        if not self.validate_text(text):
            return

        text = self._normalize_text(text)
        if not text:
            return

        try:
            # 处理参考音频
            ref_audio_np = None
            if voice_ref_audio is not None:
                ref_audio_np = self._load_audio_from_bytes(voice_ref_audio)

            # 运行推理
            loop = asyncio.get_event_loop()
            audio_data = await loop.run_in_executor(
                None, self._run_inference, text, ref_audio_np, voice_ref_text
            )

            # 转换为 int16
            if audio_data.dtype != np.float32:
                audio_data = audio_data.astype(np.float32)
            max_val = np.max(np.abs(audio_data))
            if max_val > 1.0:
                audio_data = audio_data / max_val
            audio_int16 = (audio_data * 32767).astype(np.int16)

            # 发送 WAV 头
            total_samples = len(audio_int16)
            data_size = total_samples * 2  # int16 = 2 bytes
            wav_header = _create_wav_bytes(
                np.zeros(0, dtype=np.float32),
                sample_rate=self._sample_rate,
                channels=self._channels,
            )
            # 只发头部（36 + 8 = 44 字节）
            yield wav_header[:44]

            # 分块发送音频数据
            flat_data = audio_int16.tobytes()
            for i in range(0, len(flat_data), chunk_size * 2 * self._channels):
                chunk = flat_data[i : i + chunk_size * 2 * self._channels]
                if chunk:
                    yield chunk
                await asyncio.sleep(0.01)  # 让出事件循环

            # 更新统计
            duration_sec = total_samples / self._sample_rate
            with self._lock:
                self._total_syntheses += 1
                self._total_duration_sec += duration_sec

            logger.info(f"MOSSNanTTS 流式合成完成 | {duration_sec:.1f}秒")

        except Exception as e:
            logger.error(f"MOSSNanTTS 流式合成失败: {e}", exc_info=True)

    def _load_audio_from_bytes(self, audio_bytes: bytes) -> np.ndarray:
        """从字节数据加载音频为 numpy 数组"""
        try:
            import soundfile as sf

            with io.BytesIO(audio_bytes) as buf:
                audio, sr = sf.read(buf, dtype="float32")

            # 重采样到目标采样率（如果需要）
            if sr != self._sample_rate:
                # 简单线性插值重采样
                duration = len(audio) / sr
                target_len = int(duration * self._sample_rate)
                indices = np.linspace(0, len(audio) - 1, target_len)
                audio = np.interp(indices, np.arange(len(audio)), audio).astype(np.float32)

            # 转为单声道（如果是立体声）
            if audio.ndim == 2:
                audio = audio.mean(axis=1)

            return audio

        except Exception as e:
            logger.warning(f"音频加载失败: {e}，返回静音")
            return np.zeros(self._sample_rate, dtype=np.float32)  # 1秒静音

    async def shutdown(self) -> None:
        """关闭引擎，释放资源"""
        self._tts_session = None
        self._tokenizer_session = None
        self._initialized = False
        logger.info(f"MOSSNanTTS 已关闭 | 统计: {self.stats}")
