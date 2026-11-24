# -*- coding: utf-8 -*-
"""T2 VLM 指向接地（reference_af 拆解卡）红灯测试。

契约（拆解评测 §5 卡 T2 + 核实修订）：
- 第三档定位链：UIA 树命中 → 直接用（**不调 VLM**）；未命中且 VLM 档开启 →
  VLM 指向；未开启 → 结构化 unavailable（不冒充坐标）；
- 坐标解析多格式容错（JSON / x=..y=.. / 前两个整数）+ 越界 clamp + 失败重问
  一次——反向对齐对方弱点（正则取前两数、assert 无重试）；
- 全部失败 → 结构化 grounding_failed（不编坐标）；
- 默认关：env ``NEUROVA_CU_VLM_POINTING`` 灰度。
"""

import pytest

from neurova.computer_use import vlm_pointing as vp

_W, _H = 1920, 1080


class TestParsePointReply:
    def test_plain_pair(self):
        assert vp.parsePointReply("320,240", _W, _H) == (320, 240)

    def test_json_object(self):
        assert vp.parsePointReply('{"x": 10, "y": 20}', _W, _H) == (10, 20)

    def test_json_embedded_in_prose(self):
        assert vp.parsePointReply('答案是 {"x": 15, "y": 25} 请点击', _W, _H) == (15, 25)

    def test_key_value_form(self):
        assert vp.parsePointReply("x=100, y=200", _W, _H) == (100, 200)

    def test_first_two_integers_with_prose(self):
        assert vp.parsePointReply("目标位于 320 240 附近", _W, _H) == (320, 240)

    def test_out_of_bounds_clamped(self):
        assert vp.parsePointReply("5000,5000", _W, _H) == (_W - 1, _H - 1)
        assert vp.parsePointReply("-5,-7", _W, _H) == (0, 0)

    def test_garbage_returns_none(self):
        assert vp.parsePointReply("我找不到目标", _W, _H) is None
        assert vp.parsePointReply("", _W, _H) is None
        assert vp.parsePointReply(None, _W, _H) is None


class TestVlmPointingLookup:
    def test_measured_first_attempt(self):
        calls = []

        def vlm(prompt, image):
            calls.append(prompt)
            return "320,240"

        res = vp.vlmPointingLookup(b"png", "右上角的菜单", vlm, _W, _H)
        assert res == {"state": "measured", "x": 320, "y": 240,
                       "source": "vlm", "attempts": 1}
        assert len(calls) == 1
        assert "右上角的菜单" in calls[0], "目标描述必须进 prompt"

    def test_reask_once_then_measured(self):
        replies = iter(["我看不到", "10,10"])

        def vlm(prompt, image):
            return next(replies)

        res = vp.vlmPointingLookup(b"png", "登录按钮", vlm, _W, _H)
        assert res["state"] == "measured" and res["attempts"] == 2
        assert (res["x"], res["y"]) == (10, 10)

    def test_all_failed_structured_not_fabricated(self):
        def vlm(prompt, image):
            return "我找不到目标"

        res = vp.vlmPointingLookup(b"png", "不存在的控件", vlm, _W, _H)
        assert res["state"] == "grounding_failed"
        assert res["attempts"] == 2
        assert "x" not in res and "y" not in res, "失败不得编造坐标"


class TestResolveTargetPointChain:
    def test_uia_hit_skips_vlm(self):
        vlm_calls = []

        def vlm(prompt, image):
            vlm_calls.append(prompt)
            return "1,1"

        def uia(desc):
            return (150, 260)

        monkey_off = pytest.MonkeyPatch()
        monkey_off.setenv(vp.VLM_POINTING_ENV, "1")
        try:
            res = vp.resolveTargetPoint(b"png", "确定按钮", uiaLookup=uia, vlmFn=vlm,
                                        width=_W, height=_H)
        finally:
            monkey_off.undo()
        assert res == {"state": "measured", "x": 150, "y": 260, "source": "uia"}
        assert vlm_calls == [], "UIA 命中时不得调 VLM"

    def test_uia_miss_falls_to_vlm(self):
        def vlm(prompt, image):
            return "30,40"

        def uia(desc):
            return None

        mp = pytest.MonkeyPatch()
        mp.setenv(vp.VLM_POINTING_ENV, "1")
        try:
            res = vp.resolveTargetPoint(b"png", "保存", uiaLookup=uia, vlmFn=vlm,
                                        width=_W, height=_H)
        finally:
            mp.undo()
        assert res["state"] == "measured" and res["source"] == "vlm"
        assert (res["x"], res["y"]) == (30, 40)

    def test_disabled_is_structured_unavailable(self):
        def vlm(prompt, image):
            raise AssertionError("关闭时不得调用 VLM")

        mp = pytest.MonkeyPatch()
        mp.delenv(vp.VLM_POINTING_ENV, raising=False)
        try:
            res = vp.resolveTargetPoint(b"png", "保存", uiaLookup=None, vlmFn=vlm,
                                        width=_W, height=_H)
        finally:
            mp.undo()
        assert res["state"] == "unavailable"
        assert "NEUROVA_CU_VLM_POINTING" in res["reason"]

    def test_uia_exception_treated_as_miss(self):
        def vlm(prompt, image):
            return "5,6"

        def uia(desc):
            raise RuntimeError("uia backend dead")

        mp = pytest.MonkeyPatch()
        mp.setenv(vp.VLM_POINTING_ENV, "1")
        try:
            res = vp.resolveTargetPoint(b"png", "保存", uiaLookup=uia, vlmFn=vlm,
                                        width=_W, height=_H)
        finally:
            mp.undo()
        assert res["state"] == "measured" and res["source"] == "vlm"
