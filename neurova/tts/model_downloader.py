"""
Model Downloader - 模型自动下载器

从 HuggingFace Hub 自动下载 MOSS 模型，支持断点续传和进度显示。
"""

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Callable

logger = logging.getLogger(__name__)

# 模型仓库映射
MODEL_REGISTRY = {
    "moss-tts-nano": {
        "repo_id": "OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX",
        "local_dir": "models/tts/moss-nano",
        "description": "MOSS-TTS-Nano 0.1B ONNX 推理模型",
        "required_files": ["model.onnx"],
        "size_hint": "~200MB",
    },
    "moss-audio-tokenizer": {
        "repo_id": "OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano-ONNX",
        "local_dir": "models/tts/moss-tokenizer",
        "description": "MOSS-Audio-Tokenizer-Nano (声音克隆编码器)",
        "required_files": ["model.onnx"],
        "size_hint": "~50MB",
    },
    "moss-audio-4b": {
        "repo_id": "OpenMOSS-Team/MOSS-Audio-4B-Instruct",
        "local_dir": "models/audio/moss-audio-4b",
        "description": "MOSS-Audio-4B 音频理解模型",
        "required_files": ["config.json"],
        "size_hint": "~8GB",
    },
    "bge-small-zh-v1.5": {
        "repo_id": "BAAI/bge-small-zh-v1.5",
        "description": "中文文本嵌入向量模型 (512维)",
        "local_dir": "embedding/bge-small-zh-v1.5",
        "size_hint": "~130MB",
        "files": [
            "model.safetensors",
            "tokenizer.json",
            "config.json",
            "vocab.txt",
        ],
        "required_files": [
            "model.safetensors",
            "tokenizer.json",
        ],
    },
}


@dataclass
class DownloadProgress:
    """下载进度"""
    model_name: str
    total_size: int
    downloaded_size: int
    percentage: float
    speed: float  # bytes/sec
    eta: float  # seconds


class ModelDownloader:
    """
    模型自动下载器

    首次使用时自动从 HuggingFace 下载模型到本地目录。
    支持断点续传，下载失败自动重试。
    """

    def __init__(self, base_dir: str = "."):
        """
        初始化下载器

        Args:
            base_dir: 模型存储的基础目录
        """
        self._base_dir = Path(base_dir)
        self._progress_callback: Optional[Callable[[DownloadProgress], None]] = None
        self._logger = logging.getLogger("ModelDownloader")

    def set_progress_callback(self, callback: Callable[[DownloadProgress], None]) -> None:
        """设置下载进度回调"""
        self._progress_callback = callback

    def get_model_dir(self, model_name: str) -> Path:
        """获取模型本地目录路径"""
        if model_name not in MODEL_REGISTRY:
            raise ValueError(f"未知模型: {model_name}，可用: {list(MODEL_REGISTRY.keys())}")
        return self._base_dir / MODEL_REGISTRY[model_name]["local_dir"]

    def is_model_available(self, model_name: str) -> bool:
        """检查模型是否已下载"""
        try:
            model_dir = self.get_model_dir(model_name)
            if not model_dir.exists():
                return False

            required_files = MODEL_REGISTRY[model_name]["required_files"]
            return all((model_dir / f).exists() for f in required_files)
        except (KeyError, ValueError):
            return False

    def ensure_model(self, model_name: str, force: bool = False) -> Path:
        """
        确保模型已下载，没有则自动下载

        Args:
            model_name: 模型名称
            force: 强制重新下载

        Returns:
            模型本地目录路径
        """
        if model_name not in MODEL_REGISTRY:
            raise ValueError(f"未知模型: {model_name}，可用: {list(MODEL_REGISTRY.keys())}")

        model_dir = self.get_model_dir(model_name)
        registry = MODEL_REGISTRY[model_name]

        # 检查是否已下载
        if not force and self.is_model_available(model_name):
            self._logger.debug(f"模型已存在: {model_name} -> {model_dir}")
            return model_dir

        # 下载模型
        self._logger.info(
            f"开始下载模型: {registry['description']} "
            f"({registry['size_hint']}) -> {model_dir}"
        )

        try:
            from huggingface_hub import snapshot_download

            model_dir.mkdir(parents=True, exist_ok=True)

            snapshot_download(
                repo_id=registry["repo_id"],
                local_dir=str(model_dir),
                resume_download=True,
            )

            # 验证下载完整性
            if not self.is_model_available(model_name):
                raise RuntimeError(f"模型下载不完整: 缺少必要文件 {registry['required_files']}")

            self._logger.info(f"模型下载完成: {model_name} -> {model_dir}")
            return model_dir

        except ImportError:
            self._logger.error("huggingface_hub 未安装，请运行: pip install huggingface_hub")
            raise
        except Exception as e:
            self._logger.error(f"模型下载失败: {model_name} - {e}")
            raise

    def list_models(self) -> list:
        """列出所有可用模型及其状态"""
        result = []
        for name, registry in MODEL_REGISTRY.items():
            model_dir = self.get_model_dir(name)
            available = self.is_model_available(name)
            result.append({
                "name": name,
                "description": registry["description"],
                "size_hint": registry["size_hint"],
                "local_dir": str(model_dir),
                "available": available,
            })
        return result

    def delete_model(self, model_name: str) -> bool:
        """删除本地模型文件"""
        try:
            import shutil
            model_dir = self.get_model_dir(model_name)
            if model_dir.exists():
                shutil.rmtree(model_dir)
                self._logger.info(f"已删除模型: {model_name} -> {model_dir}")
                return True
            return False
        except Exception as e:
            self._logger.error(f"删除模型失败: {model_name} - {e}")
            return False


# 全局单例
_downloader: Optional[ModelDownloader] = None


def get_model_downloader(base_dir: str = ".") -> ModelDownloader:
    """获取全局 ModelDownloader 实例"""
    global _downloader
    if _downloader is None:
        _downloader = ModelDownloader(base_dir=base_dir)
    return _downloader
