"""门面/模块里的 `X = None` 占位符只准绑在"真可能缺的东西"上（工单 2026-10-14 批 43，§6-201）。

建档实状（对 `git ls-files` 全部跟踪 .py 逐个 AST + 导入闭包现算，语法失败 0 处）：
带 `except ImportError` 且 handler 里把名字赋成 `None` 的 try 节点 **93 个 / 136 个占位符名**，
其中 **69 个节点 / 22 个文件**包的是 **stdlib 或仓内模块**——而被包的仓内模块，其模块级
import 闭包一个第三方都不碰。这类兜底永远不会触发，却把「模块未可用」写进日志、把符号降级成
`None`；它一旦真触发（循环导入、路径没装好），拿到 `None` 的调用方会在下一行炸。
最尖锐的一处是 `neurova/auth/__init__.py` 拿 try 包 **stdlib `hashlib`** 再 `hashlib = None`。

另一侧必须留住：AGENTS.md §3 明确允许「可选依赖 fail-soft」，所以包着第三方（fastapi / httpx /
aiohttp / langchain_* / bcrypt / pycryptodome / numpy…）的占位符是**正当形态**，本批判据不许误伤
——判据的口径是"这条兜底所包的导入里，至少要有一个顶层依赖闭包触及非标准库第三方"，
不是"仓里不许出现 None 占位符"。

不在本批（台账 §6-201 登记）：
- `neurova/llm_client.py:17` 的 handler 里定义了**真回退实现**（decorator 桩、class 桩），
  那不是占位符，要判的是"这套回退今天还走得到吗"；
- 24 个包真第三方的节点按 §3 保留；
- `tests/manual/context_compression_single_face_90.py:34` 的 try 带 else/finally，拆它要另判语义。
"""

from __future__ import annotations

import ast
import io
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests import ast_scan  # noqa: E402
from tests.ast_scan import parseSource

NEUROVA = REPO_ROOT / "neurova"

STDLIB = set(sys.stdlib_module_names)


def _trackedPyFiles() -> list:
    """扫描面＝已跟踪的 .py，走 `tests/ast_scan.py` 的单点（解码/退出码口径也只在那里定一次）。"""
    return ast_scan.trackedPyPaths()


def _requiredThirdPartyNames() -> set:
    """requirements.txt 里声明过的包名（连字符与下划线归一——不归一会把 langchain_openai
    这类"其实已声明"的依赖误判成"未声明可选"，从而把该保留的档也判成违规）。"""
    out = set()
    for line in io.open(REPO_ROOT / "requirements.txt", encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name = (line.split("[")[0].split(">")[0].split("<")[0].split("=")[0].split("!")[0]
                .split("~")[0].split(";")[0].strip().lower().replace("-", "_"))
        if name:
            out.add(name)
    return out


REQ = _requiredThirdPartyNames()


def _importsOf(node, rel: str) -> list:
    """模块级 import 的点分名；相对导入按所在包还原成绝对名。

    解名交 `tests/ast_scan.resolveImportModule` 那个单点。这档原来自己写了一份层数算术
    （`pkg[: len(pkg) - (node.level - 1)]`）——两份实现的坏处不在今天算错，而在**算错了
    这条判据看不见**：它只会报"这条 import 是占位兜底"，不会报"我把相对形解歪了"，
    而解歪的结果是第三方闭包**少走一条边**（假绿方向）。
    """
    if isinstance(node, ast.Import):
        return [a.name for a in node.names]
    if not isinstance(node, ast.ImportFrom):
        return []
    module = ast_scan.resolveImportModule(rel, node)
    return [module] if module else []


def _resolve(mod: str):
    parts = mod.split(".")
    for cand in ("/".join(parts) + ".py", "/".join(parts) + "/__init__.py"):
        if (REPO_ROOT / cand).is_file():
            return cand
    return None


def _thirdPartyClosure(mod: str, seen=None, depth=0):
    """该模块**模块级**（不含函数内懒加载）导入闭包里的第三方顶层名。

    只看模块级是有道理的：函数内的 import 不影响"这条 import 语句会不会抛 ImportError"。
    """
    seen = seen or set()
    if mod in seen or depth > 14:
        return set(), False
    seen = seen | {mod}
    rel = _resolve(mod)
    if rel is None:
        return set(), True
    try:
        # 走共享一次性入口：留文本缓存、不留常驻语法树，与 `filesUnder` 同一份口径
        tree = ast_scan.transientTree(REPO_ROOT / rel)
    except Exception:
        return set(), True
    third, bad = set(), False
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for m in _importsOf(node, rel):
                root = m.split(".")[0]
                if root in STDLIB or root == "__future__":
                    continue
                if m.startswith("neurova"):
                    sub, subBad = _thirdPartyClosure(m, seen, depth + 1)
                    third |= sub
                    bad = bad or subBad
                else:
                    third.add(root)
    return third, bad


def touchesRealOptional(mod: str) -> bool:
    """这条兜底所包的导入，是不是**真可能缺东西**。

    口径两分（本批用户点单时定的边界）：
    - 体内直接 `import` 一个非标准库包（fastapi / httpx / aiohttp / bcrypt / numpy…）
      ⇒ 这是 §3 说的可选依赖门，正当，保留；
    - 体内只包仓内模块，而它的闭包只触及 **requirements.txt 已声明**的第三方 ⇒ 不算"可能缺"：
      装机要么按声明装齐、要么本来就已经坏了，把这条 import 包进 try 只会把仓内故障
      （循环导入、路径没装好）伪装成"第三方没装"。⇒ 违规，本批改直连。
    - 闭包触及**未声明**的包（真可选，如 bcrypt 那类）⇒ 保留。
    """
    root = mod.split(".")[0]
    if root in STDLIB:
        return False
    if not mod.startswith("neurova"):
        return True
    third, bad = _thirdPartyClosure(mod)
    if bad:
        return True          # 解析不到 ⇒ 不敢断定它是死的兜底，留给人工判
    return any(x.replace("-", "_") not in REQ for x in third)


def placeholderViolations(source: str, rel: str):
    """返回「except ImportError 里赋 None，但所包导入一个第三方都不碰」的节点。"""
    try:
        tree = parseSource(source, filename=rel)
    except SyntaxError as exc:
        return [("语法解析失败，扫描面未覆盖该文件", rel, 0, str(exc))]
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        handlers = [h for h in node.handlers or []
                    if isinstance(h.type, ast.Name) and h.type.id in ("ImportError", "ModuleNotFoundError")]
        if not handlers:
            continue
        placed = [t.id for h in handlers for st in h.body
                  if isinstance(st, ast.Assign) and isinstance(st.value, ast.Constant)
                  and st.value.value is None for t in st.targets if isinstance(t, ast.Name)]
        if not placed:
            continue
        # 体里除了 import 还可以有别的语句（例如先算一个变量再 import）——不能因此就放过：
        # 只要这条兜底所包的导入里没有一个是"真可能缺的东西"，它就是不可达的假降级。
        mods = [m for st in node.body if isinstance(st, (ast.Import, ast.ImportFrom))
                for m in _importsOf(st, rel)]
        if mods and not any(touchesRealOptional(m) for m in mods):
            out.append(("占位符所包导入全是 stdlib/仓内纯模块——这条兜底永不可达",
                        rel, node.lineno, sorted(set(placed))[:6]))
    return out


#: 同一根因的**另一种形状**（首次现算 §6-224，8 处 / 3 档）：handler 里不赋 `None`，而是定义
#: 与 try 体**同名**的 class/def 桩。它比 `None` 更难查——`None` 在下一行就 `TypeError`，
#: 空类/"返回桩"的函数能一路走下去，把降级悄悄做实。`neurova/execution_engine/__init__.py`
#: 那九枚同名空类是 §6-224 撞出来的第一处；剩下 3 档 8 处由 §6-228 全拆（用户拍甲）。
#: 现在这张表是**零容忍政策**而不只是"清零的存量"：将来撞出一处，出路只有「拆桩直连」，
#: 或者被包的导入确实触及未声明第三方——后一条由 `touchesRealOptional` 自己判，不由人在这里登记。
#: 为什么这类桩比 `X = None` 更该零容忍：`encrypt_api_key(key): return key` 那枚一旦真触发，
#: 密钥加解密就被静默做成透传，而读代码的人看见的是"有兜底"。
STUB_LEDGER: dict = {}  # type: ignore[type-arg]


def stubViolations(source: str, rel: str):
    """返回「except ImportError 里定义同名 class/def 桩，而所包导入不触及真可选依赖」的节点。"""
    try:
        tree = parseSource(source, filename=rel)
    except SyntaxError as exc:
        return [("语法解析失败，扫描面未覆盖该文件", rel, 0, str(exc))]
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        handlers = [h for h in node.handlers or []
                    if isinstance(h.type, ast.Name) and h.type.id in ("ImportError", "ModuleNotFoundError")]
        if not handlers:
            continue
        imported = {a.asname or a.name.split(".")[0] for st in node.body
                    if isinstance(st, (ast.Import, ast.ImportFrom)) for a in st.names}
        stubbed = sorted({n.name for h in handlers for n in h.body
                          if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                          and n.name in imported})
        if not stubbed:
            continue
        mods = [m for st in node.body if isinstance(st, (ast.Import, ast.ImportFrom))
                for m in _importsOf(st, rel)]
        if mods and not any(touchesRealOptional(m) for m in mods):
            out.append((rel, node.lineno, stubbed))
    return out


class TestPlaceholderMustBindToRealOptional:
    def testRepoWideNoPlaceholderWrappingOnlyFirstPartyImports(self):
        offenders = []
        for rel in _trackedPyFiles():
            offenders += placeholderViolations(
                io.open(REPO_ROOT / rel, encoding="utf-8", errors="replace").read(), rel)
        assert not offenders, (
            f"发现 {len(offenders)} 处「把 first-party/stdlib 导入包进 try 再赋 None」的假降级："
            f"{offenders[:6]}——按修复教义第 1 条这类兜底不许留（它一旦触发，调用方拿到 None 再调用）")

    def testDetectorHasTeethAndDoesNotOverReach(self):
        """地板格 + 两枚反空转：既不能漏认违规，也不能把 §3 允许的正当 fail-soft 一起打掉。"""
        files = _trackedPyFiles()
        assert len(files) >= 3000, f"扫描集合只剩 {len(files)} 个 .py，口径被收窄了"

        plantedBad = placeholderViolations(
            "try:\n    import hashlib\nexcept ImportError:\n    hashlib = None\n", "x/probe.py")
        assert plantedBad, "漏认：包 stdlib 赋 None 这一形没被抓到"

        plantedInternal = placeholderViolations(
            "try:\n    from neurova.core import logger\nexcept ImportError:\n    logger = None\n",
            "x/probe.py")
        assert plantedInternal, "漏认：包仓内纯模块赋 None 这一形没被抓到"

        okThirdParty = placeholderViolations(
            "try:\n    import definitely_not_a_real_pkg_b43 as _m\nexcept ImportError:\n    _m = None\n",
            "x/probe.py")
        assert not okThirdParty, f"误伤真可选依赖这一形：{okThirdParty}"

    def testDeclaredRequirementIsNotAnExcuseButUndeclaredIs(self, monkeypatch):
        """把判据的两条边界各钉一格：已声明依赖不是保留理由，未声明的才是。

        这条边界是用户点单时拍的：`llm/providers/*` 那种"仓内模块、顶层 import 了 langchain_*"
        的兜底，本批一起改直连——requirements.txt 声明了它，装机缺它属于装坏了，不是受支持的降级；
        而 bcrypt / pycryptodome 那类**没声明**的，才是 §3 允许的门。
        """
        declared = placeholderViolations(
            "try:\n    import neurova.llm.providers.openai_provider\n"
            "except ImportError:\n    OpenAIProvider = None\n", "x/probe.py")
        assert declared, "已声明依赖不该成为保留理由（这一形本批要改直连）"

        directThird = placeholderViolations(
            "try:\n    import fastapi\nexcept ImportError:\n    fastapi = None\n", "x/probe.py")
        assert not directThird, f"直接包第三方是 §3 允许的可选依赖门，不该被误伤：{directThird}"

        # 全仓现读：没有任何仓内模块的**模块级**闭包触及未声明第三方（真可选依赖都在函数内
        # 懒加载），所以这一支无法用真模块取样，只能直接验判定函数两边的方向。
        me = sys.modules[__name__]
        monkeypatch.setattr(me, "_thirdPartyClosure",
                            lambda mod, *a, **k: ({"some_optional_pkg"}, False))
        assert me.touchesRealOptional("neurova.any.module"), "未声明可选应算真降级风险"
        monkeypatch.setattr(me, "_thirdPartyClosure", lambda mod, *a, **k: ({"fastapi"}, False))
        assert not me.touchesRealOptional("neurova.any.module"), "已声明依赖不该算保留理由"

    def testStubShadowingFirstPartyImportMatchesTheLedger(self):
        """同名 class/def 桩：现读与存量表**两侧相等**（新长一处即红，修好了不摘行也红）。"""
        counts = {}
        for rel in _trackedPyFiles():
            for _r, _lineno, _names in stubViolations(
                    io.open(REPO_ROOT / rel, encoding="utf-8", errors="replace").read(), rel):
                counts[rel] = counts.get(rel, 0) + 1
        extra = sorted(set(counts) - set(STUB_LEDGER))
        stale = sorted(p for p in STUB_LEDGER if counts.get(p, 0) != STUB_LEDGER[p])
        assert not extra and not stale, (
            f"同名桩与豁免表不符。新长出来的（唯一出路是拆桩直连；确实触及未声明第三方的那一形"
            f"本来就不进这条判据）：{[(p, counts[p]) for p in extra]}；"
            f"数目变了却没改表的（别留过期豁免）：{[(p, counts.get(p, 0), STUB_LEDGER[p]) for p in stale]}")

    def testTheStubExemptionLedgerIsStillEmpty(self):
        """零容忍格（§6-228 清零后新增）：这张表的空值本身就是要钉的东西。

        防的不是"这次忘了拆"，而是下一个人把"顺手加个兜底"当合法出路——他可以往表里加一行让
        上面那条等号格绿，但这一格会红着告诉他那条路已经封了：确实可能缺的东西由
        `touchesRealOptional` 自己判，不由人在这里登记。
        """
        assert not STUB_LEDGER, (
            f"同名桩豁免表又被填上了：{STUB_LEDGER}——拆桩直连，"
            "或让 touchesRealOptional 那条『确实可能缺』的判定自己放行，别在这里登记")

    def testStubDetectorHasTeethAndDoesNotOverReach(self):
        """探测器正反两头：桩冒充真身必抓，§3 允许的第三方可选依赖回退不许误伤。"""
        caught = stubViolations(
            "try:\n    from neurova.execution_engine.tool_engine import ToolEngine\n"
            "except ImportError:\n    class ToolEngine:\n        '占位'\n", "x/probe.py")
        assert caught, "漏认：仓内纯模块的同名空 class 桩没被抓到"

        caughtFn = stubViolations(
            "try:\n    from neurova.core.logger import get_logger\n"
            "except ImportError:\n    def get_logger(name):\n        return None\n", "x/probe.py")
        assert caughtFn, "漏认：同名函数桩没被抓到"

        legitOptional = stubViolations(
            "try:\n    import openai\n    from openai import APIConnectionError\n"
            "except ImportError:\n    class APIConnectionError(Exception):\n        pass\n",
            "x/probe.py")
        assert not legitOptional, f"误伤真可选依赖的正当回退：{legitOptional}"

        notShadowing = stubViolations(
            "try:\n    import neurova.core.logger\n"
            "except ImportError:\n    class LoggerShim:\n        pass\n", "x/probe.py")
        assert not notShadowing, "handler 里定义的名字与 try 体不同名——不是『桩冒充真身』，不该报"

class TestMemoryFacadeBrokenPointersRepaired:
    """拆掉兜底后现读到的三条坏指路必须改对——HEAD 上它们是静默的 None。

    建档实证（HEAD 侧现读）：`import neurova.memory` 后
    `SelfModel/UserProfile/GraphTraversal/SleepConsolidation/ProactiveQuestion/VersionControl`
    全都是 `None`——名字指错模块（前两条真身在 `memory_layer.models`）或**仓内根本没有这两个类**。
    旧形态不报错，所以这条链坏了多久无从判断。
    """

    def testRepairedReexportsResolveToRealClasses(self):
        import neurova.memory as facade
        from neurova.cognitive_layers.memory_layer import models as layerModels
        from neurova.cognitive_layers.memory_layer.graph_traversal import GraphTraversal
        from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation

        assert facade.SelfModel is layerModels.SelfModel
        assert facade.UserProfile is layerModels.UserProfile
        assert facade.GraphTraversal is GraphTraversal
        assert facade.SleepConsolidation is SleepConsolidation

    def testNamesWithoutImplementationAreNotReExportedAsNulls(self):
        """`ProactiveQuestion` / `VersionControl` 在仓内没有实装 ⇒ 门面不再假装有这两个名字。

        真身分别是 `proactive_question.Question`+`QuestionQueueManager` 与
        `version_control.MemoryVersionControl`；以真名再导出＝另一次裁定（§6-201），
        这里只钉"不许再留一个静默的 None 名字"。
        """
        import neurova.memory as facade

        for gone in ("ProactiveQuestion", "ProactiveQuestionManager", "VersionControl"):
            assert not hasattr(facade, gone), f"门面还在假装有 {gone}"
            assert gone not in (facade.__all__ or []), f"__all__ 还在宣传 {gone}"


class TestFacadeNullsAreAllBackedByRealOptional:
    def testEveryFacadeNullSymbolComesFromAThirdPartyBackedFallback(self):
        """包门面上每一个值为 None 的公开符号，都必须有一条"所包导入触及第三方"的兜底作出处。

        这条把形状判据与行为读数扣在一起：只按形状判会放过"占位符写在别处、门面导出 None"，
        只按行为判又会误伤 §3 允许的正当可选依赖（比如未声明的 bcrypt 之类）。两头的交集才是
        要守的不变量：**没有来路的 None 就是不可达兜底的产物**。
        """
        import importlib

        offenders = []
        for initFile in ast_scan.filesUnder(NEUROVA, "__init__.py"):
            rel = ast_scan.relativeToRepo(initFile)
            try:
                tree = ast_scan.transientTree(initFile)
            except SyntaxError:
                continue
            backed = set()
            for node in ast.walk(tree):
                if not isinstance(node, ast.Try):
                    continue
                handlers = [h for h in node.handlers or []
                            if isinstance(h.type, ast.Name)
                            and h.type.id in ("ImportError", "ModuleNotFoundError")]
                mods = [m for st in getattr(node, "body", []) if isinstance(st, (ast.Import, ast.ImportFrom))
                        for m in _importsOf(st, rel)]
                if not (handlers and mods and any(touchesRealOptional(m) for m in mods)):
                    continue
                for h in handlers:
                    for st in h.body:
                        if (isinstance(st, ast.Assign) and isinstance(st.value, ast.Constant)
                                and st.value.value is None):
                            backed |= {t.id for t in st.targets if isinstance(t, ast.Name)}
            pkgDots = rel[:-len("/__init__.py")].replace("/", ".")
            try:
                fm = importlib.import_module(pkgDots)
            except Exception:
                continue
            liveNulls = {n for n in dir(fm) if not n.startswith("_") and getattr(fm, n, "?") is None}
            unbacked = sorted(liveNulls - backed)
            if unbacked:
                offenders.append(f"{pkgDots}:{unbacked[:5]}")
        assert not offenders, (
            f"这些门面上的 None 公开符号没有「触及第三方的兜底」作出处（＝占位符残留）：{offenders[:6]}")
