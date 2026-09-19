"""确定性实体消解 · 并查集聚类（工单 006）。

传递合并靠并查集；代表元取组内字典序最小者，因此输出与输入顺序无关——
这是"同一批数据重放两次结果一致"的判据所在。
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List


class IdentityMerger:
    def __init__(self, threshold: float = 0.9, minClusterSize: int = 2) -> None:
        if not 0.0 < threshold <= 1.0:
            raise ValueError("threshold 必须落在 (0, 1]，收到 %r" % threshold)
        self._threshold = threshold
        self._minClusterSize = max(2, int(minClusterSize))

    def cluster(self, proposals: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        accepted = sorted(
            (
                (str(p["left"]), str(p["right"]), float(p["score"]))
                for p in proposals
                if float(p["score"]) >= self._threshold
            ),
            key=lambda row: (row[0], row[1]),
        )

        parent: Dict[str, str] = {}

        def find(node: str) -> str:
            parent.setdefault(node, node)
            root = node
            while parent[root] != root:
                root = parent[root]
            while parent[node] != root:
                parent[node], node = root, parent[node]
            return root

        for left, right, _score in accepted:
            rootLeft, rootRight = find(left), find(right)
            if rootLeft != rootRight:
                # 小号做根：与遍历顺序无关，重放稳定
                parent[max(rootLeft, rootRight)] = min(rootLeft, rootRight)

        groups: Dict[str, List[str]] = {}
        for node in parent:
            groups.setdefault(find(node), []).append(node)

        clusters = [
            {
                "members": sorted(members),
                "canonical": min(members),
                "topScore": max(
                    (score for left, right, score in accepted if left in members and right in members),
                    default=self._threshold,
                ),
            }
            for members in groups.values()
            if len(members) >= self._minClusterSize
        ]
        return sorted(clusters, key=lambda c: c["canonical"])

    def mergeInstructions(self, clusters: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        """把聚类翻成"谁并入谁"，供底座 `mergeSubjects` 消费。"""
        return [
            {"from": member, "into": cluster["canonical"], "reason": "identity_merger"}
            for cluster in clusters
            for member in cluster["members"]
            if member != cluster["canonical"]
        ]
