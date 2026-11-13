"""per-agent 执行档位存储（R6，2026-11-13）。

HarnessPro 对照 §10.2 R6：档位此前只有部署级 env（全体 agent 一档）；
本模块给**单个 agent** 一格档位覆盖（lite/standard/heavy），管理员经
governance 面派发。单文件 JSON 持久化（agent_limits_settings 同模式：
原子写 + env 路径覆盖），合法域 = `agent_limits_settings.EXEC_PROFILES`
键集——未设/非法一律空串（回落部署档位），不兜假值。

消费点：`chat_pipeline._resolve_task_profile` 在轮次开始时把
「agent 存储档位」写进 turn 级 ContextVar（见 `agent/turn_profile.py`），
门控/分段提醒/溢出阈值同轮生效。
"""

import json
import os
import threading
from pathlib import Path
from typing import Dict, Optional

from neurova.core.logger import get_logger
from neurova.core.data_root import resolveDataPath

logger = get_logger(__name__)

_LOCK = threading.Lock()


def store_path() -> Path:
    custom = os.environ.get("NEUROVA_AGENT_PROFILES_SETTINGS")
    if custom:
        return Path(custom)
    return resolveDataPath("agent_exec_profiles.json")


def _validProfiles() -> set:
    try:
        from neurova.security.agent_limits_settings import EXEC_PROFILES

        return set(EXEC_PROFILES.keys())
    except Exception:  # noqa: BLE001 - 配置面故障退回三档字面域
        return {"lite", "standard", "heavy"}


def _load(path: Path) -> Dict[str, str]:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                valid = _validProfiles()
                return {str(k): str(v) for k, v in data.items()
                        if str(v) in valid}
    except Exception as e:  # noqa: BLE001 - 损坏文件回落空表
        logger.warning("加载 per-agent 档位失败，使用空表: %s", e)
    return {}


def all_agent_profiles(path: Optional[Path] = None) -> Dict[str, str]:
    return _load(Path(path) if path else store_path())


def get_agent_profile(agent_id: str, path: Optional[Path] = None) -> str:
    """该 agent 的存储档位；未设/非法 ⇒ 空串（回落部署档位）。"""
    if not str(agent_id or "").strip():
        return ""
    return all_agent_profiles(path).get(str(agent_id).strip(), "")


def set_agent_profile(agent_id: str, profile: str, path: Optional[Path] = None) -> bool:
    """设置/清除（profile 传 "standard" 也算显式设置）某 agent 的档位。

    非法档位拒收（False）——不静默改成 standard；agent_id 必须非空。
    """
    agent_key = str(agent_id or "").strip()
    profile_key = str(profile or "").strip().lower()
    if not agent_key or profile_key not in _validProfiles():
        return False
    p = Path(path) if path else store_path()
    with _LOCK:
        try:
            current = _load(p)
            current[agent_key] = profile_key
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(current, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            os.replace(tmp, p)
            return True
        except Exception as e:  # noqa: BLE001
            logger.error("保存 per-agent 档位失败: %s", e)
            return False
