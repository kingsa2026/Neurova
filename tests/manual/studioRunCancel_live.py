# -*- coding: utf-8 -*-
"""取消四件套的 live-verify：真点「停止」之后，剩下的分片必须不再开跑。

跑的真生产对象：真 `create_app()` + `TestClient`（真 lifespan）、真
`POST /episodes/{eid}/generate-images`、真 `POST /runs/{rid}/cancel`、真 `_spawn_run` 与
runs 台账、真 `services.generate_shot_images`（含分片检查点）、真 `StudioStore`、
真 `core/task_tracker`。只替服务商凭证与图像生成边界、auth 身份。
数据根走 `_liveVerifyIsolation.isolatedDataRoot()`。

四件各自要在真链路上自证一遍，缺一件就是假取消：

1. **持久意图**：`runs.cancel_requested` 落列（不是只在内存里）；
2. **真句柄**：端点能按 run id 在注册表里找到 Task 并打断（`tasks_cancelled >= 1`）；
3. **收敛单点**：两条停止路（检查点 `RunCancelled` / `Task.cancel()`）都落 `cancelled`，
   不是 `failed`——"人让它停的"与"它自己崩了"是两件事；
4. **读侧同源**：`GET /projects/{pid}` 的投影里那一行就是 `cancelled`（前端只认终态集合）。

外加本批真正要的那个数：**取消后剩余分片没开跑**（图像调用次数停在被打断的位置）。
最后证一次重启收敛：叫过停的 running 行 reopen 后收成 `cancelled`，而不是 `process_died`。

一条命令复现（机器无关串）：
PYTHONPATH="$(git rev-parse --show-toplevel)" .venv/Scripts/python.exe tests/manual/studioRunCancel_live.py
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
USER = {"user_id": "u-cancel", "role": "admin"}
SHOT_COUNT = 4
PER_SHOT_S = 0.35


def fingerprintDataDir():
    items = []
    if REPO_DATA_DIR.exists():
        for p in sorted(REPO_DATA_DIR.rglob("*")):
            if p.is_file():
                st = p.stat()
                items.append(f"{p.relative_to(REPO_DATA_DIR)}:{st.st_size}:{st.st_mtime_ns}")
    digest = hashlib.sha256("\n".join(items).encode("utf-8")).hexdigest() if items else "empty"
    return digest, len(items)


def main() -> int:
    from fastapi.testclient import TestClient

    from neurova.aigc_studio import services
    from neurova.aigc_studio.store import StudioStore, get_store
    from neurova.api.app import create_app
    from neurova.api.deps import get_current_user
    from neurova.llm.generators import protocols as proto_mod
    from neurova.llm.generators import runtime as gen_runtime
    from neurova.llm.generators.protocols import ProtocolCredentials

    failures = []
    before, nBefore = fingerprintDataDir()
    calls = {"n": 0}

    def fakeResolve(hint, model, providerId, apiKey, baseUrl, defaultBase=None, **kw):
        return ProtocolCredentials(api_key="k", base_url="https://stub.local",
                                   model="stub", protocol=hint)

    async def slowImage(creds, prompt, **kw):
        calls["n"] += 1
        await asyncio_sleep(PER_SHOT_S)
        return {"images": [f"data:image/png;base64,{calls['n']}"]}

    async def asyncio_sleep(seconds):
        import asyncio
        await asyncio.sleep(seconds)

    async def fakePersist(url, kind, key, ttl):
        p = Path(DATA_ROOT) / f"probe_{kind}_{calls['n']}.png"
        p.write_bytes(b"IMG")
        return str(p)

    gen_runtime.resolve_generation_creds = fakeResolve
    proto_mod.generate_image = slowImage
    services.persist_media = fakePersist

    store = get_store()
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: dict(USER)
    with TestClient(app) as client:
        pid = store.create_project(owner_user_id="u-cancel", title="取消真链路")["id"]
        eid = store.add_episode(pid, {"number": 1, "title": "e1", "content": "客厅夜"})["id"]
        for n in range(1, SHOT_COUNT + 1):
            store.add_storyboard(eid, {"number": n, "image_prompt": f"镜 {n}",
                                       "prompt": f"镜 {n}", "duration": 3})

        runId = client.post(f"{BASE}/episodes/{eid}/generate-images",
                            json={"provider": "openai", "model": "gpt-image"}
                            ).json()["data"]["run_id"]

        # 等它真跑起来（第一镜已发出请求），再走端点叫停
        deadline = time.time() + 20.0
        while time.time() < deadline and calls["n"] < 1:
            time.sleep(0.02)
        if calls["n"] < 1:
            failures.append(f"执行体一镜都没发出请求，后面的取消读数没有意义（calls={calls['n']}）")

        r = client.post(f"{BASE}/runs/{runId}/cancel")
        print(f"取消端点读数：HTTP {r.status_code} {r.text[:180]}")
        if r.status_code != 200:
            failures.append(f"属主叫停被拒：{r.status_code}")
        else:
            data = r.json()["data"]
            if not data["cancel_requested"]:
                failures.append(f"意图没落库：{data}")
            if data["tasks_cancelled"] < 1:
                failures.append(f"句柄没被打断（登记表没接通）：{data}")

        row = {}
        deadline = time.time() + 20.0
        while time.time() < deadline:
            row = store.get_run(runId) or {}
            if row.get("status") in ("done", "done_with_fallback", "failed", "cancelled"):
                break
            time.sleep(0.05)
        stoppedAt = calls["n"]
        print(f"终态读数：status={row.get('status')!r} error={row.get('error')!r} "
              f"cancel_requested={row.get('cancel_requested')!r} 已发出图像请求={stoppedAt}/{SHOT_COUNT}")

        if row.get("status") != "cancelled":
            failures.append(f"取消后落的是 {row.get('status')!r}——"
                            "把「人让它停的」记成「它自己崩了」，按失败率排查会去查一条没坏的任务")
        if not row.get("cancel_requested"):
            failures.append("runs.cancel_requested 没落列：重启后「用户叫过停」这件事就消失了")
        if stoppedAt >= SHOT_COUNT:
            failures.append(f"叫停后仍把 {SHOT_COUNT} 镜全跑完（检查点没生效，calls={stoppedAt}）")

        # 读侧同源：HTTP 投影里就是 cancelled（前端只认终态集合）
        projected = next((x for x in client.get(f"{BASE}/projects/{pid}").json()["data"]["runs"]
                          if x["id"] == runId), {})
        print(f"投影读数：status={projected.get('status')!r}")
        if projected.get("status") != "cancelled":
            failures.append(f"前端投影里不是 cancelled：{projected.get('status')!r}")

        # 已终态再叫停 → 409（不许假成功）
        again = client.post(f"{BASE}/runs/{runId}/cancel")
        print(f"重复叫停读数：HTTP {again.status_code}")
        if again.status_code != 409:
            failures.append(f"已终态还接受取消：{again.status_code}")

    # 重启收敛：叫过停的 running 行 reopen 后应收成 cancelled，而不是 process_died
    legacy = StudioStore(db_path=str(DATA_ROOT / "cancel_reopen.db"))
    row = legacy.add_run({"project_id": "p-reopen", "kind": "images"})
    legacy.requestCancel(row["id"])
    legacy.close()
    reopened = StudioStore(db_path=str(DATA_ROOT / "cancel_reopen.db"))
    back = reopened.get_run(row["id"])
    print(f"重启收敛读数：status={back['status']!r} error={back['error']!r}")
    if back["status"] != "cancelled":
        failures.append(f"叫过停的行重启后收成 {back['status']!r}（应为 cancelled）")
    reopened.close()

    after, nAfter = fingerprintDataDir()
    print(f"仓内 data/ 指纹：before={before[:12]}({nBefore}) after={after[:12]}({nAfter})")
    if after != before:
        failures.append("仓内 data/ 被写动了")
    if failures:
        for f in failures:
            print("FAIL:", f)
        return 1
    print("STUDIO RUN CANCEL FOUR-PIECE LIVE VERIFY PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
