"""子进程写侧编码口径的唯一出处（§6-490，教义第 6/7 条）。

三份逐字相同的 `_utf8ChildEnv()`（`neurova/web_reach/reach.py`、`scripts/ci_static_gate.py`、
`scripts/ci/protected_subset_nightly.py`）在此收一，另两份退役。落点选在生产侧：`scripts/` 可以
import 生产包，反过来（生产 import `scripts/`）是方向错。

为什么必须钉子进程写侧：本仓根路径含中文，子件把带路径的日志写到 stderr 时按
`locale.getpreferredencoding()`（开发机 cp936）编码，父端再按 utf-8 解就成了 U+FFFD 替换字符——
读数为真、内容为假。「父端按 utf-8 解、子端按 cp936 写」就是半修（§6-225 那族），两头都得钉。

键名一律写字面量：棘轮闸（`tests/unit/ci/test_subprocessTextEncodingRatchet.py`）与本族判据都按
AST 里的字符串常量认「这个 dict 带键」，把键换成常量会让**已修的**实装在判据眼里消失。
"""

from __future__ import annotations

import os
from typing import Dict


def utf8ChildEnv() -> Dict[str, str]:
    """一次 `subprocess` 调用的子环境：继承父环境，写侧钉 utf-8。"""
    return {**os.environ, "PYTHONIOENCODING": "utf-8"}
