#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B4/008 召回作用域闸口 live-verify：真库、真跨进程、真闸口判定。

手工运行，不进 CI；写盘全在系统临时目录（不碰 data/ 生产库）。
用法：PYTHONPATH=. python tests/manual/context_ledger_recall_scope_90.py

验四件事（判据 A8 + 规格 D13）：
- 群聊归档落库后，在**单聊轮**与**无会话池**召回均不可见（改前无会话池可见）；
- 群轮可见 direct + 本群；他群互不可见；
- 判据与视图路径同源：两条路径都经 `memory_scope.filter_by_scope`
  （探针打在事实源函数上，复刻第二份规则会被抓出）；
- 跨进程：另一进程同库开池召回，闸口对其同样生效（闸口不在进程内缓存里）。
"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402
isolatedDataRoot()

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

ROOM_CONTENT = "群聊归档：量子项目代号 ZEPHYR-9（房间 project_roomB）"
DIRECT_CONTENT = "单聊归档：家里地址在某某路"
OTHER_ROOM_CONTENT = "他群归档：专属代号 ATLAS-3（房间 project_roomA）"
USER_ID = "u1"
AGENT_ID = "a1"


def seed(dbPath):
    from neurova.context.eviction_ledger_db import EvictionLedgerDB

    ledger = EvictionLedgerDB(db_path=dbPath, user_id=USER_ID, agent_id=AGENT_ID)
    ledger.record(content=ROOM_CONTENT, session_id="project_roomB", chat_scope="room:project_roomB")
    ledger.record(content=OTHER_ROOM_CONTENT, session_id="project_roomA", chat_scope="room:project_roomA")
    ledger.record(content=DIRECT_CONTENT, session_id="s_direct", chat_scope="direct")
    ledger.close()


def recall(dbPath, *, sessionId, turnScope=None, query=None):
    from neurova.context.eviction_ledger_db import EvictionLedgerDB
    from neurova.context_pool import ContextPool

    pool = ContextPool(
        user_id=USER_ID, agent_id=AGENT_ID, session_id=sessionId, ttl_seconds=0,
        ledger_db=EvictionLedgerDB(db_path=dbPath, user_id=USER_ID, agent_id=AGENT_ID),
    )
    if turnScope:
        pool.turn_scope = turnScope
    contents = [str(c.content) for c in pool.recall_evicted(query=query, limit=10)]
    pool.close()
    return contents


def recallFromChildProcess(dbPath, sessionId):
    """另一进程同库开池召回（闸口必须同样生效，不能只在本进程内存里成立）。"""
    code = (
        "import sys; sys.path.insert(0, %r)\n"
        "from neurova.context.eviction_ledger_db import EvictionLedgerDB\n"
        "from neurova.context_pool import ContextPool\n"
        "pool = ContextPool(user_id=%r, agent_id=%r, session_id=%r, ttl_seconds=0,\n"
        "    ledger_db=EvictionLedgerDB(db_path=sys.argv[1], user_id=%r, agent_id=%r))\n"
        "print('|'.join(str(c.content) for c in pool.recall_evicted(limit=10)))\n"
        "pool.close()\n"
    ) % (ROOT, USER_ID, AGENT_ID, sessionId, USER_ID, AGENT_ID)
    run = subprocess.run([sys.executable, "-c", code, dbPath], capture_output=True, text=True)
    if run.returncode != 0:
        raise RuntimeError(f"子进程召回失败：\n{run.stdout[-1200:]}\n{run.stderr[-1200:]}")
    out = run.stdout.strip().splitlines()
    return [c for c in (out[-1].split("|") if out else []) if c]


def sameSourceProbe(dbPath):
    """两路判据同源：召回路径必须走 `memory_scope.filter_by_scope`。

    探针打在**事实源函数**上。若召回侧自己复刻了一份作用域判定（第二份规则），
    这个探针就抓不到任何调用——那正是本判据要防的形态。
    """
    from neurova.collaboration import memory_scope
    from neurova.context.eviction_ledger_db import EvictionLedgerDB
    from neurova.context_pool import ContextPool

    calls = []
    original = memory_scope.filter_by_scope

    def counting(items, metadata_of, **kwargs):
        calls.append(kwargs)
        return original(items, metadata_of, **kwargs)

    memory_scope.filter_by_scope = counting
    try:
        pool = ContextPool(
            user_id=USER_ID, agent_id=AGENT_ID, session_id="s_direct", ttl_seconds=0,
            ledger_db=EvictionLedgerDB(db_path=dbPath, user_id=USER_ID, agent_id=AGENT_ID),
        )
        pool.recall_evicted(limit=10)
        pool.close()
    finally:
        memory_scope.filter_by_scope = original
    return {"recall_path_calls": len(calls), "kwargs": calls}


def main():
    tmp = tempfile.mkdtemp(prefix="ctxRecallScope90_")
    dbPath = os.path.join(tmp, "scope.db")
    seed(dbPath)
    print(f"[setup] 临时目录: {tmp}")
    print(f"[0 库内前像] {json.dumps({'rows': sqlite3.connect(dbPath).execute('SELECT COUNT(*) FROM evicted_chunks').fetchone()[0]}, ensure_ascii=False)}")

    direct = recall(dbPath, sessionId="s_direct")
    print(f"[1 单聊轮召回] {json.dumps(direct, ensure_ascii=False)}")
    assert ROOM_CONTENT not in direct, "群聊归档在单聊轮可见"
    assert OTHER_ROOM_CONTENT not in direct, "他群归档在单聊轮可见"
    assert DIRECT_CONTENT in direct, "单聊自己的归档被挡掉（修过头）"

    sessionless = recall(dbPath, sessionId=None)
    print(f"[2 无会话池召回] {json.dumps(sessionless, ensure_ascii=False)}")
    assert ROOM_CONTENT not in sessionless, "无会话池看到房间内容（改前正是此处泄露）"
    assert OTHER_ROOM_CONTENT not in sessionless, "无会话池看到他群内容"

    inRoom = recall(dbPath, sessionId="project_roomB", turnScope="room:project_roomB")
    print(f"[3 群 B 轮召回] {json.dumps(inRoom, ensure_ascii=False)}")
    assert ROOM_CONTENT in inRoom, "本群归档被挡掉（修过头）"
    assert DIRECT_CONTENT in inRoom, "群轮应可见 direct 归档"
    assert OTHER_ROOM_CONTENT not in inRoom, "他群内容在本群轮可见"

    child = recallFromChildProcess(dbPath, "s_direct")
    print(f"[4 跨进程（单聊池）] {json.dumps(child, ensure_ascii=False)}")
    assert ROOM_CONTENT not in child, "另一进程里群聊归档仍可见（闸口只在本进程生效）"

    probe = sameSourceProbe(dbPath)
    print(f"[5 判据同源探针] {json.dumps(probe, ensure_ascii=False)}")
    assert probe["recall_path_calls"] >= 1, (
        "召回路径没走 memory_scope.filter_by_scope（复刻了第二份作用域规则）"
    )

    print(
        "\nLIVE-VERIFY PASSED：群聊归档在单聊轮与无会话池均不可见（含跨进程），"
        "群轮见 direct + 本群，他群互不可见，判据与视图路径同源"
    )


if __name__ == "__main__":
    main()
