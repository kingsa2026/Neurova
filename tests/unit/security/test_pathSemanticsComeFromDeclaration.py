# -*- coding: utf-8 -*-
r"""丁：路径语义由**声明**决定，名字表降为"没有声明时"的兜底（§6-284 末态，用户 2026-10-17 拍丁）。

改前实状（真引擎现读，探针即用即删，工具名按运行时注册表 `_BUILTIN_SCHEMAS` 定名——不用行号）：
    registry 73 只内置工具，其中 11 个属性名就是路径语义：
        exec_command.workdir、file_{create,delete,edit,parse,read,write}.file_path、
        file_list.path、file_search.path、git.path、write_pdf.path
    `{"workdir": "/etc/shadow"}`                      -> ['protected_path']   ← **偶然**：回落正则
        （`(?:path|file|dir)=` 把 `workdir=` 里的子串 `dir=` 咬住了）
    `{"workdir": "/etc/shadow", "file_path": 良性}`   -> []                   ← **放行**：回落只在
        "参数面一个路径值都没取到"时才跑，清单内键一出现，workdir 就彻底消失
    `{"workdir": r"C:\Program Files\Foo"}`            -> []                   ← 回落按空格截断，
        只取到 `C:\Program`，配不上 `c:\program files` 前缀；同值给 `path` 键则报
⇒ 第一方真实漏名是 `exec_command.workdir`：它**不在 `PATH_NAME_ROLES` 的任何角色里**。
甲案修不到它（甲只在"已登记的名字"范围内把取数做可信）；扩清单能修，但那是"加一个名字修一次"；
丁把"这个参数是不是路径"的判定权交回**声明方**——以后新工具、远端工具声明即生效，守卫不必再认键名。

为什么"按形状判"不行（这条决定了本票的形态）：`looksLikePathValue` 只要求整串含 `/` 或 `\`，
`"见 /etc/shadow"` 照样过。于是"声明过的 string 参数、值长得像路径就按路径判"＝把 §6-284 甲明确
拒掉的 case 4（自由文本）放回来。**声明说了算，形状不参与裁决。**

兜底刻意保留（保守一侧不许放宽）：远端/MCP 工具的 schema 不一定会声明，未声明时仍按名字表判——
这一条由第 5 格钉着，别把它当成"丁没做完"；把兜底删掉的后果是远端工具的路径参数从此无人看。

名字表从此只关不加（第 8 格）：往 `PATH_NAME_ROLES` 里添一个名字就红——要新增语义，请在声明里写。
"""

from __future__ import annotations

import ast
import io
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from neurova.builtin_tools import get_builtin_tool_params
from neurova.security.governance import get_governance
from neurova.security.tool_guard import ToolGuardEngine

#: 声明约定本身的取值——测试侧常量，不 import 生产侧的新符号（否则红会退化成 ImportError）。
DECLARED_FORMAT = "path"
#: 声明的唯一读者应有的函数名（同样只作字符串比对，不 import）。
PATH_READER = "pathValuesForTool"

SAFE = "/home/agent/workspace/readme.txt"
SHADOW = "/etc/shadow"
PROGRAM_FILES = r"C:\Program Files\Foo"

#: 运行时注册表现读的 11 个"按语义就是路径"的属性（下限清单；掉出去即红，防 schema 被手改漏声明）。
PATH_BEARING_PARAMS = [
    ("exec_command", "workdir"),
    ("file_create", "file_path"),
    ("file_delete", "file_path"),
    ("file_edit", "file_path"),
    ("file_list", "path"),
    ("file_parse", "file_path"),
    ("file_read", "file_path"),
    ("file_search", "path"),
    ("file_write", "file_path"),
    ("git", "path"),
    ("write_pdf", "path"),
]


def ruleIds(toolName: str, params: dict) -> list:
    return [f.rule_id for f in ToolGuardEngine().guard(toolName, params).findings]


def evidencesOf(toolName: str, params: dict, ruleId: str) -> list:
    return [f.evidence for f in ToolGuardEngine().guard(toolName, params).findings
            if f.rule_id == ruleId]


def declaredFormat(toolName: str, param: str):
    schema = get_builtin_tool_params(toolName) or {}
    props = (schema.get("parameters") or {}).get("properties") or {}
    return (props.get(param) or {}).get("format")


class TestDeclarationDrivesJudgment:
    def testDeclaredWorkdirIsJudgedBesideAListedPathKey(self):
        """本票主红：`workdir` 不在名字表里，同一次调用出现清单内键时它今天就消失了。"""
        found = evidencesOf("exec_command", {"workdir": SHADOW, "file_path": SAFE}, "protected_path")

        assert SHADOW in found, (
            f"声明为路径的参数仍因'旁边有清单内键'而不被查：{found}——丁要修的正是这一形")

    def testDeclaredWorkdirKeepsItsWholeValue(self):
        """第二枚主红：声明取到的必须是**整值**，不许再被空格的形状猜短。"""
        alone = ruleIds("exec_command", {"workdir": PROGRAM_FILES})
        viaListed = ruleIds("file_list", {"path": PROGRAM_FILES})

        assert "windows_system_path" in viaListed, f"对照那一支自己就不成立了：{viaListed}"
        assert "windows_system_path" in alone, (
            f"带空格的声明值被按空格切短了（回落那支的老形状），同一份字节两种判法：{alone}")

    def testEveryPathBearingBuiltinParamDeclaresItself(self):
        """声明完整性的下限格：注册表里 11 个路径语义属性，缺一个声明就红。"""
        missing = [(t, p) for t, p in PATH_BEARING_PARAMS
                   if declaredFormat(t, p) != DECLARED_FORMAT]

        assert not missing, (
            f"{len(missing)}/{len(PATH_BEARING_PARAMS)} 个路径语义参数没有声明自己是路径：{missing}"
            "——守卫读不到声明就只能回名字表兜底，丁等于没落地")

    def testDeclaredParamsAreJudgedThroughTheGovernanceRoute(self):
        """在路上的证明：生产唯一入口是 `evaluate_tool_call`，不是直调 guardian。"""
        verdict = get_governance().evaluate_tool_call(
            "exec_command", {"workdir": SHADOW, "file_path": SAFE, "command": "ls"})

        assert verdict is not None and verdict.decision.name != "ALLOW", (
            f"经真预检走一遍，声明为路径的 workdir 仍然放行：{verdict and verdict.decision.name}")


class TestUndeclaredCallersKeepTheNameTable:
    """兜底不许顺手删：远端/动态工具的 schema 不一定声明，未声明时仍按名字表判。"""

    def testUnregisteredToolIsStillJudgedByNameTable(self):
        ids = ruleIds("mcp.srv.fetch", {"path": SHADOW})

        assert "protected_path" in ids, (
            f"没有 schema 的工具名，路径参数从此无人看——兜底被删了：{ids}")

    def testFreeTextKeyHoldingAPathStaysUnjudged(self):
        """case 4 反向钉：形状会把它判成路径，声明不会——这正是丁的形状边界。"""
        ids = ruleIds("file_read", {"file_path": SAFE, "note": f"见 {SHADOW}"})

        assert ids == [], f"自由文本键开始被当路径判（改前改后都该是空）：{ids}"

    @pytest.mark.parametrize("toolName,param", PATH_BEARING_PARAMS[:4])
    def testSingleDeclaredPathCallStillJudged(self, toolName, param):
        """对照：单路径调用的读数不许因引入声明而变松。"""
        ids = ruleIds(toolName, {param: SHADOW})

        assert "protected_path" in ids, f"{toolName}.{param} 单给就不报了：{ids}"


class TestTheNameTableIsClosingDown:
    """两枚收口形状格：表只关不加；声明的解释处只有一处。"""

    def testNameTableGainsNoMoreNames(self):
        from neurova.security.tool_guard import PATH_NAME_ROLES

        assert len(PATH_NAME_ROLES) <= 9, (
            f"`PATH_NAME_ROLES` 长到 {len(PATH_NAME_ROLES)} 个名字了——新增语义请写进 schema 的声明，"
            "往名字表里加名字就是绕开丁")

    def testDeclarationIsInterpretedInExactlyOnePlace(self):
        """声明只有一个读者：取数口一处定义，而 guardian 自己不许再去读 `format`。

        （第一版这格是按键名 `"format"` 全仓扫，被三处无关同名字段自咬——`media/config.py`、
        `neurflow/drama_nodes.py`、`security/arg_grounding.py` 各读各的 `format`，红得没有意义。
        改成钉代码形态：定义数＋调用位置。）
        """
        definitions, guardianReadsFormat = [], False
        for path in REPO.glob("neurova/**/*.py"):
            try:
                tree = ast.parse(io.open(path, encoding="utf-8").read(), filename=str(path))
            except (SyntaxError, UnicodeDecodeError):
                continue
            rel = path.relative_to(REPO).as_posix()
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name == PATH_READER:
                    definitions.append(rel)
                if (isinstance(node, ast.ClassDef) and node.name == "FilePathGuardian"):
                    for sub in ast.walk(node):
                        if isinstance(sub, ast.Subscript) and isinstance(sub.slice, ast.Constant) \
                                and sub.slice.value == "format":
                            guardianReadsFormat = True

        assert len(definitions) == 1 and definitions[0] == "neurova/security/tool_guard.py", (
            f"`{PATH_READER}` 的实装应全仓一处且在 tool_guard，实得 {definitions}"
            "——两处解释声明迟早给出两个答案")
        assert not guardianReadsFormat, (
            "FilePathGuardian 自己去读 format 了——声明必须由引擎算一次交下来，"
            "否则名字表与声明两套读法并存")
