"""computer 动作实现层

把 tool_executor 中 computer_* 动作的实现体抽为可独立调用的纯函数：
- 宿主侧 LLM 工具执行体（tool_executor）与本模块共用同一份实现
- 未来来宾守护进程（远程会话平面 RS-2 的 neurova-guest-agent）复用同一契约，
  保证 guest 端与宿主端的动作语义/结果结构一字不差

约定：
- 函数全部为同步阻塞（pyautogui/UIA），调用方负责放线程池（asyncio.to_thread）
- 返回统一的 LLM 面向结果 dict（success/error 结构）；动作确认档
  （action_result）与刷新截图标记由调用方按通道策略附加

车道互斥（护栏三招之三，项 8）：本模块的前台输入注入族动作
（点击/输入/滚动/按键/粘贴/拖拽）执行前必须取得 **desktop 车道**；
浏览器动作持 **browser:<session> 车道**，两侧互斥（lane_mutex）。
车道被拒时返回结构化拒绝 dict（guardrail.code = lane_busy / lane_unknown），
不执行动作本体。
"""

from typing import Any, Dict, Optional

from neurova.core.logger import get_logger
from neurova.computer_use.lane_mutex import (
    DESKTOP_LANE,
    LaneRefusal,
    currentLaneScope,
    get_lane_mutex,
)

logger = get_logger(__name__)


def _holdDesktopLane(action: str):
    """取得 desktop 车道（护栏关闭时直通；被拒抛 LaneRefusal）。"""
    return get_lane_mutex().hold(
        DESKTOP_LANE, scope=currentLaneScope(), owner=str(action)
    )


def _laneRefusalResult(refusal: LaneRefusal) -> Dict:
    """车道拒绝 → 统一结构化结果（带原因码，供模型/前端判读）。"""
    logger.warning("桌面动作被车道拒绝（%s）：%s", refusal.code, refusal.message)
    return {
        "success": False,
        "error": refusal.message,
        "guardrail": {"code": refusal.code, "lane": refusal.lane},
    }


def click_screenshot_point(manager: Any, x: Any, y: Any, button: str = "left") -> Dict:
    """截图像素坐标点击（R0-2 坐标链：内部换算 DPI/多屏后落 pyautogui）"""
    if x is None or y is None:
        return {"error": "缺少必要的坐标参数 x, y"}
    from neurova.computer_use import evidence_frames as _ef

    evidenceOn = _ef.evidenceFramesEnabled()
    beforeBytes: Optional[bytes] = None
    try:
        with _holdDesktopLane("computer_click"):
            # T5 证据帧：开启档下在车道窗口内取动作前/后帧（拒绝路径无帧）
            beforeBytes = screenshot_bytes(manager) if evidenceOn else None
            success = manager.click_screenshot_point(x, y, button)
            afterBytes = screenshot_bytes(manager) if evidenceOn else None
    except LaneRefusal as refusal:
        return _laneRefusalResult(refusal)
    result: Dict = {}
    if success:
        result = {"success": True, "x": x, "y": y, "button": button}
    else:
        result = {"error": "点击操作失败", "x": x, "y": y}
    if evidenceOn:
        pair = _ef.buildEvidencePair(beforeBytes, afterBytes, (x, y))
        if pair is not None:
            _ef.storeEvidence(pair)
            _ef.attachToResult(result, pair)
    return result


def type_text(manager: Any, text: Any, interval: float = 0.05) -> Dict:
    """键盘输入文本（C5：超阈值长文本附 paste 引导，不拒绝执行）"""
    if not text:
        return {"error": "缺少输入文本"}
    try:
        with _holdDesktopLane("computer_type"):
            success = manager.type_text(text, interval)
    except LaneRefusal as refusal:
        return _laneRefusalResult(refusal)
    if success:
        result = {"success": True, "text": text, "length": len(text)}
        if len(text) > 200:
            # C5 长文本引导（M4 教训：逐字符敲长文本又慢又易错）
            result["suggest_paste"] = True
            result["suggest_paste_hint"] = (
                "长文本建议改用 computer_paste（写剪贴板+ctrl+v，快且不易错）；"
                "逐字符键入长文本耗时且容易丢字。"
            )
        return result
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
    try:
        with _holdDesktopLane("computer_scroll"):
            success = manager.scroll(x, y, vertical, horizontal)
    except LaneRefusal as refusal:
        return _laneRefusalResult(refusal)
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
    """截图原始 PNG 字节（None=无可用后端）。观察面不占前台车道。"""
    return manager.screenshot(region)


def press_key(manager: Any, key: Any, repeat: Any = 1, interval: Any = 0.05) -> Dict:
    """按键/组合键（P2-7；键名归一与键表校验在 manager 层单源）"""
    if not str(key or "").strip():
        return {"error": "缺少按键参数 key"}
    try:
        repeat_n = max(1, int(repeat or 1))
    except (TypeError, ValueError):
        repeat_n = 1
    try:
        interval_f = max(0.0, float(interval or 0.0))
    except (TypeError, ValueError):
        interval_f = 0.05
    try:
        with _holdDesktopLane("computer_key"):
            success = manager.press_key(str(key), repeat_n, interval_f)
    except LaneRefusal as refusal:
        return _laneRefusalResult(refusal)
    if success:
        return {"success": True, "key": key, "repeat": repeat_n}
    return {"error": f"按键失败或键名不支持: {key!r}（示例 enter / ctrl+s / alt+f4）"}


def paste_text(manager: Any, text: Any) -> Dict:
    """剪贴板写入 + ctrl+v 粘贴（P2-7；Windows 剪贴板通道）"""
    if not str(text or ""):
        return {"error": "缺少粘贴文本"}
    try:
        with _holdDesktopLane("computer_paste"):
            success = manager.paste_text(str(text))
    except LaneRefusal as refusal:
        return _laneRefusalResult(refusal)
    if success:
        return {"success": True, "text": text, "length": len(str(text))}
    return {"error": "粘贴失败（需要 Windows 剪贴板与 pyautogui，目标控件需已聚焦）"}


def drag(
    manager: Any,
    start_x: Any,
    start_y: Any,
    end_x: Any,
    end_y: Any,
    duration: Any = 0.5,
    button: str = "left",
) -> Dict:
    """按截图像素坐标拖拽（P2-7；DPI/多屏换算在 manager 坐标链）"""
    if start_x is None or start_y is None or end_x is None or end_y is None:
        return {"error": "缺少坐标参数 start_x/start_y/end_x/end_y"}
    try:
        duration_f = max(0.05, float(duration or 0.5))
    except (TypeError, ValueError):
        duration_f = 0.5
    from neurova.computer_use import evidence_frames as _ef

    evidenceOn = _ef.evidenceFramesEnabled()
    beforeBytes: Optional[bytes] = None
    try:
        with _holdDesktopLane("computer_drag"):
            # T5 证据帧：以拖拽终点为取证中心（落点才是结果位置）
            beforeBytes = screenshot_bytes(manager) if evidenceOn else None
            success = manager.drag(start_x, start_y, end_x, end_y, duration_f, button or "left")
            afterBytes = screenshot_bytes(manager) if evidenceOn else None
    except LaneRefusal as refusal:
        return _laneRefusalResult(refusal)
    if success:
        result = {
            "success": True,
            "start": [start_x, start_y],
            "end": [end_x, end_y],
            "button": button or "left",
        }
    else:
        result = {"error": "拖拽操作失败"}
    if evidenceOn:
        pair = _ef.buildEvidencePair(beforeBytes, afterBytes, (end_x, end_y))
        if pair is not None:
            _ef.storeEvidence(pair)
            _ef.attachToResult(result, pair)
    return result

