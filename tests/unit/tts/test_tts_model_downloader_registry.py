"""
Tier 3A.1 防回归 — TTS 模型下载器 registry 契约与实际仓库文件对齐

根因（2026-09-03）：MODEL_REGISTRY 里 moss-tts-nano / moss-audio-tokenizer
的 required_files 写的是 model.onnx，但 OpenMOSS 仓库实际发布的是
moss_tts_prefill.onnx 等 5 图级联 + .data 共享权重（无 model.onnx）——
is_model_available 恒 False、ensure_model 恒抛"模型下载不完整"，
MOSS 本地 TTS 引擎即使模型已下载完整也永远无法初始化。

本组测试锁定：
1. registry 文件清单与 HF 仓库真实文件对齐（快照，含最近的提交修订号）
2. is_model_available 按真实文件名判定（临时目录构造，不依赖本机模型）
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from neurova.tts.model_downloader import MODEL_REGISTRY, ModelDownloader

# HF 仓库真实文件快照（2026-09-03 核对，注释掉的坑请勿改回 model.onnx）
REPO_FILES_TTS = {
    "moss_tts_prefill.onnx",
    "moss_tts_decode_step.onnx",
    "moss_tts_local_cached_step.onnx",
    "moss_tts_local_decoder.onnx",
    "moss_tts_local_fixed_sampled_frame.onnx",
    "moss_tts_global_shared.data",
    "moss_tts_local_shared.data",
    "tokenizer.model",
    "browser_poc_manifest.json",
    "tts_browser_onnx_meta.json",
}

REPO_FILES_TOKENIZER = {
    "moss_audio_tokenizer_encode.onnx",
    "moss_audio_tokenizer_encode.data",
    "moss_audio_tokenizer_decode_step.onnx",
    "moss_audio_tokenizer_decode_shared.data",
    "moss_audio_tokenizer_decode_full.onnx",
}


class TestRegistryContract:
    """registry 必须引用仓库真实存在的文件"""

    def test_moss_tts_required_files_exist_in_repo(self):
        entry = MODEL_REGISTRY["moss-tts-nano"]
        assert entry["required_files"], "核心推理文件清单不能为空"
        missing = set(entry["required_files"]) - REPO_FILES_TTS
        assert not missing, f"required_files 含仓库不存在的文件: {missing}"

    def test_moss_tts_no_stale_model_onnx(self):
        """防止旧契约 model.onnx 回潮（根因文件）"""
        entry = MODEL_REGISTRY["moss-tts-nano"]
        assert "model.onnx" not in entry["required_files"]
        assert "model.onnx" not in MODEL_REGISTRY["moss-audio-tokenizer"]["required_files"]

    def test_tokenizer_required_files_exist_in_repo(self):
        entry = MODEL_REGISTRY["moss-audio-tokenizer"]
        missing = set(entry["required_files"]) - REPO_FILES_TOKENIZER
        assert not missing, f"tokenizer required_files 含仓库不存在的文件: {missing}"

    def test_required_files_cover_full_pipeline(self):
        """5 图 + 2 份共享权重 + tokenizer 全部纳入核心检查（缺一即视为不完整）"""
        entry = MODEL_REGISTRY["moss-tts-nano"]
        onnx_counts = sum(1 for f in entry["required_files"] if f.endswith(".onnx"))
        assert onnx_counts >= 5, f"5 图级联应全部纳入检查, 当前 onnx 文件数={onnx_counts}"
        assert "moss_tts_global_shared.data" in entry["required_files"]
        assert "moss_tts_local_shared.data" in entry["required_files"]


class TestIsModelAvailable:
    """is_model_available 按真实文件名判定"""

    def _make_downloader(self, base_dir: Path) -> ModelDownloader:
        return ModelDownloader(base_dir=str(base_dir))

    def test_available_when_all_required_files_present(self, tmp_path):
        d = self._make_downloader(tmp_path)
        model_dir = tmp_path / MODEL_REGISTRY["moss-tts-nano"]["local_dir"]
        for f in MODEL_REGISTRY["moss-tts-nano"]["required_files"]:
            (model_dir / f).parent.mkdir(parents=True, exist_ok=True)
            (model_dir / f).touch()
        assert d.is_model_available("moss-tts-nano") is True

    def test_not_available_when_core_onnx_missing(self, tmp_path):
        d = self._make_downloader(tmp_path)
        model_dir = tmp_path / MODEL_REGISTRY["moss-tts-nano"]["local_dir"]
        for f in MODEL_REGISTRY["moss-tts-nano"]["required_files"]:
            if f == "moss_tts_prefill.onnx":
                continue  # 剥掉核心 prefill 图
            (model_dir / f).parent.mkdir(parents=True, exist_ok=True)
            (model_dir / f).touch()
        assert d.is_model_available("moss-tts-nano") is False
