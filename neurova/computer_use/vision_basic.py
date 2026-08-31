"""
Computer Use 基础视觉理解模块 v1.0.0-beta1

不依赖任何外部库的纯 Python 实现：
- 使用内置库进行基础图像处理
- 使用简单的算法检测 UI 元素
- 提供基本的视觉理解功能

适合在无法安装任何外部依赖时使用
"""

from __future__ import annotations

import base64
from neurova.core.logger import get_logger
import struct
import time
import typing
from dataclasses import dataclass, field

logger = get_logger(__name__)


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

    # 注意: bbox 无默认值, 必须排在所有带默认值的字段之前。
    # 子类覆盖 element_type 默认值时若 bbox 靠后, dataclass 会抛
    # "non-default argument follows default argument"。
    bbox: BoundingBox
    element_type: str = ""
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


class BasicImage:
    """纯 Python 图像类（BMP/PPM 格式）"""

    def __init__(self, data: bytes, width: int, height: int, channels: int = 3):
        self.data = data
        self.width = width
        self.height = height
        self.channels = channels

    @classmethod
    def from_base64(cls, b64_str: str) -> typing.Optional["BasicImage"]:
        """从 base64 字符串创建"""
        try:
            raw = base64.b64decode(b64_str)
            # 尝试 BMP
            if raw[:2] == b"BM":
                return cls._parse_bmp(raw)
            # 尝试 PPM
            if raw[:2] == b"P6" or raw[:2] == b"P5":
                return cls._parse_ppm(raw)
            # 尝试 PNG (提取基础信息)
            if raw[:8] == b"\x89PNG\r\n\x1a\n":
                return cls._parse_png_simple(raw)
            logger.warning("不支持的图像格式")
            return None
        except Exception as e:
            logger.error("图像解码失败: %s", e)
            return None

    @classmethod
    def _parse_bmp(cls, data: bytes) -> typing.Optional["BasicImage"]:
        """解析 BMP 格式"""
        try:
            if len(data) < 54:
                return None
            width = struct.unpack_from("<i", data, 18)[0]
            height = abs(struct.unpack_from("<i", data, 22)[0])
            bpp = struct.unpack_from("<H", data, 28)[0]
            channels = bpp // 8
            # BMP 像素数据从 offset 54 开始（简化处理）
            pixel_offset = struct.unpack_from("<I", data, 10)[0]
            pixel_data = data[pixel_offset:]
            return cls(pixel_data[: width * height * channels], width, height, channels)
        except Exception:
            return None

    @classmethod
    def _parse_ppm(cls, data: bytes) -> typing.Optional["BasicImage"]:
        """解析 PPM/PGM 格式"""
        try:
            lines = data.split(b"\n", 3)
            if len(lines) < 3:
                return None
            magic = lines[0].strip()
            dims = lines[1].strip().split()
            width, height = int(dims[0]), int(dims[1])
            channels = 3 if magic == b"P6" else 1
            # 跳过头部
            header_end = data.find(b"\n", data.find(b"\n", data.find(b"\n") + 1) + 1) + 1
            pixel_data = data[header_end:]
            return cls(pixel_data[: width * height * channels], width, height, channels)
        except Exception:
            return None

    @classmethod
    def _parse_png_simple(cls, data: bytes) -> typing.Optional["BasicImage"]:
        """简单 PNG 解析（提取尺寸，不支持解码）"""
        try:
            # IHDR chunk at offset 8
            width = struct.unpack_from(">I", data, 16)[0]
            height = struct.unpack_from(">I", data, 20)[0]
            # 返回空像素数据（仅尺寸可用）
            logger.warning("PNG 格式仅提供尺寸信息，不支持像素解码")
            return cls(b"\x00" * (width * height * 3), width, height, 3)
        except Exception:
            return None

    def get_pixel(self, x: int, y: int) -> typing.Tuple[int, ...]:
        """获取像素值"""
        if x < 0 or x >= self.width or y < 0 or y >= self.height:
            raise IndexError(f"坐标越界: ({x}, {y})")
        idx = (y * self.width + x) * self.channels
        return tuple(self.data[idx : idx + self.channels])

    def get_region(self, x: int, y: int, w: int, h: int) -> bytes:
        """获取矩形区域像素数据"""
        region = bytearray()
        for row in range(y, min(y + h, self.height)):
            start = (row * self.width + x) * self.channels
            end = start + w * self.channels
            region.extend(self.data[start:end])
        return bytes(region)

    def to_base64(self) -> str:
        """转为 base64"""
        return base64.b64encode(self.data).decode("utf-8")


class BasicUIDetector:
    """纯 Python UI 元素检测器"""

    def __init__(self, min_element_size: int = 10):
        self.min_element_size = min_element_size
        logger.debug("BasicUIDetector 初始化完成")

    def detect_color_regions(
        self, image: "BasicImage", target_color: typing.Tuple[int, ...], tolerance: int = 30, min_area: int = 100
    ) -> typing.List[BoundingBox]:
        """检测特定颜色区域"""
        if not image.data:
            return []

        regions = []
        visited = set()

        for y in range(image.height):
            for x in range(image.width):
                if (x, y) in visited:
                    continue
                pixel = image.get_pixel(x, y)
                if self._color_match(pixel, target_color, tolerance):
                    # BFS 连通区域
                    region_pixels = []
                    queue = [(x, y)]
                    while queue:
                        cx, cy = queue.pop(0)
                        if (cx, cy) in visited:
                            continue
                        if cx < 0 or cx >= image.width or cy < 0 or cy >= image.height:
                            continue
                        visited.add((cx, cy))
                        px = image.get_pixel(cx, cy)
                        if self._color_match(px, target_color, tolerance):
                            region_pixels.append((cx, cy))
                            queue.extend([(cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)])

                    if len(region_pixels) >= min_area:
                        xs = [p[0] for p in region_pixels]
                        ys = [p[1] for p in region_pixels]
                        regions.append(
                            BoundingBox(
                                x=min(xs),
                                y=min(ys),
                                width=max(xs) - min(xs) + 1,
                                height=max(ys) - min(ys) + 1,
                                confidence=1.0,
                            )
                        )

        return regions

    def detect_rectangles(self, image: "BasicImage", edge_threshold: int = 30) -> typing.List[BoundingBox]:
        """检测矩形区域（简单边缘检测）"""
        if not image.data or image.channels < 3:
            return []

        rectangles = []
        # 简单边缘检测：计算相邻像素差异
        edges = []
        for y in range(1, image.height):
            for x in range(1, image.width):
                px = image.get_pixel(x, y)
                px_left = image.get_pixel(x - 1, y)
                px_up = image.get_pixel(x, y - 1)
                # 灰度差异
                gray = sum(px[:3]) // 3
                gray_left = sum(px_left[:3]) // 3
                gray_up = sum(px_up[:3]) // 3
                if abs(gray - gray_left) > edge_threshold or abs(gray - gray_up) > edge_threshold:
                    edges.append((x, y))

        # 简单聚类
        if len(edges) > 4:
            [e[0] for e in edges]
            [e[1] for e in edges]
            # 将边缘点按网格分组
            grid_size = max(image.width, image.height) // 10
            if grid_size < self.min_element_size:
                grid_size = self.min_element_size

            grid: typing.Dict[typing.Tuple[int, int], typing.List[typing.Tuple[int, int]]] = {}
            for ex, ey in edges:
                key = (ex // grid_size, ey // grid_size)
                grid.setdefault(key, []).append((ex, ey))

            for key, points in grid.items():
                if len(points) >= 4:
                    pxs = [p[0] for p in points]
                    pys = [p[1] for p in points]
                    bx, by = min(pxs), min(pys)
                    bw, bh = max(pxs) - bx, max(pys) - by
                    if bw >= self.min_element_size and bh >= self.min_element_size:
                        rectangles.append(
                            BoundingBox(x=bx, y=by, width=bw, height=bh, confidence=len(points) / max(len(edges), 1))
                        )

        return rectangles

    def _color_match(self, c1: typing.Tuple[int, ...], c2: typing.Tuple[int, ...], tolerance: int) -> bool:
        """颜色匹配"""
        return all(abs(a - b) <= tolerance for a, b in zip(c1[:3], c2[:3]))


class BasicBoxAnnotator:
    """框标注器"""

    def __init__(self, line_width: int = 2):
        self.line_width = line_width

    def annotate(self, image: "BasicImage", boxes: typing.List[BoundingBox]) -> "BasicImage":
        """在图像上绘制边界框（返回新图像）"""
        # 简化实现：返回原图像
        logger.debug("BasicBoxAnnotator: 标注 %s 个框（简化实现）", len(boxes))
        return image


class BasicVisualParser:
    """基础视觉解析器"""

    def __init__(self):
        self.detector = BasicUIDetector()
        self.annotator = BasicBoxAnnotator()
        logger.info("BasicVisualParser 初始化完成")

    def parse(self, image: "BasicImage") -> ParseResult:
        """解析图像中的 UI 元素"""
        start_time = time.time()

        elements: typing.List[UIElement] = []

        # 检测按钮（蓝色区域）
        blue_regions = self.detector.detect_color_regions(image, (37, 99, 235), tolerance=50)
        for bbox in blue_regions:
            elements.append(ButtonElement(bbox=bbox, text="button", is_clickable=True))

        # 检测输入框（白色区域）
        white_regions = self.detector.detect_color_regions(image, (255, 255, 255), tolerance=20)
        for bbox in white_regions:
            if bbox.width > 50 and bbox.height > 15:
                elements.append(InputElement(bbox=bbox, input_type="text"))

        # 检测矩形
        rectangles = self.detector.detect_rectangles(image)
        for bbox in rectangles:
            # 简单分类
            if bbox.width < 50 and bbox.height < 50:
                elements.append(IconElement(bbox=bbox))
            elif bbox.height < 30:
                elements.append(TextElement(bbox=bbox))

        elapsed = time.time() - start_time

        return ParseResult(elements=elements, image_width=image.width, image_height=image.height, parse_time=elapsed)

    def parse_from_base64(self, b64_str: str) -> ParseResult:
        """从 base64 解析"""
        image = BasicImage.from_base64(b64_str)
        if image is None:
            return ParseResult(metadata={"error": "无法解码图像"})
        return self.parse(image)


# 全局实例
_parser: typing.Optional[BasicVisualParser] = None


def get_basic_visual_parser() -> BasicVisualParser:
    """获取全局 BasicVisualParser 实例"""
    global _parser
    if _parser is None:
        _parser = BasicVisualParser()
    return _parser


def is_basic_vision_available() -> bool:
    """检查基础视觉理解功能是否可用"""
    return True  # 纯 Python 实现，始终可用


def get_visual_parser() -> BasicVisualParser:
    """获取视觉解析器（兼容接口）"""
    return get_basic_visual_parser()


def is_vision_available() -> bool:
    """检查视觉理解是否可用（兼容接口）"""
    return is_basic_vision_available()


def reset_basic_visual_parser() -> None:
    """重置（用于测试）"""
    global _parser
    _parser = None
