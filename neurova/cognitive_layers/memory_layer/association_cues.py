"""联想线索（associativeCue）——存储、归一与**零模型**的规则派生（TM-2a，批 A）

一句话：给一条记忆挂若干「只参与检索、永不进提示」的短语，让它们进同一份关键词倒排，
于是与记忆本身无共同词面、却语义相关的提问有第二条访问路。根因读数见
`docs/08-research/tmem_paper_vs_neurova_associative_memory_comparison_2026-10-21.md`
与判据集 `tests/performance/memory/test_associativeRecallGate.py`（§6-381）。

本模块刻意**不含任何模型调用面**（批 A 的立身之处是零成本；常驻判据
`test_ruleAssociationCues.py::TestRuleDerivationIsModelFree` 按 AST 反证本文件的符号面）。
模型生成的前瞻线索属批 C，落独立模块，与本文件共享同一份存储与同一套作用域门——
不另起第二份口径（教义第 6 条）。

命名说明：本仓不叫 trigger。`explainability.py` 的死 trigger-chain DAG 与 `schema.py`
的死 `trigger_chains` 表都还在册，复用该词即造第二份「触发器」语义。
"""

import hashlib
import re
import threading
from typing import Any, Dict, Iterable, List, Optional, Tuple

from neurova.core.logger import get_logger

logger = get_logger(__name__)

#: 线索种类闭集。`hypernym`＝上位名，`situation`＝情境，`foresight`＝前瞻（批 C 才产）。
CUE_KINDS = ("hypernym", "situation", "foresight")

#: 规则派生的来源标记；模型派生写 `model`，预算与审计据此分账。
CUE_SOURCE_RULE = "rule"

#: 每条记忆的规则线索上限。上限是**形态上限**（防止一条记忆刷出一片线索污染倒排），
#: 不是调用预算上限——本批根本没有调用。
MAX_RULE_CUES_PER_MEMORY = 6

#: 记忆类型 → 中文上位标签。本仓结构化词汇（枚举键）一律是英文，而词法倒排
#: 抽的是中文 2–4 字串（`semantic_search.py:113-119`），英文标签进不了中文查询的分词面。
#: 因此这里显式落成中文——且**这张表只在本模块出现、只被本模块消费**，
#: 不在前端 i18n 之外再造第二份显示名口径（那是展示层账目，与检索层线索不是一回事）。
_TYPE_CUE_LABELS: Dict[str, Tuple[str, ...]] = {
    "episodic": ("经历", "发生过的事"),
    "semantic": ("事实", "已知信息"),
    "procedural": ("做法", "操作步骤"),
    "pattern": ("规律", "反复出现的模式"),
    "emotional": ("情绪", "感受"),
    "working": ("当下事项",),
    "workflow_experience": ("流程经验", "踩过的坑"),
}

#: 分类 → 中文上位标签（同上，检索层口径，单点在此）。
_CATEGORY_CUE_LABELS: Dict[str, Tuple[str, ...]] = {
    "general": (),
    "conversation": ("交谈内容",),
    "knowledge": ("知识", "了解到的事"),
    "experience": ("经验", "以往的处置"),
    "tool_usage": ("工具用法",),
    "reflection": ("反思", "总结出的教训"),
    "user_preference": ("偏好", "在意的东西", "忌讳"),
}

#: 情感 → 中文上位标签（只取规则标注已有的那几档，不新造情感体系）。
_EMOTION_CUE_LABELS: Dict[str, Tuple[str, ...]] = {
    "joy": ("愉快的事",),
    "sadness": ("难受的事",),
    "anger": ("令人生气的事",),
    "fear": ("担心的事", "忌讳"),
    "trust": ("信任相关",),
    "anticipation": ("将要发生的事", "提前准备"),
    "surprise": ("意外",),
    "disgust": ("排斥", "忌讳"),
}

# 中文 2–4 字串抽取与 `semantic_search._extract_keywords` 同形——线索文本必须经
# **同一把分词刀**切过，否则「写侧按一套词切、读侧按另一套词查」就是第二条断链。
_CJK_RUN = re.compile(r"[\u4e00-\u9fa5]{2,4}")
_PUNCT = re.compile(r"[\s，。、；：！？,.;:!?”\"'（）()【】\[\]{}<>《》\-—_/\\|]+")


def normalizeCueText(text: str) -> str:
    """归一：压空白、去首尾标点、转小写。用于幂等键与去重比较。"""
    if not text:
        return ""
    collapsed = _PUNCT.sub("", str(text))
    return collapsed.strip().lower()


def cueNormKey(text: str) -> str:
    """幂等键：归一文本的短摘要。同一条记忆上同键的线索只保一条。"""
    normalized = normalizeCueText(text)
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]


def cueTokens(text: str) -> List[str]:
    """线索文本进倒排所用的词面——与关键词检索同一把刀。"""
    return [tok for tok in _CJK_RUN.findall(normalizeCueText(text)) if tok]


def deriveRuleAssociationCues(
    content: str,
    memoryType: Optional[str] = None,
    category: Optional[str] = None,
    inferredCategories: Optional[Iterable[str]] = None,
    emotion: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """由**行上已有的结构化标签**派生规则线索。确定性、可重放、零模型调用。

    Args:
        content: 记忆正文（本函数不读它的词面——正文的词面已经在索引里，
            复制进线索只是膨胀倒排；这里只产**抽象层**的词）。
        memoryType/category/emotion: 行自带标签。
        inferredCategories: 分类器多标签结果（本批是 `classify_category_multi_label`
            的第一个真实消费者；此前它只被分类器内部自用）。

    Returns:
        `[{cue_text, cue_kind, confidence, norm_key}, ...]`，按 (kind, text) 稳定序，
        超上限即截断。
    """
    collected: List[Tuple[str, str, float]] = []
    seenNorms: set = set()

    def _add(texts: Tuple[str, ...], kind: str, confidence: float) -> None:
        for raw in texts:
            cueText = (raw or "").strip()
            if len(cueText) < 2:
                continue
            norm = cueNormKey(cueText)
            if norm in seenNorms:
                continue
            seenNorms.add(norm)
            collected.append((cueText, kind, confidence))

    _add(_TYPE_CUE_LABELS.get(memoryType or "", ()), "hypernym", 0.5)
    _add(_CATEGORY_CUE_LABELS.get(category or "", ()), "hypernym", 0.5)
    for inferred in inferredCategories or ():
        _add(_CATEGORY_CUE_LABELS.get(str(inferred), ()), "hypernym", 0.4)
    _add(_EMOTION_CUE_LABELS.get(emotion or "", ()), "situation", 0.35)

    collected.sort(key=lambda item: (item[1], item[0]))
    cues: List[Dict[str, Any]] = []
    for cueText, kind, confidence in collected[:MAX_RULE_CUES_PER_MEMORY]:
        cues.append(
            {
                "cue_text": cueText,
                "cue_kind": kind,
                "confidence": confidence,
                "norm_key": cueNormKey(cueText),
            }
        )
    return cues


class AssociationCueStore:
    """`memory_cues` 的唯一读写口（与 `memories` 同库：persist 伴生库）。

    作用域门与主表一致——线索按 `(agent_id, neuser_id, user_id)` 三元组隔离，
    身份口径走 §6-163 收口后的唯一通道，不在这里再猜一遍是谁。
    """

    def __init__(self, connGetter, lock: threading.RLock, agentId: str):
        self._connGetter = connGetter
        self._lock = lock
        self._agent_id = agentId

    def replaceForMemory(
        self,
        memoryId: str,
        cues: List[Dict[str, Any]],
        scope: Tuple[str, str],
        createdAt: str,
    ) -> int:
        """按 (memory_id, norm_key) 幂等写入；返回落库条数。

        幂等是硬要求：线索表若随重放/重派生长，而它没有任何清理消费方，
        就成了「只写不删的派生表」——本仓同名事故形态。
        """
        if not memoryId:
            return 0
        neuserId, userId = scope
        with self._lock:
            conn = self._connGetter()
            existing = {
                row[0]
                for row in conn.execute(
                    "SELECT norm_key FROM memory_cues WHERE memory_id = ?", (memoryId,)
                )
            }
            inserted = 0
            for cue in cues:
                norm = cue.get("norm_key") or cueNormKey(cue.get("cue_text", ""))
                if not norm or norm in existing:
                    continue
                existing.add(norm)
                conn.execute(
                    "INSERT INTO memory_cues ("
                    " cue_id, memory_id, cue_text, cue_kind, cue_source, confidence,"
                    " norm_key, agent_id, neuser_id, user_id, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        f"cue_{norm}_{memoryId}",
                        memoryId,
                        str(cue.get("cue_text", "")).strip(),
                        cue.get("cue_kind", "hypernym"),
                        cue.get("cue_source", CUE_SOURCE_RULE),
                        float(cue.get("confidence", 0.0)),
                        norm,
                        self._agent_id,
                        neuserId,
                        userId,
                        createdAt,
                    ),
                )
                inserted += 1
            conn.commit()
        return inserted

    def purgeForMemory(self, memoryId: str) -> None:
        if not memoryId:
            return
        with self._lock:
            conn = self._connGetter()
            conn.execute("DELETE FROM memory_cues WHERE memory_id = ?", (memoryId,))
            conn.commit()

    def listForMemory(self, memoryId: str, scope: Tuple[str, str]) -> List[Dict[str, Any]]:
        """按作用域取一条记忆的线索。跨作用域取不到——这是门，不是排序问题。"""
        if not memoryId:
            return []
        neuserId, userId = scope
        with self._lock:
            conn = self._connGetter()
            rows = conn.execute(
                "SELECT cue_text, cue_kind, cue_source, confidence, norm_key"
                " FROM memory_cues"
                " WHERE memory_id = ? AND agent_id = ? AND neuser_id = ? AND user_id = ?"
                " ORDER BY cue_kind, cue_text",
                (memoryId, self._agent_id, neuserId, userId),
            ).fetchall()
        return [
            {
                "cue_text": row[0],
                "cue_kind": row[1],
                "cue_source": row[2],
                "confidence": row[3],
                "norm_key": row[4],
            }
            for row in rows
        ]

    def cueTextsByMemory(self, scope: Tuple[str, str]) -> Dict[str, List[str]]:
        """整作用域的 `memory_id → [线索文本]`，供重启后重建倒排一次批量取。"""
        neuserId, userId = scope
        with self._lock:
            conn = self._connGetter()
            rows = conn.execute(
                "SELECT memory_id, cue_text FROM memory_cues"
                " WHERE agent_id = ? AND neuser_id = ? AND user_id = ?"
                " ORDER BY cue_kind, cue_text",
                (self._agent_id, neuserId, userId),
            ).fetchall()
        grouped: Dict[str, List[str]] = {}
        for memoryId, cueText in rows:
            grouped.setdefault(memoryId, []).append(cueText)
        return grouped

    def stats(self) -> Dict[str, int]:
        with self._lock:
            conn = self._connGetter()
            total = conn.execute("SELECT COUNT(*) FROM memory_cues").fetchone()[0]
            distinct = conn.execute("SELECT COUNT(DISTINCT norm_key) FROM memory_cues").fetchone()[0]
            rows = conn.execute("SELECT COUNT(DISTINCT memory_id) FROM memory_cues").fetchone()[0]
        return {"cues": total, "distinctNormKeys": distinct, "memoriesWithCues": rows}
