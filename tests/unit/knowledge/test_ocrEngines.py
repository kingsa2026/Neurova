# -*- coding: utf-8 -*-
"""OCR 引擎协议（升级计划 A2）：三 provider 契约同形，选择单源可读失败。

验收（计划 §5 Batch A2）：
- `OcrEngine` 契约（available/recognize）三家一致，下游不感知 provider 差异；
- `NEUROVA_KB_OCR_ENGINE` 缺省 rapidocr——历史行为逐字不变；未知引擎名在
  选择处报可读错误，不静默回落；
- auto 按序取第一个可用，全不可用返回首选实例由调用点显式 ocr_unavailable；
- 文档管线真用选择器（桩引擎的 name 进 ocr_engine 元数据，置信度进 _scores）。
"""
from __future__ import annotations

import io

import pytest

from neurova.knowledge import document_pipeline as dp
from neurova.knowledge.ocr_engines import (
    OCR_ENGINE_ENV,
    PaddleOcrEngine,
    RapidOcrEngine,
    TesseractOcrEngine,
    selectOcrEngine,
)

ENGINE_CLASSES = (RapidOcrEngine, PaddleOcrEngine, TesseractOcrEngine)


class _StubEngine:
    name = "stub"

    def available(self) -> bool:
        return True

    def recognize(self, image: bytes):
        return "识别文本", 0.87, self.name


def _pngBytes() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (4, 4), "white").save(buf, format="PNG")
    return buf.getvalue()


class TestEngineContract:
    @pytest.mark.parametrize("cls", ENGINE_CLASSES, ids=lambda c: c.name)
    def testEnginesShareTheSameContract(self, cls):
        engine = cls()

        assert engine.name in ("rapidocr", "paddle", "tesseract")
        assert callable(engine.available)
        # 不装依赖的引擎 available() 如实 False，不抛——契约是"回答"，不是"崩溃"。
        assert isinstance(engine.available(), bool)
        assert callable(engine.recognize)

    def testUnavailableEngineFailsWithReadableReason(self):
        class _Absent(RapidOcrEngine):
            name = "absent"

            def _load(self):
                return None

        with pytest.raises(Exception) as excinfo:
            _Absent().recognize(b"not-an-image")

        assert "ocr_unavailable" in str(excinfo.value) or "不可用" in str(excinfo.value)


class TestEngineSelection:
    def testDefaultIsRapidOcrWithoutEnv(self, monkeypatch):
        monkeypatch.delenv(OCR_ENGINE_ENV, raising=False)

        assert isinstance(selectOcrEngine(), RapidOcrEngine)

    def testExplicitSelectionHonoredEvenIfUnavailable(self, monkeypatch):
        monkeypatch.setenv(OCR_ENGINE_ENV, "paddle")

        assert isinstance(selectOcrEngine(), PaddleOcrEngine)

    def testUnknownEngineNameIsAReadableConfigError(self, monkeypatch):
        monkeypatch.setenv(OCR_ENGINE_ENV, "hal9000")

        with pytest.raises(ValueError) as excinfo:
            selectOcrEngine()

        assert "hal9000" in str(excinfo.value)
        assert "NEUROVA_KB_OCR_ENGINE" in str(excinfo.value)

    def testAutoPicksFirstAvailable(self, monkeypatch):
        monkeypatch.setenv(OCR_ENGINE_ENV, "auto")
        calls = []

        def _fakeAvailable(self):
            calls.append(type(self).name)
            return type(self).name == "paddle"

        monkeypatch.setattr(RapidOcrEngine, "available", _fakeAvailable)
        monkeypatch.setattr(PaddleOcrEngine, "available", _fakeAvailable)
        monkeypatch.setattr(TesseractOcrEngine, "available", _fakeAvailable)

        assert isinstance(selectOcrEngine(), PaddleOcrEngine)
        assert calls[0] == "rapidocr"

    def testAutoWithNothingAvailableReturnsRapidForHonestFailure(self, monkeypatch):
        monkeypatch.setenv(OCR_ENGINE_ENV, "auto")
        monkeypatch.setattr(RapidOcrEngine, "available", lambda self: False)
        monkeypatch.setattr(PaddleOcrEngine, "available", lambda self: False)
        monkeypatch.setattr(TesseractOcrEngine, "available", lambda self: False)

        assert isinstance(selectOcrEngine(), RapidOcrEngine)


class TestPipelineUsesTheSelector:
    def testStubEngineFlowsThroughMetadata(self, monkeypatch):
        monkeypatch.delenv(OCR_ENGINE_ENV, raising=False)
        monkeypatch.setattr(dp, "selectOcrEngine", lambda: _StubEngine())

        parsed = dp.parse_document(_pngBytes(), "scan.png", ocr_mode="on")

        assert parsed.pages[0]["text"] == "识别文本"
        assert parsed.metadata.get("ocr_engine") == "stub"
        assert parsed.metadata.get("ocr_used") is True
        # _scores 是内部累计键，出 metadata 时折成 ocr_confidence_avg。
        assert parsed.metadata.get("ocr_confidence_avg") == 0.87

    def testUnavailableSelectedEngineReportsItsName(self, monkeypatch):
        class _DeadEngine(_StubEngine):
            name = "dead"

            def available(self) -> bool:
                return False

        monkeypatch.setattr(dp, "selectOcrEngine", lambda: _DeadEngine())

        with pytest.raises(dp.DocumentParseError) as excinfo:
            dp.parse_document(_pngBytes(), "scan.png", ocr_mode="on")

        assert excinfo.value.reason == "ocr_unavailable"
        assert "dead" in str(excinfo.value)
