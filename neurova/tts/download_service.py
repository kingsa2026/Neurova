# -*- coding: utf-8 -*-
"""模型下载服务：后台触发、进度聚合、skip 语义。

前端提示框选完源后 POST trigger → 本服务起后台线程跑 ensure_model；
前端轮询 progress() 渲染进度条。重复触发幂等（同一状态对象）；
choice=skip 时直接返回 skipped 状态，绝不下载（用户选择必须被尊重）。
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Dict, List, Optional

from neurova.tts.download_source import get as get_choice
from neurova.tts.model_downloader import ModelDownloader, get_model_downloader

logger = logging.getLogger(__name__)


def _choice_path() -> Path:
    from neurova.tts.download_source import DEFAULT_PATH

    return DEFAULT_PATH


# 下载源存储的 UI 选择值 → ensure_model 的 source 参数值
_CHOICE_TO_SOURCE = {
    "auto": "auto",
    "always_modelscope": "modelscope",
    "always_huggingface": "huggingface",
}


class ModelDownloadService:
    """全模型下载状态机（单例语义由 get_download_service 保证）。"""

    def __init__(self, downloader: Optional[ModelDownloader] = None):
        self._downloader = downloader or get_model_downloader()
        self._states: Dict[str, dict] = {}
        self._threads: Dict[str, threading.Thread] = {}
        self._lock = threading.RLock()
        # 进度回调 → 更新对应模型状态
        self._downloader.set_progress_callback(self._on_progress)

    def _on_progress(self, p) -> None:
        with self._lock:
            st = self._states.get(p.model_name)
            if st is not None:
                st["percentage"] = p.percentage
                if st["status"] == "pending":
                    st["status"] = "downloading"

    def start(self, model: str, source: Optional[str] = None) -> dict:
        """触发下载（幂等）。source 缺省时读用户持久化选择。"""
        from neurova.tts.model_downloader import MODEL_REGISTRY

        if model not in MODEL_REGISTRY:
            raise ValueError(f"未知模型: {model!r}")

        with self._lock:
            if model in self._states:
                return self._states[model]  # 幂等：已在跑/已完成不重跑

            choice = source or get_choice(model, path=_choice_path())
            state = {
                "model": model,
                "status": "pending",
                "error": "",
                "percentage": 0.0,
            }
            self._states[model] = state

        if choice == "skip":
            state["status"] = "skipped"
            return state

        source_param = _CHOICE_TO_SOURCE.get(choice, "auto")

        def _run():
            try:
                state["status"] = "downloading"
                self._downloader.ensure_model(model, source=source_param)
                state["status"] = "done"
                state["percentage"] = 100.0
            except Exception as e:  # noqa: BLE001 - 后台线程吞异常转状态
                logger.warning("模型 %s 下载失败: %s", model, e)
                state["status"] = "failed"
                state["error"] = str(e)

        t = threading.Thread(target=_run, daemon=True, name=f"dl-{model}")
        self._threads[model] = t
        t.start()
        return state

    def progress(self) -> List[dict]:
        """全模型状态快照（前端轮询数据源；未触发的模型不出现）。"""
        with self._lock:
            return [dict(st) for st in self._states.values()]


_service: Optional[ModelDownloadService] = None
_service_lock = threading.RLock()


def get_download_service() -> ModelDownloadService:
    global _service
    with _service_lock:
        if _service is None:
            _service = ModelDownloadService()
        return _service


def reset_download_service() -> None:
    global _service
    with _service_lock:
        _service = None
