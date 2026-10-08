# -*- coding: utf-8 -*-
"""H2-7 · ③的 live-verify：四列退役后，真端点与真投影照跑，且退役面真的收不到东西。

跑的真生产对象：真 `create_app()` + `TestClient`（真 lifespan）、真
`POST /episodes/{eid}/storyboards/manual`、`PUT /episodes/{eid}`、`PUT /storyboards/{sid}`、
`POST /episodes/{eid}/storyboards`（走真 `break_storyboards` + 真 LLM 边界替身）、
真 `GET /episodes/{eid}` 投影、真 `StudioStore`。只替 LLM 与 auth 身份。
数据根走 `_liveVerifyIsolation.isolatedDataRoot()`。

判据（退役批最容易出的事故是"删过头"和"旧库崩"，所以两面都要真跑）：
1. 手动新增镜头时在 body 里塞 `bgm_prompt`/`sound_effect` → 200 且落库行**没有**这两个键
   （白名单不收，不是报错，也不是静默落库）；
2. `PUT /episodes/{eid}` 塞 `duration` → 分集行里没有 `duration` 键（episodes 侧退役），
   但同一行的 `subtitle_path` 键**必须在**（那是活列，删了就断字幕链路）；
3. 拆解 LLM 照旧回这两个字段 → 落库行不含它们，而 `title`/`duration`/`atmosphere` 完好；
4. 镜头投影里活列齐全：`image_prompt`/`video_prompt`/`injected_prompt`/`video_resolution`
   /`first_frame_path`/`subtitle_path`(仅 episodes 活) —— 防"扫平整表也绿"；
5. 老库形态（手工把退役列加回去）在同一真栈上开库、写镜、读镜不报错；
6. 仓内真实 `data/` 未被写动。

一条命令复现（机器无关串）：
PYTHONPATH="$(git rev-parse --show-toplevel)" .venv/Scripts/python.exe tests/manual/retiredShotColumns_live.py
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
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
USER = {"user_id": "u-live", "role": "admin"}
RETIRED = ("bgm_prompt", "sound_effect")
TERMINAL = ("done", "done_with_fallback", "failed")


def fingerprintDataDir():
    items = []
    if REPO_DATA_DIR.exists():
        for p in sorted(REPO_DATA_DIR.rglob("*")):
            if p.is_file():
                st = p.stat()
                items.append(f"{p.relative_to(REPO_DATA_DIR)}:{st.st_size}:{st.st_mtime_ns}")
    digest = hashlib.sha256("\n".join(items).encode("utf-8")).hexdigest() if items else "empty"
    return digest, len(items)


async def _shotsJson(prompt: str, system: str) -> str:
    return json.dumps([{"number": 1, "title": "雨夜对峙", "description": "推门",
                        "image_prompt": "a man pushes the door", "video_prompt": "推门",
                        "narration": "他回来了", "camera": "中景", "movement": "固定",
                        "atmosphere": "冷调夜雨", "bgm_prompt": "古琴",
                        "sound_effect": "雨声", "duration": 4,
                        "characters": [], "props": [],
                        "scene": "", "scene_time": ""}], ensure_ascii=False)


def main() -> int:
    from fastapi.testclient import TestClient

    from neurova.aigc_studio import services
    from neurova.aigc_studio.store import StudioStore, get_store
    from neurova.api.app import create_app
    from neurova.api.deps import get_current_user

    failures = []
    before, nBefore = fingerprintDataDir()
    services.call_llm = _shotsJson

    store = get_store()
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: dict(USER)
    with TestClient(app) as client:
        pid = client.post(f"{BASE}/projects", json={"title": "退役面", "style": "国风水墨"}
                          ).json()["data"]["project"]["id"]
        eid = store.add_episode(pid, {"number": 1, "title": "e1", "content": "客厅夜"})["id"]

        # 1. 手动新增：退役键不得进白名单，也不得让请求坏掉
        r = client.post(f"{BASE}/episodes/{eid}/storyboards/manual",
                        json={"number": 9, "title": "手动镜", "description": "关门",
                              "image_prompt": "door closes",
                              "bgm_prompt": "该被丢掉", "sound_effect": "该被丢掉",
                              "duration": 5})
        if r.status_code != 200:
            failures.append(f"手动新增被退役键弄坏了：{r.status_code} {r.text[:120]}")
        sb = r.json()["data"]["storyboard"]
        for name in RETIRED:
            if name in sb:
                failures.append(f"手动新增仍收了退役键 {name}：{sb[name]!r}")

        # 2. PUT 分集：duration 退役、subtitle_path 是活列
        client.put(f"{BASE}/episodes/{eid}", json={"title": "e1", "duration": 99})
        ep = client.get(f"{BASE}/projects/{pid}").json()["data"]["episodes"][0]
        if "duration" in ep:
            failures.append(f"episodes.duration 已退役却仍在行里：{ep['duration']!r}")
        if "subtitle_path" not in ep:
            failures.append(f"episodes.subtitle_path（活列）被误删：键都不在了 → {sorted(ep)}")

        # 3. 拆解：LLM 照旧回那两个字段
        #    （另开一集：`break_storyboards` 在"已有镜头且非 force"时是早退复用，
        #    拿上一集测就等于没测拆解本身。）
        eid2 = store.add_episode(pid, {"number": 2, "title": "e2", "content": "雪夜"})["id"]
        r = client.post(f"{BASE}/episodes/{eid2}/storyboards", json={})
        runId = r.json()["data"]["run_id"]
        deadline = time.time() + 25.0
        status = ""
        while time.time() < deadline:
            runs = client.get(f"{BASE}/projects/{pid}").json()["data"]["runs"]
            status = next((x["status"] for x in runs if x["id"] == runId), "")
            if status in TERMINAL:
                break
            time.sleep(0.1)
        rows = client.get(f"{BASE}/episodes/{eid2}").json()["data"]["storyboards"]
        shot = next((x for x in rows if x.get("title") == "雨夜对峙"), {})
        print(f"拆解读数：run={status!r} 镜头数={len(rows)} 键={sorted(shot)[:8]}…")
        for name in RETIRED:
            if name in shot:
                failures.append(f"拆解仍把退役字段落库 {name}={shot[name]!r}")
        if shot.get("atmosphere") != "冷调夜雨" or float(shot.get("duration") or 0) != 4:
            failures.append(f"同一次拆解里的在役列被顺手弄坏：{shot.get('atmosphere')!r}/"
                            f"{shot.get('duration')!r}")

        # 4. 活列齐全的投影面
        for live in ("image_prompt", "video_prompt", "injected_prompt",
                     "video_resolution", "first_frame_path", "ledger_task_id", "audio_path"):
            if live not in shot:
                failures.append(f"投影缺在役列 {live}（退役不该波及它）：{sorted(shot)}")

    # 5. 老库形态：把退役列加回去再开一次库
    legacy = StudioStore(db_path=str(DATA_ROOT / "legacy_probe.db"))
    legacy.close()
    conn = sqlite3.connect(DATA_ROOT / "legacy_probe.db")
    conn.execute("ALTER TABLE storyboards ADD COLUMN bgm_prompt TEXT DEFAULT ''")
    conn.execute("ALTER TABLE storyboards ADD COLUMN sound_effect TEXT DEFAULT ''")
    conn.execute("ALTER TABLE episodes ADD COLUMN duration REAL DEFAULT 0")
    conn.commit()
    conn.close()
    try:
        again = StudioStore(db_path=str(DATA_ROOT / "legacy_probe.db"))
        p2 = again.create_project(owner_user_id="u-live", title="旧库")["id"]
        e2 = again.add_episode(p2, {"number": 1, "content": "夜"})["id"]
        s2 = again.add_storyboard(e2, {"number": 1, "image_prompt": "x", "duration": 3})["id"]
        again.update_storyboard(s2, {"status": "image_ready"})
        row = again.get_storyboard(s2)
        if row["duration"] != 3 or row["status"] != "image_ready":
            failures.append(f"旧库形态下写读失真：{row.get('duration')!r}/{row.get('status')!r}")
        again.close()
    except Exception as e:  # noqa: BLE001 - 这正是本判据要抓的形态
        failures.append(f"老库残留退役列导致开库/读写崩：{type(e).__name__}: {e}")

    after, nAfter = fingerprintDataDir()
    print(f"仓内 data/ 指纹：before={before[:12]}({nBefore}) after={after[:12]}({nAfter})")
    if after != before:
        failures.append("仓内 data/ 被写动了")
    if failures:
        for f in failures:
            print("FAIL:", f)
        return 1
    print("H2-7 RETIRED SHOT COLUMNS LIVE VERIFY PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
