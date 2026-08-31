"""睡眠设置持久化存储

固定目录 data/sleep_settings/{agent_id}.json。
不可信输入只有 agent_id —— 用白名单正则净化, 文件名由净化后的 id 派生,
路径不接收任何外部拼接输入（防目录穿越）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from neurova.core.logger import get_logger

logger = get_logger(__name__)

# agent_id 白名单: 字母/数字开头, 仅字母数字下划线连字符, 最长 64
_AGENT_ID_RE = r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}"


class SleepSettingsStore:
    """按 agent 持久化睡眠设置（JSON）"""

    def __init__(self, agent_id: str, base_dir: str = "data"):
        import re

        if not re.fullmatch(_AGENT_ID_RE, agent_id or ""):
            raise ValueError(f"Invalid agent_id for sleep settings: {agent_id!r}")
        self._dir = Path(base_dir) / "sleep_settings"
        self._file = self._dir / f"{agent_id}.json"

    def load(self) -> Dict[str, Any]:
        """读取设置; 文件不存在返回空 dict, 损坏文件由调用方兜底"""
        try:
            return json.loads(self._file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except Exception as e:
            logger.warning("读取睡眠设置失败: %s", e)
            return {}

    def save(self, settings: Dict[str, Any]) -> None:
        """写入设置（目录不存在则创建）"""
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            self._file.write_text(
                json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as e:
            logger.warning("写入睡眠设置失败: %s", e)
