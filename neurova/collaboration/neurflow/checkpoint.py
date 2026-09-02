"""
执行检查点摘要（Probe）— 借鉴 langflow lfx/graph/checkpoint 的探针形态

execution_checkpoint_summary：基于 ExecutionInstance（node_results/variables）
输出进度摘要：completed/failed/pending/变量快照/错误。纯函数，供
GET /executions/{id}/checkpoint 与 UI 展示消费。
"""

from typing import Any, Dict, List

from .models import ExecutionInstance


def execution_checkpoint_summary(
    instance: ExecutionInstance,
    node_ids: List[str],
) -> Dict[str, Any]:
    """探针摘要。

    Args:
        instance: 执行实例（其 node_results 即检查点数据）
        node_ids: 工作流全部节点（决定 pending 集）
    """
    completed: List[str] = []
    failed: List[str] = []
    skipped: List[str] = []
    node_ids_set = set(node_ids)
    for nid, res in (instance.node_results or {}).items():
        if res.status == "success":
            completed.append(nid)
        elif res.status == "failed":
            failed.append(nid)
        elif res.status == "skipped":
            skipped.append(nid)

    known = set(completed) | set(failed) | set(skipped)
    pending = [nid for nid in node_ids if nid not in known]

    return {
        "execution_id": instance.id,
        "workflow_id": instance.workflow_id,
        "status": instance.status.value,
        "completed": sorted(completed),
        "failed": sorted(failed),
        "skipped": sorted(skipped),
        "pending": pending,
        "variables": dict(instance.variables or {}),
        "error": instance.error,
    }
