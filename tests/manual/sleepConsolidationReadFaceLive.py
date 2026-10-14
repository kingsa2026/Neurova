"""活体：正文单源留下的第二读面——`get_all_memories()` 取的是进程内缓存。

跑法（仓库根）：
    PYTHONPATH="$(git rev-parse --show-toplevel)" .venv/Scripts/python.exe \\
        tests/manual/sleepConsolidationReadFaceLive.py

问的是四件事，逐件给读数：
  一 写侧通不通（经引擎 flush 的行在正文库里有没有对应行）；
  二 检索面那道门（§6-208）在这份真装配上咬不咬得住；
  三 固化/召回那条腿的取数面（`manager.get_all_memories()`）看不看得到引擎写的行——
      配一格反空转：同一份 manager 自己 `add_memory` 的行必须看得见，
      否则「看不到引擎那行」就只是探针走错了支路；
  四 重启后进不进得来，以及进来以后固化认不认得出它是回声（类别在 metadata 里，
      而 `MemoryRecord.from_dict()` 取的是 `categories` 字段）。

**本档不判绿不判红的是第三、四件的现值**——那是缺陷实状，按形态集第 117 条不钉成契约：
收口之后重跑，`same_process_bodyRows_visible_in_fetch` 应从 0 变 1、
`record_categories_reveal_echo` 应从 null 变成含 `reasoning_trace`。
只有一、二两件断言的是应当一直成立的防线。
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests" / "manual"))

from _liveVerifyIsolation import isolatedAgentWorkspaces, isolatedDataRoot  # noqa: E402

MARK_TRACE = "LIVE-ECHO-TRACE-MARKER"
MARK_ORDINARY = "LIVE-ORDINARY-OK-MARKER"

failures = []
readings = {}


def _collect() -> None:
    isolatedDataRoot(prefix="neurovaLive")
    isolatedAgentWorkspaces(prefix="neurovaLive")

    from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import (
        MemoryType,
        UnifiedMemoryNode,
    )
    from neurova.cognitive_layers.memory_layer.manager import MemoryManager
    from neurova.cognitive_layers.memory_layer.sleep import MemoryRecord
    from tests.cognitive_body_store import bodyManager, cognitiveEngine

    tmp = Path(tempfile.mkdtemp(prefix="sleepReadFace-"))
    manager = bodyManager(tmp, agentId="live-sleep-face")
    engine = cognitiveEngine(tmp, agentId="live-sleep-face", manager=manager)

    engine.store(UnifiedMemoryNode(
        content="推理链: 问题 → 答案 %s" % MARK_TRACE,
        memory_type=MemoryType.EPISODIC,
        category="reasoning_trace",
        temperature=100.0,
        trace_id="live-trace-1",
        metadata={"steps_count": 3},
    ))
    engine.store(UnifiedMemoryNode(
        content="普通正文 %s" % MARK_ORDINARY,
        memory_type=MemoryType.SEMANTIC,
        category="general",
        temperature=60.0,
    ))
    readings["flushed_into_body"] = engine._flushL0ToBody()

    # 一、写侧：正文库里两行俱在（直接读盘，不碰 manager 私有字段）
    import sqlite3

    persistDb = tmp / "neurova_memories_persist.db"
    con = sqlite3.connect("file:%s?mode=ro" % persistDb.as_posix(), uri=True)
    try:
        bodyRows = con.execute("select count(*) from memories").fetchone()[0]
    finally:
        con.close()
    readings["body_rows_after_flush"] = bodyRows
    if bodyRows != 2:
        failures.append("正文库里应有 2 行（引擎 flush 的两条），实得 %s ⇒ 写侧没通，"
                        "后面三件的读数全部失去意义" % bodyRows)

    # 二、检索面：§6-208 那道门在这份真装配上必须咬住回声、放过普通行
    traceHits = [n for n in engine.retrieve(MARK_TRACE, limit=10) if MARK_TRACE in n.content]
    ordinaryHits = [n for n in engine.retrieve(MARK_ORDINARY, limit=10)
                    if MARK_ORDINARY in n.content]
    readings["trace_visible_via_engine_retrieve"] = len(traceHits)
    readings["ordinary_visible_via_engine_retrieve"] = len(ordinaryHits)
    if traceHits:
        failures.append("回声行经真检索口可见 ⇒ §6-208 的门没装配上")
    if not ordinaryHits:
        failures.append("同一查询下普通行也取不到 ⇒ 过滤器成了总闸，上一格「看不见」是空转")

    # 三、固化/召回那条腿：取数面是进程内缓存
    fetch = manager.get_all_memories()
    readings["fetch_total"] = len(fetch)
    readings["same_process_bodyRows_visible_in_fetch"] = sum(
        1 for m in fetch if MARK_TRACE in (m.get("content") or ""))
    manager.add_memory(content="manager 自己写的 %s" % MARK_ORDINARY)
    readings["managerOwnWrite_visible_in_fetch"] = sum(
        1 for m in manager.get_all_memories()
        if (m.get("content") or "").startswith("manager 自己写的"))
    if readings["managerOwnWrite_visible_in_fetch"] != 1:
        failures.append("manager 自己写的行在取数面也看不见 ⇒ 取数面本身失灵，"
                        "「引擎那行看不见」不能归给缓存滞后")

    # 四、重启后：进得来，但认不出是回声
    reopened = MemoryManager(
        db_path=str(tmp / "memory.db"),
        agent_id="live-sleep-face",
        neuser_id="default",
        user_id="default",
        enable_buffer=False,
    )
    afterRestart = reopened.get_all_memories()
    traceRows = [m for m in afterRestart if MARK_TRACE in (m.get("content") or "")]
    readings["after_restart_bodyRows_visible_in_fetch"] = len(traceRows)
    readings["restart_metadata_face"] = traceRows[0].get("metadata") if traceRows else None
    if traceRows:
        record = MemoryRecord.from_dict(traceRows[0])
        readings["record_categories_reveal_echo"] = record.categories

    # 影响面现算：这条取数面在生产里有多少个调用档（按读取形态扫，不手抄）
    consumers = []
    for py in (REPO / "neurova").rglob("*.py"):
        if "get_all_memories()" in py.read_text(encoding="utf-8", errors="replace"):
            consumers.append(py.relative_to(REPO).as_posix())
    readings["fetch_face_production_consumers"] = sorted(consumers)
    readings["fetch_face_production_consumer_count"] = len(consumers)


def main() -> int:
    _collect()
    print(json.dumps(readings, ensure_ascii=False, indent=2, default=str))
    if failures:
        print("FAIL")
        for line in failures:
            print("  - %s" % line)
        return 1
    print("PASS（一、二两道防线在位；三、四的现值见上方读数，未钉成契约）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
