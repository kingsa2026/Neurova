"""
Model Downloader - 模型自动下载器

从 HuggingFace Hub 自动下载 MOSS 模型，支持断点续传和进度显示。
"""

import logging

from neurova.core.logger import get_logger
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

logger = get_logger(__name__)

# 模型仓库映射
MODEL_REGISTRY = {
    "moss-tts-nano": {
        "repo_id": "OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX",
        "local_dir": "models/tts/moss-nano",
        "description": "MOSS-TTS-Nano 0.1B ONNX 推理模型",
        # 仓库实际是 5 图级联（prefill/decode_step/local_cached_step/
        # local_decoder/local_fixed_sampled_frame）+ 2 份 .data 共享权重，
        # 旧契约的 model.onnx 在仓库不存在——导致 is_model_available 恒
        # False、ensure_model 恒报"下载不完整"，模型已下载也无法初始化
        "required_files": [
            "moss_tts_prefill.onnx",
            "moss_tts_decode_step.onnx",
            "moss_tts_local_cached_step.onnx",
            "moss_tts_local_decoder.onnx",
            "moss_tts_local_fixed_sampled_frame.onnx",
            "moss_tts_global_shared.data",
            "moss_tts_local_shared.data",
            "tokenizer.model",
        ],
        "size_hint": "~200MB",
        # ModelScope 官方 ONNX 镜像（2026-09-06 实证 13 文件与 HF 对齐，
        # required_files 全覆盖）——国内首选源
        "ms_repo_id": "OpenMOSS/MOSS-TTS-Nano-100M-ONNX",
    },
    "moss-audio-tokenizer": {
        "repo_id": "OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano-ONNX",
        "local_dir": "models/tts/moss-tokenizer",
        "description": "MOSS-Audio-Tokenizer-Nano (声音克隆编码器)",
        # 同样无 model.onnx：实际是 encode/decode 双端 onnx + .data 权重。
        # 声音克隆是可选功能，不齐时 ensure_model 抛错只降级克隆能力
        "required_files": [
            "moss_audio_tokenizer_encode.onnx",
            "moss_audio_tokenizer_encode.data",
            "moss_audio_tokenizer_decode_step.onnx",
            "moss_audio_tokenizer_decode_shared.data",
        ],
        "size_hint": "~50MB",
        # ModelScope 官方 ONNX 镜像（9 文件，encode/decode 权重齐全）
        "ms_repo_id": "OpenMOSS/MOSS-Audio-Tokenizer-Nano-ONNX",
    },
    "bge-small-zh-v1.5": {
        "repo_id": "BAAI/bge-small-zh-v1.5",
        # ModelScope 官方镜像（实测 14 文件与 HF 对齐，国内直连硬可靠）
        "ms_repo_id": "AI-ModelScope/bge-small-zh-v1.5",
        "description": "中文文本嵌入向量模型 (512维)",
        "local_dir": "models/embedding/bge-small-zh-v1.5",
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

    def ensure_model(self, model_name: str, force: bool = False, source: str = "auto") -> Path:
        """
        确保模型已下载，没有则自动下载

        Args:
            model_name: 模型名称
            force: 强制重新下载
            source: 下载源 auto|modelscope|huggingface。
                auto = ModelScope（有镜像时）→ hf-mirror → HF 直连 依次降级；
                显式指定源失败不换源（用户选择必须被尊重）。

        Returns:
            模型本地目录路径
        """
        if model_name not in MODEL_REGISTRY:
            raise ValueError(f"未知模型: {model_name}，可用: {list(MODEL_REGISTRY.keys())}")
        if source not in ("auto", "modelscope", "huggingface"):
            raise ValueError(f"非法下载源: {source!r}，合法值: auto/modelscope/huggingface")

        model_dir = self.get_model_dir(model_name)
        registry = MODEL_REGISTRY[model_name]

        # 检查是否已下载
        if not force and self.is_model_available(model_name):
            self._logger.debug("模型已存在: %s -> %s", model_name, model_dir)
            return model_dir

        # 下载模型（按源解析出引擎序列，依次尝试）
        self._logger.info("开始下载模型: %s " f"(%s -> %s) -> %s", registry['description'], source, registry['size_hint'], model_dir)

        engine_errors: list[str] = []
        progress_cb = _wrap_progress(model_name, self._progress_callback)
        for engine in _resolve_engines(source, registry):
            try:
                engine(registry, model_dir, progress_cb)
                break
            except Exception as e:  # noqa: BLE001 - 单源失败降级下一源
                engine_errors.append(f"{getattr(engine, '__name__', engine)}: {e}")
                self._logger.warning("下载源失败，尝试下一源: %s", e)
        else:
            raise RuntimeError(
                f"所有下载源均失败: {'; '.join(engine_errors)}"
            )

        # 完整性校验（引擎已负责下载与进度；此处统一验证 required_files）
        if not self.is_model_available(model_name):
            raise RuntimeError(f"模型下载不完整: 缺少必要文件 {registry['required_files']}")

        self._logger.info("模型下载完成: %s -> %s", model_name, model_dir)
        return model_dir

        # 完整性校验（引擎已负责下载与进度；此处统一验证 required_files）
        if not self.is_model_available(model_name):
            raise RuntimeError(f"模型下载不完整: 缺少必要文件 {registry['required_files']}")

        self._logger.info("模型下载完成: %s -> %s", model_name, model_dir)
        return model_dir

    def pending_downloads(self) -> list:
        """待下载清单（模型缺失项），供前端渲染下载提示框。"""
        return [
            {
                "model": name,
                "description": registry["description"],
                "size_hint": registry["size_hint"],
                "available": self.is_model_available(name),
                "has_ms_mirror": bool(registry.get("ms_repo_id")),
            }
            for name, registry in MODEL_REGISTRY.items()
            if not self.is_model_available(name)
        ]

    def list_models(self) -> list:
        """列出所有可用模型及其状态"""
        result = []
        for name, registry in MODEL_REGISTRY.items():
            model_dir = self.get_model_dir(name)
            available = self.is_model_available(name)
            result.append(
                {
                    "name": name,
                    "description": registry["description"],
                    "size_hint": registry["size_hint"],
                    "local_dir": str(model_dir),
                    "available": available,
                }
            )
        return result

    def delete_model(self, model_name: str) -> bool:
        """删除本地模型文件"""
        try:
            import shutil

            model_dir = self.get_model_dir(model_name)
            if model_dir.exists():
                shutil.rmtree(model_dir)
                self._logger.info("已删除模型: %s -> %s", model_name, model_dir)
                return True
            return False
        except Exception as e:
            self._logger.error("删除模型失败: %s - %s", model_name, e)
            return False


# 全局单例
_downloader: Optional[ModelDownloader] = None


def _wrap_progress(model_name: str, raw_cb):
    """把 (current, total) 风格的引擎回调包装成 DownloadProgress 推送。

    各引擎统一用 (current_bytes, total_bytes) 上报；total 未知传 0。
    """
    if raw_cb is None:
        return None

    def cb(current: int, total: int = 0):
        try:
            total_i = int(total or 0)
            pct = min(100.0, current / total_i * 100.0) if total_i > 0 else 0.0
            raw_cb(
                DownloadProgress(
                    model_name=model_name,
                    total_size=total_i,
                    downloaded_size=int(current),
                    percentage=pct,
                    speed=0.0,
                    eta=0.0,
                )
            )
        except Exception:
            pass

    return cb


def _resolve_engines(source: str, registry: dict) -> list:
    """把 source 解析为引擎函数序列（依次尝试，前败后继）。

    - auto: ModelScope（registry.ms_repo_id 存在时）→ hf-mirror → HF 直连
    - modelscope / huggingface: 仅指定引擎（用户显式选择失败不换源）
    """
    if source == "modelscope":
        if not registry.get("ms_repo_id"):
            raise ValueError(
                f"该模型无 ModelScope 镜像: {registry.get('repo_id')}（国内源将走 hf-mirror）"
            )
        return [_download_via_modelscope]
    if source == "huggingface":
        return [_download_via_huggingface]
    # auto
    engines: list = []
    if registry.get("ms_repo_id"):
        engines.append(_download_via_modelscope)
    engines.append(_download_via_hf_mirror)
    engines.append(_download_via_huggingface)
    return engines


def _with_progress_polling(model_dir: Path, download_fn) -> None:
    """下载执行 + 目录体积轮询推送进度（各引擎共用的进度壳）。

    下载函数异常时停止轮询后原样抛出；进度失败绝不影响下载本身。
    """
    import threading
    import time

    stop_event = threading.Event()

    def _poll_progress():
        while not stop_event.is_set():
            try:
                current_size = _dir_size(model_dir)
                if download_fn.progress_callback:
                    download_fn.progress_callback(
                        DownloadProgress(
                            model_name=download_fn.model_name,
                            total_size=max(current_size, 1),
                            downloaded_size=current_size,
                            percentage=0.0,  # 体积未知时恒 0（MS 镜像无 size_hint）
                            speed=0.0,
                            eta=0.0,
                        )
                    )
            except Exception:
                pass
            stop_event.wait(0.5)

    poll_thread = threading.Thread(target=_poll_progress, daemon=True)
    poll_thread.start()
    try:
        download_fn()
    finally:
        stop_event.set()
        poll_thread.join(timeout=1.0)


def _download_via_modelscope(registry: dict, model_dir: Path, progress_cb=None) -> None:
    """ModelScope 源（国内直连硬可靠；仅 registry.ms_repo_id 存在时启用）。"""
    from modelscope import snapshot_download as ms_snapshot

    ms_snapshot(
        model_id=registry["ms_repo_id"],
        local_dir=str(model_dir),
    )


def _download_via_hf_mirror(registry: dict, model_dir: Path, progress_cb=None) -> None:
    """hf-mirror.com 源：HF 协议代理镜像（国内尽力而为——LFS 大文件会
    308 跳回 huggingface.co 的 Xet CDN，无代理网络可能失败）。

    实现走 huggingface_hub 但临时切 HF_ENDPOINT；hf_hub 1.x 与镜像的
    API 协议不兼容（实测 LocalEntryNotFoundError），因此直接用
    requests 拉直链清单 + 文件，不依赖 hf_hub 的镜像兼容性。
    """
    import requests

    repo = registry["repo_id"]
    base = f"https://hf-mirror.com/{repo}/resolve/main/"
    files = registry.get("required_files") or registry.get("files") or []
    if not files:
        # 无清单时退回 hf_hub（配置镜像端点；可能因 1.x 协议不兼容失败）
        import os

        old = os.environ.get("HF_ENDPOINT")
        os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
        try:
            from huggingface_hub import snapshot_download

            snapshot_download(repo_id=repo, local_dir=str(model_dir), resume_download=True)
        finally:
            if old is None:
                os.environ.pop("HF_ENDPOINT", None)
            else:
                os.environ["HF_ENDPOINT"] = old
        return

    model_dir.mkdir(parents=True, exist_ok=True)
    import urllib.request

    for fname in files:
        dest = model_dir / fname
        if dest.exists() and dest.stat().st_size > 0:
            continue  # 断点续传粒度：文件级
        req = urllib.request.Request(
            base + fname, headers={"User-Agent": "Neurova/1.0"}
        )
        with urllib.request.urlopen(req, timeout=300) as resp, open(dest, "wb") as f:
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)


def _download_via_huggingface(registry: dict, model_dir: Path, progress_cb=None) -> None:
    """HuggingFace 直连源（huggingface_hub 官方协议）。"""
    from huggingface_hub import snapshot_download

    snapshot_download(
        repo_id=registry["repo_id"],
        local_dir=str(model_dir),
        resume_download=True,
        tqdm_class=None,
    )


def _parse_size_hint(size_hint: str) -> int:
    """解析形如 '~130MB' / '~8GB' 的体积字符串为字节数。

    Returns:
        字节数；解析失败返回 0。
    """
    try:
        s = size_hint.strip().lower().lstrip("~")
        # 数字部分
        num = ""
        unit = ""
        for ch in s:
            if ch.isdigit() or ch == ".":
                num += ch
            else:
                unit += ch
        num_f = float(num) if num else 0.0
        unit = unit.strip()
        if unit in ("gb", "g"):
            return int(num_f * 1024**3)
        if unit in ("mb", "m"):
            return int(num_f * 1024**2)
        if unit in ("kb", "k"):
            return int(num_f * 1024)
        if unit in ("b", ""):
            return int(num_f)
        return int(num_f * 1024**2)  # 默认按 MB 处理
    except Exception:
        return 0


def _dir_size(path: Path) -> int:
    """递归计算目录大小（字节）。"""
    total = 0
    try:
        if not path.exists():
            return 0
        for root, _dirs, files in os.walk(path):
            for f in files:
                try:
                    fp = Path(root) / f
                    total += fp.stat().st_size
                except (OSError, FileNotFoundError):
                    pass
    except Exception:
        pass
    return total


def get_model_downloader(base_dir: str = None) -> ModelDownloader:
    """获取全局 ModelDownloader 实例

    Args:
        base_dir: 模型存储的基础目录。如果为 None，则自动使用项目根目录。
    """
    global _downloader
    if _downloader is None:
        if base_dir is None:
            # 自动检测项目根目录：从 neurova/tts/model_downloader.py 向上两级
            base_dir = Path(__file__).parent.parent.parent.resolve()
        _downloader = ModelDownloader(base_dir=base_dir)
    return _downloader
