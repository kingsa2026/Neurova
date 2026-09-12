"""应用设置持久化（CUA 真机问题修复：最大输出 token 的全局默认）

背景：/v1/settings 此前是内存 stub（TODO 从数据库加载）——高级选项卡
保存即丢、读取形状错位，max_tokens 于 09-10 被当"零消费死参数"移除；
实际 openai_loop 每次请求都消费 agent.llm_client.config.max_tokens。

本模块是设置 API 的真实存储层（governance_settings 同款 JSON 模式）：
- data/app_settings.json 持久化，按 section 合并
- advanced.max_output_tokens = 全局默认输出预算：agent 的 llm_config
  未显式设置 max_tokens（== LLMConfig 数据类默认 131072）时应用；
  显式配置永不覆盖（增量式：只补默认，不改显式）
"""

import json
from pathlib import Path
from typing import Any, Dict, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

# LLMConfig 数据类默认值（neurova/llm_client.py LLMConfig.max_tokens）——
# 该值即"未显式设置"的哨兵
LLM_DEFAULT_MAX_TOKENS = 131072

GENERAL_DEFAULTS: Dict[str, Any] = {"app_name": "Neurova", "language": "zh-CN"}
ADVANCED_DEFAULTS: Dict[str, Any] = {
    "debug_mode": False,
    "log_level": "info",
    "telemetry": False,
    "max_output_tokens": LLM_DEFAULT_MAX_TOKENS,
}
SECTION_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "general": GENERAL_DEFAULTS,
    "advanced": ADVANCED_DEFAULTS,
}


def _settings_path(path: Optional[Path] = None) -> Path:
    return path or (Path("data") / "app_settings.json")


def load_app_settings(path: Optional[Path] = None) -> Dict[str, Any]:
    """加载应用设置（文件值合并到默认结构上；损坏文件回退默认并告警）"""
    p = _settings_path(path)
    stored: Dict[str, Any] = {}
    if p.exists():
        try:
            stored = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("应用设置文件损坏，回退默认: %s", e)
            stored = {}
    merged: Dict[str, Any] = {}
    for section, defaults in SECTION_DEFAULTS.items():
        merged[section] = {**defaults, **(stored.get(section) or {})}
    # 未定义默认结构的 section（security/storage 等）原样透传
    for key, value in stored.items():
        if key not in merged:
            merged[key] = value
    return merged


def save_app_settings(
    section: str, data: Dict[str, Any], path: Optional[Path] = None
) -> Dict[str, Any]:
    """按 section 合并保存（原子写），返回保存后的完整设置"""
    p = _settings_path(path)
    current: Dict[str, Any] = {}
    if p.exists():
        try:
            current = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            current = {}
    section_data = current.get(section) or {}
    if isinstance(data, dict):
        section_data.update(data)
    current[section] = section_data
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    return load_app_settings(path)


def get_advanced_settings(path: Optional[Path] = None) -> Dict[str, Any]:
    return load_app_settings(path).get("advanced") or dict(ADVANCED_DEFAULTS)


def apply_global_output_budget(llm_config: Any, path: Optional[Path] = None) -> bool:
    """把全局默认输出预算应用到 agent 的 llm_config。

    应用条件（二者其一）：
    - max_tokens == LLMConfig 数据类默认（未显式设置的哨兵值）
    - 此前由本函数应用过（_global_output_budget_applied 标记——全局预算
      二次修改时能跟进新值）
    用户/agent 显式配置（其余任何值）永不覆盖。应用成功返回 True。
    """
    if llm_config is None:
        return False
    try:
        current = int(getattr(llm_config, "max_tokens", 0) or 0)
    except (TypeError, ValueError):
        return False
    applied_before = bool(getattr(llm_config, "_global_output_budget_applied", False))
    if current != LLM_DEFAULT_MAX_TOKENS and not applied_before:
        return False
    gmax = get_advanced_settings(path).get("max_output_tokens")
    try:
        gmax_int = int(gmax)
    except (TypeError, ValueError):
        return False
    if gmax_int <= 0 or gmax_int == LLM_DEFAULT_MAX_TOKENS:
        return False
    llm_config.max_tokens = gmax_int
    llm_config._global_output_budget_applied = True
    logger.info("应用全局默认输出预算: max_tokens=%d", gmax_int)
    return True
