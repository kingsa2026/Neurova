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

#: 只读 PRAGMA 的**单源**名单，按"取不取对象名实参"分两类。
#: 名单之外一律拒（fail-closed）——`journal_mode` / `writable_schema` 这类
#: 既可读又可设置的 PRAGMA 不在名单内，故 `PRAGMA journal_mode(WAL)` 与
#: `PRAGMA writable_schema=ON` 两种写法都被挡下。
READ_ONLY_PRAGMA_OBJECT_ARGUMENT = frozenset({
    "table_info",
    "table_xinfo",
    "index_info",
    "index_xinfo",
    "index_list",
    "foreign_key_list",
})
READ_ONLY_PRAGMA_NO_ARGUMENT = frozenset({
    "database_list",
    "table_list",
    "page_count",
    "page_size",
    "schema_version",
    "user_version",
    "freelist_count",
})

#: SQLite 授权回调里的**写型动作**（唯一判定依据：交给 SQLite 自己的解析器分类）。
#: 为什么不用关键字扫描：文本里出现 `delete` / `replace` / `=` 与"这条语句会写"
#: 是两回事 —— `SELECT ... WHERE id = 1` 与 `SELECT replace(...)` 都是纯读，
#: 却被关键字扫描误杀；而 `PRAGMA journal_mode(WAL)` 会写、却不带等号。
#: 授权动作是 SQLite 对**语句结构**的分类，不随写法漂移。
_SQL_WRITE_ACTIONS = frozenset({
    sqlite3.SQLITE_INSERT,
    sqlite3.SQLITE_UPDATE,
    sqlite3.SQLITE_DELETE,
    sqlite3.SQLITE_ALTER_TABLE,
    sqlite3.SQLITE_DROP_TABLE,
    sqlite3.SQLITE_DROP_INDEX,
    sqlite3.SQLITE_DROP_VIEW,
    sqlite3.SQLITE_DROP_TRIGGER,
    sqlite3.SQLITE_CREATE_TABLE,
    sqlite3.SQLITE_CREATE_INDEX,
    sqlite3.SQLITE_CREATE_VIEW,
    sqlite3.SQLITE_CREATE_TRIGGER,
    sqlite3.SQLITE_ATTACH,
    sqlite3.SQLITE_DETACH,
    sqlite3.SQLITE_TRANSACTION,
    sqlite3.SQLITE_REINDEX,
    sqlite3.SQLITE_ANALYZE,
})

#: 只读面明确拒绝的函数（文件 I/O 与扩展加载）。即使当前连接从未调用
#: `enable_load_extension`，也显式拒 —— 判据不许依赖"上游恰好没开门"。
_SQL_DENIED_FUNCTIONS = frozenset({
    "load_extension",
    "readfile",
    "writefile",
    "edit",
    "fts3_tokenizer",
})

_WRITE_ACTION_LABELS = {
    sqlite3.SQLITE_INSERT: "INSERT",
    sqlite3.SQLITE_UPDATE: "UPDATE",
    sqlite3.SQLITE_DELETE: "DELETE",
    sqlite3.SQLITE_ALTER_TABLE: "ALTER TABLE",
    sqlite3.SQLITE_DROP_TABLE: "DROP TABLE",
    sqlite3.SQLITE_DROP_INDEX: "DROP INDEX",
    sqlite3.SQLITE_DROP_VIEW: "DROP VIEW",
    sqlite3.SQLITE_DROP_TRIGGER: "DROP TRIGGER",
    sqlite3.SQLITE_CREATE_TABLE: "CREATE TABLE",
    sqlite3.SQLITE_CREATE_INDEX: "CREATE INDEX",
    sqlite3.SQLITE_CREATE_VIEW: "CREATE VIEW",
    sqlite3.SQLITE_CREATE_TRIGGER: "CREATE TRIGGER",
    sqlite3.SQLITE_ATTACH: "ATTACH",
    sqlite3.SQLITE_DETACH: "DETACH",
    sqlite3.SQLITE_TRANSACTION: "TRANSACTION",
    sqlite3.SQLITE_REINDEX: "REINDEX",
    sqlite3.SQLITE_ANALYZE: "ANALYZE",
}


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


def _readOnlyAuthorizer(violations: List[str]):
    """在连接上装**唯一**的只读授权判定（写型动作 / 非许可 PRAGMA / 危险函数）。

    为什么是授权回调而不是文本扫描：语句会做什么是**解析结果**，不是文本特征。
    关键字扫描把 `SELECT ... WHERE id = 1`（裸等号）读成写型 PRAGMA、把标量
    函数 `replace(...)` 读成 `REPLACE INTO`，同时又漏掉 `PRAGMA journal_mode(WAL)`
    这种不带等号的写 —— 同一份判据两头都错。授权动作由 SQLite 按**语句结构**
    给出，且 `WITH … DELETE` 这类"语句头是 WITH、最外层动作是写"的形态也分得开。

    `violations` 由调用方持有，命中时被点名（判据是诚实形态暴露，不静默拦截）。
    """

    def _authorizer(action, argument1, argument2, _dbname, _source):
        if action == sqlite3.SQLITE_PRAGMA:
            name = str(argument1 or "").lower()
            if _pragmaFormAllowed(name, argument2):
                return sqlite3.SQLITE_OK
            violations.append(f"写型或未许可的 PRAGMA {name}")
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_FUNCTION:
            name = str(argument2 or "").lower()
            if name in _SQL_DENIED_FUNCTIONS:
                violations.append(f"被禁函数 {name}")
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        if action in _SQL_WRITE_ACTIONS:
            violations.append(_WRITE_ACTION_LABELS.get(action, f"动作 {action}"))
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    return _authorizer


def _dryRunClassify(conn: sqlite3.Connection, sql: str) -> Optional[str]:
    """在**既有 schema 的连接**上干跑一次分类，返回违规点名（纯读返回 None）。

    按 `EXPLAIN` 干跑而非直接执行：分类要的是解析与授权结果，不是数据。
    必须用真连接：无 schema 的探针解析不了对象名，`WITH … DELETE` 这类
    最外层动作就无从判定（实测漏放）。

    准备阶段失败但**不是**授权拦下的（表/列不存在、语法错）一律放行，由真实
    执行给出诚实报错 —— 不把"读不出来的表"改写成"白名单拒绝"（两回事必须
    分得开）。这不构成放行面：准备失败的语句压根无法执行，写不可能落地；
    反过来，能执行的写型语句在准备阶段必然被授权拦下（判据咬合）。
    """
    violations: List[str] = []

    previous = conn.set_authorizer(None)
    try:
        conn.set_authorizer(_readOnlyAuthorizer(violations))
        try:
            conn.execute("EXPLAIN " + sql)
        except sqlite3.ProgrammingError as err:
            return f"只允许单条语句：{err}"
        except sqlite3.DatabaseError as err:
            if violations:
                return "、".join(dict.fromkeys(violations))
            if "not authorized" in str(err):
                return "未许可的语句动作"
            return None
    finally:
        conn.set_authorizer(previous)
    return None


def _pragmaFormAllowed(name: str, argument: Optional[str]) -> bool:
    """该 PRAGMA 写法是否属于许可的只读形态（名单单源，名单外一律拒）。"""
    if name in READ_ONLY_PRAGMA_OBJECT_ARGUMENT:
        return True
    if argument is None:
        return name in READ_ONLY_PRAGMA_NO_ARGUMENT
    return False


def assertReadOnlySql(sql: str, conn: sqlite3.Connection) -> str:
    """SQL 白名单（第三件）：不合法即抛 `ValueError`，不降级、不放行。

    `conn` 是要干跑其上的只读连接：结构判定需要 schema 才分得出
    `WITH … DELETE` 这类"语句头非写、最外层动作是写"的形态（内存探针实测
    漏放）。形参不给默认值——退化成无 schema 的探针等于开一条放行面。

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

    violation = _dryRunClassify(conn, code)
    if violation:
        raise ValueError(f"只读白名单拒绝非读取语句：{violation}")
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
