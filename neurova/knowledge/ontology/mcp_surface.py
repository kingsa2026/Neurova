# -*- coding: utf-8 -*-
"""本体 MCP 工具面 curated 名册（对照研究 P2-1，2026-11-15）。

对方经验（auto-ontology `mcp/tools.py`）：87 个 OpenAPI 操作只暴露 7 个
curated 工具——「工具面是给模型用的，不是 API 文档的镜像」；新端点默认
不可见（catch-all exclude），要暴露必须在此点名。

本仓 adapting：MCP server 的工具经 `@_SERVER.tool()` 注册，docstring 即
描述。本名册承担两件事：

- **allowlist**：广告出来的工具名必须与本名册完全一致——新工具注册而未
  登记 curated，守卫当场红（防「顺手加一个、模型面静默变宽」）；
- **when_to_use**：每个工具一句「何时该用它」的行为指引（prompt 语言），
  与 docstring 的「是什么」互补；skill/文档引用这里，不复制工具表。

只读名册，无行为；治理语义见各工具 docstring。
"""

from __future__ import annotations

from typing import Tuple

CURATED_TOOLS: Tuple[dict, ...] = (
    {"name": "ontology_query",
     "when_to_use": "先查业务词在本部署里的含义与关系，再回答依赖这些词的问题。"},
    {"name": "ontology_validate",
     "when_to_use": "提交断言前自查合法性（dry-run），被拒就改写而不是硬交。"},
    {"name": "fact_submit",
     "when_to_use": "把一条业务断言写入知识底座；走逐字可核闸与异步人审兜底。"},
    {"name": "ontology_sparql",
     "when_to_use": "需要图模式查询（SPARQL 投影）时用；简单词匹配用 ontology_query。"},
    {"name": "ontology_abduce",
     "when_to_use": "反向搜索「什么前提能解释这个结论」，用于假设排查。"},
    {"name": "ontology_community_search",
     "when_to_use": "找与某主体同社区的关联主体（GraphRAG 分簇读数）。"},
    {"name": "graph_search",
     "when_to_use": "从事实图谱走多跳找关联证据；术语/本体面请走 ontology_query。"},
    {"name": "ontology_decision_record",
     "when_to_use": "把一项决策作为一等对象记台账（决策、依据、选项）。"},
    {"name": "ontology_decision_link",
     "when_to_use": "在决策之间建立因果/依赖链接（如「基于」「取代」）。"},
    {"name": "ontology_decision_trace",
     "when_to_use": "沿决策链接追溯来龙去脉（上游依据/下游影响）。"},
    {"name": "ontology_decision_precedents",
     "when_to_use": "按情境检索相似判例，回答「以前这种情况怎么裁的」。"},
    {"name": "ontology_simulate",
     "when_to_use": "先演后决：对假设注入做零生产写推演，拿 diff 影响报告。"},
    {"name": "ontology_act",
     "when_to_use": "执行已登记的本体动作（经 ToolExecutor 与治理链）。"},
    {"name": "ontology_state",
     "when_to_use": "查主体当前状态机状态与合法迁移，再决定下一步动作。"},
    {"name": "ontology_compute",
     "when_to_use": "对主体的登记函数做只读 dry 求值；要落结论走事实提交。"},
    {"name": "ontology_derive",
     "when_to_use": "求规则引擎对某主体的派生结论，并带回推导溯源。"},
    {"name": "ontology_answerability",
     "when_to_use": "回答前先做覆盖预检：coverage 低就向用户澄清，不要硬答。"},
    {"name": "ontology_readiness",
     "when_to_use": "会话开始时探一次部署就绪态（术语/事实/目录/源），避免静默死胡同。"},
    {"name": "team_list",
     "when_to_use": "派团前先看固定团队名册与成员职责，选对团队再 dispatch。"},
    {"name": "team_dispatch",
     "when_to_use": "把整个固定团队按名册派活（多路 spawn+依赖编排，治理照走）；单成员任务直接 spawn。"},
    {"name": "project_list",
     "when_to_use": "先列当前可见项目拿 project_id，再进详情或协作房间。"},
    {"name": "project_detail",
     "when_to_use": "查单个项目的成员/可见性/状态与团队任务计数，判断能否协作接入。"},
)


def curatedNames() -> set:
    return {entry["name"] for entry in CURATED_TOOLS}
