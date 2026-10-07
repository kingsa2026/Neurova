# -*- coding: utf-8 -*-
"""`parked` 非终态：让位闸超限后，这条回合在库里必须"活着等人"。

拍板口径是「最多等 10 次、每次 ≤20s，超时直接挂起等待人工续跑」。落到库层
就是三条硬要求，每条都对着今天的一个缺失形态（不是偏好）：

- **parked 不是终态**：`reconcile_at_startup` 绝不能顺手收敛它。否则"等人工"
  在一次重启后变成 `failed(process_died)`，人工再也没东西可点——这条能力
  的意义恰恰是"活过进程"。
- **park 必须交还同 session 单活槽并松开 owner 栅栏**：行若留在 `running`，
  `claim_next` 的 `NOT EXISTS (… status='running')` 会把整个会话永久挡住，
  用户连"续跑"都发不出去；而 lease 继续过期又会被 `reconcile_stale` 误杀。
- **续跑复用原行**（`seq` 不变，故仍排在队列头），不是再 `intake` 一条：
  否则一个挂起回合在库里长出第二个身份，审计与"这条已跑过没有"都读错。

另外钉两条数据卫生：待跑载荷（含用户原文）只在该行确实挂着时存在，**写终态
即清空**；`stats()` 必须单列 parked——现形态把一切未知状态折进 `terminal`，
新状态一旦进去就把"等人"读成"已结束"。
"""
from __future__ import annotations

import sqlite3

import pytest

from neurova.core import agent_run_store as ars
from neurova.core.db_migration import latest_version, schema_version


@pytest.fixture()
def store(tmp_path):
    s = ars.AgentRunStore(tmp_path / "parked.db")
    yield s
    s.close()


def _runningRun(store, session_id="s1", message="m"):
    run_id = store.intake(session_id, "u1", "a1", message)
    assert store.claim_next(session_id) == run_id
    return run_id


def test_parkIsNonTerminalAndReleasesOwnerFence(store):
    """park 后：非终态、不再是 running、owner 松开、park_reason 有据可查。"""
    run_id = _runningRun(store)
    assert ars.PARKED_STATUS not in ars.TERMINAL_STATUSES, "parked 混进终态就没有'等人'可言"

    assert store.park(run_id, ars.OWNER_IDENTITY, "rate_limit_cooldown", {"message": "hi"}) is True

    row = store.get(run_id)
    assert row["status"] == ars.PARKED_STATUS
    assert row["park_reason"] == "rate_limit_cooldown"
    assert row["finished_at"] in (None, 0), "非终态不得写 finished_at"
    assert row["owner"] == "", "owner 不松开＝幽灵续租面还在"
    assert store.active_run("s1") is None, "parked 不得占据同 session 单活槽"


def test_parkedTurnDoesNotBlockTheNextTurn(store):
    """会话里挂起一条之后，下一条消息仍要能正常晋升——否则"挂起"等于"卡死整个会话"。"""
    parked = _runningRun(store, message="stuck-turn")
    store.park(parked, ars.OWNER_IDENTITY, "rate_limit_cooldown", {"message": "stuck-turn"})

    nxt = store.intake("s1", "u1", "a1", "next-turn")
    assert store.claim_next("s1") == nxt, "parked 行把后来的回合挡在队列外"


def test_parkedRowsSurviveStartupReconcile(tmp_path):
    """跨重启保留：新进程构造 store 时只收敛 running/queued，parked 原样留着。"""
    db = tmp_path / "ghost-parked.db"
    s1 = ars.AgentRunStore(db)
    parked = _runningRun(s1, session_id="sp", message="wait-for-human")
    s1.park(parked, ars.OWNER_IDENTITY, "model_pin_violation", {"message": "wait-for-human"})
    ghost = s1.intake("sq", "u1", "a1", "ghost")
    s1.claim_next("sq")
    s1.close()

    s2 = ars.AgentRunStore(db)  # 构造即 reconcile_at_startup
    assert s2.get(parked)["status"] == ars.PARKED_STATUS, "重启把'等人工'抹成了终态"
    assert s2.get(parked)["park_reason"] == "model_pin_violation"
    assert s2.get(ghost)["status"] == "failed"
    s2.close()


def test_resumeReusesTheSameRowAsQueueHead(store):
    """续跑把 parked 翻回 queued 并交还载荷；seq 不变 → 它排在会话队列最前。"""
    parked = _runningRun(store, session_id="sr", message="parked-turn")
    store.park(parked, ars.OWNER_IDENTITY, "rate_limit_cooldown", {"message": "parked-turn", "model": "gpt-x"})
    later = store.intake("sr", "u1", "a1", "later-queued")

    row = store.takeForResume(parked)
    assert row is not None
    assert row["status"] == ars.PARKED_STATUS, "返回值应是翻转前的行（调用方据此判定）"
    assert "parked-turn" in row["resume_payload"]
    assert store.get(parked)["resume_payload"] in (None, ""), "载荷交给调用方后库里不该再留一份"

    # 挂起的回合提交得更早（seq 更小），翻回 queued 后必须抢到队头
    assert store.claim_next("sr") == parked
    assert store.get(parked)["status"] == "running"
    assert store.get(later)["status"] == "queued"


def test_takeForResumeRefusesNonParkedRows(store):
    """只有 parked 能被取走；running/queued/终态一律拒绝（防同一回合被起两遍）。"""
    run_id = _runningRun(store, session_id="sx")
    assert store.takeForResume(run_id) is None, "running 行被 resume 取走＝双执行"
    store.finish(run_id, ars.OWNER_IDENTITY, "completed")
    assert store.takeForResume(run_id) is None
    assert store.takeForResume("run_missing") is None


def test_cancelConvergesParkedRowImmediately(store):
    """挂起行没有执行体：stop 的持久取消意图应直接落终态，而不是留一条永远等人停不掉的行。"""
    run_id = _runningRun(store, session_id="sc")
    store.park(run_id, ars.OWNER_IDENTITY, "rate_limit_cooldown", {"message": "m"})

    assert store.request_cancel("sc") == run_id
    row = store.get(run_id)
    assert row["status"] == "cancelled"
    assert row["error_type"] == "user_stopped_while_parked"


def test_statsCountsParkedSeparatelyFromTerminal(store):
    """现形态把未知状态折进 terminal——parked 一旦进去，看板就把"等人"读成"已结束"。"""
    parked = _runningRun(store, session_id="ss", message="p")
    store.park(parked, ars.OWNER_IDENTITY, "rate_limit_cooldown", {"message": "p"})
    done = _runningRun(store, session_id="ss", message="d")
    store.finish(done, ars.OWNER_IDENTITY, "completed")

    counts = store.stats()
    assert counts[ars.PARKED_STATUS] == 1
    assert counts["terminal"] == 1, "parked 被折进 terminal 了"


def test_resumePayloadClearedOnTerminal(store):
    """载荷里是用户原文：写终态即清空，不在库里长期滞留。"""
    run_id = _runningRun(store, session_id="sd")
    store.park(run_id, ars.OWNER_IDENTITY, "rate_limit_cooldown", {"message": "secret-ish text"})
    assert "secret-ish text" in store.get(run_id)["resume_payload"]

    assert store.takeForResume(run_id) is not None
    assert store.claim_next("sd") == run_id
    store.finish(run_id, ars.OWNER_IDENTITY, "completed")
    assert store.get(run_id)["resume_payload"] in (None, ""), "终态行仍留着用户原文"
    assert store.get(run_id)["park_reason"] == "rate_limit_cooldown", "原因要留着供审计"


def test_existingV1DatabaseUpgradesInPlace(tmp_path):
    """升级路径真跑：只带 v1 schema 的存量库，经生产装配点打开后补上两列并落到最新版本。"""
    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(db)
    conn.executescript(ars._SCHEMA)
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()

    s = ars.AgentRunStore(db)
    cols = {r[1] for r in s._conn.execute("PRAGMA table_info(agent_runs)")}
    assert {"park_reason", "resume_payload"} <= cols, f"存量库未补齐 parked 所需列: {sorted(cols)}"
    assert schema_version(s._conn) == latest_version("agent_runs")
    s.close()
