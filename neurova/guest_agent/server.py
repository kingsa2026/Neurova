"""neurova-guest-agent 守护进程（CUA Phase 3 扩展 RS-2）

来宾（Windows Sandbox / 容器 / VM）内运行的桌面动作守护进程：把与宿主**同一份**
actions.py / desktop_uia.py 动作实现经 HTTP 暴露，端口默认 8765。宿主侧 remote
后端（RS-1）经此驱动来宾桌面。

设计红线（立项书 §3 要点 2）：
- 复用现有契约，不另起实现 → guest 端动作语义与宿主逐字段一致
- 双向 token 鉴权（默认 bind 127.0.0.1 / 容器内网；无 token 拒）
- ActionResult 的 route/delivery 由**宿主侧**按通道附加（guest 只回基础动作结果）

运行：python -m neurova.guest_agent.server --port 8765 --token <secret>
"""

from __future__ import annotations

import base64
from typing import Any, Dict, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from neurova.core.logger import get_logger

logger = get_logger(__name__)

DEFAULT_PORT = 8765


class ActionRequest(BaseModel):
    kind: str
    params: Dict[str, Any] = {}


def _make_auth(token: Optional[str]):
    async def _require_token(authorization: Optional[str] = Header(default=None)):
        if not token:
            return  # 未配置 token（仅本地测试/受信内网）
        if not authorization or not authorization.replace("Bearer ", "") == token:
            raise HTTPException(status_code=401, detail="guest agent token 校验失败")
    return _require_token


def create_app(manager: Any = None, uia_manager: Any = None, token: Optional[str] = None) -> FastAPI:
    """构建 guest agent ASGI 应用。manager/uia_manager 注入便于测试
    （默认真机 ComputerUseManager / DesktopUIAManager）。"""
    app = FastAPI(title="neurova-guest-agent")
    auth = _make_auth(token)

    def _mgr():
        if manager is not None:
            return manager
        from neurova.computer_use import get_computer_use_manager

        return get_computer_use_manager()

    def _uia_mgr():
        if uia_manager is not None:
            return uia_manager
        from neurova.computer_use.desktop_uia import get_desktop_uia_manager

        return get_desktop_uia_manager()

    @app.get("/health")
    async def health():
        return {"ok": True, "agent": "neurova-guest-agent"}

    @app.post("/action", dependencies=[Depends(auth)])
    async def action(body: ActionRequest):
        import asyncio

        from neurova.computer_use import actions

        mgr = _mgr()
        kind = body.kind
        p = body.params or {}
        try:
            if kind == "screenshot":
                png = await asyncio.to_thread(actions.screenshot_bytes, mgr)
                if png is None:
                    return {"error": "无可用截图后端"}
                return {"success": True, "format": "png", "size_bytes": len(png),
                        "png_b64": base64.b64encode(png).decode("ascii")}
            if kind == "click":
                return await asyncio.to_thread(
                    actions.click_screenshot_point, mgr, p.get("x"), p.get("y"), p.get("button", "left")
                )
            if kind == "type":
                return await asyncio.to_thread(actions.type_text, mgr, p.get("text"), p.get("interval", 0.05))
            if kind == "scroll":
                return await asyncio.to_thread(
                    actions.scroll, mgr, p.get("scroll_x", 0), p.get("scroll_y", 0), p.get("x"), p.get("y")
                )
            if kind in ("dom_snapshot", "click_element", "set_value"):
                return await asyncio.to_thread(_uia_action, kind, p, _uia_mgr())
            return {"error": f"guest agent 未知动作: {kind}"}
        except Exception as e:  # noqa: BLE001 — guest 语义：错误也回结构化
            logger.warning("guest agent 动作 %s 失败: %s", kind, e)
            return {"error": str(e)}

    return app


def _uia_action(kind: str, p: Dict[str, Any], mgr: Any) -> Dict[str, Any]:
    """桌面语义动作（UIA）——与宿主 desktop_uia 同一实现（mgr 注入）。"""
    gen = int(p["generation"]) if p.get("generation") is not None else None
    if kind == "dom_snapshot":
        return mgr.snapshot(
            window_title=p.get("window_title"),
            max_nodes=p.get("max_nodes"),
            max_depth=p.get("max_depth"),
        )
    if kind == "click_element":
        return mgr.click_element(
            p.get("index"), p.get("runtime_id"), p.get("window_title"),
            p.get("button", "left"), gen,
        )
    return mgr.set_value(
        p.get("value"), p.get("index"), p.get("runtime_id"), p.get("window_title"), gen,
    )


def main(argv: Optional[list] = None) -> None:
    import argparse

    import uvicorn

    ap = argparse.ArgumentParser(prog="neurova-guest-agent")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--token", default=None)
    args = ap.parse_args(argv)
    uvicorn.run(create_app(token=args.token), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
