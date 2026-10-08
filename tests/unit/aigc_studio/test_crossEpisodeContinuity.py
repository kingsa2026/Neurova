# -*- coding: utf-8 -*-
"""C1（=§6-78 的 H 条〔H2-4 提交侧诚实形态〕+ I 条〔H2-7 零读者列〕）：
跨集资产连续性的读数面与消费侧硬阻断。

本仓自己的断点（与任何外部项目无关）：
- `characters.seed_value`、`storyboards.scene_id`（空列）、`storyboards.atmosphere`、
  `storyboards.props_json`——四路都**只写不读**，于是"跨集同一角色/同一场景"的连续性
  只存在于表里，生成侧（`generate_shot_images`/`generate_shot_videos`）从不取用；
- 镜头引用的角色**没有定妆图**时，`generate_shot_images` 旧的 `refs` 推导是
  "有就带上、没有就丢"，静默出的是与全集其他镜头不同的一张脸，且不留任何标记；
- 无首帧仍提交 i2v → 静默退化成 t2v 并写 `running`；
- `persist_media` 把 0 字节回包也当产物落盘并返回路径 → 上游一律记成成功。

判据一律打在**行为**上（生成侧实际发出的提示词/参考图/seed、以及"该镜根本不该发出请求"），
不打"库里有没有这一列"。
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


def _project(store):
    return store.create_project(owner_user_id="u1", title="连续性", genre="都市",
                                style="国风水墨", aspect_ratio="9:16")


@pytest.fixture()
def imageProbe(monkeypatch, tmp_path):
    """真协议替身只记录"实际发出的东西"；凭据解析走同一注入面。"""
    from neurova.llm.generators import protocols as proto_mod
    from neurova.llm.generators import runtime as gen_runtime
    from neurova.llm.generators.protocols import ProtocolCredentials

    seen = {"calls": [], "persisted": {}}

    def fake_resolve(hint, model, provider_id, api_key, base_url, default_base):
        return ProtocolCredentials(api_key="k", base_url="https://x", model="m",
                                   protocol=hint)

    async def fake_gen(creds, prompt, **kw):
        seen["calls"].append({"prompt": prompt, "refs": kw.get("ref_images") or [],
                              "seed": kw.get("seed")})
        return {"images": ["http://cdn/1.png"], "task_id": "t", "raw": {}}

    async def fake_persist(url, kind, task_id, index, out_dir=None):
        payload = seen["persisted"].get("payload", b"IMG")
        f = tmp_path / f"{task_id}_{index}.png"
        f.write_bytes(payload)
        return str(f)

    monkeypatch.setattr(gen_runtime, "resolve_generation_creds", fake_resolve)
    monkeypatch.setattr(proto_mod, "generate_image", fake_gen)
    monkeypatch.setattr(gen_runtime, "persist_media", fake_persist)
    return seen


@pytest.fixture()
def videoProbe(monkeypatch, tmp_path):
    from neurova.llm.generators import protocols as proto_mod
    from neurova.llm.generators import runtime as gen_runtime
    from neurova.llm.generators import task_ledger as ledger_mod
    from neurova.llm.generators.protocols import ProtocolCredentials
    from neurova.llm.generators.task_ledger import GenerationTaskLedger

    led = GenerationTaskLedger(path=str(tmp_path / "led.json"))
    monkeypatch.setattr(ledger_mod, "_ledger", led)
    seen = {"calls": []}

    def fake_resolve(hint, model, provider_id, api_key, base_url, default_base):
        return ProtocolCredentials(api_key="k", base_url="https://x", model="m",
                                   protocol=hint)

    async def fake_submit(creds, prompt, **kw):
        seen["calls"].append({"prompt": prompt, "refs": kw.get("ref_images") or []})
        return {"task_id": "r1", "poll_url": "", "raw": {}}

    monkeypatch.setattr(gen_runtime, "resolve_generation_creds", fake_resolve)
    monkeypatch.setattr(proto_mod, "submit_video", fake_submit)
    return seen


class TestShotReadsProjectAssets:
    """镜头生成必须把项目级资产（场景/氛围/道具）读进实际发出的提示词与参考图。"""

    @pytest.mark.asyncio
    async def testScenePromptAndLightingReachTheShot(self, store, imageProbe):
        from neurova.aigc_studio import services

        p = _project(store)
        ep = store.add_episode(p["id"], {"number": 1, "title": "e1"})
        scene = store.add_scene(p["id"], {
            "episode_id": ep["id"], "location": "老宅厅堂", "time": "夜",
            "prompt": "old mansion hall, dim lamp", "lighting": "low key amber"})
        store.add_storyboard(ep["id"], {
            "number": 1, "image_prompt": "hero steps in", "scene_id": scene["id"]})

        await services.generate_shot_images(store, p["id"], ep["id"])
        sent = imageProbe["calls"][0]["prompt"]
        assert "old mansion hall, dim lamp" in sent
        assert "low key amber" in sent

    @pytest.mark.asyncio
    async def testSceneReferenceImageJoinsRefs(self, store, imageProbe, tmp_path):
        from neurova.aigc_studio import services

        p = _project(store)
        ep = store.add_episode(p["id"], {"number": 1, "title": "e1"})
        img = tmp_path / "scene.png"
        img.write_bytes(b"S")
        scene = store.add_scene(p["id"], {"location": "天台", "prompt": "roof",
                                          "image_path": str(img)})
        store.add_storyboard(ep["id"], {"number": 1, "image_prompt": "wide",
                                        "scene_id": scene["id"]})
        await services.generate_shot_images(store, p["id"], ep["id"])
        assert str(img) in imageProbe["calls"][0]["refs"]

    @pytest.mark.asyncio
    async def testAtmosphereReachesBothImageAndVideoPrompts(self, store, imageProbe, videoProbe, tmp_path):
        from neurova.aigc_studio import services

        p = _project(store)
        ep = store.add_episode(p["id"], {"number": 1, "title": "e1"})
        frame = tmp_path / "f.png"
        frame.write_bytes(b"F")
        store.add_storyboard(ep["id"], {
            "number": 1, "image_prompt": "man turns", "video_prompt": "slow push in",
            "atmosphere": "压抑的对峙", "first_frame_path": str(frame)})

        await services.generate_shot_images(store, p["id"], ep["id"])
        assert "压抑的对峙" in imageProbe["calls"][0]["prompt"]

        await services.generate_shot_videos(store, p["id"], ep["id"])
        assert "压抑的对峙" in videoProbe["calls"][0]["prompt"]

    @pytest.mark.asyncio
    async def testPropDescriptorAndPortraitAreConsumed(self, store, imageProbe, tmp_path):
        from neurova.aigc_studio import services

        p = _project(store)
        ep = store.add_episode(p["id"], {"number": 1, "title": "e1"})
        propImg = tmp_path / "prop.png"
        propImg.write_bytes(b"P")
        prop = store.add_prop(p["id"], {"name": "请柬", "description": "gold-foil invitation",
                                        "image_path": str(propImg)})
        store.add_storyboard(ep["id"], {
            "number": 1, "image_prompt": "hand holds",
            "props_json": json.dumps([{"name": "请柬", "id": prop["id"]}])})

        await services.generate_shot_images(store, p["id"], ep["id"])
        assert "gold-foil invitation" in imageProbe["calls"][0]["prompt"]
        assert str(propImg) in imageProbe["calls"][0]["refs"]

    @pytest.mark.asyncio
    async def testPersistedSeedIsReadBackForAssetRegeneration(self, store, imageProbe):
        """定妆 seed 的单一事实源是库：重跑读回同一枚，不再每次重算。"""
        import zlib

        from neurova.aigc_studio import services

        p = _project(store)
        c = store.add_character(p["id"], {"name": "林凡", "final_prompt": "portrait"})
        store.update_asset_row("characters", c["id"], {"seed_value": "424242"})

        await services.generate_asset_images(store, p["id"])
        assert imageProbe["calls"][0]["seed"] == 424242
        assert imageProbe["calls"][0]["seed"] != zlib.crc32(c["id"].encode("utf-8")) % 10 ** 8

    @pytest.mark.asyncio
    async def testAbsentSeedIsDerivedOnceAndPersisted(self, store, imageProbe):
        from neurova.aigc_studio import services

        p = _project(store)
        c = store.add_character(p["id"], {"name": "苏瑶", "final_prompt": "portrait"})
        await services.generate_asset_images(store, p["id"])
        first = imageProbe["calls"][0]["seed"]
        assert str(first) == store.get_asset_row("characters", c["id"])["seed_value"]

    @pytest.mark.asyncio
    async def testShotWithoutAssetReferencesIsNotBlocked(self, store, imageProbe):
        """反向对照：闸只咬"引用了却取不到"，不得把无引用的镜头一起判红。"""
        from neurova.aigc_studio import services

        p = _project(store)
        ep = store.add_episode(p["id"], {"number": 1, "title": "e1"})
        sb = store.add_storyboard(ep["id"], {"number": 1, "image_prompt": "empty street"})
        stats = await services.generate_shot_images(store, p["id"], ep["id"])
        assert stats["done"] == 1
        assert store.get_storyboard(sb["id"])["status"] == "image_ready"


class TestContinuityBlockingGate:
    """引用取不到时**根本不该发出请求**，并点名成因（教义第 2 条的诚实形态）。"""

    @pytest.mark.asyncio
    async def testCharacterWithoutPortraitBlocksBeforeApiCall(self, store, imageProbe):
        from neurova.aigc_studio import services

        p = _project(store)
        ep = store.add_episode(p["id"], {"number": 1, "title": "e1"})
        c = store.add_character(p["id"], {"name": "林凡"})  # 未定妆
        sb = store.add_storyboard(ep["id"], {
            "number": 1, "image_prompt": "hero close up",
            "characters_json": json.dumps([{"name": c["name"], "id": c["id"]}])})

        stats = await services.generate_shot_images(store, p["id"], ep["id"])
        assert imageProbe["calls"] == []          # 一次请求都没发出
        row = store.get_storyboard(sb["id"])
        assert row["status"] == "failed"
        assert "林凡" in row["error"] and "定妆" in row["error"]
        assert stats["failed"] == 1 and stats["blocked_no_asset"] == 1

    @pytest.mark.asyncio
    async def testCharacterPortraitMissingOnDiskBlocks(self, store, imageProbe, tmp_path):
        from neurova.aigc_studio import services

        p = _project(store)
        ep = store.add_episode(p["id"], {"number": 1, "title": "e1"})
        gone = tmp_path / "deleted.png"
        c = store.add_character(p["id"], {"name": "苏瑶", "image_path": str(gone)})
        sb = store.add_storyboard(ep["id"], {
            "number": 1, "image_prompt": "two shot",
            "characters_json": json.dumps([{"name": c["name"], "id": c["id"]}])})

        await services.generate_shot_images(store, p["id"], ep["id"])
        assert imageProbe["calls"] == []
        assert store.get_storyboard(sb["id"])["status"] == "failed"

    @pytest.mark.asyncio
    async def testDanglingCharacterReferenceBlocks(self, store, imageProbe):
        from neurova.aigc_studio import services

        p = _project(store)
        ep = store.add_episode(p["id"], {"number": 1, "title": "e1"})
        sb = store.add_storyboard(ep["id"], {
            "number": 1, "image_prompt": "crowd",
            "characters_json": json.dumps([{"name": "已删角色", "id": "chr_gone"}])})

        await services.generate_shot_images(store, p["id"], ep["id"])
        assert imageProbe["calls"] == []
        row = store.get_storyboard(sb["id"])
        assert row["status"] == "failed" and "已删角色" in row["error"]

    @pytest.mark.asyncio
    async def testDanglingSceneReferenceBlocks(self, store, imageProbe):
        from neurova.aigc_studio import services

        p = _project(store)
        ep = store.add_episode(p["id"], {"number": 1, "title": "e1"})
        sb = store.add_storyboard(ep["id"], {"number": 1, "image_prompt": "hall",
                                             "scene_id": "scn_gone"})
        await services.generate_shot_images(store, p["id"], ep["id"])
        assert imageProbe["calls"] == []
        assert store.get_storyboard(sb["id"])["status"] == "failed"

    @pytest.mark.asyncio
    async def testSceneReferenceImageMissingOnDiskBlocks(self, store, imageProbe, tmp_path):
        from neurova.aigc_studio import services

        p = _project(store)
        ep = store.add_episode(p["id"], {"number": 1, "title": "e1"})
        gone = tmp_path / "gone.png"
        scene = store.add_scene(p["id"], {"location": "巷口", "prompt": "alley",
                                          "image_path": str(gone)})
        sb = store.add_storyboard(ep["id"], {"number": 1, "image_prompt": "walk",
                                             "scene_id": scene["id"]})
        await services.generate_shot_images(store, p["id"], ep["id"])
        assert imageProbe["calls"] == []
        assert store.get_storyboard(sb["id"])["status"] == "failed"

    @pytest.mark.asyncio
    async def testVideoSubmitWithoutFirstFrameBlocks(self, store, videoProbe):
        """§6-78 H 条：无首帧不再静默退化成 t2v 并写 running。"""
        from neurova.aigc_studio import services

        p = _project(store)
        ep = store.add_episode(p["id"], {"number": 1, "title": "e1"})
        sb = store.add_storyboard(ep["id"], {"number": 1, "video_prompt": "推门而入"})

        stats = await services.generate_shot_videos(store, p["id"], ep["id"])
        assert videoProbe["calls"] == []
        row = store.get_storyboard(sb["id"])
        assert row["video_status"] == "failed"
        assert "首帧" in row["error"]
        assert stats["failed"] == 1 and stats["blocked_no_frame"] == 1

    @pytest.mark.asyncio
    async def testVideoSubmitWithFirstFrameMissingOnDiskBlocks(self, store, videoProbe, tmp_path):
        from neurova.aigc_studio import services

        p = _project(store)
        ep = store.add_episode(p["id"], {"number": 1, "title": "e1"})
        sb = store.add_storyboard(ep["id"], {"number": 1, "video_prompt": "vp",
                                             "first_frame_path": str(tmp_path / "gone.png")})
        await services.generate_shot_videos(store, p["id"], ep["id"])
        assert videoProbe["calls"] == []
        assert store.get_storyboard(sb["id"])["video_status"] == "failed"


class TestArtifactMustNotBeEmpty:
    """`persist_media` 是产物唯一落盘点：0 字节回包不该换来一个"成功"路径。"""

    @pytest.mark.asyncio
    async def testEmptyDataUrlIsRejected(self, tmp_path, monkeypatch):
        from neurova.llm.generators import runtime as gen_runtime

        monkeypatch.setattr(gen_runtime, "GENERATION_OUTPUT_DIR", tmp_path)
        with pytest.raises(RuntimeError) as exc:
            await gen_runtime.persist_media("data:image/png;base64,", "image", "t1", 0)
        assert "空" in str(exc.value)
        assert list(tmp_path.iterdir()) == []

    @pytest.mark.asyncio
    async def testNonEmptyPayloadStillLands(self, tmp_path, monkeypatch):
        import base64

        from neurova.llm.generators import runtime as gen_runtime

        monkeypatch.setattr(gen_runtime, "GENERATION_OUTPUT_DIR", tmp_path)
        url = "data:image/png;base64," + base64.b64encode(b"PNGBYTES").decode()
        path = await gen_runtime.persist_media(url, "image", "t2", 0)
        assert Path(path).read_bytes() == b"PNGBYTES"


class TestStoryboardSceneMapping:
    """自动拆解路径必须把场景落到 `scene_id`——否则该列永远空着，跨集复用无从谈起。"""

    @pytest.mark.asyncio
    async def testSceneLocationAndTimeMapToSceneRow(self, store):
        from neurova.aigc_studio import services

        p = _project(store)
        ep = store.add_episode(p["id"], {"number": 1, "title": "e1"})
        s1 = store.add_scene(p["id"], {"location": "客厅", "time": "夜", "prompt": "a"})
        s2 = store.add_scene(p["id"], {"location": "客厅", "time": "日", "prompt": "b"})
        shots = [
            {"number": 1, "image_prompt": "x", "scene": "客厅", "scene_time": "夜"},
            {"number": 2, "image_prompt": "y", "scene": "客厅", "scene_time": "日"},
        ]

        async def fake_llm(prompt, system_prompt=""):
            return json.dumps(shots, ensure_ascii=False)

        await services.break_storyboards(store, p["id"], ep["id"], llm=fake_llm)
        rows = store.list_storyboards(ep["id"])
        assert rows[0]["scene_id"] == s1["id"]
        assert rows[1]["scene_id"] == s2["id"]

    @pytest.mark.asyncio
    async def testAmbiguousSceneLeavesSceneIdEmpty(self, store):
        from neurova.aigc_studio import services

        p = _project(store)
        ep = store.add_episode(p["id"], {"number": 1, "title": "e1"})
        store.add_scene(p["id"], {"location": "客厅", "time": "夜", "prompt": "a"})
        store.add_scene(p["id"], {"location": "客厅", "time": "日", "prompt": "b"})

        async def fake_llm(prompt, system_prompt=""):
            return json.dumps([{"number": 1, "image_prompt": "x", "scene": "客厅"}],
                              ensure_ascii=False)

        await services.break_storyboards(store, p["id"], ep["id"], llm=fake_llm)
        assert store.list_storyboards(ep["id"])[0]["scene_id"] == ""

    def testStoryboardsBreakerPromptAsksForScene(self):
        from neurova.aigc_studio.llm import STORYBOARD_BREAKER

        assert "scene" in STORYBOARD_BREAKER and "scene_time" in STORYBOARD_BREAKER


class TestSceneIdIsEditable:
    """手动建镜头收 `scene_id`，编辑面却放行不了它——同一列两份口径。"""

    @pytest.fixture()
    def client(self, tmp_path, monkeypatch):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from neurova.aigc_studio.store import StudioStore
        from neurova.api.endpoints import studio_api
        from neurova.api.deps import get_current_user

        store = StudioStore(db_path=str(tmp_path / "studio.db"))
        monkeypatch.setattr(studio_api, "get_store", lambda: store)
        app = FastAPI()
        app.include_router(studio_api.router, prefix="/api/v1/studio")
        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": "u1", "username": "u1", "role": "user", "neuser_id": "u1"}
        c = TestClient(app)
        c.store = store  # type: ignore[attr-defined]
        return c

    def testPutStoryboardPersistsSceneId(self, client):
        p = client.store.create_project(owner_user_id="u1", title="T")
        ep = client.store.add_episode(p["id"], {"number": 1, "title": "e"})
        scene = client.store.add_scene(p["id"], {"location": "天台", "prompt": "roof"})
        sb = client.store.add_storyboard(ep["id"], {"number": 1, "image_prompt": "wide"})
        r = client.put(f"/api/v1/studio/storyboards/{sb['id']}",
                       json={"scene_id": scene["id"]})
        assert r.status_code == 200
        assert client.store.get_storyboard(sb["id"])["scene_id"] == scene["id"]
