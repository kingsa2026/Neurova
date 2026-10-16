r"""shell 逃逸检测只剩一张表（§6-266 末格第③刀，用户点单按"比→并→接→退"收）。

复核实状（现读，不抄台账）：`ShellEvasionGuardian` 除主表 `_evasion_patterns` 外还挂着两个 helper——
`_has_command_substitution`（`$()`／反引号／`<()`）与 `_has_encoding_evasion`（base64 -d／`\xNN`／`\uNNNN`）。
两条都在全仓**零调用**（现查文件内出现次数＝定义行本身），内容是主表的一份影子，唯独
`\u[0-9a-fA-F]{4}` 这条**为它们独有**——主表没有。这就是 §6-266 记下的"全仓唯一实装"那一格：
静默删掉就是永久失去这条检测，所以走教义第 7 条的固定顺序：先比（下面第一条格把逐条覆盖关系钉住）、
再并（把独有条并进主表，严重度取齐同族 `\xNN` 的 HIGH）、再退（删掉两个 helper）。

**并进来之后这条真的开始参与裁决**——此前它无人调用，等于不存在。这是能力落地，也是新增的一处 ASK 摩擦；
取 HIGH 而不是 low 的理由是同族三条（`$()`／反引号／`\xNN`／base64）全是 HIGH，分叉成两档就是新造口径。

第四格钉的是这次并动之所以安全的根据：§6-266 第①刀换向后，**路径键的值不再进命令面**，
于是 `C:\Users\u1234\…` 这种"分隔符 + u + 四位十六进制"不会再被读成转义——也就是 §6-255 那条缺陷
在同一族规则上的复发面，被那一刀的换向挡住了。这一格今天就该绿，它守的是"别把修好的病带回来"。
"""
from __future__ import annotations

import ast
import pathlib

from neurova.security.tool_guard import (
    GuardThreatCategory, ShellEvasionGuardian, ToolGuardEngine)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
GUARD_FILE = REPO_ROOT / "neurova" / "security" / "tool_guard.py"
EVASION = GuardThreatCategory.SHELL_EVASION
RETIRED_HELPERS = ("_has_command_substitution", "_has_encoding_evasion")

#: 退役 helper 原来覆盖的六种形状，逐条给一个样本串（并入主表后一条都不许掉）。
SHAPES = {
    "命令替换 $()": "echo $(id)",
    "反引号替换": "echo `whoami`",
    "进程替换 <()": "diff <(sort a) <(sort b)",
    "base64 解码": "echo Y2F0IC9ldGMvcGFzc3dk | base64 -d",
    "十六进制转义": r"""python -c 'print("\x41\x42")'""",
    "Unicode 转义": r"""python -c 'print("\u4142")'""",
}


def evasionFindings(toolName: str, params: dict) -> list:
    return [f for f in ToolGuardEngine().guard(toolName, params).findings
            if f.category == EVASION]


def test_eachRetiredShapeIsStillCaught():
    r"""比＋并：六种形状逐条钉住"主表这张脸抓得到"，少一条就是并的时候掉了覆盖。"""
    for label, command in SHAPES.items():
        findings = evasionFindings("run_command", {"command": command})
        assert findings, f"形状「{label}」在主表里抓不到了（{command!r}）⇒ 退役会连带丢能力"


def test_unicodeEscapeRuleIsNowOnTheMainTable():
    r"""并的落点：`\uNNNN` 这条从影子表进主表，且与同族 `\xNN` 同severity（不分叉成两档口径）。"""
    patterns = {p.pattern: (sev, desc) for p, sev, cat, desc in
                ShellEvasionGuardian()._evasion_patterns}
    unicodeRule = [(sev, desc) for pat, (sev, desc) in patterns.items() if "u[" in pat]
    assert len(unicodeRule) == 1, (
        f"主表里该有一条 Unicode 转义规则，现读 {unicodeRule}——没有就是这条能力随退役消失了")
    hexRule = [(sev, desc) for pat, (sev, desc) in patterns.items() if "x[0-9a-fA-F]" in pat]
    assert unicodeRule[0][0] == hexRule[0][0], (
        f"同族转义规则严重度分叉：u={unicodeRule[0][0]} x={hexRule[0][0]}")

    findings = evasionFindings("run_command", {"command": SHAPES["Unicode 转义"]})
    assert findings and findings[0].severity.value == "high", (
        f"命令里的 `\\u4142` 没被判成 high：{[(f.rule_id, f.severity.value) for f in findings]}")


def test_retiredHelpersAreGoneFromTheGuardian():
    r"""退：两个零调用 helper 不得还挂在 guardian 上（按 AST 判代码身份，不按词 grep）。

    按词判会被自家注释与文档撞红（本仓这一形跑过两遭）；这里只看 `ShellEvasionGuardian`
    类体里的 `FunctionDef.name`——名字在这里就是被退役符号的身份，不是措辞。
    """
    tree = ast.parse(GUARD_FILE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "ShellEvasionGuardian":
            alive = [f.name for f in node.body
                     if isinstance(f, ast.FunctionDef) and f.name in RETIRED_HELPERS]
            assert not alive, (
                f"ShellEvasionGuardian 还带着第二份逃逸判定：{alive}——同一功能两处实现，"
                "改一处另一处静默不跟（教义第 6/7 条）")
            return
    raise AssertionError("找不到 ShellEvasionGuardian 类——本档的扫描面变了，去查而不是关掉判据")


def test_unicodeShapeInsideAPathKeyIsNotReadAsEscape():
    r"""复发面（今天就该绿）：路径键的值不进命令面，所以 `C:\Users\u1234\a;b.txt` 里的
    `\u1234` 不被读成转义——**这条同时把第①刀与第③刀咬在一起**。

    取值刻意带一个 `;`：第①刀落地前，豁免是"形状 + 不含 shell 字符"双闸，带 `;` 的值会被打回
    命令面，于是这条新进的 Unicode 规则就会在**路径**上复发 §6-255 那个病形。留一个 `;` 才是这一格
    该有的强度——只写一个干净路径的话，把豁免改回双闸也照样绿（本笔第一版就踩在这上面，
    变异 M4 打空被抓，见台账）。同时钉"审计那条要在"：放行不等于删读数。
    """
    pathValue = "C:\\Users\\u1234\\a;b.txt"

    findings = ToolGuardEngine().guard("file_read", {"file_path": pathValue}).findings
    assert not [f for f in findings if f.category == EVASION], (
        f"路径值里的 `\\u1234` 被读成 Unicode 转义（{[(f.rule_id, f.evidence) for f in findings]}）"
        "⇒ 第①刀的换向被改回双闸，并进主表的这条又把 §6-255 带回来了")
    assert [f for f in findings if f.rule_id == "path_with_shell_metacharacters"], (
        f"含 `;` 的路径值没留下审计读数 ⇒ 放行被写成静默丢弃：{[f.rule_id for f in findings]}")
