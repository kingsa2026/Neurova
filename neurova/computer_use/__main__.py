"""CUA 独立 CLI（`python -m neurova.computer_use <command>`）。

AD-5（agent-desktop 对照工单后置项拍板立项，2026-11-19）。进程内直调 manager，
**人工代理形态**——不经过 agent 工具面的治理门（审批/审计/租户）；外部 agent
自动化必须走工具面/REST/MCP（有治理），不得用本 CLI 承载。每条命令输出统一
JSON 信封 `{"ok", "command", "data"|"error"}`，退出码 0=成功 / 1=执行失败 / 2=用法错。

README 此前记载的 `neurova computer ...` 无实现（文档漂移），本模块补齐真入口。
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from typing import Any, Dict, List, Optional


class _UsageError(ValueError):
    """用法/参数错误（退出码 2）"""


class _EnvelopeParser(argparse.ArgumentParser):
    """把 argparse 的报错（未知命令/缺参/非法值）转成可捕获的用法异常，
    保证任何失败都以 JSON 信封输出而非裸 usage 文本。"""

    def error(self, message: str):
        raise _UsageError(message)


def _uia_manager():
    from neurova.computer_use.desktop_uia import get_desktop_uia_manager

    return get_desktop_uia_manager()


def _cu_manager():
    from neurova.computer_use import get_computer_use_manager

    return get_computer_use_manager()


def _emit(command: str, ok: bool, data: Any = None, error: Optional[str] = None) -> int:
    envelope: Dict[str, Any] = {"ok": ok, "command": command}
    if ok:
        envelope["data"] = data
    else:
        envelope["error"] = error or "failed"
    print(json.dumps(envelope, ensure_ascii=False, default=str))
    return 0 if ok else 1


def _require_target(args: argparse.Namespace) -> None:
    if getattr(args, "index", None) is None and not getattr(args, "runtime_id", None):
        raise _UsageError("缺少目标元素：--index 或 --runtime_id（来自 dom-snapshot 快照事实）")


def _cmd_status(args: argparse.Namespace) -> Dict[str, Any]:
    from neurova.computer_use.desktop_uia import availabilityDetail

    uia = availabilityDetail()
    return {
        "uia": uia,
        "platform": sys.platform,
        "global_input_env": "NEUROVA_ALLOW_GLOBAL_INPUT",
    }


def _cmd_list_windows(args: argparse.Namespace) -> Dict[str, Any]:
    return _uia_manager().list_windows(limit=args.limit)


def _cmd_dom_snapshot(args: argparse.Namespace) -> Dict[str, Any]:
    return _uia_manager().snapshot(
        args.window_title,
        args.max_nodes,
        args.max_depth,
        args.root_index,
        args.root_runtime_id,
        bool(args.skeleton),
    )


def _cmd_screenshot(args: argparse.Namespace) -> Dict[str, Any]:
    png = _cu_manager().screenshot()
    if png is None:
        raise RuntimeError("截图失败（后端未就绪）")
    if args.out:
        with open(args.out, "wb") as f:
            f.write(png)
        return {"path": args.out, "bytes": len(png)}
    return {"png_b64": base64.b64encode(png).decode("ascii"), "bytes": len(png)}


def _cmd_click(args: argparse.Namespace) -> Dict[str, Any]:
    ok = _cu_manager().click(args.x, args.y, args.button)
    return {"clicked": bool(ok)}


def _cmd_type(args: argparse.Namespace) -> Dict[str, Any]:
    ok = _cu_manager().type_text(args.text, args.interval)
    return {"typed": bool(ok)}


def _cmd_scroll(args: argparse.Namespace) -> Dict[str, Any]:
    ok = _cu_manager().scroll(args.x, args.y, args.dy, args.dx)
    return {"scrolled": bool(ok)}


def _cmd_key(args: argparse.Namespace) -> Dict[str, Any]:
    ok = _cu_manager().press_key(args.keys)
    return {"key_sent": bool(ok)}


def _cmd_click_element(args: argparse.Namespace) -> Dict[str, Any]:
    _require_target(args)
    return _uia_manager().click_element(
        args.index, args.runtime_id, args.window_title, args.button, args.generation,
    )


def _cmd_set_value(args: argparse.Namespace) -> Dict[str, Any]:
    _require_target(args)
    return _uia_manager().set_value(
        args.value, args.index, args.runtime_id, args.window_title, args.generation,
    )


def _build_parser() -> _EnvelopeParser:
    parser = _EnvelopeParser(prog="python -m neurova.computer_use",
                              description="Neurova Computer Use CLI（人工代理形态，进程内直调）")
    sub = parser.add_subparsers(dest="command", parser_class=_EnvelopeParser)

    sub.add_parser("status", help="能力探测（UIA/平台/门控）")
    p = sub.add_parser("list-windows", help="枚举桌面顶层窗口")
    p.add_argument("--limit", type=int, default=50)
    p = sub.add_parser("dom-snapshot", help="控件树快照（支持 --skeleton / --root-index 下钻）")
    p.add_argument("--window-title", default=None)
    p.add_argument("--max-nodes", type=int, default=None)
    p.add_argument("--max-depth", type=int, default=None)
    p.add_argument("--root-index", type=int, default=None)
    p.add_argument("--root-runtime-id", default=None)
    p.add_argument("--skeleton", action="store_true")
    p = sub.add_parser("screenshot", help="截图（--out 写文件，否则回 base64）")
    p.add_argument("--out", default=None)
    p = sub.add_parser("click", help="像素坐标点击（全局输入，会动真实光标）")
    p.add_argument("--x", type=int, required=True)
    p.add_argument("--y", type=int, required=True)
    p.add_argument("--button", default="left", choices=["left", "right", "middle"])
    p = sub.add_parser("type", help="键入文本")
    p.add_argument("--text", required=True)
    p.add_argument("--interval", type=float, default=0.05)
    p = sub.add_parser("scroll", help="滚轮")
    p.add_argument("--x", type=int, required=True)
    p.add_argument("--y", type=int, required=True)
    p.add_argument("--dy", type=int, required=True)
    p.add_argument("--dx", type=int, default=0)
    p = sub.add_parser("key", help="按键（如 esc/enter/ctrl+s）")
    p.add_argument("--keys", required=True)
    p = sub.add_parser("click-element", help="按快照元素语义点击（不抢焦点）")
    p.add_argument("--index", type=int, default=None)
    p.add_argument("--runtime-id", dest="runtime_id", default=None)
    p.add_argument("--window-title", default=None)
    p.add_argument("--button", default="left", choices=["left", "right", "middle"])
    p.add_argument("--generation", type=int, default=None)
    p = sub.add_parser("set-value", help="按快照元素写值（ValuePattern）")
    p.add_argument("--value", required=True)
    p.add_argument("--index", type=int, default=None)
    p.add_argument("--runtime-id", dest="runtime_id", default=None)
    p.add_argument("--window-title", default=None)
    p.add_argument("--generation", type=int, default=None)
    return parser


_HANDLERS = {
    "status": _cmd_status,
    "list-windows": _cmd_list_windows,
    "dom-snapshot": _cmd_dom_snapshot,
    "screenshot": _cmd_screenshot,
    "click": _cmd_click,
    "type": _cmd_type,
    "scroll": _cmd_scroll,
    "key": _cmd_key,
    "click-element": _cmd_click_element,
    "set-value": _cmd_set_value,
}


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except _UsageError as e:
        _emit(argv[0] if argv else "", False, error=str(e))
        return 2
    command = getattr(args, "command", None)
    if command not in _HANDLERS:
        _emit(command or "", False, error=f"未知命令：{command!r}")
        return 2
    try:
        data = _HANDLERS[command](args)
    except _UsageError as e:
        _emit(command, False, error=str(e))
        return 2
    except Exception as e:  # noqa: BLE001 — CLI 边界：一切失败以信封诚实输出
        return _emit(command, False, error=f"{type(e).__name__}: {e}")
    if isinstance(data, dict) and data.get("success") is False:
        return _emit(command, False, error=str(data.get("error") or data))
    return _emit(command, True, data=data)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
