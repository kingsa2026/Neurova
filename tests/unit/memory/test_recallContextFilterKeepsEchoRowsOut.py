# -*- coding: utf-8 -*-
"""上下文侧过滤：回声行（推理链）永不进上下文，也不得因检索被记账复活（§6-207 裁定乙前半）。

事故成因（2026-09-05；`reasoning_trace_manager.py:150-156` 的注释与档案 §4-2 都记着）：
每轮对话把整条推理链（含"晚上好→晚上好呀"这类寒暄）存成记忆，而统一检索**不带 category
过滤** ⇒ 寒暄链被当相关记忆捞回上下文，形成回声污染。§6-206 把那道门接进治理面之后，
"门能开"和"开了会不会污染"是两件事——本批先钉住后者，再谈把点赞回执接进结晶器
（用户裁定乙的顺序：先过滤器，后票据）。

四条契约与各自的防假绿装置：
1. 回声行**经真生产路**造出来（开闸 → 真 `finish_trace` → flush 进正文库）——前置格；
2. 引擎与统一检索两路都取不到它；判据按**类别**而不是按 id（跨作用域行的 id 带 `\\x1f` 前缀，
   按 id 取交集会因两侧形状不同而"永远为空"＝假绿）；
3. 取不到之外还要证"**这条查询本来捞得到东西**"：同一次查询下 `crystallized` 与普通正文行
   照常返回——这两格就是那次对照，缺了它们"没返回"可能只是没匹配上；
4. 过滤必须发生在**记账之前**：先记账再过滤，被丢掉的行也已经 +10，冷档就被自己这次命中
   复活（与工单 017 那条同形）。

另有一枚枚举报示：`UnifiedMemoryNode(category="X")` 的每个字面量都必须在
`CONTEXT_VISIBILITY` 里显式表态（True＝可进上下文 / False＝永不进）；表与谓词全仓各只准
定义一处。形状是"默认放行 + 显式禁"——普通正文行没有 `cse_category`，把它们并进白名单会
当场掐死现网检索。
"""
from __future__ import annotations

import ast
import asyncio
import sys
from pathlib import Path

from tests.cognitive_body_store import bodyManager, cognitiveEngine

NEUROVA = Path(__file__).resolve().parents[3] / "neurova"
sys.path.insert(0, str(NEUROVA.parent))  # 仓根进 sys.path，`from tests import ast_scan` 才取得到

from tests import ast_scan  # noqa: E402


def _neurovaRel(path) -> str:
    """读数口径保持"相对 `neurova/`"——只换取数入口，报错信息一字不变。"""
    return ast_scan.relativeToRepo(path)[len("neurova/"):]
ECHO = "reasoning_trace"
ECHO_QUERY = "晚上好"


def _isEcho(item) -> bool:
    """节点或结果字典都问同一个问题：这条是不是推理链回声。"""
    if isinstance(item, dict):
        return item.get("category") == ECHO
    return getattr(item, "category", None) == ECHO


def _writeEchoRow(manager, engine, monkeypatch) -> None:
    """真生产路：开闸 → 真 ReasoningTraceManager 走完一轮 → flush 进正文库。"""
    from neurova.cognitive_layers.memory_layer.reasoning_trace_manager import ReasoningTraceManager

    monkeypatch.setenv("NEUROVA_TRACE_PERSIST", "1")
    traceManager = ReasoningTraceManager(engine=engine)
    tid = traceManager.start_trace(ECHO_QUERY)
    traceManager.add_step(tid, "retrieve", ECHO_QUERY, "找到 0 条记忆")
    traceManager.finish_trace(tid, "晚上好呀！😊", total_tokens=42)
    engine.close()


def _echoBodyRow(manager):
    for mem in manager.iterBodyMemories(limit=500):
        meta = mem.metadata if isinstance(mem.metadata, dict) else {}
        if meta.get("cse_category") == ECHO:
            return mem
    return None


class TestEchoRowExistsBeforeWeFilterIt:
    def test_theProductionPathActuallyWroteIt(self, tmp_path, monkeypatch):
        """前置自证：闸门开着时真生产路确实往正文库写了一行推理链。

        少了这一格，下面"检索取不到它"可能只是因为压根没写进去。
        """
        manager = bodyManager(tmp_path)
        engine = cognitiveEngine(tmp_path, manager=manager)
        _writeEchoRow(manager, engine, monkeypatch)

        row = _echoBodyRow(manager)
        assert row is not None, "真生产路没造出回声行——本文件其余读数都不可信"
        assert ECHO_QUERY in row.content


class TestEchoNeverEntersContext:
    def test_engineRetrieveDropsIt(self, tmp_path, monkeypatch):
        manager = bodyManager(tmp_path)
        engine = cognitiveEngine(tmp_path, manager=manager)
        _writeEchoRow(manager, engine, monkeypatch)
        assert _echoBodyRow(manager) is not None

        assert not any(_isEcho(n) for n in engine.retrieve(ECHO_QUERY, limit=10)), (
            "寒暄推理链被检索回上下文（2026-09-05 回声污染的读侧成因）")

    def test_l0BufferedEchoIsDroppedToo(self, tmp_path, monkeypatch):
        """还压在 L0、没 flush 的那一份也过不去——两条支路共用同一个谓词。"""
        manager = bodyManager(tmp_path)
        engine = cognitiveEngine(tmp_path, manager=manager)
        monkeypatch.setenv("NEUROVA_TRACE_PERSIST", "1")
        from neurova.cognitive_layers.memory_layer.reasoning_trace_manager import ReasoningTraceManager

        traceManager = ReasoningTraceManager(engine=engine)
        tid = traceManager.start_trace(ECHO_QUERY)
        traceManager.add_step(tid, "retrieve", ECHO_QUERY, "0 条")
        traceManager.finish_trace(tid, "晚上好呀", total_tokens=9)

        hits = engine.retrieve(ECHO_QUERY, limit=10)
        assert not any(_isEcho(n) for n in hits), "L0 里的回声行漏进上下文"

    def test_retrieverFaceDropsItToo(self, tmp_path, monkeypatch):
        """统一检索器经的是引擎同一个口，不许绕过过滤器。"""
        from neurova.cognitive_layers.memory_layer.unified_retriever import UnifiedRetriever

        manager = bodyManager(tmp_path)
        engine = cognitiveEngine(tmp_path, manager=manager)
        _writeEchoRow(manager, engine, monkeypatch)

        results = asyncio.run(UnifiedRetriever(engine=engine).retrieve(ECHO_QUERY, limit=10))
        assert not any(_isEcho(r) for r in results), "UnifiedRetriever 仍把回声行投进上下文"

    def test_droppedRowIsNotCredited(self, tmp_path, monkeypatch):
        """顺序要钉死：过滤在记账之前，被丢掉的行不许被 +10 复活。"""
        manager = bodyManager(tmp_path)
        engine = cognitiveEngine(tmp_path, manager=manager)
        _writeEchoRow(manager, engine, monkeypatch)
        row = _echoBodyRow(manager)
        before = (int(row.access_count or 0), float(row.temperature))

        engine.retrieve(ECHO_QUERY, limit=10)

        after = _echoBodyRow(manager)
        assert (int(after.access_count or 0), float(after.temperature)) == before, (
            "被丢掉的回声行仍被记账：%s → %s" % (before, (after.access_count, after.temperature)))


class TestFilterIsNotABlanketDenial:
    """同一次查询必须仍捞得到别的东西——否则"没返回"可能只是没匹配上。"""

    def test_crystallizedPatternStillEnters(self, tmp_path):
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import UnifiedMemoryNode

        manager = bodyManager(tmp_path)
        engine = cognitiveEngine(tmp_path, manager=manager)
        node = UnifiedMemoryNode(content="结晶：晚上好时先给结论再给理由", category="crystallized")
        engine.store(node)
        engine.close()

        hits = engine.retrieve(ECHO_QUERY, limit=10)
        assert any(getattr(n, "category", None) == "crystallized" for n in hits), (
            "crystallized 被误排除（过滤器成了总闸）或这条查询本来就捞不到东西（判据空转）")

    def testOrdinaryBodyRowStillEnters(self, tmp_path):
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import UnifiedMemoryNode

        manager = bodyManager(tmp_path)
        engine = cognitiveEngine(tmp_path, manager=manager)
        node = UnifiedMemoryNode(content="普通记忆：晚上好的问候也算闲聊")
        engine.store(node)
        engine.close()

        hits = engine.retrieve(ECHO_QUERY, limit=10)
        assert any(ECHO_QUERY in n.content for n in hits), "普通正文行也不返回了＝检索被整体掐死"


class TestCategoryVocabularyIsExplicitlyTriaged:
    """生产侧新增节点类别必须显式表态可见性，不许默认进上下文而不留痕。"""

    def _producerLiterals(self):
        found = {}
        surface = len(ast_scan.filesUnder(NEUROVA))
        assert surface > 500, f"扫描面现读 {surface} 个 .py（根＝neurova/）——根被改窄时「零命中」不代表干净"
        # 取数走 `tests/ast_scan.py` 的一次性入口 + 文本预筛：造过 `UnifiedMemoryNode(...)`
        # 的文件才会被解析（被赋值/被调用过的那个名字必然出现在源码文本里 ⇒ 预筛是充分条件）
        for path, node in ast_scan.transientNodes(NEUROVA, hints=("UnifiedMemoryNode",)):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else (
                func.attr if isinstance(func, ast.Attribute) else "")
            if name != "UnifiedMemoryNode":
                continue
            for kw in node.keywords:
                if kw.arg == "category" and isinstance(kw.value, ast.Constant) \
                        and isinstance(kw.value.value, str):
                    found.setdefault(kw.value.value, []).append(
                        "%s:%d" % (_neurovaRel(path), node.lineno))
        return found

    def test_everyProducerCategoryIsDeclared(self):
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import CONTEXT_VISIBILITY

        undeclared = sorted(set(self._producerLiterals()) - set(CONTEXT_VISIBILITY))
        assert undeclared == [], (
            "这些节点类别没在 CONTEXT_VISIBILITY 里表态（默认放行＝回声污染的老路）：%s"
            % undeclared)

    def test_declarationsAreBoolean(self):
        """表里写非布尔值会让 `is not False` 变成随手漂移的谓词。"""
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import CONTEXT_VISIBILITY

        odd = sorted(k for k, v in CONTEXT_VISIBILITY.items() if not isinstance(v, bool))
        assert odd == [], "这些项的可见性不是布尔：%s" % odd

    def test_theEchoCategoryFromTheAccidentIsDenied(self):
        """2026-09-05 那个类别必须禁——这一格是这批存在的理由。"""
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import (
            CONTEXT_VISIBILITY, mayEnterContext)

        assert CONTEXT_VISIBILITY[ECHO] is False
        assert mayEnterContext(ECHO) is False
        assert mayEnterContext("crystallized") is True
        assert mayEnterContext("general") is True, "普通正文行被默认掐死＝过滤器成了总闸"


def test_theVocabularyAndPredicateHaveExactlyOneHome(tmp_path, monkeypatch):
    """单源格（按代码形态数，不按词数）：表态表与谓词各自全仓只准定义一处。

    两侧各定义一遍就会各漂一遍——将来加新类别时只改一处，另一处静默放行。
    """
    names = {"CONTEXT_VISIBILITY", "mayEnterContext"}
    homes = {n: [] for n in names}
    # 一次性入口 + 两个词一起预筛（被定义过的那个名字必然出现在源码文本里）
    for path, node in ast_scan.transientNodes(NEUROVA, hints=tuple(sorted(names))):
        targets = []
        if isinstance(node, ast.Assign):
            targets = [tg.id for tg in node.targets if isinstance(tg, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target.id]
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            targets = [node.name]
        for tg in targets:
            if tg in names:
                homes[tg].append("%s:%d" % (_neurovaRel(path), node.lineno))
    for name, places in sorted(homes.items()):
        assert len(places) == 1, "%s 被定义了 %d 处（第二处即平行事实源）：%s" % (
            name, len(places), places)

    manager = bodyManager(tmp_path)
    engine = cognitiveEngine(tmp_path, manager=manager)
    _writeEchoRow(manager, engine, monkeypatch)
    assert not any(_isEcho(n) for n in engine.retrieve(ECHO_QUERY, limit=10))
