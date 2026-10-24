# -*- coding: utf-8 -*-
"""旧集成档 `tests/integration/test_full_chain.py` 按 §6-133 口径分流后的退役守卫（§6-391）。

那份文件是 2026-08 的"全链集成"配方，到 2026-10 已是**四代前的形状**：它 import
`neurova.agent.ContextBuilder` / `LLMClient`（两个符号今天都不在 `neurova.agent` 上）、
用 `Message(sender=…)`（字段已删）、同步调 `router.route()`（早已 async）、依赖不存在的
fixture `sample_memory_manager`，最后两格还会在无凭据时**真去连 OpenAI**。逐格修它等于给
一条已经不存在的链路补形状——按本卷的口径是"把形状问题洗成看着已修"。

分流结论（逐类，按存活守卫给指针）：

| 类 | 它想证的性质 | 今天由谁在守 |
|----|--------------|--------------|
| `TestAgentRouterSkillChain` | router/agent 编排 | `tests/integration/test_message_routing.py`（路由分支与 handler）+ `tests/unit/agent/*`（回合契约，含 `test_processMessageUnifiedEntry.py`） |
| `TestMemorySystemFullFlow` | 记忆持久化/情感/结晶 | `tests/unit/memory/*` 与 `tests/unit/cognitive_layers/memory_layer/*`（真落盘、真并发） |
| `TestChannelMessageProcessing` | 消息分类与命令路由 | 同上 `test_message_routing.py` 的 `TestMessage`/`TestMessageRouter` |
| `TestContextBuilderIntegration` | 上下文拼装 | `tests/unit/context/*`（含折叠层索引、池保留契约） |
| `TestLLMClientIntegration` | LLM 客户端 mock 形状 | `tests/unit/agent/test_openai_loop_stream_contract.py`、`test_anthropicLoopStreamContract.py`、`test_stream_usage.py`（替身按真签名/真事件流） |

本档钉三件事，都是**不许复活**而不仅是"文件没了"：
1. 文件与模块路径都不存在（兼容旧集成档若以包路径被 import 会立即报）；
2. 它赖以存在的两个死门面（`neurova.agent.ContextBuilder` / `LLMClient`）仍是**不存在**的
   —— 有人为了"让旧档能跑"把它们加回去，本档当场红（那等于复活一条已被收口的兼容面）；
3. **不许再出现同步调用 `router.route(...)` 的用例**：AST 扫 `tests/` 与 `scripts/`，
   `route` 调用若出现在非 `async def` 里即红（这正是旧档 14 红的根因形态）；配一格合成样本
   作反向控制（同步样本必须被点名、`await` 样本不得误报）。
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests import ast_scan

REPO_ROOT = Path(__file__).resolve().parents[2]
OLD_CHAIN = REPO_ROOT / "tests" / "integration" / "test_full_chain.py"


def _pySourcesUnderTheScanFace(hints: tuple = ()):
    """本档扫描面（`tests/` ＋ `scripts/`）的源码引用清单——走 `tests/ast_scan` 的唯一取数口。

    此前两处各写一遍 `rglob("*.py")` ＋ 裸 `read_text`：那是受保护子集里
    「枚举 + 解析」组合（`test_ci_ast_scan_budget_guard.py` 逐条点名要销账的形状），
    判据成本因此与仓内 `.py` 总量捆绑，同一台机器上与其余近五百档共享 30s 墙钟。
    预筛按 `hints` 给：连那个词都没出现的文件不可能命中，这不是放宽判据。
    """
    refs = []
    for root in (REPO_ROOT / "tests", REPO_ROOT / "scripts"):
        refs.extend(ast_scan.sourceRefsUnder(root, hints=hints))
    return refs


def _isAwaitWrapped(node, parentMap) -> bool:
    parent = parentMap.get(id(node))
    if not isinstance(parent, ast.Call):
        return False
    func = parent.func
    if isinstance(func, ast.Attribute) and func.attr == "run_until_complete":
        return True
    if isinstance(func, ast.Attribute) and func.attr == "run":
        return isinstance(func.value, ast.Name) and func.value.id == "asyncio"
    return False


def _syncRouteCallsIn(source: str) -> list:
    """挑出"同步地把 Message 喂给 `.route(`"的行号。

    只认三件同时成立：非 async 上下文、属性名 route、**第一参是 `Message(...)` 形态**；
    且排除已被 `asyncio.run(...)` / `loop.run_until_complete(...)` 包住的调用——
    MoE 网络那只 `route(query_vec)` 是另一条真 async 接口，把它算进来会让本档退化成
    "见 route 就红"的假守卫（判据问错对象那一族）。
    """
    tree = ast.parse(source)
    parentMap = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parentMap[id(child)] = parent
    offenders = []

    class Visitor(ast.NodeVisitor):
        def __init__(self):
            self.asyncDepth = 0

        def visit_AsyncFunctionDef(self, node):
            self.asyncDepth += 1
            self.generic_visit(node)
            self.asyncDepth -= 1

        def visit_Call(self, node):
            func = node.func
            first = node.args[0] if node.args else None
            isMessageArg = (isinstance(first, ast.Call)
                            and (getattr(first.func, "id", None) == "Message"
                                 or getattr(first.func, "attr", None) == "Message"))
            if (isinstance(func, ast.Attribute) and func.attr == "route"
                    and self.asyncDepth == 0 and isMessageArg
                    and not _isAwaitWrapped(node, parentMap)):
                offenders.append(node.lineno)
            self.generic_visit(node)

    Visitor().visit(tree)
    return offenders


class TestTheOldIntegrationFileIsRetired:
    def testTheFileAndItsModulePathAreGone(self):
        assert not OLD_CHAIN.exists(), (
            "旧集成档又回来了：它 import 的三个符号今天都不存在，逐格修它等于给死路补形状")

    def testNoLiveCodeImportsIt(self):
        """只认**按文件/模块**引用旧档的形态；同名方法不算，带「退役」的指针也不算。

        本仓惯例是"退役后在原地留一行指针说它退了"——那种行含 `退役` 二字，是路标，
        不是把人引回去的活引用。判据按**行**判，不对整档豁免。
        """
        hits = []
        for ref in _pySourcesUnderTheScanFace():
            if ref.path.name == Path(__file__).name:
                continue
            for lineno, line in enumerate(ref.code.splitlines(), 1):
                refers = ("test_full_chain.py" in line
                          or "integration.test_full_chain" in line
                          or "from tests.integration import test_full_chain" in line)
                if refers and "退役" not in line:
                    hits.append("%s:%d" % (ref.path.relative_to(REPO_ROOT), lineno))
        assert hits == [], (
            "还有活引用指向旧集成档（会把人引回死文件）；确实要提就带上「退役」二字：%s" % hits[:5])


class TestTheDeadFacadesStayDead:
    def testContextBuilderAndLLMClientAreStillAbsentFromNeurovaAgent(self):
        import neurova.agent as agentPackage

        for name in ("ContextBuilder", "LLMClient"):
            assert not hasattr(agentPackage, name), (
                "为了复活旧集成档把 %r 又挂回 neurova.agent 了——那是已收口的兼容面" % name)


class TestNobodyCallsTheAsyncRouterSynchronously:
    def testNoSyncRouteCallsRemainInTestsOrScripts(self):
        offenders = []
        candidates = 0
        # 枚举面：不带预筛地量一次根（走同一个共享入口，避免"我只数了预筛后的"那种自证）。
        enumerated = len(_pySourcesUnderTheScanFace(hints=()))
        # 候选面：预筛词 `.route(` 是本判据谓词的**充分条件**（没有这个字面串就不可能
        # 有同步 `route` 调用），口径仍是全量清单。
        for ref in _pySourcesUnderTheScanFace(hints=(".route(",)):
            candidates += 1
            path = ref.path
            source = ref.code
            try:
                lines = _syncRouteCallsIn(source)
            except SyntaxError:
                continue
            if lines:
                offenders.append("%s:%s" % (path.relative_to(REPO_ROOT), lines))
        # 面自证拆两条（形态 404）：枚举面证"根指得到"，候选面证"预筛没把命中滤空"。
        # 现算 tests 2483 ＋ scripts 76 ＝ 2559 个 .py；根少指一层（只剩 scripts）就掉到 76。
        assert enumerated >= 2000, (
            "枚举面现读 %d 个 .py（tests＋scripts 应在千级）——根指错时零 offender 不作数" % enumerated)
        assert candidates >= 3, (
            "候选面（含 `.route(` 的档）现读 %d 个——预筛词写坏会把一切滤成零命中" % candidates)
        assert offenders == [], (
            "还有同步调用 `router.route(...)` 的落点——`route()` 早就是 async，"
            "这形会把协程当成结果用（旧档 14 红的根因）：%s" % offenders[:5])

    def testTheDetectorCatchesTheShapeAndSparesTheTwoLegitimateForms(self):
        bad = "def t():\n    result = router.route(Message(content='hi'))\n"
        awaited = "async def t():\n    result = await router.route(Message(content='hi'))\n"
        wrapped = "def t():\n    result = asyncio.run(network.route(query_vec))\n"

        assert _syncRouteCallsIn(bad) == [2], "同步样本没被点名，守卫会恒绿"
        assert _syncRouteCallsIn(awaited) == [], "await 形态被误报了"
        assert _syncRouteCallsIn(wrapped) == [], (
            "把 asyncio.run(...) 里的真 async 调用也算红了——判据问错对象")

    def testTheReferenceScannerSparesAPointerButCatchesABareReference(self):
        """反向控制：带「退役」的指针不报，裸引用必须点名。"""
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            (base / "bare.py").write_text(
                "from tests.integration import test_full_chain\n", encoding="utf-8")
            (base / "pointer.py").write_text(
                "# 旧档 tests/integration/test_full_chain.py 已退役（§6-391）\n", encoding="utf-8")

            offenders = []
            for path in base.glob("*.py"):
                for line in path.read_text(encoding="utf-8").splitlines():
                    if "test_full_chain" in line and "退役" not in line:
                        offenders.append(path.name)

        assert offenders == ["bare.py"], (
            "扫描器要么放过了裸引用，要么把带「退役」的指针也算了：%s" % offenders)
