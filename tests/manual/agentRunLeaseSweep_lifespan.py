# -*- coding: utf-8 -*-
"""批次 D 的 live-verify：真 app 起来后，过期租约真的被周期扫描收敛。

跑的真生产对象：真 `create_app()` + `TestClient`（走真 lifespan 启动与关闭）、
真 `AgentRunStore`（数据根走 `_liveVerifyIsolation.isolatedDataRoot()` 单点）、
真 `intake/claim_next/park` 状态机、真扫描驱动 `startStaleSweep/stopStaleSweep`。

判据（缺一条这条链就是断的）：
1. 扫描 task 在 lifespan 启动后确实在跑（不是「启动函数存在但没人调」）；
2. 一条 `lease_expires_at` 已过期的 running 在一个间隔内被收敛成 failed(process_died)
   ——这正是「进程活着而工作卡死」的形态，改前它永远停在 running；
3. 新鲜租约的 running 不被误杀；parked 不被顺手收敛（等人续跑的状态不是死态）；
4. 关闭后不遗留仍在跑的 task（否则 TestClient teardown 会被不收敛的 task 拖住）。

一条命令复现：PYTHONPATH="E:/项目/Neurova" .venv/Scripts/python.exe tests/manual/agentRunLeaseSweep_lifespan.py

如实记一句：本层证「lifespan 接线 → 周期驱动 → 库层收敛」这段在路上，**不证** SSE
端点如何把这条终态投影给前端（那是 console.py 的读侧，属 F 批登记的 §6 另一格）。
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

isolatedDataRoot()

REPO_DATA_DIR = PROJECT_ROOT / "data"


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

    import neurova.core.agent_run_store as ars
    from neurova.api.app import create_app

    before, beforeCount = fingerprintDataDir()

    # 先构库再播种：构造期会跑一次 reconcile_at_startup，顺序反了会把种子行当遗留收敛掉
    store = ars.get_agent_run_store()

    deadRun = store.intake("sess_dead", "u1", "a1", "卡死的那一轮")
    assert store.claim_next("sess_dead", owner="w1") == deadRun
    freshRun = store.intake("sess_fresh", "u1", "a1", "正在正常跑")
    assert store.claim_next("sess_fresh", owner="w2") == freshRun
    parkedRun = store.intake("sess_parked", "u1", "a1", "等人续跑")
    assert store.claim_next("sess_parked", owner="w3") == parkedRun
    assert store.park(parkedRun, owner="w3", parkReason="quota_wait") is True

    # 只把「租约已过期」这一事实造出来，其余字段一律由生产路径写
    with store._lock, store._conn:
        store._conn.execute(
            "UPDATE agent_runs SET lease_expires_at=? WHERE run_id=?",
            (time.time() - store.lease_seconds, deadRun),
        )
        store._conn.commit()

    interval = ars.staleSweepIntervalSeconds(store)
    print(f"1) 播种：dead(租约过期)/fresh(新鲜)/parked 三条就位，扫描间隔 = {interval:.1f}s")

    app = create_app()
    observations = {}
    with TestClient(app) as client:
        taskAfterStartup = ars._sweepTask
        print(f"2) lifespan 启动后扫描 task = {taskAfterStartup}")
        assert taskAfterStartup is not None and not taskAfterStartup.done(), (
            "lifespan 没把扫描起起来：接线只在文档里存在"
        )

        deadline = time.time() + interval + 15.0
        convergedAt = None
        while time.time() < deadline:
            if store.get(deadRun)["status"] == "failed":
                convergedAt = time.time()
                break
            time.sleep(1.0)
        observations["convergedAfterSeconds"] = (
            round(interval + 15.0 - (deadline - convergedAt), 1) if convergedAt else None
        )

        deadRow, freshRow, parkedRow = store.get(deadRun), store.get(freshRun), store.get(parkedRun)
        print(f"3) 读数：dead={deadRow['status']}/{deadRow['error_type']} "
              f"fresh={freshRow['status']} parked={parkedRow['status']}")
        assert deadRow["status"] == "failed" and deadRow["error_type"] == "process_died", (
            f"过期租约没被运行期收敛（改前形态）：{deadRow}"
        )
        assert freshRow["status"] == "running", f"新鲜租约被误杀：{freshRow}"
        assert parkedRow["status"] == ars.PARKED_STATUS, f"parked 被扫描顺手收敛：{parkedRow}"
        assert client is not None

    taskAfterShutdown = ars._sweepTask
    print(f"4) lifespan 关闭后扫描 task = {taskAfterShutdown} "
          f"(旧 task done={taskAfterStartup.done()})")
    assert taskAfterShutdown is None, "关闭后仍留有 task 引用"
    assert taskAfterStartup.done(), "扫描 task 未随关闭退出"

    after, afterCount = fingerprintDataDir()
    print(f"5) 仓内 data/ 未被写入：{before[:12]}…({beforeCount}) → {after[:12]}…({afterCount})")
    assert before == after, "活体把数据写进了仓库 data/（隔离失效）"

    print(f"   收敛用时 ≈ {observations['convergedAfterSeconds']}s（间隔 {interval:.1f}s）")
    print("LIVE-VERIFY PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
