"""camofox-browser REST 客户端后端

对接 https://github.com/jo-inc/camofox-browser (Node 服务 @ :9377)
- 复用 BrowserBackend 抽象,Neurova 既有的 aria 快照/role 定位/generation/tab 管理全部直接生效
- 鉴权:`NEUROVA_CAMOFOX_ACCESS_KEY` → Authorization: Bearer 头
- userId/sessionKey 映射 Neurova tab_id,保持 tab 隔离
- 不动 BrowserManager/ComputerUseManager/builtin_tools 任何代码
"""

from __future__ import annotations

import base64
import re
import time
import uuid
from typing import Any, Dict, Optional, Tuple

from neurova.computer_use.browser_manager import BrowserBackend, BrowserResult
from neurova.core.config import get as env_get
from neurova.core.logger import get_logger

logger = get_logger(__name__)

try:
    import httpx

    HTTPX_AVAILABLE = True
except ImportError:
    httpx = None  # type: ignore[assignment]
    HTTPX_AVAILABLE = False

DEFAULT_CAMOFOX_URL = "http://localhost:9377"
DEFAULT_TIMEOUT = 30.0
NAVIGATE_TIMEOUT = 60.0  # /navigate 可能包含 SERP 提取


class CamofoxServerBackend(BrowserBackend):
    """通过 camofox-browser REST API 驱动的反检测浏览器后端"""

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ):
        super().__init__(config)
        cfg = config or {}
        self._base_url: str = cfg.get("base_url") or env_get("NEUROVA_CAMOFOX_URL", DEFAULT_CAMOFOX_URL)
        self._access_key: str = cfg.get("access_key") or env_get("NEUROVA_CAMOFOX_ACCESS_KEY", "")
        # 三层隔离:优先用 caller 传入的 user_id(由 BrowserManager 池化时按 JWT 派生),
        # 其次 cfg,最后 env 兜底
        self._user_id: str = (
            user_id
            or cfg.get("user_id")
            or env_get("NEUROVA_CAMOFOX_USER", "neurova")
        )
        self._client: Optional[Any] = None
        # Neurova 侧维护 tab 映射(target_id ↔ camofox tabId + generation)
        self._tabs: Dict[str, Dict[str, Any]] = {}
        self._active_target_id: Optional[str] = None

    # ── 能力声明 ──

    @property
    def capabilities(self) -> Dict[str, bool]:
        return {"aria_snapshot": True, "role_locator": True, "pixel_screenshot": True}

    def _eff_user_id(self) -> str:
        """三层隔离:优先读 ContextVar(由 tool_executor / API 入口注入),
        无则用 backend._user_id(由 BrowserManager 池化时按 user_id 派生)。"""
        try:
            from neurova.core.identity_context import get_request_user_id

            ctx_uid = get_request_user_id()
            if ctx_uid:
                return ctx_uid
        except ImportError:
            pass
        return self._user_id or "default"

    # ── 生命周期 ──

    async def initialize(self) -> bool:
        if not HTTPX_AVAILABLE:
            logger.warning("httpx not available; CamofoxServerBackend disabled")
            return False
        headers = {"Authorization": f"Bearer {self._access_key}"} if self._access_key else {}
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=DEFAULT_TIMEOUT, headers=headers)
        try:
            r = await self._client.get("/health")
            r.raise_for_status()
            logger.info("camofox-browser ready at %s (user=%s)", self._base_url, self._user_id)
            self._initialized = True
            return True
        except Exception as e:
            logger.warning("camofox-browser 直连 health 失败(%s): %s——尝试 supervisor 拉起", self._base_url, e)
            self._client = None
            # 尝试 supervisor 拉起(autostart=true 时才会真启动)
            try:
                from neurova.computer_use.camofox_supervisor import get_camofox_supervisor

                if not await get_camofox_supervisor().ensure_started():
                    logger.error("supervisor 拉起 camofox-browser 失败")
                    return False
            except Exception as sp_e:
                logger.error("supervisor 调用失败: %s", sp_e)
                return False
            # 拉起后重新建 client 并 probe
            self._client = httpx.AsyncClient(base_url=self._base_url, timeout=DEFAULT_TIMEOUT, headers=headers)
            try:
                r = await self._client.get("/health")
                r.raise_for_status()
                logger.info("camofox-browser 通过 supervisor 拉起 ready (user=%s)", self._user_id)
                self._initialized = True
                return True
            except Exception as e2:
                logger.error("supervisor 拉起后 health 仍失败: %s", e2)
                self._client = None
                return False

    async def close(self) -> None:
        if self._client:
            try:
                await self._client.aclose()
            except Exception as e:  # noqa: BLE001 - 收尾失败不阻碍清理
                logger.debug("camofox client close failed (ignored): %s", e)
            self._client = None
        self._tabs.clear()
        self._active_target_id = None

    # ── 内部 HTTP 助手 ──

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """统一封装:raise_for_status + JSON 解析 + 异常统一转 RuntimeError。
        外层方法再 catch 一次转 BrowserResult。
        """
        if not self._client:
            raise RuntimeError("CamofoxServerBackend not initialized")
        kwargs: Dict[str, Any] = {}
        if json is not None:
            kwargs["json"] = json
        if params is not None:
            kwargs["params"] = params
        if timeout is not None:
            kwargs["timeout"] = timeout
        r = await self._client.request(method, path, **kwargs)
        r.raise_for_status()
        # 通知 supervisor 刷新 idle 计时器(仅在跑着时;supervisor 未启用不阻断)
        try:
            from neurova.computer_use.camofox_supervisor import get_camofox_supervisor

            get_camofox_supervisor().record_activity()
        except Exception:
            pass
        if not r.content:
            return {}
        return r.json()

    # ── Tab 管理(Neurova 侧 target_id ↔ camofox tabId)──

    def _register_tab(self, tab_id: str, url: str, title: str = "") -> Dict[str, Any]:
        target_id = f"tab_{uuid.uuid4().hex[:8]}"
        self._tabs[target_id] = {"tab_id": tab_id, "generation": 1, "url": url, "title": title}
        self._active_target_id = target_id
        return {"target_id": target_id, "tab_id": tab_id, "generation": 1}

    def _check_active_generation(self, generation: Optional[int]) -> Optional[BrowserResult]:
        """校验调用方持有的 generation;None 表示跳过校验(向后兼容)"""
        if generation is None:
            return None
        tab = self._tabs.get(self._active_target_id) if self._active_target_id else None
        if not tab:
            return BrowserResult(success=False, error="无活动浏览器 tab")
        if tab["generation"] != generation:
            return BrowserResult(
                success=False,
                error=(
                    f"target generation 过期(当前 {tab['generation']},传入 {generation})——"
                    "页面已变化,快照事实失效,请重新 dom_snapshot"
                ),
                data={"stale": True, "current_generation": tab["generation"]},
            )
        return None

    def _active_generation(self) -> Optional[int]:
        tab = self._tabs.get(self._active_target_id) if self._active_target_id else None
        return tab["generation"] if tab else None

    def _active_tab(self) -> Optional[Dict[str, Any]]:
        return self._tabs.get(self._active_target_id) if self._active_target_id else None

    async def _resolve_tab_id(
        self, target_id: Optional[str]
    ) -> Tuple[Optional[str], Optional[BrowserResult]]:
        """把 Neurova target_id 解析成 camofox tabId;错误时返回 (None, BrowserResult)"""
        if not target_id:
            target_id = self._active_target_id
        if not target_id:
            return None, BrowserResult(success=False, error="无活动浏览器 tab")
        tab = self._tabs.get(target_id)
        if not tab:
            return None, BrowserResult(success=False, error=f"target 不存在: {target_id}")
        return tab["tab_id"], None

    # ── 导航 ──

    async def navigate(self, url: str, generation: Optional[int] = None) -> BrowserResult:
        start = time.time()
        stale = self._check_active_generation(generation)
        if stale:
            return stale
        tab = self._active_tab()
        try:
            if tab:
                # 复用活动 tab,POST /tabs/:id/navigate
                data = await self._request(
                    "POST",
                    f"/tabs/{tab['tab_id']}/navigate",
                    json={"userId": self._eff_user_id(), "url": url},
                    timeout=NAVIGATE_TIMEOUT,
                )
                tab["generation"] += 1
                tab["url"] = data.get("url", url)
                return BrowserResult(
                    success=True,
                    url=tab["url"],
                    title=tab.get("title", ""),
                    duration_ms=(time.time() - start) * 1000,
                    generation=self._active_generation(),
                )
            # 无活动 tab → POST /tabs 新建
            data = await self._request(
                "POST",
                "/tabs",
                json={
                    "userId": self._eff_user_id(),
                    "sessionKey": f"neurova-{uuid.uuid4().hex[:8]}",
                    "url": url,
                },
                timeout=NAVIGATE_TIMEOUT,
            )
            tab_id = data.get("tabId") or data.get("targetId") or ""
            info = self._register_tab(tab_id, url)
            return BrowserResult(
                success=True,
                data=info,
                url=url,
                duration_ms=(time.time() - start) * 1000,
                generation=info["generation"],
            )
        except Exception as e:
            return BrowserResult(
                success=False, error=str(e), duration_ms=(time.time() - start) * 1000
            )

    # ── ARIA 快照 ──

    async def dom_snapshot(self, generation: Optional[int] = None) -> BrowserResult:
        start = time.time()
        stale = self._check_active_generation(generation)
        if stale:
            return stale
        tab_id, err = await self._resolve_tab_id(None)
        if err:
            return err
        try:
            data = await self._request(
                "GET",
                f"/tabs/{tab_id}/snapshot",
                params={"userId": self._eff_user_id()},
            )
            active = self._active_tab() or {}
            return BrowserResult(
                success=True,
                data={
                    "snapshot": data.get("snapshot", ""),
                    "refs_count": data.get("refsCount", 0),
                    "truncated": data.get("truncated", False),
                },
                url=data.get("url", active.get("url", "")),
                title=active.get("title", ""),
                duration_ms=(time.time() - start) * 1000,
                generation=self._active_generation(),
            )
        except Exception as e:
            return BrowserResult(
                success=False, error=str(e), duration_ms=(time.time() - start) * 1000
            )

    # ── Role 定位(先 snapshot → 解析 ref → 调 click/type)──

    async def click_role(
        self,
        role: str,
        name: Optional[str] = None,
        generation: Optional[int] = None,
    ) -> BrowserResult:
        start = time.time()
        if not role or not str(role).strip():
            return BrowserResult(success=False, error="缺少 ARIA role(如 button/link/textbox)")
        stale = self._check_active_generation(generation)
        if stale:
            return stale
        ref, err = await self._resolve_ref_via_snapshot(role, name)
        if err:
            return err
        return await self._click_ref(ref)

    async def fill_role(
        self,
        role: str,
        name: Optional[str] = None,
        text: str = "",
        generation: Optional[int] = None,
    ) -> BrowserResult:
        start = time.time()
        if text is None:
            return BrowserResult(success=False, error="缺少输入文本(空串表示清空)")
        stale = self._check_active_generation(generation)
        if stale:
            return stale
        ref, err = await self._resolve_ref_via_snapshot(role, name)
        if err:
            return err
        return await self._type_ref(ref, text)

    async def _resolve_ref_via_snapshot(
        self, role: str, name: Optional[str]
    ) -> Tuple[Optional[str], Optional[BrowserResult]]:
        """拉最新快照并解析 (role, name) → ref;找不到返回 (None, BrowserResult)"""
        snap = await self.dom_snapshot(generation=self._active_generation())
        if not snap.success:
            return None, snap
        yaml_text = (snap.data or {}).get("snapshot", "")
        ref = _find_ref_in_yaml(yaml_text, role.strip(), name)
        if not ref:
            return None, BrowserResult(
                success=False,
                error=f"快照中未找到 role={role!r} name={name!r} 的可交互元素",
            )
        return ref, None

    async def _click_ref(self, ref: str) -> BrowserResult:
        start = time.time()
        tab_id, err = await self._resolve_tab_id(None)
        if err:
            return err
        try:
            await self._request(
                "POST",
                f"/tabs/{tab_id}/click",
                json={"userId": self._eff_user_id(), "ref": ref},
            )
            tab = self._active_tab()
            if tab:
                tab["generation"] += 1  # 交互使快照事实失效
            return BrowserResult(
                success=True,
                url=tab["url"] if tab else "",
                duration_ms=(time.time() - start) * 1000,
                generation=self._active_generation(),
            )
        except Exception as e:
            return BrowserResult(
                success=False, error=str(e), duration_ms=(time.time() - start) * 1000
            )

    async def _type_ref(self, ref: str, text: str) -> BrowserResult:
        start = time.time()
        tab_id, err = await self._resolve_tab_id(None)
        if err:
            return err
        try:
            await self._request(
                "POST",
                f"/tabs/{tab_id}/type",
                json={"userId": self._eff_user_id(), "ref": ref, "text": text, "clear": True},
            )
            tab = self._active_tab()
            if tab:
                tab["generation"] += 1
            return BrowserResult(
                success=True,
                url=tab["url"] if tab else "",
                duration_ms=(time.time() - start) * 1000,
                generation=self._active_generation(),
            )
        except Exception as e:
            return BrowserResult(
                success=False, error=str(e), duration_ms=(time.time() - start) * 1000
            )

    # ── Tab 生命周期 ──

    async def open_target(self, url: Optional[str] = None) -> BrowserResult:
        start = time.time()
        try:
            data = await self._request(
                "POST",
                "/tabs",
                json={
                    "userId": self._eff_user_id(),
                    "sessionKey": f"neurova-{uuid.uuid4().hex[:8]}",
                    "url": url or "about:blank",
                },
            )
            tab_id = data.get("tabId") or data.get("targetId") or ""
            info = self._register_tab(tab_id, url or "")
            return BrowserResult(
                success=True,
                data=info,
                url=url or "",
                duration_ms=(time.time() - start) * 1000,
                generation=info["generation"],
            )
        except Exception as e:
            return BrowserResult(
                success=False, error=str(e), duration_ms=(time.time() - start) * 1000
            )

    async def list_targets(self) -> BrowserResult:
        start = time.time()
        data = [
            {
                "target_id": tid,
                "generation": tab["generation"],
                "url": tab["url"],
                "active": tid == self._active_target_id,
            }
            for tid, tab in self._tabs.items()
        ]
        return BrowserResult(
            success=True, data=data, duration_ms=(time.time() - start) * 1000
        )

    async def switch_target(
        self, target_id: str, generation: Optional[int] = None
    ) -> BrowserResult:
        tab = self._tabs.get(target_id)
        if not tab:
            return BrowserResult(success=False, error=f"target 不存在: {target_id}")
        if generation is not None and tab["generation"] != generation:
            return BrowserResult(
                success=False,
                error=f"target generation 过期(当前 {tab['generation']},传入 {generation})",
                data={"stale": True, "current_generation": tab["generation"]},
            )
        self._active_target_id = target_id
        return BrowserResult(success=True, url=tab["url"])

    async def close_target(
        self, target_id: str, generation: Optional[int] = None
    ) -> BrowserResult:
        tab = self._tabs.get(target_id)
        if not tab:
            return BrowserResult(success=False, error=f"target 不存在: {target_id}")
        if generation is not None and tab["generation"] != generation:
            return BrowserResult(
                success=False,
                error=f"target generation 过期(当前 {tab['generation']},传入 {generation})",
                data={"stale": True, "current_generation": tab["generation"]},
            )
        try:
            await self._request(
                "DELETE",
                f"/tabs/{tab['tab_id']}",
                params={"userId": self._eff_user_id()},
            )
        except Exception as e:  # noqa: BLE001 - 关闭失败不阻碍移除登记
            logger.debug("camofox close tab failed (ignored): %s", e)
        del self._tabs[target_id]
        if self._active_target_id == target_id:
            self._active_target_id = next(iter(self._tabs), None)
        return BrowserResult(success=True)

    # ── 其他 BrowserBackend 抽象方法 ──

    async def screenshot(self) -> BrowserResult:
        """camofox /screenshot 返回原始 PNG 字节,转 base64 后塞 BrowserResult.screenshot"""
        start = time.time()
        if not self._client:
            return BrowserResult(success=False, error="not initialized")
        tab_id, err = await self._resolve_tab_id(None)
        if err:
            return err
        try:
            r = await self._client.get(
                f"/tabs/{tab_id}/screenshot",
                params={"userId": self._eff_user_id()},
                timeout=DEFAULT_TIMEOUT,
            )
            r.raise_for_status()
            tab = self._active_tab() or {}
            return BrowserResult(
                success=True,
                screenshot=base64.b64encode(r.content).decode(),
                url=tab.get("url", ""),
                title=tab.get("title", ""),
                duration_ms=(time.time() - start) * 1000,
                generation=self._active_generation(),
            )
        except Exception as e:
            return BrowserResult(
                success=False, error=str(e), duration_ms=(time.time() - start) * 1000
            )

    async def click(self, selector: str) -> BrowserResult:
        start = time.time()
        tab_id, err = await self._resolve_tab_id(None)
        if err:
            return err
        try:
            await self._request(
                "POST",
                f"/tabs/{tab_id}/click",
                json={"userId": self._eff_user_id(), "selector": selector},
            )
            tab = self._active_tab()
            if tab:
                tab["generation"] += 1
            return BrowserResult(
                success=True,
                duration_ms=(time.time() - start) * 1000,
                generation=self._active_generation(),
            )
        except Exception as e:
            return BrowserResult(
                success=False, error=str(e), duration_ms=(time.time() - start) * 1000
            )

    async def type_text(self, selector: str, text: str) -> BrowserResult:
        start = time.time()
        tab_id, err = await self._resolve_tab_id(None)
        if err:
            return err
        try:
            await self._request(
                "POST",
                f"/tabs/{tab_id}/type",
                json={
                    "userId": self._eff_user_id(),
                    "selector": selector,
                    "text": text,
                    "clear": True,
                },
            )
            tab = self._active_tab()
            if tab:
                tab["generation"] += 1
            return BrowserResult(
                success=True,
                duration_ms=(time.time() - start) * 1000,
                generation=self._active_generation(),
            )
        except Exception as e:
            return BrowserResult(
                success=False, error=str(e), duration_ms=(time.time() - start) * 1000
            )

    async def extract_text(self) -> BrowserResult:
        return await self._evaluate_simple("document.body.innerText")

    async def extract_links(self) -> BrowserResult:
        expr = (
            "Array.from(document.querySelectorAll('a[href]'))"
            ".map(a => ({text: a.innerText, href: a.href}))"
        )
        return await self._evaluate_simple(expr)

    async def execute_js(self, script: str) -> BrowserResult:
        return await self._evaluate_simple(script)

    async def _evaluate_simple(self, expression: str) -> BrowserResult:
        start = time.time()
        tab_id, err = await self._resolve_tab_id(None)
        if err:
            return err
        try:
            data = await self._request(
                "POST",
                f"/tabs/{tab_id}/evaluate",
                json={"userId": self._eff_user_id(), "expression": expression},
            )
            return BrowserResult(
                success=True,
                data=data.get("result"),
                duration_ms=(time.time() - start) * 1000,
            )
        except Exception as e:
            return BrowserResult(
                success=False, error=str(e), duration_ms=(time.time() - start) * 1000
            )

    async def snapshot(self) -> BrowserResult:
        """camofox 没有原生 HTML 端点,回退到 extract_text 返回 innerText"""
        return await self.extract_text()


# ── 模块级辅助函数 ──


# camofox YAML 快照行格式:`- button 'Login' [e3]` / `- button "Login" [e3]` / `- textbox [e5]:`
# 单引号为主(实测 camofox 输出),双引号作为 YAML 兼容回退
_REF_LINE_RE = re.compile(r'-\s+(\w+)(?:\s+(["\'])([^"\']*)\2)?\s+\[e(\d+)\]')


def _find_ref_in_yaml(yaml_text: str, role: str, name: Optional[str]) -> Optional[str]:
    """从 camofox YAML 快照中找出第一个匹配 (role, name) 的 [eN] ref。

    匹配规则:
    - 行必须以 `- role` 开头
    - name 为 None 时,取该 role 第一个出现的 ref
    - name 非 None 时,name 必须严格相等(quoted)
    """
    if not yaml_text or not role:
        return None
    for line in yaml_text.splitlines():
        m = _REF_LINE_RE.search(line)
        if not m:
            continue
        line_role, line_name, ref_num = m.group(1), m.group(3), m.group(4)
        if line_role != role:
            continue
        if name is not None and line_name != name:
            continue
        return f"e{ref_num}"
    return None