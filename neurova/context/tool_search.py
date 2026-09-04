"""A6 Tool Search（P2，docs/Neurova_OpenClaw工具技能专项对比 §1.3 A6）。

大工具目录的检索式延迟加载（对齐 OC Tool Search 的 directory 模式朴素版）：
- 非 direct 工具的参数 schema 不进 prompt，只留有界能力目录（name+description）
- 模型经三个控制工具检索/取 schema/调用：tool_search / tool_describe / tool_call
- 检索为静态 BM25（Okapi K1=1.2, B=0.75），零学习信号（与 OC 同构；
  学习信号在工具权重棘轮层，两层正交）
- tool_call 经 ToolExecutor 正常执行——治理预检/审批/肌肉记忆全链路生效
- 激活条件：NEUROVA_TOOL_SEARCH=1 且工具数 > NEUROVA_TOOL_SEARCH_MIN_CATALOG（默认 40）

控制工具的执行由 ToolExecutor.execute 入口拦截（见该文件 A6 注释）。
"""

import math
import re
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

CONTROL_TOOL_NAMES = ("tool_search", "tool_describe", "tool_call")

_BM25_K1 = 1.2
_BM25_B = 0.75

_TOKEN_SPLIT = re.compile(r"[^a-z0-9\u4e00-\u9fff]+")

# 每次构建目录时刷新（进程级最后目录——Executor 的 tool_search/tool_describe 读它；
# 单网关进程语义下与 OC 的 per-session catalog 等价收敛）
_ACTIVE_CATALOG: List[Dict[str, Any]] = []


def _tokenize(text: str) -> List[str]:
    return [t for t in _TOKEN_SPLIT.split(str(text).lower()) if t]


def build_catalog(tools: List[Dict]) -> List[Dict[str, Any]]:
    """从 OpenAI function schema 列表构建目录条目（不含参数 schema 本身）。"""
    entries: List[Dict[str, Any]] = []
    for t in tools or []:
        fn = (t or {}).get("function") or {}
        name = fn.get("name")
        if not name:
            continue
        params = (fn.get("parameters") or {}).get("properties") or {}
        params_text = " ".join(str(k) for k in params)
        entries.append(
            {
                "name": name,
                "description": fn.get("description", "") or "",
                "schema": t,
                "params_text": params_text,
            }
        )
    return entries


def search_catalog(query: str, entries: List[Dict[str, Any]], limit: int = 8) -> List[Dict[str, Any]]:
    """Okapi BM25 词法检索（静态；与 OC tool-search-ranking 同参数）。"""
    if not query or not entries:
        return []
    docs = [_tokenize(f"{e['name']} {e['description']} {e.get('params_text', '')}") for e in entries]
    doc_count = len(docs)
    avgdl = sum(len(d) for d in docs) / max(1, doc_count)
    df: Dict[str, int] = {}
    for d in docs:
        for term in set(d):
            df[term] = df.get(term, 0) + 1

    q_terms = _tokenize(query)
    scored: List[tuple] = []
    for idx, doc in enumerate(docs):
        score = 0.0
        dl = len(doc) or 1
        for term in q_terms:
            tf = doc.count(term)
            if not tf:
                continue
            idf = math.log(1 + (doc_count - df.get(term, 0) + 0.5) / (df.get(term, 0) + 0.5))
            score += idf * (tf * (_BM25_K1 + 1)) / (tf + _BM25_K1 * (1 - _BM25_B + _BM25_B * dl / avgdl))
        if score > 0:
            scored.append((score, idx))
    scored.sort(reverse=True)
    return [entries[idx] for _, idx in scored[: max(1, limit)]]


def render_directory(entries: List[Dict[str, Any]], max_chars: int = 18000) -> str:
    """有界能力目录（只有 name+description，schema 永不进 prompt）。"""
    lines = [f"- {e['name']}: {e['description']}" for e in entries]
    body = "\n".join(lines)
    if len(body) <= max_chars:
        return body
    kept = []
    used = 0
    for line in lines:
        if used + len(line) + 1 > max_chars:
            break
        kept.append(line)
        used += len(line) + 1
    kept.append(f"…（其余 {len(entries) - len(kept)} 个工具可用 tool_search 检索）")
    return "\n".join(kept)


def control_tool_schemas() -> List[Dict[str, Any]]:
    """三个控制工具的 OpenAI schema（直连工具面，永不进隐藏目录）。"""
    return [
        {
            "type": "function",
            "function": {
                "name": "tool_search",
                "description": (
                    "Search the hidden tool catalog by intent. Returns matching tool "
                    "names and descriptions (no schemas). Use tool_describe to load a "
                    "full schema before tool_call."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "What you want to do"},
                        "limit": {"type": "integer", "description": "Max results (default 8)"},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "tool_describe",
                "description": "Load the full parameter schema of one hidden tool by exact name.",
                "parameters": {
                    "type": "object",
                    "properties": {"name": {"type": "string", "description": "Exact tool name"}},
                    "required": ["name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "tool_call",
                "description": (
                    "Call a hidden tool by exact name with its full argument object. "
                    "Describe the tool first to learn the schema. Execution goes through "
                    "the normal policy/approval pipeline."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Exact tool name"},
                        "arguments": {"type": "object", "description": "Tool arguments"},
                    },
                    "required": ["name"],
                },
            },
        },
    ]


def apply_tool_search_compaction(
    tools: List[Dict],
    direct_names: List[str],
    min_catalog: int = 40,
    max_chars: int = 18000,
) -> Optional[List[Dict]]:
    """目录压缩（A6 主入口）。不满足激活条件返回 None（调用方透传原清单）。

    激活条件由调用方判断（env + 规模）；本函数只做纯变换：
    - direct_names 中的工具与控制工具保持模型可见
    - 其余进隐藏目录，仅以有界 directory 描述（由调用方注入 prompt）
    """
    entries = build_catalog(tools)
    hidden = [e for e in entries if e["name"] not in set(direct_names)]
    if len(hidden) < min_catalog:
        return None
    visible = [t for t in tools if ((t or {}).get("function") or {}).get("name") in set(direct_names)]
    visible.extend(control_tool_schemas())
    global _ACTIVE_CATALOG
    _ACTIVE_CATALOG = hidden
    logger.info("Tool Search 目录压缩: %d 直连 + %d 隐藏", len(visible) - 3, len(hidden))
    return visible


def get_active_catalog() -> List[Dict[str, Any]]:
    return _ACTIVE_CATALOG


def handle_control_tool(name: str, params: Dict) -> Dict:
    """tool_search / tool_describe 的执行体（ToolExecutor 拦截后调用）。"""
    params = params or {}
    if name == "tool_search":
        hits = search_catalog(
            str(params.get("query", "")),
            get_active_catalog(),
            limit=int(params.get("limit") or 8),
        )
        return {
            "results": [
                {"name": h["name"], "description": h["description"]} for h in hits
            ],
            "hint": "Use tool_describe to load a full schema, then tool_call to execute.",
        }
    if name == "tool_describe":
        wanted = str(params.get("name", ""))
        for e in get_active_catalog():
            if e["name"] == wanted:
                return {"schema": e["schema"]}
        return {"error": f"工具 {wanted} 不在隐藏目录中（可能是直连工具，直接调用即可）"}
    return {"error": f"未知控制工具: {name}"}
