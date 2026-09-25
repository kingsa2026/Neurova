"""
经验结晶器 — Hebb 学习替代 LLM 调用

深度模块设计：小接口（observe/retrieve），深实现（模式提取+结晶）。
"""

from __future__ import annotations

from neurova.core.logger import get_logger
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

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

# 结晶模式的冷档线（工单 017）：温度低于此值即退出注入池。
# 与 reap_stale_patterns() 配对构成淘汰路径——只衰减不屏蔽是假淘汰。
COLD_PATTERN_TEMPERATURE = 20.0


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
        # 入库门槛（工单 004）：默认值即历史上的字面量 3 / 0.6；
        # 值由 ExperienceFeedback 经 attach_crystallizer 桥推进（RSI 可调参数面）
        self.min_observations = 3
        self.min_success_rate = 0.6
        self._buffer: Dict[str, List[Dict[str, Any]]] = {}
        # 混合信号层：规则预筛（≥3 次 & 成功率≥60%）通过后，
        # 候选不再直写存储引擎，进入 _pending 队列等待 LLM 可复用性裁决
        # （低频批量，由 post_chat 复盘通道触发）。闸状态见 `_llm_gate`——
        # 它由治理设置在**裁决时刻**决定，不在构造期缓存（工单 015）。
        self._llm_judge = None  # 复盘通道注入的 LLM client；None = 零 LLM 语义（直写）
        self._pending: List[Dict[str, Any]] = []
        # 待裁决队列的有界上限与"已丢弃多少"计数（工单 005：静默丢候选 = 观察面失明）
        self._max_pending = 20
        self.pending_dropped = 0
        self._load_buffer_state()

        logger.info("PatternCrystallizer 初始化完成 (llm_gate=%s)", self._llm_gate)

    @property
    def _llm_gate(self) -> bool:
        """结晶 LLM 裁决闸开关（工单 015 收进治理设置）。

        刻意做成属性而非构造期赋值：治理设置是运行时可改的，构造期读一次
        等于"设置页改了要重启才认"——那和收口前那个没人能写的裸 env 是同一种
        幻影旋钮。优先级：env 显式 0 > env 显式 1 > 治理设置 > 默认开。
        """
        from neurova.security.governance_settings import resolve_flag

        return resolve_flag("crystallization_llm_gate_enabled", "NEUROVA_CRYSTALLIZATION_LLM_GATE")

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
                if key == "pending":
                    continue  # 待裁决队列单独恢复
                n = int(agg.get("observations", 0))
                succ = int(agg.get("successes", 0))
                # 无证据观察的个数也要跨重启保真：`evidenced` 键缺席说明是旧状态文件
                # （那时无证据会被算成失败票），按"全部有证据"恢复，行为与升级前一致
                evid = int(agg.get("evidenced", n))
                if n <= 0 or n >= self.min_observations:
                    continue  # 满门槛的缓冲即时结晶后已清空，不恢复
                ctx = str(agg.get("last_context", ""))[:200]
                self._buffer[key] = [
                    {"tool": agg.get("tool", key),
                     "success": True if i < succ else (False if i < evid else None),
                     "context": ctx}
                    for i in range(n)
                ]
            # 待裁决队列恢复（混合信号层；重启不丢候选）
            pending = data.get("pending")
            if isinstance(pending, list):
                self._pending = [p for p in pending if isinstance(p, dict) and p.get("key")][-20:]
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
                evidenced = [e for e in entries if e.get("success") is not None]
                data[key] = {
                    "observations": len(entries),
                    "successes": sum(1 for e in evidenced if e["success"]),
                    # 无证据观察单独计数：否则重启后它们会被恢复成失败票
                    "evidenced": len(evidenced),
                    "tool": entries[0].get("tool", ""),
                    "last_context": entries[-1].get("context", ""),
                }
            if self._pending:
                data["pending"] = self._pending
            p = _Path(self._state_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(_json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.debug("结晶缓冲状态落盘失败: %s", e)

    def observe(
        self,
        tool_name: str,
        context: str,
        success: Optional[bool],
        result: Any = None,
    ) -> None:
        """
        观察工具使用

        Args:
            tool_name: 工具名称
            context: 使用上下文
            success: 客观成败三态（工单 003）：True/False 是回执，
                **None 是"这轮没有回执"** —— 进缓冲但不参与成功率分子分母，
                既不投成功票也不投失败票。
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

        # 同一模式观察够次数才尝试结晶（门槛来自登记表，工单 004）
        if len(self._buffer[key]) >= self.min_observations:
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

        # 工单 003：成功率只按**有客观回执**的观察算。`success is None` 表示
        # "这轮没测到成败"，既不是成功票也不是失败票 —— 旧写法
        # `sum(1 for e in entries if e["success"])` 把它算成失败，于是三次纯对话
        # 观察会被判成失败模式；若反过来当成成功，就是被废弃的那张恒真票。
        evidenced = [e for e in entries if e.get("success") is not None]
        if not evidenced:
            logger.debug("模式 '%s' 观察全部无客观回执，暂不裁决（缓冲保留）", key)
            return

        success_count = sum(1 for e in evidenced if e["success"])
        rate = success_count / len(evidenced)

        # 成功率未达门槛不结晶
        if rate < self.min_success_rate:
            logger.debug("模式 '%s' 成功率 %.0f%% < %.0f%%，不结晶",
                         key, rate * 100, self.min_success_rate * 100)
            self._buffer.pop(key, None)
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

        # 先清缓冲再存储/通知（闭环审查修 E2）：自喂 observe 在通知链内
        # 重新观察同一 key，缓冲不清空会触发递归重结晶与二删 KeyError；
        # 清空后自喂观察从干净周期起步（1 条 < 3 阈值，无递归）
        self._buffer.pop(key, None)

        candidate = {
            "key": key,
            "primary_tool": primary_tool,
            "rate": rate,
            "sample_count": len(entries),
            "sample_context": sample_ctx,
            "queued_at": datetime.now(timezone.utc).isoformat(),
        }

        # 混合信号层：规则预筛通过 ≠ 直接写库 —— 闸开启时一律先进待裁决队列，
        # 由 post_chat 复盘通道低频批量裁决（过滤词面匹配伪模式）。
        # 工单 005 改掉的是"judge 未注入 ⇒ 直写"：那等于裁决缺席即放行，
        # 首批候选永远绕过裁决。现在 judge 不在位就留在队里等，不直写。
        if self._llm_gate:
            self._enqueue_candidate(candidate)
            self._save_buffer_state()
            logger.info("结晶候选进入 LLM 待裁决队列: '%s' (待审 %d 条)", key, len(self._pending))
            return

        # 显式关闸（治理设置 crystallization_llm_gate_enabled=false）仍按操作者
        # 选择直写——闸是"要不要送裁决"，不是"要不要入库"
        self._store_candidate(candidate)
        self._save_buffer_state()

    def _enqueue_candidate(self, candidate: Dict[str, Any]) -> None:
        """候选入待裁决队列；有界，且溢出丢弃必须可数（工单 005）。"""
        self._pending.append(candidate)
        self._enforce_pending_bound()

    def _enforce_pending_bound(self) -> int:
        """按 FIFO 收缩到上限，返回被丢弃条数（静默丢 = 观察面看不见任何丢失）。"""
        overflow = len(self._pending) - self._max_pending
        if overflow <= 0:
            return 0
        dropped = self._pending[:overflow]
        self._pending = self._pending[overflow:]
        self.pending_dropped += len(dropped)
        logger.warning(
            "结晶待裁决队列超上界 %d，丢弃最旧 %d 条（累计丢弃 %d）：keys=%s",
            self._max_pending, len(dropped), self.pending_dropped,
            [c.get("key") for c in dropped],
        )
        return len(dropped)

    def _store_candidate(self, candidate: Dict[str, Any]) -> None:
        """按候选构造 PATTERN 节点写入存储引擎并通知进化编排器。"""
        key = candidate["key"]
        primary_tool = candidate["primary_tool"]
        rate = candidate["rate"]
        sample_ctx = candidate.get("sample_context", "")[:80]
        node = UnifiedMemoryNode(
            content=(
                f"模式: '{key}' 类任务用 {primary_tool} 成功率 {rate * 100:.0f}%"
                f" | {sample_ctx}"
            ),
            memory_type=MemoryType.PATTERN,
            category="crystallized",
            # 工单 017：自述成功率不得换来永久豁免。旧写法 `rate * 100` 让
            # rate≥0.8 的节点落进温度策略的「>=80 不衰减」豁免区——一次好读数
            # 就永久固化，而 PATTERN 节点本来没有任何淘汰分支。现在满分为 75，
            # 排序信息保留（高成功率仍更热），衰减路径对所有结晶模式生效。
            # 真正的永久豁免只有一条来路：管理页/API 的人工升格
            # （lifecycle_stage=crystallized → on_decay(is_crystallized=True)）。
            temperature=rate * 75.0,  # 成功率即温度，但封顶在免衰减豁免区之下
            metadata={
                "pattern_key": key,
                "primary_tool": primary_tool,
                "success_rate": rate,
                "sample_count": candidate.get("sample_count", 0),
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
                # 工单 005：不再回灌 record_experience(..., True, ...) —— 那等于门槛
                # 给自己投一张任务成功票，结晶越多 success_rate 越好看（自喂递归的
                # 另一条路）。只通报"有新模式入库"，成败票一张都不投。
                facade.notify_pattern_crystallized(
                    pattern_key=key,
                    primary_tool=primary_tool,
                    success_rate=rate,
                    sample_count=candidate.get("sample_count", 0),
                )
            except Exception as e:
                logger.warning("通知 EvolutionOrchestrator 失败: %s", e)

    # ── 混合信号层：待裁决队列管理 ──

    def set_llm_judge(self, llm_client: Any) -> None:
        """注入复盘通道的 LLM client（幂等）。注入后闸分流生效。"""
        self._llm_judge = llm_client

    def list_pending(self) -> List[Dict[str, Any]]:
        """待 LLM 裁决的结晶候选（只读快照）。"""
        return [dict(c) for c in self._pending]

    def _candidate_age_hours(self, candidate: Dict[str, Any]) -> Optional[float]:
        """候选年龄（小时）；时间戳不可解析时返回 None（= 不可判龄，按超龄处理）。

        旧实现返回 0.0：该候选既永不超龄被处理，也没人再裁决它 —— 僵尸候选。
        """
        try:
            queued = datetime.fromisoformat(candidate.get("queued_at"))
        except (ValueError, TypeError):
            return None
        if queued.tzinfo is None:
            queued = queued.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - queued).total_seconds() / 3600.0

    def _prune_expired_pending(self, max_age_hours: float = 48.0) -> int:
        """超龄候选丢弃并计数（工单 005）。

        旧行为是"超龄自动放行入库"：那是给绕过裁决留的 48 小时后门 ——
        只过了统计预筛的候选本来就缺可复用性判断，拖得越久越该被怀疑，
        而不是越该被放行。不可判龄的候选一并丢弃，不留在队里当僵尸。
        """
        def _expired(candidate: Dict[str, Any]) -> bool:
            age = self._candidate_age_hours(candidate)
            return age is None or age >= max_age_hours

        expired = [c for c in self._pending if _expired(c)]
        if expired:
            self.pending_dropped += len(expired)
            logger.warning(
                "结晶候选超龄/不可判龄丢弃 %d 条（累计 %d）：keys=%s",
                len(expired), self.pending_dropped, [c.get("key") for c in expired],
            )
            self._pending = [c for c in self._pending if not _expired(c)]
            self._save_buffer_state()
        return len(expired)

    async def review_pending_with_llm(self, llm_client: Any = None, max_age_hours: float = 48.0) -> Dict[str, Any]:
        """复盘通道入口：批量请求 LLM 对待裁决候选做可复用性裁决。

        judge 失败/不可用时不丢数据——候选留队等下轮（超龄由 _prune 兜底放行）。
        Returns: {"reviewed": n, "approved": n, "rejected": n, "skipped": n}
        """
        client = llm_client or self._llm_judge
        if not self._pending:
            return {"reviewed": 0, "approved": 0, "rejected": 0, "skipped": 0}
        self._prune_expired_pending(max_age_hours)
        if not self._pending:
            return {"reviewed": 0, "approved": 0, "rejected": 0, "skipped": 0}

        if client is None:
            return {"reviewed": 0, "approved": 0, "rejected": 0, "skipped": len(self._pending)}

        listing = "\n".join(
            f"- [{c['key']}] 工具={c['primary_tool']} 成功率={c['rate']*100:.0f}% "
            f"样本={c['sample_count']} 上下文片段: {c.get('sample_context', '')[:60]}"
            for c in self._pending
        )
        prompt = (
            "以下是从工具使用记录中按统计规则预筛出的候选行为模式。请逐条判断该模式"
            "是否为可复用的行为规律（可复用），还是一次性事实/临时环境故障/个人偏好/"
            "无依据猜测（不可复用）。只依据给定证据判断，不要臆测。\n\n"
            f"{listing}\n\n"
            '只输出 JSON：{"verdicts": [{"key": "<原模式键>", "reusable": true/false, "reason": "<一句话>"}]}'
        )
        try:
            response = await client.generate(prompt)
        except Exception as e:
            logger.warning("结晶 LLM 裁决调用失败（候选留队）: %s", e)
            return {"reviewed": 0, "approved": 0, "rejected": 0, "skipped": len(self._pending)}

        verdicts = self._parse_verdicts(response if isinstance(response, str) else str(response))
        return self.confirm_pending(verdicts)

    def _parse_verdicts(self, response: str) -> List[Dict[str, Any]]:
        """从 LLM 响应解析裁决列表（宽松 JSON 提取；坏行跳过）。"""
        import json as _json
        import re as _re

        try:
            match = _re.search(r"\{[\s\S]*\}", response)
            if not match:
                return []
            data = _json.loads(match.group())
            verdicts = []
            for v in data.get("verdicts", []):
                if not isinstance(v, dict) or not v.get("key"):
                    continue
                verdicts.append(
                    {
                        "key": str(v["key"]),
                        "approved": bool(v.get("reusable", False)),
                        "reason": str(v.get("reason", "")),
                    }
                )
            return verdicts
        except (ValueError, TypeError):
            return []

    def confirm_pending(self, verdicts: List[Dict[str, Any]]) -> Dict[str, Any]:
        """按裁决结果处置待审候选：approved → 写库并通知；否则丢弃。"""
        by_key = {v["key"]: v for v in verdicts if isinstance(v, dict) and v.get("key")}
        approved = rejected = 0
        kept: List[Dict[str, Any]] = []
        for candidate in self._pending:
            verdict = by_key.get(candidate["key"])
            if verdict is None:
                kept.append(candidate)  # 未裁决（LLM 漏判）→ 留队等下轮
                continue
            if verdict.get("approved"):
                self._store_candidate(candidate)
                approved += 1
            else:
                rejected += 1
                logger.info("结晶候选被 LLM 否决: '%s' (%s)", candidate["key"], verdict.get("reason", ""))
        self._pending = kept
        self._save_buffer_state()
        return {"reviewed": len(by_key), "approved": approved, "rejected": rejected, "skipped": len(kept)}


    def reap_stale_patterns(
        self, idle_days: float = 30.0, decay_step: float = 15.0, limit: int = 500
    ) -> Dict[str, int]:
        """给闲置的结晶模式降温（工单 017 的淘汰写入方）。

        017 之前 PATTERN 节点没有任何衰减/淘汰分支：`update_temperature()` 零调用方，
        而入库温度又由自述成功率写成 `rate*100` ⇒ 一次好读数即进「>=80 不衰减」豁免区，
        越好的门固化越多。现在入库封顶在豁免区之下，闲置超期的按 `decay_step` 降温，
        冷到 `COLD_PATTERN_TEMPERATURE` 以下即被 `retrieve()` 的读侧过滤挡在注入池外。

        刚被取用的模式不在此列：006 的检索记账会刷新 `updated_at`（并 +10 温度），
        所以"持续被用"本身就是免于被扫掉的证据。
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=idle_days)
        stale = []
        for node in self.engine.iter_nodes(filters={"memory_type": "pattern"}, limit=limit):
            touched = node.updated_at
            if touched.tzinfo is None:
                touched = touched.replace(tzinfo=timezone.utc)
            if touched < cutoff:
                stale.append(node.id)
        for node_id in stale:
            self.engine.update_temperature(node_id, -decay_step)
        if stale:
            logger.info("结晶模式冷处理: %s 条闲置超 %s 天被降温", len(stale), idle_days)
        return {"decayed": len(stale)}

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
            # 工单 017：冷档以下的结晶模式不再进注入池。与 reap_stale_patterns 配对
            # ——一边衰减、一边看不见，才构成真实的淘汰路径
            filters={"memory_type": "pattern", "min_temperature": COLD_PATTERN_TEMPERATURE},
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
