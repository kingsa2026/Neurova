"""冗余审计：把条目层的历史重复显式化（工单 004）。

只读、只报告、不删除。删除口径属工单 019（条目库降级为投影）——
先把账目摊开，再动数据，顺序不能反。
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List

from neurova.core.content_identity import normalized_key


class RedundancyAudit:
    """按内容身份给条目分组，产出可复核的纯冗余清单。"""

    @staticmethod
    def auditRepository(repo: Any) -> Dict[str, Any]:
        items: List[Dict[str, Any]] = []
        for agentId, entries in getattr(repo, "_items", {}).items():
            for item in entries:
                row = dict(item)
                row["_agent_id"] = agentId
                items.append(row)

        keyed: Dict[str, List[Dict[str, Any]]] = {}
        noIdentity: List[Dict[str, Any]] = []
        for item in items:
            # 与写入口径一致：内容优先，标题不参与身份（同标题不同正文不是重复）
            key = normalized_key(item.get("content", ""))
            if not key:
                noIdentity.append(item)
                continue
            keyed.setdefault(key, []).append(item)

        groups = sorted(
            (
                {
                    "content_key": key,
                    "count": len(rows),
                    "title": rows[0].get("title", ""),
                    "knowledge_ids": [r.get("knowledge_id") for r in rows],
                }
                for key, rows in keyed.items()
                if len(rows) > 1
            ),
            key=lambda g: (-g["count"], g["title"]),
        )
        return {
            "total_rows": len(items),
            "distinct_content_keys": len(keyed),
            "no_identity_rows": len(noIdentity),
            "redundant_rows": sum(g["count"] - 1 for g in groups),
            "duplicate_group_count": len(groups),
            "groups": groups,
        }

    @staticmethod
    def summarize(report: Dict[str, Any]) -> str:
        counter = Counter("×%d" % g["count"] for g in report["groups"])
        return (
            "条目 %d 行 / 不同内容 %d 个 / 纯冗余 %d 行（%d 组，分布 %s）/ 无内容身份 %d 行"
            % (
                report["total_rows"], report["distinct_content_keys"],
                report["redundant_rows"], report["duplicate_group_count"],
                dict(counter) or "-", report["no_identity_rows"],
            )
        )
