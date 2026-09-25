"""用户输入进 SQL 文本匹配面的**唯一**安全化判据。

为什么要有这个模块：`LIKE` 的 `%` 与 `_` 是通配符，把用户输入直接拼进模式串
等于把"子串查询"变成"通配模式"。实测（基线脚本 §8）库内 3 行时查询 `%`
命中 **3 行**、`_` 命中 **3 行**（真值均为 0）。FTS5 的 `MATCH` 有同类问题：
裸查询串会被当作 FTS 语法（`*` `^` `-` `AND` 等），必须包成短语。

单源纪律：转义规则与短语规则只在此处实现。调用方各自 `f"%{query}%"` 就是第二份
判据——`_LIKE_ESCAPE` 改一处而漏另一处，等于没改。
"""

from __future__ import annotations

from typing import Optional

#: `LIKE ... ESCAPE` 的转义字符（SQL 文本里写作 `ESCAPE '\\'`）
LIKE_ESCAPE = "\\"


def likePredicate(columns, negate: bool = False) -> str:
    """产出一条（或由 `OR` 连接的多列）**带 `ESCAPE`** 的 LIKE 谓词。

    `columns` 只传常量列名或列名序列，**不传用户输入**（列名进 SQL 文本，
    值一律走占位符）。

    为什么连子句也在这里给：`ESCAPE` 是**逐表达式**生效的——写在整条 `WHERE`
    末尾不合法（实测 `near "ESCAPE": syntax error`），故必须贴在每个 LIKE 之后；
    而这正是"改一处漏一处"最容易发生的地方。调用方只传列名。
    """
    operator = "NOT LIKE" if negate else "LIKE"
    names = [columns] if isinstance(columns, str) else list(columns)
    return " OR ".join("%s %s ? ESCAPE '%s'" % (name, operator, LIKE_ESCAPE) for name in names)


#: 需要转义的 LIKE 元字符。反斜杠必须最先替换，否则会把后续插入的转义符再转义一次。
_LIKE_METACHARS = (LIKE_ESCAPE, "%", "_")

#: MATCH 的最短查询长度：trigram 索引不到 <3 字符的查询，强行 MATCH 是**假阴性**
#: （漏召回，比慢更糟）。短查询一律走 LIKE 子串分支。
MATCH_MIN_CHARS = 3


def escapeLike(text: str) -> str:
    """转义 LIKE 元字符（`\\` `%` `_`），供 `LIKE :pattern ESCAPE '\\'` 使用。"""
    escaped = text or ""
    for meta in _LIKE_METACHARS:
        escaped = escaped.replace(meta, LIKE_ESCAPE + meta)
    return escaped


def likePattern(query: str) -> str:
    """把查询串转成"子串匹配"模式（两侧 `%` 是通配符本体，中间的用户输入不被解释）。"""
    return f"%{escapeLike(query)}%"


def matchQuery(query: str) -> Optional[str]:
    """把查询串包成 FTS5 短语；空（或全空白）返回 None —— 空查询不该交给 MATCH。"""
    if not (query or "").strip():
        return None
    return '"%s"' % query.replace('"', '""')


def shouldMatch(query: str) -> bool:
    """该查询是否具备走 MATCH 的资格（长度足够且非空）。"""
    return len(query or "") >= MATCH_MIN_CHARS
