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
import json
import re
from neurova.core.logger import get_logger
import struct
import threading
import time
from pathlib import Path
from typing import AsyncGenerator, List, Optional

try:
    import numpy as np
except ImportError:
    np = None

from neurova.tts.base import TTSBase
from neurova.tts.model_downloader import ModelDownloader, get_model_downloader

logger = get_logger(__name__)


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

    # 空数组（流式路径用 0 长度数组造 44 字节 WAV 头）：跳过归一化直接出
    # data_size=0 的合法头——空数组做 np.max 会崩（zero-size reduction）
    if audio_data.size == 0:
        audio_int16 = np.zeros(0, dtype=np.int16)
    else:
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
    header.extend(struct.pack("<H", 1))  # PCM format
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
        model_dir: str = None,
        tokenizer_dir: str = None,
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
        self._model_dir = Path(model_dir) if model_dir else None
        self._tokenizer_dir = Path(tokenizer_dir) if tokenizer_dir else None
        self._sample_rate = sample_rate
        self._channels = channels
        self._auto_download = auto_download

        # 多图流水线 Session（对照官方 browser_poc_bundle.js 参照实现）：
        # prefill（全局 Transformer 预填）→ decode_step（KV-cache 自回归步进）
        # → local_fixed_sampled_frame（图内定参采样一帧 16 通道 token）
        # → codec decode_full（音频 token → 48kHz 双声道波形）
        self._prefill_session = None
        self._decode_session = None
        self._local_frame_session = None
        self._codec_decode_session = None
        self._codec_encode_session = None  # 声音克隆用（参考音频 → codes）
        self._manifest: Optional[dict] = None
        self._sp = None
        self._builtin_prompt_codes: Optional[List[List[int]]] = None
        self._downloader: Optional[ModelDownloader] = None
        self._lock = threading.Lock()

        # 推理统计
        self._total_syntheses = 0
        self._total_duration_sec = 0.0
        self._total_inference_ms = 0.0

    @property
    def stats(self) -> dict:
        """推理统计"""
        avg_ms = self._total_inference_ms / self._total_syntheses if self._total_syntheses > 0 else 0
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
        2. 加载 prefill/decode_step/local_fixed_sampled_frame/codec 四张 ONNX 图
        3. 预热 + 能力自检（一次最小真实推理）
        """
        try:
            self._downloader = get_model_downloader()

            # 设置默认模型路径（如果未指定）
            if self._model_dir is None:
                self._model_dir = self._downloader.get_model_dir("moss-tts-nano")
            if self._tokenizer_dir is None:
                self._tokenizer_dir = self._downloader.get_model_dir("moss-audio-tokenizer")

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
                    logger.error("模型不存在: %s", self._model_dir)
                    return False

            # 加载 ONNX Runtime
            try:
                import onnxruntime as ort

                self._ort = ort
            except ImportError:
                logger.error("onnxruntime 未安装，请运行: pip install onnxruntime")
                return False

            session_opts = ort.SessionOptions()
            session_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            session_opts.inter_op_num_threads = 4
            session_opts.intra_op_num_threads = 4

            def _load(model_dir: Path, filename: str):
                path = model_dir / filename
                if not path.exists():
                    return None
                return ort.InferenceSession(str(path), sess_options=session_opts)

            # 四图流水线：任何一张缺失 = 引擎不可用（对照 meta.files 命名）
            self._manifest = self._load_manifest()
            if self._manifest is None:
                logger.error("tts_browser_onnx_meta.json/browser_poc_manifest.json 加载失败: %s", self._model_dir)
                return False
            self._prefill_session = _load(self._model_dir, "moss_tts_prefill.onnx")
            self._decode_session = _load(self._model_dir, "moss_tts_decode_step.onnx")
            self._local_frame_session = _load(self._model_dir, "moss_tts_local_fixed_sampled_frame.onnx")
            codec_dir = self._tokenizer_dir if self._tokenizer_dir else self._model_dir
            self._codec_decode_session = _load(codec_dir, "moss_audio_tokenizer_decode_full.onnx")
            missing = [
                name
                for name, sess in [
                    ("prefill", self._prefill_session),
                    ("decode_step", self._decode_session),
                    ("local_fixed_sampled_frame", self._local_frame_session),
                    ("codec_decode_full", self._codec_decode_session),
                ]
                if sess is None
            ]
            if missing:
                logger.error("MOSS ONNX 图缺失: %s（目录: %s）", missing, self._model_dir)
                return False

            # sentencepiece 文本前端（官方 tokenizer.model；加载失败降级字符映射）
            self._load_sentencepiece()

            # Tokenizer 编码图（声音克隆用，可选）
            encode_path = codec_dir / "moss_audio_tokenizer_encode.onnx"
            if encode_path.exists():
                try:
                    self._codec_encode_session = ort.InferenceSession(str(encode_path), sess_options=session_opts)
                except Exception as e:
                    logger.warning("codec encode 加载失败（声音克隆不可用）: %s", e)

            self._initialized = True

            # 预热 + 能力自检：模型加载成功 ≠ 推理可驱动。自检失败 = 诚实
            # 上报初始化失败，交由 manager fallback 链选下一个引擎。
            if not self._probe_inference_capability():
                logger.error(
                    "MOSSNanTTS 能力自检失败：推理无法产出音频，引擎标记为不可用"
                )
                self._initialized = False
                await self.shutdown()
                return False

            logger.info(
                f"MOSSNanTTS 初始化完成 | "
                f"采样率={self._sample_rate} | "
                f"声道={self._channels} | "
                f"内置音色={'OK' if self._builtin_prompt_codes else 'N/A'}"
            )
            return True

        except Exception as e:
            logger.error(f"MOSSNanTTS 初始化失败: {e}", exc_info=True)
            return False

    def _load_manifest(self) -> Optional[dict]:
        """加载 TTS meta + browser POC manifest（合并视图），失败返回 None。"""
        try:
            meta_path = self._model_dir / "tts_browser_onnx_meta.json"
            manifest_path = self._model_dir / "browser_poc_manifest.json"
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self._tts_meta = meta
            self._manifest = manifest
            return manifest
        except Exception as e:
            logger.error("manifest 加载失败: %s", e)
            return None

    def _ensure_manifest(self) -> bool:
        """懒加载 manifest（行构造/音色 codes 在未 initialize 时也可用）。"""
        if self._manifest is None and self._model_dir is not None:
            self._load_manifest()
        return self._manifest is not None

    def _load_builtin_prompt_codes(self) -> Optional[List[List[int]]]:
        """加载内置音色的预计算参考音频 codes（manifest.builtin_voices[0]）。"""
        if self._builtin_prompt_codes is not None:
            return self._builtin_prompt_codes
        if not self._ensure_manifest():
            return None
        try:
            voices = self._manifest.get("builtin_voices") or []
            for voice in voices:
                codes = voice.get("prompt_audio_codes")
                if codes:
                    self._builtin_prompt_codes = [[int(v) for v in row] for row in codes]
                    return self._builtin_prompt_codes
        except Exception as e:
            logger.warning("内置音色 codes 加载失败: %s", e)
        return None

    def _load_sentencepiece(self) -> None:
        """加载 sentencepiece 文本分词器；失败降级字符映射（_text_to_tokens 兜底）。"""
        try:
            import sentencepiece as spm

            sp_model = self._model_dir / "tokenizer.model"
            if sp_model.exists():
                self._sp = spm.SentencePieceProcessor()
                self._sp.LoadFromSerializedProto(sp_model.read_bytes())
                logger.info("sentencepiece 分词器加载完成")
                return
        except Exception as e:
            logger.warning("sentencepiece 加载失败（降级字符映射）: %s", e)
        self._sp = None

    def _probe_inference_capability(self) -> bool:
        """
        能力自检：跑一次最小真实推理，验证引擎真能产出非空音频。

        Returns:
            True=推理链路可用；False=推理崩/产出空（模型与实现契约错位）
        """
        if not self._prefill_session:
            return False
        try:
            audio = self._run_inference("测试")
            return audio is not None and audio.size > 0
        except Exception as e:
            logger.warning("能力自检推理失败: %s", e)
            return False

    def _normalize_text(self, text: str) -> str:
        """
        文本预处理

        处理数字、符号等，使其适合 TTS 引擎。
        """
        # 基础清理
        text = text.strip()
        if not text:
            return ""

        # 移除连续的特殊字符
        text = re.sub(r"[^\w\s\u4e00-\u9fff.,!?，。！？、；：\u201c\u201d\u2018\u2019（）【】《》\\-]", " ", text)

        # 合并多余空格
        text = re.sub(r"\s+", " ", text).strip()

        # 对照官方 prepareTextForSentenceChunking：中文缺句末标点补句号，
        # 否则模型倾向不终止
        if text and re.search(r"[\u4e00-\u9fff]", text) and text[-1] not in "。！？!?；;.":
            text += "。"

        return text

    # ---- 推理流水线（对照 OpenMOSS/MOSS-TTS-Nano-Reader browser_poc_bundle.js）----

    def _tts_config(self) -> dict:
        self._ensure_manifest()
        cfg = dict(self._manifest.get("tts_config") or {}) if self._manifest else {}
        cfg.setdefault("n_vq", 16)
        cfg.setdefault("audio_pad_token_id", 1024)
        cfg.setdefault("audio_start_token_id", 6)
        cfg.setdefault("audio_end_token_id", 7)
        cfg.setdefault("audio_user_slot_token_id", 8)
        cfg.setdefault("audio_assistant_slot_token_id", 9)
        return cfg

    def _generation_defaults(self) -> dict:
        self._ensure_manifest()
        defaults = dict(self._manifest.get("generation_defaults") or {}) if self._manifest else {}
        defaults.setdefault("max_new_frames", 375)
        return defaults

    def _prompt_templates(self) -> dict:
        self._ensure_manifest()
        return (self._manifest.get("prompt_templates") or {}) if self._manifest else {}

    def _text_rows(self, token_ids, row_width: int, pad_id: int) -> List[List[int]]:
        return [[int(t)] + [pad_id] * (row_width - 1) for t in token_ids]

    def _audio_prefix_rows(self, prompt_codes, row_width: int, pad_id: int, slot_id: int, n_vq: int) -> List[List[int]]:
        rows = []
        for code_row in prompt_codes:
            row = [pad_id] * row_width
            row[0] = slot_id
            for i in range(min(len(code_row), n_vq)):
                row[i + 1] = int(code_row[i])
            rows.append(row)
        return rows

    def _build_request_rows(self, text_token_ids, prompt_codes) -> List[List[int]]:
        """构造 prefill 请求行（buildVoiceCloneRequestRows 参照移植）。"""
        cfg = self._tts_config()
        pt = self._prompt_templates()
        row_width = cfg["n_vq"] + 1
        pad_id = cfg["audio_pad_token_id"]

        prefix_ids = list(pt.get("user_prompt_prefix_token_ids") or []) + [cfg["audio_start_token_id"]]
        suffix_ids = (
            [cfg["audio_end_token_id"]]
            + list(pt.get("user_prompt_after_reference_token_ids") or [])
            + list(text_token_ids)
            + list(pt.get("assistant_prompt_prefix_token_ids") or [])
            + [cfg["audio_start_token_id"]]
        )
        rows = self._text_rows(prefix_ids, row_width, pad_id)
        rows += self._audio_prefix_rows(
            prompt_codes, row_width, pad_id, cfg["audio_user_slot_token_id"], cfg["n_vq"]
        )
        rows += self._text_rows(suffix_ids, row_width, pad_id)
        return rows

    def _split_text_chunks(self, text: str, max_tokens: int = 75) -> List[str]:
        """按句切分并打包到 token 预算内（splitVoiceCloneText 简化移植）。

        参考实现 75 token/块（max_new_frames=375 ≈ 30s 音频预算）。
        """
        text = text.strip()
        if not text:
            return []
        sentences = re.findall(r"[^。！？!?.；;\n]*[。！？!?.；;\n]+|[^。！？!?.；;\n]+$", text)
        sentences = [s.strip() for s in sentences if s.strip()]
        if not sentences:
            sentences = [text]

        def _count(s: str) -> int:
            return len(self._text_to_tokens(s)) if self._sp else len(s)

        chunks: List[str] = []
        current = ""
        current_len = 0
        for sentence in sentences:
            sent_len = _count(sentence)
            if sent_len > max_tokens:
                # 单句超预算：token 化后按预算硬切，再解码回文本
                if current:
                    chunks.append(current)
                    current, current_len = "", 0
                ids = self._text_to_tokens(sentence)
                step = max_tokens
                pieces = [
                    self._sp.decode(ids[i : i + step]) if self._sp else sentence[i : i + step]
                    for i in range(0, len(ids), step)
                ]
                chunks.extend(p for p in pieces if p.strip())
                continue
            if current_len + sent_len > max_tokens:
                chunks.append(current)
                current, current_len = sentence, sent_len
            else:
                current += sentence
                current_len += sent_len
        if current:
            chunks.append(current)
        return chunks or [text]

    def _extract_last_hidden(self, global_hidden) -> "np.ndarray":
        if global_hidden.ndim == 3:
            return global_hidden[:, -1, :]
        return global_hidden

    def _synthesize_chunk(self, text: str, prompt_codes) -> "np.ndarray":
        """合成单个文本块 → float32 (N, channels) 波形（声道交错就绪）。"""
        cfg = self._tts_config()
        n_vq = cfg["n_vq"]
        pad_id = cfg["audio_pad_token_id"]
        assistant_slot = cfg["audio_assistant_slot_token_id"]
        codebook_size = int(self._tts_meta["model_config"]["audio_codebook_sizes"][0])
        max_new_frames = self._generation_defaults()["max_new_frames"]

        rows = self._build_request_rows(self._text_to_tokens(text), prompt_codes)
        input_ids = np.array([rows], dtype=np.int32)
        attention_mask = np.ones((1, len(rows)), dtype=np.int32)
        prefill_out = self._prefill_session.run(
            None, {"input_ids": input_ids, "attention_mask": attention_mask}
        )
        prefill_names = {o.name: prefill_out[i] for i, o in enumerate(self._prefill_session.get_outputs())}
        global_hidden = self._extract_last_hidden(prefill_names["global_hidden"])
        past_valid_length = len(rows)

        # KV-cache 名单按位置映射（参照 updateDecodePastFeeds）：
        # decode 输入去掉前两个（input_ids/past_valid_lengths），输出去掉
        # global_hidden，其余 present_i ↔ past_i 一一对应。
        # 注意 past_valid_lengths 虽以 past_ 开头但不是 KV-cache 张量。
        decode_input_names = [i.name for i in self._decode_session.get_inputs()]
        decode_output_names = [o.name for o in self._decode_session.get_outputs()]
        kv_past_names = decode_input_names[2:]
        kv_present_names = decode_output_names[1:]

        frames: List[List[int]] = []
        seen = np.zeros((1, n_vq, codebook_size), dtype=np.int32)
        for _step in range(max_new_frames):
            # local_fixed_sampled_frame：图内定参采样一帧 16 通道 token
            local_out = self._local_frame_session.run(
                None,
                {
                    "global_hidden": global_hidden,
                    "repetition_seen_mask": seen,
                    "assistant_random_u": np.random.uniform(size=(1,)).astype(np.float32),
                    "audio_random_u": np.random.uniform(size=(1, n_vq)).astype(np.float32),
                },
            )
            local_names = {o.name: local_out[i] for i, o in enumerate(self._local_frame_session.get_outputs())}
            if int(local_names["should_continue"].reshape(-1)[0]) <= 0:
                break
            frame = local_names["frame_token_ids"].reshape(-1)[:n_vq].tolist()
            frames.append(frame)
            for ch, tok in enumerate(frame):
                seen[0, ch, tok] = 1

            # decode_step：喂一帧 assistant 行，KV-cache 推进全局隐状态
            row = np.full((1, 1, n_vq + 1), pad_id, dtype=np.int32)
            row[0, 0, 0] = assistant_slot
            row[0, 0, 1:] = frame
            feeds = {"input_ids": row, "past_valid_lengths": np.array([past_valid_length], dtype=np.int32)}
            for past_name, present_name in zip(kv_past_names, kv_present_names):
                feeds[past_name] = prefill_names[present_name]
            decode_out = self._decode_session.run(None, feeds)
            decode_names = {o.name: decode_out[i] for i, o in enumerate(self._decode_session.get_outputs())}
            global_hidden = self._extract_last_hidden(decode_names["global_hidden"])
            for past_name, present_name in zip(kv_past_names, kv_present_names):
                prefill_names[present_name] = decode_names[present_name]
            past_valid_length += 1

        if not frames:
            logger.warning("MOSSNanTTS 未生成任何音频帧: %s", text[:20])
            return np.zeros((0, self._channels), dtype=np.float32)

        # codec 解码：codes (1, T, 16) → 波形 (1, 2, N) 通道主序
        codes = np.array([frames], dtype=np.int32)
        code_lengths = np.array([len(frames)], dtype=np.int32)
        codec_out = self._codec_decode_session.run(
            None, {"audio_codes": codes, "audio_code_lengths": code_lengths}
        )
        codec_names = {o.name: codec_out[i] for i, o in enumerate(self._codec_decode_session.get_outputs())}
        audio = codec_names["audio"]
        n_samples = int(codec_names["audio_lengths"].reshape(-1)[0])
        return audio[0, :, :n_samples].T.astype(np.float32)  # (N, 2) 交错就绪

    def _encode_reference_audio(self, audio_bytes: bytes) -> Optional[List[List[int]]]:
        """参考音频（可解码音频格式）→ codec codes，供声音克隆前缀行。"""
        if self._codec_encode_session is None:
            logger.warning("codec encode 图不可用，声音克隆降级为内置音色")
            return None
        ref = self._load_audio_from_bytes(audio_bytes)
        if ref is None or len(ref) == 0:
            return None
        # 上限 ~8s（参考实现按句级 3~10s 参考）
        max_samples = 8 * self._sample_rate
        if len(ref) > max_samples:
            ref = ref[:max_samples]
        wave = np.stack([ref, ref], axis=0).astype(np.float32)  # (2, N) 单声道复制
        out = self._codec_encode_session.run(
            None,
            {
                "waveform": wave[np.newaxis, ...],
                "input_lengths": np.array([wave.shape[1]], dtype=np.int32),
            },
        )
        names = {o.name: out[i] for i, o in enumerate(self._codec_encode_session.get_outputs())}
        codes_t = names["audio_codes"]  # (1, T, 16)
        code_len = int(names["audio_code_lengths"].reshape(-1)[0])
        return codes_t[0, :code_len, :].tolist()

    def _resolve_prompt_codes(self, voice_ref_audio: Optional[bytes]) -> List[List[int]]:
        """声音克隆优先；无参考音频用内置音色。"""
        if voice_ref_audio is not None:
            codes = self._encode_reference_audio(voice_ref_audio)
            if codes:
                return codes
        builtin = self._load_builtin_prompt_codes()
        if not builtin:
            raise RuntimeError("无内置音色 codes 且声音克隆不可用，无法构造音频前缀")
        return builtin

    def _run_inference(
        self,
        text: str,
        voice_ref_audio: Optional[np.ndarray] = None,
        voice_ref_text: Optional[str] = None,
    ) -> np.ndarray:
        """
        运行 TTS 推理（多图流水线；长文本按句切块后拼 Pause 静音）

        Args:
            text: 要合成的文本
            voice_ref_audio: 参考音频（声音克隆用；None=内置音色）
            voice_ref_text: 参考文本（兼容保留，本流水线未使用）

        Returns:
            float32 (N, channels) 波形（声道交错就绪）
        """
        if not self._prefill_session or not self._decode_session or not self._local_frame_session:
            raise RuntimeError("TTS 模型未加载")

        prompt_codes = self._resolve_prompt_codes(voice_ref_audio)
        chunks = self._split_text_chunks(text)
        if not chunks:
            return np.zeros((0, self._channels), dtype=np.float32)

        start_time = time.time()
        pieces: List[np.ndarray] = []
        for chunk in chunks:
            piece = self._synthesize_chunk(chunk, prompt_codes)
            if len(piece):
                pieces.append(piece)

        if not pieces:
            return np.zeros((0, self._channels), dtype=np.float32)

        # 块间插静音（参考实现长停顿 0.24s）
        pause = np.zeros((int(0.24 * self._sample_rate), self._channels), dtype=np.float32)
        audio = pieces[0]
        for piece in pieces[1:]:
            audio = np.concatenate([audio, pause, piece], axis=0)

        inference_ms = (time.time() - start_time) * 1000
        logger.info(
            "MOSSNanTTS 推理完成 | 文本=%d字符%d块 | 音频=%.1f秒 | 耗时=%.0fms",
            len(text), len(chunks), len(audio) / self._sample_rate, inference_ms,
        )
        return audio

    def _text_to_tokens(self, text: str) -> List[int]:
        """
        文本转 token IDs（sentencepiece；加载失败降级字符映射）
        """
        if self._sp is not None:
            return list(self._sp.encode(text))
        # Fallback: 简单字符到 ID 映射（仅保命，音质无意义）
        return [ord(c) % 30000 for c in text]

    async def synthesize(
        self,
        text: str,
        voice_ref_audio: Optional[bytes] = None,
        voice_ref_text: Optional[str] = None,
        **kwargs,
    ) -> bytes:
        """
        合成语音

        Args:
            text: 要合成的文本
            voice_ref_audio: 参考音频 WAV 字节（声音克隆用，~3秒）
            voice_ref_text: 参考文本（声音克隆用）
            **kwargs: 上游语义参数（voice/speed 等）。本引擎无音色/语速
                概念，忽略——签名收紧会在参数绑定阶段 TypeError，炸穿
                manager fallback 链（manager 按 TTSBase 宽契约透传 kwarg）。

        Returns:
            WAV 格式的音频字节数据
        """
        if not self._initialized or not self._prefill_session:
            logger.error("MOSSNanTTS 未初始化")
            return b""

        if not self.validate_text(text):
            return b""

        text = self.sanitize_text(text)
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
            audio_data = await loop.run_in_executor(None, self._run_inference, text, ref_audio_np, voice_ref_text)

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
        **kwargs,
    ) -> AsyncGenerator[bytes, None]:
        """
        流式合成语音

        将长文本分块合成，每块 yield 一次。

        Args:
            text: 要合成的文本
            voice_ref_audio: 参考音频（声音克隆用）
            voice_ref_text: 参考文本（声音克隆用）
            chunk_size: 每个 chunk 的采样点数
            **kwargs: 上游语义参数（voice/speed 等），同 synthesize 忽略

        Yields:
            WAV 格式的音频数据块
        """
        if not self._initialized or not self._prefill_session:
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
            audio_data = await loop.run_in_executor(None, self._run_inference, text, ref_audio_np, voice_ref_text)
            if len(audio_data) == 0:
                # 空产出按失败处理：让管理器流式 fallback 接管
                raise RuntimeError("推理未产出音频帧")

            # 本引擎是伪流式（全量合成完成后再分块下发），必须用真实数据
            # 构造完整合法 WAV——此前用 zeros(0) 造假头，data_size=0，严格
            # 解析器（soundfile/部分播放器）判定时长 0 → "音频为空"。
            wav_bytes = _create_wav_bytes(
                audio_data,
                sample_rate=self._sample_rate,
                channels=self._channels,
            )

            # 分块发送（首块含 WAV 头）
            step = chunk_size * 2 * self._channels
            for i in range(0, len(wav_bytes), step):
                chunk = wav_bytes[i : i + step]
                if chunk:
                    yield chunk
                await asyncio.sleep(0.01)  # 让出事件循环

            # 更新统计
            duration_sec = len(audio_data) / self._sample_rate
            with self._lock:
                self._total_syntheses += 1
                self._total_duration_sec += duration_sec

            logger.info("MOSSNanTTS 流式合成完成 | %.1f秒", duration_sec)

        except Exception as e:
            logger.error(f"MOSSNanTTS 流式合成失败: {e}", exc_info=True)
            # 失败必须冒泡：管理器流式 fallback 依赖异常信号；静默空产出
            # 会让流式端点返回 200+0 字节（前端 0 字节 blob → <audio> 416）。
            raise RuntimeError(f"MOSSNanTTS 流式合成失败: {e}") from e

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
            logger.warning("音频加载失败: %s，返回静音", e)
            return np.zeros(self._sample_rate, dtype=np.float32)  # 1秒静音

    async def shutdown(self) -> None:
        """关闭引擎，释放资源"""
        self._prefill_session = None
        self._decode_session = None
        self._local_frame_session = None
        self._codec_decode_session = None
        self._codec_encode_session = None
        self._initialized = False
        logger.info("MOSSNanTTS 已关闭 | 统计: %s", self.stats)
