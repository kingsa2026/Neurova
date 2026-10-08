# -*- coding: utf-8 -*-
"""H2-5 · K 条的 live-verify：真蜂群跑一条挂死的子任务，槽位会自己回来。

跑的真生产对象：真 `SwarmManager` 单例（`get_swarm_manager()`，与 tool_executor
走的同一个实例）、真事件循环与真 `asyncio` 取消、真运行窗口读数
（`tool_coordinator.get_tool_timeout("spawn_subagent")`，蜂群不再自持一个数字）、
真广度闸（`MAX_ACTIVE_CHILDREN` + `_count_active`）、真逐出通道
（`_evict_finished_runs`）、真查询出口（`tool_executor.py:2282` 就是
`get_swarm_manager().status(subagent_id)`，本层按同一条口读回）。
只替 **LLM 边界**：member 的 `chat` 用替身（真模型回复要烧真配额，且本批证的是
状态机与槽位收支，不证上游返回什么）。数据根走 `_liveVerifyIsolation.isolatedDataRoot()`。

判据（缺一条这条链就是断的）：

1. 挂死的子任务在**预算到点时**落终态，`subagent_status` 读出 `failed` 且成因点名
   `subagent_timeout` 与窗口秒数——改前它永久停在 `running`；
2. 占满 5 条后第 6 条被拒，而这 5 条各自超时后**闸自己重开**（第 6 条能派生）——
   这就是「5 条卡死即蜂群整体不可用」那一格；
3. 拒案文案点名的秒数与执行侧用的是同一份读数（不各写一个数）；
4. 父任务被取消时 run 落终态并释放槽位，且 `CancelledError` 照常上抛（不吞取消）；
5. 预算默认值 == 工具层 `spawn_subagent` 那份读数（蜂群侧没另造尺度）。

一条命令复现（机器无关串——写死开发机绝对路径会给常驻守卫
`TestNoHardcodedDevMachinePaths` 新增一格 offender）：
PYTHONPATH="$(git rev-parse --show-toplevel)" NEUROVA_SWARM_SUBAGENT_BUDGET_SEC=0.3 \\
    .venv/Scripts/python.exe tests/manual/swarmTerminalUnderStall_live.py

**改前对照**：把 `_execute` 里 `asyncio.wait_for(...)` 退回裸 `await agent.chat(...)`
再跑本脚本，判据 1 会红在「读回 running、槽位永不归还」——见提交正文的反事实复跑记录。
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
BUDGET_ENV = "NEUROVA_SWARM_SUBAGENT_BUDGET_SEC"
os.environ[BUDGET_ENV] = os.environ.get(BUDGET_ENV, "0.3")


def fingerprintDataDir():
    items = []
    if REPO_DATA_DIR.exists():
        for p in sorted(REPO_DATA_DIR.rglob("*")):
            if p.is_file():
                st = p.stat()
                items.append(f"{p.relative_to(REPO_DATA_DIR)}:{st.st_size}:{st.st_mtime_ns}")
    digest = hashlib.sha256("\n".join(items).encode("utf-8")).hexdigest() if items else "empty"
    return digest, len(items)


def _member(*, hang=True, reply="子任务报告"):
    agent = MagicMock()
    agent.config.name = "蜂群成员"

    async def chat(user_input, **kw):
        if hang:
            await asyncio.Event().wait()
        return {"text": reply}

    agent.chat = chat
    return agent


async def _awaitTerminal(swarm, sid, deadlineS=5.0):
    from neurova.agent.swarm import SUBAGENT_ACTIVE_STATUSES

    deadline = asyncio.get_running_loop().time() + deadlineS
    while asyncio.get_running_loop().time() < deadline:
        record = swarm.status(sid)
        if record.get("status") not in SUBAGENT_ACTIVE_STATUSES:
            return record
        await asyncio.sleep(0.05)
    return swarm.status(sid)


async def main_async() -> int:
    from neurova.agent.swarm import (
        SUBAGENT_FAILED, SUBAGENT_FINISHED_STATUSES, SwarmManager,
        get_swarm_manager, reset_swarm_manager,
    )
    from neurova.agent.tool_coordinator import get_tool_timeout

    failures: list[str] = []
    before, nBefore = fingerprintDataDir()
    swarm = get_swarm_manager()

    budget = SwarmManager._effectiveRuntimeBudget()
    print(f"预算读数：_effectiveRuntimeBudget()={budget:g}s "
          f"工具层 spawn_subagent={get_tool_timeout('spawn_subagent'):g}s env={os.environ.get(BUDGET_ENV)}")
    if budget != float(os.environ[BUDGET_ENV]):
        failures.append(f"env 覆盖没被执行侧读到：{budget}")

    member = _member()
    with patch("neurova.api.endpoints.get_agent_instance", return_value=member):
        first = await swarm.spawn(task="停滞的上游子流", agent_id="m1", background=True)
        sid = first["subagent_id"]
        # 判据 5：预算默认取工具层那份数——把 env 撤掉再问一次
        os.environ.pop(BUDGET_ENV, None)
        inherited = SwarmManager._effectiveRuntimeBudget()
        os.environ[BUDGET_ENV] = str(budget)
    if inherited != get_tool_timeout("spawn_subagent"):
        failures.append(f"蜂群自持了另一个尺度：默认读到 {inherited}，工具层是 "
                        f"{get_tool_timeout('spawn_subagent')}")

    record = await _awaitTerminal(swarm, sid)
    print(f"超时读数：status={record['status']!r} error={record['error']!r} "
          f"运行中={len(swarm.list_active())} 条")
    if record["status"] != SUBAGENT_FAILED:
        failures.append(f"挂死件没落终态：{record['status']!r}——它会永久占着派生槽")
    elif "subagent_timeout" not in (record["error"] or ""):
        failures.append(f"终态没点名成因：{record['error']!r}")

    # 判据 2：占满 → 拒 → 全部落终态 → 闸重开
    ids = []
    with patch("neurova.api.endpoints.get_agent_instance", return_value=_member()):
        for n in range(swarm.MAX_ACTIVE_CHILDREN):
            ids.append((await swarm.spawn(task=f"占槽{n}", agent_id="m1",
                                          background=True))["subagent_id"])
        blocked = await swarm.spawn(task="第6条", agent_id="m1", background=True)
    print(f"闸读数：第6条 rejected={blocked.get('rejected')} "
          f"code={blocked.get('rejection', {}).get('code')}")
    if not blocked.get("rejected"):
        failures.append("占满 5 条却没过闸——广度保护失效（另一头的缺陷）")
    message = blocked.get("rejection", {}).get("message", "")
    if f"{budget:g}" not in message:
        failures.append(f"拒案没点名与执行侧同源的上界秒数：{message!r}")

    for sid2 in ids:
        rec = await _awaitTerminal(swarm, sid2)
        if rec["status"] not in SUBAGENT_FINISHED_STATUSES:
            failures.append(f"占槽件 {sid2} 没收尾：{rec['status']}")
    with patch("neurova.api.endpoints.get_agent_instance", return_value=_member(hang=False)):
        reopened = await swarm.spawn(task="第6条重派", agent_id="m1", background=True)
    print(f"重开读数：rejected={reopened.get('rejected')} 运行中={len(swarm.list_active())} 条")
    if reopened.get("rejected"):
        failures.append("5 条都已落终态，广度闸仍拒——槽位没真正释放（K 条的锁死形态）")

    # 判据 4：取消落终态且不上吞
    knownIds = {r["subagent_id"] for r in swarm.list_all(limit=50)}
    with patch("neurova.api.endpoints.get_agent_instance", return_value=_member()):
        runningTask = asyncio.create_task(
            swarm.spawn(task="前台长跑被取消", agent_id="m1", background=False))
        await asyncio.sleep(0.2)
        runningTask.cancel()
        cancelledPropagated = False
        try:
            await runningTask
        except asyncio.CancelledError:
            cancelledPropagated = True
    # 被取消那条的 id 只能靠差集拿（spawn 没返回就被掐了）——按"最近一条"读会读到
    # 上一条已完成的 run，那是一条判据错，不是产品错。
    fresh = [r for r in swarm.list_all(limit=50) if r["subagent_id"] not in knownIds]
    latest = fresh[0] if fresh else {}
    print(f"取消读数：status={latest['status']!r} error={latest['error']!r} "
          f"CancelledError 上抛={cancelledPropagated}")
    if not cancelledPropagated:
        failures.append("取消被吞掉了——asyncio 的取消语义会失真")
    if latest["status"] != SUBAGENT_FAILED or "subagent_cancelled" not in (latest["error"] or ""):
        failures.append(f"取消没落终态并点名：{latest['status']!r}/{latest['error']!r}")
    if swarm.list_active():
        failures.append(f"取消后仍被算作运行中：{len(swarm.list_active())} 条")

    after, nAfter = fingerprintDataDir()
    print(f"仓内 data/ 指纹：before={before[:12]}({nBefore}) after={after[:12]}({nAfter})")
    if after != before:
        failures.append("仓内 data/ 被写动了")
    reset_swarm_manager()
    if failures:
        for f in failures:
            print("FAIL:", f)
        return 1
    print("H2-5 SWARM TERMINAL UNDER STALL LIVE VERIFY PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main_async()))
