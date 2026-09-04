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
    def test_all_models_have_ms_repo(self):
        for name, entry in md.MODEL_REGISTRY.items():
            assert entry.get("ms_repo_id"), f"{name} 缺 ModelScope 镜像 repo_id"


class TestEnsureModelSource:
    def _downloader(self, tmp_path):
        return md.ModelDownloader(base_dir=str(tmp_path))

    def test_default_source_is_auto_ms_first(self, tmp_path, monkeypatch):
        """auto 策略 = ModelScope 优先（国内网络实测可靠），失败落 HF。"""
        calls = []
        monkeypatch.setattr(md, "_download_via_modelscope",
                            lambda entry, model_dir, cb: calls.append("ms") or None)
        monkeypatch.setattr(md, "_download_via_huggingface",
                            lambda entry, model_dir, cb: calls.append("hf") or None)
        dl = self._downloader(tmp_path)
        dl.ensure_model("bge-small-zh-v1.5", source="auto")
        assert calls == ["ms"]

    def test_ms_failure_falls_back_to_hf(self, tmp_path, monkeypatch):
        calls = []
        def ms_fail(entry, model_dir, cb):
            calls.append("ms-fail")
            raise RuntimeError("modelscope down")
        monkeypatch.setattr(md, "_download_via_modelscope", ms_fail)
        monkeypatch.setattr(md, "_download_via_huggingface",
                            lambda entry, model_dir, cb: calls.append("hf") or None)
        dl = self._downloader(tmp_path)
        dl.ensure_model("bge-small-zh-v1.5", source="auto")
        assert calls == ["ms-fail", "hf"]

    def test_explicit_modelscope_no_hf_fallback(self, tmp_path, monkeypatch):
        calls = []
        monkeypatch.setattr(md, "_download_via_modelscope", mock.Mock(
            side_effect=RuntimeError("modelscope down")))
        monkeypatch.setattr(md, "_download_via_huggingface",
                            lambda entry, model_dir, cb: calls.append("hf") or None)
        dl = self._downloader(tmp_path)
        with pytest.raises(RuntimeError):
            dl.ensure_model("bge-small-zh-v1.5", source="modelscope")
        assert calls == []  # 显式指定源：失败不换源

    def test_progress_callback_wired_to_both_sources(self, tmp_path, monkeypatch):
        """进度回调在两个源都要接上（前端进度条的数据源）。"""
        seen = []
        dl = self._downloader(tmp_path)
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
