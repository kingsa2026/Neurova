"""
模型下载服务契约（后台触发 + 进度聚合 + skip 语义）

- start(model): 后台线程执行 ensure_model；重复触发幂等
- choice=skip → 不发起下载，状态 skipped（用户"暂不下载"必须被尊重）
- choice=always_modelscope/huggingface → 透传给 ensure_model 的 source
- progress(): 全模型状态快照（前端轮询数据源）
"""
import threading
import time
from pathlib import Path

import pytest

from neurova.tts import download_service as ds
from neurova.tts.download_source import DownloadSourceChoice, download_source_store
from neurova.tts.model_downloader import ModelDownloader


@pytest.fixture()
def service(tmp_path):
    """干净 tmp 模型目录 + 打桩下载器（成功引擎）。"""
    dl = ModelDownloader(base_dir=str(tmp_path))

    def fake_engine(registry, model_dir, cb=None):
        time.sleep(0.05)  # 模拟下载耗时
        for f in registry["required_files"]:
            p = model_dir / f
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"x")

    import neurova.tts.model_downloader as md

    monkey_target = md
    original = {
        "ms": monkey_target._download_via_modelscope,
        "mirror": monkey_target._download_via_hf_mirror,
        "hf": monkey_target._download_via_huggingface,
    }
    monkey_target._download_via_modelscope = fake_engine
    monkey_target._download_via_hf_mirror = fake_engine
    monkey_target._download_via_huggingface = fake_engine
    yield ds.ModelDownloadService(downloader=dl)
    monkey_target._download_via_modelscope = original["ms"]
    monkey_target._download_via_hf_mirror = original["mirror"]
    monkey_target._download_via_huggingface = original["hf"]


class TestStartAndProgress:
    def test_start_runs_download_to_done(self, service):
        state = service.start("bge-small-zh-v1.5")
        assert state["status"] in ("pending", "downloading")
        # 等待后台完成
        for _ in range(100):
            if service.progress()[0]["status"] == "done":
                break
            time.sleep(0.05)
        states = {s["model"]: s for s in service.progress()}
        assert states["bge-small-zh-v1.5"]["status"] == "done"

    def test_duplicate_start_is_idempotent(self, service):
        s1 = service.start("bge-small-zh-v1.5")
        s2 = service.start("bge-small-zh-v1.5")
        assert s1 is s2  # 同一状态对象，不重复起线程

    def test_unknown_model_rejected(self, service):
        with pytest.raises(ValueError):
            service.start("no-such-model")


class TestSkipChoice:
    def test_skip_does_not_download(self, service, tmp_path, monkeypatch):
        p = tmp_path / "model_source.json"
        download_source_store.set(
            DownloadSourceChoice(model="moss-tts-nano", choice="skip"), path=p)
        monkeypatch.setattr(ds, "_choice_path", lambda: p)
        state = service.start("moss-tts-nano")
        assert state["status"] == "skipped"
        # 未落盘模型文件
        assert not list((service._downloader.get_model_dir("moss-tts-nano")).glob("*.onnx"))

    def test_explicit_choice_forwarded(self, service, tmp_path, monkeypatch):
        p = tmp_path / "model_source.json"
        download_source_store.set(
            DownloadSourceChoice(model="bge-small-zh-v1.5", choice="always_huggingface"), path=p)
        monkeypatch.setattr(ds, "_choice_path", lambda: p)
        seen_sources = []
        orig_ensure = service._downloader.ensure_model

        def spy_ensure(model, force=False, source="auto"):
            seen_sources.append(source)
            return orig_ensure(model, force=force, source=source)

        monkeypatch.setattr(service._downloader, "ensure_model", spy_ensure)
        service.start("bge-small-zh-v1.5")
        for _ in range(100):
            if seen_sources:
                break
            time.sleep(0.02)
        assert seen_sources == ["huggingface"]

    def test_auto_default_when_no_choice(self, service, tmp_path, monkeypatch):
        monkeypatch.setattr(ds, "_choice_path", lambda: tmp_path / "none.json")
        seen_sources = []
        orig_ensure = service._downloader.ensure_model

        def spy_ensure(model, force=False, source="auto"):
            seen_sources.append(source)
            return orig_ensure(model, force=force, source=source)

        monkeypatch.setattr(service._downloader, "ensure_model", spy_ensure)
        service.start("bge-small-zh-v1.5")
        for _ in range(100):
            if seen_sources:
                break
            time.sleep(0.02)
        assert seen_sources == ["auto"]


class TestFailure:
    def test_failed_state_carries_error(self, tmp_path):
        dl = ModelDownloader(base_dir=str(tmp_path))

        def broken_engine(registry, model_dir, cb=None):
            raise RuntimeError("network down")

        import neurova.tts.model_downloader as md

        for name in ("_download_via_modelscope", "_download_via_hf_mirror", "_download_via_huggingface"):
            monkey_target = md
            monkey_target.__dict__[name] = broken_engine
        try:
            service = ds.ModelDownloadService(downloader=dl)
            service.start("moss-tts-nano")
            for _ in range(100):
                if service.progress()[0]["status"] == "failed":
                    break
                time.sleep(0.05)
            states = {s["model"]: s for s in service.progress()}
            assert states["moss-tts-nano"]["status"] == "failed"
            assert "network down" in states["moss-tts-nano"]["error"]
        finally:
            # 恢复模块函数（避免污染其他测试）
            import importlib
            importlib.reload(md)
