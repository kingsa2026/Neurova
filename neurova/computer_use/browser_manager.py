"""
Browser Manager - 浏览器自动化管理器

整合 Hermes Browser 的多后端浏览器自动化能力：
- 多后端支持（Playwright, Scrapling, camofox-browser）
- 混合路由（自动选择云端/本地）
- CDP WebSocket 监控
- 反检测浏览（camofox-browser 后端）
- 对话框自动处理
- 快照压缩
"""

import asyncio
import base64
import json
import os
from neurova.core.logger import get_logger
import threading
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = get_logger(__name__)

# 可选依赖
try:
    import playwright  # noqa: F401 - 仅探测可用性

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

try:
    import httpx  # noqa: F401 - 仅探测可用性

    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False


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
    generation: Optional[int] = None  # 操作时活动 tab 的代数（agent 回传用于新鲜度校验）

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "has_screenshot": self.screenshot is not None,
            "url": self.url,
            "title": self.title,
            "duration_ms": self.duration_ms,
        }
        if self.generation is not None:
            d["generation"] = self.generation
        return d


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

    # ── 可访问性快照 + role 定位（能力裁剪模式）──
    # 基类默认"不支持"降级：不支持的后端（Scrapling 等）无需改动即自动降级为
    # 错误结果而非抛异常；能力清单供调用方按后端选路（对标 unsupportedByDefaultIn）
    @property
    def capabilities(self) -> Dict[str, bool]:
        """后端能力清单，子类按实际支持覆盖"""
        return {"aria_snapshot": False, "role_locator": False, "pixel_screenshot": False}

    async def dom_snapshot(self) -> BrowserResult:
        return BrowserResult(success=False, error=f"{type(self).__name__} does not support aria snapshot")

    async def click_role(self, role: str, name: Optional[str] = None) -> BrowserResult:
        return BrowserResult(success=False, error=f"{type(self).__name__} does not support role-based click")

    async def fill_role(self, role: str, name: Optional[str] = None, text: str = "") -> BrowserResult:
        return BrowserResult(success=False, error=f"{type(self).__name__} does not support role-based fill")


class PlaywrightBackend(BrowserBackend):
    """Playwright 浏览器后端"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._browser = None
        self._context = None
        self._tabs: Dict[str, Dict[str, Any]] = {}
        self._active_target_id: Optional[str] = None
        self._headless = config.get("headless", True) if config else True

    @property
    def capabilities(self) -> Dict[str, bool]:
        return {"aria_snapshot": True, "role_locator": True, "pixel_screenshot": True}

    # ── Tab 级 target 代际管理（对标 ZCode browserGeneration）──
    # 每个 tab 持有自己的 generation，navigate 该 tab 时 +1；调用方携带过期
    # generation 操作会被拒绝（快照事实已失效），不携带则跳过校验（向后兼容）

    @property
    def _page(self):
        """活动 tab 的页面（兼容既有单页面方法的读取路径）"""
        tab = self._tabs.get(self._active_target_id) if self._active_target_id else None
        return tab["page"] if tab else None

    def _register_tab(self, page) -> Dict[str, Any]:
        target_id = f"tab_{uuid.uuid4().hex[:8]}"
        self._tabs[target_id] = {"page": page, "generation": 1}
        self._active_target_id = target_id
        return {"target_id": target_id, "generation": 1}

    def _check_active_generation(self, generation: Optional[int]) -> Optional[BrowserResult]:
        """校验调用方持有的 generation 是否仍是活动 tab 的当前值"""
        if generation is None:
            return None
        tab = self._tabs.get(self._active_target_id) if self._active_target_id else None
        if not tab:
            return BrowserResult(success=False, error="无活动浏览器 tab")
        if tab["generation"] != generation:
            return BrowserResult(
                success=False,
                error=(
                    f"target generation 过期（当前 {tab['generation']}，传入 {generation}）——"
                    "页面已变化，快照事实失效，请重新 dom_snapshot"
                ),
                data={"stale": True, "current_generation": tab["generation"]},
            )
        return None

    def _active_generation(self) -> Optional[int]:
        tab = self._tabs.get(self._active_target_id) if self._active_target_id else None
        return tab["generation"] if tab else None

    async def open_target(self, url: Optional[str] = None) -> BrowserResult:
        """新开 tab 并激活；给 url 时顺带导航"""
        start_time = time.time()
        try:
            if not self._context:
                raise RuntimeError("Not initialized")
            page = await self._context.new_page()
            info = self._register_tab(page)
            if url:
                await page.goto(url, wait_until="networkidle")
            return BrowserResult(
                success=True,
                data=info,
                url=getattr(page, "url", ""),
                title=await page.title(),
                duration_ms=(time.time() - start_time) * 1000,
                generation=info["generation"],
            )
        except Exception as e:
            return BrowserResult(success=False, error=str(e), duration_ms=(time.time() - start_time) * 1000)

    async def list_targets(self) -> BrowserResult:
        """列出全部 tab（含 generation 与活动标记）"""
        start_time = time.time()
        data = []
        for tid, tab in self._tabs.items():
            page = tab["page"]
            data.append(
                {
                    "target_id": tid,
                    "generation": tab["generation"],
                    "url": getattr(page, "url", ""),
                    "active": tid == self._active_target_id,
                }
            )
        return BrowserResult(success=True, data=data, duration_ms=(time.time() - start_time) * 1000)

    async def switch_target(self, target_id: str, generation: Optional[int] = None) -> BrowserResult:
        """切换活动 tab；携带过期 generation 时拒绝"""
        tab = self._tabs.get(target_id)
        if not tab:
            return BrowserResult(success=False, error=f"target 不存在: {target_id}")
        if generation is not None and tab["generation"] != generation:
            return BrowserResult(
                success=False,
                error=f"target generation 过期（当前 {tab['generation']}，传入 {generation}）——请重新 list_targets",
                data={"stale": True, "current_generation": tab["generation"]},
            )
        self._active_target_id = target_id
        return BrowserResult(success=True, url=getattr(tab["page"], "url", ""))

    async def close_target(self, target_id: str, generation: Optional[int] = None) -> BrowserResult:
        """关闭 tab；活动 tab 被关时回落到剩余第一个 tab"""
        tab = self._tabs.get(target_id)
        if not tab:
            return BrowserResult(success=False, error=f"target 不存在: {target_id}")
        if generation is not None and tab["generation"] != generation:
            return BrowserResult(
                success=False,
                error=f"target generation 过期（当前 {tab['generation']}，传入 {generation}）",
                data={"stale": True, "current_generation": tab["generation"]},
            )
        try:
            await tab["page"].close()
        except Exception as e:  # noqa: BLE001 - 关闭失败不阻碍移除登记
            logger.debug("关闭 tab 页面失败（忽略）: %s", e)
        del self._tabs[target_id]
        if self._active_target_id == target_id:
            self._active_target_id = next(iter(self._tabs), None)
        return BrowserResult(success=True)

    async def dom_snapshot(self, generation: Optional[int] = None) -> BrowserResult:
        """aria 可访问性树快照 —— 结构化观察，代替原始 HTML（省 token、可精确引用）"""
        start_time = time.time()
        stale = self._check_active_generation(generation)
        if stale:
            return stale
        try:
            if not self._page:
                raise RuntimeError("Not initialized")
            tree = await self._page.locator("html").aria_snapshot()
            return BrowserResult(
                success=True,
                data=tree,
                url=self._page.url,
                title=await self._page.title(),
                duration_ms=(time.time() - start_time) * 1000,
                generation=self._active_generation(),
            )
        except Exception as e:
            return BrowserResult(success=False, error=str(e), duration_ms=(time.time() - start_time) * 1000)

    async def click_role(self, role: str, name: Optional[str] = None, generation: Optional[int] = None) -> BrowserResult:
        """按 ARIA role + accessible name 定位点击（快照事实驱动，不猜 CSS 选择器）"""
        start_time = time.time()
        if not role or not str(role).strip():
            return BrowserResult(success=False, error="缺少 ARIA role（如 button/link/textbox）")
        stale = self._check_active_generation(generation)
        if stale:
            return stale
        try:
            if not self._page:
                raise RuntimeError("Not initialized")
            locator = self._page.get_by_role(str(role).strip(), **({"name": name} if name is not None else {}))
            await locator.click(timeout=10000)
            return BrowserResult(
                success=True,
                url=self._page.url,
                title=await self._page.title(),
                duration_ms=(time.time() - start_time) * 1000,
                generation=self._active_generation(),
            )
        except Exception as e:
            return BrowserResult(success=False, error=str(e), duration_ms=(time.time() - start_time) * 1000)

    async def fill_role(
        self, role: str, name: Optional[str] = None, text: str = "", generation: Optional[int] = None
    ) -> BrowserResult:
        """按 ARIA role + accessible name 定位输入框并填写（空串=清空）"""
        start_time = time.time()
        if not role or not str(role).strip():
            return BrowserResult(success=False, error="缺少 ARIA role（如 textbox/searchbox）")
        if text is None:
            return BrowserResult(success=False, error="缺少输入文本（空串表示清空）")
        stale = self._check_active_generation(generation)
        if stale:
            return stale
        try:
            if not self._page:
                raise RuntimeError("Not initialized")
            locator = self._page.get_by_role(str(role).strip(), **({"name": name} if name is not None else {}))
            await locator.fill(text, timeout=10000)
            return BrowserResult(
                success=True,
                url=self._page.url,
                title=await self._page.title(),
                duration_ms=(time.time() - start_time) * 1000,
                generation=self._active_generation(),
            )
        except Exception as e:
            return BrowserResult(success=False, error=str(e), duration_ms=(time.time() - start_time) * 1000)

    async def initialize(self) -> bool:
        if not HAS_PLAYWRIGHT:
            logger.warning("Playwright not available")
            return False
        try:
            from playwright.async_api import async_playwright

            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=self._headless)
            self._context = await self._browser.new_context()
            page = await self._context.new_page()
            self._register_tab(page)
            self._initialized = True
            return True
        except Exception as e:
            logger.error("Failed to initialize Playwright: %s", str(e))
            return False

    async def navigate(self, url: str, generation: Optional[int] = None) -> BrowserResult:
        start_time = time.time()
        stale = self._check_active_generation(generation)
        if stale:
            return stale
        try:
            if not self._page:
                raise RuntimeError("Not initialized")
            await self._page.goto(url, wait_until="networkidle")
            tab = self._tabs.get(self._active_target_id)
            if tab:
                # 导航使该 tab 既有快照事实全部失效 → 递增 generation
                tab["generation"] += 1
            return BrowserResult(
                success=True,
                url=url,
                title=await self._page.title(),
                duration_ms=(time.time() - start_time) * 1000,
                generation=self._active_generation(),
            )
        except Exception as e:
            return BrowserResult(success=False, error=str(e), duration_ms=(time.time() - start_time) * 1000)

    async def screenshot(self) -> BrowserResult:
        start_time = time.time()
        try:
            if not self._page:
                raise RuntimeError("Not initialized")
            screenshot_bytes = await self._page.screenshot()
            return BrowserResult(
                success=True,
                screenshot=base64.b64encode(screenshot_bytes).decode(),
                url=self._page.url,
                title=await self._page.title(),
                duration_ms=(time.time() - start_time) * 1000,
            )
        except Exception as e:
            return BrowserResult(success=False, error=str(e), duration_ms=(time.time() - start_time) * 1000)

    async def click(self, selector: str) -> BrowserResult:
        start_time = time.time()
        try:
            if not self._page:
                raise RuntimeError("Not initialized")
            await self._page.click(selector)
            return BrowserResult(
                success=True,
                url=self._page.url,
                title=await self._page.title(),
                duration_ms=(time.time() - start_time) * 1000,
            )
        except Exception as e:
            return BrowserResult(success=False, error=str(e), duration_ms=(time.time() - start_time) * 1000)

    async def type_text(self, selector: str, text: str) -> BrowserResult:
        start_time = time.time()
        try:
            if not self._page:
                raise RuntimeError("Not initialized")
            await self._page.fill(selector, text)
            return BrowserResult(
                success=True,
                url=self._page.url,
                title=await self._page.title(),
                duration_ms=(time.time() - start_time) * 1000,
            )
        except Exception as e:
            return BrowserResult(success=False, error=str(e), duration_ms=(time.time() - start_time) * 1000)

    async def extract_text(self) -> BrowserResult:
        start_time = time.time()
        try:
            if not self._page:
                raise RuntimeError("Not initialized")
            text = await self._page.evaluate("() => document.body.innerText")
            return BrowserResult(
                success=True,
                data=text,
                url=self._page.url,
                title=await self._page.title(),
                duration_ms=(time.time() - start_time) * 1000,
            )
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
            return BrowserResult(
                success=True,
                data=links,
                url=self._page.url,
                title=await self._page.title(),
                duration_ms=(time.time() - start_time) * 1000,
            )
        except Exception as e:
            return BrowserResult(success=False, error=str(e), duration_ms=(time.time() - start_time) * 1000)

    async def execute_js(self, script: str) -> BrowserResult:
        start_time = time.time()
        try:
            if not self._page:
                raise RuntimeError("Not initialized")
            result = await self._page.evaluate(script)
            return BrowserResult(
                success=True,
                data=result,
                url=self._page.url,
                title=await self._page.title(),
                duration_ms=(time.time() - start_time) * 1000,
            )
        except Exception as e:
            return BrowserResult(success=False, error=str(e), duration_ms=(time.time() - start_time) * 1000)

    async def snapshot(self) -> BrowserResult:
        start_time = time.time()
        try:
            if not self._page:
                raise RuntimeError("Not initialized")
            content = await self._page.content()
            return BrowserResult(
                success=True,
                data=content[:10000] + "..." if len(content) > 10000 else content,
                url=self._page.url,
                title=await self._page.title(),
                duration_ms=(time.time() - start_time) * 1000,
            )
        except Exception as e:
            return BrowserResult(success=False, error=str(e), duration_ms=(time.time() - start_time) * 1000)

    async def close(self) -> None:
        try:
            for tab in self._tabs.values():
                try:
                    await tab["page"].close()
                except Exception as e:  # noqa: BLE001 - 单 tab 关闭失败不阻碍整体收尾
                    logger.debug("关闭 tab 失败（忽略）: %s", e)
            self._tabs.clear()
            self._active_target_id = None
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
            if hasattr(self, "_playwright"):
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
            return BrowserResult(
                success=True,
                url=url,
                title=getattr(self._current_page, "title", ""),
                duration_ms=(time.time() - start_time) * 1000,
            )
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
            return BrowserResult(
                success=True,
                data=getattr(self._current_page, "text", ""),
                duration_ms=(time.time() - start_time) * 1000,
            )
        except Exception as e:
            return BrowserResult(success=False, error=str(e), duration_ms=(time.time() - start_time) * 1000)

    async def extract_links(self) -> BrowserResult:
        start_time = time.time()
        try:
            if not self._current_page:
                raise RuntimeError("No page loaded")
            links = [
                {"text": getattr(link, "text", ""), "href": getattr(link, "url", "")}
                for link in getattr(self._current_page, "links", [])
            ]
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
        self._user_camofox_backends: Dict[str, BrowserBackend] = {}  # 三层隔离:按 userId 池化
        self._camofox_enabled: bool = False  # 由 _load_config 设置
        self._active_backend: Optional[BrowserBackend] = None
        self._spider_tool = ScraplingSpiderTool(config)
        self._dialog_handler = DialogHandler()
        self._lock = threading.RLock()  # 池化场景下必须——保护 _user_camofox_backends
        self._load_config()
        logger.info("BrowserManager initialized")

    def _load_config(self) -> None:
        """加载配置"""
        # 自动检测可用后端
        if HAS_PLAYWRIGHT:
            self._backends["playwright"] = PlaywrightBackend(self._config)
        if HAS_SCRAPLING:
            self._backends["scrapling"] = ScraplingBackend(self._config)
        # camofox-browser 反检测后端:三层隔离——按 userId 池化,延迟到首次 get 时创建。
        # 不再直接注册到 _backends(否则所有 user 共享同一后端,_tabs 跨用户污染)。
        if HAS_HTTPX and (
            os.environ.get("NEUROVA_CAMOFOX_URL")
            or (self._config or {}).get("camofox", {}).get("enabled")
        ):
            self._camofox_enabled = True

    def _resolve_backend(self, preferred: Optional[str] = None) -> str:
        """解析要使用的后端"""
        if preferred and preferred in self._backends:
            return preferred
        # 默认优先级: playwright(通用) > camofox(反检测,按 user 池化) > scrapling(静态爬取)
        if "playwright" in self._backends:
            return "playwright"
        if self._camofox_enabled:
            return "camofox"
        if "scrapling" in self._backends:
            return "scrapling"
        raise RuntimeError("No browser backend available")

    async def _get_backend(self, backend_name: Optional[str] = None) -> BrowserBackend:
        """获取并初始化后端(camofox 按 user 池化,其它共享)"""
        name = self._resolve_backend(backend_name)
        with self._lock:
            if name == "camofox" and self._camofox_enabled:
                backend = self._get_or_create_user_camofox_backend()
            else:
                backend = self._backends.get(name)
                if backend is None:
                    raise RuntimeError(f"Browser backend not available: {name}")

        if not backend._initialized:
            success = await backend.initialize()
            if not success:
                raise RuntimeError(f"Failed to initialize backend: {name}")

        self._active_backend = backend
        return backend

    def _get_or_create_user_camofox_backend(self) -> BrowserBackend:
        """按当前请求 userId 池化 camofox 后端(必须持 _lock 调用)

        - 同 user:返回同一实例(_tabs / _active_target_id 共享)
        - 不同 user:返回不同实例(隔离 cookie / tab)
        - 无 userId 注入:回退到 "default" 实例
        """
        try:
            from neurova.core.identity_context import get_request_user_id

            user_id = get_request_user_id() or "default"
        except ImportError:
            user_id = "default"
        if user_id not in self._user_camofox_backends:
            from neurova.computer_use.camofox_server_backend import CamofoxServerBackend

            cfg = (self._config or {}).get("camofox") or {}
            self._user_camofox_backends[user_id] = CamofoxServerBackend(cfg, user_id=user_id)
        return self._user_camofox_backends[user_id]

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

    async def navigate(self, url: str, backend: Optional[str] = None, generation: Optional[int] = None) -> BrowserResult:
        """导航到 URL（导航使活动 tab 快照事实失效 → generation 递增）"""
        b = await self._get_backend(backend)
        return await b.navigate(url, generation)

    async def dom_snapshot(self, backend: Optional[str] = None, generation: Optional[int] = None) -> BrowserResult:
        """获取 aria 可访问性树快照（观察优先）"""
        b = await self._get_backend(backend)
        return await b.dom_snapshot(generation)

    async def click_role(
        self, role: str, name: Optional[str] = None, backend: Optional[str] = None, generation: Optional[int] = None
    ) -> BrowserResult:
        """按 ARIA role + name 定位点击"""
        b = await self._get_backend(backend)
        return await b.click_role(role, name, generation)

    async def fill_role(
        self,
        role: str,
        name: Optional[str] = None,
        text: str = "",
        backend: Optional[str] = None,
        generation: Optional[int] = None,
    ) -> BrowserResult:
        """按 ARIA role + name 定位输入"""
        b = await self._get_backend(backend)
        return await b.fill_role(role, name, text, generation)

    async def open_target(self, url: Optional[str] = None, backend: Optional[str] = None) -> BrowserResult:
        """新开 tab 并激活"""
        b = await self._get_backend(backend)
        return await b.open_target(url)

    async def list_targets(self, backend: Optional[str] = None) -> BrowserResult:
        """列出全部 tab（含 generation 与活动标记）"""
        b = await self._get_backend(backend)
        return await b.list_targets()

    async def switch_target(
        self, target_id: str, generation: Optional[int] = None, backend: Optional[str] = None
    ) -> BrowserResult:
        """切换活动 tab"""
        b = await self._get_backend(backend)
        return await b.switch_target(target_id, generation)

    async def close_target(
        self, target_id: str, generation: Optional[int] = None, backend: Optional[str] = None
    ) -> BrowserResult:
        """关闭 tab"""
        b = await self._get_backend(backend)
        return await b.close_target(target_id, generation)

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

    async def get_capabilities(self, backend: Optional[str] = None) -> Dict[str, Any]:
        """查询当前后端能力清单（agent 据此选观察/交互方式）"""
        b = await self._get_backend(backend)
        return {"backend": b.__class__.__name__, "capabilities": dict(b.capabilities)}

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
        """关闭所有后端(共享后端 + 池化的 camofox 后端)"""
        for backend in self._backends.values():
            try:
                await backend.close()
            except Exception as e:
                logger.error("Error closing backend: %s", str(e))
        for backend in self._user_camofox_backends.values():
            try:
                await backend.close()
            except Exception as e:
                logger.error("Error closing user camofox backend: %s", str(e))
        self._user_camofox_backends.clear()
        self._active_backend = None

    def get_status(self) -> Dict[str, Any]:
        """获取状态"""
        return {
            "available_backends": list(self._backends.keys()),
            "active_backend": self._active_backend.__class__.__name__ if self._active_backend else None,
            "has_playwright": HAS_PLAYWRIGHT,
            "has_scrapling": HAS_SCRAPLING,
            "has_websockets": HAS_WEBSOCKETS,
            "has_camofox_server": "camofox" in self._backends,
            "camofox_url": os.environ.get("NEUROVA_CAMOFOX_URL", ""),
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
