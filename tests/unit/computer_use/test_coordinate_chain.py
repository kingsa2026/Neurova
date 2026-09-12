"""R0-2 DPI/多屏坐标链（CUA 升级方案 Phase 0）

病根（修复前）：
- ImageGrab.grab() 只截主屏、进程无 DPI awareness → 150% 缩放/多屏环境坐标必错
- LLM 拿到的截图像素坐标被直接当屏幕坐标点击，无换算链

验收：
- compute_screen_metadata 纯函数：virtual_origin/screen_size/pixel_size/scale 组装
- screenshot_px_to_screen_point：截图像素（虚拟屏原点相对）→ 屏幕坐标点，
  scale=1/1.5 与多屏负原点（-1920, 0）全部正确
- screen_point_to_screenshot_px 为逆映射
- Manager.convert_screenshot_point：metadata 不可用时恒等回退（fail-open 保底可用）
- 全屏截图改走 all_screens=True（单屏 100% 时输出与旧行为逐字节等价）
"""

from unittest.mock import MagicMock

import pytest

from neurova.computer_use import (
    ComputerUseManager,
    screenshot_px_to_screen_point,
    screen_point_to_screenshot_px,
)

META_100 = {
    "virtual_origin": (0, 0),
    "screen_size": (1920, 1080),
    "pixel_size": (1920, 1080),
    "scale": 1.0,
}
META_150 = {
    "virtual_origin": (0, 0),
    "screen_size": (1280, 720),
    "pixel_size": (1920, 1080),
    "scale": 1.5,
}
META_DUAL_LEFT = {
    "virtual_origin": (-1920, 0),  # 副屏在主屏左侧时的虚拟屏原点
    "screen_size": (3840, 1080),
    "pixel_size": (3840, 1080),
    "scale": 1.0,
}


class TestCoordinateConversion:
    def test_identity_at_100_scale(self):
        assert screenshot_px_to_screen_point(100, 200, META_100) == (100, 200)

    def test_scale_150(self):
        """150% 缩放：截图像素 ÷ 1.5 = 屏幕逻辑点"""
        assert screenshot_px_to_screen_point(300, 450, META_150) == (200.0, 300.0)

    def test_dual_monitor_negative_origin(self):
        """截图 (0,0) 是虚拟屏左上角（副屏），换算后带负原点偏移"""
        assert screenshot_px_to_screen_point(0, 0, META_DUAL_LEFT) == (-1920, 0)
        assert screenshot_px_to_screen_point(1920, 540, META_DUAL_LEFT) == (0, 540)

    def test_reverse_mapping(self):
        px = screen_point_to_screenshot_px(200.0, 300.0, META_150)
        assert (px[0], px[1]) == pytest.approx((300, 450))

    def test_round_trip(self):
        for meta in (META_100, META_150, META_DUAL_LEFT):
            x, y = screenshot_px_to_screen_point(123, 456, meta)
            px, py = screen_point_to_screenshot_px(x, y, meta)
            assert (round(px), round(py)) == (123, 456)


class TestManagerConvert:
    def test_convert_uses_metadata(self, monkeypatch):
        manager = ComputerUseManager()
        monkeypatch.setattr(manager, "screen_metadata", lambda force_refresh=False: META_150)
        assert manager.convert_screenshot_point(300, 450) == (200.0, 300.0)

    def test_convert_fails_open_identity_without_metadata(self, monkeypatch):
        """metadata 不可用（非 Windows 等）时恒等回退，点击仍可用"""
        manager = ComputerUseManager()
        monkeypatch.setattr(manager, "screen_metadata", lambda force_refresh=False: None)
        assert manager.convert_screenshot_point(300, 450) == (300, 450)

    def test_click_screenshot_point_converts_before_click(self, monkeypatch):
        """click_screenshot_point：先换算再把屏幕坐标交给底层 click"""
        manager = ComputerUseManager()
        monkeypatch.setattr(manager, "screen_metadata", lambda force_refresh=False: META_150)
        recorded = {}
        monkeypatch.setattr(
            manager, "click", lambda x, y, button="left": recorded.update(x=x, y=y, button=button) or True
        )
        assert manager.click_screenshot_point(300, 450) is True
        assert recorded == {"x": 200.0, "y": 300.0, "button": "left"}


class TestFullscreenCapture:
    def test_screenshot_uses_all_screens(self, monkeypatch):
        """全屏截图必须覆盖虚拟屏（多屏），region 模式保持原语义"""
        from PIL import Image

        fake_img = Image.new("RGB", (10, 10))
        calls = {}

        def fake_grab(region=None, all_screens=False):
            calls["region"] = region
            calls["all_screens"] = all_screens
            return fake_img

        fake_pil = MagicMock()
        fake_pil.ImageGrab.grab = fake_grab
        monkeypatch.setitem(__import__("sys").modules, "PIL", fake_pil)
        # PIL.ImageGrab 以 from-import 使用，需同时替换 ImageGrab 模块
        import sys as _sys
        monkeypatch.setitem(_sys.modules, "PIL.ImageGrab", fake_pil.ImageGrab)

        manager = ComputerUseManager()
        manager.screenshot()
        assert calls["all_screens"] is True and calls["region"] is None
        manager.screenshot(region=(0, 0, 5, 5))
        assert calls["region"] == (0, 0, 5, 5) and calls["all_screens"] is False
