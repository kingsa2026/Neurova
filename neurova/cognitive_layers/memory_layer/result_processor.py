"""
ResultProcessor — 结果处理器

功能:
1. 去重 (cosine > 0.95 视为重复)
2. 排序 (按 score 降序)
3. 取前 N 条
4. 冲突检测
5. 分层注入
"""

from neurova.core.logger import get_logger
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from neurova.cognitive_layers.memory_layer.conflict_detector_v2 import ConflictDetector, ConflictGroup

logger = get_logger(__name__)


@dataclass
class ProcessedResults:
    """处理后的结果"""

    independent: List[Dict[str, Any]] = field(default_factory=list)
    conflict_groups: List[ConflictGroup] = field(default_factory=list)
    evolution_chains: List[List[Dict]] = field(default_factory=list)
    injection_text: str = ""
    has_conflicts: bool = False


class ResultProcessor:
    """
    结果处理器 — 去重 + 冲突检测 + 分层注入

    处理流程:
      1. 去重 (cosine > 0.95 视为重复)
      2. 按 score 降序排序
      3. 取前 N 条 (不足 N 条全部保留)
      4. 冲突检测
      5. 构建注入内容
    """

    def __init__(
        self,
        max_results: int = 5,
        dedup_threshold: float = 0.95,
        sim_threshold: float = 0.8,
        entity_threshold: float = 0.5,
    ):
        """
        初始化结果处理器

        Args:
            max_results: 最大返回结果数
            dedup_threshold: 去重阈值
            sim_threshold: 冲突检测相似度阈值
            entity_threshold: 冲突检测实体重叠阈值
        """
        self.max_results = max_results
        self.dedup_threshold = dedup_threshold
        self.conflict_detector = ConflictDetector(
            sim_threshold=sim_threshold,
            entity_threshold=entity_threshold,
        )

    async def process(self, results: List[Dict[str, Any]]) -> ProcessedResults:
        """
        处理检索结果 — 轴突输出层的信号整合

        整合和传递最终结果，模拟轴突输出层的信号整合过程。

        神经隐喻:
        - 原始检索结果: 像来自树突的输入信号
        - 去重: 像神经元的侧向抑制，消除冗余激活
        - 排序: 像神经元的发放率排序，按重要性排列
        - 冲突检测: 像前额叶的认知控制，监控和解决冲突
        - 分层注入: 像神经递质的释放，将记忆注入到工作记忆

        Args:
            results: 原始检索结果（来自树突的输入信号）

        Returns:
            处理后的结果（轴突输出的整合信号）
        """
        if not results:
            return ProcessedResults()

        # Step 1: 去重
        unique = self._deduplicate(results)

        # Step 2: 排序
        unique.sort(key=lambda x: x.get("score", 0), reverse=True)

        # Step 3: 取前 N 条
        top_results = unique[: self.max_results]

        # Step 4: 冲突检测
        conflict_groups, independent, evolution_chains = self.conflict_detector.detect(top_results)

        # Step 5: 构建注入内容
        injection_text = self._build_injection_text(independent, conflict_groups, evolution_chains)

        return ProcessedResults(
            independent=independent,
            conflict_groups=conflict_groups,
            evolution_chains=evolution_chains,
            injection_text=injection_text,
            has_conflicts=len(conflict_groups) > 0,
        )

    def _deduplicate(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        去重

        使用简单的内容相似度判断:
        - 如果两条记忆的内容相似度 > threshold，视为重复
        - 保留 score 较高的那条
        """
        if not results:
            return []

        unique = []
        seen_contents = []

        for mem in results:
            content = mem.get("content", "").lower()
            if not content:
                unique.append(mem)
                continue

            # 检查是否与已有内容重复
            is_duplicate = False
            for seen in seen_contents:
                sim = self._compute_content_similarity(content, seen)
                if sim > self.dedup_threshold:
                    is_duplicate = True
                    break

            if not is_duplicate:
                unique.append(mem)
                seen_contents.append(content)

        return unique

    def _compute_content_similarity(self, content_a: str, content_b: str) -> float:
        """计算内容相似度"""
        if not content_a or not content_b:
            return 0.0

        words_a = set(content_a.split())
        words_b = set(content_b.split())

        if not words_a or not words_b:
            return 0.0

        intersection = words_a & words_b
        union = words_a | words_b

        return len(intersection) / len(union) if union else 0.0

    def _build_injection_text(
        self, independent: List[Dict], conflict_groups: List[ConflictGroup], evolution_chains: List[List[Dict]]
    ) -> str:
        """构建注入文本"""
        parts = []

        # 独立记忆
        for mem in independent:
            content = mem.get("content", "")
            mem.get("score", 0)
            parts.append(f"[记忆] {content}")

        # 演进链（注入最新版本）
        for chain in evolution_chains:
            if chain:
                latest = max(chain, key=lambda x: x.get("created_at", ""))
                content = latest.get("content", "")
                first = min(chain, key=lambda x: x.get("created_at", ""))
                first_date = first.get("created_at", "未知")
                latest_date = latest.get("created_at", "未知")
                parts.append(f"[记忆-已更新] {content} " f"(从 {first_date} 更新至 {latest_date})")

        # 冲突组
        if conflict_groups:
            conflict_text = self._build_conflict_prompt(conflict_groups)
            parts.append(conflict_text)

        return "\n\n".join(parts) if parts else ""

    def _build_conflict_prompt(self, conflict_groups: List[ConflictGroup]) -> str:
        """构建冲突提示"""
        prompts = []

        for group in conflict_groups:
            if len(group.options) < 2:
                continue

            option_a = group.options[0]
            option_b = group.options[1]

            prompt = f"""
系统提示: 检测到以下记忆存在冲突，请用户确认使用哪个版本：

冲突记忆组 #{group.group_id}:
┌─────────────────────────────────────────────────────────────────┐
│ [选项 A] 来源: {option_a.get('source', '未知')}  时间: {option_a.get('created_at', '未知')}
│ 内容: {option_a.get('content', '')[:200]}
├─────────────────────────────────────────────────────────────────┤
│ [选项 B] 来源: {option_b.get('source', '未知')}  时间: {option_b.get('created_at', '未知')}
│ 内容: {option_b.get('content', '')[:200]}
└─────────────────────────────────────────────────────────────────┘

请用户选择 A 或 B，或输入 C 提供新信息覆盖。
""".strip()
            prompts.append(prompt)

        return "\n\n".join(prompts)


class ConflictPresenter:
    """冲突呈现器"""

    def present_to_user(self, conflict_groups: List[ConflictGroup]) -> str:
        """生成冲突提示文本"""
        if not conflict_groups:
            return ""

        processor = ResultProcessor()
        return processor._build_conflict_prompt(conflict_groups)

    def handle_user_choice(
        self, group: ConflictGroup, choice: str, new_content: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        处理用户选择

        Args:
            group: 冲突组
            choice: 用户选择 ("A", "B", "C")
            new_content: 新内容（当选择 C 时）

        Returns:
            选中的记忆
        """
        choice = choice.upper()

        if choice == "A" and len(group.options) > 0:
            selected = group.options[0]
        elif choice == "B" and len(group.options) > 1:
            selected = group.options[1]
        elif choice == "C" and new_content:
            # 用户提供新信息
            selected = {
                "id": f"resolved_{group.group_id}",
                "content": new_content,
                "source": "user_resolution",
                "created_at": datetime.now().isoformat(),
                "metadata": {
                    "resolved_from": [m.get("id") for m in group.options],
                    "resolution_type": "user_override",
                },
            }
        else:
            raise ValueError(f"无效选择: {choice}")

        # 标记其他选项为"已解决"
        for opt in group.options:
            if opt.get("id") != selected.get("id"):
                opt["metadata"] = opt.get("metadata", {})
                opt["metadata"]["status"] = "superseded"
                opt["metadata"]["superseded_by"] = selected.get("id")

        return selected


class ConflictResolution:
    """冲突解决后的记忆更新"""

    async def resolve_and_update(
        self, group: ConflictGroup, user_choice: str, memory_manager: Any, new_content: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        用户选择后更新记忆库

        Args:
            group: 冲突组
            user_choice: 用户选择
            memory_manager: 记忆管理器
            new_content: 新内容

        Returns:
            选中的记忆
        """
        presenter = ConflictPresenter()
        selected = presenter.handle_user_choice(group, user_choice, new_content)

        # 标记被取代的记忆
        for option in group.options:
            if option.get("id") != selected.get("id"):
                try:
                    # 更新元数据
                    if hasattr(memory_manager, "update_memory"):
                        await memory_manager.update_memory(
                            option.get("id"),
                            metadata={
                                **option.get("metadata", {}),
                                "status": "superseded",
                                "superseded_by": selected.get("id"),
                                "superseded_at": datetime.now().isoformat(),
                            },
                        )
                except Exception as e:
                    logger.warning("更新记忆 %s 失败: %s", option.get('id'), e)

        # 如果用户提供新内容，写入新记忆
        if user_choice.upper() == "C" and new_content:
            try:
                if hasattr(memory_manager, "remember"):
                    memory_id = await memory_manager.remember(
                        content=new_content,
                        category="resolved_conflict",
                        metadata={
                            "resolved_from": [m.get("id") for m in group.options],
                            "resolution_type": "user_override",
                        },
                    )
                    selected["id"] = memory_id
            except Exception as e:
                logger.warning("写入新记忆失败: %s", e)

        return selected
