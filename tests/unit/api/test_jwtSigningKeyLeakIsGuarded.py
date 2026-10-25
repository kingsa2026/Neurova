# -*- coding: utf-8 -*-
"""签名密钥的模块级改指必须自带复原——否则后面每一档的 token 都验不过（§6-427）。

## 形态

`auth.JWT_SECRET_KEY` 是模块级全局。两份文档级档（`test_api_auth.py` /
`test_loginRouteContract.py`）都按"这枚 token 必须符合 TEST_SECRET"来断言，故它们必须
把签名面指过去；问题不在"指"，在**指完不留复原**：

```
test_api_auth 模块级: auth.JWT_SECRET_KEY = TEST_SECRET     ← 从不复原
```

同一条腿（受保护子集是**单进程**、按清单顺序跑）里，排在其后的档用生产
`create_access_token` 签出的 token 就验不过。实测（本机 3.11，本仓依赖集）：

```
$ pytest test_roleGateIdentitySourceIsStrict.py memory_route_shadowing.py \
         loginRouteContract.py test_sleep_phase_cycle.py test_api_auth.py
6 failed —— 全是 jwt.exceptions.InvalidSignatureError
```

注意 `test_api_auth.py` **今天不在**受保护子集里，所以这条泄漏在 CI 上暂不现形：
它是潜伏的，不是已修的。本档守的正是这个潜伏面。

## 判据

1. 受保护子集里的档，不得在模块级给 `auth.JWT_SECRET_KEY` 赋值而同一模块内不做复原
   （AST：模块体赋值 ＋ 同一模块出现复原调用/夹具，两者必须同时成立）；
2. 反空转：样本里"只改不复原"必须被抓到，"改＋复原"必须放行。
"""

from __future__ import annotations

import ast
import pathlib
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests import ast_scan  # noqa: E402

#: 撤销/复原的任何一种写法都算"带了复原"（判据咬的是有没有人收拾，不是怎么写）。
_RESTORE_CALLS = {"adoptJwtSecretForTests", "resetJwtSecretToProduction"}


def _assignsSecretAtModuleLevel(tree) -> bool:
    for statement in tree.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for node in ast.walk(statement):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Attribute) and target.attr == "JWT_SECRET_KEY":
                    return True
    return False


def _carriesRestore(tree) -> bool:
    return any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and node.func.attr in _RESTORE_CALLS
        for node in ast.walk(tree)
    )


def test_protectedEntriesNeverLeakAnUnrestoredSecret():
    offenders = []
    for entry in ast_scan.protectedSubsetEntries():
        path = REPO_ROOT / entry
        if not path.is_file():
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:  # pragma: no cover - 由 static-gate 抓
            continue
        if _assignsSecretAtModuleLevel(tree) and not _carriesRestore(tree):
            offenders.append(entry)
    assert not offenders, (
        "以下受保护档在模块级改指签名面、却不带复原——同一条腿里排在它后面的档"
        "签出的 token 会全部验不过（§6-427 实测 6 条 InvalidSignatureError）：\n  "
        + "\n  ".join(offenders)
        + "\n修法：把前提收进用例内，或改完调 "
        + " / ".join(sorted(_RESTORE_CALLS))
        + " 复原。"
    )


@pytest.mark.parametrize("body, leaked", [
    ("import x\nx.JWT_SECRET_KEY = 'v'\n", True),
    ("import x\nx.JWT_SECRET_KEY = 'v'\nx.resetJwtSecretToProduction()\n", False),
    ("import x\nfrom x import adoptJwtSecretForTests\nu = adoptJwtSecretForTests('v')\n", False),
    ("import x\ndef f():\n    x.JWT_SECRET_KEY = 'v'\n", False),
])
def test_detectorSeesTheLeakNotTheWording(body, leaked):
    """反空转：只改不复原抓到；改＋复原、以及用例内临时改指都放行。"""
    assert (_assignsSecretAtModuleLevel(ast.parse(body))
            and not _carriesRestore(ast.parse(body))) is leaked
