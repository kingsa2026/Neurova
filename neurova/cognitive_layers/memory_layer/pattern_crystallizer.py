"""
经验结晶器 — Hebb 学习替代 LLM 调用

深度模块设计：小接口（observe/retrieve），深实现（模式提取+结晶）。
"""

from __future__ import annotations

from neurova.core.logger import get_logger
import re
from datetime import datetime, timezone
from typing import Any, Dict, List

from .cognitive_storage_engine import CognitiveStorageEngine, MemoryType, UnifiedMemoryNode

logger = get_logger(__name__)

# 简单停用词表 (中英文常见无意义词, 避免引入 jieba 等重型依赖)
_STOP_WORDS = frozenset({
    # 中文停用词
    "的", "了", "是", "在", "我", "有", "和", "就", "不", "人", "都", "一", "一个",
    "上", "也", "很", "到", "说", "要", "去", "你", "会", "着", "没有", "看", "好",
    "自己", "这", "那", "它", "他", "她", "们", "把", "被", "让", "使", "给",
    "请", "帮", "帮我", "可以", "能", "能够", "需要", "想要", "应该", "可能",
    "什么", "怎么", "怎样", "如何", "为什么", "哪里", "哪个", "哪些",
    "这个", "那个", "这些", "那些", "这样", "那样",
    "现在", "今天", "明天", "昨天", "之前", "之后", "时候",
    "相关", "的资料", "情况", "问题", "东西",
    # 英文停用词
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "must", "can", "need", "to", "of", "in",
    "on", "at", "by", "for", "with", "about", "as", "into", "through",
    "during", "before", "after", "above", "below", "from", "up", "down",
    "and", "or", "but", "if", "then", "else", "when", "where", "why",
    "how", "all", "each", "every", "both", "few", "more", "most", "other",
    "some", "such", "no", "not", "only", "own", "same", "so", "than",
    "too", "very", "just", "please", "help", "me", "i", "you", "he",
    "she", "it", "we", "they", "this", "that", "these", "those",
})

# 关键词提取正则: 匹配连续中文或英文单词
_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]+|[a-zA-Z][a-zA-Z0-9_]*")


def _tokenize(context: str) -> List[str]:
    """简单分词: 中文连续字符 + 英文单词"""
    return _TOKEN_RE.findall(context)


def _extract_keywords(context: str, max_keywords: int = 8) -> List[str]:
    """提取关键词: 分词 → 去停用词 → 去重 → 取前 N 个"""
    tokens = _tokenize(context)
    seen = set()
    keywords = []
    for token in tokens:
        token_lower = token.lower() if token.isascii() else token
        if token_lower in _STOP_WORDS:
            continue
        if len(token_lower) < 2:
            continue
        if token_lower in seen:
            continue
        seen.add(token_lower)
        keywords.append(token_lower)
        if len(keywords) >= max_keywords:
            break
    return keywords


class PatternCrystallizer:
    """
    经验结晶器 — Hebb 学习替代 LLM 调用

    核心思想：
      1. 观察工具使用模式
      2. 当同一模式出现3次以上且成功率>60%时结晶
      3. 结晶经验存储为 PATTERN 类型记忆
      4. 不调用 LLM，成本降97%
    """

    def __init__(
        self,
        engine: CognitiveStorageEngine,
        evolution_orchestrator=None,
        state_path: Optional[str] = None,
    ):
        """
        初始化经验结晶器

        Args:
            engine: CognitiveStorageEngine 实例
            evolution_orchestrator: EvolutionOrchestrator 实例（可选）
            state_path: 观察缓冲持久化文件（可选；C9 断链修复——
                此前 _buffer 纯内存，重启丢计数，低频场景"≥3 次结晶"
                永远凑不齐。提供时按模式键持久化聚合计数，重启恢复）
        """
        self.engine = engine
        self.evolution = evolution_orchestrator
        self._state_path = state_path
        self._buffer: Dict[str, List[Dict[str, Any]]] = {}
        self._load_buffer_state()

        logger.info("PatternCrystallizer 初始化完成")

    def _load_buffer_state(self) -> None:
        """从 state 文件恢复观察聚合计数（C9；缺文件/损坏静默跳过）。"""
        if not self._state_path:
            return
        try:
            from pathlib import Path as _Path
            import json as _json

            p = _Path(self._state_path)
            if not p.exists():
                return
            data = _json.loads(p.read_text(encoding="utf-8"))
            # state 存聚合形态 {key: {"observations": n, "successes": n,
            # "last_context": str}}；恢复为等价缓冲条目（合成条目不含原文，
            # 只保计数语义）
            for key, agg in data.items():
                n = int(agg.get("observations", 0))
                succ = int(agg.get("successes", 0))
                if n <= 0 or n >= 3:
                    continue  # 满 3 的缓冲即时结晶后已清空，不恢复
                ctx = str(agg.get("last_context", ""))[:200]
                self._buffer[key] = [
                    {"tool": agg.get("tool", key), "success": i < succ, "context": ctx}
                    for i in range(n)
                ]
        except Exception as e:
            logger.debug("结晶缓冲状态恢复跳过: %s", e)

    def _save_buffer_state(self) -> None:
        """把缓冲聚合计数落盘（C9；写失败不影响主流程）。"""
        if not self._state_path:
            return
        try:
            from pathlib import Path as _Path
            import json as _json

            data = {}
            for key, entries in self._buffer.items():
                if not entries:
                    continue
                data[key] = {
                    "observations": len(entries),
                    "successes": sum(1 for e in entries if e.get("success")),
                    "tool": entries[0].get("tool", ""),
                    "last_context": entries[-1].get("context", ""),
                }
            p = _Path(self._state_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(_json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.debug("结晶缓冲状态落盘失败: %s", e)

    def observe(
        self,
        tool_name: str,
        context: str,
        success: bool,
        result: Any = None,
    ) -> None:
        """
        观察工具使用

        Args:
            tool_name: 工具名称
            context: 使用上下文
            success: 是否成功
            result: 工具结果（可选）
        """
        key = self._extract_pattern_key(context)

        if key not in self._buffer:
            self._buffer[key] = []

        self._buffer[key].append(
            {
                "tool": tool_name,
                "success": success,
                "context": context[:200],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

        logger.debug("观察到工具使用: %s, 模式键: %s", tool_name, key)
        self._save_buffer_state()

        # 当同一模式观察3次时尝试结晶
        if len(self._buffer[key]) >= 3:
            self._try_crystallize(key)
            self._save_buffer_state()

    def _try_crystallize(self, key: str) -> None:
        """
        尝试结晶

        Args:
            key: 模式键
        """
        entries = self._buffer.get(key, [])
        if not entries:
            return

        # 计算成功率
        success_count = sum(1 for e in entries if e["success"])
        rate = success_count / len(entries)

        # 成功率低于60%不结晶
        if rate < 0.6:
            logger.debug("模式 '%s' 成功率 %.0f%% < 60%%，不结晶", key, rate * 100)
            del self._buffer[key]
            return

        # 找出最常用的工具
        tool_counts: Dict[str, int] = {}
        for e in entries:
            tool_counts[e["tool"]] = tool_counts.get(e["tool"], 0) + 1
        primary_tool = max(tool_counts.items(), key=lambda x: x[1])[0]

        # 创建结晶记忆节点
        # content 附原始 context 片段（预存失败修复 2026-09-02）：旧内容只含
        # pattern_key（管道符键），自然语言检索永远命中不了结晶经验；
        # 顺修 f-string 的 %% 笔误（字面双百分号）
        sample_ctx = entries[0].get("context", "")[:80]
        node = UnifiedMemoryNode(
            content=(
                f"模式: '{key}' 类任务用 {primary_tool} 成功率 {rate * 100:.0f}%"
                f" | {sample_ctx}"
            ),
            memory_type=MemoryType.PATTERN,
            category="crystallized",
            temperature=rate * 100.0,  # 成功率即温度（0-100）
            metadata={
                "pattern_key": key,
                "primary_tool": primary_tool,
                "success_rate": rate,
                "sample_count": len(entries),
            },
        )

        # 存储
        self.engine.store(node)
        logger.info("结晶成功: '%s' → %s (成功率 %.0f%%)", key, primary_tool, rate * 100)

        # 通知 EvolutionOrchestrator
        if self.evolution:
            try:
                from neurova.evolution.evolution_facade import EvolutionFacade
                facade = EvolutionFacade(self.evolution)
                facade.record_experience(
                    node.content,
                    key,
                    [primary_tool],
                    True,
                )
            except Exception as e:
                logger.warning("通知 EvolutionOrchestrator 失败: %s", e)

        # 清空缓冲区
        del self._buffer[key]

    def retrieve(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        检索结晶经验

        Args:
            query: 查询文本
            limit: 返回数量限制

        Returns:
            结晶经验列表
        """
        nodes = self.engine.retrieve(
            query,
            limit=limit,
            filters={"memory_type": "pattern"},
        )

        return [
            {
                "id": n.id,
                "content": n.content,
                "method": n.metadata.get("primary_tool", ""),
                "confidence": n.metadata.get("success_rate", 0),
                "score": n.temperature,
                "source": "crystallized",
            }
            for n in nodes
        ]

    def _extract_pattern_key(self, context: str) -> str:
        """提取模式关键词

        基于关键词提取而非位置前缀, 能区分前缀相同但语义不同的上下文。
        归一化处理: 去除空白差异, 去停用词, 取前 8 个关键词组合。

        Args:
            context: 上下文文本

        Returns:
            模式键 (关键词以 '|' 分隔)
        """
        if not context or not context.strip():
            return ""

        keywords = _extract_keywords(context, max_keywords=8)
        if not keywords:
            # 全是停用词或单字符的退化情况: 回退到归一化前缀
            normalized = re.sub(r"\s+", "", context[:50])
            return normalized

        return "|".join(keywords)
