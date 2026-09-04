"""统一模型契约 — 参数与能力上下文（schema 驱动）。

Dify §2.5「参数与能力上下文全部来自 provider/model YAML schema，能力
过滤由 schema 驱动」的 Neurova 落地。数据不另起炉灶——三层既有目录
（capability_detector.MODEL_PRESETS 预埋 > model_limits 精确表 >
名称启发式）是单一事实源，本模块只做 schema 视图组装。

能力口径对齐（Dify 六型模型 ↔ Neurova 能力词表）：
MODEL_TYPE_CAPABILITIES 是双向映射源（model_types_for_capabilities 反查）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

# ── Dify 六型模型 ↔ Neurova 能力词表（口径对齐，双向映射源） ──
# 约定：一个能力词表组合唯一确定一组模型类型；text 恒归属 llm。
MODEL_TYPE_CAPABILITIES: Dict[str, frozenset] = {
    "llm": frozenset({"text"}),
    "text_embedding": frozenset({"embedding"}),
    "rerank": frozenset({"rerank"}),
    "speech2text": frozenset({"stt"}),
    "text2speech": frozenset({"tts"}),
    "moderation": frozenset({"moderation"}),
}

_CAP_TO_TYPES: Dict[str, List[str]] = {}
for _mt, _caps in MODEL_TYPE_CAPABILITIES.items():
    for _c in _caps:
        _CAP_TO_TYPES.setdefault(_c, []).append(_mt)

# 附加映射：Neurova 既有能力词 → 模型类型（vision 等属 llm 的增强面）
_EXTRA_CAP_TYPES: Dict[str, str] = {
    "vision": "llm",
    "reasoning": "llm",
    "video": "llm",
    "audio": "llm",
    "tool_use": "llm",
    "image_generation": "llm",
    "video_generation": "llm",
}


def model_types_for_capabilities(capabilities: List[str]) -> List[str]:
    """能力词表 → 模型类型列表（Dify 口径；按 MODEL_TYPE_CAPABILITIES 规范序）"""
    caps = set(capabilities or [])
    types: List[str] = []
    for mt in MODEL_TYPE_CAPABILITIES:  # 规范序：llm 在前，与 Dify 枚举一致
        if caps & MODEL_TYPE_CAPABILITIES[mt]:
            types.append(mt)
    for cap in caps:  # 附加面：vision/reasoning 等归 llm 增强
        extra = _EXTRA_CAP_TYPES.get(cap)
        if extra and extra not in types:
            types.append(extra)
    return types


# ── 参数规则（Dify parameter_rules 同构） ──────────────────────


@dataclass
class ParameterRule:
    """单参数规则：类型/区间/默认值/是否必填（schema 驱动能力过滤的单元）"""

    name: str
    type: str = "float"  # int / float / bool / string / text
    required: bool = False
    min: Optional[float] = None
    max: Optional[float] = None
    default: Any = None
    help: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"name": self.name, "type": self.type, "required": self.required}
        if self.min is not None:
            d["min"] = self.min
        if self.max is not None:
            d["max"] = self.max
        if self.default is not None:
            d["default"] = self.default
        if self.help:
            d["help"] = self.help
        return d


def _base_parameter_rules(max_tokens: Optional[int]) -> List[ParameterRule]:
    """OpenAI 兼容基础参数面（所有 LLM 通用）"""
    return [
        ParameterRule(name="temperature", type="float", min=0.0, max=2.0, default=0.7,
                      help="采样温度；推理模型（o1 族等）建议保持默认"),
        ParameterRule(name="top_p", type="float", min=0.0, max=1.0, default=0.9),
        ParameterRule(name="max_tokens", type="int", min=1, max=max_tokens, default=max_tokens),
    ]


def _is_reasoning_family(model_id: str) -> bool:
    """推理模型族判定（o1/o3/o4/gpt-oss/deepseek-r 等）：temperature 受限非必填"""
    m = (model_id or "").lower()
    return bool(re.match(r"^(o[134](-|$)|gpt-oss|deepseek-r|glm-4\.[56]|qwen.*-thinking)", m)) or "-thinking" in m


# ── 模型 schema（能力 + 限额 + 参数规则视图） ──────────────────


@dataclass
class ModelSchema:
    """模型 schema：能力过滤与参数裁剪的驱动源"""

    model_id: str = ""
    capabilities: List[str] = field(default_factory=list)
    context_window: Optional[int] = None
    max_tokens: Optional[int] = None
    parameter_rules: List[ParameterRule] = field(default_factory=list)

    def supports(self, capability: str) -> bool:
        return capability in self.capabilities

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_id": self.model_id,
            "capabilities": list(self.capabilities),
            "context_window": self.context_window,
            "max_tokens": self.max_tokens,
            "parameter_rules": [r.to_dict() for r in self.parameter_rules],
        }


def get_model_schema(model_id: str, existing_capabilities: Optional[List[str]] = None) -> ModelSchema:
    """组装模型 schema（三层既有目录为事实源，不引入新存储）。

    能力：detect_model_capabilities（显式元数据 > MODEL_PRESETS 目录 >
    名称启发式，永不为空）。
    限额：model_limits 精确表/前缀匹配 > MODEL_PRESETS 兜底（未知不杜撰）。
    参数：OpenAI 兼容基础面；推理族 temperature 标记非必填。
    """
    from neurova.llm.capability_detector import detect_model_capabilities, lookup_model_preset
    from neurova.llm.model_limits import get_model_context_window, get_model_max_tokens

    capabilities = detect_model_capabilities(model_id, existing=existing_capabilities)

    preset = lookup_model_preset(model_id)
    context_window = get_model_context_window(model_id)
    if context_window is None and preset is not None:
        context_window = preset.context_window

    max_tokens: Optional[int]
    try:
        max_tokens = get_model_max_tokens(model_id)
    except Exception:  # noqa: BLE001 — 未知模型可能抛错而非返 None
        max_tokens = None
    if not max_tokens and preset is not None:
        max_tokens = preset.max_tokens

    rules = _base_parameter_rules(max_tokens)
    if _is_reasoning_family(model_id):
        for r in rules:
            if r.name == "temperature":
                r.required = False

    return ModelSchema(
        model_id=model_id,
        capabilities=capabilities,
        context_window=context_window,
        max_tokens=max_tokens,
        parameter_rules=rules,
    )


__all__ = [
    "MODEL_TYPE_CAPABILITIES",
    "model_types_for_capabilities",
    "ParameterRule",
    "ModelSchema",
    "get_model_schema",
]
