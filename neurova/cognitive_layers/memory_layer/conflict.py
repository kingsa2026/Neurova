"""
冲突检测引擎 - 检测新记忆与已有记忆的冲突

支持两种检测模式：
1. 语义模式：使用语义相似度检测（需要SemanticSearch）
2. 规则模式：基于字符重叠和否定词检测（无需模型）

**信号必须落在"同一命题的否证"上**（Issue #72 残余项的根因）：一条冲突要么是
"同一命题被一方否证"，要么是"同一对象的取值落进矛盾词对"。两者都要求两句在说
同一件事——否则就是两条无关记忆。此前规则模式用"子串含否定词"+"字符重叠 ≥ 0.3"
判定，于是「今天天气不错」里的"不"被当成否定词、寒暄复述（相似度 0.64）也报冲突，
真矛盾（正常/故障，相似度 0.2）与噪声混在同一批 `negation_conflict` 里。下游据此
判不出哪条为准，这条链因此长期只能是"纯观测"——判不出真伪不是检测器给不出分，
是它根本没给出**可分辨的信号**。

比较在**子句**层做：一轮对话是两个说话人的两段话，矛盾住在子句里，
`"用户: X\n助手: Y"` 必须能与其子句逐条对上。报出的冲突在 `basis` 里逐字带出
被比较的两个子句——下游的裁决起点在这里。
"""

import datetime
import re
from neurova.core.logger import get_logger
from typing import Any, Dict, List, Optional

from .models import Memory

logger = get_logger(__name__)

# 否定词：整词匹配的**语义标记**，不是子串包含。长词在前，折叠时先吃掉长词
# （"不是"先于"不"），否则"不是"折成"是"会把命题对错位。
_NEGATION_MARKERS = (
    "不是", "没有", "否认", "否定", "不", "没", "非", "无", "未", "别",
    "can't", "cannot", "couldn't", "didn't", "doesn't", "don't", "hadn't",
    "hasn't", "haven't", "isn't", "aren't", "wasn't", "weren't", "won't",
    "wouldn't", "shouldn't", "neither", "never", "nobody", "none", "nor",
    "nothing", "nowhere", "not", "no",
)

# 矛盾词对：同一对象的取值互为反义。要求两侧**共享内容词**才算冲突，
# 否则"成本增加了"与"效率减少了"会被算成在说同一件事——两个不同对象各自变化，
# 不是矛盾。
_CONTRADICTION_PAIRS = (
    ("正常", "挂了"), ("正常", "故障"), ("正常", "失败"),
    ("成功", "失败"), ("开启", "关闭"), ("增加", "减少"),
    ("提升", "下降"), ("上升", "下降"), ("快", "慢"), ("好", "差"), ("多", "少"),
    ("是", "不是"), ("有", "没有"), ("能", "不能"),
)

# 说话人前缀：一轮对话的每一段是"用户: X"/"助手: Y"，比较单位是说完话的那句。
_SPEAKER_PREFIX = re.compile(r"^(用户|助手|user|assistant|ai|system)\s*[:：]\s*")
_CLAUSE_SPLIT = re.compile(r"[。；;！!？?，,、\s]+")
_WORD_CHARS = re.compile(r"[^\w\u4e00-\u9fff]+")

# 同一命题的判据：把否定标记折掉后，两句要么同串，要么结尾同源且长度相当
# （"我喜欢咖啡" vs "我喜欢咖啡的香气" 是同一命题；"今天天气不错" vs "今天天气很好" 不是）。
_PROPOSITION_COMMON_TAIL = 2


def _clauses(text: str) -> List[str]:
    """把一段话切成可比较的子句（剥说话人前缀、去标点、小写、去重保序）。"""
    out: List[str] = []
    for raw in _CLAUSE_SPLIT.split(text or ""):
        clause = _WORD_CHARS.sub("", _SPEAKER_PREFIX.sub("", raw.strip().lower()))
        if clause and clause not in out:
            out.append(clause)
    return out


def _foldNegation(clause: str) -> tuple:
    """折掉否定标记，返回 (命题, 是否含否定标记)。"""
    folded = clause
    negated = False
    for marker in _NEGATION_MARKERS:
        if marker in folded:
            negated = True
            folded = folded.replace(marker, "")
    return _WORD_CHARS.sub("", folded), negated


def _commonTail(left: str, right: str) -> int:
    """两句结尾连续相同的字符数（中文无词界，尾串同源是最稳的"同一命题"证据）。"""
    count = 0
    while count < min(len(left), len(right)) and left[-1 - count] == right[-1 - count]:
        count += 1
    return count


def _sameProposition(left: str, right: str) -> bool:
    """折掉否定后的两个命题是否在说同一件事。"""
    if not left or not right:
        return False
    if left == right:
        return True
    tail = _commonTail(left, right)
    return tail >= max(_PROPOSITION_COMMON_TAIL, min(len(left), len(right)) // 2) \
        and abs(len(left) - len(right)) <= 2


def _sharedContent(left: str, right: str) -> bool:
    """两句是否共享内容词（矛盾词对之外的实词）——没有共同对象就谈不上取值冲突。"""
    def _bigrams(text: str) -> set:
        return {text[i:i + 2] for i in range(len(text) - 1)}

    return bool(_bigrams(left) & _bigrams(right))


def _contradictionKind(left: str, right: str) -> bool:
    """两个子句是否落在同一对象的矛盾词对上（要求两侧共享内容词）。"""
    for word1, word2 in _CONTRADICTION_PAIRS:
        if word1 == word2:
            continue
        if not ((word1 in left and word2 in right) or (word2 in left and word1 in right)):
            continue
        leftRest = left.replace(word1, "").replace(word2, "")
        rightRest = right.replace(word1, "").replace(word2, "")
        if _sharedContent(leftRest, rightRest):
            return True
    return False


def judgeClauseConflict(text1: str, text2: str) -> Optional[tuple]:
    """全仓唯一的记忆侧冲突判据：返回 (类型, 左子句, 右子句, 依据) 或 None。

    `LegacyConflictDetector` 与 `ConflictModule` 都从这里取判据——一个根因两处实现，
    修一处等于没修（第二份实现会各自漂回"子串含否定词"的老路）。
    """
    for left in _clauses(text1):
        leftProp, leftNegated = _foldNegation(left)
        for right in _clauses(text2):
            rightProp, rightNegated = _foldNegation(right)
            if leftNegated != rightNegated and _sameProposition(leftProp, rightProp):
                return ("negation_conflict", left, right,
                        "同一命题的否证：%r 与 %r（一方带否定标记）" % (left, right))
            if _contradictionKind(left, right):
                return ("semantic_contradiction", left, right,
                        "同一对象的取值互斥：%r 与 %r" % (left, right))
    return None


class LegacyConflictDetector:
    """
    冲突检测引擎（Legacy；Memory 对象入参，仅历史调用方使用）

    检测新记忆与已有记忆的冲突。
    """

    def __init__(self, use_semantic: bool = True):
        """
        初始化冲突检测器
        
        Args:
            use_semantic: 是否使用语义相似度检测
        """
        self._conflict_history: List[Dict[str, Any]] = []
        self._use_semantic = use_semantic
        self._semantic_search = None
        
        # 延迟初始化语义搜索
        if use_semantic:
            try:
                from .semantic_search import get_semantic_search
                self._semantic_search = get_semantic_search()
            except Exception as e:
                logger.warning("语义搜索初始化失败，降级到规则模式: %s", e)
        
        logger.info("ConflictDetector 初始化完成 (semantic=%s)", use_semantic)

    def detect_conflict(self, new_memory: Memory, existing_memories: List[Memory]) -> List[Dict[str, Any]]:
        """
        检测新记忆与已有记忆的冲突

        Args:
            new_memory: 新记忆
            existing_memories: 已有记忆列表

        Returns:
            冲突列表
        """
        conflicts = []

        for existing_memory in existing_memories:
            conflict = self._check_pair_conflict(new_memory, existing_memory)
            if conflict:
                conflicts.append(conflict)
                self._conflict_history.append(conflict)

        return conflicts

    def _check_pair_conflict(self, memory1: Memory, memory2: Memory) -> Optional[Dict[str, Any]]:
        """检查两个记忆之间的冲突——判据是"同一命题"或"同一对象的矛盾取值"。

        逐子句比较（一轮对话的每一段都是一个说话人的子句），命中即报出，并把
        凭哪两句认定的写进 `basis`（唯一读口径：账上存它、人被它说服）。
        相似度仍是读数，但不再充当判据：0.3 的门等于"只要有点像就算冲突"，
        正是噪声的来源。
        """
        content1 = memory1.content
        content2 = memory2.content
        lower1 = content1.lower()
        lower2 = content2.lower()

        hit = judgeClauseConflict(content1, content2)
        if hit is None:
            return None

        conflict_type, basis = hit[0], hit[3]
        if self._use_semantic and self._semantic_search:
            similarity = self._semantic_search.compute_similarity(lower1, lower2)
            detection_mode = "semantic"
        else:
            similarity = self._calculate_similarity(lower1, lower2)
            detection_mode = "rule"

        return {
            "type": conflict_type,
            "memory1_id": memory1.id,
            "memory2_id": memory2.id,
            "similarity": similarity,
            "contradiction_score": self._check_contradiction(lower1, lower2),
            "detection_mode": detection_mode,
            "basis": basis,
            "description": basis,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }

    def _check_contradiction(self, text1: str, text2: str) -> float:
        """矛盾词对得分（子句层，要求共享内容词）——读数用，判据见 `judgeClauseConflict`。"""
        for left in _clauses(text1):
            for right in _clauses(text2):
                if _contradictionKind(left, right):
                    return 0.5
        return 0.0

    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """计算文本相似度（简化版）"""
        if not text1 or not text2:
            return 0.0

        # 使用字符集合重叠率
        set1 = set(text1)
        set2 = set(text2)

        intersection = len(set1.intersection(set2))
        union = len(set1.union(set2))

        return intersection / union if union > 0 else 0.0

    def get_conflict_history(self) -> List[Dict[str, Any]]:
        """获取冲突历史"""
        return self._conflict_history.copy()

    def clear_history(self) -> None:
        """清空冲突历史"""
        self._conflict_history.clear()


# 向后兼容别名（补课 5.3：包级 ConflictDetector 已由 v2 占用；
# 本模块的旧名字保留导出，新代码请用 v2 或 Legacy 名）
ConflictDetector = LegacyConflictDetector
