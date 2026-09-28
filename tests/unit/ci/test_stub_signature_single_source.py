# -*- coding: utf-8 -*-
"""测试替身不得**手抄**本仓生产符号的签名（第二份签名定义）。

## 根因（不是形状）

CI 曾转红（PR #304，构建 `cnb-6c0-1k3iv2o5f-003`）：

    TypeError: test_poolBranchPassesABudgetToCompressEnvelope.<locals>.spy()
    got an unexpected keyword argument 'report'
      neurova/context/orchestrator.py:1563: in build_context
        _env = compress_envelope(_env, budget_tokens=env_budget, report=_discard_report)

红的那一行不是生产代码写错了。生产侧在同一 PR 里给
`envelope.compress_envelope` 加了第四个参数 `report`，而测试里那个替身
自己写了一份形参表：

    def spy(envelope, budget_tokens, count_tokens=None):   # ← 手抄的第二份签名
        ...original(envelope, budget_tokens, count_tokens=count_tokens)...

于是**生产签名的事实源与测试里那份各说各话**（`AGENTS.md` 教义第 6 条：
发现第二份定义就收口并删净）。红只是表象——真正的问题是那条替身**无论生产
签名怎么变都不会自动跟随**：这一次是加参数即 TypeError，下一次是删参数时
生产侧多传一个位置实参、被替身吃进错位的变量里，**照样绿**。后一种更坏：
它不报错，只让断言看错的东西。

## 判据

1. **受保护子集内零例外**：CI 实际跑的清单（`scripts/ci/protected_tests.txt`）
   里，凡本文件内定义的函数被用作 `patch(...)` / `patch.object(...)` 的
   `side_effect=` / `wraps=` / `new=` 且被替换对象是本仓生产符号
   （`neurova.*`，含 `import ... as` 别名解析）时，该函数**不得**手抄固定
   形参表，必须写 `*args, **kwargs`（参数化形态：调用实参一律透传，生产侧
   加/删参数自动跟随）。
   零账外例外——受保护子集进 CI，这里的断链就是 CI 的红。

   **为什么 `autospec=True` 不能作为豁免**（实证，本判据的反向控制里锁着）：
   `autospec` 只约束 **mock 自身**的调用签名，而 `side_effect=` 给的是一个
   **独立函数**，平台按自己的形参表调用它。实测：生产侧 `production(a, b, c=None, d=None)`、
   替身手抄 `def staleStub(a, b, c=None)`，即便加了 `autospec=True`，生产侧传
   `d=4` 时照样 `TypeError: staleStub() got an unexpected keyword argument 'd'`。
   故"加个 autospec 就算合规"是一条**会把红推给下一个人**的假修法。

2. **面外债务台账账实相符**（两个方向都可证伪）：本仓 `tests/` 其余位置
   同类形态当下不在 CI 面上，登记为已知债务；台账条目必须
   （a）仍在仓里、（b）仍是"手抄签名"形态。修好了或文件没了却留着条目即红；
   新增面外命中点而未署名同样红。

## 反向控制（缺一条本判据就是恒真断言，教义第 3 条明禁）

- **检测器真的会报**：对一段内联的"替身手抄签名 + patch 本仓生产符号"源码，
  检测器必须报出，且报出的是**手抄形态**而不是别的；
- **两条豁免真的豁免**：同一段源码里把替身改成 `*args, **kwargs`，或给它加
  `autospec=True`，检测器都不得报出（否则它成了"凡 patch 皆红"的死规则）。
"""

import ast
import io
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

import pytest

from tests import ast_scan

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PROTECTED = PROJECT_ROOT / "scripts" / "ci" / "protected_tests.txt"

#: 替身的三种挂载键：`side_effect` / `wraps` 是 `patch` 的实参，`new` 直接换掉对象。
STUB_KEYS = ("side_effect", "wraps", "new")

#: 面外债务台账：**非受保护子集**里同类形态的已知存量（`相对仓根路径` → 依据）。
#: 逐条署名，且由 `TestOffFaceLedgerMatchesReality` 双向对账 ——
#: 它不是免检通道：条目在仓里消失、或已改成参数化形态，都必须同步销账。
#:
#: **现值：空集**。本 PR 的放大视角扫荡把面外 8 处同形态替身（`agent/swarm`、
#: `mobile_pairing`、`skill_pool_api`、`voice_precheck`、comfyui 三支、
#: `web_reach/credential_isolation`）**同批改成参数化形态**，故无存量可留。
#: 空集是默认政策：新出现的面外命中点须当场改，确需保留者登记在这里并写明理由。
OFF_FACE_LEDGER = {}

#: 本模块自身的文件名（写死相对路径只此一处，供"守卫自己进受保护子集"判据复用）。
GUARD_REL = "tests/unit/ci/test_stub_signature_single_source.py"


def protectedFiles() -> list:
    """CI 实际跑的受保护子集（唯一事实源，不另建清单）。"""
    return [
        line.split("#", 1)[0].strip()
        for line in io.open(PROTECTED, encoding="utf-8").read().splitlines()
        if line.split("#", 1)[0].strip()
    ]


def _moduleAliases(tree: ast.AST) -> dict:
    """本文件里 `名字 → neurova 模块路径` 的别名表（静态解析 patch 目标用）。"""
    table = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("neurova"):
                    table[alias.asname or alias.name.split(".")[0]] = alias.name
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if not base.startswith("neurova"):
                continue
            for alias in node.names:
                if alias.name != "*":
                    table[alias.asname or alias.name] = f"{base}.{alias.name}"
    return table


def _patchTarget(call: ast.Call, aliases: dict):
    """`patch(...)` / `patch.object(...)` 的被替换对象全名（解析不出返回 None）。"""
    funcName = ast.unparse(call.func)
    if funcName.endswith("patch.object"):
        if len(call.args) < 2:
            return None
        holder, attr = call.args[0], call.args[1]
        if isinstance(holder, ast.Name) and isinstance(attr, ast.Constant):
            modulePath = aliases.get(holder.id)
            if modulePath:
                return f"{modulePath}.{attr.value}"
        return None
    if funcName.endswith("patch"):
        if call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str):
            return call.args[0].value
    return None


def _stubIsParameterized(funcDef) -> bool:
    """替身是否**参数化**：有 `*args` 或 `**kwargs` 即自动跟随生产签名。"""
    args = funcDef.args
    return bool(args.vararg or args.kwarg)


def handCopiedStubs(tree: ast.AST) -> list:
    """本文件里「手抄本仓生产符号签名」的替身点：`(行号, 替身名, 目标)` 清单。

    判据只看**形态**、不比对当下签名是否一致 —— 本 PR 的教训正是
    "当下一致也会漂移"，等到不一致时红出来的地方已经在 CI 里了。
    """
    aliases = _moduleAliases(tree)
    localFuncs = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            localFuncs.setdefault(node.name, []).append(node)

    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = _patchTarget(node, aliases)
        if not target or not target.startswith("neurova."):
            continue
        for kw in node.keywords:
            if kw.arg not in STUB_KEYS or not isinstance(kw.value, ast.Name):
                continue
            for funcDef in localFuncs.get(kw.value.id, []):
                if _stubIsParameterized(funcDef):
                    continue
                hits.append((funcDef.lineno, kw.value.id, target))
    return hits


def scanTree(path: Path) -> list:
    """单文件替身命中点（解析失败按"无可判"处理，不静默算过）。"""
    try:
        tree = ast_scan.transientTree(path)
    except SyntaxError:
        return []
    return handCopiedStubs(tree)


def candidateRefs(root: Optional[Path] = None):
    """候选文件（走共享预算入口 + 文本预筛）。

    预筛是**充分条件**，两个词都必须在：命中点必然是「`patch(...)` 调用」，
    且其挂载键必是 `side_effect` / `wraps` / `new` 之一。故判据保证：
    两个词缺任一 ⇒ 不可能命中（漏报为 0）。

    `sourceRefsUnder` 的 `hints` 是 **OR** 语义，故这里先按挂载键取候选，
    再叠加 `patch` 做 AND —— 只按 `patch` 取会把上千个只含这个词的文件
    拉进来（实测 1016 个，是收敛后的 2.5 倍）。

    为何必须收：判据本身不得与仓库规模捆绑。手写 `rglob + ast.parse` 全仓扫描
    会把代码行数编码成时间上界，撞 30s 默认墙钟即偶发红（Issue #148 同根，
    `tests/unit/test_ci_ast_scan_budget_guard.py` 常驻守住这一形态）。
    """
    refs = ast_scan.sourceRefsUnder(
        root or ast_scan.REPO_ROOT / "tests", hints=STUB_KEYS
    )
    return [ref for ref in refs if "patch" in ref.code]


class TestProtectedSubsetHasNoHandCopiedStub:  # noqa: N801 - 与仓内既有类名风格无关，保持驼峰可读
    """受保护子集内零例外：那里的断链就是 CI 的红。"""

    def test_no_handCopiedProductionStubInProtectedSubset(self):
        protected = set(protectedFiles())
        offenders = []
        for ref in candidateRefs():
            rel = ast_scan.relativeToRepo(ref.path)
            if rel not in protected:
                continue
            for lineno, name, target in scanTree(ref.path):
                offenders.append(f"{rel}:{lineno} 替身 {name}() 手抄了 {target} 的签名")
        assert offenders == [], (
            "替身手抄了本仓生产符号的签名（第二份签名定义，生产侧加/删参数即断）：\n  "
            + "\n  ".join(offenders)
            + "\n修法：替身写成 `def stub(*args, **kwargs)` 并原样透传给被替换的实现"
            "（形参表不再是一份事实源）。注意 `autospec=True` **不是**修法："
            "它只约束 mock 自身，`side_effect` 那个函数仍按自己的形参表被调用。"
        )


class TestOffFaceLedgerMatchesReality:
    """面外存量登记在案，且账实双向对账（不是免检通道）。"""

    def test_offFaceLedger_entriesStillExistAndStillHandCopied(self):
        stale, vanished = [], []
        for rel, reason in sorted(OFF_FACE_LEDGER.items()):
            path = PROJECT_ROOT / rel
            if not path.is_file():
                vanished.append(f"{rel}（{reason}）")
                continue
            if not scanTree(path):
                stale.append(f"{rel}（{reason}）")
        assert not vanished, f"台账登记的文件已不在仓里，请销账：{vanished}"
        assert not stale, f"台账登记的替身已不再是手抄形态（已修好），请销账：{stale}"

    def test_everyOffFaceHitIsSigned(self):
        """面外新增命中点必须署名；未署名的命中点即红。"""
        unsigned = []
        for ref in candidateRefs():
            path = ref.path
            rel = ast_scan.relativeToRepo(path)
            if rel in protectedFiles() or rel in OFF_FACE_LEDGER or rel == GUARD_REL:
                continue
            for lineno, name, target in scanTree(path):
                unsigned.append(f"{rel}:{lineno} 替身 {name}() 手抄了 {target} 的签名")
        assert unsigned == [], (
            "面外出现未署名的手抄签名替身（新增即须登记台账并说明依据）：\n  "
            + "\n  ".join(unsigned)
        )


class TestDetectorIsNotVacuous:
    """反向控制：检测器真的会报，两条豁免真的豁免（缺一条本判据即恒真）。"""

    #: 手抄签名形态：这份形参表就是「第二份签名定义」本身。
    HAND_COPIED = """
from unittest.mock import patch

import neurova.context.envelope as envelopeModule


def test_sample():
    def stub(envelope, budget_tokens, count_tokens=None):
        return envelope

    with patch.object(envelopeModule, "compress_envelope", side_effect=stub):
        pass
"""

    #: 参数化形态：`*args, **kwargs` 自动跟随生产签名。
    PARAMETERIZED = """
from unittest.mock import patch

import neurova.context.envelope as envelopeModule


def test_sample():
    def stub(*args, **kwargs):
        return args

    with patch.object(envelopeModule, "compress_envelope", side_effect=stub):
        pass
"""

    #: `autospec=True` 形态：**不构成豁免** —— autospec 只约束 mock 自身，
    #: `side_effect` 那个函数仍按自己的形参表被调用（见下方实证）。
    AUTOSPEC = """
from unittest.mock import patch

import neurova.context.envelope as envelopeModule


def test_sample():
    def stub(envelope, budget_tokens, count_tokens=None):
        return envelope

    with patch.object(envelopeModule, "compress_envelope", autospec=True, side_effect=stub):
        pass
"""

    #: 非本仓符号：第三方依赖的签名不受本仓契约管辖，不得报出。
    THIRD_PARTY = """
from unittest.mock import patch


def test_sample():
    def stub(path, mode="r"):
        return path

    with patch("shutil.rmtree", side_effect=stub):
        pass
"""

    def _report(self, source: str):
        return [
            (name, target) for _lineno, name, target in handCopiedStubs(ast.parse(source))
        ]

    def test_handCopiedStubIsReported(self):
        assert self._report(self.HAND_COPIED) == [
            ("stub", "neurova.context.envelope.compress_envelope")
        ], "检测器漏报了手抄签名的替身——本判据会退化成空壳"

    def test_parameterizedStubIsExempt(self):
        """`*args, **kwargs` 形态自动跟随生产签名，不得报出。"""
        assert self._report(self.PARAMETERIZED) == [], "参数化替身被误报——修法本身被判红"

    def test_autospecStubIsStillReported(self):
        """`autospec=True` **不是**豁免：那份形参表仍是第二份签名定义，照样报出。"""
        assert self._report(self.AUTOSPEC) == [
            ("stub", "neurova.context.envelope.compress_envelope")
        ], "autospec 形态被当成豁免——`side_effect` 那个替身照样会因生产签名变化而 TypeError"

    def test_autospecDoesNotRescueAStaleStub(self):
        """实证本判据那条断言：autospec 救不了手抄签名的替身（判据不是纸面推理）。

        生产签名四参、替身手抄三参，加 `autospec=True` 后生产侧传第四个关键字
        实参——实测仍是 `TypeError`。故"加个 autospec 就算合规"是假修法。
        """
        from unittest.mock import patch as patchFn

        def production(a, b, c=None, d=None):
            return (a, b, c, d)

        def staleStub(a, b, c=None):
            return (a, b, c)

        holder = SimpleNamespace(production=production)
        with patchFn.object(holder, "production", autospec=True, side_effect=staleStub):
            with pytest.raises(TypeError, match="unexpected keyword argument"):
                holder.production(1, 2, c=3, d=4)

    def test_thirdPartyTargetIsNotCharged(self):
        """判据只谈本仓契约：第三方依赖的替身签名不属本契约。"""
        assert self._report(self.THIRD_PARTY) == [], "第三方符号被误报——口径扩错了域"


class TestPrefilterDoesNotDropHits:
    """文本预筛是**充分条件**，必须自证不漏报（否则它是"更快的假安全"）。

    预筛只保留同时含 `patch` 与挂载键之一的文件。漏报风险在于**检测器的命中条件
    是否真被这两个词覆盖**——本组用它自己的反向控制样本 + 真实语料两侧钉住。
    """

    #: 预筛谓词与检测器分开写在这里，故意的：两边各自独立，才验得到一致性。
    @staticmethod
    def _prefilterKeeps(source: str) -> bool:
        return "patch" in source and any(key in source for key in STUB_KEYS)

    def test_everyReportedShapeSurvivesThePrefilter(self):
        """凡检测器会报出的形态，预筛必须留下（用 4 份反向控制样本逐个验）。"""
        samples = {
            "手抄签名": TestDetectorIsNotVacuous.HAND_COPIED,
            "参数化": TestDetectorIsNotVacuous.PARAMETERIZED,
            "autospec": TestDetectorIsNotVacuous.AUTOSPEC,
        }
        for label, source in samples.items():
            assert self._prefilterKeeps(source), f"预筛会丢下这一形态的文件：{label}"

    def test_droppedFilesReallyHaveNoHits(self):
        """真实语料反证：被预筛丢掉的文件里，检测器确实一个命中都没有。

        这是**非空转**的那一半：不是"我认为丢了没关系"，而是对被丢掉的那批
        文件真跑一遍检测器。代价有界（只解析被丢掉的那部分，实测 0.2s 量级），
        不随仓库规模线性涨——判据不得与代码总量捆绑。
        """
        kept = {ref.path for ref in candidateRefs()}
        dropped = [
            ref for ref in ast_scan.sourceRefsUnder(ast_scan.REPO_ROOT / "tests", hints=STUB_KEYS)
            if ref.path not in kept
        ]
        offenders = [
            f"{ast_scan.relativeToRepo(ref.path)}:{lineno}"
            for ref in dropped
            for lineno, _name, _target in scanTree(ref.path)
        ]
        assert offenders == [], (
            f"预筛丢掉了真有命中的文件（判据漏报）：{offenders}"
            " —— 预筛谓词与检测器条件已不一致，必须放宽谓词而不是放过漏报"
        )


class TestGuardIsReachableFromCi:
    """守卫自己必须在 CI 面上（否则本门禁绿得毫无意义）。"""

    def test_guardIsRegisteredInProtectedSubset(self):
        assert (PROJECT_ROOT / GUARD_REL).is_file(), "守卫文件不在仓里"
        assert GUARD_REL in protectedFiles(), (
            "本守卫未登记进 scripts/ci/protected_tests.txt —— 它不会在 CI 上跑，"
            "本 PR 那条断链下次照旧能合进来。"
        )
