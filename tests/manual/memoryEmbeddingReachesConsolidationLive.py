"""活体：正文出口补上 `embedding` 键之后，睡眠合并这条路第一次真能走通。

跑法（仓库根）：
    PYTHONPATH="$(git rev-parse --show-toplevel)" .venv/Scripts/python.exe \\
        tests/manual/memoryEmbeddingReachesConsolidationLive.py

问三件事，逐件给读数：
  一 出口形状：真 `Memory.to_dict()` 现在带不带得出 `embedding`（此前 23 键里根本没有它）；
  二 跨界闭环：给真 agent 的真记忆对象填上嵌入（**现网写侧没人填**，这是本档唯一一处替生产
     补数据，理由现量在 §6-214 那张票里），经生产取数面 `get_all_memories()` 交给真
     `sleep_consolidation`，能不能聚出一个 ≥2 源的簇、写回能不能把合并产物落进正文库；
  三 退役防线仍在位（§6-214）：合并之后第二轮不得把已 soft-forget 的源再合一次。

判据只断一、二、三这三件应当成立的事；"现网今天还没有嵌入"这一件不写断言（那是 §6-214
票里"要不要开始写嵌入"的裁定对象，不是本档的契约）。
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests" / "manual"))

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from _liveVerifyIsolation import isolatedAgentWorkspaces, isolatedDataRoot  # noqa: E402

EMB_A = [1.0, 0.5, 0.25, 0.0]
EMB_B = [0.97, 0.53, 0.24, 0.02]

readings = {}
failures = []


def _bodyRows(dbPath: Path):
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
    from neurova.cognitive_layers.memory_layer.models import Memory
    from neurova.cognitive_layers.memory_layer.sleep import MemoryRecord
    from neurova.cognitive_layers.memory_layer.sleep_writeback import (
        write_back_consolidation_result,
    )

    # 一、出口形状
    sample = Memory(id="m_probe", content="c")
    sample.embedding = list(EMB_A)
    dictKeys = sorted(sample.to_dict().keys())
    readings["to_dict_has_embedding_key"] = "embedding" in dictKeys
    readings["to_dict_embedding_value"] = sample.to_dict().get("embedding")
    readings["to_dict_key_count"] = len(dictKeys)
    readings["empty_embedding_shape"] = Memory(id="m_e", content="c").to_dict().get("embedding")
    if "embedding" not in dictKeys:
        failures.append("正文出口仍不带 embedding ⇒ 本批那一行没装配上（键集合=%s）" % dictKeys)

    app = create_app()
    with TestClient(app):
        from neurova.api.endpoints import get_agent_instance

        agent = get_agent_instance("default")
        manager = agent.memory_manager
        sleep = agent.sleep_consolidation
        bodyPath = Path(manager._persist_db_path)

        manager.remember(content="登录页验证码在弱网下超时，活体甲例")
        manager.remember(content="登录页验证码在弱网下超时，活体乙例")
        manager.remember(content="会议纪要讨论排期与预算，活体丙例")

        with manager._lock:
            targets = [m for m in manager._memories.values() if "验证码" in (m.content or "")]
            for mem, emb in zip(targets, (EMB_A, EMB_B)):
                mem.embedding = list(emb)

        readings["seeded_rows"] = len(_bodyRows(bodyPath))

        def productionFaceRecords():
            return [MemoryRecord.from_dict(m) for m in manager.get_all_memories()]

        # 二、跨界闭环
        recs1 = productionFaceRecords()
        readings["face_embedding_lengths"] = [len(r.embedding) for r in recs1]
        if not any(r.embedding for r in recs1):
            failures.append("给真对象填了嵌入，经生产取数面却又全是空 ⇒ 出口到记录这条链仍断")

        res1 = sleep.run_sleep_cycle(recs1, phase="deep_sleep")
        clusters1 = [sorted(getattr(r, "source_ids", []) or [])
                     for r in (res1.get("merge_results") or [])]
        readings["round1_clusters"] = clusters1
        realMerges = [c for c in clusters1 if len(c) >= 2]
        readings["round1_real_merge"] = realMerges
        stats1 = write_back_consolidation_result(manager, res1)
        readings["round1_writeback"] = stats1
        rowsAfter1 = _bodyRows(bodyPath)
        readings["rows_after_round1"] = len(rowsAfter1)
        retired = {rid for rid, stage in rowsAfter1 if str(stage) == "forgotten"}
        readings["retired_after_round1"] = sorted(retired)
        if not realMerges:
            failures.append("填了嵌入仍聚不出 ≥2 源的簇 ⇒ "
                            "『这条路走得通』没有被证明（簇=%s）" % clusters1)

        # 三、退役防线仍在位
        res2 = sleep.run_sleep_cycle(productionFaceRecords(), phase="deep_sleep")
        clusters2 = [sorted(getattr(r, "source_ids", []) or [])
                     for r in (res2.get("merge_results") or [])]
        readings["round2_clusters"] = clusters2
        write_back_consolidation_result(manager, res2)
        rowsAfter2 = _bodyRows(bodyPath)
        readings["rows_after_round2"] = len(rowsAfter2)
        remerged = [c for c in clusters2 if c and set(c) <= retired]
        if remerged:
            failures.append("第二轮又把已 soft-forget 的源合了一次：%s ⇒ §6-214 的防线失守" % remerged)
        if retired and len(rowsAfter2) != len(rowsAfter1):
            failures.append("第二轮正文库长了行：%d → %d" % (len(rowsAfter1), len(rowsAfter2)))


def main() -> int:
    _run()
    print(json.dumps(readings, ensure_ascii=False, indent=2, default=str))
    if failures:
        print("FAIL")
        for line in failures:
            print("  - %s" % line)
        return 1
    print("PASS（出口带得出嵌入、合并这条路经生产面真走通一次、退役防线仍在位）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
