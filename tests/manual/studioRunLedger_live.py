# -*- coding: utf-8 -*-
"""批次 E 的 live-verify：/studio 长任务台账在真 HTTP 链路上收口成「一次请求一行」，
并在重启后把遗留 running 真的对账掉。

跑的真生产对象：真 `create_app()` + `TestClient`（真 lifespan、真路由、真属主隔离）、
真 JWT（`auth.create_access_token` 签，不走 dependency_overrides 后门）、
真 `StudioStore`（落点走 `_liveVerifyIsolation.isolatedDataRoot()` 单点下的
`defaultDbPath()`）、真 `_spawn_run` 后台任务、真 `services.split_script`。
唯一替身是 LLM 本体（`services.call_llm` 这一层外呼边界）。

判据（缺一条这条链就是断的）：
1. 经真端点发起的一次剧本拆解，runs 投影里 `kind=script` **只有一行**，且它就是终态
   （改前外层一行、服务内一行并排，前端只 poll 外层那条）；
2. 该行的 `detail_json` 带着服务侧的产出读数——说明写回的是同一行，不是两条各写各的；
3. 重启对偶：同库重开 + `reset_store()` 后，遗留 running 在**读侧**（GET 端点）呈现为
   failed + process_died 成因，而不是永远"在跑"；
4. 仓内 `data/` 未被写入。

一条命令复现：PYTHONPATH="E:/项目/Neurova" .venv/Scripts/python.exe tests/manual/studioRunLedger_live.py

如实记一句：本层证「端点 → 后台任务 → 台账行 → 读侧投影」与「重启对账 → 读侧可见」
两段闭合，不证视频子账（`video_status` + 生成任务账本）——那条已有 recovery 轮询覆盖。
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.manual._liveVerifyIsolation import isolatedDataRoot

isolatedDataRoot()

REPO_DATA_DIR = PROJECT_ROOT / "data"
TERMINAL = {"done", "done_with_fallback", "failed"}


def fingerprintDataDir():
    items = []
    if REPO_DATA_DIR.exists():
        for p in sorted(REPO_DATA_DIR.rglob("*")):
            if p.is_file():
                st = p.stat()
                items.append(f"{p.relative_to(REPO_DATA_DIR)}|{st.st_size}|{st.st_mtime_ns}")
    return hashlib.sha256("\n".join(items).encode("utf-8")).hexdigest(), len(items)


def main() -> int:
    from fastapi.testclient import TestClient

    import neurova.aigc_studio.services as svc
    from neurova.aigc_studio.store import defaultDbPath, get_store, reset_store
    from neurova.api.app import create_app
    from neurova.api.auth import create_access_token

    before, beforeCount = fingerprintDataDir()

    async def fakeLlm(prompt, system):
        return json.dumps(
            [{"number": 1, "title": "第一集", "content": "山上有座庙", "synopsis": "开场"}],
            ensure_ascii=False,
        )

    # LLM 本体是唯一外呼边界，打在真源模块的使用点上
    svc.call_llm = fakeLlm

    token = create_access_token({
        "sub": "u_studio_live", "username": "u_studio_live", "role": "user",
    })
    headers = {"Authorization": f"Bearer {token}"}
    app = create_app()

    with TestClient(app) as client:
        pid = client.post("/api/v1/studio/projects", json={"title": "E 批活体", "style": "水墨"},
                          headers=headers).json()["data"]["project"]["id"]
        print(f"1) 真端点建项目 = {pid}（真 JWT，未用 dependency_overrides）")

        accepted = client.post(f"/api/v1/studio/projects/{pid}/script",
                               json={"content": "从前有座山，山里有座庙。" * 4},
                               headers=headers).json()["data"]
        runId = accepted["run_id"]
        print(f"2) 发起拆解，返回 run_id = {runId}")

        deadline = time.time() + 20.0
        rows = []
        while time.time() < deadline:
            rows = [r for r in client.get(f"/api/v1/studio/projects/{pid}",
                                          headers=headers).json()["data"]["runs"]
                    if r["kind"] == "script"]
            if rows and rows[0]["status"] in TERMINAL:
                break
            time.sleep(0.2)

        print(f"3) runs 投影里 kind=script 的行 = {[ (r['id'], r['status']) for r in rows ]}")
        assert len(rows) == 1, f"一次请求仍有 {len(rows)} 行 kind=script（前端 poll 的是外层那条）"
        row = rows[0]
        assert row["id"] == runId, f"终态不在请求返回的那一行上：{row['id']} != {runId}"
        assert row["status"] in ("done", "done_with_fallback"), row["status"]
        detail = json.loads(row["detail_json"] or "{}")
        print(f"   detail_json = {detail}")
        assert detail.get("episodes"), f"服务侧产出读数没写进同一行：{detail}"

        eps = client.get(f"/api/v1/studio/projects/{pid}", headers=headers).json()["data"]["episodes"]
        assert eps and eps[0]["title"] == "第一集", f"拆解产物未落库：{eps}"
        print(f"4) 读侧一致：episodes={len(eps)} 条，标题 {eps[0]['title']!r}")

        # ── 重启对偶：往同一张库塞一条「进程死了没人写终态」的 running，再重开 store
        dbPath = str(defaultDbPath())
        from neurova.aigc_studio.store import StudioStore

        stray = StudioStore(db_path=dbPath)
        ghost = stray.add_run({"project_id": pid, "kind": "videos"})
        stray.close()
        print(f"5) 塞入遗留 running = {ghost['id']}（模拟进程重启后没人收尸的行）")

        reset_store()
        ghosts = [r for r in client.get(f"/api/v1/studio/projects/{pid}",
                                        headers=headers).json()["data"]["runs"]
                  if r["id"] == ghost["id"]]
        print(f"   重开 store 后读侧该行 = {[(g['status'], g['error']) for g in ghosts]}")
        assert ghosts, "重启后读侧看不到该行（属主/投影断了）"
        assert ghosts[0]["status"] == "failed", (
            f"遗留 running 未被启动收敛：{ghosts[0]['status']}——前端会一直轮它"
        )
        assert "process_died" in str(ghosts[0]["error"]), ghosts[0]["error"]

    after, afterCount = fingerprintDataDir()
    print(f"6) 仓内 data/ 未被写入：{before[:12]}…({beforeCount}) → {after[:12]}…({afterCount})")
    assert before == after, "活体把数据写进了仓库 data/（隔离失效）"

    print(f"   store 落点 = {dbPath}")
    print("LIVE-VERIFY PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
