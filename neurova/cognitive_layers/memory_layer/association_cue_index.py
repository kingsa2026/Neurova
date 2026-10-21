"""联想线索的**向量**通道（TM-2b，批 C-1）

一句话：每条线索一个向量，查询与线索算余弦，过门限后把 `memory_id` 并进候选，
加分仍走既有 RRF 与 origin 信任——通道不自己排序、不出结果、不进提示。

为什么不是词法通道（本会话实测否掉了批 A 那条假设，读数写进判据文件抬头）：
词法那把刀是「连续中文按 2–4 字**非重叠**切片」（`semantic_search.py:113-119`），
两句不同的话切片几乎对不上——把理想线索灌进倒排后 TM-1 联想读数一字未动。
同义改写只能靠稠密相似度，所以这里用向量。

三处刻意的设计选择（都带理由，不留「以后再说」）：
- **门限高于收益**：宁可不注入。注入的净收益必须是「捞回本来捞不到的」，
  代价是「把无关行顶进前五」；本仓的可见后果是后者更贵（用户会看到莫名相关的一条）。
- **只加分不减分**：通道给命中行加一份 RRF 贡献，绝不重排已有列表，
  所以描述性召回的地板不可能被它挤掉（判据 `test_描述性地板不得被线索挤掉` 钉住）。
- **规模上限是公平性边界，不是模型预算**：冷启动编码全库线索会吃掉整轮固化窗口，
  故按 `created_at` 新近截断。用户裁的丙只放开**生成侧**的调用量，这里不跟着放。
"""

import os
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple

from neurova.core import vector_math
from neurova.core.logger import get_logger

logger = get_logger(__name__)

#: 查询↔线索余弦门限。**本仓实测标定，不抄外部数值**：外部那 0.85 配的是 bge-m3
#: （1024 维），本仓 bge-small-zh-v1.5（512 维）上余弦整体偏低，抄过来通道永不点火
#: （实测 0.52 时 droppedByGate 吃掉全部候选、fired 恒 0）。
#:
#: 标定读数（同一 66 行干扰集 + 10 条盲写线索，本机 ONNX 现算）：
#:   目标线索最好余弦 0.465–0.612；**其它记忆的线索**最高 0.687；干扰项正文最高 0.631。
#:   门限扫 0.30/0.35/0.40/0.45 均点火 10/10、top-1 精确率 7/10；提到 0.50 点火掉到 9/10、
#:   精确率反而降到 6/9。⇒ 工单 §3 原写的「取精确率 ≥0.9 的最低门限」在这份语料上
#:   **没有可行解**——串味来自线索与线索之间（跨记忆混淆），不是线索与查询之间，
#:   抬门限救不了。当前取 0.45 为该语料的最优点，代价是每 10 次注入约 3 次是别人的记忆，
#:   所以通道**只加分不重排**、且权重压在两路主信号之下，把误注的可见代价限制在名次而非顶替。
CUE_COSINE_GATE = 0.45

#: 通道在 RRF 里的加分权重（与既有「向量 0.7 / 关键词 0.3」并列的第三路）。
#: 刻意小于任一路的主权重：线索是**补充可达性**，不该把已有强命中挤下去。
CUE_RRF_WEIGHT = 0.25

#: RRF 常数沿用既有那份（`manager.py:2104-2111` 的 k=60），不另立一套。
RRF_K = 60

#: 冷启动一次最多索引多少条线索（按 `created_at` 新近取）。
CUE_INDEX_MAX_ENTRIES = 20000

#: 一键关断：`NEUROVA_MEMORY_CUE_CHANNEL=off|0` 时通道完全不点火（不编码、不注入）。
#: 形态沿用仓内既有 env 开关先例（`NEUROVA_AUTO_EFFORT` / `NEUROVA_ADAPTIVE_RETRIEVAL`），
#: 不新造配置面——新增 PARAM_SCHEMAS 条目要连带动 11 语言 i18n，那是另一批的账。
ENV_SWITCH = "NEUROVA_MEMORY_CUE_CHANNEL"


def cueChannelEnabled() -> bool:
    """通道开关。默认开（丙档＝全量启用），显式 `off`/`0`/`false` 才关。"""
    value = (os.environ.get(ENV_SWITCH) or "").strip().lower()
    return value not in ("off", "0", "false", "disabled")


class CueVectorChannel:
    """按作用域装载的线索向量索引 + 每次查询的门限匹配与计数。

    索引是**进程内**的（与主向量库同一形态：`unified_vector_store` 也没有落盘向量，
    重启动靠 `memory_cues` 表重建，文本→向量走既有磁盘嵌入缓存，不重算）。
    """

    def __init__(
        self,
        cueRowsGetter: Callable[[int], List[Dict[str, Any]]],
        encodeOne: Callable[[str], Optional[List[float]]],
        maxEntries: int = CUE_INDEX_MAX_ENTRIES,
    ):
        self._cueRowsGetter = cueRowsGetter
        self._encodeOne = encodeOne
        self._maxEntries = maxEntries
        self._lock = threading.RLock()
        self._vectors: Optional["Any"] = None
        self._memoryIds: List[str] = []
        self._built = False
        self._stats: Dict[str, int] = {
            "fired": 0,
            "injected": 0,
            "droppedByGate": 0,
            "skippedOff": 0,
            "skippedNoEngine": 0,
            "skippedEmpty": 0,
            "indexed": 0,
        }

    def invalidate(self) -> None:
        """线索变更后作废索引（下次查询重建）。"""
        with self._lock:
            self._built = False
            self._vectors = None
            self._memoryIds = []

    def capacity(self) -> int:
        return self._maxEntries

    def _build(self) -> None:
        import numpy as np

        rows = self._cueRowsGetter(self._maxEntries)
        vectors: List[Any] = []
        memoryIds: List[str] = []
        for row in rows:
            vector = self._encodeOne(row.get("cue_text", ""))
            if not vector:
                continue
            normalized = vector_math.vectorNormalize([float(x) for x in vector])
            if not normalized:
                continue
            vectors.append(normalized)
            memoryIds.append(row.get("memory_id", ""))
        self._vectors = np.vstack(vectors) if vectors else None
        self._memoryIds = memoryIds
        self._built = True
        self._stats["indexed"] = len(memoryIds)

    def candidateMemoryIds(self) -> List[str]:
        """当前索引里出现过的记忆 id（去重、按索引顺序）——作用域门的可观测出口。"""
        with self._lock:
            if not self._built:
                self._build()
            seen: List[str] = []
            recorded = set()
            for memoryId in self._memoryIds:
                if memoryId and memoryId not in recorded:
                    recorded.add(memoryId)
                    seen.append(memoryId)
            return seen

    def recall(
        self, queryVector: Optional[List[float]], limit: int = 10
    ) -> List[Tuple[str, int, float]]:
        """返回 `[(memory_id, 通道内名次, 最好一次余弦), ...]`，已过门限、已去重。

        同一条记忆的多条线索取**最优**那次匹配（`max`），不是累加——
        累加会让「线索写得多的行」天然压过「线索写得准的行」，把生成质量变成数量竞赛。
        """
        if not cueChannelEnabled():
            self._stats["skippedOff"] += 1
            return []
        if not queryVector:
            self._stats["skippedNoEngine"] += 1
            return []

        import numpy as np

        with self._lock:
            if not self._built:
                self._build()
            if self._vectors is None or not self._memoryIds:
                self._stats["skippedEmpty"] += 1
                return []
            query = vector_math.vectorNormalize([float(x) for x in queryVector])
            if not query:
                self._stats["skippedNoEngine"] += 1
                return []
            scores = self._vectors @ np.asarray(query, dtype=np.float32)
            bestPerMemory: Dict[str, float] = {}
            for index, score in enumerate(scores):
                memoryId = self._memoryIds[index]
                if not memoryId:
                    continue
                value = float(score)
                if value > bestPerMemory.get(memoryId, -1.0):
                    bestPerMemory[memoryId] = value

        ordered = sorted(bestPerMemory.items(), key=lambda kv: kv[1], reverse=True)
        results: List[Tuple[str, int, float]] = []
        rank = 0
        for memoryId, cosine in ordered:
            if cosine < CUE_COSINE_GATE:
                self._stats["droppedByGate"] += 1
                continue
            rank += 1
            results.append((memoryId, rank, cosine))
            if len(results) >= limit:
                break
        if results:
            self._stats["fired"] += 1
            self._stats["injected"] += len(results)
        return results

    def stats(self) -> Dict[str, int]:
        return dict(self._stats)


def cueScoreContribution(rank: int) -> float:
    """通道第 `rank`（1 起）名的 RRF 加分。与既有两路同一公式、不同权重。"""
    return CUE_RRF_WEIGHT / (RRF_K + max(1, rank))
