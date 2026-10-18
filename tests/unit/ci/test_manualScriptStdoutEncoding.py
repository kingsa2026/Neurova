# -*- coding: utf-8 -*-
r"""活体档的 stdout 编码必须自己钉住——否则退出码 1 可以来自 print，而不是来自判据。

复核实状（AST 现读 `tests/manual/*.py`，166 档，逐档取字面常量里 cp936 编不出的字符）：
    含不可 cp936 字面字符 且 已钉 reconfigure（安全）＝ 36 档
    含不可 cp936 字面字符 且 **未钉**（真 offender）              ＝ 27 档
仓内既有写法（那 36 档里的共同形状，本批照它统一）：
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

危害不是"输出难看"：`tests/manual/pathNameListsOneSource_b62.py` 第 6 腿的 detail 串里有个 `↔`，
父进程没给 `PYTHONIOENCODING` 时 stdout 是本机 cp936 ⇒ `print` 里抛 `UnicodeEncodeError`、
**退出码 1**。而活体档的全部证据就是"退出码 + 那几行读数"——退出码被打印本身决定时，
读起来就像"有一条腿 FAIL"，人会去查一个根本没坏的东西（形态集 265／243 同族：报错说错了对象）。
批 62 的复跑现场就撞上一次，批 66 的探针又撞上一次（`✓`）。

为什么钉在脚本里而不是要求调用方带环境变量：判据的成立不该依赖"谁怎么起的"。
`errors="replace"` 是有意的——编码问题只该影响显示，不该影响判定；判定靠的是退出码与 PASS/FAIL 行。

覆盖边界写清（别把这格读成"活体档从此不会编码坏"）：本批管的是**字面常量**里的不可编码字符
（静态可判、且正是撞到的那两例）。跑起来才决定的字符串（工具回包、模型文本、路径）仍可能不可编码——
那一类要证就得逐档实跑，不在静态不变量的能力范围内；所以这格是"零容忍的门"，不是"全仓已安全"的断言。
"""

from __future__ import annotations

import ast
import sys

from tests import ast_scan
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

MANUAL_DIR = REPO / "tests" / "manual"
PIN_CALL_FRAGMENT = "stdout.reconfigure("


def _unencodableInLiterals(source: str) -> set:
    """字面常量里 cp936（本机默认 stdout 编码）编不出的字符集合。"""
    out = set()
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        for ch in node.value:
            try:
                ch.encode("cp936")
            except UnicodeEncodeError:
                out.add(ch)
    return out


def _pinsStdoutEncoding(source: str) -> bool:
    """模块顶层有没有真的调用 `sys.stdout.reconfigure(...)`——写进字符串或注释不算钉住。"""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "reconfigure":
            receiver = node.func.value
            if isinstance(receiver, ast.Attribute) and isinstance(receiver.value, ast.Name) \
                    and receiver.value.id == "sys" and receiver.attr == "stdout":
                return True
    return False


def _liveScripts() -> list:
    """manual 目录里的"真脚本"（`_` 前缀的是共享件，不是活体档）。

    枚举走 `tests/ast_scan` 的共享预算，不自己 `glob`——§6-314 的 D22 收的就是判据里
    各写一份"文件枚举＋自付解析"的形态（成本绑在文件总量上，且读盘口径各处不一）。
    """
    refs = ast_scan.sourceRefsUnder(MANUAL_DIR, ".py")
    surface = len(refs)
    assert surface > 100, f"扫描面现读 {surface} 个 .py（根＝tests/manual/）——根被改窄时「零命中」不代表干净"
    return [ref for ref in refs if not ref.path.name.startswith("_")]


class TestEveryScriptThatPrintsForeignCharsPinsEncoding:
    def testNoLiveScriptPrintsWhatThisMachineCannotEncode(self):
        """主格：含不可 cp936 字面量的活体档，必须一律自己钉 stdout 编码（零容忍，不留基线）。"""
        offenders = []
        for ref in _liveScripts():
            src = ref.code
            if _unencodableInLiterals(src) and not _pinsStdoutEncoding(src):
                offenders.append(ref.path.name)

        assert not offenders, (
            f"{len(offenders)} 档活体脚本会打出本机编码编不出的字符又没钉 stdout 编码，"
            f"`print` 抛 UnicodeEncodeError 会让退出码变 1，看着像“有一条腿 FAIL”：{offenders}")

    def testDetectorActuallyReadsCallsNotWords(self):
        """探测器自证（双向）：真调用要认下来；把这句话写进字符串或注释不算钉住。"""
        pinned = ("import sys\n"
                  'sys.stdout.reconfigure(encoding="utf-8", errors="replace")\n'
                  "print('⇒')\n")
        onlyMentioned = ("import sys\n"
                         '# sys.stdout.reconfigure(encoding="utf-8") 的注释\n'
                         "X = 'sys.stdout.reconfigure'  # 出现在字符串里，不算\n")

        assert _pinsStdoutEncoding(pinned), "真钉住的写法被判成没钉——那零容忍格会把合规档报成违规"
        assert not _pinsStdoutEncoding(onlyMentioned), (
            "注释与字符串里的字面话被当成了“已钉住”——那这格就是橡皮章")
        assert _unencodableInLiterals(pinned) == {"⇒"}, (
            f"字面量扫描没咬到不可编码字符：{_unencodableInLiterals(pinned)}")
        assert _unencodableInLiterals(onlyMentioned) == set(), "良性样本里冒出了不可编码字符"


class TestThePinnedCallIsActuallyReachable:
    def testPinSitsAtModuleTopLevelAfterSysIsBound(self):
        """钉的位置要模块顶层、且在 `import sys` 之后——函数体内的调用不会在打印前发生（形态集 247）。"""
        badlyPlaced = []
        for ref in _liveScripts():
            src = ref.code
            if not _pinsStdoutEncoding(src):
                continue
            tree = ast_scan.transientTree(ref.path)
            sysBoundBefore = False
            for node in tree.body:                      # 只看顶层语句，按书写顺序
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    names = {a.name for a in node.names}
                    if "sys" in names or node.__class__ is ast.ImportFrom and node.module == "sys":
                        sysBoundBefore = True
                    continue
                for call in (n for n in ast.walk(node) if isinstance(n, ast.Call)
                             and isinstance(n.func, ast.Attribute) and n.func.attr == "reconfigure"):
                    if not sysBoundBefore:
                        badlyPlaced.append(f"{ref.path.name}:{call.lineno}")
        assert not badlyPlaced, f"钉在 `import sys` 之前（跑到那行就 NameError）：{badlyPlaced}"
