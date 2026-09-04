"""治理设置持久层（治理遗留收口 2026-09-05）

Step9.96 对话规则提取的 LLM 成本门控此前只有 env 开关（NEUROVA_CONVERSATION_RULES），
生产无管理面；RSI 部署阶段同样只能靠 env。本模块提供独立于 /v1/settings 扁平 kv 的
治理设置：JSON 文件持久化 + 管理端读写（require_admin 在端点层）。

优先级约定：env 显式设 0 强制关 > 治理设置值 > env 默认 > 内置默认。
"""

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

_LOCK = threading.Lock()

DEFAULTS: Dict[str, Any] = {
    "conversation_rules_enabled": False,  # Step9.96 LLM 成本门控，默认关
    "rsi_phase": 0,  # RSI 部署阶段 0..4（0=观察）
}


def settings_path() -> Path:
    """治理设置文件路径（NEUROVA_GOVERNANCE_SETTINGS 可覆盖）"""
    custom = os.environ.get("NEUROVA_GOVERNANCE_SETTINGS")
    if custom:
        return Path(custom)
    return Path("data") / "governance_settings.json"


def load_governance_settings(path: Optional[Path] = None) -> Dict[str, Any]:
    """加载治理设置（文件不存在/损坏 → 内置默认）"""
    p = Path(path) if path else settings_path()
    merged = dict(DEFAULTS)
    try:
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for key in DEFAULTS:
                    if key in data:
                        merged[key] = data[key]
    except Exception as e:  # noqa: BLE001 - 读取失败回退默认，不阻断
        logger.warning("治理设置加载失败，使用默认: %s", e)
    return merged


def save_governance_settings(data: Dict[str, Any], path: Optional[Path] = None) -> bool:
    """保存治理设置（merge 进现有值后落盘）"""
    p = Path(path) if path else settings_path()
    with _LOCK:
        try:
            current = load_governance_settings(p)
            for key in DEFAULTS:
                if key in data:
                    current[key] = data[key]
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(
                json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            logger.info("治理设置已保存: %s", p)
            return True
        except Exception as e:  # noqa: BLE001
            logger.error("治理设置保存失败: %s", e)
            return False
