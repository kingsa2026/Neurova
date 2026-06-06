"""
Browser Manager - 浏览器自动化管理器

整合 Hermes Browser 的多后端浏览器自动化能力：
- 多后端支持（Playwright, Scrapling, Camofox）
- 混合路由（自动选择云端/本地）
- CDP WebSocket 监控
- 反检测浏览
- 对话框自动处理
- 快照压缩
"""

import asyncio
import base64
import json
import logging
import os
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 可选依赖
try:
    import playwright.async_api
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

try:
    import scrapling.fetchers
    HAS_SCRAPLING = True
except ImportError:
    HAS_SCRAPLING = False

try:
    import websockets
    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False


@dataclass
class BrowserResult:
    """浏览器操作结果"""
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None
    screenshot: Optional[str] = None  # base64
    url: Optional[str] = None
    title: Optional[str] = None
    duration_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "has_screenshot": self.screenshot is not None,
            "url": self.url,
            "title": self.title,
            "duration_ms": self.duration_ms,
        }


class DialogHandler:
    """对话框处理器"""
    
    def __init__(self, auto_accept: bool = True):
        self._auto_accept = auto_accept
        self._dialogs: List[Dict[str, Any]] = []

    async def handle_dialog(self, dialog: Any) -> None:
        """处理对话框"""
        dialog_info = {
            "type": getattr(dialog, "type", "unknown"),
            "message": getattr(dialog, "message", ""),
            "accepted": self._auto_accept,
            "timestamp": time.time(),
        }
        self._dialogs.append(dialog_info)
        
        if self._auto_accept:
            await dialog.accept()
        else:
            await dialog.dismiss()

    def get_dialogs(self) -> List[Dict[str, Any]]:
        return self._dialogs.copy()

    def clear_dialogs(self) -> None:
        self._dialogs.clear()


class BrowserSupervisor:
    """浏览器监控器（CDP WebSocket）"""
    
    def __init__(self, ws_url: str):
        self._ws_url = ws_url
        self._ws = None
        self._running = False
        self._next_msg_id = 0
        self._pending_responses: Dict[int, asyncio.Future] = {}

    async def connect(self) -> bool:
        if not HAS_WEBSOCKETS:
            logger.warning("websockets not available")
            return False
        
        try:
            self._ws = await websockets.connect(self._ws_url)
            self._running = True
            asyncio.create_task(self._event_loop())
            logger.info("Connected to CDP WebSocket: %s", self._ws_url)
            return True
        except Exception as e:
            logger.error("Failed to connect to CDP: %s", str(e))
            return False

    async def send(self, method: str, params: Optional[Dict[str, Any]] = None) -> Any:
        if not self._ws:
            raise RuntimeError("Not connected")
        
        msg_id = self._next_id()
        message = {"id": msg_id, "method": method, "params": params or {}}
        
        future = asyncio.get_event_loop().create_future()
        self._pending_responses[msg_id] = future
        
        await self._ws.send(json.dumps(message))
        
        try:
            return await asyncio.wait_for(future, timeout=30.0)
        except asyncio.TimeoutError:
            del self._pending_responses[msg_id]
            raise TimeoutError(f"CDP command timed out: {method}")

    async def _event_loop(self) -> None:
        try:
            async for message in self._ws:
                data = json.loads(message)
                if "id" in data:
                    msg_id = data["id"]
                    if msg_id in self._pending_responses:
                        future = self._pending_responses.pop(msg_id)
                        if not future.done():
                            if "error" in data:
                                future.set_exception(RuntimeError(data["error"].get("message", "Unknown")))
                            else:
                                future.set_result(data.get("result"))
        except Exception as e:
            logger.error("CDP event loop error: %s", str(e))
        finally:
            self._running = False

    def _next_id(self) -> int:
        self._next_msg_id += 1
        return self._next_msg_id

    def _compress_snapshot(self, snapshot: str, max_length: int = 10000) -> str:
        if len(snapshot) <= max_length:
            return snapshot
        return snapshot[:max_length] + "... [truncated]"

    async def disconnect(self) -> None:
        self._running = False
        if self._ws:
            await self._ws.close()
            self._ws = None


class CamofoxAdapter:
    """Camofox 反检测浏览器适配器"""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self._config = config or {}
        self._port = self._config.get("port", 9222)

    async def navigate(self, url: str) -> BrowserResult:
        start_time = time.time()
        try:
            # Camofox 通过 CDP 连接
            supervisor = BrowserSupervisor(f"ws://localhost:{self._port}")
            if await supervisor.connect():
                await supervisor.send("Page.navigate", {"url": url})
                await supervisor.disconnect()
                return BrowserResult(success=True, url=url, duration_ms=(time.time() - start_time) * 1000)
            return BrowserResult(success=False, error="Failed to connect to Camofox", duration_ms=(time.time() - start_time) * 1000)
        except Exception as e:
            return BrowserResult(success=False, error=str(e), duration_ms=(time.time() - start_time) * 1000)

    async def screenshot(self) -> BrowserResult:
        start_time = time.time()
        try:
            supervisor = BrowserSupervisor(f"ws://localhost:{self._port}")
            if await supervisor.connect():
                result = await supervisor.send("Page.captureScreenshot", {"format": "png"})
                await supervisor.disconnect()
                return BrowserResult(success=True, screenshot=result.get("data") if result else None, duration_ms=(time.time() - start_time) * 1000)
            return BrowserResult(success=False, error="Failed to connect", duration_ms=(time.time() - start_time) * 1000)
        except Exception as e:
            return BrowserResult(success=False, error=str(e), duration_ms=(time.time() - start_time) * 1000)

    async def extract_text(self) -> BrowserResult:
        start_time = time.time()
        try:
            supervisor = BrowserSupervisor(f"ws://localhost:{self._port}")
            if await supervisor.connect():
                result = await supervisor.send("Runtime.evaluate", {"expression": "document.body.innerText"})
                await supervisor.disconnect()
                return BrowserResult(success=True, data=result.get("result", {}).get("value") if result else None, duration_ms=(time.time() - start_time) * 1000)
            return BrowserResult(success=False, error="Failed to connect", duration_ms=(time.time() - start_time) * 1000)
        except Exception as e:
            return BrowserResult(success=False, error=str(e), duration_ms=(time.time() - start_time) * 1000)

    async def close(self) -> None:
        pass


class ScraplingSpiderTool:
    """Scrapling 爬虫工具"""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self._config = config or {}
        self._spiders: Dict[str, Any] = {}

    def create_spider(self, name: str, start_urls: List[str], **kwargs) -> str:
        if not HAS_SCRAPLING:
            raise RuntimeError("Scrapling not available")
        
        spider_id = f"spider_{name}_{int(time.time())}"
        self._spiders[spider_id] = {"name": name, "start_urls": start_urls, "status": "created", **kwargs}
        return spider_id

    async def run_spider(self, spider_id: str) -> BrowserResult:
        start_time = time.time()
        if spider_id not in self._spiders:
            return BrowserResult(success=False, error=f"Spider not found: {spider_id}")
        
        spider = self._spiders[spider_id]
        spider["status"] = "running"
        
        try:
            results = []
            for url in spider["start_urls"]:
                try:
                    page = scrapling.fetchers.Fetcher().get(url)
                    results.append({"url": url, "text": page.text[:1000] if page.text else ""})
                except Exception as e:
                    results.append({"url": url, "error": str(e)})
            
            spider["status"] = "completed"
            return BrowserResult(success=True, data=results, duration_ms=(time.time() - start_time) * 1000)
        except Exception as e:
            spider["status"] = "failed"
            return BrowserResult(success=False, error=str(e), duration_ms=(time.time() - start_time) * 1000)

    def stop_spider(self, spider_id: str) -> bool:
        if spider_id in self._spiders:
            self._spiders[spider_id]["status"] = "stopped"
            return True
        return False

    def resume_spider(self, spider_id: str) -> bool:
        if spider_id in self._spiders and self._spiders[spider_id]["status"] == "stopped":
            self._spiders[spider_id]["status"] = "running"
            return True
        return False


class BrowserBackend(ABC):
    """浏览器后端基类"""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self._config = config or {}
        self._initialized = False

    @abstractmethod
    async def initialize(self) -> bool:
        pass

    @abstractmethod
    async def navigate(self, url: str) -> BrowserResult:
        pass

    @abstractmethod
    async def screenshot(self) -> BrowserResult:
        pass

    @abstractmethod
    async def click(self, selector: str) -> BrowserResult:
        pass

    @abstractmethod
    async def type_text(self, selector: str, text: str) -> BrowserResult:
        pass

    @abstractmethod
    async def extract_text(self) -> BrowserResult:
        pass

    @abstractmethod
    async def extract_links(self) -> BrowserResult:
        pass

    @abstractmethod
    async def execute_js(self, script: str) -> BrowserResult:
        pass

    @abstractmethod
    async def snapshot(self) -> BrowserResult:
        pass

    @abstractmethod
    async def close(self) -> None:
        pass


class PlaywrightBackend(BrowserBackend):
    """Playwright 浏览器后端"""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._browser = None
        self._context = None
        self._page = None
        self._headless = config.get("headless", True) if config else True

    async def initialize(self) -> bool:
        if not HAS_PLAYWRIGHT:
            logger.warning("Playwright not available")
            return False
        try:
            from playwright.async_api import async_playwright
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=self._headless)
            self._context = await self._browser.new_context()
            self._page = await self._context.new_page()
            self._initialized = True
            return True
        except Exception as e:
            logger.error("Failed to initialize Playwright: %s", str(e))
            return False

    async def navigate(self, url: str) -> BrowserResult:
        start_time = time.time()
        try:
            if not self._page:
                raise RuntimeError("Not initialized")
            await self._page.goto(url, wait_until="networkidle")
            return BrowserResult(success=True, url=url, title=await self._page.title(), duration_ms=(time.time() - start_time) * 1000)
        except Exception as e:
            return BrowserResult(success=False, error=str(e), duration_ms=(time.time() - start_time) * 1000)

    async def screenshot(self) -> BrowserResult:
        start_time = time.time()
        try:
            if not self._page:
                raise RuntimeError("Not initialized")
            screenshot_bytes = await self._page.screenshot()
            return BrowserResult(success=True, screenshot=base64.b64encode(screenshot_bytes).decode(), url=self._page.url, title=await self._page.title(), duration_ms=(time.time() - start_time) * 1000)
        except Exception as e:
            return BrowserResult(success=False, error=str(e), duration_ms=(time.time() - start_time) * 1000)

    async def click(self, selector: str) -> BrowserResult:
        start_time = time.time()
        try:
            if not self._page:
                raise RuntimeError("Not initialized")
            await self._page.click(selector)
            return BrowserResult(success=True, url=self._page.url, title=await self._page.title(), duration_ms=(time.time() - start_time) * 1000)
        except Exception as e:
            return BrowserResult(success=False, error=str(e), duration_ms=(time.time() - start_time) * 1000)

    async def type_text(self, selector: str, text: str) -> BrowserResult:
        start_time = time.time()
        try:
            if not self._page:
                raise RuntimeError("Not initialized")
            await self._page.fill(selector, text)
            return BrowserResult(success=True, url=self._page.url, title=await self._page.title(), duration_ms=(time.time() - start_time) * 1000)
        except Exception as e:
            return BrowserResult(success=False, error=str(e), duration_ms=(time.time() - start_time) * 1000)

    async def extract_text(self) -> BrowserResult:
        start_time = time.time()
        try:
            if not self._page:
                raise RuntimeError("Not initialized")
            text = await self._page.evaluate("() => document.body.innerText")
            return BrowserResult(success=True, data=text, url=self._page.url, title=await self._page.title(), duration_ms=(time.time() - start_time) * 1000)
        except Exception as e:
            return BrowserResult(success=False, error=str(e), duration_ms=(time.time() - start_time) * 1000)

    async def extract_links(self) -> BrowserResult:
        start_time = time.time()
        try:
            if not self._page:
                raise RuntimeError("Not initialized")
            links = await self._page.evaluate("""
                () => Array.from(document.querySelectorAll('a[href]')).map(a => ({text: a.innerText, href: a.href}))
            """)
            return BrowserResult(success=True, data=links, url=self._page.url, title=await self._page.title(), duration_ms=(time.time() - start_time) * 1000)
        except Exception as e:
            return BrowserResult(success=False, error=str(e), duration_ms=(time.time() - start_time) * 1000)

    async def execute_js(self, script: str) -> BrowserResult:
        start_time = time.time()
        try:
            if not self._page:
                raise RuntimeError("Not initialized")
            result = await self._page.evaluate(script)
            return BrowserResult(success=True, data=result, url=self._page.url, title=await self._page.title(), duration_ms=(time.time() - start_time) * 1000)
        except Exception as e:
            return BrowserResult(success=False, error=str(e), duration_ms=(time.time() - start_time) * 1000)

    async def snapshot(self) -> BrowserResult:
        start_time = time.time()
        try:
            if not self._page:
                raise RuntimeError("Not initialized")
            content = await self._page.content()
            return BrowserResult(success=True, data=content[:10000] + "..." if len(content) > 10000 else content, url=self._page.url, title=await self._page.title(), duration_ms=(time.time() - start_time) * 1000)
        except Exception as e:
            return BrowserResult(success=False, error=str(e), duration_ms=(time.time() - start_time) * 1000)

    async def close(self) -> None:
        try:
            if self._page:
                await self._page.close()
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
            if hasattr(self, '_playwright'):
                await self._playwright.stop()
        except Exception as e:
            logger.error("Error closing Playwright: %s", str(e))


class ScraplingBackend(BrowserBackend):
    """Scrapling 浏览器后端"""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._fetcher = None
        self._current_page = None

    async def initialize(self) -> bool:
        if not HAS_SCRAPLING:
            logger.warning("Scrapling not available")
            return False
        try:
            self._fetcher = scrapling.fetchers.Fetcher()
            self._initialized = True
            return True
        except Exception as e:
            logger.error("Failed to initialize Scrapling: %s", str(e))
            return False

    async def navigate(self, url: str) -> BrowserResult:
        start_time = time.time()
        try:
            if not self._fetcher:
                raise RuntimeError("Not initialized")
            self._current_page = self._fetcher.get(url)
            return BrowserResult(success=True, url=url, title=getattr(self._current_page, 'title', ''), duration_ms=(time.time() - start_time) * 1000)
        except Exception as e:
            return BrowserResult(success=False, error=str(e), duration_ms=(time.time() - start_time) * 1000)

    async def screenshot(self) -> BrowserResult:
        return BrowserResult(success=False, error="Scrapling does not support screenshots")

    async def click(self, selector: str) -> BrowserResult:
        return BrowserResult(success=False, error="Scrapling does not support click")

    async def type_text(self, selector: str, text: str) -> BrowserResult:
        return BrowserResult(success=False, error="Scrapling does not support type_text")

    async def extract_text(self) -> BrowserResult:
        start_time = time.time()
        try:
            if not self._current_page:
                raise RuntimeError("No page loaded")
            return BrowserResult(success=True, data=getattr(self._current_page, 'text', ''), duration_ms=(time.time() - start_time) * 1000)
        except Exception as e:
            return BrowserResult(success=False, error=str(e), duration_ms=(time.time() - start_time) * 1000)

    async def extract_links(self) -> BrowserResult:
        start_time = time.time()
        try:
            if not self._current_page:
                raise RuntimeError("No page loaded")
            links = [{"text": getattr(link, 'text', ''), "href": getattr(link, 'url', '')} for link in getattr(self._current_page, 'links', [])]
            return BrowserResult(success=True, data=links, duration_ms=(time.time() - start_time) * 1000)
        except Exception as e:
            return BrowserResult(success=False, error=str(e), duration_ms=(time.time() - start_time) * 1000)

    async def execute_js(self, script: str) -> BrowserResult:
        return BrowserResult(success=False, error="Scrapling does not support JavaScript")

    async def snapshot(self) -> BrowserResult:
        return await self.extract_text()

    async def close(self) -> None:
        self._fetcher = None
        self._current_page = None


class BrowserManager:
    """浏览器管理器"""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self._config = config or {}
        self._backends: Dict[str, BrowserBackend] = {}
        self._active_backend: Optional[BrowserBackend] = None
        self._spider_tool = ScraplingSpiderTool(config)
        self._dialog_handler = DialogHandler()
        self._lock = threading.RLock()
        self._load_config()
        logger.info("BrowserManager initialized")

    def _load_config(self) -> None:
        """加载配置"""
        # 自动检测可用后端
        if HAS_PLAYWRIGHT:
            self._backends["playwright"] = PlaywrightBackend(self._config)
        if HAS_SCRAPLING:
            self._backends["scrapling"] = ScraplingBackend(self._config)

    def _resolve_backend(self, preferred: Optional[str] = None) -> str:
        """解析要使用的后端"""
        if preferred and preferred in self._backends:
            return preferred
        # 默认优先级: playwright > scrapling
        if "playwright" in self._backends:
            return "playwright"
        if "scrapling" in self._backends:
            return "scrapling"
        raise RuntimeError("No browser backend available")

    async def _get_backend(self, backend_name: Optional[str] = None) -> BrowserBackend:
        """获取并初始化后端"""
        name = self._resolve_backend(backend_name)
        backend = self._backends[name]
        
        if not backend._initialized:
            success = await backend.initialize()
            if not success:
                raise RuntimeError(f"Failed to initialize backend: {name}")
        
        self._active_backend = backend
        return backend

    async def execute(self, action: str, **kwargs) -> BrowserResult:
        """执行浏览器动作"""
        backend = await self._get_backend()
        
        if action == "navigate":
            return await backend.navigate(kwargs.get("url", ""))
        elif action == "screenshot":
            return await backend.screenshot()
        elif action == "click":
            return await backend.click(kwargs.get("selector", ""))
        elif action == "type":
            return await backend.type_text(kwargs.get("selector", ""), kwargs.get("text", ""))
        elif action == "extract_text":
            return await backend.extract_text()
        elif action == "extract_links":
            return await backend.extract_links()
        elif action == "execute_js":
            return await backend.execute_js(kwargs.get("script", ""))
        elif action == "snapshot":
            return await backend.snapshot()
        else:
            return BrowserResult(success=False, error=f"Unknown action: {action}")

    async def navigate(self, url: str, backend: Optional[str] = None) -> BrowserResult:
        """导航到 URL"""
        b = await self._get_backend(backend)
        return await b.navigate(url)

    async def screenshot(self, backend: Optional[str] = None) -> BrowserResult:
        """截图"""
        b = await self._get_backend(backend)
        return await b.screenshot()

    async def click(self, selector: str, backend: Optional[str] = None) -> BrowserResult:
        """点击元素"""
        b = await self._get_backend(backend)
        return await b.click(selector)

    async def type_text(self, selector: str, text: str, backend: Optional[str] = None) -> BrowserResult:
        """输入文本"""
        b = await self._get_backend(backend)
        return await b.type_text(selector, text)

    async def extract_text(self, backend: Optional[str] = None) -> BrowserResult:
        """提取文本"""
        b = await self._get_backend(backend)
        return await b.extract_text()

    async def extract_links(self, backend: Optional[str] = None) -> BrowserResult:
        """提取链接"""
        b = await self._get_backend(backend)
        return await b.extract_links()

    async def execute_js(self, script: str, backend: Optional[str] = None) -> BrowserResult:
        """执行 JavaScript"""
        b = await self._get_backend(backend)
        return await b.execute_js(script)

    async def snapshot(self, backend: Optional[str] = None) -> BrowserResult:
        """获取快照"""
        b = await self._get_backend(backend)
        return await b.snapshot()

    async def scrape(self, urls: List[str]) -> BrowserResult:
        """爬取多个 URL"""
        start_time = time.time()
        try:
            results = []
            for url in urls:
                result = await self.navigate(url)
                if result.success:
                    text_result = await self.extract_text()
                    results.append({"url": url, "text": text_result.data if text_result.success else ""})
                else:
                    results.append({"url": url, "error": result.error})
            
            return BrowserResult(success=True, data=results, duration_ms=(time.time() - start_time) * 1000)
        except Exception as e:
            return BrowserResult(success=False, error=str(e), duration_ms=(time.time() - start_time) * 1000)

    async def close_all(self) -> None:
        """关闭所有后端"""
        for backend in self._backends.values():
            try:
                await backend.close()
            except Exception as e:
                logger.error("Error closing backend: %s", str(e))
        self._active_backend = None

    def get_status(self) -> Dict[str, Any]:
        """获取状态"""
        return {
            "available_backends": list(self._backends.keys()),
            "active_backend": self._active_backend.__class__.__name__ if self._active_backend else None,
            "has_playwright": HAS_PLAYWRIGHT,
            "has_scrapling": HAS_SCRAPLING,
            "has_websockets": HAS_WEBSOCKETS,
        }


# 全局单例
_manager_instance: Optional[BrowserManager] = None
_manager_lock = threading.Lock()


def get_browser_manager(config: Optional[Dict[str, Any]] = None) -> BrowserManager:
    """获取全局 BrowserManager 实例"""
    global _manager_instance
    if _manager_instance is None:
        with _manager_lock:
            if _manager_instance is None:
                _manager_instance = BrowserManager(config=config)
    return _manager_instance


def reset_browser_manager() -> None:
    """重置全局 BrowserManager 实例（用于测试）"""
    global _manager_instance
    with _manager_lock:
        _manager_instance = None
