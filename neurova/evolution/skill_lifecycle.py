"""技能遥测生命周期 — active → stale → archived 状态机(纯函数,零 LLM)。

对位 Hermes `agent/curator.py:apply_automatic_transitions`。

设计两段式(照搬 Hermes 的克制):
  - **本模块是确定性那段**:只依据活动时间戳做状态迁移,不调 LLM,不删除;
  - LLM 巩固(合并类级技能)是另一件事,默认关(见 Wave 5)。

三条约保护语义(Hermes 踩过坑的,原样继承):
  1. `pinned` 技能全绕开——用户显式钉住的永不自动迁移;
  2. 只对 `created_by == "agent"` 的技能迁移——内置/hub/用户手写的不可动;
  3. **从未活跃的技能锚 `created_at`,不自归档**——`use_count == 0` 是
     "无证据"而非"陈旧",一个刚建好还没被触发的技能不该被清掉。

归档 = 移到 `.archive/`(可恢复),**永不删除**。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional, Protocol

from neurova.core.logger import get_logger

logger = get_logger(__name__)

DAY_MS = 86_400_000

STATE_ACTIVE = "active"
STATE_STALE = "stale"
STATE_ARCHIVED = "archived"

# 默认阈值(对齐 Hermes:14 天陈旧 / 30 天归档)
DEFAULT_STALE_AFTER_DAYS = 14
DEFAULT_ARCHIVE_AFTER_DAYS = 30


class _SkillStoreLike(Protocol):
    """生命周期需要的最小技能服务接口(便于测试注入 stub)。"""

    def iter_skills(self): ...
    def set_skill_lifecycle_state(self, skill_id: str, state: str) -> bool: ...
    def archive_skill(self, skill_id: str): ...


class SkillLifecycle:
    """生命周期参数与判定逻辑(可独立于存储复用)。"""

    def __init__(
        self,
        stale_after_days: int = DEFAULT_STALE_AFTER_DAYS,
        archive_after_days: int = DEFAULT_ARCHIVE_AFTER_DAYS,
    ):
        self.stale_after_days = stale_after_days
        self.archive_after_days = archive_after_days

    def anchor_ms(self, usage: dict[str, Any]) -> int:
        """活动锚点:最近活动时间;从未活跃则用创建时间(保护语义 3)。"""
        last_activity = int(usage.get("last_activity_at_ms") or 0)
        if last_activity > 0:
            return last_activity
        return int(usage.get("created_at_ms") or 0)

    def is_protected(self, usage: dict[str, Any]) -> bool:
        """保护语义 1 + 2:pinned 或非 agent 来源,一律不迁移。"""
        if usage.get("pinned"):
            return True
        return (usage.get("created_by") or "") != "agent"

    def target_state(self, usage: dict[str, Any], now_ms: int) -> Optional[str]:
        """计算该技能应有的状态;None 表示保持当前状态。

        返回的目标状态要与当前状态不同,调用方才真正落库。
        """
        if self.is_protected(usage):
            return None
        current = usage.get("state", STATE_ACTIVE)
        anchor = self.anchor_ms(usage)
        if anchor <= 0:
            # 连创建时间都没有:无从判断,保持不动(宁可漏过,不可误伤)
            return None
        age_days = (now_ms - anchor) / DAY_MS
        never_used = int(usage.get("use_count", 0) or 0) == 0

        # 保护语义 3:从未活跃且在陈旧窗口内的,不归档;若已被标 stale 则纠正回 active
        if never_used and age_days <= self.stale_after_days:
            return STATE_ACTIVE if current == STATE_STALE else None

        if age_days > self.archive_after_days:
            return None if current == STATE_ARCHIVED else STATE_ARCHIVED
        if age_days > self.stale_after_days:
            return STATE_STALE if current == STATE_ACTIVE else None
        # 年轻:若此前被标 stale,现在回暖 → reactivate
        return STATE_ACTIVE if current == STATE_STALE else None


def apply_transitions(
    service: _SkillStoreLike,
    *,
    now_ms: Optional[int] = None,
    stale_after_days: int = DEFAULT_STALE_AFTER_DAYS,
    archive_after_days: int = DEFAULT_ARCHIVE_AFTER_DAYS,
) -> dict[str, int]:
    """把所有 agent 创建技能按活动时间迁移状态;返回计数。

    与 Hermes 一致:先 seed(首见无记录者锚 now 并延迟),再迁移。本实现把
    seed 语义交给 anchor_ms——从未活跃者锚 created_at;若连 created_at 都
    没有,视为首次见到,锚 now 并跳过本轮。
    """
    lifecycle = SkillLifecycle(stale_after_days, archive_after_days)
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    counts = {"marked_stale": 0, "archived": 0, "reactivated": 0, "checked": 0, "seeded": 0}

    for skill_id, rec in service.iter_skills():
        counts["checked"] += 1
        usage = rec.get("usage") if isinstance(rec, dict) else None
        if not isinstance(usage, dict):
            counts["seeded"] += 1
            # 首见播种:以 now 锚 created_at(时钟从此开始,本轮仍不动)
            seed = getattr(service, "seed_skill_usage", None)
            if seed is not None:
                try:
                    seed(skill_id)
                except Exception as e:  # noqa: BLE001
                    logger.debug("播种技能 %s 失败: %s", skill_id, e)
            continue

        target = lifecycle.target_state(usage, now_ms)
        if target is None:
            continue
        current = usage.get("state", STATE_ACTIVE)
        if target == STATE_ARCHIVED:
            try:
                service.archive_skill(skill_id)
                counts["archived"] += 1
            except Exception as e:  # noqa: BLE001 - 单个技能失败不中断整轮
                logger.debug("归档技能 %s 失败: %s", skill_id, e)
            continue
        try:
            service.set_skill_lifecycle_state(skill_id, target)
        except Exception as e:  # noqa: BLE001
            logger.debug("迁移技能 %s 状态失败: %s", skill_id, e)
            continue
        if target == STATE_STALE:
            counts["marked_stale"] += 1
        elif target == STATE_ACTIVE and current == STATE_STALE:
            counts["reactivated"] += 1

    return counts


# ── 定期扫描触发(对位 Hermes .curator_state,无 cron 守护)──

_DEFAULT_INTERVAL_HOURS = 24


def _state_file(skills_dir: Path) -> Path:
    return Path(skills_dir) / ".lifecycle_state.json"


def _load_last_run(skills_dir: Path) -> int:
    try:
        data = json.loads(_state_file(skills_dir).read_text(encoding="utf-8"))
        return int(data.get("last_run_at_ms") or 0)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return 0


def _save_last_run(skills_dir: Path, now_ms: int) -> None:
    try:
        path = _state_file(skills_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"last_run_at_ms": now_ms}), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as e:
        logger.debug("生命周期扫描状态写入失败: %s", e)


def run_sweep_if_due(
    service: _SkillStoreLike,
    skills_dir: Path,
    *,
    interval_hours: int = _DEFAULT_INTERVAL_HOURS,
    now_ms: Optional[int] = None,
    stale_after_days: int = DEFAULT_STALE_AFTER_DAYS,
    archive_after_days: int = DEFAULT_ARCHIVE_AFTER_DAYS,
) -> Optional[dict[str, int]]:
    """到期才扫并更新状态;未到期返回 None。

    首次观察只 seed(记录 now 并跳过本轮)——与 Hermes curator 一致:
    全新安装的首个 tick 绝不动技能库。
    """
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    last = _load_last_run(Path(skills_dir))
    if last == 0:
        _save_last_run(Path(skills_dir), now_ms)
        logger.debug("生命周期扫描首次 seed, 延迟一个周期")
        return None
    if now_ms - last < interval_hours * 3_600_000:
        return None
    counts = apply_transitions(
        service, now_ms=now_ms,
        stale_after_days=stale_after_days, archive_after_days=archive_after_days,
    )
    _save_last_run(Path(skills_dir), now_ms)
    logger.info(
        "技能生命周期扫描: stale=%d archived=%d reactivated=%d",
        counts["marked_stale"], counts["archived"], counts["reactivated"],
    )
    return counts
