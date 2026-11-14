# -*- coding: utf-8 -*-
"""SQL/迁移安全工具单源（P3-19）。

- :func:`quoteIdent`：SQLite 标识符安全引用（双引号包裹 + 内部双引号转义），
  供动态拼接 ``PRAGMA``/``UPDATE`` 的迁移代码统一取用——表名/列名绝不允许
  裸拼进 SQL。原 ``agent_migration.py`` 与 ``agent_layout_migration.py``
  各有一份逐字相同的 ``_quoteIdent``，收口到这里。
- :func:`replacePathStrings`：把字符串中的旧路径前缀按右边界规则替换为
  新路径；两个迁移模块的 ``_rewriteJsonValue`` 字符串分支共用此实现
  （原先各写一份相同的 ``re.sub`` 循环）。
"""
from __future__ import annotations

import re
from typing import List, Tuple

#: 路径替换的右边界：命中前缀之后必须紧跟串尾/路径分隔/引号/空白/常见标点，
#: 才认作独立前缀（防止 ``/old`` 误伤 ``/old_extra`` 这类更长路径）。
PATH_BOUNDARY = r"(?=$|[\\/\"'\s,;:)\]}>])"


def quoteIdent(value: str) -> str:
    """SQLite 标识符安全引用：包双引号并转义内部双引号。"""
    return '"' + value.replace('"', '""') + '"'


def replacePathStrings(value: str, pairs: List[Tuple[str, str]]) -> str:
    """按 (旧前缀, 新前缀) 对替换字符串中的路径，只认右边界完整的命中。"""
    for src, dst in pairs:
        if src in value:
            value = re.sub(re.escape(src) + PATH_BOUNDARY, lambda _m: dst, value)
    return value
