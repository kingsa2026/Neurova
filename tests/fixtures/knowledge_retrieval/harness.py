# -*- coding: utf-8 -*-
"""检索回归门的共用跑法——基线与判据必须走同一条路，否则"对账"是在比两套装配。

为什么收在这一处：基线数字（`baseline.json`）和门禁判据若各写一套仓库/索引构造，
两边就会各自漂（不同 topK、不同 user、不同引擎），最后门拦的是"哪套装配"而不是"检索退步"。
`openGate()` + `runOnce()` 是这条跑法唯一的定义点：基线产法 `runGateBenchmark()` 与判据用例
都只调它们，用例里不另拼一份 hybrid 调用、也不自己实现"算不算退步"的裁决——
裁决长在 `RetrievalBenchmark.compareAgainstBaseline()` 一处。

向量化用**确定性字符三元组**替身，不碰真 ONNX 模型：真模型是否可用随机器而变
（`search.py` 那句 jieba 回退警告是同族现象），把语义质量写进门禁会让 CI 在换机器时假红。
这个替身仍然真吃向量路——它保证"向量路整体哑掉"会被门抓到，只是不证明语义好坏。
"""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

from neurova.knowledge.evaluation.retrieval_benchmark import RetrievalBenchmark
from neurova.knowledge.hybrid import hybrid_search_knowledge
from neurova.knowledge.repository import KnowledgeRepository
from neurova.knowledge.vector_index import KnowledgeVectorIndex

FIXTURE_DIR = Path(__file__).resolve().parent
CORPUS_PATH = FIXTURE_DIR / "corpus.json"
BASELINE_PATH = FIXTURE_DIR / "baseline.json"
TOP_K = 5
MIN_CASES = 30


class TrigramEmbedding:
    """确定性嵌入替身：字符三元组计数 + L2 归一，跨机器逐维同值。"""

    def encode(self, text: str) -> List[float]:
        body = str(text or "")
        counts = Counter(body[i:i + 3] for i in range(max(len(body) - 2, 0)))
        norm = math.sqrt(sum(c * c for c in counts.values())) or 1.0
        return [c / norm for c in counts.values()]

    def encode_batch(self, texts: List[str]) -> List[List[float]]:
        return [self.encode(t) for t in texts]


def buildRepository(root: Any) -> Dict[str, Any]:
    """按夹具语料建一座隔离仓库（tmp 落点，不碰真库）。"""
    corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    repo = KnowledgeRepository(str(Path(root) / "kb"))
    for item in corpus["items"]:
        repo.create_knowledge(
            corpus["agent_id"], title=item["title"], content=item["content"],
            category=item["category"], tags=item.get("tags") or [],
            knowledge_id=item["knowledge_id"], owner_user_id=corpus["owner_user_id"],
            detect_conflict=False,
        )
    return {"repo": repo, "corpus": corpus}


def openGate(root: Any) -> Dict[str, Any]:
    """装配一条门：仓库 + 向量面 + 评测库 + 已播种的评测集。"""
    built = buildRepository(root)
    repo, corpus = built["repo"], built["corpus"]
    gate = {
        "repo": repo,
        "corpus": corpus,
        "seeker": {"user_id": corpus["owner_user_id"]},
        "vectors": KnowledgeVectorIndex(str(Path(root) / "kb" / "vec"),
                                        engine=TrigramEmbedding()),
        "bench": RetrievalBenchmark(str(Path(root) / "kb" / "knowledge_evaluation.db")),
        "frozen": False,
    }
    gate["bench"].seedFromRepository(repo, minCases=MIN_CASES)
    return gate


def runOnce(gate: Dict[str, Any], searchOverride: Any = None) -> Dict[str, Any]:
    """按同一条路跑一轮。`searchOverride` 只给判据里的反证格用。"""
    repo, corpus = gate["repo"], gate["corpus"]

    def _search(query: str) -> List[Dict[str, Any]]:
        return hybrid_search_knowledge(
            repo, gate["seeker"], query, limit=TOP_K,
            agent_id=corpus["agent_id"], vector_index=gate["vectors"])

    return gate["bench"].run(
        repo, user=gate["seeker"], agentId=corpus["agent_id"], topK=TOP_K,
        note="gate run", searchFn=searchOverride or _search)


def runGateBenchmark(root: Any) -> Dict[str, Any]:
    """基线产法：开一条门、跑一轮、补上标注构成，然后收摊。"""
    gate = openGate(root)
    try:
        report = runOnce(gate)
        report["labeling_breakdown"] = gate["bench"].labelingBreakdown()
        return report
    finally:
        gate["bench"].close()
