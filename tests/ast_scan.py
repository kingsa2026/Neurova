# -*- coding: utf-8 -*-
"""兼容薄转发：共享解析预算的唯一实现在 ``neurova/core/ast_scan.py``。

P1-19 收口：生产码（``tool_executor`` / ``safe_expr`` / ``scripted.validator``）
与 ``scripts/`` 六处曾 ``from tests.ast_scan import parseSource``——测试根反向
成为运行时事实源，任何不打包 tests/ 的发布形态（wheel、仅含 neurova/ 的镜像）
在 import 期即崩。实现整体下沉 ``neurova/core/ast_scan.py``（单一事实源，
AGENTS 修复教义第 6 条）；本文件只保留旧导入面兼容——tests/ 内既有测试的
``from tests import ast_scan`` / ``from tests.ast_scan import parseSource``
照常可用，**新代码一律直接** ``from neurova.core.ast_scan import ...``。
"""

from neurova.core.ast_scan import *  # noqa: F401,F403  公开面随实现单源
from neurova.core.ast_scan import (  # noqa: F401  显式补齐测试面用到的私有助手
    _cacheKey,
    _cachedCode,
    _cachedNodes,
    _cachedParse,
    _walkNodes,
)
