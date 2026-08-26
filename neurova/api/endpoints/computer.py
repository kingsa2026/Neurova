"""
Computer Use API 端点 v2.0.0 - 浏览器自动化增强版

隔离层级: 全局共享 + L1/L2 防火墙
"""

import asyncio
from neurova.core.logger import get_logger
import typing

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = get_logger(__name__)
router = APIRouter()


# ── Models ─────────────────────────────────────────────


class ScreenshotRequest(BaseModel):
    region: typing.Optional[typing.List[int]] = None  # [x, y, w, h]
    format: str = "png"


class ClickRequest(BaseModel):
    x: int
    y: int
    button: str = "left"
    clicks: int = 1


class TypeRequest(BaseModel):
    text: str
    interval: float = 0.02


class ScrollRequest(BaseModel):
    x: int = 0
    y: int = 0
    dx: int = 0
    dy: int = -3


class ShellRequest(BaseModel):
    command: str
    timeout: int = 30


class FileReadRequest(BaseModel):
    path: str
    encoding: str = "utf-8"


class FileWriteRequest(BaseModel):
    path: str
    content: str
    encoding: str = "utf-8"


class VisualParseRequest(BaseModel):
    screenshot: typing.Optional[str] = None  # base64
    detect_elements: bool = True


class SmartClickRequest(BaseModel):
    target: str  # e.g. "登录按钮"
    screenshot: typing.Optional[str] = None


class SmartTypeRequest(BaseModel):
    target: str  # e.g. "用户名输入框"
    text: str
    screenshot: typing.Optional[str] = None


class BrowserNavigateRequest(BaseModel):
    url: str
    wait_until: str = "domcontentloaded"


class BrowserScreenshotRequest(BaseModel):
    full_page: bool = False


class BrowserClickRequest(BaseModel):
    selector: typing.Optional[str] = None
    text: typing.Optional[str] = None


class BrowserTypeRequest(BaseModel):
    selector: str
    text: str


class BrowserExtractTextRequest(BaseModel):
    selector: typing.Optional[str] = None


class BrowserExtractLinksRequest(BaseModel):
    selector: typing.Optional[str] = None


class BrowserExecuteJsRequest(BaseModel):
    script: str


class BrowserSnapshotRequest(BaseModel):
    pass


class BrowserScrapeRequest(BaseModel):
    url: str
    selectors: typing.Optional[dict] = None


# ── In-memory state ────────────────────────────────────

_browser_state = {"url": None, "history": []}
_action_log: typing.List[dict] = []


def _log_action(action: str, detail: dict):
    import datetime

    _action_log.append({"action": action, "detail": detail, "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()})
    if len(_action_log) > 1000:
        _action_log.pop(0)


# ── Desktop endpoints ──────────────────────────────────


def _get_manager():
    """获取 ComputerUseManager（真实桌面/浏览器能力）"""
    from neurova.computer_use import get_computer_use_manager

    return get_computer_use_manager()


def _normalize_browser_result(result) -> dict:
    """BrowserResult(dataclass)/dict/None → 紧凑 dict"""
    if isinstance(result, dict):
        return result
    if result is None:
        return {"success": False, "error": "浏览器管理器不可用"}
    to_dict = getattr(result, "to_dict", None)
    if callable(to_dict):
        return dict(to_dict())
    return {"success": False, "error": "浏览器返回格式未知"}


@router.post("/screenshot")
async def screenshot(body: ScreenshotRequest):
    """获取桌面截图（真实实现：PIL ImageGrab 后端）"""
    import base64

    _log_action("screenshot", {"region": body.region})
    region = tuple(body.region) if body.region else None
    data = await asyncio.to_thread(_get_manager().screenshot, region)
    if not data:
        raise HTTPException(status_code=503, detail="截图失败：无可用后端（需要 PIL/Pillow）")
    return {
        "code": 0,
        "message": "Screenshot captured",
        "data": {"format": body.format, "base64": base64.b64encode(data).decode("utf-8")},
    }


@router.post("/click")
async def click(body: ClickRequest):
    """鼠标点击操作（真实实现：pyautogui）"""
    _log_action("click", {"x": body.x, "y": body.y, "button": body.button})
    ok = await asyncio.to_thread(_get_manager().click, int(body.x), int(body.y), body.button)
    if not ok:
        raise HTTPException(status_code=503, detail="点击失败：需要 pyautogui")
    return {
        "code": 0,
        "message": f"Clicked ({body.x}, {body.y})",
        "data": {"success": True, "x": body.x, "y": body.y, "button": body.button},
    }


@router.post("/type")
async def type_text(body: TypeRequest):
    """键盘输入操作（真实实现：pyautogui）"""
    _log_action("type", {"length": len(body.text)})
    ok = await asyncio.to_thread(_get_manager().type_text, body.text, body.interval)
    if not ok:
        raise HTTPException(status_code=503, detail="输入失败：需要 pyautogui")
    return {"code": 0, "message": f"Typed {len(body.text)} characters", "data": {"success": True, "length": len(body.text)}}


@router.post("/scroll")
async def scroll(body: ScrollRequest):
    """滚轮操作（真实实现：pyautogui）"""
    _log_action("scroll", {"dx": body.dx, "dy": body.dy})
    # dy 负值向下、正值向上，与前端 direction/amount 语义换算
    clicks = abs(int(body.dy)) or 3
    ok = await asyncio.to_thread(_get_manager().scroll, None, None, clicks)
    if not ok:
        raise HTTPException(status_code=503, detail="滚动失败：需要 pyautogui")
    return {"code": 0, "message": "Scrolled", "data": {"success": True, "dx": body.dx, "dy": body.dy}}


@router.post("/shell")
async def shell(body: ShellRequest):
    """执行 Shell 命令"""
    try:
        proc = await asyncio.create_subprocess_shell(
            body.command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=body.timeout)
        _log_action("shell", {"command": body.command[:100], "returncode": proc.returncode})
        return {
            "code": 0,
            "message": "Command executed",
            "data": {
                "stdout": stdout.decode(errors="replace"),
                "stderr": stderr.decode(errors="replace"),
                "returncode": proc.returncode,
            },
        }
    except asyncio.TimeoutError:
        raise HTTPException(status_code=408, detail="Command timed out")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/file/read")
async def file_read(body: FileReadRequest):
    """读取文件"""
    try:
        from pathlib import Path

        p = Path(body.path)
        if not p.exists():
            raise HTTPException(status_code=404, detail=f"File not found: {body.path}")
        content = p.read_text(encoding=body.encoding)
        _log_action("file_read", {"path": body.path, "size": len(content)})
        return {"code": 0, "message": "File read", "data": {"content": content, "size": len(content)}}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/file/write")
async def file_write(body: FileWriteRequest):
    """写入文件"""
    try:
        from pathlib import Path

        p = Path(body.path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body.content, encoding=body.encoding)
        _log_action("file_write", {"path": body.path, "size": len(body.content)})
        return {"code": 0, "message": "File written", "data": {"path": body.path, "size": len(body.content)}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/visual-parse")
async def visual_parse(body: VisualParseRequest):
    """视觉解析：截图 + UI 元素检测"""
    _log_action("visual_parse", {"detect_elements": body.detect_elements})
    return {
        "code": 0,
        "message": "Visual parse (placeholder)",
        "data": {"elements": [], "screenshot": body.screenshot or ""},
    }


@router.post("/smart-click")
async def smart_click(body: SmartClickRequest):
    """智能点击：基于语义目标"""
    _log_action("smart_click", {"target": body.target})
    return {
        "code": 0,
        "message": f"Smart click on '{body.target}' (placeholder)",
        "data": {"target": body.target, "found": False},
    }


@router.post("/smart-type")
async def smart_type(body: SmartTypeRequest):
    """智能输入：基于语义目标"""
    _log_action("smart_type", {"target": body.target, "text_len": len(body.text)})
    return {
        "code": 0,
        "message": f"Smart type into '{body.target}' (placeholder)",
        "data": {"target": body.target, "found": False},
    }


@router.get("/status")
async def get_status():
    """查询 Computer Use 服务状态（真实探测桌面/浏览器后端可用性）"""
    desktop_available = False
    browser_backends: typing.List[str] = []
    try:
        manager = _get_manager()
        desktop_available = getattr(manager, "_screenshot_backend", "basic") != "basic"
    except Exception as e:
        logger.warning("探测桌面能力失败: %s", e)
    try:
        from neurova.computer_use.browser_manager import get_browser_manager

        browser_backends = list(get_browser_manager().get_status().get("available_backends", []))
    except Exception as e:
        logger.warning("探测浏览器后端失败: %s", e)

    return {
        "code": 0,
        "message": "success",
        "data": {
            "desktop_available": desktop_available,
            "browser_available": bool(browser_backends),
            "browser_backends": browser_backends,
            "vision_available": False,
            "actions_logged": len(_action_log),
            "browser_url": _browser_state.get("url"),
        },
    }


# ── Browser endpoints ──────────────────────────────────


@router.post("/browser/navigate")
async def browser_navigate(body: BrowserNavigateRequest):
    """浏览器导航（真实实现：BrowserManager 多后端）"""
    result = await _get_manager().browser_navigate(body.url)
    normalized = _normalize_browser_result(result)
    if not normalized.get("success"):
        raise HTTPException(status_code=502, detail=normalized.get("error") or "导航失败：无可用浏览器后端")
    _browser_state["url"] = body.url
    _browser_state["history"].append(body.url)
    _log_action("browser_navigate", {"url": body.url})
    return {"code": 0, "message": f"Navigated to {body.url}", "data": normalized}


@router.post("/browser/screenshot")
async def browser_screenshot(body: BrowserScreenshotRequest):
    """浏览器截图（真实实现）"""
    _log_action("browser_screenshot", {"full_page": body.full_page})
    raw = await _get_manager().browser_screenshot()
    shot = getattr(raw, "screenshot", None)  # BrowserResult 携带 base64
    if not shot:
        raise HTTPException(status_code=503, detail="截图失败：无可用浏览器后端")
    return {
        "code": 0,
        "message": "Browser screenshot captured",
        "data": {"base64": shot, "url": getattr(raw, "url", None) or _browser_state.get("url")},
    }


@router.post("/browser/click")
async def browser_click(body: BrowserClickRequest):
    """浏览器点击（selector 或可见文本）"""
    target = body.selector or (f"text={body.text}" if body.text else "")
    if not target:
        raise HTTPException(status_code=422, detail="缺少 selector 或 text 参数")
    raw = await _get_manager().browser_click(target)
    normalized = _normalize_browser_result(raw)
    _log_action("browser_click", {"target": target, "success": normalized.get("success")})
    return {"code": 0, "message": "Browser click executed", "data": normalized}


@router.post("/browser/type")
async def browser_type(body: BrowserTypeRequest):
    """浏览器输入（真实实现）"""
    raw = await _get_manager().browser_type(body.selector, body.text)
    normalized = _normalize_browser_result(raw)
    _log_action("browser_type", {"selector": body.selector})
    return {"code": 0, "message": "Typed into element", "data": normalized}


@router.post("/browser/extract-text")
async def browser_extract_text(body: BrowserExtractTextRequest):
    """浏览器提取文本（真实实现）"""
    raw = await _get_manager().browser_extract_text()
    normalized = _normalize_browser_result(raw)
    data = normalized.get("data")
    if isinstance(data, str) and len(data) > 20000:
        normalized["data"] = data[:20000] + "…[已截断]"
        normalized["truncated"] = True
    _log_action("browser_extract_text", {"selector": body.selector, "size": len(str(data or ""))})
    return {"code": 0, "message": "Text extracted", "data": {"text": normalized.get("data", ""), "url": normalized.get("url")}}


@router.post("/browser/extract")
async def browser_extract_alias(body: BrowserExtractTextRequest):
    """浏览器提取内容（/browser/extract-text 的别名，兼容前端 extractPage 调用）"""
    return await browser_extract_text(body)


@router.post("/browser/extract-links")
async def browser_extract_links(body: BrowserExtractLinksRequest):
    """浏览器提取链接"""
    _log_action("browser_extract_links", {"selector": body.selector})
    return {"code": 0, "message": "Links extracted (placeholder)", "data": {"links": [], "selector": body.selector}}


@router.post("/browser/execute-js")
async def browser_execute_js(body: BrowserExecuteJsRequest):
    """浏览器执行 JavaScript"""
    _log_action("browser_execute_js", {"script_len": len(body.script)})
    return {
        "code": 0,
        "message": "JS executed (placeholder)",
        "data": {"result": None, "script_length": len(body.script)},
    }


@router.post("/browser/snapshot")
async def browser_snapshot(body: BrowserSnapshotRequest):
    """浏览器获取 accessibility tree 快照"""
    _log_action("browser_snapshot", {})
    return {
        "code": 0,
        "message": "Snapshot captured (placeholder)",
        "data": {"tree": {}, "url": _browser_state.get("url")},
    }


@router.post("/browser/scrape")
async def browser_scrape(body: BrowserScrapeRequest):
    """浏览器抓取（支持自适应解析）"""
    _log_action("browser_scrape", {"url": body.url})
    return {"code": 0, "message": "Scrape complete (placeholder)", "data": {"url": body.url, "data": {}}}
