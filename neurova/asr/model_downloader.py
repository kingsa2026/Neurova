# -*- coding: utf-8 -*-
"""ASR 模型下载器（补课 4.2，模式复制自 tts/model_downloader.py）。

whisper 模型经 openai-whisper 自带下载（~/.cache/whisper），本项目约定
模型统一落 models/asr/whisper——下载器用 huggingface 镜像不了 openai
whisper 的格式，故走 whisper.load_model(download_root=...) 的官方通道，
由本模块负责：目录约定 + 就绪探测 + 下载触发（load_model 本身带进度）。
"""
import threading
from pathlib import Path
from typing import Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

# 就绪判定文件（whisper.<size>.pt 落 download_root）
ASR_MODEL_REGISTRY = {
    "whisper-base": {
        "description": "OpenAI Whisper base（多语种 ASR，~140MB）",
        "download_root": "models/asr/whisper",
        "model_file": "base.pt",
        "size_hint": "~140MB",
    },
    "whisper-small": {
        "description": "OpenAI Whisper small（更高质量，~460MB）",
        "download_root": "models/asr/whisper",
        "model_file": "small.pt",
        "size_hint": "~460MB",
    },
    "whisper-tiny": {
        "description": "OpenAI Whisper tiny（最小，~72MB）",
        "download_root": "models/asr/whisper",
        "model_file": "tiny.pt",
        "size_hint": "~72MB",
    },
}

# FunASR Paraformer（中文优先，ModelScope 下载；补课 4.2 续）
FUNASR_MODEL_REGISTRY = {
    "paraformer-zh": {
        "description": "FunASR Paraformer-zh（中文 SOTA 非自回归，~350MB，标点/VAD 内建）",
        "model_id": "paraformer-zh",
        "cache_dir": "models/asr/funasr",
        "size_hint": "~350MB",
    },
}

# 默认模型：base（质量/体积平衡点）
DEFAULT_ASR_MODEL = "whisper-base"

_download_lock = threading.Lock()
_downloading: dict = {}


def get_asr_model_dir() -> Path:
    """项目约定的 whisper 模型目录（对齐 manager.py 的 models/asr/whisper）。"""
    root = Path(__file__).resolve().parent.parent.parent
    return root / "models" / "asr" / "whisper"


def is_model_ready(size: str = "base") -> bool:
    """探测指定尺寸模型是否已就绪（download_root 下存在 <size>.pt）。"""
    entry = ASR_MODEL_REGISTRY.get(f"whisper-{size}")
    if not entry:
        return False
    return (get_asr_model_dir() / entry["model_file"]).exists()


def ensure_model(size: str = "base", device: str = "cpu") -> Optional[object]:
    """确保模型就绪并返回 whisper 模型实例；失败返回 None（诚实降级）。

    download_root 传 get_asr_model_dir()——修复 whisper_engine 原实现
    model_dir 被忽略、模型散落 ~/.cache 的问题。下载本身由
    whisper.load_model 完成（进度打印到 stdout）。
    """
    import whisper

    key = f"whisper-{size}"
    if key not in ASR_MODEL_REGISTRY:
        logger.error("未知 ASR 模型: %s", key)
        return None

    root = get_asr_model_dir()
    root.mkdir(parents=True, exist_ok=True)

    with _download_lock:
        if _downloading.get(key):
            logger.info("ASR 模型 %s 下载进行中，等待", key)
        else:
            _downloading[key] = True
        try:
            model = whisper.load_model(size, device=device, download_root=str(root))
            logger.info("Whisper 模型就绪: %s @ %s", size, root)
            return model
        except Exception as e:
            logger.error("Whisper 模型下载/加载失败（诚实降级）: %s", e)
            return None
        finally:
            _downloading[key] = False
