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
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List

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
    # ── RSI 运行参数(§6-3 收口 2026-10-06:原三处硬编码入配置,默认值
    #    与原字面量逐字一致,零行为漂移)──
    # 经验/事件触发 RSI 迭代的节流窗口(秒)
    rsi_event_throttle_seconds: float = 60.0
    # backoff(收敛/度量失明)降频巡检窗口:每 N 轮巡检一次
    rsi_backoff_every_turns: int = 20
    # 递归棘轮每轮候选数(粗筛→中筛→细筛,轮数=len)
    rsi_ratchet_candidates: List[int] = field(default_factory=lambda: [50, 10, 3])


def _coerce_rsi_knobs(data: Dict[str, Any], defaults: Dict[str, Any]) -> None:
    """RSI 运行参数收敛(load_settings / update_settings 共用一处)。

    坏值回默认、候选数抬正、列表整组收敛——脏配置不得阻断进化装配,
    也不得静默截半(一个坏元素=整组回默认,诚实优于猜测)。
    """
    try:
        data["rsi_event_throttle_seconds"] = max(0.0, float(data["rsi_event_throttle_seconds"]))
    except (TypeError, ValueError):
        data["rsi_event_throttle_seconds"] = defaults["rsi_event_throttle_seconds"]
    try:
        backoff = int(data["rsi_backoff_every_turns"])
    except (TypeError, ValueError):
        backoff = 0
    data["rsi_backoff_every_turns"] = (
        backoff if backoff >= 1 else defaults["rsi_backoff_every_turns"])
    raw_candidates = data.get("rsi_ratchet_candidates")
    parsed: list = []
    if isinstance(raw_candidates, (list, tuple)):
        try:
            parsed = [max(1, int(x)) for x in raw_candidates]
        except (TypeError, ValueError):
            parsed = []
    data["rsi_ratchet_candidates"] = (
        parsed[:8] if parsed else list(defaults["rsi_ratchet_candidates"]))


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
    _coerce_rsi_knobs(raw, _defaults())
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
        _coerce_rsi_knobs(data, defaults)
        settings = EvolutionSettings(**data)
        save_settings(settings)
        return settings
