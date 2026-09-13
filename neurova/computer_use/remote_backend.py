"""远程桌面后端（CUA Phase 3 扩展 RS-1/RS-2 宿主侧）

RemoteComputerUseManager 与本地 ComputerUseManager 同方法面（duck-type），但把
动作代理到来宾 neurova-guest-agent（经 GuestAgentClient）。宿主侧统一附加
ActionResult（route=remote / delivery=background）——远程是隔离机，天然不抢用户
真机焦点，"非侵入"在此档自动成立（立项书 §5 要点 1）。
"""

from __future__ import annotations

import base64
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional, Tuple

from neurova.core.logger import get_logger

logger = get_logger(__name__)


class RemoteComputerUseManager:
    """来宾桌面动作代理（控制面 HTTP，与显示协议无关）。"""

    def __init__(self, client: Any, session_id: str = ""):
        self._client = client
        self.session_id = session_id

    # ── 与本地 manager 同面的动作 ──────────────────────────────

    def screenshot(self, region: Optional[Tuple[int, int, int, int]] = None) -> Optional[bytes]:
        out = self._client.action("screenshot", {"region": region} if region else {})
        if out.get("png_b64"):
            return base64.b64decode(out["png_b64"])
        return None

    def click_screenshot_point(self, x: Any, y: Any, button: str = "left") -> bool:
        out = self._client.action("click", {"x": x, "y": y, "button": button})
        return bool(out.get("success"))

    def type_text(self, text: str, interval: float = 0.05) -> bool:
        return bool(self._client.action("type", {"text": text, "interval": interval}).get("success"))

    def scroll(self, x: Any, y: Any, vertical: int, horizontal: int = 0) -> bool:
        out = self._client.action("scroll", {"x": x, "y": y, "scroll_x": horizontal, "scroll_y": vertical})
        return bool(out.get("success"))

    def snapshot(self, window_title=None, max_nodes=None, max_depth=None) -> Dict[str, Any]:
        # 与本地 DesktopUIAManager.snapshot 同签名（wire kind 仍为 dom_snapshot）
        return self._client.action("dom_snapshot", {
            "window_title": window_title, "max_nodes": max_nodes, "max_depth": max_depth,
        })

    def click_element(self, index=None, runtime_id=None, window_title=None, button="left", generation=None) -> Dict[str, Any]:
        return self._client.action("click_element", {
            "index": index, "runtime_id": runtime_id, "window_title": window_title,
            "button": button, "generation": generation,
        })

    def set_value(self, value, index=None, runtime_id=None, window_title=None, generation=None) -> Dict[str, Any]:
        return self._client.action("set_value", {
            "value": value, "index": index, "runtime_id": runtime_id,
            "window_title": window_title, "generation": generation,
        })

    # ── 能力声明（远程恒 background 投递）──────────────────────

    def input_available(self) -> bool:
        return True

    def uia_available(self) -> bool:
        return True

    def screen_metadata(self) -> Optional[Dict[str, Any]]:
        # 来宾元数据由 guest 端截图结果附带；此处尽力从 health 拿不到则 None
        return None


def attach_remote_action_result(result: Dict[str, Any], *, confirmed: bool) -> Dict[str, Any]:
    """宿主侧为远程动作附加 ActionResult：route=remote、delivery=background。

    confirmed→confirmed 档（来宾回执）；否则 suspected_noop（诚实档）。
    """
    from neurova.computer_use import action_result as _ar

    if confirmed:
        _ar.attach(result, _ar.confirmed("remote", "background", ["delivery_ack"]))
    else:
        _ar.attach(result, _ar.suspected_noop("remote", "background"))
    return result


@contextmanager
def use_remote_session(pool: Any, user_id: str) -> Iterator[RemoteComputerUseManager]:
    """闭环胶水：从会话池领用一个来宾桌面 → 绑定为当前上下文的活动远程桌面
    （此后 computer_* 动作经 get_computer_use_manager()/_desktop_uia() 自动路由到来宾）
    → 退出时解绑并归还池。

    这是 RS 平面"任务→隔离桌面"的编排入口；生产触发（无人值守/高风险任务何时走
    远程）由上层策略决定，本函数保证组件间可组合、可测、异常必归还。
    """
    from neurova.computer_use import bind_remote_desktop, unbind_remote_desktop
    from neurova.guest_agent.client import GuestAgentClient

    session = pool.claim(user_id)
    try:
        client = GuestAgentClient(session.base_url, token=session.token)
        manager = RemoteComputerUseManager(client, session_id=session.session_id)
        session.manager = manager
        token = bind_remote_desktop(manager)
        try:
            yield manager
        finally:
            unbind_remote_desktop(token)
            client.close()
    finally:
        pool.release(session.session_id)
