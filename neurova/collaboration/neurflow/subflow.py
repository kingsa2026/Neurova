"""
子工作流（subflow）核心逻辑（P2-4.3）

纯函数模块：input_mapping 解析、嵌套深度限制、循环检测、配置校验。
builtin.py 的 exec_subflow 薄壳负责存储/引擎对接；本模块零存储依赖。
"""

from typing import Any, Dict, Set


class SubflowDepthExceeded(Exception):
    """子工作流嵌套深度超限。"""


class SubflowCycleDetected(Exception):
    """子工作流引用成环（A→B→A 或自引用）。"""

DEFAULT_MAX_DEPTH = 5


def validate_subflow_config(config: Dict[str, Any]) -> str:
    """校验 subflow 节点配置；返回 workflow_id。"""
    workflow_id = (config or {}).get("workflow_id")
    if not workflow_id:
        raise ValueError("subflow node requires config['workflow_id']")
    return workflow_id


def resolve_input_mapping(
    mapping: Dict[str, Any],
    inputs: Dict[str, Any],
    node_results: Dict[str, Any],
) -> Dict[str, Any]:
    """把 input_mapping 解析为子工作流入参。

    支持前缀：
      "$input.key"      → inputs[key]
      "$node.<nid>.key" → node_results[nid]["output"][key]
    其余值原样透传（静态参数）。
    """
    resolved: Dict[str, Any] = {}
    for key, raw in (mapping or {}).items():
        if isinstance(raw, str) and raw.startswith("$input."):
            resolved[key] = (inputs or {}).get(raw[len("$input."):])
        elif isinstance(raw, str) and raw.startswith("$node."):
            parts = raw[len("$node."):].split(".", 1)
            nid = parts[0] if parts else ""
            leaf = parts[1] if len(parts) > 1 else ""
            output = (node_results or {}).get(nid, {})
            output_value = output.get("output") if isinstance(output, dict) else None
            if isinstance(output_value, dict):
                resolved[key] = output_value.get(leaf)
            else:
                resolved[key] = None
        else:
            resolved[key] = raw
    return resolved


def check_subflow_depth(depth: int, max_depth: int = DEFAULT_MAX_DEPTH) -> None:
    """嵌套深度守卫：depth >= max_depth 时拒绝（防栈溢出/无限递归）。"""
    if depth >= max_depth:
        raise SubflowDepthExceeded(
            f"subflow nesting depth {depth} exceeds limit {max_depth}"
        )


def check_subflow_cycle(workflow_id: str, ancestor_chain: Set[str]) -> None:
    """循环引用守卫：目标 workflow_id 已在祖先链中则拒绝。"""
    if workflow_id in (ancestor_chain or set()):
        raise SubflowCycleDetected(
            "subflow cycle detected: workflow appears in its own ancestor chain"
        )