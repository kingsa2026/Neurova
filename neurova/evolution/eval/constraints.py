"""约束闸 — 进化产物必须全过的硬约束。

对位 Hermes `hermes-agent-self-evolution/evolution/core/constraints.py`:
变体违反任一闸即被丢弃,绝不进入部署。

五类闸:
  1. size_limit      — 技能 ≤15KB / 工具描述 ≤500 字符 / 参数描述 ≤200 字符
  2. growth_limit    — 相对基线增长 ≤20%(防提示词膨胀退化注意力)
  3. non_empty       — 非空
  4. skill_structure — SKILL.md frontmatter 含 name + description
  5. semantic_similarity — 与基线语义不漂移(防跑题)

语义保持是 Hermes 有而 Neurova 原先完全缺的一环。实现优先用 embedding
余弦相似度;embedding 不可用时退回 token Jaccard,保证离线可跑(不因
可选依赖缺失而失去这道闸)。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from neurova.core.logger import get_logger
from neurova.evolution.eval.config import EvolutionConfig

logger = get_logger(__name__)


@dataclass
class ConstraintResult:
    """单条约束的校验结果。"""

    passed: bool
    name: str
    message: str
    details: str = ""


class ConstraintValidator:
    """校验进化产物是否满足全部硬约束。"""

    def __init__(self, config: EvolutionConfig):
        self.config = config

    # ── 入口 ──

    def validate(
        self,
        artifact_text: str,
        artifact_type: str,
        baseline_text: Optional[str] = None,
    ) -> list[ConstraintResult]:
        results = [
            self._check_non_empty(artifact_text),
            self._check_size(artifact_text, artifact_type),
        ]
        if baseline_text is not None:
            results.append(self._check_growth(artifact_text, baseline_text))
            results.append(self._check_semantic(artifact_text, baseline_text))
        if artifact_type == "skill":
            results.append(self._check_skill_structure(artifact_text))
        return results

    def all_pass(self, results: list[ConstraintResult]) -> bool:
        return all(r.passed for r in results)

    # ── 各闸 ──

    def _size_limit_for(self, artifact_type: str) -> int:
        if artifact_type == "tool_description":
            return self.config.max_tool_desc_size
        if artifact_type == "param_description":
            return self.config.max_param_desc_size
        return self.config.max_skill_size

    def _check_size(self, text: str, artifact_type: str) -> ConstraintResult:
        limit = self._size_limit_for(artifact_type)
        size = len(text)
        if size <= limit:
            return ConstraintResult(True, "size_limit", f"尺寸合规: {size}/{limit}")
        return ConstraintResult(
            False, "size_limit", f"尺寸超限: {size}/{limit}(超出 {size - limit} 字符)"
        )

    def _check_growth(self, text: str, baseline: str) -> ConstraintResult:
        base_len = len(baseline)
        if base_len == 0:
            return ConstraintResult(True, "growth_limit", "基线为空,跳过增长校验")
        growth = (len(text) - base_len) / base_len
        if growth <= self.config.max_prompt_growth:
            return ConstraintResult(True, "growth_limit", f"增长合规: {growth:+.1%}")
        return ConstraintResult(
            False,
            "growth_limit",
            f"增长超限: {growth:+.1%}(上限 {self.config.max_prompt_growth:+.1%})",
        )

    def _check_non_empty(self, text: str) -> ConstraintResult:
        if text and text.strip():
            return ConstraintResult(True, "non_empty", "非空")
        return ConstraintResult(False, "non_empty", "产物为空")

    def _check_skill_structure(self, text: str) -> ConstraintResult:
        head = text.lstrip()
        has_frontmatter = head.startswith("---")
        head_window = text[:500]
        has_name = "name:" in head_window
        has_description = "description:" in head_window
        if has_frontmatter and has_name and has_description:
            return ConstraintResult(True, "skill_structure", "frontmatter 合规(name + description)")
        missing = []
        if not has_frontmatter:
            missing.append("frontmatter(---)")
        if not has_name:
            missing.append("name")
        if not has_description:
            missing.append("description")
        return ConstraintResult(False, "skill_structure", f"frontmatter 缺失: {', '.join(missing)}")

    def _check_semantic(self, text: str, baseline: str) -> ConstraintResult:
        sim = semantic_similarity(text, baseline)
        passed = sim >= self.config.semantic_similarity_threshold
        return ConstraintResult(
            passed,
            "semantic_similarity",
            f"语义相似度 {sim:.3f}(阈值 {self.config.semantic_similarity_threshold:.2f})",
            details=_SEMANTIC_BACKEND,
        )


# ── 语义相似度 ──

_SEMANTIC_BACKEND = "token_jaccard"  # 被 _check_semantic 更新,便于观测实际后端


def semantic_similarity(a: str, b: str) -> float:
    """语义相似度:优先 embedding 余弦,不可用时退回 token Jaccard。

    返回 [0,1]。Jaccard 是词面下界——同义改写也能拿到较高分,主题漂移
    (如"搜论文"→"发邮件")会显著掉分,足以作漂移闸。
    """
    global _SEMANTIC_BACKEND
    emb = _embedding_similarity(a, b)
    if emb is not None:
        _SEMANTIC_BACKEND = "embedding_cosine"
        return emb
    _SEMANTIC_BACKEND = "token_jaccard"
    return _token_jaccard(a, b)


def _embedding_similarity(a: str, b: str) -> Optional[float]:
    """尝试用项目 embedding 引擎算余弦;任何不可用原因都返回 None(不抛)。

    只消费**已初始化**的引擎(启动期 ONNX 懒加载策略,见 09-09 启动性能
    修复):进化闸不触发模型加载,未就绪即 Jaccard 回退——离线可跑。
    """
    try:
        from neurova.embedding import get_embedding_engine

        engine = get_embedding_engine()
        if engine is None or not engine.is_initialized():
            return None
        va, vb = engine.encode(a), engine.encode(b)
        if not va or not vb:
            return None
        import math

        dot = sum(x * y for x, y in zip(va, vb))
        na = math.sqrt(sum(x * x for x in va))
        nb = math.sqrt(sum(y * y for y in vb))
        if na == 0 or nb == 0:
            return None
        return max(0.0, min(1.0, dot / (na * nb)))
    except Exception:  # noqa: BLE001 - 可选依赖,缺失时退回 Jaccard
        return None


def _tokenize(text: str) -> set[str]:
    """词面 token 集:拉丁词 + 中文 jieba 分词(jieba 不可用时 CJK 字符二元组)。

    Jaccard 是词面下界——中文整段成单 token 会让改写/漂移都算不出差异,
    必须按词切分(项目 RAG 已依赖 jieba,此处同源)。
    """
    tokens: set[str] = set()
    latin_runs = re.findall(r"[a-z0-9]+", text.lower())
    tokens.update(r for r in latin_runs if len(r) >= 2)
    cjk_runs = re.findall(r"[\u4e00-\u9fff]+", text)
    if cjk_runs:
        try:
            import jieba

            for run in cjk_runs:
                tokens.update(w for w in jieba.cut(run) if len(w) >= 2)
        except Exception:  # noqa: BLE001 - jieba 缺席时用二元组保持粒度
            for run in cjk_runs:
                if len(run) == 1:
                    tokens.add(run)
                else:
                    tokens.update(run[i : i + 2] for i in range(len(run) - 1))
    return tokens


def _token_jaccard(a: str, b: str) -> float:
    ta, tb = _tokenize(a), _tokenize(b)
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)
