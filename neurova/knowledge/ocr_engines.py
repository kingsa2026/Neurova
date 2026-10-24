"""OCR 引擎协议与可选 provider（升级计划 A2）。

三家实现同一契约：`available()` 只回答"现在能不能用"，`recognize()` 把一张
图片字节变成（文本, 置信度, 引擎名）。选择单源在 `selectOcrEngine`：
`NEUROVA_KB_OCR_ENGINE=rapidocr|paddle|tesseract|auto`，缺省 rapidocr——
历史行为逐字不变。`auto` 按此顺序取第一个可用的，全不可用时返回首选实例，
由调用点对用户显式 `ocr_unavailable`，不静默换引擎。

全都不下载模型：依赖不在这个进程里就是不可用，如实报 `ocr_unavailable`，
不 pip install、不拉模型文件。OCR 结果只有"文本+置信度"这一种形状，
下游（document_pipeline 的 ocrMeta、覆盖率/置信度读数）不感知 provider 差异。
"""
from __future__ import annotations

import io
import os
import shutil
from typing import Any, List, Optional, Protocol, Tuple

from neurova.core.logger import get_logger

logger = get_logger(__name__)

OCR_ENGINE_ENV = "NEUROVA_KB_OCR_ENGINE"


class DocumentParseError(Exception):
    """与 document_pipeline 同形的解析错误（reason, message）。

    独立定义会造成两个异常类并行；这里从原模块取——只在 recognize 失败路径
    惰性 import，避免 ocr_engines ← document_pipeline 的反向依赖。
    """

    @staticmethod
    def _error(reason: str, message: str) -> Exception:
        from neurova.knowledge.document_pipeline import DocumentParseError as Err

        return Err(reason, message)


class OcrEngine(Protocol):
    """OCR 引擎契约（升级计划 A2）：available/recognize 两问。"""

    name: str

    def available(self) -> bool:
        ...

    def recognize(self, image: bytes) -> Tuple[str, float, str]:
        ...


def _imageToRgbArray(image: bytes) -> Any:
    import numpy as np
    from PIL import Image

    return np.array(Image.open(io.BytesIO(image)).convert("RGB"))


def _assembleLines(items: List[Tuple[str, float]]) -> Tuple[str, float, ...]:
    lines = [text for text, _score in items if text]
    scores = [float(score) for _text, score in items if score is not None]
    confidence = sum(scores) / len(scores) if scores else 0.0
    return "\n".join(lines), round(confidence, 4)


class RapidOcrEngine:
    """RapidOCR 的惰性封装；未安装时 available()=False，不抛到调用方。"""

    name = "rapidocr"
    _engine: Any = None

    def available(self) -> bool:
        return self._load() is not None

    def _load(self) -> Any:
        if self._engine is not None:
            return self._engine
        try:
            from rapidocr_onnxruntime import RapidOCR  # type: ignore

            self._engine = RapidOCR()
            return self._engine
        except Exception:  # noqa: BLE001 - 新包名/旧包名都试
            try:
                from rapidocr import RapidOCR  # type: ignore

                self._engine = RapidOCR()
                return self._engine
            except Exception as exc:  # noqa: BLE001
                logger.debug("RapidOCR 不可用: %s", exc)
                return None

    def recognize(self, image: bytes) -> Tuple[str, float, str]:
        engine = self._load()
        if engine is None:
            raise DocumentParseError._error("ocr_unavailable", "RapidOCR 未安装或不可用")
        try:
            array = _imageToRgbArray(image)
            result, _elapse = engine(array)
        except Exception as exc:  # noqa: BLE001
            raise DocumentParseError._error("ocr_failed", str(exc)) from exc
        items: List[Tuple[str, float]] = []
        for row in result or []:
            try:
                _box, text, score = row[0], row[1], row[2]
            except (IndexError, TypeError):
                continue
            items.append((str(text), float(score)))
        text, confidence = _assembleLines(items)
        return text, confidence, self.name


class PaddleOcrEngine:
    """PaddleOCR 的惰性封装；契约与 RapidOCR 完全同形（升级计划 A2）。"""

    name = "paddle"
    _engine: Any = None

    def available(self) -> bool:
        return self._load() is not None

    def _load(self) -> Any:
        if self._engine is not None:
            return self._engine
        try:
            from paddleocr import PaddleOCR  # type: ignore

            self._engine = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
            return self._engine
        except Exception as exc:  # noqa: BLE001
            logger.debug("PaddleOCR 不可用: %s", exc)
            return None

    def recognize(self, image: bytes) -> Tuple[str, float, str]:
        engine = self._load()
        if engine is None:
            raise DocumentParseError._error("ocr_unavailable", "PaddleOCR 未安装或不可用")
        try:
            array = _imageToRgbArray(image)
            result = engine.ocr(array, cls=True)
        except Exception as exc:  # noqa: BLE001
            raise DocumentParseError._error("ocr_failed", str(exc)) from exc
        # paddleocr 新旧版本返回形状不同：[[box,(text,score)],...] 或
        # [[[box,(text,score)],...]]。取第一个非空的页级列表，不认第二套形状名。
        page = result[0] if result and isinstance(result[0], list) and result[0] \
            and isinstance(result[0][0], list) else result
        items: List[Tuple[str, float]] = []
        for row in page or []:
            try:
                _box, (text, score) = row[0], row[1]
            except (IndexError, TypeError, ValueError):
                continue
            items.append((str(text), float(score)))
        text, confidence = _assembleLines(items)
        return text, confidence, self.name


class TesseractOcrEngine:
    """Tesseract 的惰性封装；pytesseract 与二进制都不可用即如实报缺。"""

    name = "tesseract"

    def available(self) -> bool:
        try:
            import pytesseract  # noqa: F401
        except Exception as exc:  # noqa: BLE001
            logger.debug("Tesseract 不可用（缺 pytesseract）: %s", exc)
            return False
        if not shutil.which("tesseract"):
            logger.debug("Tesseract 不可用（缺 tesseract 可执行文件）")
            return False
        return True

    def recognize(self, image: bytes) -> Tuple[str, float, str]:
        if not self.available():
            raise DocumentParseError._error(
                "ocr_unavailable", "Tesseract 未安装或不可用")
        try:
            from PIL import Image

            import pytesseract

            img = Image.open(io.BytesIO(image)).convert("RGB")
            text = pytesseract.image_to_string(img)
            data = pytesseract.image_to_data(
                img, output_type=pytesseract.Output.DICT)
            confs = [float(c) / 100.0 for c in data.get("conf", [])
                     if str(c) not in ("-1", "-1.0") and str(c) != ""]
        except Exception as exc:  # noqa: BLE001
            raise DocumentParseError._error("ocr_failed", str(exc)) from exc
        confidence = sum(confs) / len(confs) if confs else 0.0
        return text.strip(), round(confidence, 4), self.name


_ENGINE_CLASSES = {
    "rapidocr": RapidOcrEngine,
    "paddle": PaddleOcrEngine,
    "tesseract": TesseractOcrEngine,
}
_AUTO_ORDER = ("rapidocr", "paddle", "tesseract")


def selectOcrEngine(requested: Optional[str] = None) -> OcrEngine:
    """引擎选择单源：缺省 rapidocr（历史行为逐字不变）。

    未知引擎名抛 ValueError——配置错在配置处暴露，回落会让写错的环境变量静默。
    """
    name = str(requested or os.environ.get(OCR_ENGINE_ENV) or "rapidocr").strip().lower()
    if name == "auto":
        for kind in _AUTO_ORDER:
            engine = _ENGINE_CLASSES[kind]()
            if engine.available():
                return engine
        # 全不可用：返回首选实例，调用点对其 available()/recognize() 显式
        # ocr_unavailable——"都没装"必须是可读的失败，不是静默降级。
        return RapidOcrEngine()
    if name not in _ENGINE_CLASSES:
        raise ValueError(
            "未知 OCR 引擎 %r（NEUROVA_KB_OCR_ENGINE 可选：%s；auto 按序取第一个可用）"
            % (name, "/".join(_ENGINE_CLASSES)))
    return _ENGINE_CLASSES[name]()
