"""P3-10（ZCode 电脑操控对照评测）：SOM 检测器接口化＋能力面标注。

som.py 的检测器本就是"可注入"设计，但选型点散在调用方（detector= 参数），
能力面也不知道当前用的是哪档检测器。本文件钉：get_som_detector() 单点选型
（env NEUROVA_SOM_DETECTOR，未知值回启发式不崩）、SomDetector 协议、
capability_state 新增 som 轴（如实标注启发式档）。
"""

import pytest

from neurova.computer_use import capability_state as caps
from neurova.computer_use import som


class TestDetectorSelection:
    def test_default_returns_heuristic(self, monkeypatch):
        monkeypatch.delenv(som.SOM_DETECTOR_ENV, raising=False)
        assert som.get_som_detector() is som.default_detector

    def test_unknown_env_falls_back_heuristic(self, monkeypatch):
        """未登记的选型名：回退启发式（不崩、不静默换实现）。"""
        monkeypatch.setenv(som.SOM_DETECTOR_ENV, "onnx-yolo-v9")
        assert som.get_som_detector() is som.default_detector

    def test_heuristic_env_explicit(self, monkeypatch):
        monkeypatch.setenv(som.SOM_DETECTOR_ENV, "heuristic")
        assert som.get_som_detector() is som.default_detector

    def test_mark_screenshot_uses_selection_point(self, monkeypatch):
        """mark_screenshot 缺省走 get_som_detector() 单点（替换检测器上层零改动）。"""
        called = []

        def fake_detector(png_bytes):
            called.append(png_bytes)
            return [{"bbox": (0, 0, 10, 10), "label": "x"}]

        monkeypatch.setattr(som, "get_som_detector", lambda: fake_detector)
        out = som.mark_screenshot(_png())
        assert called, "mark_screenshot 必须经 get_som_detector() 选型"
        assert out["marks"][0]["label"] == "x"

    def test_protocol_satisfied_by_heuristic(self):
        """default_detector 满足 SomDetector 协议（结构化类型，非继承）。"""
        assert isinstance(som.default_detector, som.SomDetector)


class TestCapabilityAxis:
    def test_som_axis_present_and_tri_state(self):
        assert "som" in caps.CAPABILITY_NAMES
        reading = caps.reading("som")
        assert reading.state == caps.CAP_AVAILABLE
        assert "heuristic" in reading.reason, "能力面必须如实标注当前检测器档位"

    def test_probeall_includes_som(self):
        assert "som" in caps.probeAll()


def _png():
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (64, 64), "white").save(buf, format="PNG")
    return buf.getvalue()
