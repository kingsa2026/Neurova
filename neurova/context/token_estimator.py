"""统一 Token 估算器 —— 全仓 token 计量的唯一事实源。

判据侧（折叠/microcompact/抽屉额度/窗口预算）与展示侧（组成面板）**必须**共用
同一把尺子：估算偏低会让"该压缩时不压缩"，估算偏高会过度折叠。两条都改变
发给模型的内容，所以不允许存在第二份实现（含 `len//4`、`len*1.5` 这类就地近似）。

两档策略：

- ``EXACT``（默认）：tiktoken ``o200k_base`` 精确计数。判据与展示统一走它。
- ``BALANCED``：**无 tokenizer 时的回退**。按字符类别取实测上确界比例，
  保证"宁可高估不可低估"——tokenizer 装不上的环境也不许漏掉折叠。

回退比例由 o200k 实测标定，回归见
``tests/unit/context/test_token_estimator_calibration.py``。
"""

import math
import re
from enum import Enum
from typing import Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)


class EstimationStrategy(Enum):
    """估算策略。"""

    EXACT = "exact"  # tiktoken o200k 精确计数（判据与展示的统一口径）
    BALANCED = "balanced"  # 无 tokenizer 时的回退（按类别上界，宁可高估）


# 回退档各字符类别的 token 上确界（o200k 实测标定）。
# 取值原则：不得低于实测上界，否则无 tokenizer 环境会漏掉折叠。
#   cjk   实测上界 1.575（生僻 CJK 序列）→ 取 2.0
#   alnum 实测上界 1.000（十六进制串）  → 取 1.0
#   punct 实测上界 0.583（标点密集）    → 取 0.6
#   space 实测上界 0.063（纯空白）      → 取 0.1
#   wide  实测上界 3.000（盲文/数学符号）→ 取 3.0
_FALLBACK_RATES = {"cjk": 2.0, "alnum": 1.0, "punct": 0.6, "space": 0.1, "wide": 3.0}

# CJK 及全角区段：中日韩统一表意、扩展 A、假名、谚文、CJK 标点、全角半角形。
_CJK_CHAR = re.compile(
    r"[\u3000-\u303f\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uf900-\ufaff\uff00-\uffef]"
)


def _fallback_rate(ch: str) -> float:
    """单个字符在回退档下的 token 计入值。"""
    if _CJK_CHAR.match(ch):
        return _FALLBACK_RATES["cjk"]
    if ch.isspace():
        return _FALLBACK_RATES["space"]
    if ord(ch) < 128:
        return _FALLBACK_RATES["alnum"] if ch.isalnum() else _FALLBACK_RATES["punct"]
    return _FALLBACK_RATES["wide"]


class TokenEstimator:
    """统一的 Token 估算器。"""

    def __init__(self, strategy: EstimationStrategy = EstimationStrategy.EXACT):
        self.strategy = strategy
        self._tiktoken_encoder = None
        self._tiktoken_failed = False
        self._degraded_logged = False

    def _get_tiktoken_encoder(self):
        """懒加载 tiktoken o200k 编码器；不可用时标记并回退比例估算。"""
        if self._tiktoken_failed:
            return None
        if self._tiktoken_encoder is None:
            try:
                import tiktoken

                self._tiktoken_encoder = tiktoken.get_encoding("o200k_base")
            except Exception as e:  # noqa: BLE001 - 缺 tokenizer 是可用性降级，不是错误
                self._tiktoken_failed = True
                self._tiktoken_encoder = None
                logger.warning(
                    "tiktoken o200k 不可用（%s），token 估算降级为 BALANCED 比例上界口径"
                    "——判定只会偏保守，不会漏掉压缩",
                    e,
                )
        return self._tiktoken_encoder

    def estimate(self, text: str) -> int:
        """估算文本的 token 数量。"""
        if not text:
            return 0

        if self.strategy == EstimationStrategy.EXACT:
            encoder = self._get_tiktoken_encoder()
            if encoder is not None:
                try:
                    return len(encoder.encode(text))
                except Exception as e:  # noqa: BLE001 - 单条编码失败同样降级，不抛
                    if not self._degraded_logged:
                        self._degraded_logged = True
                        logger.warning("单条编码失败（%s），本条降级为比例上界口径", e)
        return self._estimate_by_rate(text)

    @staticmethod
    def _estimate_by_rate(text: str) -> int:
        """回退档：逐字符累加类别上界比例。"""
        total = 0.0
        for ch in text:
            total += _fallback_rate(ch)
        return int(round(total))

    def estimate_batch(self, texts: List[str]) -> List[int]:
        """批量估算 token 数量。"""
        return [self.estimate(text) for text in texts]


# 按策略缓存估算器实例（判据侧与展示侧会交替请求不同档，缓存必须按档分槽，
# 否则每次跨档调用都重建对象）。
_ESTIMATORS: Dict[EstimationStrategy, TokenEstimator] = {}


def get_token_estimator(strategy: EstimationStrategy = EstimationStrategy.EXACT) -> TokenEstimator:
    """获取指定策略的估算器实例（按策略缓存）。"""
    estimator = _ESTIMATORS.get(strategy)
    if estimator is None:
        estimator = TokenEstimator(strategy)
        _ESTIMATORS[strategy] = estimator
    return estimator


def estimate_tokens(text: str, strategy: EstimationStrategy = EstimationStrategy.EXACT,
                    model_id: Optional[str] = None) -> int:
    """估算文本的 token 数量（全仓统一入口）。

    `model_id` 提供时应用该模型的**溢出保证金**系数（向上取整——宁可高估
    不可低估；见 `recordModelOverflow`）。不传则与既有调用完全一致。
    """
    base = get_token_estimator(strategy).estimate(text)
    if not model_id:
        return base
    margin = getModelSafetyMargin(model_id)
    return int(math.ceil(base * margin))


#: 溢出保证金参数（QwenPaw 对照批 B4）：单次溢出的抬高档、封顶与下界。
MARGIN_STEP = 1.25
MARGIN_CAP = 2.0
MARGIN_FLOOR = 1.0
_MARGIN_CAPABILITY = "token_safety_margin"


def recordModelOverflow(model_id: str) -> float:
    """provider 溢出拒收后抬高该模型的估算基线（QwenPaw"拒收保证金"的对偶实现）。

    保证金存模型能力缓存单例（进程级记忆）；步进 ×1.25、封顶 ×2.0——封顶防
    "一次坏估算把可用窗口砍半"。返回抬高后的系数。
    """
    from neurova.llm.model_capability_cache import get_capability_cache

    key = str(model_id or "").strip()
    if not key:
        return MARGIN_FLOOR
    cache = get_capability_cache()
    try:
        current = float(cache.get(key, _MARGIN_CAPABILITY, MARGIN_FLOOR) or MARGIN_FLOOR)
    except (TypeError, ValueError):
        current = MARGIN_FLOOR
    raised = min(MARGIN_CAP, current * MARGIN_STEP)
    cache.learn(key, _MARGIN_CAPABILITY, raised)
    return raised


def getModelSafetyMargin(model_id: str) -> float:
    """读某模型的溢出保证金系数（无记录/非法值一律回落下界 1.0）。"""
    from neurova.llm.model_capability_cache import get_capability_cache

    key = str(model_id or "").strip()
    if not key:
        return MARGIN_FLOOR
    try:
        value = float(get_capability_cache().get(key, _MARGIN_CAPABILITY, MARGIN_FLOOR)
                      or MARGIN_FLOOR)
    except (TypeError, ValueError):
        return MARGIN_FLOOR
    if value < MARGIN_FLOOR:
        return MARGIN_FLOOR
    return min(value, MARGIN_CAP)


def resetModelSafetyMargins() -> None:
    """测试隔离用：清空保证金记忆（连能力缓存一起重置）。"""
    from neurova.llm.model_capability_cache import get_capability_cache

    get_capability_cache().clear()


def isRulerCalibrated() -> bool:
    """尺子是否处于**校准档**（判定类动作允许生效的唯一前置）。

    校准档 = `EXACT` 且 `o200k` 编码器真的可用。缺 tokenizer 时估算会走
    按类上界比例的回退档——那个档只保证"不低估"，不保证判据所需的分辨率，
    拿它算盈亏就是**在坏尺上建闸**（方向确定地偏向"不压"）。

    探针只在本处实现一处：谁要判断"尺子准不准"一律调它，不得自己再写一遍
    `import tiktoken` 或可用性判断（那是第二份事实源）。
    """
    return get_token_estimator(EstimationStrategy.EXACT)._get_tiktoken_encoder() is not None
