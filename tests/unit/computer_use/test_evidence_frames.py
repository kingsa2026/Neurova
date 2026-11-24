# -*- coding: utf-8 -*-
"""T5 动作证据帧（reference_af 拆解卡）红灯测试。

契约（拆解评测 §5 卡 T5）：
- 前台点动作（click/drag）在开启档下采集 **动作前/后帧**，并按动作点做
  300×300 **局部放大裁剪**（越界 clamp），存入有界证据库（LRU 32）；
- 工具结果只挂 **元数据**（evidence_id/point/crop_size），像素不进 LLM
  上下文（与 computer_screenshot "base64 撑爆上下文" 纪律同源）；
- 读取面 getEvidence(evidence_id) 供审批/失败归因/面板消费；
- 默认关（env ``NEUROVA_CU_EVIDENCE_FRAMES`` 灰度）；护栏拒绝的动作不产帧。
"""

import base64
import io

import pytest
from PIL import Image

from neurova.computer_use import evidence_frames as ef


def _png(width: int = 800, height: int = 600, color=(10, 20, 30)) -> bytes:
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _stubManager(png: bytes):
    class _Mgr:
        def screenshot(self, region=None):
            return png

        def click_screenshot_point(self, x, y, button="left"):
            return True

        def drag(self, sx, sy, ex, ey, duration, button="left"):
            return True

    return _Mgr()


class TestBuildEvidenceCrop:
    def test_crop_around_point(self):
        crop = ef.buildEvidenceCrop(_png(), (400, 300))
        assert crop is not None
        assert crop["point"] == [400, 300]
        assert crop["crop_size"] == 300
        assert crop["crop_box"] == [250, 150, 550, 450]
        img = Image.open(io.BytesIO(base64.b64decode(crop["png_b64"])))
        assert img.size == (300, 300)

    def test_crop_clamped_at_edges(self):
        crop = ef.buildEvidenceCrop(_png(400, 300), (0, 0))
        assert crop["crop_box"] == [0, 0, 300, 300]

    def test_small_screen_clamped(self):
        crop = ef.buildEvidenceCrop(_png(200, 150), (100, 75))
        assert crop is not None
        img = Image.open(io.BytesIO(base64.b64decode(crop["png_b64"])))
        assert img.size == (200, 150), "画面小于裁剪窗时按整幅取"

    def test_empty_bytes_none(self):
        assert ef.buildEvidenceCrop(b"", (10, 10)) is None
        assert ef.buildEvidenceCrop(None, (10, 10)) is None


class TestEvidencePairAndStore:
    def test_pair_build_and_store_roundtrip(self):
        pair = ef.buildEvidencePair(_png(), _png(800, 600, (99, 99, 99)), (400, 300))
        assert pair["point"] == [400, 300]
        assert pair["before"]["label"] == "before"
        assert pair["after"]["label"] == "after"
        eid = ef.storeEvidence(pair)
        assert ef.getEvidence(eid) is pair

    def test_store_lru_cap(self):
        ids = []
        for i in range(40):
            pair = ef.buildEvidencePair(_png(), _png(), (i, i))
            ids.append(ef.storeEvidence(pair))
        assert ef.getEvidence(ids[0]) is None, "超出 LRU 容量的最旧证据应被淘汰"
        assert ef.getEvidence(ids[-1]) is not None

    def test_attach_metadata_only_no_pixels(self):
        pair = ef.buildEvidencePair(_png(), _png(), (400, 300))
        result = {"success": True}
        ef.attachToResult(result, pair)
        assert result["evidence_frames"]["evidence_id"] == pair["evidence_id"]
        assert result["evidence_frames"]["point"] == [400, 300]
        assert "png_b64" not in str(result["evidence_frames"]), "像素不得进 LLM 结果面"


class TestEnvGate:
    def test_default_off(self, monkeypatch):
        monkeypatch.delenv(ef.EVIDENCE_FRAMES_ENV, raising=False)
        assert ef.evidenceFramesEnabled() is False

    def test_env_on(self, monkeypatch):
        monkeypatch.setenv(ef.EVIDENCE_FRAMES_ENV, "1")
        assert ef.evidenceFramesEnabled() is True


class TestClickDragIntegration:
    def test_click_attaches_evidence_when_enabled(self, monkeypatch):
        monkeypatch.setenv(ef.EVIDENCE_FRAMES_ENV, "1")
        from neurova.computer_use import actions

        manager = _stubManager(_png())
        res = actions.click_screenshot_point(manager, 400, 300)
        assert res["success"] is True
        assert "evidence_id" in res["evidence_frames"]
        assert ef.getEvidence(res["evidence_frames"]["evidence_id"]) is not None

    def test_click_no_evidence_when_disabled(self, monkeypatch):
        monkeypatch.delenv(ef.EVIDENCE_FRAMES_ENV, raising=False)
        from neurova.computer_use import actions

        manager = _stubManager(_png())
        res = actions.click_screenshot_point(manager, 400, 300)
        assert res["success"] is True
        assert "evidence_frames" not in res

    def test_drag_attaches_evidence_at_end_point(self, monkeypatch):
        monkeypatch.setenv(ef.EVIDENCE_FRAMES_ENV, "1")
        from neurova.computer_use import actions

        manager = _stubManager(_png())
        res = actions.drag(manager, 100, 100, 500, 400)
        assert res["success"] is True
        assert res["evidence_frames"]["point"] == [500, 400], "拖拽以终点为取证中心"

    def test_refused_action_produces_no_evidence(self, monkeypatch):
        monkeypatch.setenv(ef.EVIDENCE_FRAMES_ENV, "1")
        from neurova.computer_use import actions
        from neurova.computer_use.lane_mutex import DESKTOP_LANE, get_lane_mutex

        manager = _stubManager(_png())
        with get_lane_mutex().hold(DESKTOP_LANE, owner="other"):
            res = actions.click_screenshot_point(manager, 400, 300)
        assert res.get("success") is False
        assert "evidence_frames" not in res, "护栏拒绝的动作不产证据帧"
