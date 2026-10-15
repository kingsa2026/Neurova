"""活体：真 agent 装配的那只睡眠对象，两轮闭环里会不会把已 soft-forget 的源再合一次。

跑法（仓库根）：
    PYTHONPATH="$(git rev-parse --show-toplevel)" .venv/Scripts/python.exe \\
        tests/manual/sleepRetiredSourcesNotReMergedLive.py

走的是生产那条腿本身：`create_app()` 起来取真 agent 的 `sleep_consolidation` 与
`memory_manager`，输入面用 `manager.get_all_memories()`（与 `sleep.py:826`、
`idle_tracker` 同一个取法），周期用 `run_sleep_cycle(phase="deep_sleep")`，
写回用 `write_back_consolidation_result`——不是替身，也不是我自己 new 的整合器。

嵌入在隔离数据根下拿不到（那里没有 providers.json，本档也不往里塞真凭据），
所以按生产行的形状把嵌入直接注到真 Memory 对象上再落盘；这是本档唯一一处替生产补数据，
且它只影响"能不能聚成簇"，不影响被问的那件事（退役行为）。
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests" / "manual"))

# 中文输出：stdout 重定向到文件时默认走系统 ANSI 码页（中文 Windows = cp936），
# 读数里的 ⇒ 之类会直接 UnicodeEncodeError（与 `start_server.py` 顶部同一处理）。
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from _liveVerifyIsolation import isolatedAgentWorkspaces, isolatedDataRoot  # noqa: E402

SAME_EMB = [1.0, 0.5, 0.25]
OTHER_EMB = [0.0, 0.0, 1.0]

readings = {}
failures = []


def _bodyRows(dbPath: Path):
    if not dbPath.exists():
        return []
    con = sqlite3.connect("file:%s?mode=ro" % dbPath.as_posix(), uri=True)
    try:
        return con.execute("select id, lifecycle_stage from memories order by id").fetchall()
    finally:
        con.close()


def _run() -> None:
    isolatedDataRoot(prefix="neurovaLive")
    isolatedAgentWorkspaces(prefix="neurovaLive")

    from fastapi.testclient import TestClient

    from neurova.api.app import create_app
    from neurova.cognitive_layers.memory_layer.sleep import MemoryRecord
    from neurova.cognitive_layers.memory_layer.sleep_writeback import (
        write_back_consolidation_result,
    )

    app = create_app()
    with TestClient(app):
        from neurova.api.endpoints import get_agent_instance

        agent = get_agent_instance("default")
        manager = agent.memory_manager
        sleep = agent.sleep_consolidation
        readings["real_sleep_object"] = type(sleep).__name__
        readings["real_manager_object"] = type(manager).__name__

        # 正文库位置按真 manager 的自陈取，不手拼路径
        bodyPath = Path(manager._persist_db_path)

        manager.remember(content="登录页验证码在弱网下加载超时")
        manager.remember(content="登录页验证码在弱网下加载超时，用户已提交投诉")
        manager.remember(content="本周会议纪要讨论了排期与预算分配")

        readings["rows_after_seed"] = len(_bodyRows(bodyPath))

        def recordsFromProductionFace():
            # 嵌入在**记录面**注入，且这是本档第二处替生产补数据。理由现量在此：
            # 真正文库的 `embedding` 列 0 非空（default 12 行 / kai 4 行都量为 0），
            # 而 `cluster_by_similarity` 只在两边都有嵌入时才打分 ⇒ 不注入就恒单例簇，
            # 本档会"全绿"却没咬到任何被测面。注入只决定"能不能聚成簇"，
            # 不改被问的那件事（退役行还进不进聚类）。
            out = []
            for m in manager.get_all_memories():
                rec = MemoryRecord.from_dict(m)
                rec.embedding = OTHER_EMB if "会议纪要" in (m.get("content") or "") else SAME_EMB
                out.append(rec)
            return out

        readings["to_dict_carries_embedding"] = bool(
            (manager.get_all_memories()[0] or {}).get("embedding"))

        def clustersOf(res):
            return [sorted(getattr(r, "source_ids", []) or [])
                    for r in (res.get("merge_results") or [])]

        # ── 第一轮 ──
        # 装配诊断：soft-forget 有归属校验，脱离请求边界跑活体时生效作用域可能不同——
        # 先把这一件摆出来，否则"第二轮还在合并"会被误读成修复无效。
        readings["effective_scope"] = {
            "neuser": manager._eff_neuser_id(),
            "user": manager._eff_user_id(),
            "agent": manager._agent_id,
        }
        forgetOutcomes = []
        originalForget = manager.forget

        def forgetSpy(memory_id, soft=True, agent_wide=False):
            ok = originalForget(memory_id, soft=soft, agent_wide=agent_wide)
            forgetOutcomes.append((memory_id, bool(ok)))
            return ok

        manager.forget = forgetSpy  # type: ignore[method-assign]

        res1 = sleep.run_sleep_cycle(recordsFromProductionFace(), phase="deep_sleep")
        real1 = [c for c in clustersOf(res1) if len(c) >= 2]
        readings["round1_clusters"] = clustersOf(res1)
        readings["round1_writeback"] = write_back_consolidation_result(manager, res1)
        readings["round1_forget_outcomes"] = list(forgetOutcomes)
        forgetOutcomes.clear()
        rowsAfter1 = _bodyRows(bodyPath)
        readings["rows_after_round1"] = len(rowsAfter1)
        retired = {rid for rid, stage in rowsAfter1 if str(stage) == "forgotten"}
        readings["retired_ids_after_round1"] = sorted(retired)
        if not retired:
            failures.append("第一轮没把任何源标成 forgotten ⇒ 后续断言全是空转，"
                            "本档没咬到被测面（round1 簇=%s）" % clustersOf(res1))

        # ── 第二轮：完全照生产驱动再走一遍 ──
        touched = []
        originalUpdate = manager.update_memory

        def spy(**kwargs):
            touched.append(kwargs.get("memory_id"))
            return originalUpdate(**kwargs)

        manager.update_memory = spy  # type: ignore[method-assign]
        res2 = sleep.run_sleep_cycle(recordsFromProductionFace(), phase="deep_sleep")
        readings["round2_clusters"] = clustersOf(res2)
        readings["round2_writeback"] = write_back_consolidation_result(manager, res2)
        manager.update_memory = originalUpdate  # type: ignore[method-assign]

        rowsAfter2 = _bodyRows(bodyPath)
        readings["rows_after_round2"] = len(rowsAfter2)
        readings["round2_updates_on_retired"] = sorted(set(touched) & retired)

        remerged = [c for c in clustersOf(res2) if c and set(c) <= retired]
        if remerged:
            failures.append("第二轮把已 soft-forget 的源又合并了一次：%s ⇒ 每轮稳定 +1 行"
                            % remerged)
        if len(rowsAfter2) != len(rowsAfter1):
            failures.append("正文库在第二轮长了行：%d → %d"
                            % (len(rowsAfter1), len(rowsAfter2)))
        if readings["round2_updates_on_retired"]:
            failures.append("退役行仍被写回逐条 update：%s" % readings["round2_updates_on_retired"])


def main() -> int:
    _run()
    print(json.dumps(readings, ensure_ascii=False, indent=2, default=str))
    if failures:
        print("FAIL")
        for line in failures:
            print("  - %s" % line)
        return 1
    print("PASS（退役行不再进聚类、正文库第二轮零增长、写回不碰退役行）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
