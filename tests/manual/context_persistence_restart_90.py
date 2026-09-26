#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B4/001 跨重启召回 live-verify：真 Agent 构造面 + 真跨进程。

手工运行，不进 CI；写盘全在系统临时目录（不碰 data/ 生产库）。
用法：PYTHONPATH=. python tests/manual/context_persistence_restart_90.py

验三件事（判据 A1 与写入侧契约）：
- 进程 A：真 `Agent` → 真 `ContextOrchestrator` → 生产归档路径写入 → 退出；
- 进程 B：同 agent_id、同库、新进程 → `recall_evicted(query)` 取回原文，逐字相等；
- 进程 B：写穿计数与失败面可从 `get_retention_stats()` 读出（不静默）。
"""
import json
import os
import subprocess
import sys
import tempfile

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402
isolatedDataRoot()

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

SECRETS = [
    "第一轮：设备固件升级窗口定在周四凌晨两点",
    "第二轮：固件校验和用 sha256 而不是 md5，旧固件保留一个版本",
    "第三轮：灰度顺序先华东后华南，回滚演练在周五下午",
]


def _agent(agent_id):
    from neurova.agent_core import Agent, AgentConfig

    return Agent(
        AgentConfig(name=agent_id, agent_id=agent_id, llm_model="gpt-4o", workspace_path=os.getcwd())
    )


def writer(agent_id):
    """子进程 A：走生产归档路径写入后退出。"""
    agent = _agent(agent_id)
    pool = agent.context_orchestrator.context_pool
    messages = [{"role": "user", "content": s} for s in SECRETS]
    agent.context_orchestrator._archive_conversation_to_pool(messages)
    stats = pool.get_retention_stats()["ledger_persistence"]
    print(json.dumps({
        "role": "writer",
        "pool_session_id": pool.session_id,
        "ledger_enabled": stats["enabled"],
        "resident": pool.resident_count(),
        "write_through": stats["written"],
        "failed": stats["failed"],
        "db_rows": pool._ledger_db.count(),
    }, ensure_ascii=False))


def reader(agent_id):
    """子进程 B：同库新开池读取（模拟重启）。"""
    agent = _agent(agent_id)
    pool = agent.context_orchestrator.context_pool
    recalled = pool.recall_evicted(query="固件", limit=10)
    print(json.dumps({
        "role": "reader",
        "resident": pool.resident_count(),
        "recalled": [c.content for c in recalled],
        "sources": sorted({c.metadata.get("recalled_from") for c in recalled}),
    }, ensure_ascii=False))


def _spawn(fn_name, agent_id, cwd):
    env = dict(os.environ)
    env["PYTHONPATH"] = ROOT
    env["NEUROVA_AGENT_DB"] = os.path.join(cwd, "agent.db")
    run = subprocess.run(
        [sys.executable, "-c", f"import sys; sys.path.insert(0, {ROOT!r}); "
                               f"import tests.manual.context_persistence_restart_90 as m; "
                               f"m.{fn_name}({agent_id!r})"],
        cwd=cwd, env=env, capture_output=True, text=True,
    )
    if run.returncode != 0:
        raise RuntimeError(f"{fn_name} 子进程失败：\n{run.stdout[-2000:]}\n{run.stderr[-2000:]}")
    return json.loads(run.stdout.strip().splitlines()[-1])


def main():
    workdir = tempfile.mkdtemp(prefix="ctxRestart90_")
    agent_id = "ctx90"
    print(f"[setup] 临时工作目录: {workdir}（含 data/context_ledger/{agent_id}.db）")

    wrote = _spawn("writer", agent_id, workdir)
    print(f"[A 进程写入后退出] {json.dumps(wrote, ensure_ascii=False)}")
    assert wrote["ledger_enabled"], "生产构造面未注入持久台账"
    assert wrote["failed"] == 0, "写穿失败面不为 0（先看日志点名原因）"
    assert wrote["write_through"] >= len(SECRETS), "入池条目未写穿持久台账"
    assert wrote["db_rows"] >= len(SECRETS), "台账 DB 里没有刚写入的内容"

    read = _spawn("reader", agent_id, workdir)
    print(f"[B 进程新开池读取] {json.dumps(read, ensure_ascii=False)}")
    assert read["resident"] == 0, "新进程常驻非空（常驻集本就是进程内的）"
    expected = [s for s in reversed(SECRETS) if "固件" in s]
    assert read["recalled"] == expected, f"A1 失败：新进程召回 {read['recalled']} ≠ 原文 {expected}"
    assert read["sources"] == ["ledger_db"], "召回源不是持久台账"

    print("\nLIVE-VERIFY PASSED：归档活过真跨进程重启（A1），写穿面可观测，零失败")


if __name__ == "__main__":
    main()
