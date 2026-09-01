"""
节点配置校验器 — 执行前硬失败拦截（画布“节点数据异常”弹窗数据源）

背景：节点配置缺失时 executor 要么返回 failed（带病跑到最后，问题被吞），
要么运行时抛错。执行前集中校验收集全图问题：run 端点 400 返回
{[{node_id, label, type, message}...]}（缺失字段级），前端弹窗逐条展示。

规则覆盖 executor 硬性需求（"缺少 X 无法执行"）；condition 有默认值
（expression 空 = "True"）不告警；动态 tool:/skill: 节点执行器自适应不校验。
"""
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .models import WorkflowDefinition


@dataclass
class NodeConfigIssue:
    """节点配置缺失issue（字段级）"""

    node_id: str
    label: str
    type: str
    missing: List[str] = field(default_factory=list)
    message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "label": self.label,
            "type": self.type,
            "missing": self.missing,
            "message": self.message,
        }


def _is_empty(value: Any) -> bool:
    """空值判定：None / 空串 / 空白串；0 与 False 合法。"""
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    return False


# 特例规则：type -> [(config 键, 描述)]；键空即缺失
_SPECIAL_RULES: Dict[str, List[tuple]] = {
    "builtin:llm": [("prompt", "提示词")],
    "builtin:variable": [("name", "变量名")],
    "builtin:transform": [("expression", "转换表达式")],
    "builtin:subflow": [("workflow_id", "目标工作流 ID")],
    "builtin:agent": [("agent_id", "Agent ID"), ("task", "任务描述")],
    "builtin:approval": [("approver", "审批人")],
    "builtin:human_input": [("prompt", "提示信息")],
}


def validate_node_configs(workflow: WorkflowDefinition) -> List[NodeConfigIssue]:
    """收集全图节点配置缺失；返回 issue 列表（空=可通过）。"""
    issues: List[NodeConfigIssue] = []
    for node in workflow.nodes:
        config = node.config or {}
        missing: List[str] = []
        # 通用：config 内已登记的必填语义键（覆盖前端默认空对象的情况）
        rules = _SPECIAL_RULES.get(node.type, [])
        for key, desc in rules:
            if _is_empty(config.get(key)):
                missing.append(f"{desc}（{key}）")
        if missing:
            issues.append(
                NodeConfigIssue(
                    node_id=node.id,
                    label=node.label or node.id,
                    type=node.type,
                    missing=missing,
                    message=f"节点「{node.label or node.id}」配置缺失: " + "、".join(missing),
                )
            )
    return issues


def issues_to_payload(issues: List[NodeConfigIssue]) -> Dict[str, Any]:
    """包装为 API 400 detail：前端直接可展示的清单。"""
    return {
        "code": 1,
        "message": "节点配置异常，已停止执行",
        "errors": [i.to_dict() for i in issues],
    }
