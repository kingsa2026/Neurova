# -*- coding: utf-8 -*-
r"""安装门读数面的"代码形态"分类单点（§6-259 末格「读数面仍欠的一刀」）。

为什么要有这个模块：`dangerous_exec` 那条规则在 §6-259 从 `\b(exec|eval|compile)\s*\(` 收窄成
只判**裸名调用**，此后"一条读数到底是真动态编译还是 `re.compile(` 属性调用"必须由**证据行**判，
不能由 (后缀, 规则 id) 的计数判——旧计数面把 26 条正则预编译与 1 条真 `compile(` 给出同一个绿。
两档判据都要用这套形状判定（一档走扫描器对象面，一档走装载门发给调用方的那份 dict），
各抄一份针＝两条可独立漂移的口径（教义第 6 条），所以收在这里。

**分类器刻意不看被测规则**。要问的是"这一行里那个 exec/eval/compile 是裸名调用还是属性调用"，
这是代码结构问题，用 `ast` 判（`Call.func` 是 `Name` 还是 `Attribute`）；如果拿被测规则的
pattern 去分类，规则一旦改宽，误判产生的读数会被分类器认成"真形态"，那格就跟着误判一起绿——
判据与被判对象共享同一个偏见，等于没判。规则的 pattern 只用在另一问上：**这条读数能不能在它
自己的证据行上复算出来**（`execRule(...).severityFor(evidence)`），两问各自独立。

属性调用的正则针（`ATTRIBUTE_CALL_SHAPE`）只在证据行**不是完整可解析的 Python** 时兜底
（截断的证据、非 .py 文件里的命中）。它本身由 `test_shapeNeedlesSeparateTheTwoForms` 钉住
在两个样本上给出相反答案，防"针打空却被读成判据没牙"（形态集 220）。
"""
from __future__ import annotations

import ast
import re
from typing import Iterable, List

from neurova.security.skill_scanner import (
    Finding, PatternAnalyzer, ScanPolicy, ScanRule, SkillScanner, isBlocking)
from tests.ast_scan import parseSource

EXEC_RULE_ID = "dangerous_exec"
DYNAMIC_NAMES = frozenset({"exec", "eval", "compile"})

#: 属性调用形态：`re.compile(`／`cursor.exec(`／`obj.eval(`。仅作**兜底针**用，见模块头。
ATTRIBUTE_CALL_SHAPE = re.compile(r"\w\.\s*(?:exec|eval|compile)\s*\(")


def execRule(scanner: SkillScanner | None = None) -> ScanRule:
    """取生产装配面上那条 `dangerous_exec` 规则本体。

    传 `scanner`（门那台装配）⇒ 读的就是它真正在用的规则表；不传时只建 `PatternAnalyzer`
    这张表本身，不起整台扫描器（扫描器带缓存与落盘面，判据不该为拿一条规则惊动它）。
    """
    analyzers = (list(scanner.analyzers) if scanner is not None else [PatternAnalyzer()])
    for analyzer in analyzers:
        if isinstance(analyzer, PatternAnalyzer) and EXEC_RULE_ID in analyzer.rules:
            return analyzer.rules[EXEC_RULE_ID]
    raise AssertionError(
        "扫描器装配面上取不到 dangerous_exec 规则 ⇒ 本格失去根据，去查规则表而不是改断言")


def callShapesInLine(line: str) -> dict:
    """按 AST 数这一行里的动态调用形态：`{"bare": n, "attribute": m}`。

    `bare`＝`Call.func` 是裸名 `exec/eval/compile`（真动态执行）；
    `attribute`＝`Call.func` 是 `X.compile(...)` 这类属性调用（不经内置动态执行）。
    解析不了就返回 `None`——调用方据此走兜底针，而不是把"看不见"读成"没有"。
    """
    try:
        tree = parseSource(line)
    except SyntaxError:
        return None
    bare = attribute = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id in DYNAMIC_NAMES:
            bare += 1
        elif isinstance(func, ast.Attribute) and func.attr in DYNAMIC_NAMES:
            attribute += 1
    return {"bare": bare, "attribute": attribute}


def classifyEvidence(evidence: str) -> str:
    """这一行的形态类别：`bare`／`attribute`／`both`／`other`／`unparsed`。

    先看 AST；AST 看不见（证据被截断、非完整语句）时才用兜底针，且兜底针只能给出
    `attribute`/`other`——它判不出裸名，判不出就不冒充 `bare`（保守：宁可 `other`）。
    """
    line = str(evidence or "")
    shapes = callShapesInLine(line)
    if shapes is None:
        return "attribute" if ATTRIBUTE_CALL_SHAPE.search(line) else "unparsed"
    if shapes["bare"] and shapes["attribute"]:
        return "both"
    if shapes["bare"]:
        return "bare"
    if shapes["attribute"]:
        return "attribute"
    return "other"


def execReadings(findings: Iterable) -> List[dict]:
    """把 `dangerous_exec` 读数收成 dict 面（既收 `Finding` 也收 `to_dict()` 出来的载荷）。"""
    out = []
    for f in findings:
        if isinstance(f, dict):
            if f.get("rule_id") == EXEC_RULE_ID:
                out.append(f)
        elif f.rule_id == EXEC_RULE_ID:
            out.append(f.to_dict())
    return out


def shapesOf(findings: Iterable) -> dict:
    """逐条读证据行分类 ⇒ `{shape: [读数…]}`。计数是副产物，条目本身要能被点名。"""
    buckets: dict = {}
    for payload in execReadings(findings):
        buckets.setdefault(classifyEvidence(payload.get("evidence")), []).append(payload)
    return buckets


def isAttributeOnly(evidence: str) -> bool:
    """这一行**只有**属性调用形（没有任何裸名动态调用）——旧规则误判的就是这一类。"""
    shapes = callShapesInLine(str(evidence or ""))
    if shapes is not None:
        return shapes["attribute"] > 0 and shapes["bare"] == 0
    return bool(ATTRIBUTE_CALL_SHAPE.search(str(evidence or "")))


def unReproducible(readings: Iterable[dict], rule: ScanRule) -> List[dict]:
    """在生产规则自己的证据行上复算不出来的读数（读数与证据脱节那一类）。"""
    return [f for f in readings if rule.severityFor(str(f.get("evidence") or "")) is None]


def blockingFromPayloads(payloads: Iterable[dict],
                         policy: ScanPolicy = ScanPolicy.DENY) -> List[Finding]:
    """装载侧 dict 面**用生产谓词**判参与裁决的条目。

    dict 里丢掉的只是对象身份，字段一个不少 ⇒ 回填成 `Finding` 再交给 `isBlocking`，
    而不是在测试里再写一遍 `severity in ("critical", "high")`（那份名单在生产只有一处：
    `BLOCKING_SEVERITIES`）。默认 DENY 与安装门一致，前提由调用方那格钉着。
    """
    fields = set(Finding.__dataclass_fields__)
    out: List[Finding] = []
    for payload in payloads:
        finding = Finding(**{k: v for k, v in payload.items() if k in fields})
        if isBlocking(finding, policy):
            out.append(finding)
    return out
