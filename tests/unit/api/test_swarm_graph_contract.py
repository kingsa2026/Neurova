# -*- coding: utf-8 -*-
"""P2-4 服务端投影契约钉子：后端 TypedDict ↔ 前端 TS 类型 ↔ 组件消费字段 三方一致。

对方 2106 行前端 traceParser 与平台私有 trace 结构强耦合是反面前车——本仓约定
**多代理可视化的一切语义解析在服务端完成，浏览器只拿 render-ready 结构**。这里把
三方钉在一起，任何一侧漂移即红：

1. 后端投影字段集单源：``swarm_graph_projection``（GraphNode/GraphEdge/GraphMeta/
   GraphProjection）与 ``candidate_projection``（CandidateProjectionEntry/
   CandidateBoardSnapshot）的 TypedDict；
2. 前端 TS 类型：``NeurUI/src/types/swarmGraph.ts`` 手抄对齐（字段名集合全等）；
3. 组件消费：``SwarmFlowPanel.vue`` 里 node./edge./meta. 的取字段必须都在 TS
   类型里（组件不得私自定义投影字段）；
4. 状态词汇：组件状态着色映射的键必须落在台账/蜂群状态词汇与候选状态词汇内。
"""

import re
from pathlib import Path
from typing import Dict, Set

from neurova.agent import candidate_projection
from neurova.agent import swarm_graph_projection as sgp
from neurova.agent.candidate_merge import CANDIDATE_STATUSES
from neurova.agent.swarm_support import SUBAGENT_STATUSES
from neurova.core import agent_run_store

_REPO = Path(__file__).resolve().parents[3]
_TS_TYPES = _REPO / "NeurUI" / "src" / "types" / "swarmGraph.ts"
_PANEL = _REPO / "NeurUI" / "src" / "components" / "chat" / "SwarmFlowPanel.vue"


def _tsInterfaceFields(name: str) -> Set[str]:
    """从 swarmGraph.ts 取 `export interface <name> {...}` 的字段名集合。"""
    source = _TS_TYPES.read_text(encoding="utf-8")
    marker = f"export interface {name} "
    start = source.index(marker)
    openAt = source.index("{", start)
    depth = 0
    for i in range(openAt, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                body = source[openAt + 1:i]
                break
    else:
        raise AssertionError(f"{name} 接口块未闭合")
    fields = set()
    for line in body.splitlines():
        line = line.strip()
        m = re.match(r"^(?:readonly\s+)?([A-Za-z_][A-Za-z0-9_]*)\??\s*:", line)
        if m:
            fields.add(m.group(1))
    return fields


def _tsTypeAliasValues(name: str) -> Set[str]:
    """取 `export type <name> = 'a' | 'b'` 的字面量值集合（分号可省，TS 合法）。"""
    source = _TS_TYPES.read_text(encoding="utf-8")
    m = re.search(rf"export type {name}\s*=\s*([^;\n]+)", source)
    assert m, f"swarmGraph.ts 缺 type {name}"
    return set(re.findall(r"'([^']+)'", m.group(1)))


def _typedDictFields(cls) -> Set[str]:
    return {k for k in cls.__annotations__ if not k.startswith("_")}


# ---------------------------------------------------------------------------
# 1. 后端 TypedDict ↔ 前端 TS 接口：字段名集合全等
# ---------------------------------------------------------------------------

def testGraphNodeFieldsMatchFrontendType():
    backend = _typedDictFields(sgp.GraphNode)
    frontend = _tsInterfaceFields("SwarmGraphNode")
    assert backend == frontend, (
        f"GraphNode 字段漂移——后端多 {sorted(backend - frontend)}，"
        f"前端多 {sorted(frontend - backend)}；三方（后端 schema/前端类型/组件）须同批改")


def testGraphEdgeFieldsMatchFrontendType():
    backend = _typedDictFields(sgp.GraphEdge)
    frontend = _tsInterfaceFields("SwarmGraphEdge")
    assert backend == frontend, (
        f"GraphEdge 字段漂移——后端多 {sorted(backend - frontend)}，"
        f"前端多 {sorted(frontend - backend)}")


def testGraphMetaFieldsMatchFrontendType():
    backend = _typedDictFields(sgp.GraphMeta)
    frontend = _tsInterfaceFields("SwarmGraphMeta")
    assert backend == frontend, (
        f"GraphMeta 字段漂移——后端多 {sorted(backend - frontend)}，"
        f"前端多 {sorted(frontend - backend)}")


def testGraphProjectionFieldsMatchFrontendType():
    backend = _typedDictFields(sgp.GraphProjection)
    frontend = _tsInterfaceFields("SwarmGraphProjection")
    assert backend == frontend, (
        f"GraphProjection 字段漂移——后端多 {sorted(backend - frontend)}，"
        f"前端多 {sorted(frontend - backend)}")


def testCandidateEntryFieldsMatchFrontendType():
    backend = _typedDictFields(candidate_projection.CandidateProjectionEntry)
    frontend = _tsInterfaceFields("CandidateProjectionEntry")
    assert backend == frontend, (
        f"CandidateProjectionEntry 字段漂移——后端多 {sorted(backend - frontend)}，"
        f"前端多 {sorted(frontend - backend)}")


def testCandidateSnapshotFieldsMatchFrontendType():
    backend = _typedDictFields(candidate_projection.CandidateBoardSnapshot)
    frontend = _tsInterfaceFields("CandidateBoardSnapshot")
    assert backend == frontend, (
        f"CandidateBoardSnapshot 字段漂移——后端多 {sorted(backend - frontend)}，"
        f"前端多 {sorted(frontend - backend)}")


# ---------------------------------------------------------------------------
# 2. 组件消费字段 ⊆ TS 类型（组件不得私自定义投影字段）
# ---------------------------------------------------------------------------

def _panelSource() -> str:
    """组件源码（剥掉 <style> 块——CSS 选择器里的 `.nf-node.nf-tone` 不是字段消费）。"""
    source = _PANEL.read_text(encoding="utf-8")
    styleAt = source.find("<style")
    return source[:styleAt] if styleAt != -1 else source


def testComponentNodeFieldsAreInsideContract():
    consumed = set(re.findall(r"\bnode\.([A-Za-z_][A-Za-z0-9_]*)", _panelSource()))
    unknown = consumed - _tsInterfaceFields("SwarmGraphNode")
    assert not unknown, f"SwarmFlowPanel 消费了契约外的 node 字段 {sorted(unknown)}"


def testComponentEdgeFieldsAreInsideContract():
    consumed = set(re.findall(r"\bedge\.([A-Za-z_][A-Za-z0-9_]*)", _panelSource()))
    unknown = consumed - _tsInterfaceFields("SwarmGraphEdge")
    assert not unknown, f"SwarmFlowPanel 消费了契约外的 edge 字段 {sorted(unknown)}"


def testComponentMetaFieldsAreInsideContract():
    consumed = set(re.findall(r"\bmeta\.([A-Za-z_][A-Za-z0-9_]*)", _panelSource()))
    unknown = consumed - _tsInterfaceFields("SwarmGraphMeta")
    assert not unknown, f"SwarmFlowPanel 消费了契约外的 meta 字段 {sorted(unknown)}"


# ---------------------------------------------------------------------------
# 3. 状态词汇对齐（沿 LEDGER_TO_WINDOW_STATUS 先例）
# ---------------------------------------------------------------------------

def testNodeStatusToneKeysStayInsideBackendVocabularies():
    """组件 run 节点着色映射的键 ⊆ 台账状态 ∪ 蜂群 run 状态。"""
    source = _panelSource()
    m = re.search(r"RUN_STATUS_TONE[^=]*=\s*\{", source)
    assert m, "SwarmFlowPanel 缺 RUN_STATUS_TONE 映射（节点按状态着色的唯一出口）"
    openAt = source.index("{", m.start())
    depth = 0
    for i in range(openAt, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                body = source[openAt:i + 1]
                break
    keys = set(re.findall(r"'([a-z_]+)'\s*:", body))
    vocabulary = set(agent_run_store.TERMINAL_STATUSES) | \
        set(agent_run_store.NON_TERMINAL_STATUSES) | set(SUBAGENT_STATUSES)
    unknown = keys - vocabulary
    assert not unknown, (
        f"RUN_STATUS_TONE 认了台账/蜂群词汇之外的状态 {sorted(unknown)}——"
        "后端加状态必须同批改前端着色，否则节点渲染成未知态")


def testCandidateStatusToneKeysStayInsideCandidateVocabulary():
    source = _panelSource()
    m = re.search(r"CANDIDATE_STATUS_TONE[^=]*=\s*\{", source)
    assert m, "SwarmFlowPanel 缺 CANDIDATE_STATUS_TONE 映射"
    openAt = source.index("{", m.start())
    depth = 0
    for i in range(openAt, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                body = source[openAt:i + 1]
                break
    keys = set(re.findall(r"'([a-zA-Z]+)'\s*:", body))
    unknown = keys - set(CANDIDATE_STATUSES)
    assert not unknown, f"CANDIDATE_STATUS_TONE 认了候选状态域之外的状态 {sorted(unknown)}"


def testEdgeTypesPinnedToV2FullSet():
    """D-A 拍板：图边集是 v2 四类（spawn/dependency/approval/candidate）。"""
    assert _tsTypeAliasValues("SwarmGraphEdgeType") == {
        "spawn", "dependency", "approval", "candidate"}
    source = _panelSource()
    for word in ("spawn", "dependency", "approval", "candidate"):
        assert word in source, f"SwarmFlowPanel 未区分 {word} 边型"


def testPanelDoesNotImportEventSemantics():
    """P2-4 红线：可视化组件不 import 事件语义、不做 trace 解释。"""
    source = _panelSource()
    banned = ["swarm_event_log", "traceParser", "parseTrace", "subagent_event",
              "SessionSyncEvent"]
    hits = [w for w in banned if w in source]
    assert not hits, f"SwarmFlowPanel 混入了事件/trace 语义 {hits}——渲染组件只吃投影"
