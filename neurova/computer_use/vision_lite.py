"""
Computer Use 轻量级视觉理解模块 v1.0

不依赖 torch/ultralytics 的轻量级实现：
- 使用 Pillow 进行基础图像处理
- 使用 pytesseract 或 easyocr 进行 OCR
- 使用 opencv-python 进行边缘检测和轮廓分析

适合在资源受限环境或无法安装 PyTorch 时使用
"""

from __future__ import annotations

import base64
import io
import logging
import time
import typing
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

try:
    import cv2

    CV2_AVAILABLE = True
except ImportError:
    cv2 = None
    CV2_AVAILABLE = False

try:
    import numpy as np

    NUMPY_AVAILABLE = True
except ImportError:
    np = None
    NUMPY_AVAILABLE = False

try:
    from PIL import Image

    PIL_AVAILABLE = True
except ImportError:
    Image = None
    PIL_AVAILABLE = False


@dataclass
class BoundingBox:
    """边界框"""

    x: float
    y: float
    width: float
    height: float
    confidence: float = 1.0
    label: str = ""

    def coordinates(self) -> typing.Tuple[float, float, float, float]:
        """返回 (x1, y1, x2, y2) 坐标"""
        return (self.x, self.y, self.x + self.width, self.y + self.height)

    def to_pixel(self, image_width: int, image_height: int) -> "BoundingBox":
        """将归一化坐标转为像素坐标"""
        return BoundingBox(
            x=self.x * image_width,
            y=self.y * image_height,
            width=self.width * image_width,
            height=self.height * image_height,
            confidence=self.confidence,
            label=self.label,
        )

    def get_center(self) -> typing.Tuple[float, float]:
        """获取中心点坐标"""
        return (self.x + self.width / 2, self.y + self.height / 2)

    def __repr__(self) -> str:
        return f"BoundingBox(x={self.x:.1f}, y={self.y:.1f}, w={self.width:.1f}, h={self.height:.1f}, conf={self.confidence:.2f})"


@dataclass
class UIElement:
    """UI 元素基类"""

    element_type: str
    bbox: BoundingBox
    text: str = ""
    confidence: float = 1.0
    attributes: typing.Dict[str, typing.Any] = field(default_factory=dict)

    def to_dict(self) -> typing.Dict[str, typing.Any]:
        return {
            "element_type": self.element_type,
            "bbox": list(self.bbox.coordinates()),
            "text": self.text,
            "confidence": self.confidence,
            "attributes": self.attributes,
        }

    def __repr__(self) -> str:
        return f"UIElement(type={self.element_type}, text={self.text!r}, bbox={self.bbox})"


@dataclass
class IconElement(UIElement):
    """图标元素"""

    element_type: str = "icon"
    icon_type: str = "unknown"


@dataclass
class TextElement(UIElement):
    """文本元素"""

    element_type: str = "text"
    font_size: float = 0.0

    def to_dict(self) -> typing.Dict[str, typing.Any]:
        d = super().to_dict()
        d["font_size"] = self.font_size
        return d


@dataclass
class ButtonElement(UIElement):
    """按钮元素"""

    element_type: str = "button"
    is_clickable: bool = True

    def to_dict(self) -> typing.Dict[str, typing.Any]:
        d = super().to_dict()
        d["is_clickable"] = self.is_clickable
        return d


@dataclass
class InputElement(UIElement):
    """输入框元素"""

    element_type: str = "input"
    input_type: str = "text"
    placeholder: str = ""

    def to_dict(self) -> typing.Dict[str, typing.Any]:
        d = super().to_dict()
        d["input_type"] = self.input_type
        d["placeholder"] = self.placeholder
        return d


@dataclass
class ParseResult:
    """解析结果"""

    elements: typing.List[UIElement] = field(default_factory=list)
    image_width: int = 0
    image_height: int = 0
    parse_time: float = 0.0
    metadata: typing.Dict[str, typing.Any] = field(default_factory=dict)

    def to_dict(self) -> typing.Dict[str, typing.Any]:
        return {
            "elements": [e.to_dict() for e in self.elements],
            "image_width": self.image_width,
            "image_height": self.image_height,
            "parse_time": self.parse_time,
            "metadata": self.metadata,
        }

    def find_element_by_text(self, text: str, case_sensitive: bool = False) -> typing.Optional[UIElement]:
        """按文本查找元素"""
        for elem in self.elements:
            elem_text = elem.text
            if not case_sensitive:
                elem_text = elem_text.lower()
                text = text.lower()
            if text in elem_text:
                return elem
        return None

    def find_clickable_element(self, text: str = None) -> typing.Optional[UIElement]:
        """查找可点击元素"""
        for elem in self.elements:
            if isinstance(elem, ButtonElement) and elem.is_clickable:
                if text is None or text.lower() in elem.text.lower():
                    return elem
        return None


class LiteOCRProcessor:
    """轻量级 OCR 处理器"""

    def __init__(self):
        self._backend = None
        self._init_backend()
        logger.debug("LiteOCRProcessor 初始化完成")

    def _init_backend(self) -> None:
        """初始化 OCR 后端"""
        # 尝试 easyocr
        try:
            import easyocr

            self._reader = easyocr.Reader(["en", "ch_sim"], gpu=False)
            self._backend = "easyocr"
            logger.info("OCR 后端: easyocr")
            return
        except (ImportError, Exception):
            pass

        # 尝试 pytesseract
        try:
            import pytesseract

            pytesseract.get_tesseract_version()
            self._backend = "pytesseract"
            logger.info("OCR 后端: pytesseract")
            return
        except (ImportError, Exception):
            pass

        self._backend = None
        logger.warning("无可用 OCR 后端")

    def detect(self, image_data: bytes, width: int, height: int) -> typing.List[typing.Dict[str, typing.Any]]:
        """检测文本"""
        if not self._backend:
            return []

        try:
            if self._backend == "easyocr":
                return self._detect_easyocr(image_data, width, height)
            elif self._backend == "pytesseract":
                return self._detect_pytesseract(image_data, width, height)
        except Exception as e:
            logger.error("OCR 检测失败: %s", e)

        return []

    def _detect_easyocr(self, image_data: bytes, width: int, height: int) -> typing.List[typing.Dict[str, typing.Any]]:
        """使用 easyocr 检测"""
        if not NUMPY_AVAILABLE:
            return []

        # 转换为 numpy 数组
        arr = np.frombuffer(image_data, dtype=np.uint8)
        if len(arr) != width * height * 3:
            return []
        img = arr.reshape((height, width, 3))

        results = self._reader.readtext(img)
        detections = []
        for bbox, text, conf in results:
            x1, y1 = bbox[0]
            x2, y2 = bbox[2]
            detections.append(
                {
                    "text": text,
                    "confidence": conf,
                    "bbox": BoundingBox(x=x1, y=y1, width=x2 - x1, height=y2 - y1, confidence=conf),
                }
            )
        return detections

    def _detect_pytesseract(
        self, image_data: bytes, width: int, height: int
    ) -> typing.List[typing.Dict[str, typing.Any]]:
        """使用 pytesseract 检测"""
        import pytesseract

        if not PIL_AVAILABLE:
            return []

        # 转换为 PIL 图像
        arr = np.frombuffer(image_data, dtype=np.uint8) if NUMPY_AVAILABLE else None
        if arr is None:
            return []
        img = Image.fromarray(arr.reshape((height, width, 3)))

        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
        detections = []
        for i in range(len(data["text"])):
            text = data["text"][i].strip()
            conf = int(data["conf"][i]) / 100.0
            if text and conf > 0.3:
                detections.append(
                    {
                        "text": text,
                        "confidence": conf,
                        "bbox": BoundingBox(
                            x=data["left"][i],
                            y=data["top"][i],
                            width=data["width"][i],
                            height=data["height"][i],
                            confidence=conf,
                        ),
                    }
                )
        return detections


class LiteUIDetector:
    """轻量级 UI 元素检测器"""

    def __init__(self, min_element_size: int = 10):
        self.min_element_size = min_element_size
        logger.debug("LiteUIDetector 初始化完成")

    def detect_buttons(self, image_data: bytes, width: int, height: int) -> typing.List[BoundingBox]:
        """检测按钮"""
        if not CV2_AVAILABLE or not NUMPY_AVAILABLE:
            return []

        try:
            arr = np.frombuffer(image_data, dtype=np.uint8)
            if len(arr) != width * height * 3:
                return []
            img = arr.reshape((height, width, 3))
            gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
            edges = cv2.Canny(gray, 50, 150)
            contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            buttons = []
            for contour in contours:
                x, y, w, h = cv2.boundingRect(contour)
                if w > 30 and h > 15 and w < width * 0.8 and h < height * 0.3:
                    aspect = w / h
                    if 1.5 < aspect < 8:  # 按钮宽高比
                        buttons.append(BoundingBox(x=x, y=y, width=w, height=h, confidence=0.7, label="button"))

            return buttons
        except Exception as e:
            logger.error("按钮检测失败: %s", e)
            return []

    def detect_inputs(self, image_data: bytes, width: int, height: int) -> typing.List[BoundingBox]:
        """检测输入框"""
        if not CV2_AVAILABLE or not NUMPY_AVAILABLE:
            return []

        try:
            arr = np.frombuffer(image_data, dtype=np.uint8)
            if len(arr) != width * height * 3:
                return []
            img = arr.reshape((height, width, 3))
            gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
            _, binary = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
            contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            inputs = []
            for contour in contours:
                x, y, w, h = cv2.boundingRect(contour)
                if w > 80 and 20 < h < 60:
                    aspect = w / h
                    if aspect > 3:  # 输入框通常很宽
                        inputs.append(BoundingBox(x=x, y=y, width=w, height=h, confidence=0.6, label="input"))

            return inputs
        except Exception as e:
            logger.error("输入框检测失败: %s", e)
            return []

    def detect_icons(self, image_data: bytes, width: int, height: int) -> typing.List[BoundingBox]:
        """检测图标"""
        if not CV2_AVAILABLE or not NUMPY_AVAILABLE:
            return []

        try:
            arr = np.frombuffer(image_data, dtype=np.uint8)
            if len(arr) != width * height * 3:
                return []
            img = arr.reshape((height, width, 3))
            gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
            circles = cv2.HoughCircles(gray, cv2.HOUGH_GRADIENT, 1, 20, param1=50, param2=30, minRadius=5, maxRadius=50)

            icons = []
            if circles is not None:
                for circle in circles[0]:
                    cx, cy, r = circle
                    icons.append(
                        BoundingBox(x=cx - r, y=cy - r, width=2 * r, height=2 * r, confidence=0.5, label="icon")
                    )

            return icons
        except Exception as e:
            logger.error("图标检测失败: %s", e)
            return []


class LiteBoxAnnotator:
    """轻量级框标注器"""

    def __init__(self, line_width: int = 2):
        self.line_width = line_width

    def annotate(self, image_data: bytes, width: int, height: int, boxes: typing.List[BoundingBox]) -> bytes:
        """在图像上绘制边界框"""
        if not CV2_AVAILABLE or not NUMPY_AVAILABLE:
            return image_data

        try:
            arr = np.frombuffer(image_data, dtype=np.uint8).copy()
            if len(arr) != width * height * 3:
                return image_data
            img = arr.reshape((height, width, 3))

            for box in boxes:
                x1, y1, x2, y2 = int(box.x), int(box.y), int(box.x + box.width), int(box.y + box.height)
                color = (0, 255, 0)  # 绿色
                cv2.rectangle(img, (x1, y1), (x2, y2), color, self.line_width)

            return img.tobytes()
        except Exception:
            return image_data


class LiteVisualParser:
    """轻量级视觉解析器"""

    def __init__(self):
        self.ocr = LiteOCRProcessor()
        self.detector = LiteUIDetector()
        self.annotator = LiteBoxAnnotator()
        logger.info("LiteVisualParser 初始化完成")

    def parse(self, image_data: bytes, width: int, height: int) -> ParseResult:
        """解析图像中的 UI 元素"""
        start_time = time.time()
        elements: typing.List[UIElement] = []

        # OCR 检测文本
        texts = self.ocr.detect(image_data, width, height)
        for t in texts:
            elements.append(
                TextElement(element_type="text", bbox=t["bbox"], text=t["text"], confidence=t["confidence"])
            )

        # 检测按钮
        buttons = self.detector.detect_buttons(image_data, width, height)
        for bbox in buttons:
            elements.append(ButtonElement(bbox=bbox, is_clickable=True))

        # 检测输入框
        inputs = self.detector.detect_inputs(image_data, width, height)
        for bbox in inputs:
            elements.append(InputElement(bbox=bbox))

        # 检测图标
        icons = self.detector.detect_icons(image_data, width, height)
        for bbox in icons:
            elements.append(IconElement(bbox=bbox))

        elapsed = time.time() - start_time

        return ParseResult(
            elements=elements,
            image_width=width,
            image_height=height,
            parse_time=elapsed,
            metadata={
                "backend": "lite",
                "cv2_available": CV2_AVAILABLE,
                "numpy_available": NUMPY_AVAILABLE,
                "pil_available": PIL_AVAILABLE,
            },
        )

    def parse_from_base64(self, b64_str: str) -> ParseResult:
        """从 base64 解析"""
        try:
            data = base64.b64decode(b64_str)
            if not PIL_AVAILABLE:
                return ParseResult(metadata={"error": "PIL 不可用"})
            img = Image.open(io.BytesIO(data))
            width, height = img.size
            rgb = img.convert("RGB")
            pixels = list(rgb.getdata())
            raw = bytes([p[i] for p in pixels for i in range(3)])
            return self.parse(raw, width, height)
        except Exception as e:
            return ParseResult(metadata={"error": str(e)})


# 全局实例
_parser: typing.Optional[LiteVisualParser] = None


def get_lite_visual_parser() -> LiteVisualParser:
    """获取全局 LiteVisualParser 实例"""
    global _parser
    if _parser is None:
        _parser = LiteVisualParser()
    return _parser


def is_lite_vision_available() -> bool:
    """检查轻量级视觉理解功能是否可用"""
    return CV2_AVAILABLE or PIL_AVAILABLE


def get_visual_parser() -> LiteVisualParser:
    """获取视觉解析器（兼容接口）"""
    return get_lite_visual_parser()


def is_vision_available() -> bool:
    """检查视觉理解是否可用（兼容接口）"""
    return is_lite_vision_available()


def reset_lite_visual_parser() -> None:
    """重置（用于测试）"""
    global _parser
    _parser = None
