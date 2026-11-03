# -*- coding: utf-8 -*-
"""playwright 惰性 import 的测试桩（§6-494，一处装配口，两档共用）。

**为什么不能 patch 消费模块的属性**：产品 `neurova/web_reach/browser_read.py:113` 把
`from playwright.async_api import async_playwright` 放在唯一消费点 `_browser_read_async()` 内
——那是 AGENTS §3「可选依赖一律惰性 import + fail-soft」的要求（`ffc8fbf2` 2026-10-07 落地的
正是这件事，但它**没回改测试**）。于是 `neurova.web_reach.browser_read.async_playwright`
这个名字从那天起就不存在，`patch(那个名字)` 只会抛 `AttributeError: module does not have the
attribute`，12 条行为断言全被卡在 mock 装配点上，红不在被测行为（§6-490 入账、§6-494 收口）。

**正解是注桩包**：把 `playwright` / `playwright.async_api` 挂进 `sys.modules`，让生产那句惰性
import 原样取到假工厂——被测的仍是生产那条取用路径；且**薄环境（真没装 playwright）也跑得动**，
不像"只把 patch 目标改指 `playwright.async_api.async_playwright`"那样在未装时直接
ModuleNotFoundError。

不是把 import 提回模块级：那会违反 §3，并让没装 playwright 的机器在 import 面就炸。
"""

import contextlib
import sys
import types
from unittest.mock import MagicMock

_STUB_ROOT = "playwright"
_STUB_SUB = "playwright.async_api"


@contextlib.contextmanager
def stubAsyncPlaywright():
    """yield 一枚 `MagicMock` 充当 `async_playwright` 工厂，退出时还原 `sys.modules`。

    用法：`with stubAsyncPlaywright() as pw: pw.return_value = _make_fake_playwright(browser)`；
    要断言"没启动浏览器"就读 `pw.assert_not_called()`。
    """
    saved = {name: mod for name, mod in sys.modules.items()
             if name == _STUB_ROOT or name.startswith(_STUB_ROOT + ".")}

    pkg = types.ModuleType(_STUB_ROOT)
    sub = types.ModuleType(_STUB_SUB)
    factory = MagicMock(name="async_playwright")
    sub.async_playwright = factory
    pkg.async_api = sub

    sys.modules[_STUB_ROOT] = pkg
    sys.modules[_STUB_SUB] = sub
    try:
        yield factory
    finally:
        for name in [k for k in list(sys.modules)
                     if k == _STUB_ROOT or k.startswith(_STUB_ROOT + ".")]:
            del sys.modules[name]
        sys.modules.update(saved)
