# -*- coding: utf-8 -*-
"""清单生成器的消费面计数必须显式声明解码口径（`generate_api_inventory._nonTestConsumers`）。

实测（本机中文 Windows，直接调生产函数）：

    scripts/generate_api_inventory.py:653  found = ...text=True).stdout
    AttributeError: 'NoneType' object has no attribute 'splitlines'

父端 `text=True` 不写 `encoding` 时，Python 用的是 **Windows ANSI 码页**（cp936），
而 `grep` 交回的是文件原始字节（前端源码是 UTF-8）。现量三个导出名：
`login` 13817 字节 / 1470 非 ASCII（utf-8 可解 133 行，cp936 在 @293 抛）、
`request` 32242 字节 / 513 非 ASCII（utf-8 284 行，cp936 @48 抛）、
`getPendingApprovals` 263 字节 / 非 ASCII 0（两口径都可解——侥幸那一支）。

两个读数一并记在这里，免得下一批又猜：
1. 把父进程 `PYTHONIOENCODING` 钉成 utf-8 **不修这个问题**——它只改 Python 自己的 stdio，
   不改 `locale.getpreferredencoding()`；实测两种父环境下都照样抛。外部件这一支只有显式
   `encoding=` 一个答案。
2. 这条路径今天不在 `--write` 的导出名集合里（所以清单没被算错，实跑只读模式与 `--write`
   都 exit 0），属**尚未被数据触发的崩面**，不是已发生的错账——本格据此定性，不夸大成"清单一直是错的"。

判据三层（承 §6-465 的形状）：跨平台代码形态格、Windows 真调用行为格（Linux 上 ANSI 码页恒 UTF-8，
这个缺陷形态在那边不存在 ⇒ 明确 skip 并自陈，不拿恒真凑数）、反空转格。
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.ast_scan import parseSource

REPO = Path(__file__).resolve().parents[2]
GEN = REPO / "scripts" / "generate_api_inventory.py"


def _consumerRunCall(source: str) -> ast.Call:
    """`_nonTestConsumers` 里那次 subprocess.run（应当只有一处）。"""
    tree = parseSource(source)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_nonTestConsumers")
    calls = [n for n in ast.walk(fn)
             if isinstance(n, ast.Call) and ast.unparse(n.func).endswith("subprocess.run")]
    assert len(calls) == 1, f"消费面计数应当只有一处 subprocess.run，现读 {len(calls)} 处"
    return calls[0]


def _readFacePin(call: ast.Call) -> dict:
    """读数：显式 encoding 有吗、值是什么、子件是不是 Python（Python 才要求两头钉）。"""
    kws = {k.arg: k.value for k in call.keywords if k.arg}
    value = ""
    if "encoding" in kws and isinstance(kws["encoding"], ast.Constant):
        value = str(kws["encoding"].value)
    argv = ast.unparse(call.args[0]) if call.args else ""
    return {
        "hasEncoding": "encoding" in kws,
        "encoding": value,
        "isPythonChild": "sys.executable" in argv,
    }


class TestConsumerCountDeclaresItsDecode:
    def test_runFacePinsEncodingExplicitly(self):
        source = GEN.read_text(encoding="utf-8")
        pin = _readFacePin(_consumerRunCall(source))
        assert pin["hasEncoding"], (
            "grep 交回的是源码原始字节（前端文件是 UTF-8），而父端不写 encoding 就按 Windows "
            "ANSI 码页解 ⇒ 读线程抛 UnicodeDecodeError、stdout 静默变 None，第 653 行崩"
        )
        assert pin["encoding"].lower().replace("-", "") == "utf8", (
            f"声明的口径是 {pin['encoding']!r}，与 grep 交回的 UTF-8 不一致"
        )

    def test_predicateBitesOnSyntheticShapes(self):
        """反空转：同一谓词喂三种合成形态，方向必须各异（缺、只钉错码页、钉对）。"""
        def pinOf(body: str) -> dict:
            return _readFacePin(_consumerRunCall(body))

        bare = pinOf(
            "def _nonTestConsumers(x):\n"
            "    subprocess.run(['grep', p], capture_output=True, text=True)\n")
        assert bare == {"hasEncoding": False, "encoding": "", "isPythonChild": False}, bare

        wrong = pinOf(
            "def _nonTestConsumers(x):\n"
            "    subprocess.run(['grep', p], capture_output=True, text=True, encoding='cp936')\n")
        assert wrong["hasEncoding"] and wrong["encoding"] == "cp936", wrong

        right = pinOf(
            "def _nonTestConsumers(x):\n"
            "    subprocess.run([sys.executable, '-c', c], capture_output=True, text=True,\n"
            "                   encoding='utf-8')\n")
        assert right["hasEncoding"] and right["encoding"] == "utf-8" and right["isPythonChild"], right


@pytest.mark.skipif(os.name != "nt",
                    reason="Linux/macOS 的 preferredencoding 恒 UTF-8，这个崩形在那边不存在；"
                           "跨平台的那条是形态格，不拿恒真凑数")
class TestConsumerCountOnRealMachine:
    def _load(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("gen_probe", str(GEN))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_aNameWithNonAsciiMatchesCountsInsteadOfCrashing(self):
        """`login` 的匹配里现量 1470 个非 ASCII 字节——旧形在这里抛 AttributeError。"""
        mod = self._load()
        count = mod._nonTestConsumers("login")     # 旧形：当场抛
        assert count > 0, f"有 133 行匹配的名字被判成 0 消费者——幻影列就是把读数吞了"
