# -*- coding: utf-8 -*-
"""H2-4 · G 条的 live-verify：真端点跑完后，「重试这一镜」用的就是这一镜当初的规格。

跑的真生产对象：真 `create_app()` + `TestClient`（真 lifespan）、真 `/api/v1/studio/*` 端点族
（`POST /episodes/{eid}/generate-videos` 与 `POST /storyboards/{sid}/retry` 两条支路都真打）、
真 `_spawn_run` 后台任务与 runs 台账、真 `StudioStore`（SQLite，含本批新增的
`storyboards.video_resolution` 列与幂等补列通道）、真 `GenerationTaskLedger`。
只把**服务商边界**（`resolve_generation_creds` / `submit_video`）替成记录型假实现——
本层证的是「规格写下去有人读」这条链，不证上游服务商收参数后怎么编码。
数据根走 `_liveVerifyIsolation.isolatedDataRoot()` 单点。

判据（缺一条这条链就是断的）：

1. 整集首发带 `resolution='720p'`：真提交收到 720p，且**库内每条提交镜头行都落 720p**
   （改前这档规格只活在请求体里，页面一刷就查无可查）；
2. 单镜重试**不传任何规格**（前端 `retryStoryboard` 的现形）：真提交收到的仍是 720p——
   继承的是这一镜当初的值。改前这里会落回服务层默认 1080p，即用户点「重试」被悄悄换尺寸；
3. 重试没有把镜头留在自相矛盾的状态：`video_status` 回到 `running`、`ledger_task_id` 换新的、
   `error` 清空（失败态被显式覆盖，不是靠残留）；
4. 全程不写仓内真实 `data/`（指纹前后一致）。

一条命令复现（机器无关串——写死开发机绝对路径会给常驻守卫
`TestNoHardcodedDevMachinePaths` 新增一格 offender）：
PYTHONPATH="$(git rev-parse --show-toplevel)" .venv/Scripts/python.exe tests/manual/shotSpecInheritance_live.py

**改前对照**：本批的 `storyboards.video_resolution` 列不存在时，判据 1 就红在
`KeyError: 'video_resolution'`；把 `services` 里「读回行内规格」那一句退回旧形态
（只用调用方传值），判据 2 会红在 `发出 '1080p'`——见提交正文的反事实复跑记录。

如实记一句：本层证后端两条支路的规格继承，**不证**前端页面（`StudioProjectPage.vue`
的定时器启停形态属 `H2-4 · F 条`，其判据在 vitest 组件契约那一层，用假时钟断真行为）。
"""
from __future__ import annotations

import hashlib
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.manual._liveVerifyIsolation import isolatedDataRoot

DATA_ROOT = isolatedDataRoot()
REPO_DATA_DIR = PROJECT_ROOT / "data"
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


def waitRuns(store, pid, expect, deadlineS=30.0):
    from neurova.aigc_studio.store import RUN_TERMINAL_STATUSES

    deadline = time.time() + deadlineS
    runs = []
    while time.time() < deadline:
        runs = store.list_runs(pid)
        if len(runs) >= expect and all(
                r["status"] in RUN_TERMINAL_STATUSES for r in runs[:expect]):
            return runs
        time.sleep(0.2)
    return runs


def main() -> int:
    from fastapi.testclient import TestClient

    from neurova.aigc_studio.store import get_store, defaultDbPath
    from neurova.api.app import create_app
    from neurova.api.deps import get_current_user
    from neurova.llm.generators import protocols as proto_mod
    from neurova.llm.generators import runtime as gen_runtime
    from neurova.llm.generators.protocols import ProtocolCredentials

    USER = {"user_id": "u-live", "role": "admin"}
    failures = []
    before, nBefore = fingerprintDataDir()
    calls = []

    def fakeResolve(hint, model, providerId, apiKey, baseUrl, defaultBase=None, **kw):
        return ProtocolCredentials(api_key="k", base_url="https://x", model=model or "m",
                                   protocol=hint)

    async def fakeSubmit(creds, prompt, **kw):
        calls.append({"resolution": kw.get("resolution"), "duration": kw.get("duration"),
                      "refs": kw.get("ref_images") or [], "prompt": prompt})
        return {"task_id": f"rt{len(calls)}", "poll_url": "", "raw": {}}

    gen_runtime.resolve_generation_creds = fakeResolve
    proto_mod.submit_video = fakeSubmit

    store = get_store()
    project = store.create_project(owner_user_id="u-live", title="规格继承活体",
                                   aspect_ratio="9:16")
    pid = project["id"]
    ep = store.add_episode(pid, {"number": 1, "title": "e1"})
    shots = []
    for n in (1, 2):
        sb = store.add_storyboard(ep["id"], {"number": n, "video_prompt": f"镜头{n}",
                                             "duration": 3})
        frame = DATA_ROOT / f"frame_{n}.png"
        frame.write_bytes(b"IMG")
        store.update_storyboard(sb["id"], {"first_frame_path": str(frame)})
        shots.append(sb)

    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: USER

    with TestClient(app) as client:
        # ① 整集首发：规格在请求体里
        r = client.post(f"{BASE}/episodes/{ep['id']}/generate-videos",
                        json={"provider": "wan", "model": "wan-x", "resolution": "720p"})
        assert r.status_code == 200, r.text
        waitRuns(store, pid, 1)
        sentFirst = [c["resolution"] for c in calls]
        rows = {s["id"]: store.get_storyboard(s["id"]) for s in shots}
        stored = {sid: (row["video_status"], row["video_resolution"]) for sid, row in rows.items()}
        print(f"首发读数：提交收到 {sentFirst} 库内={stored}")
        if set(sentFirst) != {"720p"}:
            failures.append(f"整集首发没把 720p 发出去：{sentFirst}")
        if {v[1] for v in stored.values()} != {"720p"}:
            failures.append(f"生效规格没落到镜头行（下次重试无从继承）：{stored}")

        # ② 单镜重试：规格一个都不传（前端 retryStoryboard 的现形）
        target = shots[0]["id"]
        store.update_storyboard(target, {"video_status": "failed", "error": "上游超时"})
        calls.clear()
        r = client.post(f"{BASE}/storyboards/{target}/retry", json={"stage": "video"})
        assert r.status_code == 200, r.text
        waitRuns(store, pid, 2)
        rowAfter = store.get_storyboard(target)
        print(f"重试读数：提交收到 {[c['resolution'] for c in calls]} "
              f"行内={rowAfter['video_status']}/{rowAfter['video_resolution']}/"
              f"ledger={rowAfter['ledger_task_id']}/error={rowAfter['error']!r}")
        if [c["resolution"] for c in calls] != ["720p"]:
            failures.append("同一镜头重试换了规格：期望继承行内 720p，实收 "
                            f"{[c['resolution'] for c in calls]}")
        # ③ 状态面自洽：重跑回到 running、换了账本行、成因被清空
        if rowAfter["video_status"] != "running":
            failures.append(f"重试后镜头状态没回到 running：{rowAfter['video_status']}")
        if not rowAfter["ledger_task_id"]:
            failures.append("重试没接上新的账本任务行")
        if rowAfter["error"]:
            failures.append(f"重跑成功却还挂着上一轮的失败成因：{rowAfter['error']!r}")

    after, nAfter = fingerprintDataDir()
    print(f"仓内 data/ 指纹：before={before[:12]}({nBefore}) after={after[:12]}({nAfter})")
    print(f"Studio 库落点：{defaultDbPath()}（隔离数据根内，不碰仓内真库）")
    if after != before:
        failures.append("仓内 data/ 被写动了")
    if failures:
        for f in failures:
            print("FAIL:", f)
        return 1
    print("H2-4 G-SHOT-SPEC-INHERITANCE LIVE VERIFY PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
