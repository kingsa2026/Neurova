"""进化系统设置 — 管理员可持久化(admin 写 / 登录读),env 保留开发态覆盖。

对位项目既有范式:governance_settings 的 JSON 持久化 + 高级选项卡(经验结晶
闭环审计 2026-09-05)。文本进化开关必须能在 UI 上开合,env 变量仅作为
开发/测试的即时覆盖(env 显式设置时**赢过**文件,未设置时以文件为准)。

落盘位置: config/evolution_settings.json
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict

from neurova.core.logger import get_logger

logger = get_logger(__name__)

_ENV_OVERRIDE_KEY = "NEUROVA_EVOLUTION_SETTINGS"
_lock = threading.RLock()


def _settings_path() -> Path:
    """动态解析(测试可 monkeypatch env;import 时冻结会让隔离测试互踩)。"""
    return Path(os.environ.get(_ENV_OVERRIDE_KEY, "config/evolution_settings.json"))


@dataclass
class EvolutionSettings:
    """进化系统运行设置(默认保守关闭)。"""

    # 文本级进化总开关(GEPA 式闭环)
    text_evolution: bool = False
    # 技能生命周期定期扫描(确定性、零 LLM,默认开)
    lifecycle_sweep: bool = True
    # 生命周期扫描最小间隔(小时)
    lifecycle_interval_hours: int = 24
    # LLM 模型覆写(空=用路由默认)
    judge_model: str = ""
    optimizer_model: str = ""


def _defaults() -> Dict[str, Any]:
    return asdict(EvolutionSettings())


def load_settings() -> EvolutionSettings:
    """读设置文件;缺文件/坏 JSON 一律回默认(不因配置损坏而崩进化链路)。"""
    raw = dict(_defaults())
    try:
        if _settings_path().exists():
            data = json.loads(_settings_path().read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for k in raw:
                    if k in data:
                        raw[k] = data[k]
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("进化设置读取失败, 使用默认: %s", e)
    try:
        return EvolutionSettings(**raw)
    except TypeError as e:
        logger.warning("进化设置字段不匹配, 使用默认: %s", e)
        return EvolutionSettings()


def save_settings(settings: EvolutionSettings) -> bool:
    """原子写(tmp + rename),损坏配置不能污染原文件。"""
    try:
        with _lock:
            path = _settings_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(asdict(settings), ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, path)
        return True
    except OSError as e:
        logger.error("进化设置写入失败: %s", e)
        return False


def update_settings(**patch: Any) -> EvolutionSettings:
    """局部更新未知键忽略(防前端乱传撑坏 schema)。"""
    with _lock:
        data = _defaults()
        try:
            if _settings_path().exists():
                existing = json.loads(_settings_path().read_text(encoding="utf-8"))
                if isinstance(existing, dict):
                    data.update({k: v for k, v in existing.items() if k in data})
        except (OSError, json.JSONDecodeError):
            pass
        for k, v in patch.items():
            if k in data:
                data[k] = v
        # 类型收敛:布尔字段拒绝字符串误传,数值字段坏值回默认
        defaults = _defaults()
        for k in ("text_evolution", "lifecycle_sweep"):
            data[k] = bool(data[k])
        try:
            data["lifecycle_interval_hours"] = max(1, int(data["lifecycle_interval_hours"]))
        except (TypeError, ValueError):
            data["lifecycle_interval_hours"] = defaults["lifecycle_interval_hours"]
        for k in ("judge_model", "optimizer_model"):
            data[k] = str(data[k] or "")
        settings = EvolutionSettings(**data)
        save_settings(settings)
        return settings
