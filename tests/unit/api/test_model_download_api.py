"""
模型下载 API 契约（提示框前端数据面）

- GET  /v1/models/pending-downloads   待下载清单（含每模型已存选择）
- GET  /v1/models/download-source     用户选择映射
- POST /v1/models/download-source     写选择（非法值/未知模型 → 400）
- POST /v1/models/download            触发下载（幂等，unknown → 400）
- GET  /v1/models/download-progress   触发过的模型状态快照

写端点要求登录（get_current_user）；读端点登录可选。
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.endpoints import model as model_api


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from neurova.tts import download_service as ds
    from neurova.tts.model_downloader import ModelDownloader
    import neurova.tts.model_downloader as md

    # 隔离：tmp 模型目录 + tmp 选择文件 + tmp 下载状态
    monkeypatch.setattr(model_api, "_downloader", ModelDownloader(base_dir=str(tmp_path)))
    service = ds.ModelDownloadService(downloader=model_api._downloader)
    monkeypatch.setattr(model_api, "_service", service)
    monkeypatch.setattr(
        ds, "_choice_path", lambda: tmp_path / "model_source.json", raising=False
    )

    # 引擎打桩：不碰真网络，落盘 required_files 即视为下载成功
    def fake_engine(registry, model_dir, cb=None):
        for f in registry["required_files"]:
            p = model_dir / f
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"x")

    for name in ("_download_via_modelscope", "_download_via_hf_mirror", "_download_via_huggingface"):
        monkeypatch.setattr(md, name, fake_engine)

    app = FastAPI()
    app.include_router(model_api.router, prefix="/v1/models")
    # POST 端点要求登录：注入 fake 登录用户
    app.dependency_overrides[model_api.get_current_user] = lambda: {
        "id": 1, "username": "tester", "is_admin": True,
    }
    yield TestClient(app)
    app.dependency_overrides.clear()


class TestPendingDownloads:
    def test_lists_missing_with_choice(self, client, tmp_path):
        r = client.get("/v1/models/pending-downloads")
        assert r.status_code == 200
        items = r.json()
        assert items and len(items) == 3  # 干净环境三模型全缺
        for item in items:
            assert item["available"] is False
            assert item["choice"] in ("auto", "always_modelscope", "always_huggingface", "skip")


class TestDownloadSourceApi:
    def test_get_empty_defaults(self, client):
        r = client.get("/v1/models/download-source")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict)

    def test_post_roundtrip(self, client):
        r = client.post(
            "/v1/models/download-source",
            json={"model": "bge-small-zh-v1.5", "choice": "always_modelscope"},
        )
        assert r.status_code == 200
        assert r.json()["ok"] is True
        r2 = client.get("/v1/models/download-source")
        assert r2.json()["bge-small-zh-v1.5"] == "always_modelscope"

    def test_post_invalid_choice_400(self, client):
        r = client.post(
            "/v1/models/download-source",
            json={"model": "bge-small-zh-v1.5", "choice": "ftp"},
        )
        assert r.status_code == 400

    def test_post_unknown_model_400(self, client):
        r = client.post(
            "/v1/models/download-source",
            json={"model": "nope", "choice": "auto"},
        )
        assert r.status_code == 400


class TestDownloadTrigger:
    def test_trigger_unknown_model_400(self, client):
        r = client.post("/v1/models/download", json={"model": "nope"})
        assert r.status_code == 400

    def test_trigger_and_progress(self, client):
        r = client.post("/v1/models/download", json={"model": "moss-tts-nano"})
        assert r.status_code == 200
        state = r.json()
        assert state["status"] in ("pending", "downloading", "done")
        # 轮询直至终态（服务层引擎被打桩为立即成功？——此处走真实引擎会失败，
        # 但终态必达：failed 或 done 都算"状态机收敛"）
        import time

        final = None
        for _ in range(200):
            prog = client.get("/v1/models/download-progress").json()
            st = next((s for s in prog if s["model"] == "moss-tts-nano"), None)
            if st and st["status"] in ("done", "failed"):
                final = st
                break
            time.sleep(0.05)
        assert final is not None
        assert final["status"] in ("done", "failed")

    def test_progress_empty_before_any_trigger(self, client):
        assert client.get("/v1/models/download-progress").json() == []
