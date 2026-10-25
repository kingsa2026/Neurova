"""约束闸 — 进化产物必须全过的硬约束。

变体违反任一闸即被丢弃,绝不进入部署。

五类闸:
  1. size_limit      — 技能 ≤15KB / 工具描述 ≤500 字符 / 参数描述 ≤200 字符
  2. growth_limit    — 相对基线增长 ≤20%(防提示词膨胀退化注意力)
  3. non_empty       — 非空
  4. skill_structure — SKILL.md frontmatter 含 name + description
  5. semantic_similarity — 与基线语义不漂移(防跑题)

实现优先用 embedding
余弦相似度;embedding 不可用时退回 token Jaccard,保证离线可跑(不因
可选依赖缺失而失去这道闸)。
"""

from __future__ import annotations

from neurova.core import vector_math
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


#: 取引擎这一步"没拿到可用引擎"的唯一哨兵值。它与"相似度算出差值"必须分开：
#: 前者要回退到词面下界，后者要如实返回——两者都折进 `None` 时，`None` 就同时
#: 表达"没有向量"和"向量算出了空"，调用方无从分辨。
_ENGINE_UNAVAILABLE = object()


def _noteEngineProbe(state: str) -> None:
    """把"这一跳走到了哪一步"落进模块级读面（`probed` / `ready`）。

    为什么要有这一格：判据要能分辨三件事——**根本没取引擎**（语义面被摘掉）、
    **取了但没就绪就回退**（正常路径）、**取了且就绪**（用了向量）。只看返回值
    分不出前两者（都回退到词面下界），于是把语义闸整段删掉也能"绿得很干净"。
    """
    global _SEMANTIC_ENGINE_TOUCHED
    _SEMANTIC_ENGINE_TOUCHED = str(state)


#: 取引擎这一跳的读数（空串 = 本轮进程里这一跳一次都没走到）。
_SEMANTIC_ENGINE_TOUCHED = ""


def _initialized_embedding_engine():
    """取**已初始化**的 embedding 引擎；取不到回 `_ENGINE_UNAVAILABLE`。

    ⚠ 这里只许读 `is_initialized`、**不许**调 `initialize_sync()`：工厂
    `get_embedding_engine()` 在引擎缺席时会懒建一个 `ONNXEmbeddingEngine`，而它的
    `initialize_sync()` 走 `ModelDownloader.ensure_model(..., auto_download=True)`——
    也就是**在一条判据的路径上出网拉 130MB 权重**。`requirements-ci` 刻意不带
    torch/onnxruntime/模型权重，于是这一跳在 CI 上要么超时、要么把跑测挂到整场
    被平台掐断；开关也仍在，CI 一联网就会真下大件。懒加载策略要求"进化闸不触发
    模型加载"，所以这里只认**已经就绪**的引擎，其余一律回退。
    """
    try:
        from neurova.embedding import get_embedding_engine

        engine = get_embedding_engine()
        if engine is None or not engine.is_initialized:
            return _ENGINE_UNAVAILABLE
        return engine
    except Exception:  # noqa: BLE001 - 引擎装配失败属可选依赖缺席,回退词面
        return _ENGINE_UNAVAILABLE
    finally:
        # 每一次判据都会走这一跳，必须让"这一跳走到了、且没去建模型"可被**读**出来：
        # 只写在注释里的纪律，下一次有人把 `initialize_sync()` 加回来时没有任何东西会红
        # （判据 `tests/unit/evolution/eval/test_semanticGateLoadsNoModel.py` 读这一格）。
        if _SEMANTIC_ENGINE_TOUCHED != "ready":
            _noteEngineProbe("probed")


def _embedding_similarity(a: str, b: str) -> Optional[float]:
    """尝试用项目 embedding 引擎算余弦;任何**不可用**原因都返回 None(不抛)。

    只消费**已初始化**的引擎(启动期 ONNX 懒加载策略,见 09-09 启动性能
    修复):进化闸不触发模型加载,未就绪即 Jaccard 回退——离线可跑。
    """
    try:
        engine = _initialized_embedding_engine()
        if engine is _ENGINE_UNAVAILABLE:
            return None
        # 取向量一律走 `encodeOrNone`：全零向量是"引擎兜底"不是"有向量"（并发会话那笔
        # `encodeOrNone` 的口径更彻底，按其收口）。这一跳只在**已就绪**的引擎上发生。
        _noteEngineProbe("ready")
        va, vb = engine.encodeOrNone(a), engine.encodeOrNone(b)
        if va is None or vb is None:
            return None
        raw = vector_math.tryCosineSimilarity(va, vb)
        if raw is None:
            return None
        return max(0.0, min(1.0, raw))
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
    jieba = _jiebaModule()
    if cjk_runs and jieba is not None:
        for run in cjk_runs:
            tokens.update(w for w in jieba.cut(run) if len(w) >= 2)
    elif cjk_runs:
        for run in cjk_runs:
            if len(run) == 1:
                tokens.add(run)
            else:
                tokens.update(run[i : i + 2] for i in range(len(run) - 1))
    return tokens


def _jiebaModule():
    """取 jieba：走 `knowledge.search` 那一个入口，不在这里裸 import。

    裸 `import jieba` 只是把模块名拿到手，前缀字典仍是**首次 cut 时**才建（实测 0.5–0.8s，
    CI 并行场里被 GIL 争抢放大到 8s+）——那笔账会落在"哪条无关键恰好第一个调到这里"身上，
    上层完全看不出来。`knowledge.search._get_jieba()` 已在取用时把字典建完并把缺失记成
    不可用，本模块复用它（教义第 6 条：同一件东西只有一处取用口）。
    """
    try:
        from neurova.knowledge.search import _get_jieba

        return _get_jieba()
    except Exception:  # noqa: BLE001 - 取用口本身不可达时用二元组保持粒度
        return None


def _token_jaccard(a: str, b: str) -> float:
    ta, tb = _tokenize(a), _tokenize(b)
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)
