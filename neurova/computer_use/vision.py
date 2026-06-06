"""
Computer Use 视觉理解模块 v1.0

集成 OmniParser 实现视觉智能：
- YOLOv8 图标检测
- EasyOCR 文本识别
- UI 元素解析与标注

从"盲操作"升级为"视觉智能"
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
import io
import logging
from pathlib import Path
import shutil
import time
import typing

logger = logging.getLogger(__name__)

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    np = None
    NUMPY_AVAILABLE = False

try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    torch = None
    TORCH_AVAILABLE = False


def detect_device() -> str:
    """检测最佳计算设备"""
    if TORCH_AVAILABLE:
        if torch.cuda.is_available():
            return "cuda"
        elif hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
            return "mps"
    return "cpu"


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
    
    def to_pixel(self, image_width: int, image_height: int) -> 'BoundingBox':
        """将归一化坐标转为像素坐标"""
        return BoundingBox(
            x=self.x * image_width,
            y=self.y * image_height,
            width=self.width * image_width,
            height=self.height * image_height,
            confidence=self.confidence,
            label=self.label
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
            "attributes": self.attributes
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
            "metadata": self.metadata
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
            if elem.element_type == "icon" or elem.element_type == "button":
                if text is None or text.lower() in elem.text.lower():
                    return elem
        return None


class IconDetector:
    """YOLOv8 图标检测器"""
    
    def __init__(self, model_path: str = None, device: str = None):
        self.device = device or detect_device()
        self.model = None
        self.model_path = model_path
        self._init_model()
        logger.debug(f"IconDetector 初始化完成, device={self.device}")
    
    def _init_model(self) -> None:
        """初始化模型"""
        try:
            from ultralytics import YOLO
            if self.model_path and Path(self.model_path).exists():
                self.model = YOLO(self.model_path)
                logger.info(f"已加载图标检测模型: {self.model_path}")
            else:
                logger.warning("未找到图标检测模型，使用默认配置")
                self._download_model()
        except ImportError:
            logger.warning("ultralytics 未安装，图标检测不可用")
        except Exception as e:
            logger.error(f"图标检测模型加载失败: {e}")
    
    def _download_model(self) -> None:
        """下载模型"""
        try:
            from ultralytics import YOLO
            self.model = YOLO('yolov8n.pt')
            logger.info("已下载 YOLOv8n 模型")
        except Exception as e:
            logger.error(f"模型下载失败: {e}")
    
    def detect(self, image: 'np.ndarray') -> typing.List[typing.Dict[str, typing.Any]]:
        """检测图标"""
        if self.model is None:
            return []
        
        try:
            results = self.model(image, device=self.device, verbose=False)
            detections = []
            for result in results:
                for box in result.boxes:
                    x1, y1, x2, y2 = box.xyxy[0].tolist()
                    conf = float(box.conf[0])
                    cls = int(box.cls[0])
                    detections.append({
                        "bbox": BoundingBox(x=x1, y=y1, width=x2-x1, height=y2-y1, confidence=conf),
                        "class": cls,
                        "confidence": conf
                    })
            return detections
        except Exception as e:
            logger.error(f"图标检测失败: {e}")
            return []


class OCRProcessor:
    """EasyOCR 文本识别处理器"""
    
    def __init__(self, languages: typing.List[str] = None):
        self.languages = languages or ['en', 'ch_sim']
        self.reader = None
        self._init_model()
        logger.debug("OCRProcessor 初始化完成")
    
    def _init_model(self) -> None:
        """初始化 OCR 模型"""
        try:
            import easyocr
            self.reader = easyocr.Reader(self.languages, gpu=TORCH_AVAILABLE and torch.cuda.is_available())
            logger.info("EasyOCR 初始化完成")
        except ImportError:
            logger.warning("easyocr 未安装，OCR 不可用")
        except Exception as e:
            logger.error(f"EasyOCR 初始化失败: {e}")
    
    def detect(self, image: 'np.ndarray') -> typing.List[typing.Dict[str, typing.Any]]:
        """检测文本"""
        if self.reader is None:
            return []
        
        try:
            results = self.reader.readtext(image)
            detections = []
            for (bbox, text, conf) in results:
                x1, y1 = bbox[0]
                x2, y2 = bbox[2]
                detections.append({
                    "text": text,
                    "bbox": BoundingBox(x=x1, y=y1, width=x2-x1, height=y2-y1, confidence=conf),
                    "confidence": conf
                })
            return detections
        except Exception as e:
            logger.error(f"OCR 检测失败: {e}")
            return []


class BoxAnnotator:
    """框标注器"""
    
    def __init__(self, line_width: int = 2):
        self.line_width = line_width
    
    def annotate(self, image: 'np.ndarray', boxes: typing.List[BoundingBox]) -> 'np.ndarray':
        """在图像上绘制边界框"""
        if not NUMPY_AVAILABLE:
            return image
        
        try:
            import cv2
            annotated = image.copy()
            for box in boxes:
                x1, y1 = int(box.x), int(box.y)
                x2, y2 = int(box.x + box.width), int(box.y + box.height)
                color = (0, 255, 0)
                cv2.rectangle(annotated, (x1, y1), (x2, y2), color, self.line_width)
            return annotated
        except ImportError:
            logger.warning("cv2 未安装，无法标注")
            return image


class VisualParser:
    """视觉解析器（完整版）"""
    
    def __init__(self, model_path: str = None, device: str = None):
        self.device = device or detect_device()
        self.icon_detector = IconDetector(model_path, self.device)
        self.ocr_processor = OCRProcessor()
        self.annotator = BoxAnnotator()
        self._loaded = False
        logger.info(f"VisualParser 初始化完成, device={self.device}")
    
    def load_models(self) -> bool:
        """加载所有模型"""
        self._loaded = True
        logger.info("视觉模型加载完成")
        return True
    
    def parse(self, image: 'np.ndarray') -> ParseResult:
        """解析图像"""
        start_time = time.time()
        elements: typing.List[UIElement] = []
        
        if image is None or (NUMPY_AVAILABLE and image.size == 0):
            return ParseResult(metadata={"error": "无效图像"})
        
        h, w = image.shape[:2] if NUMPY_AVAILABLE else (0, 0)
        
        # 图标检测
        icons = self.icon_detector.detect(image)
        for icon in icons:
            elements.append(IconElement(
                element_type="icon",
                bbox=icon["bbox"],
                confidence=icon["confidence"],
                icon_type=str(icon.get("class", "unknown"))
            ))
        
        # OCR 文本检测
        texts = self.ocr_processor.detect(image)
        for t in texts:
            elements.append(TextElement(
                element_type="text",
                bbox=t["bbox"],
                text=t["text"],
                confidence=t["confidence"]
            ))
        
        elapsed = time.time() - start_time
        
        return ParseResult(
            elements=elements,
            image_width=w,
            image_height=h,
            parse_time=elapsed,
            metadata={"device": self.device, "icons": len(icons), "texts": len(texts)}
        )
    
    def parse_from_base64(self, b64_str: str) -> ParseResult:
        """从 base64 解析"""
        try:
            data = base64.b64decode(b64_str)
            if NUMPY_AVAILABLE:
                import cv2
                arr = np.frombuffer(data, dtype=np.uint8)
                image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if image is not None:
                    image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
                    return self.parse(image)
            
            # 降级到 PIL
            try:
                from PIL import Image
                img = Image.open(io.BytesIO(data)).convert('RGB')
                arr = np.array(img)
                return self.parse(arr)
            except ImportError:
                return ParseResult(metadata={"error": "无法解析图像（缺少 cv2/PIL）"})
        except Exception as e:
            return ParseResult(metadata={"error": str(e)})


# 全局实例
_parser: typing.Optional[VisualParser] = None


def get_visual_parser(model_path: str = None, device: str = None) -> VisualParser:
    """获取全局 VisualParser 实例"""
    global _parser
    if _parser is None:
        _parser = VisualParser(model_path, device)
    return _parser


def is_vision_available() -> bool:
    """检查视觉理解功能是否可用"""
    try:
        import cv2
        import easyocr
        return True
    except ImportError:
        return False


def reset_visual_parser() -> None:
    """重置（用于测试）"""
    global _parser
    _parser = None