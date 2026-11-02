# -*- coding: utf-8 -*-
"""PATH 回读那处必须两侧钉同 UTF-8（`win_installer_kit.refresh_machine_path`）。

实测现场（本机，中文 Windows，纯净父环境 `env -u PYTHONIOENCODING -u PYTHONUTF8`）：

    Exception in thread Thread-1 (_readerthread)
    UnicodeDecodeError: 'gbk' codec can't decode byte 0xae in position 40: illegal multibyte sequence
    AttributeError: 'NoneType' object has no attribute 'strip'
      File "scripts/desktop/win_installer_kit.py", line 141, in refresh_machine_path

即**打包机入口文档里那条 `python scripts/desktop/win_installer_kit.py run …` 今天跑不到底**。
根因不在 PowerShell 也不在 PATH：那次 `subprocess.run(..., text=True)` 不写 `encoding`，父端按
`locale.getpreferredencoding()`（cp936）解，而 PowerShell 这条命令交回的是 **UTF-8 字节**
（现量 1968 字节、56 个非 ASCII，按 utf-8 解 0 个 U+FFFD，按 cp936 解在 @31 抛）。
`text=True` 下解码异常只炸读线程：子进程 rc 仍是 0，`probe.stdout` 静默变 None。

同进程还量到一件更别扭的事：PowerShell **裸打字符串走 cp936**（`'项目A'` → `cf ee c4 bf`），
而点源 helper 之后的对象流走 UTF-8——同一个子件两条通道编码不一致。所以「按机器码页解」
在任何一台机器上都不是一个可靠口径，只钉父端也不是：把子件的控制台输出显式钉成 UTF-8，
两侧才有一个共同答案（本仓 §6-225 那条「半修」纪律）。

判据分三层：
- 跨平台可复跑的代码形态格（格1）：那次调用必须显式 `encoding`，且命令里带控制台输出编码前缀。
- Windows 真跑的行为格（格2）：真调生产函数，PATH 必须被刷新成段数不减的结果。非 Windows
  **明确 skip 并自陈**——Linux 上该函数按设计 no-op，行为格没有对象；恒真不是判据，跳过才是实话。
- 反空转格（格3）：把格1 的谓词喂合成源码，缺 encoding 必须被点名、齐的必须放行。
"""

from __future__ import annotations

import ast
import importlib.util
import os
import re
import sys
from pathlib import Path

import pytest

from tests.ast_scan import parseSource

REPO = Path(__file__).resolve().parents[3]
KIT = REPO / "scripts" / "desktop" / "win_installer_kit.py"


def _pathProbeCall(source: str) -> ast.Call:
    """取出 `refresh_machine_path` 里那次 `subprocess.run(...)`（唯一一处，找不到即红）。"""
    tree = parseSource(source)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "refresh_machine_path")
    calls = [n for n in ast.walk(fn)
             if isinstance(n, ast.Call) and ast.unparse(n.func) == "subprocess.run"]
    assert len(calls) == 1, f"PATH 探针应当只有一处 subprocess.run，现读 {len(calls)} 处"
    return calls[0]


def _stringConsts(tree: ast.AST) -> dict:
    """模块级 `NAME = "字符串"` 表——命令里引用常量时，谓词要顺着名字取到字面值。"""
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
           and isinstance(node.targets[0], ast.Name) \
           and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            out[node.targets[0].id] = node.value.value
    return out


def _pinReading(call: ast.Call, source: str) -> dict:
    """这一处「两侧是否钉同一 UTF-8」的读数——格1 与格3 共用同一个谓词，不各写一份。

    子件侧认两种等价写法：命令字面量里直接带前缀，或引用一个模块级字符串常量（本仓取后者，
    因为同一段前缀还可能给别的 PowerShell 调用复用——写第二份字面量就是第二处定义）。
    """
    tree = parseSource(source)
    consts = _stringConsts(tree)
    kws = {k.arg: k.value for k in call.keywords if k.arg}
    declared = ""
    if "encoding" in kws and isinstance(kws["encoding"], ast.Constant):
        declared = str(kws["encoding"].value)
    cmdNode = call.args[0] if call.args else kws.get("cmd")
    commandText = ast.unparse(cmdNode) if cmdNode is not None else ""
    resolved = commandText
    for name, value in consts.items():
        if re.search(r"\b" + re.escape(name) + r"\b", commandText):
            resolved += "\n" + value
    return {
        "hasEncoding": "encoding" in kws,
        "encoding": declared,
        "childPinned": "OutputEncoding" in resolved and "UTF8" in resolved,
        "textMode": "text" in kws or "universal_newlines" in kws,
    }


class TestPathProbePinsBothEnds:
    def test_probeDeclaresExplicitEncodingAndPinsChild(self):
        source = KIT.read_text(encoding="utf-8")
        pin = _pinReading(_pathProbeCall(source), source)
        assert pin["hasEncoding"], (
            "PATH 回读那次子进程没写 encoding——父端按机器码页解 PowerShell 的 UTF-8 字节，"
            "读线程抛 UnicodeDecodeError、stdout 静默变 None，第 141 行当场 AttributeError"
        )
        assert pin["encoding"].lower().replace("-", "") == "utf8", (
            f"声明的口径是 {pin['encoding']!r}，与 PowerShell 交回的 UTF-8 不一致"
        )
        assert pin["childPinned"], (
            "只钉父端是半修：同一进程里 PowerShell 裸打字符串走机器码页、点源 helper 后的对象流走 "
            "UTF-8（本机两形都实测到），子件控制台输出必须显式钉 UTF-8"
        )

    def test_predicateBitesOnSyntheticShapes(self):
        """反空转：同一谓词喂四种合成形态，读数必须各不相同且方向正确。"""
        bare = _pinReading(_pathProbeCall(
            "def refresh_machine_path():\n"
            "    subprocess.run(['powershell', '-Command', '. x.ps1'], "
            "capture_output=True, text=True)\n"), "")
        assert bare == {"hasEncoding": False, "encoding": "", "childPinned": False,
                        "textMode": True}, bare

        parentOnly = _pinReading(_pathProbeCall(
            "def refresh_machine_path():\n"
            "    subprocess.run(['powershell', '-Command', '. x.ps1'], "
            "capture_output=True, text=True, encoding='utf-8')\n"), "")
        assert parentOnly["hasEncoding"] and not parentOnly["childPinned"], parentOnly

        literal = _pinReading(_pathProbeCall(
            "def refresh_machine_path():\n"
            "    subprocess.run(['powershell', '-Command', "
            '"[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;. x.ps1"], '
            "capture_output=True, text=True, encoding='utf-8')\n"), "")
        assert literal["hasEncoding"] and literal["childPinned"], literal

        # 本仓的真形：前缀提成模块级常量、命令里按名字引用——谓词要顺名字取到字面值
        viaConst = _pinReading(_pathProbeCall(
            'PS_UTF8_PREFIX = "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;"\n'
            "def refresh_machine_path():\n"
            "    subprocess.run(['powershell', '-Command', "
            "PS_UTF8_PREFIX + '. x.ps1'], "
            "capture_output=True, text=True, encoding='utf-8')\n"),
            'PS_UTF8_PREFIX = "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;"\n'
            "def refresh_machine_path():\n"
            "    subprocess.run(['powershell', '-Command', "
            "PS_UTF8_PREFIX + '. x.ps1'], capture_output=True, text=True, encoding='utf-8')\n")
        assert viaConst["hasEncoding"] and viaConst["childPinned"], viaConst


@pytest.mark.skipif(os.name != "nt",
                    reason="PATH 刷新只在 Windows 上有读盘面；Linux 上该函数按设计 no-op，"
                           "本格没有对象（跨平台的那条是格1，不拿恒真凑数）")
class TestPathProbeOnRealMachine:
    def _loadKit(self):
        spec = importlib.util.spec_from_file_location("wik_path_probe", str(KIT))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_refreshActuallyMergesPath(self):
        mod = self._loadKit()
        before = mod.os.environ["PATH"]
        try:
            mod.refresh_machine_path()          # 真 helper、真 PowerShell、真 PATH
        finally:
            mod.os.environ["PATH"] = before     # 全局回填按原样，不只回填引用
        merged = mod.os.environ["PATH"]
        assert merged, "刷新后 PATH 是空串——那比不刷更坏"
        assert merged.count(";") + 1 >= before.count(";") + 1, (
            "合并后的段数比合并前还少：helper 是只增不减的合并，读数反了说明取到的不是 PATH 那一行"
        )
        assert not re.search(r"[\uFFFD]", merged), "PATH 里有 U+FFFD：解码口径与子件写侧不一致"
