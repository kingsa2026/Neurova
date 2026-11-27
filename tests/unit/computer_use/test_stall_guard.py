# -*- coding: utf-8 -*-
"""C4 屏幕指纹卡顿熔断（OSWorld 失败驱动改进卡）红灯测试。

M3 教训（OSWorld 子集 50）：动作反复执行、画面零变化（9bc3cc16 dup=12、
c288e301 dup=7）——模型无法区分"动作未生效"与"生效但无视觉变化"，空转到
步数耗尽。本卡在桌面管理器内做指纹记账：

- ``framesDiffer``：前后帧像素差分判别原语（纯函数，与证据帧同源）；
- ``StallGuard``：截图指纹记账——连续 N 次截图无变化**且其间发生过前台
  注入动作** → stall 信号（动作可能未生效，换策略）；无动作的空截图不报
  （那是盲截图循环，另有纪律条目管）；
- 信号经 ``manager.stallObserve`` 在 computer_screenshot 结果面注入提醒。
"""

import os
from unittest.mock import MagicMock

import pytest

from neurova.computer_use.evidence_frames import framesDiffer
from neurova.computer_use.stall_guard import (
    STALL_GUARD_ENV,
    STALL_DEFAULT_WINDOW,
    StallGuard,
)


def _pngBytes(color, size=(64, 48)):
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


_SAME = _pngBytes((240, 240, 245))
_CHANGED = _pngBytes((20, 80, 180))


class TestFramesDiffer:
    def test_identicalFramesReturnFalse(self):
        assert framesDiffer(_SAME, _SAME) is False

    def testDifferentFramesReturnTrue(self):
        assert framesDiffer(_SAME, _CHANGED) is True

    def testMissingOrCorruptFrameReturnsNone(self):
        assert framesDiffer(None, _SAME) is None
        assert framesDiffer(_SAME, b"not-png") is None


class TestStallGuard:
    def test_consecutiveNoChangeWithActionsSignalsStall(self):
        guard = StallGuard(window=3)
        # 每次"截图"之间都发生过前台注入动作（模型在操作，画面没变）
        guard.markAction()
        assert guard.observe(_SAME) is None  # 第 1 帧：无历史
        guard.markAction()
        assert guard.observe(_SAME) is None  # 第 2 帧：无变化计 1，未达窗
        guard.markAction()
        signal = guard.observe(_SAME)  # 第 3 帧：连续无变化达窗 → stall
        assert signal is not None
        assert signal["stall"] is True
        assert signal["stall_count"] >= 3
        assert signal["hint"], "stall 信号必须带换策略提醒文本"

    def test_actionWithoutFrameChangeResetsOnChange(self):
        guard = StallGuard(window=3)
        guard.markAction()
        guard.observe(_SAME)   # streak=1（一对无变化）
        guard.markAction()
        guard.observe(_CHANGED)  # 画面真的变了 → 重新起账，该帧是新基线
        guard.markAction()
        guard.observe(_SAME)   # 与新基线比 → 变化 → streak=0，重新起账
        assert guard.streak == 0
        guard.markAction()
        assert guard.observe(_SAME) is None  # 无变化一对 → streak=1，未达窗
        assert guard.streak == 1

    def test_screenshotWithoutActionNeverStalls(self):
        guard = StallGuard(window=3)
        guard.observe(_SAME)
        guard.observe(_SAME)
        assert guard.observe(_SAME) is None, \
            "无注入动作的相同帧不报 stall（盲截图循环另有纪律管）"
        assert guard.streak == 0, "无动作的无变化帧不计入 streak"

    def test_envDisableShortCircuits(self, monkeypatch):
        monkeypatch.setenv(STALL_GUARD_ENV, "0")
        guard = StallGuard(window=3)
        guard.markAction()
        for _ in range(5):
            assert guard.observe(_SAME) is None, "档位关闭时恒无信号"

    def test_defaultWindowIsThreeAndDefaultEnabled(self, monkeypatch):
        monkeypatch.delenv(STALL_GUARD_ENV, raising=False)
        assert STALL_DEFAULT_WINDOW == 3
        assert StallGuard().enabled is True, "缺省开启（env 显式关才关）"

    def test_managerWiringScreenshotObserveAndActionMark(self, monkeypatch):
        """manager 接线：截图走 observe、前台动作走 markAction、信号出结果面。"""
        from neurova.computer_use import get_computer_use_manager, reset_computer_use_manager

        monkeypatch.delenv(STALL_GUARD_ENV, raising=False)
        reset_computer_use_manager()
        manager = get_computer_use_manager()
        guard = manager.stallGuard()
        assert guard is not None, "manager 必须持有 StallGuard"
        guard.reset()
        monkeypatch.setattr(manager, "screenshot", lambda region=None: _SAME)

        manager.markDesktopAction()
        first = manager.screenshot()
        assert first == _SAME
        assert manager.stallObserve(first) is None
        assert guard.streak == 1
