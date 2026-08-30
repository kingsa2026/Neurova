"""
Neurflow 适配器模块 — 自动发现适配器

将 Neurova 核心组件（ToolEngine/SkillRegistry/MCPToolClient）
转换为 Neurflow 工作流节点定义。

架构理念：
- 适配器是"翻译层"，将外部组件的接口转换为统一的节点定义
- 使用 graceful degradation 设计，导入失败时返回空结果
- 遵循 TDD 原则，所有转换逻辑可独立测试
"""

from neurova.core.logger import get_logger
from typing import Any, Dict

from .models import NodeDefinition

logger = get_logger(__name__)


# ==================== 参数类型映射 ====================

# 外部组件的参数类型 → Neurflow SubBlockConfig 类型
TYPE_MAP: Dict[str, str] = {
    "string": "input",
    "number": "slider",
    "boolean": "switch",
    "enum": "select",
    "object": "json",
    "array": "json",
    "file": "file",
    "text": "textarea",
    "code": "code",
    "json": "json",
}


# ==================== 参数转换 ====================


def param_to_sub_block(param: Dict[str, Any]) -> Dict[str, Any]:
    """
    将外部组件的参数定义转换为 SubBlockConfig

    Args:
        param: 外部组件参数字典
            - name: 参数名
            - type: 参数类型
            - description: 参数描述
            - required: 是否必填
            - default: 默认值
            - min: 最小值（number 类型）
            - max: 最大值（number 类型）
            - enum: 枚举选项（enum 类型）

    Returns:
        SubBlockConfig 字典
    """
    param_type = param.get("type", "string")
    sub_block_type = TYPE_MAP.get(param_type, "input")

    sub_block = {
        "id": param.get("name", "unknown"),
        "title": param.get("name", "unknown").replace("_", " ").title(),
        "type": sub_block_type,
        "description": param.get("description", ""),
        "required": param.get("required", False),
        "default_value": param.get("default", param.get("default_value")),
    }

    # number 类型添加 min/max
    if param_type == "number" or param_type == "slider":
        if "min" in param:
            sub_block["min"] = param["min"]
        if "max" in param:
            sub_block["max"] = param["max"]

    # enum 类型添加 options
    if param_type == "enum" and "enum" in param:
        sub_block["options"] = [
            {"label": opt if isinstance(opt, str) else str(opt), "value": opt} for opt in param["enum"]
        ]

    # boolean 类型默认值处理
    if param_type == "boolean" and "default" in param:
        sub_block["default_value"] = bool(param["default"])

    return sub_block


# ==================== 组件转换 ====================


def tool_to_node(tool_def: Dict[str, Any]) -> NodeDefinition:
    """
    ToolEngine 工具 → 工作流节点定义

    Args:
        tool_def: 工具定义字典
            - name: 工具名称
            - description: 工具描述
            - parameters: 参数列表
            - tags: 标签列表
            - version: 版本号

    Returns:
        NodeDefinition 节点定义
    """
    name = tool_def.get("name", "unknown")
    parameters = tool_def.get("parameters", [])

    return NodeDefinition(
        type=f"tool:{name}",
        label=name,
        icon="🔧",
        category="tools",
        description=tool_def.get("description", f"工具: {name}"),
        sub_blocks=[param_to_sub_block(p) for p in parameters],
        inputs=[{"id": "input", "label": "输入"}],
        outputs=[{"id": "output", "label": "输出"}, {"id": "error", "label": "错误"}],
        source="tool",
        source_id=name,
        version=tool_def.get("version", "1.0.0"),
        tags=tool_def.get("tags", []),
    )


def _info_field(info: Any, key: str, default: Any = None) -> Any:
    """兼容读取技能/工具信息字段（dict 与属性对象双支持）。

    SkillRegistry.list_skills() 返回属性式的 _SkillInfo，
    而部分调用方传入普通字典——两种形态都必须工作。
    """
    if isinstance(info, dict):
        return info.get(key, default)
    return getattr(info, key, default)


def skill_to_node(skill_info: Any) -> NodeDefinition:
    """
    SkillRegistry 技能 → 工作流节点定义

    Args:
        skill_info: 技能信息（dict 或属性对象）
            - name: 技能名称
            - description: 技能描述
            - parameters: 参数列表
            - tags: 标签列表
            - version: 版本号

    Returns:
        NodeDefinition 节点定义
    """
    name = str(_info_field(skill_info, "name", "unknown") or "unknown")
    parameters = _info_field(skill_info, "parameters", []) or []
    tags = _info_field(skill_info, "tags", []) or []

    return NodeDefinition(
        type=f"skill:{name}",
        label=name,
        icon="📚",
        category="skills",
        description=str(_info_field(skill_info, "description", f"技能: {name}") or f"技能: {name}"),
        sub_blocks=[param_to_sub_block(p) for p in parameters],
        inputs=[{"id": "input", "label": "输入"}],
        outputs=[{"id": "output", "label": "输出"}],
        source="skill",
        source_id=name,
        version=str(_info_field(skill_info, "version", "1.0.0") or "1.0.0"),
        tags=list(tags),
    )


def mcp_tool_to_node(server: str, tool_info: Dict[str, Any]) -> NodeDefinition:
    """
    MCP 工具 → 工作流节点定义

    Args:
        server: MCP 服务器名称
        tool_info: 工具信息字典
            - name: 工具名称
            - description: 工具描述
            - parameters: 参数列表

    Returns:
        NodeDefinition 节点定义
    """
    name = tool_info.get("name", "unknown")
    parameters = tool_info.get("parameters", [])

    return NodeDefinition(
        type=f"mcp:{server}:{name}",
        label=name,
        icon="🔌",
        category="mcp",
        description=tool_info.get("description", f"MCP 工具: {name}"),
        sub_blocks=[param_to_sub_block(p) for p in parameters],
        inputs=[{"id": "input", "label": "输入"}],
        outputs=[{"id": "output", "label": "输出"}],
        source="mcp",
        source_id=f"{server}:{name}",
        version=tool_info.get("version", "1.0.0"),
        tags=tool_info.get("tags", []),
    )


# ==================== 同步函数 ====================


def _get_tool_engine():
    """延迟加载 ToolEngine"""
    try:
        from neurova.execution_engine.tool_engine import get_tool_engine

        return get_tool_engine()
    except ImportError:
        logger.debug("ToolEngine 未可用")
        return None


def _get_skill_registry():
    """延迟加载 SkillRegistry"""
    try:
        from neurova.skill_system import get_skill_registry

        return get_skill_registry()
    except ImportError:
        logger.debug("SkillRegistry 未可用")
        return None


def _get_mcp_client():
    """延迟加载 MCPToolClient"""
    try:
        from neurova.tool_layers.mcp_client import get_mcp_client

        return get_mcp_client()
    except ImportError:
        logger.debug("MCPToolClient 未可用")
        return None


def sync_tools(registry) -> int:
    """
    从 ToolEngine 同步工具节点

    Args:
        registry: 节点注册表实例

    Returns:
        同步的工具数量
    """
    tool_engine = _get_tool_engine()
    if tool_engine is None:
        return 0

    try:
        count = 0
        for tool in tool_engine.list_tools():
            node_def = tool_to_node(tool)
            registry.register(node_def)
            count += 1
        return count
    except Exception as e:
        logger.warning("同步工具失败: %s", e)
        return 0


def sync_skills(registry) -> int:
    """
    从 SkillRegistry 同步技能节点

    Args:
        registry: 节点注册表实例

    Returns:
        同步的技能数量
    """
    skill_registry = _get_skill_registry()
    if skill_registry is None:
        return 0

    try:
        count = 0
        for skill in skill_registry.list_skills():
            node_def = skill_to_node(skill)
            registry.register(node_def)
            count += 1
        return count
    except Exception as e:
        logger.warning("同步技能失败: %s", e)
        return 0


def sync_mcp(registry) -> int:
    """
    从 MCPToolClient 同步 MCP 工具节点

    Args:
        registry: 节点注册表实例

    Returns:
        同步的 MCP 工具数量
    """
    mcp_client = _get_mcp_client()
    if mcp_client is None:
        return 0

    try:
        count = 0
        for tool in mcp_client.list_tools():
            # MCP 工具需要服务器名称
            server = tool.get("server", "default")
            node_def = mcp_tool_to_node(server, tool)
            registry.register(node_def)
            count += 1
        return count
    except Exception as e:
        logger.warning("同步 MCP 工具失败: %s", e)
        return 0


def sync_all(registry) -> Dict[str, int]:
    """
    同步所有节点（工具 + 技能 + MCP + ComfyUI + 电商 + 短剧视频）

    Args:
        registry: 节点注册表实例

    Returns:
        同步结果字典 {"tools": N, "skills": N, "mcp": N, "comfyui": N, "commerce": N, "drama": N}
    """
    comfyui_count = 0
    try:
        from .comfyui_nodes import register_comfyui_nodes

        comfyui_count = register_comfyui_nodes(registry)
    except Exception as e:  # noqa: BLE001 - comfyui 注册失败不阻断其他同步
        import logging

        logging.getLogger(__name__).warning("ComfyUI 节点同步失败: %s", e)

    commerce_count = 0
    try:
        from .commerce_nodes import register_commerce_nodes

        commerce_count = register_commerce_nodes(registry)
    except Exception as e:  # noqa: BLE001 - commerce 注册失败不阻断其他同步
        import logging

        logging.getLogger(__name__).warning("电商节点同步失败: %s", e)

    drama_count = 0
    try:
        from .drama_nodes import register_drama_nodes

        drama_count = register_drama_nodes(registry)
    except Exception as e:  # noqa: BLE001 - drama 注册失败不阻断其他同步
        import logging

        logging.getLogger(__name__).warning("短剧视频节点同步失败: %s", e)

    return {
        "tools": sync_tools(registry),
        "skills": sync_skills(registry),
        "mcp": sync_mcp(registry),
        "comfyui": comfyui_count,
        "commerce": commerce_count,
        "drama": drama_count,
    }


# ==================== 便捷导出 ====================

__all__ = [
    "TYPE_MAP",
    "param_to_sub_block",
    "tool_to_node",
    "skill_to_node",
    "mcp_tool_to_node",
    "sync_all",
    "sync_tools",
    "sync_skills",
    "sync_mcp",
]
