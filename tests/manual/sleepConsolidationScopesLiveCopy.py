"""现网正文库的**副本**上跑真入口：跨归属不并、同归属该合的合、退役腿在源行自己的作用域里真落地。

跑法（仓库根）：
    PYTHONPATH="$(git rev-parse --show-toplevel)" .venv/Scripts/python.exe tests/manual/sleepConsolidationScopesLiveCopy.py

为什么要它：§6-223 那条"写回的退役与温度腿被归属校验整段拒"是在现网读出来的，
而单元格的夹具是新造的库。本档把**现网那份库原样拷进隔离工作区**，再用真 `create_app()`
+ 真 agent 的 `sleep_consolidation.start_sleep()`（生产入口）跑一轮，问四件事：

1. 同一只 agent 内**不同 neuser/user** 的行不再被并进同一簇（乙）；
2. 同归属的逐字重复照旧合并（不收得过紧）；
3. 被合并的源**真的退役了**（`forgotten` 不再是 0），且产物行落在**源行自己的作用域**（甲）；
4. 单例行在本轮之前那一腿（温度）也不再被归属门拒——盘上温度真的降了。

现网那份库里两组形状都是现成的：`(default, ne-alice, alice)` 名下有 `ALIVE-私密记忆`×3
与 `DB-探针`×2（该合），`(default, default, default)` 名下有两条
`你好，测试一下` / `用户: 你好，测试一下`（余弦实测低于近等价下限 ⇒ 该不合）。

只读现网、只写副本：两份根都走 `_liveVerifyIsolation` 的注入口，跑完打印副本落点。
"""
from __future__ import annotations

import json
import shutil
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

LIVE_DIR = Path("agent_workspaces/default/memory")
LIVE_DB = LIVE_DIR / "neurova_memories_persist.db"


def _rows(dbPath: Path):
    con = sqlite3.connect(f"file:{dbPath.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute("select * from memories order by id").fetchall()]
    finally:
        con.close()


def _active(rows):
    return [r for r in rows if str(r["lifecycle_stage"]) not in ("archived", "forgotten")]


def _provenance(row):
    try:
        return json.loads(row.get("metadata") or "{}").get("merged_from")
    except Exception:  # noqa: BLE001
        return None


def _run() -> None:
    isolatedDataRoot(prefix="neurovaLive")
    workspaceRoot = isolatedAgentWorkspaces(prefix="neurovaLive")

    if not LIVE_DB.exists():
        print(json.dumps({"error": f"现网正文库不在 expected 处: {LIVE_DB}"}))
        return

    # 现网那份库原样拷进隔离工作区（含 WAL/SHM，未检查点的内容也带过来）
    targetDir = Path(workspaceRoot) / "default" / "memory"
    targetDir.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        src = Path(str(LIVE_DB) + suffix)
        if src.exists():
            shutil.copy2(src, str(targetDir / (LIVE_DB.name + suffix)))
    for extra in ("memory.db", "motivation.json"):
        if (LIVE_DIR / extra).exists():
            shutil.copy2(LIVE_DIR / extra, targetDir / extra)
    copyDb = targetDir / LIVE_DB.name
    readings["copy_under"] = str(targetDir)

    from fastapi.testclient import TestClient

    from neurova.api.app import create_app

    app = create_app()
    with TestClient(app):
        from neurova.api.endpoints import get_agent_instance

        agent = get_agent_instance("default")
        manager = agent.memory_manager
        sleep = agent.sleep_consolidation

        before = _rows(copyDb)
        readings["rows_before"] = len(before)
        readings["scopes_before"] = sorted({
            (r["agent_id"], r["neuser_id"], r["user_id"]) for r in before
        })
        readings["embeddings_filled"] = sum(
            1 for r in before if (r.get("embedding") or "").strip() not in ("", "[]", "None")
        )
        readings["consolidation_enabled"] = sleep.get_settings().get("memory_consolidation_enabled")

        # 现网那份库里留着**上一批（§6-223 之前那一轮）写下的产物残迹**：那两行是旧代码写的，
        # 落在 `(default,default)` 而它们的源属 `ne-alice`。本档**不动它们**（也不动现网）——
        # 它们要作为读数摆出来，判据只问"本轮新增的行有没有造出同作用域的重复载体"。
        idsBefore = {r["id"] for r in before}
        residue = [r for r in before
                   if str(r["id"]).startswith("merged_") and _provenance(r)]
        readings["live_residue"] = [
            {"id": r["id"], "scope": (r["neuser_id"], r["user_id"]),
             "merged_from": _provenance(r)} for r in residue
        ]

        result = sleep.start_sleep(duration_minutes=1)
        readings["start_sleep_result"] = result

        after = _rows(copyDb)
        activeAfter = _active(after)
        readings["rows_after"] = len(after)
        readings["active_after"] = len(activeAfter)
        # 本轮的产物按"本轮新长出来的 id"认，不按 id 前缀认——前缀会把上一批的同名残迹也算进来
        newRows = [r for r in after if r["id"] not in idsBefore]
        readings["new_rows"] = [
            {"id": r["id"], "scope": (r["neuser_id"], r["user_id"]),
             "content": (r["content"] or "")[:20], "merged_from": _provenance(r)}
            for r in newRows
        ]
        readings["products"] = [n for n in readings["new_rows"] if n["merged_from"]]
        readings["retired"] = sorted(
            (r["id"], r["neuser_id"], r["user_id"]) for r in after
            if str(r["lifecycle_stage"]) in ("archived", "forgotten")
        )

        # 一、跨归属不并：产物的 merged_from 必须全在同一作用域，且产物归属等于源行归属
        byId = {r["id"]: (r["neuser_id"], r["user_id"]) for r in after}
        for product in readings["products"]:
            sources = product["merged_from"] or []
            sourceScopes = {byId.get(sid) for sid in sources}
            if len(sourceScopes) > 1:
                failures.append(
                    "产物 %s 的源跨了 %d 个作用域 %s ⇒ 乙 的分桶没生效" % (
                        product["id"], len(sourceScopes), sorted(str(s) for s in sourceScopes))
                )
            if sourceScopes and sourceScopes != {(product["scope"][0], product["scope"][1])}:
                failures.append(
                    "产物落在 %s 而它的源属 %s ⇒ 甲 那条「进入源行自己的作用域」没落地" % (
                        product["scope"], sorted(str(s) for s in sourceScopes))
                )

        # 二、同归属的逐字重复该合，且**源真的退役**（§6-223 的病就是这一腿被拒）
        aliceDupeIds = [r["id"] for r in before
                        if r["neuser_id"] == "ne-alice"
                        and (r["content"] or "").startswith("ALIVE-私密记忆")]
        if aliceDupeIds:
            stillActive = [i for i in aliceDupeIds if i in {r["id"] for r in activeAfter}]
            readings["alice_verbatim_dupes"] = aliceDupeIds
            readings["alice_dupes_still_active"] = stillActive
            if len(aliceDupeIds) >= 2 and stillActive:
                failures.append(
                    "alice 名下 %d 条逐字重复里有 %d 条合并后仍活跃 ⇒ 退役那一腿照旧被拒"
                    % (len(aliceDupeIds), len(stillActive))
                )

        # 二之二、本轮新增的行不得与**本轮之后仍活跃**的其他行同作用域、同内容
        # （对照集是"之后仍活跃"的那些，不是"之前活跃"的那些——本轮被退役的源本来就该与新产物
        # 同内容，拿它们当对照会把正确结果读成缺陷）。上一批的旧残迹落在别的作用域，不记在本轮账上。
        activeIdsAfter = {x["id"] for x in activeAfter}
        byActive = {}
        for r in activeAfter:
            byActive.setdefault(
                ((r["neuser_id"], r["user_id"]), (r["content"] or "").strip()), []
            ).append(r["id"])
        duplicatesCreated = []
        for r in newRows:
            if r["id"] not in activeIdsAfter:
                continue
            clashes = [i for i in byActive.get(
                ((r["neuser_id"], r["user_id"]), (r["content"] or "").strip()), []
            ) if i != r["id"]]
            if clashes:
                duplicatesCreated.append((r["id"], clashes))
        readings["duplicates_created_by_this_round"] = duplicatesCreated
        if duplicatesCreated:
            failures.append(
                "本轮新增与仍活跃的行在同作用域内容重复 %s ⇒ 合并造出了同一事实的两个载体"
                % duplicatesCreated
            )

        # 三、低于下限的一对**不许**被并（不收得过紧，也不放得过松）
        helloIds = [r["id"] for r in before
                    if (r["content"] or "").replace("用户: ", "") == "你好，测试一下"]
        mergedAnyHello = any(
            set(p["merged_from"] or []) & set(helloIds) for p in readings["products"]
        )
        readings["hello_pair_ids"] = helloIds
        readings["hello_pair_merged"] = mergedAnyHello
        if len(helloIds) >= 2 and mergedAnyHello:
            failures.append("余弦低于近等价下限的一对被并了 ⇒ 甲3 的下限在这份真数据上失效")

        # 四、温度腿不再被归属门拒：至少有一行的温度比本轮之前低
        tempBefore = {r["id"]: float(r["temperature"]) for r in before}
        lowered = [r["id"] for r in after
                   if r["id"] in tempBefore and float(r["temperature"]) < tempBefore[r["id"]]]
        readings["temperatures_lowered"] = len(lowered)
        if not lowered:
            failures.append("盘上没有一行的温度降下来 ⇒ 温度腿照旧没做成（或被拒而被计入 updated）")


def main() -> int:
    _run()
    print(json.dumps(readings, ensure_ascii=False, indent=2, default=str))
    if failures:
        print("FAIL")
        for line in failures:
            print("  - %s" % line)
        return 1
    print("PASS（跨归属不并、同归属重复真收拢、产物落源行作用域、温度腿真落地）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
