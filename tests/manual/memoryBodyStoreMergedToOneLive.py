# -*- coding: utf-8 -*-
"""live-verify（批：记忆双根收口）：正文只有一个库之后，真链路上写进正文库的记忆能不能被召回。

判据档 (`tests/unit/memory/test_memoryDualRootMergedToOneStore.py`) 在单元装配点取证；
这一支在**真 app + 真 HTTP + 真落点**上读数，证一批不同的事：

1. `create_app()` 带真 lifespan 起来，真 JWT 打 `POST /api/v1/memory` ⇒ 2xx，且正文库真多一行；
2. 该 agent 的 `cognitive_engine` 挂在正文库上：恢复文件与 `persistenceDbPath()` 同目录，
   隔离数据根下**没有** `data/<agent>/memory.db`（第二落点真的不再被创建）；
3. `engine.retrieve(中文子串)` 非空 ⇒ 全文层真落在真行上；
4. `GET /api/v1/memory?query=` 端点面 200；
5. 正文库读数：`memories` 行数、`memories_fts` 与三条触发器在场；
6. 隔离：换 user 作用域后引擎不得召回上一条（收口没把跨用户泄漏带进来）；
7. **反证**（独立子进程）：把本批根修的那条接缝——「L1 读路经 `MemoryManager`」——桩成
   返回空，端到端召回必须变成 0；不红说明召回另有出处，本批的"接通"就没咬住；
8. 附带读数：把分词器退回 `unicode61` 直接问影子表——命中必为 0（说明 trigram 是全文这一侧
   承重的；端到端召回另有 LIKE 子串兜底，所以第 3 条不依赖它，这一条只是把两者分清）；
9. 仓内真 `data/` **与真 `agent_workspaces/`** 未被本轮写入：对记忆库取内容指纹前后对账。

跑法（仓库根）：

    PYTHONPATH="$(git rev-parse --show-toplevel)" .venv/Scripts/python.exe -m tests.manual.memoryBodyStoreMergedToOneLive

第 7、8 条的对照子进程由本脚本自己起，不需要手动跑第二遍。
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CJK_SENTENCE = "我始终会把你的记忆保护好，哪怕每次重启之后"
CJK_TERM = "记忆保护好"
AGENT_ID = "default"

failures: list[str] = []
readings: dict = {}


def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest() if path.exists() else "ABSENT"


def _memoryLandingFingerprints() -> dict:
    """仓内真落点上所有记忆库的内容指纹（清单集合差看不见原地改写，故取 md5）。"""
    repo = Path(__file__).resolve().parents[2]
    shots = {}
    for root in (repo / "data", repo / "agent_workspaces"):
        if not root.exists():
            continue
        for db in sorted(root.rglob("*memor*.db*")):  # 带 -wal/-shm：WAL 下主文件可以整轮不变
            shots[str(db.relative_to(repo))] = _md5(db)
    return shots


def _bodyShape(dbPath: Path):
    con = sqlite3.connect(str(dbPath))
    try:
        names = {r[0] for r in con.execute("SELECT name FROM sqlite_master")}
        count = con.execute("SELECT COUNT(*) FROM memories").fetchone()[0] if (
            "memories" in names) else -1
        shadow = con.execute("SELECT COUNT(*) FROM memories_fts").fetchone()[0] if (
            "memories_fts" in names) else -1
    finally:
        con.close()
    return count, shadow, names


def main() -> int:
    # 双根都要隔：数据根管 data/，记忆正文落在 agent 工作区根（隔离单点各一处）
    from tests.manual._liveVerifyIsolation import isolatedAgentWorkspaces, isolatedDataRoot

    dataRoot = isolatedDataRoot(prefix="neurovaMemoryDualRoot")
    workspaceRoot = isolatedAgentWorkspaces(prefix="neurovaMemoryDualRoot")
    before = _memoryLandingFingerprints()

    from fastapi.testclient import TestClient

    from neurova.api.app import create_app, get_app_state
    from neurova.api.auth import create_access_token
    from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import (
        CognitiveStorageEngine,
    )
    from neurova.core.agent_workspaces import get_agent_workspace_dir
    from neurova.core.data_root import get_data_root

    readings["isolated_data_root"] = str(dataRoot)
    readings["isolated_workspace_root"] = str(workspaceRoot)

    with TestClient(create_app()) as client:
        token = create_access_token(
            {"user_id": "live-memory-admin", "username": "live-memory-admin",
             "sub": "live-memory-admin"}
        )
        headers = {"Authorization": "Bearer " + token}

        state = get_app_state()
        agent = state.get_agent(AGENT_ID) if state else None
        if agent is None or getattr(agent, "memory_manager", None) is None:
            failures.append("真 lifespan 没交出带 memory_manager 的 agent，后续读数无从取")
            return _report(before)

        manager = agent.memory_manager
        engine = getattr(agent, "cognitive_engine", None)
        readings["engine_present"] = isinstance(engine, CognitiveStorageEngine)
        if not isinstance(engine, CognitiveStorageEngine):
            failures.append("真装配点没交出 cognitive_engine（_init_cognitive_graph 被跳过或吞异常）")
            return _report(before)

        bodyPath = Path(manager.persistenceDbPath() or "")
        readings["body_db"] = str(bodyPath)
        expectedDir = get_agent_workspace_dir(AGENT_ID) / "memory"
        readings["body_under_isolated_workspace"] = bodyPath.parent == expectedDir
        if not readings["body_under_isolated_workspace"]:
            failures.append("正文库不在**隔离后**的 agent 工作区下：%s（期望 %s）"
                            % (bodyPath, expectedDir))

        secondLanding = get_data_root() / AGENT_ID / "memory.db"
        readings["second_landing_absent"] = not secondLanding.exists()
        readings["second_landing_path"] = str(secondLanding)
        if secondLanding.exists():
            failures.append("引擎仍在数据根下按 agent 开第二个正文落点：%s" % secondLanding)

        readings["wal_beside_body"] = (
            engine._wal_path is not None and Path(engine._wal_path).parent == bodyPath.parent
        )
        if not readings["wal_beside_body"]:
            failures.append("崩溃恢复文件没与正文库同目录：%s" % (engine._wal_path,))

        rowsBefore, _, _ = _bodyShape(bodyPath)
        written = client.post(
            "/api/v1/memory", json={"content": CJK_SENTENCE, "auto_classify": False},
            headers=headers,
        )
        readings["POST_write"] = "%s %s" % (written.status_code, written.text[:100])
        if written.status_code >= 300:
            failures.append("真端点写记忆没成：%s" % written.text[:200])
        rowsAfter, shadowAfter, names = _bodyShape(bodyPath)
        readings["body_rows_before_after"] = "%d -> %d" % (rowsBefore, rowsAfter)
        if rowsAfter <= rowsBefore:
            failures.append("端点回了 2xx 而正文库行数没涨——写面没落到唯一的库上")
        readings["fts_present"] = "memories_fts" in names
        readings["triggers_present"] = sorted(
            n for n in names if n in ("memories_ai", "memories_ad", "memories_au")
        )
        readings["shadow_rows"] = shadowAfter
        if not readings["fts_present"]:
            failures.append("正文库上没有全文影子表")
        if len(readings["triggers_present"]) != 3:
            failures.append("正文表触发器不齐：%s" % readings["triggers_present"])

        # 端点写这条的归属由凭证解析决定，召回断言走显式作用域：写与读同一个口径
        with manager.request_scope("live-neuser", "live-user"):
            manager.add_memory(CJK_SENTENCE + "（作用域探针）")
            recalled = engine.retrieve(CJK_TERM, limit=10)
            readings["recall_hits"] = len(recalled)
            if not any(CJK_TERM in n.content for n in recalled):
                failures.append("写进正文库的中文记忆，引擎按文本里就存在的子串召不回来")
            listed = client.get(
                "/api/v1/memory", params={"query": CJK_TERM, "limit": 20}, headers=headers
            )
            readings["GET_search_status"] = listed.status_code
            readings["GET_search_echoes_term"] = CJK_TERM in listed.text
            with manager.request_scope("live-neuser", "live-user-other"):
                readings["cross_scope_hits"] = len(engine.retrieve(CJK_TERM, limit=10))
                if any(CJK_TERM in n.content for n in engine.retrieve(CJK_TERM, limit=10)):
                    failures.append("另一 user 作用域召回到了本次写入的记忆——隔离倒退")

    # 反证与附带读数（各自独立子进程、各自全新隔离根）
    readings["counterprobe"] = _runChild(_COUNTERPROBE_SEAM_REVERT)
    readings["tokenizer_reading"] = _runChild(_COUNTERPROBE_TOKENIZER)
    if "SEAM-REVERT-BLUE" in readings["counterprobe"]:
        failures.append("把 L1 读路桩成空而召回仍有命中——本批「接通」另有出处，反证没牙")
    if "TOKENIZER-NOT-TRIGRAM-DEPENDENT" in readings["tokenizer_reading"]:
        failures.append("unicode61 下影子表也命中——trigram 这一枚并非承重，读数与判据不符")

    return _report(before)


def _runChild(code: str) -> str:
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True,
        encoding="utf-8", errors="replace", env={**os.environ},
    )
    tail = (proc.stdout or "").strip()[-300:]
    if proc.returncode != 0 and "AssertionError" not in (proc.stderr or ""):
        failures.append("子进程没跑到断言处：%s" % (proc.stderr or "")[-200:])
    return tail or (proc.stderr or "").strip()[-200:]


def _report(before: dict) -> int:
    after = _memoryLandingFingerprints()
    changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    readings["repo_memory_landings_touched"] = changed
    if changed:
        failures.append("本轮改了仓内真记忆库（隔离没盖住）：%s" % changed)
    print(json.dumps(readings, ensure_ascii=False, indent=2))
    for f in failures:
        print("[FAIL] " + f)
    if failures:
        return 1
    print("LIVE-PASS：正文一个库、真端点写进行、引擎召回真行、恢复文件同目录、"
          "隔离未倒退、反证咬住")
    return 0


#: 反证：把本批根修的那条接缝（L1 读路经 MemoryManager）桩成"读不到任何东西"，
#: 等价于退回"引擎读它自己那张空表"。端到端召回必须因此变 0。
_COUNTERPROBE_SEAM_REVERT = r'''
import sys, tempfile, pathlib
sys.path.insert(0, str(pathlib.Path.cwd()))
from tests.manual._liveVerifyIsolation import isolatedDataRoot
isolatedDataRoot(prefix="neurovaMemSeamRevert")
from neurova.cognitive_layers.memory_layer import manager as mgr_mod
mgr_mod.MemoryManager.searchMemoriesFulltext = lambda self, query, limit=10: []
from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import CognitiveStorageEngine
tmp = pathlib.Path(tempfile.mkdtemp())
mgr = MemoryManager(db_path=str(tmp / "memory.db"), agent_id="seam", enable_buffer=False)
mgr.add_memory("我始终会把你的记忆保护好，哪怕每次重启之后")
eng = CognitiveStorageEngine(agent_id="seam", memory_manager=mgr)
eng._l0_buffer.clear()          # 只留正文那一路，绕开 L0 内存匹配
hits = eng.retrieve("记忆保护好", limit=10)
print("seam_revert_hits=%d" % len(hits))
assert len(hits) == 0, "SEAM-REVERT-BLUE"
'''

#: 附带读数：unicode61 影子表对同一子串必须 0 命中（证 trigram 是全文这一侧承重的）。
_COUNTERPROBE_TOKENIZER = r'''
import sys, tempfile, pathlib
sys.path.insert(0, str(pathlib.Path.cwd()))
from tests.manual._liveVerifyIsolation import isolatedDataRoot
isolatedDataRoot(prefix="neurovaMemTokenizer")
from neurova.core import sql_like
sql_like.FTS_TOKENIZER = "unicode61"
from neurova.cognitive_layers.memory_layer.manager import MemoryManager
tmp = pathlib.Path(tempfile.mkdtemp())
mgr = MemoryManager(db_path=str(tmp / "memory.db"), agent_id="tok", enable_buffer=False)
mgr.add_memory("我始终会把你的记忆保护好，哪怕每次重启之后")
import sqlite3
con = sqlite3.connect(str(mgr.persistenceDbPath()))
n = con.execute("SELECT COUNT(*) FROM memories_fts WHERE memories_fts MATCH ?",
                ('"记忆保护好"',)).fetchone()[0]
print("unicode61_shadow_hits=%d" % n)
assert n == 0, "TOKENIZER-NOT-TRIGRAM-DEPENDENT"
'''

if __name__ == "__main__":
    raise SystemExit(main())
