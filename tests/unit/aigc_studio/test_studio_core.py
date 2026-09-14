# -*- coding: utf-8 -*-
"""R3：aigc_studio（创作专区后端域）核心契约。

功能规格对标 huobao-drama（CC BY-NC-SA：仅功能对齐，实现全部自研）：
- store：9 表 SQLite（WAL）+ 属主隔离（deny 与不存在同构 404 语义由 API 层做）；
- llm.extract_json：LLM 输出的稳健 JSON 抽取（对象/数组、坏输出返回 None 不炸）；
- services：分集拆解→资产抽取（去重）→分镜→批量首帧（@角色参考图 + 风格/画幅
  项目锁注入）→i2v 提交（账本 batch_key 关联，恢复循环收口）→合并（FFmpeg
  三态诚实降级）。LLM/图像/视频均支持注入 fake（网络零依赖单测）。
"""
from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.timeout(60)


@pytest.fixture()
def store(tmp_path):
    from neurova.aigc_studio.store import StudioStore

    return StudioStore(db_path=str(tmp_path / "studio.db"))


def _project(store, owner="u1"):
    return store.create_project(
        owner_user_id=owner, title="龙王归来", genre="都市逆袭",
        style="国风水墨", aspect_ratio="9:16", total_episodes=1,
    )


class TestStore:
    def test_project_crud_and_owner(self, store):
        p = _project(store)
        assert p["id"] and p["status"] == "draft"
        assert store.get_project(p["id"], "u1")["title"] == "龙王归来"
        assert store.get_project(p["id"], "u2") is None  # 属主隔离
        store.update_project(p["id"], "u1", {"description": "x"})
        assert store.get_project(p["id"], "u1")["description"] == "x"
        store.soft_delete(p["id"], "u1")
        assert store.get_project(p["id"], "u1") is None
        assert [x["id"] for x in store.list_projects("u1")] == []

    def test_episodes_storyboards_json_fields(self, store):
        p = _project(store)
        ep = store.add_episode(p["id"], {"number": 1, "title": "第1集"})
        sb = store.add_storyboard(ep["id"], {
            "number": 1, "description": "主角推门",
            "characters": [{"name": "林凡", "id": "c1"}],
        })
        assert json.loads(store.get_storyboard(sb["id"])["characters_json"])[0]["name"] == "林凡"
        assert store.list_storyboards(ep["id"])[0]["number"] == 1


class TestExtractJson:
    def test_object_and_array_and_noise(self):
        from neurova.aigc_studio.llm import extract_json

        assert extract_json('前缀 {"a": 1} 后缀', "object") == {"a": 1}
        assert extract_json('```json\n[{"x":1}]\n```', "array") == [{"x": 1}]
        assert extract_json("完全没有 JSON", "object") is None
        assert extract_json("", "array") is None


class TestScriptSplit:
    @pytest.mark.asyncio
    async def test_split_episodes_with_fake_llm(self, store):
        from neurova.aigc_studio import services

        p = _project(store)
        episodes = [{"number": 1, "title": "受辱", "content": "主角被羞辱",
                     "characters": ["林凡"], "scenes": ["客厅"], "props": ["请柬"]}]

        async def fake_llm(prompt, system_prompt=""):
            return "分析...\n" + json.dumps(episodes, ensure_ascii=False)

        eps = await services.split_script(store, p["id"], "小说正文", llm=fake_llm)
        assert len(eps) == 1
        assert store.list_episodes(p["id"])[0]["title"] == "受辱"

    @pytest.mark.asyncio
    async def test_bad_llm_output_falls_back_to_source(self, store):
        from neurova.aigc_studio import services

        p = _project(store)

        async def garbage(prompt, system_prompt=""):
            return "纯文本没有结构"

        eps = await services.split_script(store, p["id"], "第一段剧情。", llm=garbage)
        assert len(eps) == 1
        assert "第一段剧情" in eps[0]["content"]  # 兜底：原文作单集


class TestExtractAssets:
    @pytest.mark.asyncio
    async def test_dedup_existing_names(self, store):
        from neurova.aigc_studio import services

        p = _project(store)
        ep = store.add_episode(p["id"], {"number": 1, "title": "e1"})
        store.add_character(p["id"], {"name": "林凡", "description": "既有"})
        assets = {
            "characters": [{"name": "林凡", "description": "重复应跳过"},
                           {"name": "苏瑶", "description": "新增"}],
            "scenes": [{"location": "客厅", "time": "夜", "prompt": "p", "lighting": "暖"}],
            "props": [{"name": "请柬", "description": "烫金"}],
        }

        async def fake_llm(prompt, system_prompt=""):
            return json.dumps(assets, ensure_ascii=False)

        result = await services.extract_assets(store, p["id"], ep["id"], llm=fake_llm)
        assert result["characters_added"] == 1  # 林凡去重
        assert result["scenes_added"] == 1
        assert len(store.list_characters(p["id"])) == 2


class TestShotImageGeneration:
    @pytest.mark.asyncio
    async def test_ref_injection_and_style_lock_and_per_shot_fail_isolated(
        self, store, tmp_path, monkeypatch,
    ):
        from neurova.aigc_studio import services
        from neurova.llm.generators import protocols as proto_mod
        from neurova.llm.generators import runtime as gen_runtime
        from neurova.llm.generators.protocols import ProtocolCredentials

        p = _project(store)
        ep = store.add_episode(p["id"], {"number": 1, "title": "e1"})
        c = store.add_character(p["id"], {"name": "林凡", "image_path": str(tmp_path / "c.png")})
        (tmp_path / "c.png").write_bytes(b"REF")
        sb1 = store.add_storyboard(ep["id"], {
            "number": 1, "image_prompt": "man enters",
            "characters_json": json.dumps([{"name": c["name"], "id": c["id"]}]),
        })
        sb2 = store.add_storyboard(ep["id"], {"number": 2})  # 无任何提示词 → 诚实跳过

        monkeypatch.setattr(
            gen_runtime, "resolve_generation_creds",
            lambda hint, model, pid, ak, bu, db: ProtocolCredentials(
                api_key="k", base_url="https://x", model="seedream", protocol="ark"))

        captured = {}

        async def fake_gen(creds, prompt, **kw):
            captured["prompt"] = prompt
            captured["refs"] = kw.get("ref_images")
            return {"images": ["http://cdn/1.png"], "task_id": None, "raw": {}}

        async def fake_persist(url, kind, task_id, index, out_dir=None):
            f = tmp_path / f"{task_id}.png"
            f.write_bytes(b"IMG")
            return str(f)

        monkeypatch.setattr(proto_mod, "generate_image", fake_gen)
        monkeypatch.setattr(gen_runtime, "persist_media", fake_persist)

        stats = await services.generate_shot_images(store, p["id"], ep["id"])
        assert stats["done"] == 1
        assert stats["failed"] == 1  # 无提示词镜头诚实跳过标注，不中断整批
        assert stats["skipped_no_prompt"] == 1
        rec = store.get_storyboard(sb1["id"])
        assert rec["first_frame_path"]
        assert rec["status"] == "image_ready"
        # @角色参考图透传 + 风格/画幅项目锁注入
        assert captured["refs"] == [str(tmp_path / "c.png")]
        assert "国风水墨" in captured["prompt"]
        assert "9:16" in captured["prompt"]
        assert store.get_storyboard(sb2["id"])["status"] == "failed"


class TestVideoSubmit:
    @pytest.mark.asyncio
    async def test_i2v_submit_links_ledger(self, store, tmp_path, monkeypatch):
        from neurova.aigc_studio import services
        from neurova.llm.generators import protocols as proto_mod
        from neurova.llm.generators import runtime as gen_runtime
        from neurova.llm.generators import task_ledger as ledger_mod
        from neurova.llm.generators.protocols import ProtocolCredentials
        from neurova.llm.generators.task_ledger import GenerationTaskLedger

        p = _project(store)
        ep = store.add_episode(p["id"], {"number": 1, "title": "e1"})
        frame = tmp_path / "f.png"
        frame.write_bytes(b"F")
        sb = store.add_storyboard(ep["id"], {
            "number": 1, "video_prompt": "推门而入，环视全场",
            "first_frame_path": str(frame),
        })
        led = GenerationTaskLedger(path=str(tmp_path / "led.json"))
        monkeypatch.setattr(ledger_mod, "_ledger", led)
        monkeypatch.setattr(
            gen_runtime, "resolve_generation_creds",
            lambda hint, model, pid, ak, bu, db: ProtocolCredentials(
                api_key="k", base_url="https://ds", model="wan", protocol="wan"))

        async def fake_submit(creds, prompt, **kw):
            return {"task_id": "remote-9", "poll_url": "https://ds/tasks/remote-9", "raw": {}}

        monkeypatch.setattr(proto_mod, "submit_video", fake_submit)
        stats = await services.generate_shot_videos(store, p["id"], ep["id"])
        assert stats["submitted"] == 1
        rec = store.get_storyboard(sb["id"])
        assert rec["video_status"] == "running"
        task = led.get(rec["ledger_task_id"])
        assert task is not None and task.batch_key == ep["id"]
        assert task.source == "workflow" or task.source == "rest"


class TestMerge:
    @pytest.mark.asyncio
    async def test_no_ffmpeg_manifest(self, store, monkeypatch, tmp_path):
        import shutil

        from neurova.aigc_studio import services

        monkeypatch.setattr(shutil, "which", lambda x: None)
        p = _project(store)
        ep = store.add_episode(p["id"], {"number": 1, "title": "e1"})
        frame = tmp_path / "f.png"
        frame.write_bytes(b"IMG")
        store.add_storyboard(ep["id"], {
            "number": 1, "description": "d", "video_prompt": "vp",
            "first_frame_path": str(frame),
        })
        res = await services.merge_episode(store, p["id"], ep["id"])
        assert res["composed"] is False
        assert res["mode"] == "slideshow_manifest"
        assert res["merge"]["id"]
        m = store.get_merge(res["merge"]["id"])
        assert m["status"] == "manifest"

    @pytest.mark.asyncio
    async def test_only_ready_items_or_error(self, store, monkeypatch, tmp_path):
        import shutil

        from neurova.aigc_studio import services

        monkeypatch.setattr(shutil, "which", lambda x: "/usr/bin/ffmpeg")
        p = _project(store)
        ep = store.add_episode(p["id"], {"number": 1, "title": "e1"})
        # 没有任何产物 → 诚实报错，不假合成
        res = await services.merge_episode(store, p["id"], ep["id"])
        assert res["ok"] is False
        assert "无就绪产物" in res["error"]
