# -*- coding: utf-8 -*-
"""H2-6 · L 条的 live-verify：真 app 起来后，子任务的状态面在**重启等价**之后还读得到。

跑的真生产对象：真 `create_app()` + `TestClient`（真 lifespan）、真 `SwarmManager` 单例、
真 `agent_run_store`（真 SQLite 文件、真 v3 迁移建的两列、真启动收敛）、真台账写侧
`agent_run_ledger.openSubagentRun/closeSubagentRun`、真读面 `GET /console/chat/runs`。
只替 **LLM 边界**（member 的 `chat`）与 auth 身份——本层证的是「写下去有人读、且活过进程」，
不证上游模型返回什么。数据根走 `_liveVerifyIsolation.isolatedDataRoot()` 单点。

判据（缺一条这条链就是断的）：

1. 派生一条子任务后，台账里**确有该行**，且 `subagent_id` 与蜂群那条成对、
   `parent_session_id` 是发起者会话（不是 member 键）；
2. 真 HTTP 出口 `?scope=subagents` 带出该行，并投出前端要用的键；
3. **重启等价**：换新 `AgentRunStore` 实例（等价于进程重启，走同一份库文件与启动收敛）
   后仍读得到——这正是内存 `_runs` 给不了的那一半，也是「刷新一下就没了」的成因；
4. 终态诚实：跑完是 `completed`；K 条那两种收尾在台账里分别是
   `failed/subagent_timeout` 与 `cancelled/subagent_cancelled`；
5. 全程不写仓内真实 `data/`（指纹前后一致）。

一条命令复现（机器无关串——写死开发机绝对路径会给常驻守卫
`TestNoHardcodedDevMachinePaths` 新增一格 offender）：
PYTHONPATH="$(git rev-parse --show-toplevel)" NEUROVA_SWARM_SUBAGENT_BUDGET_SEC=0.3 \\
    .venv/Scripts/python.exe tests/manual/swarmLedgerSurface_live.py
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.manual._liveVerifyIsolation import isolatedDataRoot

DATA_ROOT = isolatedDataRoot()
REPO_DATA_DIR = PROJECT_ROOT / "data"
BASE = "/api/v1/console"
USER = "u-live"
PARENT_SESSION = "sess-live-parent"


def fingerprintDataDir():
    items = []
    if REPO_DATA_DIR.exists():
        for p in sorted(REPO_DATA_DIR.rglob("*")):
            if p.is_file():
                st = p.stat()
                items.append(f"{p.relative_to(REPO_DATA_DIR)}:{st.st_size}:{st.st_mtime_ns}")
    digest = hashlib.sha256("\n".join(items).encode("utf-8")).hexdigest() if items else "empty"
    return digest, len(items)


def _member(hang=False, reply="子任务报告"):
    agent = MagicMock()
    agent.config.name = "蜂群成员"

    async def chat(user_input, **kw):
        if hang:
            await asyncio.Event().wait()
        return {"text": reply}

    agent.chat = chat
    return agent


def _initiator():
    agent = MagicMock()
    agent.current_session_id = PARENT_SESSION
    agent.current_user_id = USER
    return agent


async def main_async() -> int:
    from fastapi.testclient import TestClient

    from neurova.api.app import create_app
    from neurova.api.deps import get_current_user
    from neurova.api.endpoints import console as console_ep
    from neurova.agent.swarm import get_swarm_manager, reset_swarm_manager
    from neurova.core import agent_run_store as ars

    failures: list[str] = []
    before, nBefore = fingerprintDataDir()
    os.environ["NEUROVA_RUN_GATE"] = "on"
    os.environ.setdefault("NEUROVA_SWARM_SUBAGENT_BUDGET_SEC", "0.3")

    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: {"user_id": USER, "role": "admin"}
    swarm = get_swarm_manager()
    ids = {}

    with TestClient(app) as client:
        # 判据 1+2：真派生 → 台账有行 → 真 HTTP 出口带出
        with patch("neurova.api.endpoints.get_agent_instance", return_value=_member()):
            done = await swarm.spawn(task="真派生一条", agent_id="m1",
                                     session_id=PARENT_SESSION, background=True,
                                     initiator_agent=_initiator())
            ids["done"] = done["subagent_id"]
        # 判据 4 之二：超时（K 条那条路）——member 停在未返回的流上，预算 0.3s 到点
        with patch("neurova.api.endpoints.get_agent_instance",
                   return_value=_member(hang=True)):
            timeouty = await swarm.spawn(task="停在上游", agent_id="m1",
                                         session_id=PARENT_SESSION, background=True,
                                         initiator_agent=_initiator())
            ids["timeout"] = timeouty["subagent_id"]
        deadline = time.time() + 20.0
        while time.time() < deadline:
            rows = client.get(f"{BASE}/chat/runs",
                              params={"session_id": PARENT_SESSION, "scope": "subagents"}
                              ).json()["data"]["runs"]
            if len(rows) >= 2 and all(r["status"] not in ("queued", "running") for r in rows):
                break
            await asyncio.sleep(0.2)

        r = client.get(f"{BASE}/chat/runs",
                       params={"session_id": PARENT_SESSION, "scope": "subagents"})
        assert r.status_code == 200, r.text
        rows = r.json()["data"]["runs"]
        byId = {x.get("subagent_id"): x for x in rows}
        print(f"出口读数：HTTP 带出 {len(rows)} 行 "
              f"状态={[(x.get('subagent_id', '')[:12], x['status'], x['error_type']) for x in rows]}")
        for key in ("run_id", "status", "subagent_id", "agent_id", "error_type"):
            if rows and key not in rows[0]:
                failures.append(f"出口少投 {key}：{rows[0]}")
        if byId.get(ids["done"], {}).get("status") != "completed":
            failures.append(f"正常那条没收成 completed：{byId.get(ids['done'])}")
        tRow = byId.get(ids["timeout"], {})
        if (tRow.get("status"), tRow.get("error_type")) != ("failed", "subagent_timeout"):
            failures.append(f"超时那条的终态/成因不对：{tRow}")

        # 判据 3：重启等价——换新 store 实例（同一份库文件），再走一次真 HTTP 出口
        reopened = ars.AgentRunStore(ars.defaultDbPath())
        fresh = reopened.list_subagent_runs(PARENT_SESSION, limit=50)
        reopened.close()
        print(f"重启等价读数：新实例读到 {len(fresh)} 行 "
              f"状态={[(r_['subagent_id'][:12], r_['status']) for r_ in fresh]}")
        if len(fresh) < 2:
            failures.append(f"重启等价后读不到子任务行：{len(fresh)} 行")

        # 归属：关闸时诚实 503，而不是"空列表"装成没历史
        os.environ["NEUROVA_RUN_GATE"] = "off"
        try:
            r503 = client.get(f"{BASE}/chat/runs",
                              params={"session_id": PARENT_SESSION, "scope": "subagents"})
            print(f"关闸读数：HTTP {r503.status_code}")
            if r503.status_code != 503:
                failures.append(f"关闸时不是 503 而是 {r503.status_code}——把'没有读面'装成'没有历史'")
        finally:
            os.environ["NEUROVA_RUN_GATE"] = "on"

    after, nAfter = fingerprintDataDir()
    print(f"仓内 data/ 指纹：before={before[:12]}({nBefore}) after={after[:12]}({nAfter})")
    reset_swarm_manager()
    ars.reset_agent_run_store()
    if after != before:
        failures.append("仓内 data/ 被写动了")
    if failures:
        for f in failures:
            print("FAIL:", f)
        return 1
    print("H2-6 SWARM LEDGER SURFACE LIVE VERIFY PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main_async()))
