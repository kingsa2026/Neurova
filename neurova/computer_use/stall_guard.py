# -*- coding: utf-8 -*-
"""屏幕指纹卡顿熔断（C4，OSWorld 失败驱动改进卡）。

M3 教训：动作反复执行、画面零变化（模型无法区分"动作未生效"与"生效但无
视觉变化"，空转到步数耗尽）。本模块在桌面管理器内做指纹记账：

- 记账零额外截图成本：指纹在 ``computer_screenshot``（模型自发的观察动作）
  的取帧点采集，前台注入动作只打一个 mark；
- 判定语义：**连续 N 次截图无变化且其间发生过前台注入动作** → stall 信号
  （"动作可能未生效，换策略"）。无注入动作的相同帧不计（盲截图循环另有
  纪律条目管，不冤枉观察行为）；
- 缺省开启（env ``NEUROVA_CU_STALL_GUARD`` 显式关才关），状态有界（只存
  最近一帧字节 + 两个计数器）。
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from neurova.computer_use.evidence_frames import framesDiffer
from neurova.core.logger import get_logger

logger = get_logger(__name__)

__all__ = [
    "STALL_GUARD_ENV",
    "STALL_DEFAULT_WINDOW",
    "STALL_HINT",
    "stallGuardEnabled",
    "StallGuard",
]

#: 卡顿熔断档开关（缺省开；env 显式 0/false/no/off 才关）。
STALL_GUARD_ENV = "NEUROVA_CU_STALL_GUARD"

#: 连续无变化截图窗（达窗即发 stall 信号并重新起账）。
STALL_DEFAULT_WINDOW = 3

#: 注入提醒（随 computer_screenshot 结果面对模型可见）。
STALL_HINT = (
    "连续多次操作后画面无变化：动作可能未生效（命令未进入目标窗口/焦点错位/"
    "弹窗遮挡）。请换策略或换工具，不要重复同一动作；需要时先用 "
    "computer_dom_snapshot 拿控件树事实再操作。"
)


def stallGuardEnabled() -> bool:
    """卡顿熔断档是否开启（env 显式关才关，缺省开）。"""
    raw = str(os.environ.get(STALL_GUARD_ENV, "")).strip().lower()
    return raw not in ("0", "false", "no", "off")


class StallGuard:
    """截图指纹记账器（桌面管理器持有；线程安全面由调用方串行化保证——
    截图与前台注入动作都经 desktop 车道串行）。"""

    def __init__(self, window: int = STALL_DEFAULT_WINDOW, enabled: Optional[bool] = None):
        self._window = max(2, int(window))
        self.enabled = stallGuardEnabled() if enabled is None else bool(enabled)
        self._lastFrameBytes: Optional[bytes] = None
        self.streak: int = 0
        self._actionsSinceLastFrame: int = 0

    def markAction(self) -> None:
        """前台注入动作完成时打点（声明"两帧之间发生过操作"）。"""
        self._actionsSinceLastFrame += 1

    def observe(self, pngBytes: Optional[bytes]) -> Optional[Dict[str, Any]]:
        """截图取帧点记账：与上一帧差分，达窗发 stall 信号（发后重新起账）。

        Returns:
            ``{"stall": True, "stall_count": n, "hint": str}`` 或 None（无信号）。
        """
        if not self.enabled:
            return None
        last = self._lastFrameBytes
        self._lastFrameBytes = pngBytes
        if last is None:
            self.streak = 1
            self._actionsSinceLastFrame = 0
            return None
        differ = framesDiffer(last, pngBytes)
        hadAction = self._actionsSinceLastFrame > 0
        self._actionsSinceLastFrame = 0
        if differ is None or differ or not hadAction:
            # 变化/无法判定/无动作 → 不构成"动作未生效"证据，重新起账
            self.streak = 0
            return None
        self.streak += 1
        if self.streak >= self._window:
            self.streak = 0
            logger.warning(
                "[stall_guard] 连续 %d 次操作后画面无变化，注入换策略提醒",
                self._window,
            )
            return {
                "stall": True,
                "stall_count": self._window,
                "hint": STALL_HINT,
            }
        return None

    def reset(self) -> None:
        """清账（新任务/新会话起点）。"""
        self._lastFrameBytes = None
        self.streak = 0
        self._actionsSinceLastFrame = 0
