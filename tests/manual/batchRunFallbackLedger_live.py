# -*- coding: utf-8 -*-
"""H2-3 · ①的 live-verify：真端点跑一批视频，被阻断的镜头必须让台账行变成"带病完成"。

跑的真生产对象：真 `create_app()` + `TestClient`（真 lifespan）、真
`POST /api/v1/studio/episodes/{eid}/generate-videos`、真 `_spawn_run` 与 runs 台账、
真 `StudioStore`、真 `GenerationTaskLedger`。只替服务商边界（`resolve_generation_creds`
与 `submit_video`）与 auth 身份——本层证的是「一批没全跑完时，台账上那行到底写了什么」。
数据根走 `_liveVerifyIsolation.isolatedDataRoot()`。

判据（缺一条这条链就是断的）：

1. 两条镜头、其中一条没有首帧（C1 的闸会阻断它，诚实标 failed）→ 外层 run 行必须是
   `done_with_fallback` 且 `error` 点名「1 项被阻断」；改前 wrapper 兜底写干净的 `done`，
   读侧完全看不出这批没跑完（§6-70 第③格对四个批量服务的残留）；
2. 两条都有首帧、全部提交成功 → 同一列判据反过来：行必须是 `done` 且 `error` 为空
   （不能把成功写成带病）；
3. 一次请求只留一行该 kind 的台账（run_id 贯通后服务写的就是外层那行）；
4. 全程不写仓内真实 `data/`（指纹前后一致）。

一条命令复现（机器无关串）：
PYTHONPATH="$(git rev-parse --show-toplevel)" .venv/Scripts/python.exe tests/manual/batchRunFallbackLedger_live.py

**改前对照**：把四个服务里 `rid = run_id or ...` 与收尾那行 `_settleRun` 撤掉再跑本脚本，
判据 1 会红在 `status='done'`、判据 3 会红在多出一行——见提交正文。
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.manual._liveVerifyIsolation import isolatedDataRoot

DATA_ROOT = isolatedDataRoot()
REPO_DATA_DIR = PROJECT_ROOT / "data"
BASE = "/api/v1/studio"
USER = {"user_id": "u-live", "role": "admin"}


def fingerprintDataDir():
    items = []
    if REPO_DATA_DIR.exists():
        for p in sorted(REPO_DATA_DIR.rglob("*")):
            if p.is_file():
                st = p.stat()
                items.append(f"{p.relative_to(REPO_DATA_DIR)}:{st.st_size}:{st.st_mtime_ns}")
    digest = hashlib.sha256("\n".join(items).encode("utf-8")).hexdigest() if items else "empty"
    return digest, len(items)


async def _awaitRun(store, rid, deadlineS=25.0):
    from neurova.aigc_studio.store import RUN_TERMINAL_STATUSES

    deadline = asyncio.get_running_loop().time() + deadlineS
    while asyncio.get_running_loop().time() < deadline:
        row = store.get_run(rid)
        if row and row["status"] in RUN_TERMINAL_STATUSES:
            return row
        await asyncio.sleep(0.1)
    return store.get_run(rid) or {}


def _spawnShots(store, pid, eid, withFrames):
    shots = []
    for n, hasFrame in withFrames.items():
        sb = store.add_storyboard(eid, {"number": n, "video_prompt": f"镜{n}",
                                        "prompt": f"镜{n}", "duration": 3})
        if hasFrame:
            f = DATA_ROOT / f"frame{n}.png"
            f.write_bytes(b"IMG")
            store.update_storyboard(sb["id"], {"first_frame_path": str(f)})
        shots.append(sb)
    return shots


def main() -> int:
    from fastapi.testclient import TestClient

    from neurova.api.app import create_app
    from neurova.api.deps import get_current_user
    from neurova.aigc_studio.store import get_store
    from neurova.llm.generators import protocols as proto_mod
    from neurova.llm.generators import runtime as gen_runtime
    from neurova.llm.generators.protocols import ProtocolCredentials

    failures = []
    before, nBefore = fingerprintDataDir()

    def fakeResolve(hint, model, providerId, apiKey, baseUrl, defaultBase=None, **kw):
        return ProtocolCredentials(api_key="k", base_url="https://x", model="m", protocol=hint)

    async def fakeSubmit(creds, prompt, **kw):
        return {"task_id": f"rt-{prompt[-1]}", "poll_url": "", "raw": {}}

    gen_runtime.resolve_generation_creds = fakeResolve
    proto_mod.submit_video = fakeSubmit

    store = get_store()
    project = store.create_project(owner_user_id="u-live", title="批量带病完成",
                                   aspect_ratio="9:16")
    pid = project["id"]

    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: dict(USER)
    with TestClient(app) as client:
        # ① 一条缺首帧 → 被阻断
        ep1 = store.add_episode(pid, {"number": 1, "title": "e1"})["id"]
        _spawnShots(store, pid, ep1, {1: True, 2: False})
        r = client.post(f"{BASE}/episodes/{ep1}/generate-videos",
                        json={"provider": "wan", "model": "wan-x"})
        assert r.status_code == 200, r.text
        rid1 = r.json()["data"]["run_id"]
        row1 = asyncio.run(_awaitRun(store, rid1))
        print(f"部分失败读数：run={row1['status']!r} error={row1['error']!r} "
              f"detail={row1['detail_json']}")
        if row1["status"] != "done_with_fallback":
            failures.append(f"有镜头被阻断，台账行却写着 {row1['status']!r}——带病完成被压平成成功")
        if "1" not in (row1["error"] or ""):
            failures.append(f"台账没点名被阻断条数：{row1['error']!r}")
        blockedShot = [s for s in store.list_storyboards(ep1) if s["video_status"] == "failed"]
        assert blockedShot, "被阻断的镜头行也没标 failed"

        # ② 全部可提交 → 干净的 done
        ep2 = store.add_episode(pid, {"number": 2, "title": "e2"})["id"]
        _spawnShots(store, pid, ep2, {1: True, 2: True})
        r = client.post(f"{BASE}/episodes/{ep2}/generate-videos",
                        json={"provider": "wan", "model": "wan-x"})
        rid2 = r.json()["data"]["run_id"]
        row2 = asyncio.run(_awaitRun(store, rid2))
        print(f"全成功读数：run={row2['status']!r} error={row2['error']!r}")
        if row2["status"] != "done" or (row2["error"] or ""):
            failures.append(f"全成功却被写成 {row2['status']!r}/{row2['error']!r}")

        # ③ 一次请求一行台账（外层那行就是服务写的）
        videos = [x for x in store.list_runs(pid) if x["kind"] == "videos"]
        print(f"台账行数读数：videos 类共 {len(videos)} 行 id={[v['id'] for v in videos]}")
        if len(videos) != 2:
            failures.append(f"两次请求留下 {len(videos)} 行 videos——run_id 没贯通，服务另起了一行")
        if {v["id"] for v in videos} != {rid1, rid2}:
            failures.append("服务结算的不是外层那一行（读侧无从判断哪条代表这次请求）")

    after, nAfter = fingerprintDataDir()
    print(f"仓内 data/ 指纹：before={before[:12]}({nBefore}) after={after[:12]}({nAfter})")
    if after != before:
        failures.append("仓内 data/ 被写动了")
    if failures:
        for f in failures:
            print("FAIL:", f)
        return 1
    print("H2-3 BATCH RUN FALLBACK LEDGER LIVE VERIFY PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
