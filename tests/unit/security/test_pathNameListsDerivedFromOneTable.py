# -*- coding: utf-8 -*-
r"""「哪些参数名算路径」收成一份事实源：三份名单各自的答案必须从同一处派生（§6-284 第②刀前半）。

复核实状（真入口现读，不是读代码猜）：同一个问题今天有三份字面、三个答案——
① `tool_guard.PATH_PARAM_KEYS = ("file_path", "path")` —— 值从参数面按键名取来扫路径面，
   也决定"剔除出命令面"的那一侧（§6-266 第①刀的裁定）；
② `tool_guard.py` 回落正则 `r"(?:path|file|dir)=([^\s]+)"` —— 只在 ① 一支取不到时才跑；
③ `tool_param_guard.UNAMBIGUOUS_ALIASES`（filename/filepath/filePath/file_name/fileName → file_path）
   与 `SCHEMA_REQUIRED_ALIASES` 里指向 file_path 的那两个（path/file）。

可测后果（本会话实测，见 `testDivergenceMatrixIsExactlyTheRegisteredOne`）：拿一个带 `\xHH` 形状的
无害路径当值——正是 §6-255 那族的触发条件——**12 个路径语义的名字里只有 ① 那两个**不进命令扫描面，
其余 10 个各出一条 `shell_十六进制编码`。
`_build_command_surface` 的 docstring 自己写着"没登记进任何一把清单的键一律照命令面扫（那是仍然
保守的那一侧）"——所以这不是 bug 现场，是**没拍的那一刀**。

本批因此**只做一件事**：把三份字面收成一处派生，**不改任何裁决语义**（不扩表、不缩表、不改正则行为）。
"到底该按哪张表判"（丁·按 schema 判 vs 甲·扩清单）留给下一批拍；这批的价值是把分歧从"三处静默
各写一份"变成"一处声明＋一格会红的读数"，谁只改一张表，本档当场红。
"""

from __future__ import annotations

import ast
import io
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from neurova.security import tool_guard, tool_param_guard  # noqa: E402
from neurova.security.tool_guard import (  # noqa: E402
    GuardThreatCategory, ToolGuardEngine)
from tests.ast_scan import parseSource

EVASION = GuardThreatCategory.SHELL_EVASION

#: 触发值自己把 `\xHH` 形状写进档名，**不向操作者的用户名借**。
#: 早先这一格取 `Path.home()/…`，本机 `C:\Users\xccoo\…` 里那个 `\xcc` 恰好点火——家目录换成
#: `/home/runner` 就没有反斜杠，10 格会从"报一条"变成"什么都不报"，收进子集即成一条只在异机红
#: 的常驻红（形态集 239 的反向：取值没落在分歧点上）。现取值经探针实证：同一条矩阵在
#: Windows 家目录、临时目录、`/var/tmp` 三种形状下逐名一致。
#: 值不必真实存在——这一族判据问的是"这个键的值进不进命令扫描面"，不碰文件系统。
SAFE_PATH = r"/var/tmp/neurova_b62/readme\x41.txt"

#: 12 个"看起来都该算路径"的名字：清单 2 ＋ 正则字面 2 个额外的 ＋ 别名表 5 ＋ 现场还常见的 3 个。
PATHISH_NAMES = ("file_path", "path", "dir", "file", "filename", "filepath", "filePath",
                 "file_name", "fileName", "output_path", "src", "destination")

#: 探测器侧的规范名常量。同样不向被测对象借（理由见 `_secondLiteralOffenders` 的注释）。
CANONICAL = "file_path"

#: 登记的实状：命令面读数（rule_id 列表）随键名翻转。**收名单不许动它**，动它要先过下一批的拍板。
REGISTERED_COMMAND_FACE = {
    "file_path": [], "path": [],
    "dir": ["shell_十六进制编码"], "file": ["shell_十六进制编码"],
    "filename": ["shell_十六进制编码"], "filepath": ["shell_十六进制编码"],
    "filePath": ["shell_十六进制编码"], "file_name": ["shell_十六进制编码"],
    "fileName": ["shell_十六进制编码"], "output_path": ["shell_十六进制编码"],
    "src": ["shell_十六进制编码"], "destination": ["shell_十六进制编码"],
}


def _evasionRules(toolName: str, params: dict) -> list:
    return [f.rule_id for f in ToolGuardEngine().guard(toolName, params).findings
            if f.category == EVASION]


class TestThreeViewsComeFromOneTable:
    """三份答案必须是一处声明的三个投影——改一处就三处一起动，只改一处即红。"""

    def testSourceTableExistsAndRolesAreDeclared(self):
        roles = tool_guard.PATH_NAME_ROLES
        assert isinstance(roles, dict) and roles, "单源表不在场，三份名单还是各写各的"
        for name, role in roles.items():
            assert set(role) <= {"scanned", "textual", "alias_plain", "alias_gated"}, (
                f"{name} 的角色集有没登记的取值：{role}——加角色要先改这张表的口径")

    def testEachViewIsTheTableProjectionNotItsOwnLiteral(self):
        """三张派生视图逐项等值（含**顺序**：清单顺序决定取哪条，§6-284 第①条实测）。"""
        assert tool_guard.PATH_PARAM_KEYS == tool_guard.pathNamesWithRole("scanned"), (
            "清单不再是从单源表派生的了——它自己长回了字面量")
        assert tuple(tool_guard.PATH_PARAM_KEYS) == ("file_path", "path"), (
            f"收名单顺手改了裁决面（清单变成 {tool_guard.PATH_PARAM_KEYS}）——那属于下一批的拍板")

        alternation = re.findall(r"\(\?:([^)]*)\)", tool_guard.PATH_VALUE_PATTERN.pattern)[0]
        assert alternation.split("|") == list(tool_guard.pathNamesWithRole("textual")), (
            f"回落正则的字面键 {alternation!r} 不再等于单源表的 textual 角色集"
            "⇒ 两张表又开始各走各的")

        plain = tuple(tool_param_guard.UNAMBIGUOUS_ALIASES)
        assert plain == tuple(tool_guard.pathNamesWithRole("alias_plain")), (
            f"无歧义别名表 {plain} 与单源表的 alias_plain 不一致")
        assert all(v == tool_guard.PATH_CANONICAL_NAME for v in tool_param_guard.UNAMBIGUOUS_ALIASES.values()), (
            "别名目标不再统一指向规范名——那张表里混进了非路径别名，口径就不是一份了")
        gated = [k for k in tool_param_guard.SCHEMA_REQUIRED_ALIASES
                 if tool_param_guard.SCHEMA_REQUIRED_ALIASES[k] == tool_guard.PATH_CANONICAL_NAME]
        assert gated == list(tool_guard.pathNamesWithRole("alias_gated")), (
            f"需 schema 背书的路径别名 {gated} 不再由单源表决定")

    #: 唯一出处按 **AST 身份**认（赋给这些名字的表达式豁免），不按文件名、不按词——
    #: 否则单源表自己会被自己的守卫咬（形态集 223），而"给文件开口子"又是下一个漂移的入口。
    _ALLOWED = ("PATH_NAME_ROLES", "PATH_PARAM_KEYS", "COMMAND_PARAM_KEYS")

    def _assignedValues(self, tree) -> dict:
        """模块级"名字 → 被赋的表达式"。两种写法都要认：`X = …` 与 `X: T = …`（AnnAssign）——
        只认前者，别名表那两处带类型标注的声明会**静默掉出扫描面**，探测器与形状格一起变瞎。"""
        out = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                out.setdefault(node.targets[0].id, node.value)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
                out.setdefault(node.target.id, node.value)
        return out

    def _secondLiteralOffenders(self, source: str, where: str) -> list:
        tree = parseSource(source, filename=where)
        allowed = {id(v) for name, v in self._assignedValues(tree).items() if name in self._ALLOWED}
        #: 别名表的形状是"若干路径名 → 规范名"，键名宇宙取**本档自己的登记表** `PATHISH_NAMES`，
        #: 不向被测对象借那张表：借了之后表一不在场，这一格就从"点名抄本"的行为红退化成
        #: `AttributeError`（形态集：红要看形状，跑都没跑成的红抓不住东西）。
        #: 值必须真的指向规范名——只按键名判会把**工具调用的入参**读成第二份定义：生产面 1020 档之外
        #: 再扫测试面时，第一条撞出来的就是 `test_tool_param_guard.py:66` 那个
        #: `{"filename": "a", "filepath": "b", "cmd": "ls"}`，那是被测数据，不是又一份口径。
        universe = set(PATHISH_NAMES) | {CANONICAL}
        out = []
        for node in ast.walk(tree):
            if id(node) in allowed:
                continue
            if isinstance(node, (ast.Tuple, ast.List)):
                elts = [e.value for e in node.elts if isinstance(e, ast.Constant)]
                if len(elts) >= 2 and CANONICAL in elts and "path" in elts:
                    out.append(f"{where}:{node.lineno} 抄了一份路径键清单")
            elif isinstance(node, ast.Dict):
                keys = [k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)]
                vals = [v.value for v in node.values if isinstance(v, ast.Constant)]
                if len([k for k in keys if k in universe]) >= 2 and CANONICAL in vals:
                    out.append(f"{where}:{node.lineno} 抄了一份路径别名表")
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                if re.search(r"\(\?:[a-z_]+(\|[a-z_]+)*\)=\(", node.value):
                    out.append(f"{where}:{node.lineno} 又写了一份回落正则字面")
        return out

    def testNoSecondLiteralOfTheseNamesAnywhere(self):
        """教义第 6 条：这些字面只许出现在唯一出处（AST 判身份，注释里提到不算违规）。

        扫描面是**整个 `neurova/` 生产面**（本轮现量 1020 档已跟踪 .py，命中 0 条），不限
        `neurova/security/`——"哪些名字算路径"的第二份答案今天可能在 `tools/` 或 `agent/` 里
        长出来并把裁决带走，把面圈在自家目录等于不去看别人会不会抄。
        测试档不在面内：那里的同形字面是**被测数据与本档自己的登记表与合成样本**
        （`PATHISH_NAMES` 是一份刻意列全的名单、探测器要有牙就必须在样本里重写一遍那三形），
        把它们豁免进去只会把口子交给后来的抄写者。
        """
        offenders = []
        for rel in _productionPy():
            offenders += self._secondLiteralOffenders(
                io.open(REPO / rel, encoding="utf-8").read(), str(rel))
        assert not offenders, "路径键名/别名的第二份定义又长出来了：\n  " + "\n  ".join(offenders)

    def testDetectorBitesASyntheticSecondCopy(self):
        """探测器三形各该点一次；同时按"被测数据"那一形不许咬（否则全仓扫的命中面是假的）。"""
        sample = (
            "PATH_KEYS_COPY = ('file_path', 'path')\n"
            "ALIASES_COPY = {'filename': 'file_path', 'filepath': 'file_path'}\n"
            "PATTERN_COPY = r'(?:path|file|dir)=([^\\s]+)'\n")
        hits = self._secondLiteralOffenders(sample, "synthetic.py")

        assert len(hits) == 3, f"三形各该点一次，实得 {hits}"

        fixture = ('params = {"filename": "a", "filepath": "b", "cmd": "ls"}\n'
                   'assert params == {"file_path": "a", "filepath": "b", "cmd": "ls"}\n')
        assert self._secondLiteralOffenders(fixture, "callSite.py") == [], (
            "工具调用的入参被读成了第二份定义——命中面一旦掺进被测数据，"
            "全仓扫出来的红就没人当真了")

    #: 四个视图名 → 各自所在文件。等值比对拦不住"派生被换成同值字面"（值一样，格照样绿），
    #: 所以这一格按 **AST 形状**判：赋给这些名字的表达式里必须真的调用了 `pathNamesWithRole`。
    _VIEWS = {
        "neurova/security/tool_guard.py": ("PATH_PARAM_KEYS", "PATH_VALUE_PATTERN"),
        "neurova/security/tool_param_guard.py": ("UNAMBIGUOUS_ALIASES", "SCHEMA_REQUIRED_ALIASES"),
    }

    def testEachViewIsStillADerivedShape(self):
        """收口之后不许悄悄长回字面：视图的**来源形状**也得是派生，不只是今天值相等。"""
        for rel, viewNames in self._VIEWS.items():
            fails = self._viewShapeFailures(
                io.open(REPO / rel, encoding="utf-8").read(), rel, viewNames)
            assert not fails, "\n  ".join(fails)

    def _viewShapeFailures(self, source: str, where: str, viewNames) -> list:
        tree = parseSource(source, filename=where)
        values = self._assignedValues(tree)
        out = []
        for view in viewNames:
            value = values.get(view)
            if value is None:
                out.append(f"{where}:{view} 不再被赋值——那份名单换了落点")
                continue
            called = {n.func.id for n in ast.walk(value)
                      if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
            called |= {n.func.attr for n in ast.walk(value)
                       if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
            if "pathNamesWithRole" not in called:
                out.append(f"{where}:{view} 不再是单源表的投影（调用了 {sorted(called)}）"
                           "——它长回了字面量；今天值相等所以别的格看不见它，改表那天它静默不跟")
        return out

    def testShapeDetectorBitesBothAssignmentForms(self):
        """形状探测器双向要有牙：同值字面必须被点名，带类型标注的派生声明不许掉出扫描面。

        后一半不是装饰——本批第一版探测器只认 `ast.Assign`，而两份别名表声明写的是
        `X: Dict[str, str] = …`（AnnAssign），于是"不再被赋值"假红一条；只认一种写法，
        改天谁把派生换成带标注的字面，这一族就静默瞎掉。
        """
        literal = "PATH_PARAM_KEYS = ('file_path', 'path')\n"
        annotated = (
            "PATH_PARAM_KEYS: tuple = pathNamesWithRole('scanned')\n"
            "SCHEMA_REQUIRED_ALIASES: Dict[str, str] = "
            "{**{n: 'file_path' for n in pathNamesWithRole('alias_gated')}, 'cmd': 'command'}\n")

        assert len(self._viewShapeFailures(literal, "lit.py", ("PATH_PARAM_KEYS",))) == 1, (
            "同值字面没被点名——形状判据是空转的")
        assert self._viewShapeFailures(
            annotated, "ann.py", ("PATH_PARAM_KEYS", "SCHEMA_REQUIRED_ALIASES")) == [], (
            "带标注的派生声明被判成'不再被赋值'——AnnAssign 掉出了扫描面")


class TestTheRegisterdDivergenceStaysPinned:
    """分歧不许被"收名单"顺手抹平，也不许悄悄扩大——它是下一批拍板的事实底座。"""

    @pytest.mark.parametrize("name", PATHISH_NAMES)
    def testDivergenceMatrixIsExactlyTheRegisteredOne(self, name):
        """两态各跑一次真入口（形态集 249：只看列表会把"随上下文翻转"读成"都覆盖"）。"""
        alone = _evasionRules("file_read", {name: SAFE_PATH})
        withHarmless = _evasionRules("file_read", {name: SAFE_PATH, "timeout": 30})
        expected = REGISTERED_COMMAND_FACE[name]

        assert alone == expected, f"{name} 单给：实得 {alone}，登记 {expected}"
        assert withHarmless == expected, (
            f"{name} 加一条同族无害键后答案变了（{alone} → {withHarmless}）——"
            "同一份输入两次调用判成不同东西，这本身就是缺陷读数")

    def testFallbackOnlyRunsWhenTheListMisses(self):
        """钉住今天"清单优先、取不到才回落"这条已实测语义（下一批改判时这格必须一起改判）。"""
        from neurova.security.tool_guard import FilePathGuardian

        engine = FilePathGuardian()
        # `dir` 不在清单里 → 只有回落那一支看得见它；给了清单键时回落不跑，取的是清单那一支。
        # 取值必须是路径面**会报**的形状（`/etc/passwd`）——拿良性路径来测，两态都空，格就恒真。
        viaFallback = engine.guard("dir=/etc/passwd", {})
        assert [f.rule_id for f in viaFallback] == ["protected_path"], (
            f"回落那一支不再工作（{[f.rule_id for f in viaFallback]}）：清单外的名字从此谁都看不见"
            "——收名单收成瞎了")
        both = engine.guard("dir=/etc/passwd", {"file_path": "/tmp/keep.txt"})
        assert not [f for f in both if f.rule_id == "protected_path"], (
            f"清单命中后回落还在跑（{[f.rule_id for f in both]}）——两条取数路同时生效，"
            "取哪条就不再是清单顺序说了算")


def _productionPy():
    from tests import ast_scan

    return [rel for rel in sorted(ast_scan.trackedPyPaths())
            if str(rel).replace("\\", "/").startswith("neurova/")]

