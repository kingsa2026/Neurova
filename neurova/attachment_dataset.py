"""附件域只读数据集访问（T-05）：把不可抽取的 SQLite 附件变成可查的能力。

## 为什么单独一个模块

事故（2026-09-24）：用户上传 `memory.db` 要"看看有什么信息可以提炼"，agent
三轮未成 —— 工具面里没有任何一条原语能读 SQLite。`file_parse` 只收 agent 工作区
内的 `file_path`，而附件落在 `data/storage/users/**`（`_resolve_agent_path` 锚定
工作区，结构上够不到）。本模块补的正是这块缺的能力。

## 安全边界（缺一即不合规）

能力开放与安全同批收口（D1/D6），四道防线一个不少：

1. **句柄域**：只认 `file_id`，形参里**没有** `file_path` —— 杜绝"诱导 agent
   去读 `data/users.db`/`rbac.db`"。属主校验走
   `files_api.get_attachment_info(file_id, caller_user_id)`（唯一用户域校验点），
   取字节走 `files_api.get_attachment_bytes(file_id)`（同一条字节咽喉）。
2. **只读连接**：`mode=ro` + `immutable=1` 的 URI 连接，且 `PRAGMA query_only=ON`。
3. **SQL 白名单**：仅 `SELECT` / `WITH … SELECT` / 只读 `PRAGMA`；写型与
   `ATTACH`/多语句一律拒。
4. **有界**：行数、单元格长度、返回字节三重上限，超限截断并**显式**标 `truncated`。

## 落点

SQLite 需要随机读，必须落一份只读副本；副本根**可注入**
（`NEUROVA_ATTACHMENT_QUERY_CACHE`），默认走数据根的 `dataLanding(...)`。
测试一律注入 `tmp_path`，严禁写真实 `data/`。
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

#: 副本根注入点（唯一开关；缺省走数据根，测试注入 tmp）。
QUERY_CACHE_ROOT_ENV = "NEUROVA_ATTACHMENT_QUERY_CACHE"

#: 有界上限：行 / 表 / 单元格字符 / 单次返回总字节。
MAX_ROWS_DEFAULT = 200
MAX_ROWS_LIMIT = 1000
MAX_TABLES = 50
MAX_SAMPLE_ROWS = 5
MAX_CELL_CHARS = 500
MAX_RESULT_BYTES = 200_000

_SQL_HEAD_ALLOWED = ("SELECT", "WITH", "PRAGMA")
_SQL_COMMENT_PATTERN = re.compile(r"--[^\n]*|/\*.*?\*/", re.S)
_SQL_LITERAL_PATTERN = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"", re.S)
_SQL_WRITE_KEYWORDS = re.compile(
    r"\b(attach|detach|insert|update|delete|drop|alter|create|replace|vacuum|reindex"
    r"|begin|commit|rollback|savepoint|release)\b",
    re.IGNORECASE,
)
_SQL_PRAGMA_WRITE = re.compile(r"\bpragma\b\s+[a-z_][a-z0-9_]*\s*[^;\s]=|=", re.IGNORECASE)


def resolveQueryCacheRoot() -> Path:
    """副本根：注入优先，缺省落数据根（**不得**写成 CWD 相对）。"""
    injected = (os.environ.get(QUERY_CACHE_ROOT_ENV) or "").strip()
    if injected:
        return Path(injected).expanduser()
    from neurova.core.data_root import dataLanding

    return dataLanding("attachment_query_cache", legacy=())


def materializeReadOnlyCopy(file_id: str, data: bytes, filename: str = "") -> Path:
    """把附件字节落成一份本地只读副本，返回副本路径。

    副本名取身份指纹（不直接把 `file_id` 拼进路径：外部可控串不进文件名），
    扩展名沿用附件原名以便诊断时一眼看出是哪个库。
    """
    root = resolveQueryCacheRoot()
    root.mkdir(parents=True, exist_ok=True)
    fingerprint = hashlib.sha256(file_id.encode("utf-8", "replace")).hexdigest()[:16]
    suffix = Path(filename or "").suffix.lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,8}", suffix or ""):
        suffix = ".db"
    target = root / f"attachment_{fingerprint}{suffix}"
    target.write_bytes(data)
    return target


def openReadOnlyConnection(path: "str | Path") -> sqlite3.Connection:
    """以**只读**方式打开本地 SQLite 副本（只读三件套的前两件）。

    `mode=ro` 挡住一切写入与文件创建；`immutable=1` 声明该文件在连接期间不被
    外部改动，SQLite 因此不做加锁与变更检测（副本本就是一次性的）。
    第三件（`PRAGMA query_only=ON`）在连接上立即生效，作为同层第二道。
    """
    uri = Path(path).resolve().as_uri() + "?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True, timeout=5.0)
    conn.execute("PRAGMA query_only=ON")
    return conn


def _stripSqlComments(text: str) -> str:
    """剥注释与字符串字面量内容：关键字/多语句判定只看**代码面**。"""
    stripped = _SQL_COMMENT_PATTERN.sub(" ", text)
    return _SQL_LITERAL_PATTERN.sub(" '' ", stripped)


def assertReadOnlySql(sql: str) -> str:
    """SQL 白名单（第三件）：不合法即抛 `ValueError`，不降级、不放行。

    判据是**诚实形态**暴露 —— 拒的时候点名原因，不做"静默改成只读"这类改写
    （改写会让模型以为自己的写语句生效了）。
    """
    if not isinstance(sql, str) or not sql.strip():
        raise ValueError("SQL 不能为空")

    code = _stripSqlComments(sql).strip()
    if code.endswith(";"):
        code = code[:-1].strip()
    if not code:
        raise ValueError("SQL 不能为空")
    if ";" in code:
        raise ValueError("只允许单条语句：检测到多语句（多语句是绕过只读检查的常见手法）")

    head = code.split(None, 1)[0].upper()
    if head not in _SQL_HEAD_ALLOWED:
        raise ValueError(
            f"只读白名单只允许 SELECT / WITH … SELECT / 只读 PRAGMA，收到 {head}"
        )

    hit = _SQL_WRITE_KEYWORDS.search(code)
    if hit:
        raise ValueError(f"只读白名单拒绝写型语句：命中 {hit.group(1).upper()}")
    if _SQL_PRAGMA_WRITE.search(code):
        raise ValueError("只读白名单拒绝写型 PRAGMA（只允许不带赋值的读取形态）")
    return sql


def _renderCell(value: Any) -> Any:
    """单元格渲染：二进制不外泄正文，超长串截断（有界的最后一层）。"""
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<{len(bytes(value))} 字节二进制>"
    if isinstance(value, str) and len(value) > MAX_CELL_CHARS:
        return value[:MAX_CELL_CHARS] + f"…（截断，共 {len(value)} 字符）"
    return value


def _tableNames(conn: sqlite3.Connection) -> List[str]:
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )
    return [row[0] for row in cursor.fetchall()]


def readDatasetSummary(conn: sqlite3.Connection, row_limit: int) -> Dict[str, Any]:
    """缺省视图：表清单 + 每表列定义 + 行数 + 样例行。

    "只给表名"对模型没有用（它要判断"有什么信息可提炼"必须看到真实值），
    故每表附有界样例行；总量仍有界。
    """
    names = _tableNames(conn)
    truncated = len(names) > MAX_TABLES
    tables: List[Dict[str, Any]] = []
    for name in names[:MAX_TABLES]:
        quoted = '"' + name.replace('"', '""') + '"'
        columns = [
            {"name": row[1], "type": row[2] or ""}
            for row in conn.execute(f"PRAGMA table_info({quoted})").fetchall()
        ]
        row_count = int(conn.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()[0])
        sample_limit = max(1, min(MAX_SAMPLE_ROWS, row_limit))
        cursor = conn.execute(f"SELECT * FROM {quoted} LIMIT {sample_limit}")
        column_names = [d[0] for d in (cursor.description or [])]
        sample_rows = [
            dict(zip(column_names, (_renderCell(value) for value in row)))
            for row in cursor.fetchall()
        ]
        tables.append(
            {
                "name": name,
                "columns": columns,
                "row_count": row_count,
                "sample_rows": sample_rows,
            }
        )
    return {"tables": tables, "row_count_total": len(names), "truncated": truncated}


def runReadOnlyQuery(conn: sqlite3.Connection, sql: str, row_limit: int) -> Dict[str, Any]:
    """执行一条已过白名单的只读查询（有界返回）。"""
    cursor = conn.execute(sql)
    if cursor.description is None:
        # 只读白名单下不该出现；出现了就如实说"没有结果集"，不伪造空表。
        return {"columns": [], "rows": [], "truncated": False,
                "notice": "该语句不返回结果集（只读白名单内通常为 PRAGMA 设置类）"}

    columns = [{"name": desc[0]} for desc in cursor.description]
    fetched = cursor.fetchmany(row_limit + 1)
    truncated = len(fetched) > row_limit
    rows: List[List[Any]] = []
    used_bytes = 0
    for row in fetched[:row_limit]:
        rendered = [_renderCell(value) for value in row]
        used_bytes += sum(len(str(value)) for value in rendered)
        if used_bytes > MAX_RESULT_BYTES:
            truncated = True
            break
        rows.append(rendered)
    return {"columns": columns, "rows": rows, "truncated": truncated}


def normalizeRowLimit(value: Optional[Any]) -> int:
    """`row_limit` 归一：非法值取默认，超上界收敛到上界（有界，不放大）。"""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return MAX_ROWS_DEFAULT
    if parsed <= 0:
        return MAX_ROWS_DEFAULT
    return min(parsed, MAX_ROWS_LIMIT)
