# -*- coding: utf-8 -*-
"""C1 的 live-verify：真 app 起来后，跨集资产连续性「读数 / 阻断」在真端点上各自留痕。

跑的真生产对象：真 `create_app()` + `TestClient`（走真 lifespan）、真 `StudioStore`、
真 `GenerationTaskLedger`、真 `persist_media`（产物落盘点），真 `/api/v1/studio/*` 端点族。
只把**服务商边界**（`resolve_generation_creds` / `generate_image` / `submit_video`）替成
记录型假实现——本层证的是读数与闸门，不证上游服务商返回什么。
数据根走 `_liveVerifyIsolation.isolatedDataRoot()` 单点。

判据（缺一条这条链就是断的）：

1. 引用了未定妆角色的镜头：一次请求都不发（`generate_image` 调用数不含它）、镜头标
   `failed` 且 `error` 点名成因——改前是静默丢参考图照样出图（另一张脸）；
2. 引用了已定妆角色 + 场景 + 氛围的镜头：场景定妆提示词/灯光/氛围进了注入提示词，
   定妆图与场景参考图进了 `ref_images`，首帧经**真** `persist_media` 落盘并在镜头行留路径；
3. 定妆 seed 以库为准：端点跑完 `characters.seed_value` 可读回，重跑复用同一枚
   （改前是每次按 id 现算，库里那列有写无读）；
4. 无首帧的镜头提交视频：标 `failed` 点名成因、不写 `running`（改前 i2v 静默退化成
   t2v，产出一段与本集画面无关的片子且账面看不出坏了）；有首帧的照常提交，
   氛围进视频提示词；
5. 空回包（0 字节）经真 `persist_media`：不落盘、不返回路径、当场报错——上游不会记成
   「有产物」；
6. 全程不写仓内真实 `data/`（指纹前后一致）。

一条命令复现：
PYTHONPATH="E:/项目/Neurova" .venv/Scripts/python.exe tests/manual/crossEpisodeContinuity_live.py

如实记一句：本层不证 `recovery.py` 对上游的轮询正确性，也不证前端页面渲染
（`StudioProjectPage.vue` 的错误展示另有页面测试）。
"""
from __future__ import annotations

import base64
import hashlib
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.manual._liveVerifyIsolation import isolatedDataRoot

DATA_ROOT = isolatedDataRoot()
REPO_DATA_DIR = PROJECT_ROOT / "data"

# 1x1 PNG：让真 persist_media 走完整解码-落盘路径
PNG_B64 = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGA"
           "hKmMIQAAAABJRU5ErkJggg==")
USER = {"user_id": "live_c1", "username": "live_c1", "role": "user", "neuser_id": "live_c1"}
BASE = "/api/v1/studio"


def fingerprintDataDir():
    items = []
    if REPO_DATA_DIR.exists():
        for p in sorted(REPO_DATA_DIR.rglob("*")):
            if p.is_file():
                st = p.stat()
                items.append(f"{p.relative_to(REPO_DATA_DIR)}:{st.st_size}:{st.st_mtime_ns}")
    digest = hashlib.sha256("\n".join(items).encode("utf-8")).hexdigest() if items else "empty"
    return digest, len(items)


def waitRuns(store, pid, expect, deadline_s=30.0):
    deadline = time.time() + deadline_s
    runs = []
    while time.time() < deadline:
        runs = store.list_runs(pid)
        if len(runs) >= expect and all(
                r["status"] in ("done", "done_with_fallback", "failed") for r in runs[:expect]):
            return runs
        time.sleep(0.2)
    return runs


def main() -> int:
    from fastapi.testclient import TestClient

    from neurova.aigc_studio import services
    from neurova.aigc_studio.store import get_store
    from neurova.api.app import create_app
    from neurova.api.deps import get_current_user
    from neurova.llm.generators import protocols as proto_mod
    from neurova.llm.generators import runtime as gen_runtime
    from neurova.llm.generators import task_ledger as ledger_mod
    from neurova.llm.generators.protocols import ProtocolCredentials

    store = get_store()
    services._auto_route = lambda kind: ("probe-model", "probe-provider")  # 不打真实路由器
    gen_runtime.resolve_generation_creds = (
        lambda hint, model, provider_id, api_key, base_url, default_base:
        ProtocolCredentials(api_key="k", base_url="https://probe", model=model or "m",
                            protocol=hint))

    imageCalls, videoCalls = [], []

    async def fakeImage(creds, prompt, **kw):
        imageCalls.append({"prompt": prompt, "refs": list(kw.get("ref_images") or []),
                           "seed": kw.get("seed")})
        return {"images": [f"data:image/png;base64,{PNG_B64}"], "task_id": None, "raw": {}}

    async def fakeSubmit(creds, prompt, **kw):
        videoCalls.append({"prompt": prompt, "refs": list(kw.get("ref_images") or []),
                           "last_frame": kw.get("last_frame")})
        return {"task_id": f"live-{len(videoCalls)}", "poll_url": "", "raw": {}}

    proto_mod.generate_image = fakeImage
    proto_mod.submit_video = fakeSubmit

    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: USER
    failures = []

    portrait = DATA_ROOT / "live_c1_portrait.png"
    portrait.write_bytes(base64.b64decode(PNG_B64))
    sceneRef = DATA_ROOT / "live_c1_scene.png"
    sceneRef.write_bytes(base64.b64decode(PNG_B64))

    with TestClient(app) as client:
        pid = client.post(f"{BASE}/projects",
                          json={"title": "跨集连续性活体", "style": "国风水墨",
                                "aspect_ratio": "9:16"}).json()["data"]["project"]["id"]
        ep = store.add_episode(pid, {"number": 1, "title": "第1集"})
        cReady = store.add_character(pid, {"name": "林凡", "image_path": str(portrait),
                                           "status": "ready"})
        cNew = store.add_character(pid, {"name": "苏瑶"})  # 未定妆
        scene = store.add_scene(pid, {"location": "客厅", "time": "夜",
                                      "prompt": "old mansion hall, dim lamp",
                                      "lighting": "warm rim light",
                                      "image_path": str(sceneRef)})
        sb1 = store.add_storyboard(ep["id"], {
            "number": 1, "image_prompt": "hero steps in", "video_prompt": "turns slowly",
            "atmosphere": "压抑的对峙", "scene_id": scene["id"],
            "characters": [{"name": cReady["name"], "id": cReady["id"]}]})
        sb2 = store.add_storyboard(ep["id"], {
            "number": 2, "image_prompt": "villain laughs",
            "characters": [{"name": cNew["name"], "id": cNew["id"]}]})
        sb3 = store.add_storyboard(ep["id"], {"number": 3, "video_prompt": "camera pushes in"})

        fpBefore, nBefore = fingerprintDataDir()

        r = client.post(f"{BASE}/episodes/{ep['id']}/generate-images",
                        json={"model": "probe-img", "provider_id": "probe-p"})
        assert r.status_code == 200, r.text
        waitRuns(store, pid, 1)
        row1, row2 = store.get_storyboard(sb1["id"]), store.get_storyboard(sb2["id"])
        print(f"首帧读数：sb1.status={row1['status']!r} sb2.status={row2['status']!r} "
              f"sb2.error={row2['error'][:60]!r} 请求数={len(imageCalls)}")

        if row1["status"] != "image_ready":
            failures.append(f"可读链路的镜头没出图：{row1}")
        frame = Path(row1["first_frame_path"] or "")
        if not frame.is_file():
            failures.append(f"首帧没经真 persist_media 落盘：{row1['first_frame_path']!r}")
        if "old mansion hall" not in row1["injected_prompt"] \
                or "warm rim light" not in row1["injected_prompt"]:
            failures.append(f"场景提示词/灯光没进注入提示词：{row1['injected_prompt']!r}")
        if "压抑的对峙" not in row1["injected_prompt"]:
            failures.append(f"氛围没进注入提示词：{row1['injected_prompt']!r}")
        if str(portrait) not in imageCalls[0]["refs"] or str(sceneRef) not in imageCalls[0]["refs"]:
            failures.append(f"定妆图/场景参考图没进 ref_images：{imageCalls[0]['refs']}")
        if row2["status"] != "failed" or "无定妆图" not in row2["error"]:
            failures.append(f"未定妆角色的镜头没被点名阻断：{row2}")
        if len(imageCalls) != 1:
            failures.append(f"阻断闸没拦住请求（本批 1 次，实发 {len(imageCalls)} 次）")

        # 定妆 seed 写后读回：端点跑一轮 → 库里每枚都落值 → 再跑一轮逐枚复用同一枚
        imageCalls.clear()
        r = client.post(f"{BASE}/projects/{pid}/assets/images",
                        json={"model": "probe-img", "provider_id": "probe-p"})
        assert r.status_code == 200, r.text
        waitRuns(store, pid, 2)
        seedsFirst = [c["seed"] for c in imageCalls]
        stored = {c["id"]: str(store.get_asset_row("characters", c["id"])["seed_value"] or "")
                  for c in store.list_characters(pid)}
        imageCalls.clear()
        r = client.post(f"{BASE}/projects/{pid}/assets/images",
                        json={"model": "probe-img", "provider_id": "probe-p"})
        assert r.status_code == 200, r.text
        waitRuns(store, pid, 3)
        seedsSecond = [c["seed"] for c in imageCalls]
        print(f"seed 读数：首轮={seedsFirst} 库内={stored} 复跑={seedsSecond}")
        if len(seedsFirst) != 2 or None in seedsFirst:
            failures.append(f"首轮每枚资产都该带 seed：{seedsFirst}")
        if set(stored.values()) != {str(s) for s in seedsFirst}:
            failures.append(f"用过的 seed 没逐枚写回库：库={stored} 用={seedsFirst}")
        if seedsSecond != seedsFirst:
            failures.append(f"复跑没读回库里那枚（又现算了）：{seedsFirst} → {seedsSecond}")

        imageCalls.clear()
        r = client.post(f"{BASE}/episodes/{ep['id']}/generate-videos",
                        json={"provider": "wan", "model": "probe-vid",
                              "provider_id": "probe-p"})
        assert r.status_code == 200, r.text
        waitRuns(store, pid, 4)
        row1v, row3v = store.get_storyboard(sb1["id"]), store.get_storyboard(sb3["id"])
        print(f"视频读数：sb1.video_status={row1v['video_status']!r} "
              f"sb3.video_status={row3v['video_status']!r} sb3.error={row3v['error'][:40]!r} "
              f"提交数={len(videoCalls)}")
        if row1v["video_status"] not in ("running", "done"):
            failures.append(f"有首帧的镜头没提交：{row1v}")
        if row3v["video_status"] != "failed" or "尚无首帧" not in row3v["error"]:
            failures.append(f"无首帧的镜头没被点名阻断：{row3v}")
        if len(videoCalls) != 1:
            failures.append(f"视频闸没拦住提交（本批 1 次，实发 {len(videoCalls)} 次）")
        elif videoCalls[0]["refs"] != [str(frame)] or "压抑的对峙" not in videoCalls[0]["prompt"]:
            failures.append(f"首帧参考/氛围没进提交：{videoCalls[0]}")

        led = ledger_mod.get_generation_task_ledger()
        if not led.list():
            failures.append("提交没落进任务账本（batch_key 关联链断）")

        emptyBefore = len(list(gen_runtime.GENERATION_OUTPUT_DIR.iterdir()))
        try:
            import asyncio

            asyncio.new_event_loop().run_until_complete(
                gen_runtime.persist_media("data:image/png;base64,", "image", "live_c1_empty", 0))
            failures.append("空回包居然返回了路径")
        except RuntimeError as e:
            print(f"空件闸：{str(e)[:60]!r}")
            if "空" not in str(e):
                failures.append(f"空件报错没点名：{e}")
        if len(list(gen_runtime.GENERATION_OUTPUT_DIR.iterdir())) != emptyBefore:
            failures.append("空回包仍然落了盘")

    fpAfter, nAfter = fingerprintDataDir()
    print(f"仓内 data/ 指纹：before={fpBefore[:12]}({nBefore}) after={fpAfter[:12]}({nAfter})")
    if fpBefore != fpAfter:
        failures.append("活体探针写进了仓内真实 data/ —— 数据根隔离没生效")

    if failures:
        for f in failures:
            print("FAIL:", f)
        return 1
    print("C1 CROSS-EPISODE CONTINUITY LIVE VERIFY PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
