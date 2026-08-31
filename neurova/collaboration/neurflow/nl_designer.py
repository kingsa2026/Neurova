"""
自然语言画布设计器（R-8）

用户用自然语言描述流程目标，Agent 经 LLM 生成 WorkflowDefinition JSON，
节点类型白名单校验后转画布快照（复用 canvas_bridge.definition_to_canvas）。

安全:
  - 节点类型仅允许 node_registry 注册表已知类型（未知节点丢弃，防注入任意类型）
  - 生成结果 JSON 解析失败/字段缺失 → 结构化错误，不抛异常、不污染画布
"""

import json
from typing import Any, Callable, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

_LLM_PROMPT = """你是一个工作流设计助手。根据用户描述，设计一个 NeurFlow 工作流。
输出必须是一个 JSON 对象（不要 markdown 代码块），结构如下：
{{
  "name": "流程名称",
  "description": "一句话说明",
  "nodes": [
    {{"id": "n1", "type": "<node_type>", "label": "节点名",
      "position": {{"x": 40, "y": 80}}, "config": {{"<字段>": "<值>"}}}}
  ],
  "edges": [
    {{"source": "n1", "target": "n2", "source_handle": "out", "target_handle": "input"}}
  ]
}}

可用节点类型（只允许用这些）:
- builtin:start, builtin:end, builtin:llm, builtin:agent, builtin:condition,
  builtin:memory-load, builtin:memory-save, builtin:text_input, builtin:media_input,
  builtin:output, builtin:knowledge_base, builtin:remote_api
LLM 节点 config 示例: {{"prompt": "任务提示", "model_name": "auto", "model_provider": "auto", "temperature": 0.7, "max_tokens": 2048}}
Agent 节点 config 示例: {{"agent_id": "default", "task": "任务描述"}}
知识库节点 config 示例: {{"kb_type": "iflow", "query": "检索词", "limit": 5}}

节点位置请横向排列（x 递增 220），首节点为 builtin:start、末节点为 builtin:end，
边用源节点 outputs 与目标节点 inputs 的端口 id 连接。

用户描述: {user_prompt}
请只输出 JSON。"""


def sanitize_node_types(nodes: List[Dict[str, Any]], known_types) -> List[Dict[str, Any]]:
    """剔除未知类型的节点（白名单：仅注册表已知节点类型）。"""
    result = []
    for node in nodes or []:
        ntype = (node or {}).get("type", "")
        if ntype in known_types:
            result.append(node)
        else:
            logger.debug("[NL设计] 丢弃未知节点类型: %s", ntype)
    return result


def parse_generated_workflow(text: str) -> Optional[Dict[str, Any]]:
    """解析 LLM 输出 JSON（防御 markdown 代码块包裹）；不合法返回 None。"""
    if not text:
        return None
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        data = json.loads(raw)
    except Exception:
        # 尝试截取首个 { 到最后一个 }
        try:
            s, e = raw.index("{"), raw.rindex("}")
            data = json.loads(raw[s : e + 1])
        except Exception:
            return None
    if not isinstance(data, dict):
        return None
    if not data.get("nodes"):
        return None
    return data


async def _call_agent_llm(prompt: str, agent_id: str = "default", model: Optional[str] = None) -> str:
    """调用 Agent LLM 生成工作流（测试可 monkeypatch 为 async）。

    agent_id: 指定用户已有的 Agent（其独立人设/记忆/模型）；不存在回退 default。
    model: 可选，覆盖 Agent 当前模型（Agent.chat 的 hot-swap 路由）。
    """
    from neurova.api.endpoints import get_agent_instance

    agent = get_agent_instance(agent_id)
    if not agent:
        agent = get_agent_instance("default")
    if not agent:
        raise RuntimeError(f"未找到 agent: {agent_id}")
    response = await agent.chat(user_input=prompt, stream=False, model=model)
    if isinstance(response, dict):
        return str(response.get("text", ""))
    return str(response)


def _normalize_edge_ports(
    canvas: Dict[str, Any], registry
) -> Dict[str, Any]:
    """把边端点端口归一化为注册表真实端口（R-8 连线悬空修复）。

    LLM 生成边常用 out/output/input 等通用端口名，但各节点真实端口不同
    （start→output、text_input→text、knowledge_base→results、llm→input/output）。
    端口不匹配时画布连线悬空。归一化规则：
      - source_handle 必须 ∈ 源节点 outputs；否则取 outputs[0]，源节点无输出则弃边
      - target_handle 必须 ∈ 目标节点 inputs；否则取 inputs[0]，目标节点无输入则弃边
    """
    nodes = canvas.get("nodes", [])
    node_ports: Dict[str, Dict[str, List[str]]] = {}
    for n in nodes:
        node_ports[str(n.get("id"))] = {
            "inputs": [str(p.get("id")) for p in (n.get("inputs") or []) if isinstance(p, dict)],
            "outputs": [str(p.get("id")) for p in (n.get("outputs") or []) if isinstance(p, dict)],
        }

    kept_edges = []
    for e in canvas.get("edges", []):
        src = (e.get("source") or {}).get("nodeId", "") if isinstance(e.get("source"), dict) else ""
        tgt = (e.get("target") or {}).get("nodeId", "") if isinstance(e.get("target"), dict) else ""
        src_ports = node_ports.get(str(src), {}).get("outputs", [])
        tgt_ports = node_ports.get(str(tgt), {}).get("inputs", [])
        if not src_ports or not tgt_ports:
            continue  # 源/目标节点缺少对应端口 → 边无法连线，丢弃
        src_port = (
            (e.get("source") or {}).get("portId", "") if isinstance(e.get("source"), dict) else ""
        )
        tgt_port = (
            (e.get("target") or {}).get("portId", "") if isinstance(e.get("target"), dict) else ""
        )
        if src_port not in src_ports:
            src_port = src_ports[0]
        if tgt_port not in tgt_ports:
            tgt_port = tgt_ports[0]
        e = dict(e)
        e["source"] = {"nodeId": str(src), "portId": src_port}
        e["target"] = {"nodeId": str(tgt), "portId": tgt_port}
        kept_edges.append(e)

    canvas = dict(canvas)
    canvas["edges"] = kept_edges
    return canvas


async def generate_canvas_from_nl(
    user_prompt: str, agent_id: str = "default", model: Optional[str] = None
) -> Dict[str, Any]:
    """自然语言 → 画布快照（nodes/edges）。

    agent_id: 指定用于编排设计的 Agent（非 default 亦可）。
    model: 可选的模型热切换（覆盖 Agent 当前模型）。

    Returns:
        {"status": "success"|"failed", "data": {"nodes": [...], "edges": [...], "notes": [...]}} /
        {"status": "failed", "error": "..."}
    """
    from neurova.collaboration.canvas_bridge import definition_to_canvas
    from neurova.collaboration.neurflow.node_registry import get_node_registry

    prompt = _LLM_PROMPT.format(user_prompt=user_prompt)
    try:
        text = await _call_agent_llm(prompt, agent_id=agent_id, model=model)
    except Exception as e:  # noqa: BLE001
        return {"status": "failed", "error": f"LLM 调用失败: {e}"}

    wf = parse_generated_workflow(text)
    if not wf:
        return {"status": "failed", "error": "LLM 输出不是有效的工作流 JSON"}

    registry = get_node_registry()
    registry.ensure_builtin()
    known = {d.type for d in registry.list_all()}
    wf["nodes"] = sanitize_node_types(wf.get("nodes", []), known)
    if not wf["nodes"]:
        return {"status": "failed", "error": "生成结果无合法节点（类型不在白名单）"}

    try:
        from neurova.collaboration.neurflow.models import WorkflowDefinition

        raw_nodes = wf["nodes"]
        node_ids = {str(n.get("id")) for n in raw_nodes}
        raw_edges = []
        for idx, edge in enumerate(wf.get("edges", [])):
            src = str(edge.get("source") or "")
            tgt = str(edge.get("target") or "")
            if src not in node_ids or tgt not in node_ids:
                logger.debug("[NL设计] 忽略无效边: %s -> %s", src, tgt)
                continue
            raw_edges.append(
                {
                    "id": edge.get("id") or f"e{idx + 1}",
                    "source": src,
                    "target": tgt,
                    "source_handle": edge.get("source_handle"),
                    "target_handle": edge.get("target_handle"),
                }
            )

        definition = WorkflowDefinition.from_dict(
            {
                "id": f"wf-nl-{hash(user_prompt) & 0xFFFFFF:06x}",
                "name": wf.get("name", "NL 设计流程"),
                "description": wf.get("description", ""),
                "nodes": raw_nodes,
                "edges": raw_edges,
                "variables": [],
                "tags": ["nl-human"],
                "category": "designer",
                "author": agent_id,
                "status": "draft",
            }
        )
        canvas = definition_to_canvas(definition, name=wf.get("name", "NL 设计流程"))
    except Exception as e:  # noqa: BLE001
        return {"status": "failed", "error": f"工作流转换失败: {e}"}

    # R-8 连线修复：端口归一化（LLM 常用 out/output，真实端口可能不同）
    canvas = _normalize_edge_ports(canvas, registry)

    return {
        "status": "success",
        "data": {
            "nodes": canvas.get("nodes", []),
            "edges": canvas.get("edges", []),
            "name": wf.get("name", "NL 设计流程"),
            "description": wf.get("description", ""),
        },
    }
