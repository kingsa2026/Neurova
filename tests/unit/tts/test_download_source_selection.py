"""
模型下载源选择契约（用户需求：下载前提示用户选国内/国外源）

背景：实测 hf-mirror 与 hf_hub 1.29 不兼容、直连 HF 需代理——国内裸机
MOSS/bge 下载必失败，ModelScope 国内直连可靠。

契约：
- ModelDownloader.ensure_model(source=...)：显式源参数（modelscope/huggingface），
  modelscope 源走 modelscope.snapshot_download，HF 源走 huggingface_hub
- MODEL_REGISTRY 各条目补 ms_repo_id（ModelScope 镜像）
- download_source_store：用户选择持久化（auto/always_modelscope/always_huggingface/skip），
  每模型独立记忆；损坏文件按 auto 处理
- pending_download：待下载清单（模型缺失判断），供前端渲染提示框
- 端点 /v1/models/download-source：GET 读选择 / POST 写选择
"""
import json
from unittest import mock

import pytest

from neurova.tts import model_downloader as md
from neurova.tts.download_source import (
    DownloadSourceChoice,
    download_source_store,
)


class TestRegistryHasModelScope:
    def test_bge_has_ms_mirror(self):
        # bge 在 ModelScope 有镜像（AI-ModelScope），国内硬可靠
        assert md.MODEL_REGISTRY["bge-small-zh-v1.5"].get("ms_repo_id")

    def test_moss_onnx_no_mirror_marked_none(self):
        # MOSS ONNX 仓在 ModelScope 只有 PyTorch 训练仓（文件格式不同），
        # 显式标 None 防"拿错仓库"——国内源落 hf-mirror（尽力而为）
        for name in ("moss-tts-nano", "moss-audio-tokenizer"):
            assert md.MODEL_REGISTRY[name].get("ms_repo_id") is None, name


class TestSourceResolution:
    def test_auto_bge_ms_first(self, tmp_path, monkeypatch):
        """bge 有 MS 镜像：auto = modelscope → hf-mirror → hf 直连。"""
        calls = []
        monkeypatch.setattr(md, "_download_via_modelscope",
                            lambda e, d, cb: calls.append("ms"))
        monkeypatch.setattr(md, "_download_via_hf_mirror",
                            lambda e, d, cb: calls.append("mirror"))
        monkeypatch.setattr(md, "_download_via_huggingface",
                            lambda e, d, cb: calls.append("hf"))
        md.ModelDownloader(base_dir=str(tmp_path)).ensure_model(
            "bge-small-zh-v1.5", source="auto")
        assert calls == ["ms"]

    def test_auto_moss_mirror_first_no_ms(self, tmp_path, monkeypatch):
        """MOSS 无 MS 镜像：auto = hf-mirror → hf 直连（跳过 modelscope）。"""
        calls = []
        monkeypatch.setattr(md, "_download_via_modelscope",
                            lambda e, d, cb: calls.append("ms"))
        monkeypatch.setattr(md, "_download_via_hf_mirror",
                            lambda e, d, cb: calls.append("mirror"))
        monkeypatch.setattr(md, "_download_via_huggingface",
                            lambda e, d, cb: calls.append("hf"))
        md.ModelDownloader(base_dir=str(tmp_path)).ensure_model(
            "moss-tts-nano", source="auto")
        assert calls == ["mirror"]

    def test_auto_ms_fail_falls_to_mirror_then_hf(self, tmp_path, monkeypatch):
        calls = []
        def ms_fail(e, d, cb):
            calls.append("ms-fail")
            raise RuntimeError("modelscope down")
        def mirror_fail(e, d, cb):
            calls.append("mirror-fail")
            raise RuntimeError("mirror down")
        monkeypatch.setattr(md, "_download_via_modelscope", ms_fail)
        monkeypatch.setattr(md, "_download_via_hf_mirror", mirror_fail)
        monkeypatch.setattr(md, "_download_via_huggingface",
                            lambda e, d, cb: calls.append("hf"))
        md.ModelDownloader(base_dir=str(tmp_path)).ensure_model(
            "bge-small-zh-v1.5", source="auto")
        assert calls == ["ms-fail", "mirror-fail", "hf"]

    def test_explicit_modelscope_no_fallback(self, tmp_path, monkeypatch):
        calls = []
        monkeypatch.setattr(md, "_download_via_modelscope", mock.Mock(
            side_effect=RuntimeError("modelscope down")))
        monkeypatch.setattr(md, "_download_via_hf_mirror",
                            lambda e, d, cb: calls.append("mirror"))
        monkeypatch.setattr(md, "_download_via_huggingface",
                            lambda e, d, cb: calls.append("hf"))
        dl = md.ModelDownloader(base_dir=str(tmp_path))
        with pytest.raises(RuntimeError):
            dl.ensure_model("bge-small-zh-v1.5", source="modelscope")
        assert calls == []  # 显式指定源：失败不换源

    def test_explicit_huggingface_direct_only(self, tmp_path, monkeypatch):
        calls = []
        monkeypatch.setattr(md, "_download_via_modelscope",
                            lambda e, d, cb: calls.append("ms"))
        monkeypatch.setattr(md, "_download_via_hf_mirror",
                            lambda e, d, cb: calls.append("mirror"))
        monkeypatch.setattr(md, "_download_via_huggingface",
                            lambda e, d, cb: calls.append("hf"))
        md.ModelDownloader(base_dir=str(tmp_path)).ensure_model(
            "bge-small-zh-v1.5", source="huggingface")
        assert calls == ["hf"]

    def test_invalid_source_rejected(self, tmp_path):
        with pytest.raises(ValueError):
            md.ModelDownloader(base_dir=str(tmp_path)).ensure_model(
                "bge-small-zh-v1.5", source="ftp")

    def test_progress_callback_wired_to_all_sources(self, tmp_path, monkeypatch):
        """进度回调在三个源都要接上（前端进度条的数据源）。"""
        seen = []
        dl = md.ModelDownloader(base_dir=str(tmp_path))
        dl.set_progress_callback(lambda p: seen.append(p))
        monkeypatch.setattr(md, "_download_via_modelscope",
                            mock.Mock(side_effect=lambda entry, d, cb: cb(50, 100)))
        dl.ensure_model("bge-small-zh-v1.5", source="modelscope")
        assert len(seen) == 1
        assert seen[0].percentage == 50.0


class TestSourceStore:
    def test_roundtrip(self, tmp_path):
        p = tmp_path / "model_source.json"
        download_source_store.set(DownloadSourceChoice(
            model="bge-small-zh-v1.5", choice="always_modelscope"), path=p)
        got = download_source_store.get("bge-small-zh-v1.5", path=p)
        assert got == "always_modelscope"

    def test_default_auto(self, tmp_path):
        p = tmp_path / "none.json"
        assert download_source_store.get("moss-tts-nano", path=p) == "auto"

    def test_skip_choice(self, tmp_path):
        p = tmp_path / "model_source.json"
        download_source_store.set(DownloadSourceChoice(
            model="moss-tts-nano", choice="skip"), path=p)
        assert download_source_store.get("moss-tts-nano", path=p) == "skip"

    def test_corrupt_file_treated_as_auto(self, tmp_path):
        p = tmp_path / "model_source.json"
        p.write_text("not json{", encoding="utf-8")
        assert download_source_store.get("moss-tts-nano", path=p) == "auto"

    def test_invalid_choice_rejected(self, tmp_path):
        p = tmp_path / "model_source.json"
        with pytest.raises(ValueError):
            download_source_store.set(DownloadSourceChoice(
                model="moss-tts-nano", choice="ftp"), path=p)

    def test_unknown_model_rejected(self, tmp_path):
        p = tmp_path / "model_source.json"
        with pytest.raises(ValueError):
            download_source_store.set(DownloadSourceChoice(
                model="nonexistent-model", choice="skip"), path=p)


class TestPendingDownloads:
    def test_pending_lists_missing_models(self, tmp_path, monkeypatch):
        monkeypatch.setattr(md.MODEL_REGISTRY["moss-tts-nano"], "local_dir",
                            "models/tts/moss-nano", raising=False)
        dl = md.ModelDownloader(base_dir=str(tmp_path))
        pending = dl.pending_downloads()
        assert isinstance(pending, list)
        for item in pending:
            assert {"model", "available", "size_hint"} <= set(item.keys())

    def test_pending_empty_when_all_present(self, tmp_path, monkeypatch):
        dl = md.ModelDownloader(base_dir=str(tmp_path))
        monkeypatch.setattr(dl, "is_model_available", lambda name: True)
        assert dl.pending_downloads() == []
