# -*- coding: utf-8 -*-
"""`scripts/` 族里会打印非 ASCII 的档，必须自己钉住 stdout 读数出口（§6-496）。

为什么需要：本仓宿主是 Windows，控制台默认 cp936。脚本 print 中文与箭头时，只要出口没钉
utf-8，就会在一句 `print` 上抛 `UnicodeEncodeError` ⇒ 退出码 1，于是"红"指向**脚本自己**
而不是被测行为（`tests/manual/` 那 36 档早就为同一件事钉过这一行）。
现算裸奔面 **35 档**（不是 §6-493 那句「5 档」——那个数只数了 `scripts/ci/` 一个目录，
口径写窄了，本格一并更正）。本批先收掉会进 CI 与跑测面的 5 档，其余 30 档进只降不升基线。

三格分工：
① 等号格：裸奔集合必须与登记基线**逐条相等**——多了＝新写了一处裸 print，少了＝有人收掉了
   存量却没人收数（"悄悄比基线好"下一次就没人回来核）；
② 收口格：本批点名的档必须已经不在裸奔表里（防止等号格靠"把新档写进基线"蒙过去）；
③ 反证格：谓词必须认三种**已有正确写法**（直写／`hasattr` 守卫／`_reconfigureStdout()` 助手形，
   后者只出现 `stream.reconfigure` 不含 `sys.stdout.reconfigure` 整串），同时必须点名两种
   "看着像钉过"的形——只钉 stderr、以及只在文字里提一句 reconfigure。
   ③ 的存在理由是一段本会话的错账：第一次用整串匹配判有无 pin，把
   `scripts/ci/ab_baseline.py:145-155` 误判成缺 pin，差点记出假欠账（§6-493 已记）。

未一并做完的（如实登记）：pin 写法仍有三种变体（直写／`hasattr` 守卫／助手形，其中三档另带
`newline="\n"` 钉"读数只出现 LF"）。**本批没有引入第四种**（补的 5 档一律用占多数的
`hasattr` 守卫式）；把它们收成一个 helper 要先解 `scripts/` 的 import 路径问题（多档不是包、
没有仓根注入），属另拍。
"""

import ast
from pathlib import Path

import pytest

from tests.ast_scan import REPO_ROOT, parseSource, sourceCode, trackedPyPaths

#: 只降不升基线（11-04 现算：30 档 → 补钉 28 档 → 余 3）。
#: 余下三档 **不是入口脚本而是被 import 的模块**（`scripts/config.py` 21 处、`scripts/health_check.py` 7 处、
#: `scripts/port_utils.py` 6 处引用，三档都没有 `__main__` 块）：在模块顶层钉 stdout 会**劫持导入方的 stdout**，
#: 所以本批不给它们补钉——正解要么把中文 print 改成 log/参数化输出，要么给各档加自己的入口块，属另批。
BARE_BASELINE = 3

#: 本批点名收口的档（进 CI／跑测面的那一族）。
CLOSED_IN_THIS_BATCH = (
    "scripts/ci/audit_ledger_commit_guard.py",
    "scripts/ci/cognitive_component_table.py",
    "scripts/ci/context_deadline_ledger.py",
    "scripts/ci/coverage_report.py",
    "scripts/ci/protected_subset_nightly.py",
)


def _nonCanonicalPins(root="scripts", baseDir=None) -> list:
    """钉 stdout 只许一种行内写法：`if hasattr(<stream>, "reconfigure")` 守卫 ＋ `errors="replace"`。

    为什么单独一格：`pinsStdoutStream()` 判的是"有没有钉"，为不误伤既有 44 档，它把直写、
    `hasattr` 守卫、助手形（`_reconfigureStdout()` 里 for stream 循环）三种都算通过——
    于是"三种并存"这件事在闸里合法。本格按用户裁定（收成一种行内写法＋判据只认它）把口径收成
    **唯一形**：直写少 `hasattr` 会在 stdout 被换成无 reconfigure 的对象时抛 AttributeError，
    助手形则是第四种"看着也是钉"的车辆；两者都点名。
    """
    offenders = []
    scanRoot = Path(baseDir) if baseDir is not None else REPO_ROOT / root
    for path in sorted(scanRoot.rglob("*.py")):
        source = path.read_text(encoding="utf-8", errors="replace")
        try:
            tree = parseSource(source)
        except SyntaxError:
            continue
        guarded = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            test = node.test if isinstance(node.test, ast.Call) else None
            if (test is not None and getattr(test.func, "id", None) == "hasattr"
                    and isinstance(test.args[0], (ast.Attribute, ast.Name))
                    and len(test.args) > 1 and getattr(test.args[1], "value", None) == "reconfigure"):
                guarded.update(id(ch) for ch in ast.walk(node))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "reconfigure"):
                continue
            stream = node.func.value
            isNamedStream = (isinstance(stream, ast.Attribute)
                             and getattr(stream.value, "id", None) == "sys"
                             and stream.attr in ("stdout", "stderr"))
            hasReplace = any(k.arg == "errors" and getattr(k.value, "value", None) == "replace"
                             for k in node.keywords)
            inGuard = any(id(ch) in guarded for ch in ast.walk(node))
            if not (isNamedStream and hasReplace and inGuard):
                rel = path.relative_to(scanRoot).as_posix()
                offenders.append("%s:%d" % (rel, node.lineno))
    return sorted(offenders)


def test_stdoutPinIsTheOneCanonicalShape():
    """单源：`scripts/` 里每一处 stdout 钉法都必须是那一形（现算非规范形必须为空）。"""
    offenders = _nonCanonicalPins()
    assert offenders == [], (
        "这些落点的 stdout 钉法不是唯一规范形（应为 `if hasattr(sys.stdout/stderr, \"reconfigure\")` "
        "守卫＋errors=\"replace\"）：\n  %s" % "\n  ".join(offenders))


def test_pinShapePredicateRejectsBareLoopAndMissingReplace(tmp_path):
    """反证格：三种旧形必须各被点名，规范形必须不被冤枉——否则上一格"零 offender"是假绿。"""
    NL = chr(10)
    cases = {
        "canonical.py": ("import sys" + NL +                        "if hasattr(sys.stdout, \"reconfigure\"):" + NL +                        "    sys.stdout.reconfigure(encoding=\"utf-8\", errors=\"replace\")" + NL),
        "bare.py": "import sys" + NL + "sys.stdout.reconfigure(encoding=\"utf-8\", errors=\"replace\")" + NL,
        "no_replace.py": ("import sys" + NL +
                          "if hasattr(sys.stdout, \"reconfigure\"):" + NL +
                          "    sys.stdout.reconfigure(encoding=\"utf-8\")" + NL),
        "loop_helper.py": ("import sys" + NL + "def _pin():" + NL +                           "    for stream in (sys.stdout, sys.stderr):" + NL +
                           "        stream.reconfigure(encoding=\"utf-8\", errors=\"replace\")" + NL),
    }
    for name, source in cases.items():
        (tmp_path / name).write_text(source, encoding="utf-8", newline="")

    offenders = _nonCanonicalPins(baseDir=tmp_path)
    named = {o.split(":")[0] for o in offenders}
    assert named == {"bare.py", "no_replace.py", "loop_helper.py"}, offenders
    assert not any(o.startswith("canonical.py") for o in offenders), offenders


def _nonAsciiPrintLines(source: str) -> list:
    """`print(...)` 直接带非 ASCII 字符串字面量的行号（注释与 docstring 不算）。"""
    try:
        tree = parseSource(source)
    except SyntaxError:
        return []
    lines = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "print"):
            continue
        for inner in ast.walk(node):
            if (isinstance(inner, ast.Constant) and isinstance(inner.value, str)
                    and any(ord(ch) > 127 for ch in inner.value)):
                lines.append(node.lineno)
                break
    return lines


def _isStdoutExpr(node) -> bool:
    return isinstance(node, ast.Attribute) and node.attr == "stdout"


def pinsStdoutStream(source: str) -> bool:
    """这份源码到底钉没钉** stdout 那一路**——按 AST 认作用对象，不按字面串猜。

    认三种已有写法：`sys.stdout.reconfigure(...)`、`for stream in (sys.stdout, sys.stderr)`
    里的 `stream.reconfigure(...)`（助手形），以及两者带 `newline=` 的变体。
    只钉 stderr 不算，注释里提一句不算——那两形在生产里照样会炸。
    """
    try:
        tree = parseSource(source)
    except SyntaxError:
        return False
    names = {"stdout"}                       # `sys.stdout.reconfigure` 里属性名就是 stdout
    for node in ast.walk(tree):
        if isinstance(node, ast.For) and isinstance(node.iter, (ast.Tuple, ast.List)):
            if any(_isStdoutExpr(elt) for elt in node.iter.elts) and isinstance(node.target, ast.Name):
                names.add(node.target.id)    # 助手形：循环变量此刻就绑着 stdout
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "reconfigure"):
            continue
        base = node.func.value
        if isinstance(base, ast.Name) and base.id in names:
            return True
        if _isStdoutExpr(base):
            return True
    return False


#: 扫描面：仓根入口档＋`scripts/`。此前只看 `scripts/`，于是仓根的 `start.py`／`install.py`
#: （167 处中文 print）从头到尾不在任何闸眼下——「余 3 档裸奔」的读数指错了对象。
#: 只用**跟踪文件**：仓根的 `.tmp_*.py` 探针残件已被 gitignore，不该进面。
SCAN_ROOTS = ("", "scripts")


def faceFiles(roots=SCAN_ROOTS) -> list:
    """扫描面本身：跟踪的仓根顶层档＋`scripts/` 全部档（去重、按名排序）。"""
    rels = set()
    for root in roots:
        for rel in (trackedPyPaths(root) if root else trackedPyPaths()):
            if not root and "/" in rel:
                continue   # 仓根那一路只看顶层档，子目录交给各自的 root
            rels.add(rel)
    return sorted(rels)


def barePrinters(roots=SCAN_ROOTS) -> list:
    """会打非 ASCII、却没钉自家 stdout 的档。"""
    bare = []
    for rel in faceFiles(roots):
        source = sourceCode(REPO_ROOT / rel)
        if _nonAsciiPrintLines(source) and not pinsStdoutStream(source):
            bare.append(rel)
    return sorted(bare)


def test_faceIsWiderThanTheOldScriptsOnlyBlindSpot():
    """面自证：扫描面必须真含仓根入口档。

    只报「裸奔 3 档」而不报面有多大，就会把面缺口读成债已清——
    `start.py`／`install.py` 合计 167 处中文 print 此前一直在闸外。
    """
    face = faceFiles()
    assert len(face) >= 88, "扫描面现算只有 %d 档——面缩了，裸奔计数再小也不可信" % len(face)
    rootTop = {f for f in face if "/" not in f}
    assert {"start.py", "install.py"} <= rootTop, "仓根入口档掉出扫描面：%s" % sorted(rootTop)
    assert any(f.startswith("scripts/") for f in face), "scripts/ 那一半掉了"

def test_barePrintersMatchTheRegisteredBaseline():
    """等号格：裸奔集合必须等于基线数——多了是新增裸 print，少了是有人收完没销账。"""
    bare = barePrinters()
    assert len(bare) == BARE_BASELINE, (
        "裸奔面现读 %d 档、登记基线 %d 档：%s——变多＝新写了一处没钉出口的中文 print"
        "（cp936 宿主上一句 print 就能让退出码变 1，红指向脚本自己）；"
        "变少＝有人收掉了存量却没把基线收下去，那下一次就没人知道这里已经更好了"
        % (len(bare), BARE_BASELINE, bare[:6]))


def test_filesClosedInThisBatchAreNoLongerBare():
    """收口格：本批点名的档必须真不在裸奔表里——不许靠把它们写进基线来蒙过等号格。"""
    bare = set(barePrinters())
    stillBare = [rel for rel in CLOSED_IN_THIS_BATCH if rel in bare]
    assert stillBare == [], (
        "这些档本批声称已收口，却仍会 print 非 ASCII 且不钉 stdout：%s" % stillBare)


@pytest.mark.parametrize("source, expectBare", [
    pytest.param('import sys\nif hasattr(sys.stdout, "reconfigure"):\n'
                 '    sys.stdout.reconfigure(encoding="utf-8", errors="replace")\n'
                 '    sys.stderr.reconfigure(encoding="utf-8", errors="replace")\n'
                 'print("读数")\n', False, id="directBothStreams"),
    pytest.param("import sys\ndef _reconfigureStdout():\n"
                 "    for stream in (sys.stdout, sys.stderr):\n"
                 '        if hasattr(stream, "reconfigure"):\n'
                 '            stream.reconfigure(encoding="utf-8", errors="replace")\n'
                 "def main():\n    _reconfigureStdout()\n"
                 'print("读数")\n', False, id="helperViaLoopTarget"),
    pytest.param('import sys\nif hasattr(sys.stdout, "reconfigure"):\n'
                 '    sys.stdout.reconfigure(encoding="utf-8", errors="replace", newline="\\n")\n'
                 'print("读数")\n', False, id="directWithLfNewline"),
    pytest.param('import sys\nif hasattr(sys.stderr, "reconfigure"):\n'
                 '    sys.stderr.reconfigure(encoding="utf-8", errors="replace")\n'
                 'print("读数")\n', True, id="stderrOnlyStillBare"),
    pytest.param('"""这里以后要补 reconfigure 的说明文字"""\nimport sys\nprint("读数")\n',
                 True, id="mentionInTextIsNotAPin"),
])
def test_pinPredicateAcceptsExistingShapesAndStillCatchesFakeOnes(source, expectBare):
    """谓词宽到认三种写法，但不宽到把"只钉 stderr／只在文字里提一句"放行。"""
    assert bool(_nonAsciiPrintLines(source)) is True, "样本里那句 print 没被认出来，判据在空转"
    assert (not pinsStdoutStream(source)) is expectBare, (
        "谓词分类与实状不符（期望裸奔=%s）：%s" % (expectBare, source[:80]))
