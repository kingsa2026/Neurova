# -*- coding: utf-8 -*-
"""R3：/api/v1/studio 端点族契约（属主隔离 / 后台任务 runs / 账本投影 / 合并）。"""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.aigc_studio.store import StudioStore
from neurova.api.endpoints import studio_api
from neurova.api.deps import get_current_user

pytestmark = pytest.mark.timeout(60)


USER = {"user_id": "u1", "username": "u1", "role": "user", "neuser_id": "u1"}
OTHER = {"user_id": "u2", "username": "u2", "role": "user", "neuser_id": "u2"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    store = StudioStore(db_path=str(tmp_path / "studio.db"))
    monkeypatch.setattr(studio_api, "get_store", lambda: store)
    app = FastAPI()
    app.include_router(studio_api.router, prefix="/api/v1/studio")
    holder = {"user": USER}
    app.dependency_overrides[get_current_user] = lambda: holder["user"]
    c = TestClient(app)
    c.holder = holder  # type: ignore[attr-defined]
    c.store = store  # type: ignore[attr-defined]
    return c


class TestProjectCrud:
    def test_create_list_update_delete(self, client):
        r = client.post("/api/v1/studio/projects", json={"title": "T", "style": "水墨"})
        assert r.status_code == 200
        pid = r.json()["data"]["project"]["id"]
        assert client.get("/api/v1/studio/projects").json()["data"]["projects"][0]["id"] == pid
        assert client.put(f"/api/v1/studio/projects/{pid}",
                          json={"title": "T2"}).json()["data"]["project"]["title"] == "T2"
        assert client.delete(f"/api/v1/studio/projects/{pid}").json()["code"] == 0
        assert client.get(f"/api/v1/studio/projects/{pid}").status_code == 404

    def test_owner_isolation_404(self, client):
        pid = client.post("/api/v1/studio/projects", json={"title": "私有"}).json()["data"]["project"]["id"]
        client.holder["user"] = OTHER
        assert client.get(f"/api/v1/studio/projects/{pid}").status_code == 404
        assert client.put(f"/api/v1/studio/projects/{pid}", json={"title": "x"}).status_code == 404
        assert client.get("/api/v1/studio/projects").json()["data"]["projects"] == []


class TestBackgroundRuns:
    def test_script_launches_run_with_injected_llm(self, client, monkeypatch):
        from neurova.aigc_studio import services as svc

        async def fake_split(store, pid, content, llm=None, model=None):
            return store.add_episode(pid, {"number": 1, "title": "注入集", "content": content})

        monkeypatch.setattr(svc, "split_script", fake_split)
        pid = client.post("/api/v1/studio/projects", json={"title": "T"}).json()["data"]["project"]["id"]
        r = client.post(f"/api/v1/studio/projects/{pid}/script", json={"content": "小说"})
        assert r.status_code == 200 and r.json()["data"]["status"] == "started"
        # TestClient 的同步循环已驱动 task：轮询 runs 至终态
        for _ in range(50):
            runs = client.store.list_runs(pid)
            if runs and runs[0]["status"] in ("done", "failed"):
                break
        assert runs and runs[0]["status"] == "done"
        eps = client.get(f"/api/v1/studio/projects/{pid}").json()["data"]["episodes"]
        assert eps and eps[0]["title"] == "注入集"


    def test_generate_endpoints_pass_provider_id(self, client, monkeypatch):
        """模型选择全链端点层：body.provider_id 透传给 services（hint 推导在 services）。"""
        from neurova.aigc_studio import services as svc

        seen = {}

        async def fake_images(store, pid, eid, provider="openai", model="",
                              provider_id="", shot_ids=None):
            seen["images"] = (model, provider_id)
            return {"done": 1, "failed": 0, "skipped_no_prompt": 0}

        async def fake_videos(store, pid, eid, provider="wan", model="",
                              resolution="1080p", duration=5, owner_user_id="",
                              provider_id="", shot_ids=None):
            seen["videos"] = (model, provider_id)
            return {"submitted": 1, "skipped": 0, "failed": 0}

        monkeypatch.setattr(svc, "generate_shot_images", fake_images)
        monkeypatch.setattr(svc, "generate_shot_videos", fake_videos)
        pid = client.post("/api/v1/studio/projects", json={"title": "T"}).json()["data"]["project"]["id"]
        eid = client.store.add_episode(pid, {"number": 1, "title": "e"})["id"]
        r = client.post(f"/api/v1/studio/episodes/{eid}/generate-images",
                        json={"model": "flux.1", "provider_id": "prov-x"})
        assert r.status_code == 200
        r = client.post(f"/api/v1/studio/episodes/{eid}/generate-videos",
                        json={"model": "seedance-2-0", "provider_id": "prov-y"})
        assert r.status_code == 200
        for _ in range(50):
            runs = client.store.list_runs(pid)
            if len(runs) >= 2 and all(x["status"] in ("done", "failed") for x in runs):
                break
        assert seen.get("images") == ("flux.1", "prov-x")
        assert seen.get("videos") == ("seedance-2-0", "prov-y")

    def test_bad_request_validation(self, client):
        pid = client.post("/api/v1/studio/projects", json={"title": "T"}).json()["data"]["project"]["id"]
        assert client.post(f"/api/v1/studio/projects/{pid}/script", json={}).status_code == 400
        assert client.post("/api/v1/studio/projects", json={}).status_code == 400


class TestEpisodeProjection:
    def test_video_backfill_from_ledger(self, client, tmp_path, monkeypatch):
        from neurova.llm.generators import task_ledger as ledger_mod
        from neurova.llm.generators.task_ledger import GenerationTaskLedger, TaskRecord

        led = GenerationTaskLedger(path=str(tmp_path / "led.json"))
        monkeypatch.setattr(ledger_mod, "_ledger", led)
        art = tmp_path / "v.mp4"
        art.write_bytes(b"M")
        task = led.add(TaskRecord(kind="video", status="succeeded",
                                  local_path=str(art), remote_task_id="r1"))
        pid = client.post("/api/v1/studio/projects", json={"title": "T"}).json()["data"]["project"]["id"]
        ep = client.store.add_episode(pid, {"number": 1, "title": "e"})
        sb = client.store.add_storyboard(ep["id"], {
            "number": 1, "video_status": "running", "ledger_task_id": task.task_id})
        data = client.get(f"/api/v1/studio/episodes/{ep['id']}").json()["data"]
        shot = next(s for s in data["storyboards"] if s["id"] == sb["id"])
        assert shot["video_status"] == "done" and shot["video_path"] == str(art)

    def test_edit_storyboard_prompt(self, client):
        pid = client.post("/api/v1/studio/projects", json={"title": "T"}).json()["data"]["project"]["id"]
        ep = client.store.add_episode(pid, {"number": 1, "title": "e"})
        sb = client.store.add_storyboard(ep["id"], {"number": 1})
        r = client.put(f"/api/v1/studio/storyboards/{sb['id']}",
                       json={"image_prompt": "new prompt", "unknown_field": 1})
        assert r.json()["data"]["storyboard"]["image_prompt"] == "new prompt"


class TestMergeEndpoint:
    def test_merge_sync_manifest(self, client, tmp_path, monkeypatch):
        import shutil

        monkeypatch.setattr(shutil, "which", lambda x: None)
        pid = client.post("/api/v1/studio/projects", json={"title": "T"}).json()["data"]["project"]["id"]
        ep = client.store.add_episode(pid, {"number": 1, "title": "e"})
        f = tmp_path / "f.png"
        f.write_bytes(b"I")
        client.store.add_storyboard(ep["id"], {"number": 1, "narration": "旁白",
                                               "first_frame_path": str(f)})
        r = client.post(f"/api/v1/studio/episodes/{ep['id']}/merge")
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["mode"] in ("slideshow_manifest", "ffmpeg_concat")
        assert data["items"][0]["text"] == "旁白"
        m = client.get(f"/api/v1/studio/merges/{data['merge']['id']}")
        assert m.status_code == 200
        # 字幕 SRT 已生成并挂到分集
        assert json.loads(client.store.get_merge(data["merge"]["id"])["items_json"])[0]["text"] == "旁白"
        assert client.store.get_episode(ep["id"])["subtitle_path"].endswith(".srt")


class TestManualShot:
    def test_add_manual_shot_without_llm(self, client):
        """手动镜头（R6 堵点：LLM 不可用时工作台不被阻塞）。"""
        pid = client.post("/api/v1/studio/projects", json={"title": "T"}).json()["data"]["project"]["id"]
        ep = client.store.add_episode(pid, {"number": 1, "title": "e"})
        r = client.post(f"/api/v1/studio/episodes/{ep['id']}/storyboards/manual",
                        json={"description": "主角推门", "image_prompt": "man enters"})
        assert r.status_code == 200
        sb = r.json()["data"]["storyboard"]
        assert sb["number"] == 1 and sb["episode_id"] == ep["id"]
        # 空镜头拒绝：三提示字段全空
        r2 = client.post(f"/api/v1/studio/episodes/{ep['id']}/storyboards/manual", json={"title": "x"})
        assert r2.status_code == 400
