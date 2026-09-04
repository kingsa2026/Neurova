# -*- coding: utf-8 -*-
"""模型下载源的用户选择持久化。

用户在下载提示框里选择"国内源（ModelScope）/国外源（HuggingFace）/
跳过"，按模型独立记忆在 data/model_source.json。选择为 auto（默认）时
ModelScope 优先、失败落 HuggingFace。

损坏文件按全 auto 处理（可用性优先于保真——下载源偏好丢了重选即可）。
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, asdict
from pathlib import Path

logger = logging.getLogger(__name__)

# 合法选择值（前端下拉/对话框同契约）
VALID_CHOICES = {"auto", "always_modelscope", "always_huggingface", "skip"}
DEFAULT_PATH = Path("data") / "model_source.json"

_lock = threading.RLock()


@dataclass
class DownloadSourceChoice:
    model: str
    choice: str


def _validate_choice(choice: str) -> str:
    if choice not in VALID_CHOICES:
        raise ValueError(f"非法下载源选择: {choice!r}，合法值: {sorted(VALID_CHOICES)}")
    return choice


def get(model: str, path: Path | None = None) -> str:
    """读某模型的下载源选择（无记录/auto/损坏 → auto）。"""
    p = path or DEFAULT_PATH
    with _lock:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return "auto"
        if not isinstance(data, dict):
            return "auto"
        choice = data.get(model)
        return choice if choice in VALID_CHOICES else "auto"


def set(model: str, choice: str, path: Path | None = None) -> None:
    """写某模型的下载源选择（choice/model 双白名单校验）。"""
    _validate_choice(choice)
    # model 必须在注册表里（防垃圾键无限增长）
    from neurova.tts.model_downloader import MODEL_REGISTRY

    if model not in MODEL_REGISTRY:
        raise ValueError(f"未知模型: {model!r}")
    p = path or DEFAULT_PATH
    with _lock:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except (OSError, json.JSONDecodeError):
            data = {}
        data[model] = choice
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(p)  # 原子写（Windows 无 flock 交叉截断教训）
    logger.debug("模型下载源选择已保存: %s -> %s", model, choice)


# 面向测试的命名空间聚合（保持 import 处用法简洁）
class download_source_store:
    get = staticmethod(get)
    set = staticmethod(set)


__all__ = ["DownloadSourceChoice", "download_source_store", "get", "set", "VALID_CHOICES"]
