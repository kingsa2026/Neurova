#!/usr/bin/env python3
"""一次性回填既有记忆的 `embedding` 列（§6-215 那张票的乙案）。

跑法（仓库根，先看影响面再动手）：
    PYTHONPATH="$(git rev-parse --show-toplevel)" .venv/Scripts/python.exe \\
        -m scripts.backfill_memory_embeddings --dry-run
    PYTHONPATH="$(git rev-parse --show-toplevel)" .venv/Scripts/python.exe \\
        -m scripts.backfill_memory_embeddings --agent default --agent kai

为什么要它：§6-215 把 `embedding` 接出了正文出口（`Memory.to_dict()`），睡眠"合并"这条腿
第一次具备走通的条件——但现网正文库该列全空，`cluster_by_similarity` 因两侧无嵌入而恒单例。
路通了，这一步是给它配上车。

三条硬规矩，各有判据钉着（`tests/unit/memory/test_backfillMemoryEmbeddingsTool.py`）：
- **只填空的那些**：已有向量的行一律不动 ⇒ 幂等，可反复执行才是运维可用的工具。
- **只写引擎真算出来的向量**：引擎缺席或初始化失败 ⇒ 一行不写、退出码非零、点名原因。
  拿随机数或占位向量冒充"回填完成"是教义第 2 条禁的表面抹除——那会让固化基于假相似度
  合并真记忆，比不填更坏。
- **写侧走唯一口** `MemoryManager.persist_memory_batch`：不许自己开 sqlite3 写正文表
  （裸 SQL 会绕开作用域 upsert、内容门索引与 FTS 影子行，等于给同一件事造第二个落点）。

副作用要说清：本工具是**另一个进程**写正文库。运行中的服务读的是自己的进程内快照，
新填入的向量要等 `reload_memories()`（`visibility.py:43` 那个端点）或重启才对它可见。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

if __package__ in (None, ""):  # 直接 `python scripts/...py` 也要能跑
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from neurova.core.agent_workspaces import get_agent_workspaces_root
from neurova.core.logger import get_logger
from neurova.embedding import get_embedding_engine

logger = get_logger(__name__)

#: 取数口 `iterBodyMemories(limit=…)` 不给就是 500；一次性回填要的是全表。
#: 这里显式给一个远超现实体量的上限（现网正文 16 行），并让读数把"扫到 ceiling"报成 truncated，
#: 免得哪天库真长到这个数时被静默截断。
_FULL_SCAN_CEILING = 1_000_000


def defaultEngine():
    """嵌入引擎的唯一取法（测试替身从这里换，生产不加第二条获取路）。"""
    return get_embedding_engine()


def agentsWithMemoryDir() -> List[str]:
    """枚举有 `memory/` 子目录的 agent 工作区。

    只取目录名，路径推导一律交给 `MemoryManager` 的默认落点（`_default_db_path_for`）——
    同一件事不许有两套推导。
    """
    root = get_agent_workspaces_root()
    if not root.exists():
        return []
    return sorted(d.parent.name for d in root.glob("*/memory") if d.is_dir())


def backfillAgent(agentId: str, engine=None, dbPath: Optional[str] = None,
                  dryRun: bool = False, limit: Optional[int] = None) -> Dict[str, Any]:
    """把一个 agent 的正文行补上嵌入；返回逐项读数，不抛异常。"""
    outcome: Dict[str, Any] = {
        "agent": agentId, "scanned": 0, "filled": 0, "wouldFill": 0,
        "skippedExisting": 0, "skippedBlank": 0, "failed": 0, "truncated": False,
    }

    if engine is None:
        engine = defaultEngine()
    if engine is None:
        outcome["error"] = "embedding_engine_unavailable"
        logger.error("嵌入引擎不可用（模型缺失或初始化失败）：agent=%s 一行都不写", agentId)
        return outcome
    if not engine.initialize_sync():
        outcome["error"] = "embedding_engine_initialize_failed"
        logger.error("嵌入引擎初始化失败：agent=%s 一行都不写", agentId)
        return outcome

    manager = (MemoryManager(db_path=dbPath, agent_id=agentId, enable_buffer=False)
               if dbPath else MemoryManager(agent_id=agentId, enable_buffer=False))

    ceiling = limit if limit is not None else _FULL_SCAN_CEILING
    rows = manager.iterBodyMemories(limit=ceiling)
    outcome["scanned"] = len(rows)
    outcome["truncated"] = len(rows) >= ceiling

    pending = []
    for mem in rows:
        if mem.embedding:
            outcome["skippedExisting"] += 1
            continue
        if not (mem.content or "").strip():
            outcome["skippedBlank"] += 1
            continue
        if dryRun:
            outcome["wouldFill"] += 1
            continue
        try:
            vector = list(engine.encode(mem.content))
        except Exception as exc:  # noqa: BLE001 - 单行算不出不该断整批
            outcome["failed"] += 1
            logger.warning("嵌入计算失败（id=%s）: %s", mem.id, exc)
            continue
        if not vector:
            outcome["failed"] += 1
            logger.warning("嵌入计算返回空向量（id=%s）——不写，避免留下'看着有其实是空'的行", mem.id)
            continue
        mem.embedding = vector
        pending.append(mem)

    if pending:
        if not manager.persist_memory_batch(pending):
            # 写入口回了 False＝没落地。这里必须报失败，不许把"算出来了"当成"写进去了"。
            outcome["failed"] += len(pending)
            outcome["filled"] = 0
            logger.error("正文写入口拒收 %d 条嵌入（agent=%s）", len(pending), agentId)
        else:
            outcome["filled"] = len(pending)

    return outcome


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--agent", action="append", default=None,
                        help="只处理这些 agent（可重复）；不给就处理所有有 memory/ 工作区的 agent")
    parser.add_argument("--db-path", default=None,
                        help="显式正文库路径（仅用于单 agent 作业与测试；默认按 agent 工作区推导）")
    parser.add_argument("--dry-run", action="store_true", help="只报数不写盘")
    parser.add_argument("--limit", type=int, default=None, help="每个 agent 最多扫多少行")
    args = parser.parse_args(argv)

    agentIds = args.agent or agentsWithMemoryDir()
    if not agentIds:
        print("没有可处理的 agent 工作区，未写入任何数据。")
        return 0

    failures = []
    for agentId in agentIds:
        outcome = backfillAgent(agentId, dbPath=args.db_path if len(agentIds) == 1 else None,
                                dryRun=args.dry_run, limit=args.limit)
        if outcome.get("error"):
            failures.append(outcome)
        print("[{agent}] 扫 {scanned} 行｜填 {filled}｜待填 {wouldFill}｜"
              "已有 {skippedExisting}｜空内容 {skippedBlank}｜失败 {failed}{trunc}{dry}".format(
                  agent=outcome["agent"], scanned=outcome["scanned"], filled=outcome["filled"],
                  wouldFill=outcome["wouldFill"], skippedExisting=outcome["skippedExisting"],
                  skippedBlank=outcome["skippedBlank"], failed=outcome["failed"],
                  trunc="｜**触到上限，被截断**" if outcome["truncated"] else "",
                  dry="（dry-run 未写盘）" if args.dry_run else ""))
        if outcome.get("error"):
            print("   ↳ 失败原因: %s" % outcome["error"])

    if failures:
        print("\n%d/%d 个 agent 未能回填——本工具不写占位向量，退出码非零。"
              % (len(failures), len(agentIds)))
        return 1
    if not args.dry_run:
        print("\n写入的是正文库；运行中的服务读自己的进程内快照，"
              "要它对嵌入可见需走 reload_memories() 或重启。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
