"""
Neurflow 自定义节点服务 — Phase 2（L1 声明式 / L2 组合式）

让用户（经节点工坊 UI）与 agent（经工具）按需创建新节点类型：

- L1 declarative：自定义表单（sub_blocks）+ prompt 模板，模板占位符
  {{key}} 由节点配置/工作流输入填充，产物交给 LLM 执行器（默认复用
  builtin.exec_llm 的多模型路由）。
- L2 composite：顺序编排已有节点/工具（steps），前一步输出经 {{prev}}
  注入后一步配置；任一步失败即短路。

设计约束：
- 单一写入口：create/update/delete 同时维护 SQLite 与内存注册表，
  进程重启后 load_into_registry() 从库内恢复执行器。
- 更新前自动快照旧版本（custom_node_versions），供 Phase 4 回滚。
- L3 代码节点不在本阶段范围（需要审批门 + 沙箱，见 Phase 4）。
"""

import json
import logging
import re
import threading
from typing import Any, Callable, Dict, List, Optional

from .models import NodeDefinition, NodePort, SubBlockConfig

logger = logging.getLogger(__name__)

TIER_DECLARATIVE = "declarative"  # L1：表单 + prompt 模板
TIER_COMPOSITE = "composite"  # L2：已有节点/工具顺序链

_VALID_TIERS = (TIER_DECLARATIVE, TIER_COMPOSITE)
_TYPE_RE = re.compile(r"^[A-Za-z0-9_\-:]+$")
_PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z_][\w.]*)\s*\}\}")

# SubBlockConfig / NodePort 允许从 spec 透传的字段（防未知键炸 dataclass）
_SUBBLOCK_FIELDS = {
    "id", "title", "type", "placeholder", "description", "required",
    "default_value", "options", "min", "max", "language",
    "provider_capability", "file_types", "condition", "depends_on",
    "validation",
}
_PORT_FIELDS = {"id", "label", "type", "required", "multiple"}


class CustomNodeError(ValueError):
    """自定义节点操作错误；code ∈ invalid_spec | exists | not_found"""

    def __init__(self, message: str, code: str = "invalid_spec"):
        super().__init__(message)
        self.code = code


def render_template(template: str, values: Dict[str, Any]) -> str:
    """渲染 {{key}} / {{a.b}} 占位符。

    - 点路径逐层深入 dict；任何一层缺失 → 空串
    - dict/list 值 → JSON（ensure_ascii=False）；其余 → str()
    """

    def _resolve(path: str) -> Any:
        cur: Any = values
        for part in path.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return None
        return cur

    def _sub(match: "re.Match[str]") -> str:
        value = _resolve(match.group(1))
        if value is None:
            return ""
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    return _PLACEHOLDER_RE.sub(_sub, template or "")


def _default_llm_runner(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """默认 LLM 执行器：复用 builtin.exec_llm（多模型路由 + Agent 回退）"""
    from neurova.collaboration.neurflow.builtin import exec_llm

    return exec_llm(config, ctx)


class CustomNodeService:
    """自定义节点的创建/更新/删除/执行器构建（SQLite + 注册表双写）"""

    def __init__(
        self,
        storage=None,
        registry=None,
        llm_runner: Optional[Callable] = None,
    ):
        if storage is None:
            from .storage import NeurflowStorage

            storage = NeurflowStorage()
        if registry is None:
            from .node_registry import get_node_registry

            registry = get_node_registry()
        self._storage = storage
        self._registry = registry
        self._llm_runner = llm_runner or _default_llm_runner

    # ==================== CRUD ====================

    def create_node(
        self, spec: Dict[str, Any], *, created_by: Optional[str] = None
    ) -> NodeDefinition:
        """按 spec 创建自定义节点：校验 → 落库 → 注册执行器"""
        normalized = self._validate_spec(spec)
        node_type = normalized["type"]

        if self._storage.get_node_definition(node_type) is not None:
            raise CustomNodeError(f"节点类型已存在: {node_type}", code="exists")

        node_def = NodeDefinition(
            type=node_type,
            label=normalized["label"],
            icon=normalized["icon"],
            category=normalized["category"],
            description=normalized["description"],
            sub_blocks=normalized["sub_blocks"],
            inputs=normalized["inputs"],
            outputs=normalized["outputs"],
            source="custom",
            version="1.0.0",
            tier=normalized["tier"],
            executor_body=normalized["executor_body"],
            status="active",
            created_by=created_by,
        )
        self._storage.save_node_definition(node_def)
        self._registry.register(node_def, executor=self.build_executor(node_def))
        logger.info("自定义节点已创建: %s (tier=%s, by=%s)", node_type, node_def.tier, created_by)
        return node_def

    def update_node(
        self, node_type: str, spec: Dict[str, Any], *, created_by: Optional[str] = None
    ) -> NodeDefinition:
        """部分更新自定义节点；更新前快照旧版本，版本号 patch +1"""
        existing = self._storage.get_node_definition(node_type)
        if existing is None:
            raise CustomNodeError(f"节点不存在: {node_type}", code="not_found")
        if not isinstance(spec, dict):
            raise CustomNodeError("更新 spec 必须是字典", code="invalid_spec")

        # 快照旧版本（供回滚/审计）
        snapshot = {
            "label": existing.label,
            "description": existing.description,
            "icon": existing.icon,
            "category": existing.category,
            "tier": existing.tier,
            "executor_body": existing.executor_body,
            "form_schema": [s.__dict__ for s in existing.sub_blocks],
            "version": existing.version,
        }
        next_version = len(self._storage.list_node_versions(node_type)) + 1
        self._storage.save_node_version(node_type, next_version, snapshot, created_by)

        # 合并变更后整体校验（tier 与 executor_body 可能分别来自新旧两侧）
        merged = {
            "type": node_type,
            "label": spec.get("label", existing.label),
            "tier": spec.get("tier", existing.tier),
            "executor_body": spec.get("executor_body", existing.executor_body),
        }
        self._validate_spec(merged)

        if "label" in spec:
            existing.label = str(spec["label"]).strip()
        if "description" in spec:
            existing.description = str(spec["description"] or "")
        if "icon" in spec:
            existing.icon = str(spec["icon"] or existing.icon)
        if "category" in spec:
            existing.category = str(spec["category"] or existing.category)
        if "tier" in spec:
            existing.tier = merged["tier"]
        if "executor_body" in spec:
            existing.executor_body = merged["executor_body"]
        if "form_schema" in spec:
            existing.sub_blocks = self._parse_form_schema(spec["form_schema"])
        if "inputs" in spec:
            existing.inputs = self._parse_ports(spec["inputs"], kind="input")
        if "outputs" in spec:
            existing.outputs = self._parse_ports(spec["outputs"], kind="output")

        existing.version = self._bump_version(existing.version)
        self._storage.save_node_definition(existing)
        self._registry.register(existing, executor=self.build_executor(existing))
        logger.info("自定义节点已更新: %s → v%s", node_type, existing.version)
        return existing

    def delete_node(self, node_type: str) -> bool:
        """删除自定义节点（库 + 注册表）；不存在返回 False"""
        deleted = self._storage.delete_node_definition(node_type)
        if deleted:
            self._registry.unregister(node_type)
            logger.info("自定义节点已删除: %s", node_type)
        return deleted

    def get_node(self, node_type: str) -> Optional[NodeDefinition]:
        return self._storage.get_node_definition(node_type)

    def list_nodes(self) -> List[NodeDefinition]:
        """列出全部自定义节点"""
        return self._storage.list_node_definitions(source="custom")

    def list_versions(self, node_type: str) -> List[Dict[str, Any]]:
        """历史快照（新版本在前）"""
        return self._storage.list_node_versions(node_type)

    def load_into_registry(self, registry=None) -> int:
        """把库内 active 自定义节点批量注册回内存注册表（幂等）。

        registry 缺省注册到 service 自身绑定的实例；
        sync_all 等批量同步方传入目标 registry 以保持单一事实源。
        """
        target = registry or self._registry
        count = 0
        for node_def in self.list_nodes():
            if node_def.status != "active":
                continue
            target.register(node_def, executor=self.build_executor(node_def))
            count += 1
        if count:
            logger.info("自定义节点已载入注册表: %d 个", count)
        return count

    # ==================== 执行器构建 ====================

    def build_executor(self, node_def: NodeDefinition) -> Callable:
        """按 tier 构建 async (config, ctx) -> {"status","output",...} 执行器"""
        if node_def.tier == TIER_DECLARATIVE:
            return self._build_declarative_executor(node_def)
        if node_def.tier == TIER_COMPOSITE:
            return self._build_composite_executor(node_def)
        raise CustomNodeError(
            f"未知节点层级: {node_def.tier}（支持 {', '.join(_VALID_TIERS)}）",
            code="invalid_spec",
        )

    def _build_declarative_executor(self, node_def: NodeDefinition) -> Callable:
        """L1：渲染 prompt 模板 → 交给 LLM 执行器"""
        body = node_def.executor_body or {}
        template = str(body.get("template", ""))
        runner = self._llm_runner

        async def _exec(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
            config = config or {}
            # 工作流输入打底，节点配置优先
            values: Dict[str, Any] = {**(ctx.get("inputs") or {}), **config}
            llm_config = {
                "prompt": render_template(template, values),
                "system_prompt": str(body.get("system_prompt", "")),
                "model_provider": config.get("model_provider")
                or body.get("model_provider", "auto"),
                "model_name": config.get("model_name") or body.get("model_name", ""),
                "temperature": config.get("temperature", body.get("temperature", 0.7)),
                "max_tokens": config.get("max_tokens", body.get("max_tokens", 4096)),
            }
            return await runner(llm_config, ctx)

        return _exec

    def _build_composite_executor(self, node_def: NodeDefinition) -> Callable:
        """L2：顺序执行 steps；{{prev}} 注入前一步输出，失败即短路"""
        steps: List[Dict[str, Any]] = (node_def.executor_body or {}).get("steps", [])
        registry = self._registry

        async def _exec(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
            config = config or {}
            prev: Any = None
            results: List[Any] = []
            for idx, step in enumerate(steps):
                node_type = str(step.get("node_type", ""))
                executor = registry.get_executor(node_type)
                if executor is None:
                    return {
                        "status": "failed",
                        "error": f"步骤 {idx + 1} 未知节点类型: {node_type}",
                        "output": None,
                    }
                render_values = {
                    "prev": prev,
                    "config": config,
                    "inputs": ctx.get("inputs") or {},
                    "steps": results,
                }
                raw_step_config = step.get("config") or {}
                step_config = {
                    key: (render_template(value, render_values) if isinstance(value, str) else value)
                    for key, value in raw_step_config.items()
                }
                try:
                    result = await executor(step_config, ctx)
                except Exception as e:  # 步骤异常视为失败，短路
                    logger.warning("组合节点步骤异常: %s 步骤%d %s", node_def.type, idx + 1, e)
                    return {
                        "status": "failed",
                        "error": f"步骤 {idx + 1} ({node_type}) 执行异常: {e}",
                        "output": None,
                    }
                if isinstance(result, dict) and result.get("status") == "failed":
                    return {
                        "status": "failed",
                        "error": f"步骤 {idx + 1} ({node_type}) 失败: {result.get('error')}",
                        "output": None,
                    }
                prev = result.get("output") if isinstance(result, dict) else result
                results.append(prev)
            return {"status": "success", "output": prev}

        return _exec

    # ==================== 校验与解析 ====================

    def _validate_spec(self, spec: Dict[str, Any]) -> Dict[str, Any]:
        """校验并归一化创建 spec；失败抛 CustomNodeError(invalid_spec)"""
        if not isinstance(spec, dict):
            raise CustomNodeError("节点 spec 必须是字典", code="invalid_spec")

        label = str(spec.get("label") or "").strip()
        if not label:
            raise CustomNodeError("label 必填", code="invalid_spec")

        node_type = str(spec.get("type") or "").strip()
        if not node_type:
            raise CustomNodeError("type 必填", code="invalid_spec")
        if not node_type.startswith("custom:"):
            node_type = f"custom:{node_type}"
        if not _TYPE_RE.match(node_type):
            raise CustomNodeError(
                f"type 仅允许字母/数字/_/-/: {node_type}", code="invalid_spec"
            )

        tier = spec.get("tier")
        if tier not in _VALID_TIERS:
            raise CustomNodeError(
                f"tier 必须是 {', '.join(_VALID_TIERS)} 之一（收到 {tier!r}）",
                code="invalid_spec",
            )

        body = spec.get("executor_body")
        if not isinstance(body, dict):
            raise CustomNodeError("executor_body 必须是字典", code="invalid_spec")
        if tier == TIER_DECLARATIVE:
            if not str(body.get("template") or "").strip():
                raise CustomNodeError(
                    "declarative 节点需要非空 executor_body.template",
                    code="invalid_spec",
                )
        else:
            steps = body.get("steps")
            if not isinstance(steps, list) or not steps:
                raise CustomNodeError(
                    "composite 节点需要非空 executor_body.steps 列表",
                    code="invalid_spec",
                )
            for i, step in enumerate(steps):
                if not isinstance(step, dict) or not str(step.get("node_type") or "").strip():
                    raise CustomNodeError(
                        f"steps[{i}] 必须含非空 node_type", code="invalid_spec"
                    )

        return {
            "type": node_type,
            "label": label,
            "icon": str(spec.get("icon") or "🧩"),
            "category": str(spec.get("category") or "custom"),
            "description": str(spec.get("description") or ""),
            "tier": tier,
            "executor_body": body,
            "sub_blocks": self._parse_form_schema(spec.get("form_schema") or []),
            "inputs": self._parse_ports(spec.get("inputs"), kind="input"),
            "outputs": self._parse_ports(spec.get("outputs"), kind="output"),
        }

    def _parse_form_schema(self, form_schema: Any) -> List[SubBlockConfig]:
        """自定义表单 → SubBlockConfig 列表（前端自动渲染表单）"""
        if not isinstance(form_schema, list):
            raise CustomNodeError("form_schema 必须是列表", code="invalid_spec")
        blocks: List[SubBlockConfig] = []
        for i, entry in enumerate(form_schema):
            if not isinstance(entry, dict) or not str(entry.get("id") or "").strip():
                raise CustomNodeError(
                    f"form_schema[{i}] 必须含非空 id", code="invalid_spec"
                )
            filtered = {k: v for k, v in entry.items() if k in _SUBBLOCK_FIELDS}
            filtered.setdefault("title", filtered["id"])
            filtered.setdefault("type", "input")
            blocks.append(SubBlockConfig(**filtered))
        return blocks

    def _parse_ports(self, ports: Any, *, kind: str) -> List[NodePort]:
        """解析端口定义；未提供时给默认单端口"""
        if ports is None:
            default_label = "输入" if kind == "input" else "输出"
            return [NodePort(id=kind, label=default_label)]
        if not isinstance(ports, list):
            raise CustomNodeError("inputs/outputs 必须是列表", code="invalid_spec")
        result: List[NodePort] = []
        for i, entry in enumerate(ports):
            if not isinstance(entry, dict) or not str(entry.get("id") or "").strip():
                raise CustomNodeError(
                    f"{kind} 端口[{i}] 必须含非空 id", code="invalid_spec"
                )
            filtered = {k: v for k, v in entry.items() if k in _PORT_FIELDS}
            filtered.setdefault("label", filtered["id"])
            result.append(NodePort(**filtered))
        return result

    @staticmethod
    def _bump_version(version: str) -> str:
        """语义版本 patch +1；无法解析时回退 1.0.1"""
        parts = (version or "").split(".")
        try:
            parts[-1] = str(int(parts[-1]) + 1)
            return ".".join(parts)
        except (ValueError, IndexError):
            return "1.0.1"


# ==================== 单例 ====================

_service_instance: Optional[CustomNodeService] = None
_service_lock = threading.RLock()


def get_custom_node_service() -> CustomNodeService:
    """进程级单例（默认 storage/registry/LLM 执行器）"""
    global _service_instance
    if _service_instance is None:
        with _service_lock:
            if _service_instance is None:
                _service_instance = CustomNodeService()
    return _service_instance


def reset_custom_node_service() -> None:
    """测试用：重置单例"""
    global _service_instance
    with _service_lock:
        _service_instance = None
