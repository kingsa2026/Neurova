"""computer 动作实现层（CUA 升级方案 R1-2 伴生提取）

把 tool_executor 中 computer_* 动作的实现体抽为可独立调用的纯函数：
- 宿主侧 LLM 工具执行体（tool_executor）与本模块共用同一份实现
- 未来来宾守护进程（远程会话平面 RS-2 的 neurova-guest-agent）复用同一契约，
  保证 guest 端与宿主端的动作语义/结果结构一字不差

约定：
- 函数全部为同步阻塞（pyautogui/UIA），调用方负责放线程池（asyncio.to_thread）
- 返回统一的 LLM 面向结果 dict（success/error 结构）；动作确认档
  （action_result）与刷新截图标记由调用方按通道策略附加
"""

from typing import Any, Dict, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)


def click_screenshot_point(manager: Any, x: Any, y: Any, button: str = "left") -> Dict:
    """截图像素坐标点击（R0-2 坐标链：内部换算 DPI/多屏后落 pyautogui）"""
    if x is None or y is None:
        return {"error": "缺少必要的坐标参数 x, y"}
    success = manager.click_screenshot_point(x, y, button)
    if success:
        return {"success": True, "x": x, "y": y, "button": button}
    return {"error": "点击操作失败", "x": x, "y": y}


def type_text(manager: Any, text: Any, interval: float = 0.05) -> Dict:
    """键盘输入文本"""
    if not text:
        return {"error": "缺少输入文本"}
    success = manager.type_text(text, interval)
    if success:
        return {"success": True, "text": text, "length": len(text)}
    return {"error": "输入操作失败"}


def scroll(
    manager: Any,
    scroll_x: Any,
    scroll_y: Any,
    x: Optional[float] = None,
    y: Optional[float] = None,
) -> Dict:
    """屏幕滚动（方向语义经 scroll_semantics 单源：符号保留、水平轴消费）"""
    from neurova.computer_use import scroll_semantics

    vertical, horizontal = scroll_semantics(scroll_x, scroll_y)
    success = manager.scroll(x, y, vertical, horizontal)
    if success:
        return {
            "success": True,
            "scroll_x": scroll_x,
            "scroll_y": scroll_y,
            "vertical_clicks": vertical,
            "horizontal_clicks": horizontal,
        }
    return {"error": "滚动操作失败（需要 pyautogui）"}


def screenshot_bytes(manager: Any, region=None) -> Optional[bytes]:
    """截图原始 PNG 字节（None=无可用后端）"""
    return manager.screenshot(region)
