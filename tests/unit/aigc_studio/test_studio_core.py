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
from pathlib import Path

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
    @pytest.fixture(autouse=True)
    def _no_auto_route(self, monkeypatch):
        """本类只测注入/风格锁/隔离，显式关闭 auto 路由不打真实 router。"""
        from neurova.aigc_studio import services
        monkeypatch.setattr(services, "_auto_route", lambda kind: ("", ""))

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
    @pytest.fixture(autouse=True)
    def _no_auto_route(self, monkeypatch):
        from neurova.aigc_studio import services
        monkeypatch.setattr(services, "_auto_route", lambda kind: ("", ""))

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


    @pytest.mark.asyncio
    async def test_auto_route_used_when_no_selection(self, store, tmp_path, monkeypatch):
        """不指定 model/provider_id → 经 LLMRouter 能力路由取模型+服务商，hint 随之推导。"""
        from neurova.aigc_studio import services
        from neurova.llm.generators import runtime as gen_runtime
        from neurova.llm.generators import task_ledger as ledger_mod
        from neurova.llm.generators.protocols import ProtocolCredentials
        from neurova.llm.generators.task_ledger import GenerationTaskLedger

        led = GenerationTaskLedger(path=str(tmp_path / "led.json"))
        monkeypatch.setattr(ledger_mod, "_ledger", led)
        monkeypatch.setattr(services, "_auto_route",
                            lambda kind: ("seedance-2-0", "prov-seed"))
        seen = {}

        def fake_resolve(hint, model, provider_id, api_key, base_url, default_base):
            seen["args"] = (hint, model, provider_id)
            return ProtocolCredentials(api_key="k", base_url="https://ark",
                                       model=model, protocol=hint)

        async def fake_submit(creds, prompt, **kw):
            return {"task_id": "r5", "poll_url": "", "raw": {}}

        monkeypatch.setattr(gen_runtime, "resolve_generation_creds", fake_resolve)
        import neurova.llm.provider_manager as pm_mod
        prov = type("P", (), {"base_url": "https://ark.cn-beijing.volces.com/api/v3"})()
        monkeypatch.setattr(pm_mod, "get_provider_manager",
                            lambda: type("M", (), {"get_provider": lambda self, pid: prov})())
        from neurova.llm.generators import protocols as proto_mod
        monkeypatch.setattr(proto_mod, "submit_video", fake_submit)
        p = _project(store)
        ep = store.add_episode(p["id"], {"number": 1, "title": "e"})
        store.add_storyboard(ep["id"], {"number": 1, "video_prompt": "vp"})
        await services.generate_shot_videos(store, p["id"], ep["id"])  # 全默认不选模型
        hint, model, pid = seen["args"]
        assert pid == "prov-seed" and model == "seedance-2-0"
        assert hint == "seedance2"  # volces base_url → seedance2 协议（非旧默认 wan）


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


class TestA1LastFrame:
    """A1：镜头尾帧列 + 服务透传（台账 A1 全链路，前端另有页面测试）。"""

    def test_storyboard_has_end_frame_column(self, store):
        ep = store.add_episode("p1", {"number": 1, "title": "e"})
        sb = store.add_storyboard(ep["id"], {"number": 1, "end_frame_path": "/x/z.png"})
        assert store.get_storyboard(sb["id"])["end_frame_path"] == "/x/z.png"

    @pytest.mark.asyncio
    async def test_generate_videos_passes_last_frame(self, store, tmp_path, monkeypatch):
        from neurova.aigc_studio import services
        from neurova.llm.generators import protocols as proto_mod
        from neurova.llm.generators import runtime as gen_runtime
        from neurova.llm.generators import task_ledger as ledger_mod
        from neurova.llm.generators.protocols import ProtocolCredentials
        from neurova.llm.generators.task_ledger import GenerationTaskLedger

        led = GenerationTaskLedger(path=str(tmp_path / "led.json"))
        monkeypatch.setattr(ledger_mod, "_ledger", led)
        monkeypatch.setattr(
            gen_runtime, "resolve_generation_creds",
            lambda hint, model, pid, ak, bu, db: ProtocolCredentials(
                api_key="k", base_url="https://ark", model="seedance", protocol="seedance2"))
        seen = {}

        async def fake_submit(creds, prompt, **kw):
            seen["last_frame"] = kw.get("last_frame")
            return {"task_id": "r1", "poll_url": "https://ark/t/r1", "raw": {}}

        monkeypatch.setattr(proto_mod, "submit_video", fake_submit)
        p = _project(store)
        ep = store.add_episode(p["id"], {"number": 1, "title": "e"})
        f1 = tmp_path / "a.png"; f1.write_bytes(b"A")
        f2 = tmp_path / "z.png"; f2.write_bytes(b"Z")
        store.add_storyboard(ep["id"], {
            "number": 1, "video_prompt": "vp",
            "first_frame_path": str(f1), "end_frame_path": str(f2)})
        await services.generate_shot_videos(store, p["id"], ep["id"],
                                            provider="seedance")
        assert seen["last_frame"] == str(f2)

    @pytest.mark.asyncio
    async def test_generate_videos_without_end_frame_passes_none(self, store, tmp_path, monkeypatch):
        from neurova.aigc_studio import services
        from neurova.llm.generators import protocols as proto_mod
        from neurova.llm.generators import runtime as gen_runtime
        from neurova.llm.generators import task_ledger as ledger_mod
        from neurova.llm.generators.protocols import ProtocolCredentials
        from neurova.llm.generators.task_ledger import GenerationTaskLedger

        led = GenerationTaskLedger(path=str(tmp_path / "led.json"))
        monkeypatch.setattr(ledger_mod, "_ledger", led)
        monkeypatch.setattr(
            gen_runtime, "resolve_generation_creds",
            lambda *a, **k: ProtocolCredentials(api_key="k", base_url="https://x",
                                                model="m", protocol="wan"))
        seen = {}

        async def fake_submit(creds, prompt, **kw):
            seen["last_frame"] = kw.get("last_frame", "SENTINEL")
            return {"task_id": "r2", "poll_url": "", "raw": {}}

        monkeypatch.setattr(proto_mod, "submit_video", fake_submit)
        p = _project(store)
        ep = store.add_episode(p["id"], {"number": 1, "title": "e"})
        f1 = tmp_path / "a.png"; f1.write_bytes(b"A")
        store.add_storyboard(ep["id"], {"number": 1, "video_prompt": "vp",
                                        "first_frame_path": str(f1)})
        await services.generate_shot_videos(store, p["id"], ep["id"])
        assert seen["last_frame"] in (None, "SENTINEL")  # 缺省不传或 None，语义等价

    @pytest.mark.asyncio
    async def test_generate_videos_records_ignored_params(self, store, tmp_path, monkeypatch):
        """A1 放大视角：Studio 提交账本与 REST 端点同契约——WAN 无尾帧通道时
        submit_video 返回的 ignored_params 必须写进 TaskRecord（记录面板可见，
        不静默丢弃）。REST 侧已由 test_generation_lastframe 覆盖，此处补画布侧。"""
        from neurova.aigc_studio import services
        from neurova.llm.generators import protocols as proto_mod
        from neurova.llm.generators import runtime as gen_runtime
        from neurova.llm.generators import task_ledger as ledger_mod
        from neurova.llm.generators.protocols import ProtocolCredentials
        from neurova.llm.generators.task_ledger import GenerationTaskLedger

        led = GenerationTaskLedger(path=str(tmp_path / "led.json"))
        monkeypatch.setattr(ledger_mod, "_ledger", led)
        monkeypatch.setattr(
            gen_runtime, "resolve_generation_creds",
            lambda *a, **k: ProtocolCredentials(api_key="k", base_url="https://x",
                                                model="m", protocol="wan"))

        async def fake_submit(creds, prompt, **kw):
            out = {"task_id": "r9", "poll_url": "", "raw": {}}
            if kw.get("last_frame"):
                out["ignored_params"] = ["last_frame"]  # 模拟 WAN 分支真实返回
            return out

        monkeypatch.setattr(proto_mod, "submit_video", fake_submit)
        p = _project(store)
        ep = store.add_episode(p["id"], {"number": 1, "title": "e"})
        f1 = tmp_path / "a.png"; f1.write_bytes(b"A")
        f2 = tmp_path / "z.png"; f2.write_bytes(b"Z")
        store.add_storyboard(ep["id"], {
            "number": 1, "video_prompt": "vp",
            "first_frame_path": str(f1), "end_frame_path": str(f2)})
        await services.generate_shot_videos(store, p["id"], ep["id"],
                                            provider="wan")
        rec = led.list()[0]
        assert rec.ignored_params == "last_frame"


class TestModelRouting:
    """模型选择全链（用户口径 2026-09-14）：Studio 生成支持 model+provider_id
    透传，协议 hint 按服务商 base_url 推导（不再硬编码 ark/wan）。"""

    @pytest.mark.asyncio
    async def test_generate_images_passes_provider_id_and_derives_hint(self, store, tmp_path, monkeypatch):
        from neurova.aigc_studio import services
        from neurova.llm.generators import runtime as gen_runtime
        import neurova.llm.provider_manager as pm_mod
        import neurova.llm.generators.protocols as proto_mod

        seen = {}

        def fake_resolve(hint, model, provider_id, api_key, base_url, default_base):
            seen["args"] = (hint, model, provider_id)
            return gen_runtime.ProtocolCredentials(api_key="k", base_url="https://b",
                                                   model=model, protocol=hint)

        async def fake_gen(creds, prompt, **kw):
            return {"images": ["http://c/1.png"], "task_id": "t1", "raw": {}}

        async def fake_persist(url, kind, task_id, index, out_dir=None):
            return str(tmp_path / "o.png")

        prov = type("P", (), {"base_url": "https://ark.cn-beijing.volces.com/api/v3",
                              "api_key": "enc", "default_model": "doub-seedream"})()
        monkeypatch.setattr(gen_runtime, "resolve_generation_creds", fake_resolve)
        monkeypatch.setattr(proto_mod, "generate_image", fake_gen)
        monkeypatch.setattr(gen_runtime, "persist_media", fake_persist)
        monkeypatch.setattr(pm_mod, "get_provider_manager",
                            lambda: type("M", (), {"get_provider": lambda self, pid: prov})())
        p = _project(store)
        ep = store.add_episode(p["id"], {"number": 1, "title": "e"})
        store.add_storyboard(ep["id"], {"number": 1, "image_prompt": "ip"})
        await services.generate_shot_images(store, p["id"], ep["id"],
                                            model="doub-seedream-4", provider_id="prov-ark")
        hint, model, pid = seen["args"]
        assert pid == "prov-ark"
        assert model == "doub-seedream-4"
        assert hint == "ark"  # base_url volces.com → ark 协议（resolve_image_protocol 推导）

    @pytest.mark.asyncio
    async def test_generate_videos_passes_provider_id(self, store, tmp_path, monkeypatch):
        from neurova.aigc_studio import services
        from neurova.llm.generators import protocols as proto_mod
        from neurova.llm.generators import runtime as gen_runtime
        from neurova.llm.generators import task_ledger as ledger_mod
        from neurova.llm.generators.protocols import ProtocolCredentials
        from neurova.llm.generators.task_ledger import GenerationTaskLedger

        led = GenerationTaskLedger(path=str(tmp_path / "led.json"))
        monkeypatch.setattr(ledger_mod, "_ledger", led)
        seen = {}

        def fake_resolve(hint, model, provider_id, api_key, base_url, default_base):
            seen["args"] = (hint, model, provider_id)
            return ProtocolCredentials(api_key="k", base_url="https://ark",
                                       model=model, protocol=hint)

        async def fake_submit(creds, prompt, **kw):
            return {"task_id": "r1", "poll_url": "", "raw": {}}

        monkeypatch.setattr(gen_runtime, "resolve_generation_creds", fake_resolve)
        monkeypatch.setattr(proto_mod, "submit_video", fake_submit)
        p = _project(store)
        ep = store.add_episode(p["id"], {"number": 1, "title": "e"})
        f1 = tmp_path / "a.png"; f1.write_bytes(b"A")
        store.add_storyboard(ep["id"], {"number": 1, "video_prompt": "vp",
                                        "first_frame_path": str(f1)})
        await services.generate_shot_videos(store, p["id"], ep["id"],
                                            model="seedance-2-0", provider_id="prov-seed")
        assert seen["args"][2] == "prov-seed"
        assert seen["args"][1] == "seedance-2-0"

    @pytest.mark.asyncio
    async def test_no_provider_id_keeps_legacy_hint(self, store, tmp_path, monkeypatch):
        """auto 路由不可得（无路由器）→ 回落旧口径 hint=provider 映射。"""
        from neurova.aigc_studio import services
        monkeypatch.setattr(services, "_auto_route", lambda kind: ("", ""))
        from neurova.llm.generators import protocols as proto_mod
        from neurova.llm.generators import runtime as gen_runtime
        from neurova.llm.generators import task_ledger as ledger_mod
        from neurova.llm.generators.protocols import ProtocolCredentials
        from neurova.llm.generators.task_ledger import GenerationTaskLedger

        led = GenerationTaskLedger(path=str(tmp_path / "led.json"))
        monkeypatch.setattr(ledger_mod, "_ledger", led)
        seen = {}

        def fake_resolve(hint, model, provider_id, api_key, base_url, default_base):
            seen["args"] = (hint, model, provider_id)
            return ProtocolCredentials(api_key="k", base_url="https://x",
                                       model="m", protocol=hint)

        async def fake_submit(creds, prompt, **kw):
            return {"task_id": "r2", "poll_url": "", "raw": {}}

        monkeypatch.setattr(gen_runtime, "resolve_generation_creds", fake_resolve)
        monkeypatch.setattr(proto_mod, "submit_video", fake_submit)
        p = _project(store)
        ep = store.add_episode(p["id"], {"number": 1, "title": "e"})
        store.add_storyboard(ep["id"], {"number": 1, "video_prompt": "vp"})
        await services.generate_shot_videos(store, p["id"], ep["id"], provider="wan")
        assert seen["args"][0] == "wan"
        assert seen["args"][2] is None


class TestA5SubtitleBurn:
    """A5：concat 成功后第二步烧字幕；字体缺失/烧录失败均诚实降级（台账验收）。"""

    @staticmethod
    def _setup_video_shot(store, tmp_path, monkeypatch):
        """一镜有视频 + 旁白（触发 srt）；产物目录与 ffmpeg 重定向 tmp。"""
        from neurova.aigc_studio import services
        from neurova.llm.generators import runtime as gen_runtime

        monkeypatch.setattr(gen_runtime, "GENERATION_OUTPUT_DIR", tmp_path)
        p = _project(store)
        ep = store.add_episode(p["id"], {"number": 1, "title": "e1"})
        v = tmp_path / "shot1.mp4"
        v.write_bytes(b"VID")
        store.add_storyboard(ep["id"], {
            "number": 1, "description": "主角推门", "video_prompt": "vp",
            "narration": "他回来了", "video_path": str(v)})
        return services, p, ep

    @staticmethod
    def _fake_run_factory(burn_ok=True):
        import subprocess as sp

        calls = []

        def fake_run(cmd, **kw):
            calls.append(list(cmd))
            # concat 步：-c copy 的最后一个参数是输出；烧录步：含 -vf
            out = cmd[-1]
            if "-vf" not in cmd or burn_ok:
                open(out, "wb").write(b"MPEG")
            return type("P", (), {"returncode": 0 if (("-vf" not in cmd) or burn_ok) else 1,
                                  "stderr": b"" if burn_ok else b"Subtitles filter not found"})()

        return sp, calls, fake_run

    @pytest.mark.asyncio
    async def test_concat_then_burn_two_step(self, store, tmp_path, monkeypatch):
        services, p, ep = self._setup_video_shot(store, tmp_path, monkeypatch)
        import neurova.core.ffmpeg as ff
        monkeypatch.setattr(ff, "resolve_ffmpeg_path", lambda preferred="": "/x/ffmpeg")
        monkeypatch.setattr(ff, "has_cjk_font", lambda: True)
        sp, calls, fake_run = self._fake_run_factory()
        monkeypatch.setattr(sp, "run", fake_run)

        res = await services.merge_episode(store, p["id"], ep["id"])
        assert res["composed"] is True
        assert res["subtitle_burned"] is True
        assert len(calls) == 2  # concat + 烧录
        assert any("-vf" in c for c in calls)
        assert str(calls[1][calls[1].index("-vf") + 1]).startswith("subtitles=filename=")
        assert res["merge"]["output_path"].endswith("_sub.mp4")
        assert Path(res["merge"]["output_path"]).is_file()

    @pytest.mark.asyncio
    async def test_missing_font_skips_burn_with_warning(self, store, tmp_path, monkeypatch):
        services, p, ep = self._setup_video_shot(store, tmp_path, monkeypatch)
        import neurova.core.ffmpeg as ff
        monkeypatch.setattr(ff, "resolve_ffmpeg_path", lambda preferred="": "/x/ffmpeg")
        monkeypatch.setattr(ff, "has_cjk_font", lambda: False)
        sp, calls, fake_run = self._fake_run_factory()
        monkeypatch.setattr(sp, "run", fake_run)

        res = await services.merge_episode(store, p["id"], ep["id"])
        assert res["composed"] is True
        assert res["subtitle_burned"] is False
        assert "字体" in res["warning"]
        assert len(calls) == 1  # 无烧录步
        assert not any("-vf" in c for c in calls)

    @pytest.mark.asyncio
    async def test_burn_failure_falls_back_to_plain(self, store, tmp_path, monkeypatch):
        services, p, ep = self._setup_video_shot(store, tmp_path, monkeypatch)
        import neurova.core.ffmpeg as ff
        monkeypatch.setattr(ff, "resolve_ffmpeg_path", lambda preferred="": "/x/ffmpeg")
        monkeypatch.setattr(ff, "has_cjk_font", lambda: True)

        def fake_run(cmd, **kw):
            out = cmd[-1]
            if "-vf" in cmd:
                return type("P", (), {"returncode": 1, "stderr": b"open filter failed"})()
            open(out, "wb").write(b"MPEG")
            return type("P", (), {"returncode": 0, "stderr": b""})()

        import subprocess as sp
        monkeypatch.setattr(sp, "run", fake_run)
        res = await services.merge_episode(store, p["id"], ep["id"])
        assert res["composed"] is True          # 无字幕成片照常交付
        assert res["subtitle_burned"] is False
        assert "字幕" in res["warning"]
        assert Path(res["merge"]["output_path"]).is_file()
