# -*- coding: utf-8 -*-
"""H2-1a 的 live-verify：真 app 起来后，镜头视频行在**没有任何人 GET 的情况下**被收敛。

跑的真生产对象：真 `create_app()` + `TestClient`（走真 lifespan 的启动与关闭钩子）、
真 `StudioStore`、真 `GenerationTaskLedger`、真 `startReconcileSweep` 周期驱动器。
数据根走 `_liveVerifyIsolation.isolatedDataRoot()` 单点。

判据（缺一条这条链就是断的）：

1. 起始态是 `running`——并且**在 app 起来之前不去读它**（改前"没人来看"就永远不收敛，
   这条是整批的对照面）；
2. lifespan 启动后，驱动器自己把它回写成 `done` 并把产物路径写进镜头行；
3. 账本行丢失的那条镜头被诚实标 `failed` 并带点名原因，不再停在 `running`
   （改前是 `continue`：既收不了口，`services` 的 running 闸门又拒绝重跑）；
4. 关闭后不遗留仍在跑的 task（否则 TestClient teardown 会被不收敛的 task 拖住）。

一条命令复现：
PYTHONPATH="E:/项目/Neurova" .venv/Scripts/python.exe tests/manual/videoReconcile_noReader_live.py

如实记一句：本层证「lifespan 接线 → 周期驱动 → 镜头行回写」这段在路上，**不证**
`recovery.py` 对上游服务商的轮询正确性（那是账本侧，已有 §6-78 E 条另计）。
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

WAIT_S = 45.0


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

    from neurova.aigc_studio.store import get_store
    from neurova.api.app import create_app
    from neurova.llm.generators import task_ledger as ledger_mod

    store = get_store()
    led = ledger_mod.get_generation_task_ledger()

    project = store.create_project("live_u", title="收口活体")
    ep = store.add_episode(project["id"], {"number": 1, "title": "e"})

    artifact = Path(DATA_ROOT) / "live_video.mp4"
    artifact.write_bytes(b"FAKE-MP4-BYTES")
    good = led.add(ledger_mod.TaskRecord(kind="video", status="succeeded",
                                         local_path=str(artifact), remote_task_id="r-good"))
    sbGood = store.add_storyboard(ep["id"], {"number": 1, "video_status": "running",
                                             "ledger_task_id": good.task_id})
    # 账本里根本没有这条：改前它会让镜头永久停在 running
    sbDangling = store.add_storyboard(ep["id"], {"number": 2, "video_status": "running",
                                                 "ledger_task_id": "task_does_not_exist"})

    before = {
        "good": store.get_storyboard(sbGood["id"])["video_status"],
        "dangling": store.get_storyboard(sbDangling["id"])["video_status"],
    }
    print(f"起始态（app 未起、无人 GET）= {before}")
    assert before == {"good": "running", "dangling": "running"}, before

    fpBefore, nBefore = fingerprintDataDir()

    with TestClient(create_app()) as client:
        client.get("/api/v1/health")           # 真 lifespan 已随 with 进入
        deadline = time.time() + WAIT_S
        goodRow = danglingRow = None
        while time.time() < deadline:
            goodRow = store.get_storyboard(sbGood["id"])
            danglingRow = store.get_storyboard(sbDangling["id"])
            if goodRow["video_status"] != "running" and danglingRow["video_status"] != "running":
                break
            time.sleep(0.5)

    print(f"收敛读数：good.video_status={goodRow['video_status']!r} "
          f"video_path={Path(goodRow['video_path']).name!r} | "
          f"dangling.video_status={danglingRow['video_status']!r} "
          f"error={danglingRow['error'][:40]!r}")

    failures = []
    if goodRow["video_status"] != "done":
        failures.append(f"镜头没被驱动器收敛：{goodRow}")
    if not goodRow["video_path"].endswith("live_video.mp4"):
        failures.append(f"产物路径没写进镜头行：{goodRow['video_path']!r}")
    if danglingRow["video_status"] != "failed":
        failures.append(f"悬空账本仍停在 running：{danglingRow}")
    if "ledger_task_missing" not in (danglingRow["error"] or ""):
        failures.append(f"悬空收尾没留点名原因：{danglingRow['error']!r}")

    from neurova.aigc_studio import video_reconcile as vr

    if vr._sweepTask is not None and not vr._sweepTask.done():
        failures.append("关闭后仍遗留活着的收口 task")

    fpAfter, nAfter = fingerprintDataDir()
    print(f"仓内 data/ 指纹：before={fpBefore[:12]}({nBefore}) after={fpAfter[:12]}({nAfter})")
    if fpBefore != fpAfter:
        failures.append("活体探针写进了仓内真实 data/ —— 数据根隔离没生效")

    if failures:
        for f in failures:
            print("FAIL:", f)
        return 1
    print("VIDEO RECONCILE LIVE VERIFY PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
