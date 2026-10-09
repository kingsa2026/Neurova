# -*- coding: utf-8 -*-
"""账本 `result_url` 的读者接上了——live-verify（§6-99，H2-2 D 条账本侧）。

跑的真生产对象：真 `create_app()` + `TestClient`（真 lifespan）、真
`POST /storyboards/{sid}/retry`（stage=video，用户点的那颗「重试」）、真 `_spawn_run`
与 runs 台账、真 `services.generate_shot_videos`、真 `video_reconcile.salvageLocalFromLedger`、
真 `GenerationTaskLedger`（磁盘上那份 json）、真 `StudioStore`（SQLite）、
**真 `persist_media`**（全仓唯一下盘口，一次下载都没替）。只替 auth 身份与服务商提交边界。
数据根走 `_liveVerifyIsolation.isolatedDataRoot()`。

为什么能用真落盘：provider 直接回内联件时账本里那条 `result_url` 是 `data:` URL
（`recovery.py:80` 那一支根本不试本地化），而 `persist_media` 原生吃这一形态——
**不需要出网、不花一分钱**，于是"抢救"这件事可以整条链真跑一遍。
`http…` 那一支在本脚本里不取证：下载要过出网安全闸且真打第三方，探针不开外网。

四格各自要在真链路上自证：

1. **不重复花钱**：账本已 `succeeded` 而本地没件 → 服务商提交边界**一次都没被调用**；
2. **件真在盘上**：镜头行 `done` + `video_path`，且那个文件的字节 == 账本里 base64 的解码
   （证明跑的是真落盘点，不是替身）；
3. **两边同源**：磁盘上那份账本 json 里 `local_path` 也补上了——只写镜头行，
   下一次收口仍会按账本判它"没本地化"；
4. **没得救时不许装救过**：另一镜的 `result_url` 是空 → 走原提交路（提交边界被调用），
   run 行的成因读数只点名真被抢救的那一镜。

一条命令复现（机器无关串）：
PYTHONPATH="$(git rev-parse --show-toplevel)" .venv/Scripts/python.exe tests/manual/salvageRemoteArtifact_live.py
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
BASE = "/api/v1/studio"
USER = {"user_id": "u-salvage", "role": "admin"}
PAYLOAD = b"NEUROVA-SALVAGE-PROBE-BYTES" * 7


def fingerprintDataDir():
    items = []
    if REPO_DATA_DIR.exists():
        for p in sorted(REPO_DATA_DIR.rglob("*")):
            if p.is_file():
                st = p.stat()
                items.append(f"{p.relative_to(REPO_DATA_DIR)}:{st.st_size}:{st.st_mtime_ns}")
    digest = hashlib.sha256("\n".join(items).encode("utf-8")).hexdigest() if items else "empty"
    return digest, len(items)


def _ledgerEntry(root: Path, taskId: str) -> dict:
    """从磁盘上那份账本 json 里取一条任务（"两边同源"要在文件上验，不在内存里验）。"""
    for p in Path(root).rglob("*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        for v in data.values():
            if isinstance(v, dict) and v.get("task_id") == taskId:
                return v
    return {}


def waitTerminal(store, rid: str, seconds: float = 60.0):
    deadline = time.time() + seconds
    while time.time() < deadline:
        row = store.get_run(rid) or {}
        if row.get("status") in ("done", "done_with_fallback", "failed", "cancelled"):
            return row
        time.sleep(0.05)
    return store.get_run(rid) or {}


def main() -> int:
    from fastapi.testclient import TestClient

    from neurova.aigc_studio import services  # noqa: F401 - 端点经它装配，先落包内引用
    from neurova.aigc_studio.store import get_store
    from neurova.api.app import create_app
    from neurova.api.deps import get_current_user
    from neurova.llm.generators import protocols as proto_mod
    from neurova.llm.generators.task_ledger import TaskRecord, get_generation_task_ledger

    failures = []
    before, nBefore = fingerprintDataDir()
    print(f"数据根={DATA_ROOT}")

    submits = {"n": 0}

    async def neverSubmit(creds, prompt, **kw):
        submits["n"] += 1
        raise AssertionError("探针里服务商提交边界被调用了——这一单不该再花钱")

    proto_mod.submit_video = neverSubmit

    store = get_store()
    led = get_generation_task_ledger()
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: dict(USER)

    dataUrl = "data:video/mp4;base64," + base64.b64encode(PAYLOAD).decode("ascii")

    def newShot(title, resultUrl):
        pid = store.create_project(owner_user_id=USER["user_id"], title=title)["id"]
        eid = store.add_episode(pid, {"number": 1, "title": "e", "content": "客厅夜"})["id"]
        sb = store.add_storyboard(eid, {"number": 1, "video_prompt": "雨夜巷口对峙",
                                        "duration": 3})
        frame = DATA_ROOT / f"frame_{sb['id']}.png"
        frame.write_bytes(b"IMG")
        rec = led.add(TaskRecord(kind="video", protocol="dashscope", model="wan",
                                 status="succeeded", remote_task_id="r-live",
                                 result_url=resultUrl, local_path="",
                                 batch_key=eid, project_id=pid))
        # §6-78 D 条留下的实况形态：收口成功但本地化失败 → 镜头已被诚实改判 failed
        store.update_storyboard(sb["id"], {
            "first_frame_path": str(frame), "ledger_task_id": rec.task_id,
            "video_status": "failed", "error": "视频已生成但本地化失败，产物未落盘"})
        return pid, eid, sb["id"], rec.task_id

    pidA, eidA, sidA, taskIdA = newShot("抢救远端件", dataUrl)
    pidB, eidB, sidB, taskIdB = newShot("没得救的一镜", "")

    with TestClient(app) as client:
        resp = client.post(f"{BASE}/storyboards/{sidA}/retry", json={"stage": "video"})
        ridA = resp.json()["data"]["run_id"]
        runA = waitTerminal(store, ridA)
        rowA = store.get_storyboard(sidA)
        detailA = json.loads(runA.get("detail_json") or "{}")
        print(f"1 提交边界调用次数={submits['n']}（应为 0）；run 终态={runA.get('status')!r}")
        print(f"2 镜头行：status={rowA['video_status']!r} error={rowA['error']!r} "
              f"video_path={rowA['video_path']!r}")
        if submits["n"] != 0:
            failures.append(f"产物还在账本里却又提交了一次（calls={submits['n']}）")
        if rowA["video_status"] != "done" or not rowA["video_path"]:
            failures.append(f"抢救成功却没收敛镜头行：{rowA}")
        saved = Path(rowA["video_path"] or "")
        if saved.is_file() and saved.read_bytes() != PAYLOAD:
            failures.append("落盘文件在，但字节不是账本里那份——跑的不是真落盘点")
        if not saved.is_file():
            failures.append(f"镜头行说件在 {rowA['video_path']!r}，磁盘上没有")

        # 读磁盘上那份账本 json（不看内存对象）——"两边同源"要在文件上成立
        entry = _ledgerEntry(DATA_ROOT, taskIdA)
        print(f"3 账本 json：local_path={entry.get('local_path')!r}")
        if not entry:
            failures.append("磁盘上的账本 json 里找不到那条任务")
        elif not entry.get("local_path"):
            failures.append("镜头行落本地件了而账本行的 local_path 还空着——下一次收口"
                            "会按账本再判一次『没本地化』")

        if runA.get("status") != "done_with_fallback":
            failures.append(f"抢救这一跳没进终态读数：{runA.get('status')!r}")
        cause = str(detailA.get("fallback") or "")
        print(f"4 run 读数：recovered={detailA.get('recovered')} "
              f"submitted={detailA.get('submitted')} fallback={cause!r}")
        if "1" not in cause or ("抢救" not in cause and "未重复提交" not in cause):
            failures.append(f"成因人读不出抢救了几条：{cause!r}")

        # ── 没得救的一镜：不许装"救过了"（本机无服务商配置，提交边界之前就挡住）──
        respB = client.post(f"{BASE}/storyboards/{sidB}/retry", json={"stage": "video"})
        runB = waitTerminal(store, respB.json()["data"]["run_id"])
        rowB = store.get_storyboard(sidB)
        detailB = json.loads(runB.get("detail_json") or "{}")
        entryB = _ledgerEntry(DATA_ROOT, taskIdB)
        print(f"5 无远端件那镜：终态={runB.get('status')!r} 镜头={rowB['video_status']!r} "
              f"error={rowB['error']!r} recovered={detailB.get('recovered')} "
              f"账本 local_path={entryB.get('local_path')!r} 提交边界累计={submits['n']}")
        if detailB.get("recovered"):
            failures.append(f"没得救却报了抢救数：{detailB}")
        if rowB["video_status"] != "failed" or not rowB["error"]:
            failures.append(f"没得救那镜没落到诚实失败：{rowB['video_status']!r}"
                            f" / {rowB['error']!r}")
        if "本地化失败" not in rowB["error"] and "抢救" in rowB["error"]:
            failures.append(f"这一镜根本没救，成因却写着抢救：{rowB['error']!r}")
        if entryB.get("local_path"):
            failures.append(f"账本里没有产物却给账本补了本地件：{entryB['local_path']!r}")
        print("   （边界说明：本机无服务商配置，这一镜在凭据解析处即诚实失败，"
              "所以活体拿不到『重复提交』那一格——它由单元判据第 3 格覆盖，不在此假装证过）")

    after, nAfter = fingerprintDataDir()
    print(f"仓内 data/ 指纹：before={before[:12]}({nBefore}) after={after[:12]}({nAfter})")
    if after != before:
        failures.append("仓内 data/ 被写动了")
    if failures:
        for f in failures:
            print("FAIL:", f)
        return 1
    print("SALVAGE REMOTE ARTIFACT LIVE VERIFY PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
