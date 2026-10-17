# -*- coding: utf-8 -*-
r"""路径守卫逐值扫＋命令文本总做——§6-284 甲案落地（用户 2026-10-17 裁甲）。

改前实状（真引擎现读，探针 `.tmp_b65_probe.py` 即用即删，七条读数逐字抄在这里）：

| 形状 | 改前 findings |
|---|---|
| `{"file_path":"/tmp/a.txt","path":"/etc/shadow"}` | `[]` ← **case 1：第二条路径从不被查** |
| `{"file_path":"/tmp/a.txt","command":"cat /etc/shadow"}` | `[]` ← **case 2：命令文本被"已找到 path"短路** |
| `{"command":"cat /etc/shadow"}`（对照） | `['protected_path_in_command']` ← 规则在册，零读数是早退造成的 |
| `{"file_path":"/tmp/a.txt","note":"见 /etc/shadow"}` | `[]` ← case 4，自由文本键，甲**不**覆盖 |
| `{"file":r"C:\Program Files\Foo\passwd"}` | `[]` ← **截断危害**：回落那支从扁串只取到 `C:\Program` |
| `{"path":r"C:\Program Files\Foo\passwd"}`（同值换 scanned 键） | `['windows_system_path']` ← 同一份字节，判成两个东西 |
| `{"file_path":"/tmp/a.txt","dir":"/etc/shadow"}` | `[]` ← 翻转形：回落只在没有 scanned 键时才跑 |

三处根因（教义第 1 条：修在生产该非法状态的地方，不在下游补判空）：
① `FilePathGuardian.guard` 的取数是「按 `PATH_PARAM_KEYS` 取到第一个非空值就 `break`」；
② 命令文本那一支挂在 `if not path:` 下面；
③ 回落那支从 `_build_tool_input` 的扁平整串里靠空格猜值边界（`[^\s]+`），带空格的路径被切短。
   `guard()` 手上本来就有那份 params dict——从 dict 取 textual 角色的名字，覆盖面一字不扩
   （名字集还是同一张 `PATH_NAME_ROLES` 的投影），改的是**取数可不可信**。

刻意不做的两件（免得下一个人顺手）：
- **不覆盖 case 4**（`note`/`target` 这类自由文本键里的路径）。把它做进去等于报"文本里出现了像路径
  的子串"而不是"有人要访问这个路径"——那是把守卫从"判形状"拖回"判词"，正是本路一批批在拆的形态。
  第 5 格反向钉着这条。
- **不扩名字表**。`source`/`destination` 这类没登记进任何角色的键照旧不判——那是丁（按 schema 判）
  的范围，本批不越过去。

去重口径（批 30 那族"同名不同源"的老坑，按归属去而不是按一个 seen 集合吞）：同一个值被两个键带着
只报一条（第 8 格）；而"按值判出来的 `protected_path`"与"按命令文本判出来的
`protected_path_in_command`"是**两个归属**，谁也不许替谁消失（第 9 格）。

同一根因的第二命中点在**治理预检**那一层（`TestThePrecheckDoesNotCollapseFirst` 四格）：
`governance.extract_adjudicable_params` 也写了一份自己的 `next(...)` 取数，一次调用带两条路径参数时
第二条在进守卫之前就已经消失——生产路上唯一的入口正是它（`tool_executor.py:1615` →
`evaluate_tool_call`）。只在咽喉里逐值扫而不动那一层，等于把修落在一条走不到的分支上；如今两侧共用
`pathValuesFromParams` 这一个口，键名清单不再有两份写法。
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

from neurova.security.tool_guard import FilePathGuardian, ToolGuardEngine

SAFE_PATH = "/home/agent/workspace/readme.txt"
SHADOW = "/etc/shadow"
PASSWD = "/etc/passwd"
ROOT_DIR = "/root/.ssh/id_rsa"
WIN_SYSTEM_FILE = r"C:\Program Files\Foo\passwd"


def ruleIds(toolName: str, params: dict) -> list:
    return [f.rule_id for f in ToolGuardEngine().guard(toolName, params).findings]


def evidencesOf(toolName: str, params: dict, ruleId: str) -> list:
    return [f.evidence for f in ToolGuardEngine().guard(toolName, params).findings
            if f.rule_id == ruleId]


class TestEveryPathValueIsJudged:
    def testSecondPathKeyIsNoLongerInvisible(self):
        """case 1 主红：两条路径参数都要被看见，且点名是哪一条命中的。"""
        ids = ruleIds("file_read", {"file_path": SAFE_PATH, "path": SHADOW})

        assert "protected_path" in ids, (
            f"第二条路径参数（`path`）从不被查——甲案要闭的就是这一格：{ids}")
        assert SHADOW in evidencesOf("file_read", {"file_path": SAFE_PATH, "path": SHADOW},
                                     "protected_path"), "命中读数没点名是哪一个值"

    def testBothOffendingValuesAreReported(self):
        """逐值扫的价值＝不止"第二个"，是**每一个**都判（两个都受保护就都得出读数）。"""
        params = {"file_path": PASSWD, "path": ROOT_DIR}
        found = evidencesOf("file_read", params, "protected_path")

        assert {PASSWD, ROOT_DIR} <= set(found), f"只判了其中一个：{found}"

    def testTruncatedWindowsPathIsJudgedWhole(self):
        """截断那一形的危害格：带空格的 Windows 系统目录路径，改前因为只取到 `C:\\Program` 而放行。"""
        ids = ruleIds("file_read", {"file": WIN_SYSTEM_FILE})

        assert "windows_system_path" in ids, (
            f"回落那支按空格切短了值，Windows 系统目录前缀配不上就整条放行：{ids}")

    def testSameBytesGiveTheSameVerdictRegardlessOfWhichKeyCarriesThem(self):
        """同一份字节不许因"谁来带它"被判成不同东西（§6-284 第二轮那组对照的收口）。"""
        asTextual = ruleIds("file_read", {"file": WIN_SYSTEM_FILE})
        asScanned = ruleIds("file_read", {"path": WIN_SYSTEM_FILE})

        assert "windows_system_path" in asScanned, f"scanned 键那一支自己就松了：{asScanned}"
        assert asScanned and "windows_system_path" in asTextual, (
            f"同一值两形不同判：textual={asTextual} scanned={asScanned}")

    def testTextualKeyBesideScannedKeyIsStillJudged(self):
        """翻转形：过去"清单内键一出现就把 textual 那支短路掉"，同形同值该同判。"""
        alone = ruleIds("file_read", {"dir": SHADOW})
        beside = ruleIds("file_read", {"file_path": SAFE_PATH, "dir": SHADOW})

        assert "protected_path" in alone, f"单给那一支就不成立了：{alone}"
        assert "protected_path" in beside, (
            f"`dir` 的值因旁边有 `file_path` 而从不被查（翻转仍未修）：{beside}")


class TestCommandSurfaceIsAlwaysScanned:
    def testCommandTextIsScannedEvenWhenAPathParamIsPresent(self):
        """case 2 主红：命令文本那一支过去挂在 `if not path:` 下面，带 path 就不做。"""
        withPath = ruleIds("shell", {"file_path": SAFE_PATH, "command": "cat /etc/shadow"})
        control = ruleIds("shell", {"command": "cat /etc/shadow"})

        assert "protected_path_in_command" in control, f"对照形本身就不成立：{control}"
        assert "protected_path_in_command" in withPath, (
            f"命令文本被'已找到路径'短路——零读数是早退造成的，不是规则缺失：{withPath}")

    def testFreeTextKeyHoldingAPathStaysUnjudged(self):
        """case 4 反向钉：本批明确不把它做进去——做了就是把守卫从"判形状"拖回"判词"。"""
        ids = ruleIds("file_read", {"file_path": SAFE_PATH, "note": f"见 {SHADOW}"})

        assert ids == [], f"自由文本键里的路径开始被当路径判了（甲案不覆盖这一形）：{ids}"

    def testDeduplicationIsByAttributionNotByString(self):
        """两条归属谁也不许替谁消失；同一个值被两个键带着只报一条。"""
        sameValueTwoKeys = evidencesOf(
            "file_read", {"file_path": SHADOW, "path": SHADOW}, "protected_path")
        bothAttributions = ruleIds("shell", {"path": SHADOW, "command": "cat /etc/shadow"})

        assert len(sameValueTwoKeys) == 1, (
            f"同一个值被两个键带着就双报——去重该按值归属去：{sameValueTwoKeys}")
        assert {"protected_path", "protected_path_in_command"} <= set(bothAttributions), (
            f"按值判与按文本判是两个归属，一个不许吞另一个：{bothAttributions}")


class TestSinglePathCallsAreByteForByteUnchanged:
    """甲对外承诺的那一半：单路径调用的读数一字不变（这组改前改后都绿，逐格写明职责）。"""

    @pytest.mark.parametrize("params,expected", [
        ({"file_path": SHADOW}, {"protected_path"}),
        ({"path": PASSWD}, {"protected_path"}),
        ({"file_path": SAFE_PATH}, set()),
    ])
    def testSinglePathVerdictUnchanged(self, params, expected):
        ids = set(ruleIds("file_read", params))

        assert expected <= ids, f"既有的裁决松了：{params} -> {sorted(ids)}"
        if not expected:
            assert ids == set(), f"无害的单路径调用开始被报：{params} -> {sorted(ids)}"

    def testRelativeTraversalFormKeepsItsOwnSingleReading(self):
        """`../../../etc/passwd` 改前改后都只出 `path_traversal`——这一格写明它是形状而不是洞。

        现读：`protected_path` 不出现，因为受保护判定是对**原值与 expanduser 后的值**做前缀比对，
        相对形状配不上 `/etc/passwd`。但同一条 `path_traversal` 也是 HIGH（AUTO 档拦 ≥HIGH），
        拦阻结果没变，只是不叠第二条读数——所以本批不改它的口径；改它要另开一票（动了就是新增读数）。
        """
        ids = set(ruleIds("file_read", {"file_path": "../../../etc/passwd"}))

        assert ids == {"path_traversal"}, f"相对遍历形状的读数被本批改动了：{sorted(ids)}"


class TestThePrecheckDoesNotCollapseFirst:
    """治理预检是同一根因的第二命中点：它先 `next(...)` 取第一个，守卫就永远拿不到第二条。

    生产路上唯一的入口是 `tool_executor` → `Governance.evaluate_tool_call(tool_name, params)`，
    它经 `extract_adjudicable_params` 把参数面交给 `evaluate`，`evaluate` 再喂 `engine.guard`。
    只在咽喉里逐值扫而不动这一层，等于把修落在一条走不到的分支上。
    """

    def _policy(self):
        from neurova.security.governance import GovernancePolicy

        return GovernancePolicy()

    def testPrecheckHandsEveryPathValueToTheAdjudication(self):
        """取数契约本身：两个路径键都在，就得两个都交出去（改前只交第一个）。"""
        from neurova.security.governance import extract_adjudicable_params

        picked = extract_adjudicable_params({"file_path": SAFE_PATH, "path": SHADOW})[1]

        assert [v for _k, v in picked] == [SAFE_PATH, SHADOW], (
            f"预检仍只把一条路径交给裁决面（改前读数是单个字符串 `{SHADOW}` 甚至空）：{picked}")
        assert [k for k, _v in picked] == ["file_path", "path"], (
            f"键名没随值一起交出来，守卫就点不出是谁命中的：{picked}")

    def testProtectedSecondValueIsAdjudicatedThroughTheRealRoute(self):
        """case 1 在**真预检路**上的读数：第二条路径受保护 ⇒ 裁决不许是 ALLOW。"""
        verdict = self._policy().evaluate_tool_call(
            "file_read", {"file_path": SAFE_PATH, "path": SHADOW})

        assert verdict is not None and verdict.decision.name != "ALLOW", (
            f"经治理预检走一遍，第二条路径仍然放行：{verdict}")

    def testCommandTextIsAdjudicatedThroughTheRealRoute(self):
        """case 2 在真预检路上：`git` 那一形（同时带 `command` 与 `path`）今天就是短路 shape。"""
        verdict = self._policy().evaluate_tool_call(
            "shell", {"command": "cat /etc/shadow", "path": SAFE_PATH})

        assert verdict is not None and verdict.decision.name != "ALLOW", (
            f"带 path 的调用里命令文本又被放过（第一方唯一那只双参数工具就是 git）：{verdict}")

    def testForwardingTextualKeysAddsNoNewFriction(self):
        """对照格：预检把 `dir`/`file` 也转给守卫之后，**良性值**不许因此新增裁决。

        这是"既有单路径调用读数一字不变"那半句在预检路上的版本。转发键名会让这些值同时出现在
        命令扫描面上（`dir`/`file` 不在 scanned 清单里，按 §6-266 第①刀的口径它们本就该走命令面），
        所以这里要点名确认它没有顺手多出一条参与拦截的读数。
        """
        benignDir = "/home/agent/workspace"
        ids = [f.rule_id for f in ToolGuardEngine().guard("file_read", {"dir": benignDir}).findings]
        verdict = self._policy().evaluate_tool_call("file_read", {"command": "ls", "dir": benignDir})

        assert ids == [], f"良性目录值开始被路径面报：{ids}"
        assert verdict is None or verdict.decision.name == "ALLOW", (
            f"转发 textual 键把一次良性调用推上了审批："
            f"{verdict and verdict.decision.name}")

    def testGovernanceNoLongerHandRollsTheKeyList(self):
        """形状格：预检的取数必须经 `pathValuesFromParams`，不许再自己写一份认键的循环。

        两份"哪些名字算路径"正是 §6-284 第③件事；名单收成一张之后，取数口也只能有一个。
        """
        import ast

        src = (REPO / "neurova/security/governance.py").read_text(encoding="utf-8")
        tree = ast.parse(src, filename="governance.py")
        attrs = {n.func.id for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        ownLoops = [n for n in ast.walk(tree) if isinstance(n, ast.For)
                    and "PATH_PARAM_KEYS" in ast.unparse(n.iter)]

        assert "pathValuesFromParams" in attrs, (
            "预检不再经单源取数口了——那意味着它自己另写了一份键名清单")
        assert not ownLoops, (
            f"governance 里仍有自己遍历 `PATH_PARAM_KEYS` 的循环（第 "
            f"{ownLoops[0].lineno} 行）：两份名单的老形状回来了")
class TestExtractionShapeIsPinned:
    """形状格：把"回填一个 break"做成会红的判据，不靠自觉。"""

    def _guardianSource(self) -> str:
        return (REPO / "neurova/security/tool_guard.py").read_text(encoding="utf-8")

    def _guardianGuardBody(self):
        tree = ast.parse(self._guardianSource(), filename="tool_guard.py")
        for cls in ast.walk(tree):
            if isinstance(cls, ast.ClassDef) and cls.name == "FilePathGuardian":
                for fn in cls.body:
                    if isinstance(fn, ast.FunctionDef) and fn.name == "guard":
                        return fn
        raise AssertionError("FilePathGuardian.guard 找不到了——扫描面失效，这格该红")

    def testNoFirstWinsBreakLeftInTheExtraction(self):
        """取数循环里不许再有 `break`：那正是"一次调用只查一条路径"的代码形状。"""
        body = self._guardianGuardBody()
        loops = [n for n in ast.walk(body) if isinstance(n, (ast.For, ast.AsyncFor))
                 and any(isinstance(s, ast.Break) for s in ast.walk(n))]

        assert not loops, (
            f"guard() 里仍有带 break 的循环（第 {loops[0].lineno} 行起）——"
            "逐值扫被改回取第一个就早退，case 1 会静默复活")

    def testCommandScanIsNotGuardedByAnEmptyPathCheck(self):
        """命令文本那一支不许再被"路径为空"这类条件包着（case 2 的根就是这个嵌套）。"""
        body = self._guardianGuardBody()
        textCalls = [n for n in ast.walk(body) if isinstance(n, ast.Call)
                     and isinstance(n.func, ast.Attribute)
                     and n.func.attr == "_scan_protected_paths_in_text"]
        assert textCalls, "命令文本那支整个不见了——那不是收口，是拆闸"

        for ifNode in (n for n in ast.walk(body) if isinstance(n, ast.If)):
            span = {x.lineno for stmt in ifNode.body for x in ast.walk(stmt)
                    if hasattr(x, "lineno")}
            for call in textCalls:
                if call.lineno not in span:
                    continue
                names = {x.id for x in ast.walk(ifNode.test) if isinstance(x, ast.Name)}
                assert "path" not in names, (
                    f"命令文本扫描又被包回「路径为空才做」那一支里（第 {ifNode.lineno} 行的 "
                    f"`if` 判的是 {sorted(names)}）——case 2 会静默复活")
