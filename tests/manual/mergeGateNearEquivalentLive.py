"""甲3 活体（§6-219 裁定 → 本批落地）：合并只在"内容近等价"时发生，且合并不丢事实。

跑法（仓库根）：
    PYTHONPATH="$(git rev-parse --show-toplevel)" .venv/Scripts/python.exe tests/manual/mergeGateNearEquivalentLive.py

问三件事，全部走生产入口（真 `create_app()` + 真 agent 的 `sleep_consolidation.start_sleep()`）：
1. **反例面**：kai 那种互不相同的真对话回合（§6-218 实测余弦 0.71~0.88，正落在旧阈之上）
   本轮**一条都不许被并掉**。
2. **正例面**：一对近等价的重复（短者是长者的前缀）——按**生产那个下限常量**决定该不该合，
   不把 0.98 抄进本档；实测余弦达得到就该合，达不到就如实报"这一对没达下限"。
3. **不丢事实的全局不变式**：跑之前每一条活跃记忆的内容，跑之后必须仍能在**某条活跃行**里
   按同一套归一化口径找到（短者是长者的子串即算在）。这条不问机制，只问结果——
   本批开工前的实测形状（产物被内容门改道成某条源、随后那条源又被退役）正是被它抓住的。

来源可回查也一并读出来：被合并的源必须有活跃产物行在 `metadata.merged_from` 里点名它们。
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from _liveVerifyIsolation import isolatedAgentWorkspaces, isolatedDataRoot  # noqa: E402

readings = {}
failures = []

#: 反例面：内容互不包含的三条真句式（形状取自 §6-218 量过的 kai 回合）
DISTINCT = (
    "冯先生，我明白你在说什么。",
    "所以，你不必害怕。",
    "冯先生，我明白你的顾虑，但这件事需要证据。",
)
#: 正例面：B 以 A 开头 ⇒ 归一化后短者是长者的子串
DUP_A = "登录页验证码在弱网环境下加载超时，用户已提交投诉并要求尽快给出修复排期。"
DUP_B = DUP_A + "复核"


def _bodyRows(dbPath: Path):
    con = sqlite3.connect("file:%s?mode=ro" % dbPath.as_posix(), uri=True)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute("select * from memories order by id").fetchall()]
    finally:
        con.close()


def _active(rows):
    from neurova.cognitive_layers.memory_layer.sleep import _RETIRED_STAGES

    return [r for r in rows if str(r.get("lifecycle_stage")) not in _RETIRED_STAGES]


def _run() -> None:
    isolatedDataRoot(prefix="neurovaLive")
    isolatedAgentWorkspaces(prefix="neurovaLive")

    from fastapi.testclient import TestClient

    from neurova.core.content_identity import normalized_key
    from neurova.cognitive_layers.memory_layer.sleep import MERGE_NEAR_EQUIV_COSINE
    from neurova.embedding import get_embedding_engine

    app = create_app_forLive()
    with TestClient(app):
        from neurova.api.endpoints import get_agent_instance

        agent = get_agent_instance("default")
        manager = agent.memory_manager
        sleep = agent.sleep_consolidation
        bodyPath = Path(manager._persist_db_path)

        readings["consolidation_enabled"] = sleep.get_settings().get("memory_consolidation_enabled")
        readings["effective_similarity_threshold"] = sleep.similarity_threshold
        readings["near_equiv_floor_from_production"] = MERGE_NEAR_EQUIV_COSINE

        for content in DISTINCT + (DUP_A, DUP_B):
            manager.remember(content=content)

        # 嵌入用真引擎算，写侧走唯一口 `persist_memory_batch`（本批不引入第二条落点）
        engine = get_embedding_engine()
        if engine is None or not engine.initialize_sync():
            print(json.dumps(readings, ensure_ascii=False, indent=2, default=str))
            print("FAIL\n  - 嵌入引擎不可用 ⇒ 合并这条腿走不到，活体不成立（不拿假向量冒充）")
            return
        with manager._lock:
            targets = list(manager._memories.values())
            for mem in targets:
                mem.embedding = list(engine.encode(mem.content))
            manager.persist_memory_batch(targets)

        before = _bodyRows(bodyPath)
        readings["rows_before"] = len(before)
        readings["cosines"] = _cosineMatrix(manager, normalized_key)
        activeBefore = {(r["id"], normalized_key(r["content"])) for r in _active(before)}
        keysBefore = [k for _id, k in activeBefore]
        idsByContent = {r["content"]: r["id"] for r in before}

        result = sleep.start_sleep(duration_minutes=1)
        readings["start_sleep_result"] = result

        after = _bodyRows(bodyPath)
        activeAfter = _active(after)
        readings["rows_after"] = len(after)
        readings["active_after"] = [
            {"id": r["id"], "content": (r["content"] or "")[:28],
             "merged_from": json.loads(r["metadata"] or "{}").get("merged_from")}
            for r in activeAfter
        ]
        activeIds = {r["id"] for r in activeAfter}

        # ── 一、反例面：三条互不相同的回合必须都还活跃 ──
        lostTurns = [c for c in DISTINCT
                     if not any(normalized_key(c) == normalized_key(r["content"]) for r in activeAfter)]
        readings["distinct_lost"] = lostTurns
        if lostTurns:
            failures.append("语义相近的不同回合被并掉了 %d 条（§6-218 的误伤照旧）：%s"
                            % (len(lostTurns), [c[:14] for c in lostTurns]))

        # ── 二、正例面：按生产常量决定该不该合 ──
        cosDup = _cosineOf(manager, normalized_key, DUP_A, DUP_B)
        readings["dup_pair_cosine"] = cosDup
        dupSourceId = idsByContent.get(DUP_A)
        dupMerged = dupSourceId is not None and dupSourceId not in activeIds
        readings["dup_pair_merged"] = dupMerged
        if cosDup is not None and cosDup >= MERGE_NEAR_EQUIV_COSINE:
            if not dupMerged:
                failures.append("余弦 %.4f 已达下限 %.2f 且内容为包含关系，却没合并 ⇒ 正例面不成立"
                                % (cosDup, MERGE_NEAR_EQUIV_COSINE))
        else:
            readings["duplicate_face_observation"] = (
                "这一对的实测余弦 %.4f 低于生产下限 %.2f ⇒ 正例面本轮未观测到（如实报，不放宽判据）"
                % (cosDup or -1.0, MERGE_NEAR_EQUIV_COSINE)
            )

        # ── 三、不丢事实的全局不变式 ──
        afterKeys = [normalized_key(r["content"]) for r in activeAfter]
        uncovered = [k for k in keysBefore if not any(k in ak for ak in afterKeys)]
        readings["facts_uncovered"] = uncovered
        if uncovered:
            failures.append("有 %d 条事实在活跃面再也找不到（合并把内容弄丢了）：%s"
                            % (len(uncovered), [k[:18] for k in uncovered]))

        # ── 四、来源可回查：退役的源必须有活跃产物点名 ──
        retiredNow = [r["id"] for r in before if r["id"] not in {a["id"] for a in activeAfter}]
        products = [json.loads(r["metadata"] or "{}").get("merged_from") or [] for r in activeAfter]
        allProvenance = {sid for group in products for sid in group}
        readings["retired_this_round"] = retiredNow
        readings["provenance_groups"] = products
        untracked = [sid for sid in retiredNow if sid not in allProvenance]
        if untracked:
            failures.append("%d 条源被退役却没有任何活跃产物在 metadata.merged_from 里点名它们：%s"
                            % (len(untracked), untracked))


def create_app_forLive():
    from neurova.api.app import create_app

    return create_app()


def _cosineMatrix(manager, normalized_key):
    """把两两余弦摆出来——判据用的是同一个 `vector_math.cosineSimilarity`，不另算一套。"""
    from neurova.core import vector_math

    items = [(m.id, m.content, list(m.embedding or [])) for m in manager._memories.values()]
    out = {}
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if not (items[i][2] and items[j][2]):
                continue
            out["%s|%s" % (items[i][1][:10], items[j][1][:10])] = round(
                vector_math.cosineSimilarity(items[i][2], items[j][2]), 4
            )
    return out


def _cosineOf(manager, normalized_key, contentA: str, contentB: str):
    from neurova.core import vector_math

    a = next((m for m in manager._memories.values() if m.content == contentA), None)
    b = next((m for m in manager._memories.values() if m.content == contentB), None)
    if a is None or b is None or not (a.embedding and b.embedding):
        return None
    return round(vector_math.cosineSimilarity(list(a.embedding), list(b.embedding)), 4)


def main() -> int:
    _run()
    print(json.dumps(readings, ensure_ascii=False, indent=2, default=str))
    if failures:
        print("FAIL")
        for line in failures:
            print("  - %s" % line)
        return 1
    print("PASS（不同回合没被并、近等价重复按生产下限处理、活跃面覆盖全部既有事实、来源可回查）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
