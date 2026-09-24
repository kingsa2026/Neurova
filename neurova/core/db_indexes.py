"""数据库索引可观测（P0-3）

历史问题（Issue #57 §2）：本模块原先是"12 条静态 DDL + `add_indexes()`"，
而 `add_indexes()` 全仓零调用方，索引实际靠各模块内联 DDL 分散维护
（全仓 155 处 `CREATE INDEX`）。于是：

- 12 条清单与真实的 155 条索引不构成单一事实源，谁也不知道哪份为准；
- 没有任何 `EXPLAIN QUERY PLAN` / `index_list` 聚合 → "索引命中"物理上不可测，
  旧审计 §7 要求的"查询计划基线"至今缺失。

本模块改为**采集器**（不再持有第二套索引清单）：

- `collect_index_snapshot(db_path)`：`PRAGMA index_list` + `index_info` 聚合，
  得到"每表索引数 / 每索引列"的真实快照（全库实测 0.39ms，含 index_info 1.43ms）；
- `explain_hot_queries(db_path)`：对白名单热点查询跑 `EXPLAIN QUERY PLAN`，
  判定是否走索引（避免全表扫描无人知晓），并记录一次探针耗时；
- `bootstrap_index_observability()`：启动期把上述结果写入 core/metrics.py 的
  gauge（失败 fail-open，不阻断启动——可观测不得成为启动依赖）。

热点查询白名单是显式维护的：新增热点查询时在此登记，判据写进注释，
避免"随手把所有 SQL 都跑一遍计划"（成本与噪声都不可控）。
"""

from __future__ import annotations

import sqlite3
import time
from neurova.core.logger import get_logger
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = get_logger(__name__)


# ── 热点查询白名单 ────────────────────────────────────────────────
# 每条 = (query_id, sql, params)：sql 必须与生产调用点同形（同 WHERE/ORDER BY），
# 否则 EXPLAIN 出来的计划不能代表生产。params 用同类型样本值（计划只与形状有关，
# 但与"是否会用到索引"绑定于列与常量比较形式，故必须给真参数）。
# 适用性声明：每条白名单查询**依赖哪张表、哪些列**。
#
# 为什么必须有：探针库清单（`resolve_probe_paths`）里既有主记忆库也有审计库，
# 而白名单同时含 memories 系与 audit_logs 系查询。此前不看 schema 就发查询，
# 于是每一对"库 × 不属于它的查询"必然抛 `no such table` / `no such column`，
# 再被下面的 except 压成一条 DEBUG——启动日志里成片的
# `EQP 失败 ...: no such table: audit_logs` 就是这么来的。
# 更坏的是汇总口径把它算进"没走索引"，假告警常年冲刷真告警。
#
# 表名/列名在此声明一次，`explain_hot_queries` 按真实 schema 过闸；不从 SQL
# 文本里反解（正则解 SQL 是第二套判据，迟早与 SQL 漂移）。
HotQuery = Tuple[str, str, tuple, str, Tuple[str, ...]]

HOT_QUERIES: List[HotQuery] = [
    (
        # memory_layer/manager.py:_load_from_db —— 启动与浏览页主查询
        "memories_by_agent_desc",
        "SELECT * FROM memories WHERE agent_id = ? ORDER BY created_at DESC",
        ("default",),
        "memories",
        ("agent_id", "created_at"),
    ),
    (
        # memory_layer/manager.py:get_top_memories_by_temperature —— 温度通道每查询
        "memories_by_temperature",
        "SELECT * FROM memories ORDER BY temperature DESC LIMIT ?",
        (10,),
        "memories",
        ("temperature",),
    ),
    (
        # 三层隔离查询（agent_id, neuser_id, user_id）
        "memories_three_tier",
        "SELECT * FROM memories WHERE agent_id = ? AND neuser_id = ? AND user_id = ?",
        ("default", "default", "default"),
        "memories",
        ("agent_id", "neuser_id", "user_id"),
    ),
    (
        # security/audit_logger.py:query —— 审计页倒序分页
        "audit_logs_recent",
        "SELECT * FROM audit_logs ORDER BY timestamp DESC LIMIT ? OFFSET ?",
        (50, 0),
        "audit_logs",
        ("timestamp",),
    ),
    (
        # security/audit_logger.py —— 按事件类型筛选
        "audit_logs_by_event_type",
        "SELECT * FROM audit_logs WHERE event_type = ? ORDER BY timestamp DESC LIMIT ?",
        ("system_event", 50),
        "audit_logs",
        ("event_type", "timestamp"),
    ),
]


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    """检查表是否存在（采集器跳过不存在的表）。"""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,)
    )
    return cursor.fetchone() is not None


def table_columns(conn: sqlite3.Connection, table_name: str) -> List[str]:
    """表的列名清单（表不存在时返回空表，不抛错）。"""
    if not table_exists(conn, table_name):
        return []
    try:
        return [str(row[1]) for row in conn.execute(f"PRAGMA table_info('{table_name}')")]
    except sqlite3.DatabaseError:
        return []


def probeApplicability(
    conn: sqlite3.Connection, entry: "HotQuery"
) -> Optional[str]:
    """该库能否承载这条热点查询。能则 None，不能则返回点名缺口的理由。

    这是判断"该不该发这条 EQP"的**唯一**入口（发查询前先过这道闸）。
    理由文本直接进读数与日志：不适用必须说得出缺哪张表/哪些列，而不是把
    `no such table` 原文当结论（那看不出是"库没这张表"还是"SQL 写错了"）。
    """
    table = hotQueryTable(entry)
    if not table:
        return None  # 未声明依赖（理论上不该有）：不做无依据的拦截
    if not table_exists(conn, table):
        return f"该库没有 {table} 表"
    declared = hotQueryColumns(entry)
    if not declared:
        return None
    present = set(table_columns(conn, table))
    missing = [column for column in declared if column not in present]
    if missing:
        return f"{table} 表缺少列 {', '.join(missing)}"
    return None


def hotQueryTable(entry: "HotQuery") -> str:
    """热点查询依赖的表名（声明的单一读取口）。"""
    return str(entry[3] if len(entry) > 3 else "")


def hotQueryColumns(entry: "HotQuery") -> Tuple[str, ...]:
    """热点查询依赖的列名（声明的单一读取口）。"""
    return tuple(entry[4]) if len(entry) > 4 else ()


def list_tables(conn: sqlite3.Connection) -> List[str]:
    """全部用户表（排除 SQLite 内部表与 FTS 影子表）。"""
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [r[0] for r in rows]


def collect_index_snapshot(db_path: str) -> Dict[str, Any]:
    """采集索引真实快照（`index_list` + `index_info`）。

    返回 {"available": bool, "db": path, "tables": {table: [ {name, unique, columns} ]},
          "index_count": int, "duration_ms": float}。

    不可用（库不存在/损坏）时 available=False —— 调用方按"无数据"处理，
    不抛错（观测面不得把启动拖下水）。
    """
    result: Dict[str, Any] = {
        "available": False,
        "db": str(db_path),
        "tables": {},
        "index_count": 0,
        "duration_ms": 0.0,
    }
    if not Path(db_path).exists():
        return result

    started = time.perf_counter()
    conn: Optional[sqlite3.Connection] = None
    try:
        # 只读意图：采集不改库；mode=ro 对已存在的库可用
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=3.0)
        index_count = 0
        for table in list_tables(conn):
            entries: List[Dict[str, Any]] = []
            try:
                index_rows = conn.execute(f"PRAGMA index_list('{table}')").fetchall()
            except sqlite3.DatabaseError:
                continue
            for row in index_rows:
                # index_list: seq, name, unique, origin, partial
                name = row[1]
                unique = bool(row[2])
                columns: List[str] = []
                try:
                    columns = [
                        info[2]
                        for info in conn.execute(f"PRAGMA index_info('{name}')").fetchall()
                    ]
                except sqlite3.DatabaseError:
                    pass
                entries.append({"name": name, "unique": unique, "columns": columns})
                index_count += 1
            if entries:
                result["tables"][table] = entries
        result["index_count"] = index_count
        result["available"] = True
    except Exception as e:  # noqa: BLE001 - 库损坏/权限不足按"无数据"
        logger.debug("索引快照采集失败 %s: %s", db_path, e)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
        result["duration_ms"] = (time.perf_counter() - started) * 1000.0
    return result


def _plan_uses_index(detail: str) -> bool:
    """EQP 单行 detail 是否表示"用了索引"。

    `SCAN t USING INDEX` / `SCAN t USING COVERING INDEX` 属覆盖索引扫描，
    仍是走索引；纯 `SCAN t` 才是全表扫描。
    """
    upper = (detail or "").upper()
    if "USING INDEX" in upper:
        return True
    if "SEARCH " in upper:
        return True
    return False


def explain_hot_queries(db_path: str) -> List[Dict[str, Any]]:
    """对白名单热点查询跑 EQP，返回每条的走索引判定与探针耗时。

    发查询**之前**先按库的真实 schema 过闸（`probeApplicability`）：
    - 表/列不适用 → `available=False` + `reason`（点名缺口），**一条 EQP 都不发**；
    - 适用但 SQL 有缺陷 → 照发，失败留 `EQP 失败` 痕迹（真问题不许被静音）。

    「不适用」与「没走索引」是两类读数，汇总口径必须分开：混在一起会让
    一个不含 audit_logs 的库被当成"审计查询全表扫描"，告警常年误报。
    """
    if not Path(db_path).exists():
        return []

    results: List[Dict[str, Any]] = []
    conn: Optional[sqlite3.Connection] = None
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=3.0)
        for entry_spec in HOT_QUERIES:
            query_id, sql, params = entry_spec[0], entry_spec[1], entry_spec[2]
            started = time.perf_counter()
            entry: Dict[str, Any] = {
                "query_id": query_id,
                "db": str(db_path),
                "indexed": False,
                "available": False,
                "plan": [],
                "reason": "",
                "duration_ms": 0.0,
            }
            inapplicable = probeApplicability(conn, entry_spec)
            if inapplicable:
                entry["reason"] = inapplicable
                entry["duration_ms"] = (time.perf_counter() - started) * 1000.0
                results.append(entry)
                continue
            try:
                rows = conn.execute("EXPLAIN QUERY PLAN " + sql, params).fetchall()
                details = [str(r[3]) if len(r) > 3 else str(r[-1]) for r in rows]
                entry["plan"] = details
                entry["available"] = True
                entry["indexed"] = any(_plan_uses_index(d) for d in details)
            except sqlite3.Error as e:
                # 走到这里说明表与列都在 ⇒ 是 SQL 自身的问题（真失败，必须留痕）
                entry["reason"] = f"EQP 失败: {e}"
                logger.warning("EQP 失败 %s @ %s: %s", query_id, db_path, e)
            entry["duration_ms"] = (time.perf_counter() - started) * 1000.0
            results.append(entry)
    except Exception as e:  # noqa: BLE001
        logger.debug("热点查询计划采集失败 %s: %s", db_path, e)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
    return results


def resolve_probe_paths() -> List[str]:
    """启动期探针库清单（只含已存在的固定路径，不含动态 glob 路径）。

    动态路径（agent_workspaces/*/memory/*.db）不进探针：库数量随用户增长，
    逐个采集既无界又不代表"全库"基线。
    """
    candidates: List[str] = []
    try:
        from neurova.core.database import defaultDbPath

        # 探针清单只收**已存在的**库：默认库没被建出来时不该被列进基线。
        candidates.append(defaultDbPath())
    except Exception:  # noqa: BLE001
        pass
    import os

    env_path = os.environ.get("NEUROVA_DB_PATH")
    if env_path:
        candidates.append(env_path)
    try:
        candidates.append(str(Path.home() / ".neurova" / "audit.db"))
    except Exception:  # noqa: BLE001
        pass

    seen: List[str] = []
    for path in candidates:
        if path and path not in seen and Path(path).exists():
            seen.append(path)
    return seen


def bootstrap_index_observability(paths: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """启动期采集索引可观测数据并写入 metrics gauge（fail-open）。

    返回汇总统计（供日志/测试断言）：{"dbs": n, "indexes": n, "hot_queries": n,
    "unindexed": [query_id...], "not_applicable": [query_id...], "duration_ms": float}。

    `unindexed` 只在**适用**的探针上累积；不适用的另计 `not_applicable`。
    两者混在一起就是假告警的来源（不含 audit_logs 的库被判成"审计查询全表扫描"）。
    """
    started = time.perf_counter()
    summary: Dict[str, Any] = {
        "dbs": 0,
        "indexes": 0,
        "hot_queries": 0,
        "unindexed": [],
        "not_applicable": [],
        "duration_ms": 0.0,
    }
    probe_paths = list(paths) if paths is not None else resolve_probe_paths()
    try:
        from neurova.core.metrics import (
            record_index_snapshot,
            record_hot_query_plan,
        )
    except Exception as e:  # noqa: BLE001 - 指标不可用时静默降级
        logger.debug("索引可观测埋点不可用: %s", e)
        summary["duration_ms"] = (time.perf_counter() - started) * 1000.0
        return summary

    for db_path in probe_paths:
        try:
            snapshot = collect_index_snapshot(db_path)
            if snapshot.get("available"):
                record_index_snapshot(
                    db_path,
                    int(snapshot.get("index_count", 0)),
                    float(snapshot.get("duration_ms", 0.0)),
                )
                summary["dbs"] += 1
                summary["indexes"] += int(snapshot.get("index_count", 0))
        except Exception as e:  # noqa: BLE001 - 单库失败不影响其余
            logger.debug("索引快照写入失败 %s: %s", db_path, e)

        try:
            for entry in explain_hot_queries(db_path):
                record_hot_query_plan(
                    db_path,
                    str(entry.get("query_id", "?")),
                    bool(entry.get("indexed")),
                    float(entry.get("duration_ms", 0.0)),
                    available=bool(entry.get("available")),
                )
                if entry.get("available"):
                    summary["hot_queries"] += 1
                    if not entry.get("indexed"):
                        summary["unindexed"].append(str(entry.get("query_id", "?")))
                elif entry.get("reason"):
                    # 不适用（该库没这张表/这些列）：单独记，不混进"没走索引"
                    summary["not_applicable"].append(str(entry.get("query_id", "?")))
        except Exception as e:  # noqa: BLE001
            logger.debug("热点查询计划写入失败 %s: %s", db_path, e)

    summary["duration_ms"] = (time.perf_counter() - started) * 1000.0
    if summary["dbs"]:
        logger.info(
            "索引可观测采集完成: %d 库 / %d 索引 / %d 热点查询（%.1fms）",
            summary["dbs"],
            summary["indexes"],
            summary["hot_queries"],
            summary["duration_ms"],
        )
    if summary["unindexed"]:
        logger.warning(
            "热点查询未走索引（全表扫描）: %s", ", ".join(sorted(set(summary["unindexed"])))
        )
    return summary


def list_indexes(db_path: str = "") -> list:
    """列出数据库中的所有索引（运维诊断用；采集器对外只读接口）。

    缺省（空串）时取数据根下的默认库——原默认值 `"neurova_memory.db"` 是裸文件名，
    诊断脚本换个目录跑就找不到库、静默回一份空清单。
    """
    if not db_path:
        from neurova.core.database import defaultDbPath

        db_path = defaultDbPath()
    if not Path(db_path).exists():
        return []

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=3.0)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT name, tbl_name, sql
            FROM sqlite_master
            WHERE type='index'
            ORDER BY tbl_name, name
        """)
        return cursor.fetchall()
    finally:
        conn.close()


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) > 1:
        target = sys.argv[1]
    else:
        from neurova.core.database import defaultDbPath

        target = defaultDbPath()
    print(json.dumps(collect_index_snapshot(target), ensure_ascii=False, indent=2))
    print(json.dumps(explain_hot_queries(target), ensure_ascii=False, indent=2))
