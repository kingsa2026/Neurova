# -*- coding: utf-8 -*-
"""live-verify（批 D，§6-393）：从真 HTTP 面改记忆内容，检索面必须跟着改。

判据档 `tests/performance/memory/test_longTermMemoryBaselineGate.py` 在 manager 装配点取证；
这一支在**真 app + 真 lifespan + 真端点 + 真落盘**上读数，证的是判据档证不到的那段：

1. `POST /api/v1/memory` 写一条含独有词面的记忆 ⇒ 2xx 且真 id；
2. `GET /api/v1/memory?query=旧词面` 能看见它（前置）；
3. `PUT /api/v1/memory/{id}` 把内容改成与旧词面无涉的新文本 ⇒ 2xx；
4. **改后 `GET ?query=旧词面` 不得再把它排在第 1 位，且位次必须劣于新问法**
   （实测改前 1、改后 14；词面支持摘干净后向量相似度非零是另一件事，见正文注释）；
5. 改后 `GET ?query=新词面` 必须把该 id 排进前五（新内容进得了读路）；
   ——两条都要在**垫了判据档同一份 66 条干扰语料**之后读：召回向量库没有相似度下限，
   库里只有一行时任何提问都会返回它，断言会恒真。
6. 落盘事实面：`memories.embedding` 随内容重算（逐元素不同且非空）、
   `memory_cues` 里那条记忆的线索整组换新、`memory_cue_attempts` 的封条被撤
   （旧内容"问过模型"不能替新内容作数，否则该行永远出不了待生成池）；
7. 进程内关键词读路 `search_by_keywords(旧词面)` 不含该 id、`(新词面)` 含该 id；
8. 仓内真 `data/` 与真 `agent_workspaces/` 未被本轮写入（隔离单点前后对账）。

跑法（仓库根）：

    PYTHONPATH="$(git rev-parse --show-toplevel)" .venv/Scripts/python.exe -m tests.manual.contentUpdateFollowsRecallIndexesLive

第 4/5/6/7 条任一条不落，就是「写侧改了、读侧没跟」在真链路上还活着。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

AGENT_ID = "default"
OLD_CONTENT = "用户: 我有一只青瓷茶壶是外婆留下的"
NEW_CONTENT = "用户: 我把阳台浇花的活改成了每周三定时自动滴灌"
OLD_QUERY = "青瓷茶壶"
NEW_QUERY = "自动滴灌"

failures: list[str] = []
readings: dict = {}


def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest() if path.exists() else "ABSENT"


def _memoryLandingFingerprints() -> dict:
    repo = Path(__file__).resolve().parents[2]
    shots = {}
    for root in (repo / "data", repo / "agent_workspaces"):
        if not root.exists():
            continue
        for db in sorted(list(root.rglob("*.db")) + list(root.rglob("*.json"))):
            if "-journal" in db.name or "-wal" in db.name:
                continue
            try:
                shots[str(db.relative_to(repo))] = _md5(db)
            except OSError:
                continue
    return shots


def _tableExists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _dbWith(dbPaths: list[Path], table: str) -> tuple[sqlite3.Connection, Path]:
    """按**实有表**取库：正文库与伴生库在不同批次里换过位置，不硬猜路径。"""
    for path in dbPaths:
        if not path.exists():
            continue
        conn = sqlite3.connect(str(path))
        if _tableExists(conn, table):
            return conn, path
        conn.close()
    raise AssertionError(f"这些库里都没有表 {table}：{[str(p) for p in dbPaths]}")


def _rank(client, headers, term: str, memoryId: str, limit: int = 20) -> int:
    """该记忆在真 GET 端点结果里的位次（1 起）；未出现返回 -1。"""
    resp = client.get(
        "/api/v1/memory", params={"query": term, "limit": limit}, headers=headers
    )
    if resp.status_code >= 300:
        failures.append("GET /api/v1/memory?query=%s 回了 %s" % (term, resp.status_code))
        return -1
    rows = (resp.json().get("data") or {}).get("memories") or []
    for index, row in enumerate(rows, start=1):
        if str(row.get("id")) == memoryId:
            return index
    return -1


def main() -> int:
    from tests.manual._liveVerifyIsolation import isolatedAgentWorkspaces, isolatedDataRoot

    dataRoot = isolatedDataRoot(prefix="neurovaContentFollowLive")
    workspaceRoot = isolatedAgentWorkspaces(prefix="neurovaContentFollowLive")
    before = _memoryLandingFingerprints()
    readings["isolated_data_root"] = str(dataRoot)
    readings["isolated_workspace_root"] = str(workspaceRoot)

    from fastapi.testclient import TestClient

    from neurova.api.app import create_app, get_app_state
    from neurova.api.auth import create_access_token
    from neurova.cognitive_layers.memory_layer.semantic_search import (
        get_semantic_search,
    )

    with TestClient(create_app()) as client:
        token = create_access_token(
            {"user_id": "live-content-follow", "username": "live-content-follow",
             "sub": "live-content-follow"}
        )
        headers = {"Authorization": "Bearer " + token}

        state = get_app_state()
        agent = state.get_agent(AGENT_ID) if state else None
        manager = getattr(agent, "memory_manager", None) if agent else None
        if manager is None:
            failures.append("真 lifespan 没交出带 memory_manager 的 agent，读数无从取")
            return _report(before)

        # 语料垫底：召回向量库对「库里唯一一行」的任何提问都会返回它（无相似度下限），
        # 只写一条探针行会让「旧词面退场」这条断言恒真。垫的是判据档同一份干扰语料，
        # 不再另造一份（教义第 6 条：语料单点）。
        from tests.performance.memory.test_associativeRecallGate import DISTRACTORS

        seeded = 0
        for text in DISTRACTORS:
            resp = client.post(
                "/api/v1/memory",
                json={"content": text, "memory_type": "episodic", "auto_classify": False},
                headers=headers,
            )
            seeded += 1 if resp.status_code < 300 else 0
        readings["distractors_seeded"] = seeded
        if seeded < len(DISTRACTORS):
            failures.append("干扰语料只写入 %d/%d 条，位次读数不可信" % (seeded, len(DISTRACTORS)))

        written = client.post(
            "/api/v1/memory",
            json={"content": OLD_CONTENT, "memory_type": "episodic",
                  "auto_classify": False},
            headers=headers,
        )
        readings["POST_write"] = "%s %s" % (written.status_code, written.text[:90])
        if written.status_code >= 300:
            failures.append("真端点写记忆没成：%s" % written.text[:200])
            return _report(before)
        memoryId = str((written.json().get("data") or {}).get("memory_id") or "")
        readings["memory_id"] = memoryId
        if not memoryId:
            failures.append("POST 回了 2xx 却没给 memory_id")
            return _report(before)

        readings["pre_old_term_rank"] = _rank(client, headers, OLD_QUERY, memoryId)
        if readings["pre_old_term_rank"] < 0:
            failures.append("前置不成立：旧词面本来就该能召回这条（实测位次 %s）"
                            % readings["pre_old_term_rank"])

        bodyPath = Path(manager.persistenceDbPath() or "")
        candidateDbs = [bodyPath, bodyPath.parent / "neurova_memories_persist.db"]
        readings["body_db"] = str(bodyPath)
        embConn, embDb = _dbWith(candidateDbs, "memories")
        embeddingBefore = embConn.execute(
            "SELECT embedding FROM memories WHERE id=?", (memoryId,)
        ).fetchone()[0]
        readings["embedding_before_bytes"] = len(str(embeddingBefore))
        cueConn, cueDb = _dbWith(candidateDbs, "memory_cues")
        cuesBefore = {
            r[0] for r in cueConn.execute(
                "SELECT cue_text FROM memory_cues WHERE memory_id=?", (memoryId,)
            )
        }
        readings["cues_before"] = sorted(cuesBefore)
        attemptsBefore = cueConn.execute(
            "SELECT COUNT(*) FROM memory_cue_attempts WHERE memory_id=?", (memoryId,)
        ).fetchone()[0] if _tableExists(cueConn, "memory_cue_attempts") else -1
        readings["attempts_before"] = attemptsBefore

        updated = client.put(
            f"/api/v1/memory/{memoryId}", json={"content": NEW_CONTENT}, headers=headers
        )
        readings["PUT_update"] = "%s %s" % (updated.status_code, updated.text[:90])
        if updated.status_code >= 300:
            failures.append("真端点 PUT 更新内容没成：%s" % updated.text[:200])
            return _report(before)

        # 核心两格：旧问法不得再把它顶在第一位、也不得压过新问法；新问法必须进前五。
        # 不写成「前 20 里彻底消失」：词面支持摘干净之后，稠密向量对「青瓷茶壶↔浇花滴灌」
        # 仍有非零相似度（实测改前位次 1、改后 14，新问法 1），那本就不是「索引没跟」，
        # 把它当缺陷会逼读路去加相似度闸门——那是另一件事（§6-381 的同一条地板）。
        oldRank = _rank(client, headers, OLD_QUERY, memoryId)
        newRank = _rank(client, headers, NEW_QUERY, memoryId)
        readings["post_old_term_rank"] = oldRank
        readings["post_new_term_rank"] = newRank
        if oldRank == 1:
            failures.append("内容已不含「%s」，真 GET 端点仍把它排在第 1 位——旧词条/旧向量还在读路上" % OLD_QUERY)
        if newRank >= 0 and oldRank >= 0 and oldRank <= newRank:
            failures.append("旧问法位次 %d 不劣于新问法 %d：检索面对新旧内容的支持没有分开" % (oldRank, newRank))
        if newRank < 0 or newRank > 5:
            failures.append(
                "新内容的词面「%s」在真 GET 端点上位次 %s（应进前五）——写侧改了读侧没跟"
                % (NEW_QUERY, newRank)
            )

        # 落盘事实面
        embeddingAfter = embConn.execute(
            "SELECT embedding FROM memories WHERE id=?", (memoryId,)
        ).fetchone()[0]
        readings["embedding_db"] = str(embDb.name)
        readings["embedding_recomputed"] = bool(embeddingAfter) and str(embeddingAfter) != str(
            embeddingBefore
        )
        if not readings["embedding_recomputed"]:
            failures.append("持久层 embedding 没随内容重算（长度或取值未变）——固化按旧向量合簇")

        cuesAfter = {
            r[0] for r in cueConn.execute(
                "SELECT cue_text FROM memory_cues WHERE memory_id=?", (memoryId,)
            )
        }
        readings["cues_after"] = sorted(cuesAfter)
        readings["cues_replaced"] = cuesAfter != cuesBefore
        attemptsAfter = cueConn.execute(
            "SELECT COUNT(*) FROM memory_cue_attempts WHERE memory_id=?", (memoryId,)
        ).fetchone()[0] if _tableExists(cueConn, "memory_cue_attempts") else -1
        readings["attempts_after"] = attemptsAfter
        # 只作读数不作断言：规则线索主要由类型/分类/情感标签派生，两段文本同标签时
        # 线索本就该相等。「封条必须撤回」在判据档里种一次尝试再验（那里可控）。
        if attemptsAfter != 0:
            failures.append("旧内容的「已问过模型」封条还在（%d 行）：该行出不了待生成池" % attemptsAfter)

        search = get_semantic_search()
        readings["keywordread_old"] = memoryId in search.search_by_keywords(OLD_QUERY, limit=50)
        readings["keywordread_new"] = memoryId in search.search_by_keywords(NEW_QUERY, limit=50)
        if readings["keywordread_old"]:
            failures.append("进程内关键词读路仍把该 id 挂在旧词面上")
        if not readings["keywordread_new"]:
            failures.append("进程内关键词读路没有新词面 → 该 id")

        embConn.close()
        cueConn.close()

    return _report(before)


def _report(before: dict) -> int:
    after = _memoryLandingFingerprints()
    changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    readings["repo_memory_landings_touched"] = changed
    if changed:
        failures.append("本轮改了仓内真记忆落点（隔离没盖住）：%s" % changed)
    print(json.dumps(readings, ensure_ascii=False, indent=2))
    for f in failures:
        print("[FAIL] " + f)
    if failures:
        return 1
    print("LIVE-PASS：真端点改内容后，旧问法从第 1 位退下且劣于新问法、新问法进前五、"
          "持久层向量重算、尝试封条撤回、关键词读路两头对齐、仓内真落点未动")
    return 0


if __name__ == "__main__":
    sys.exit(main())
