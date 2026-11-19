"""macOS AX 语义后端 · 预留骨架（AD-6）。

方法面与 Windows 的 UiautomationBackend 同形（manager 契约），但**实现未落地**：
一切动作诚实抛 NotImplementedError，不静默假成功。真机适配（AX API：AXUIElement
观察/PerformAction 投递）在「三平台适配」后续批次，需 macOS 真机 fixture（档 C）。
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from neurova.computer_use.platform import desktopBackendAvailability

_RESERVED = "macOS AX 后端为预留骨架（AD-6）：动作未实现，待三平台批次真机落地"


class MacAccessibilityBackend:
    def is_available(self) -> bool:
        return bool(desktopBackendAvailability()["macos"]["available"])

    # ── 观察 ──
    def get_window(self, window_title: Optional[str] = None) -> Optional[Dict[str, Any]]:
        raise NotImplementedError(_RESERVED)

    def walk(self, window: Dict[str, Any], max_nodes: int, max_depth: int) -> tuple:
        raise NotImplementedError(_RESERVED)

    def list_windows(self, limit: int = 50) -> list:
        raise NotImplementedError(_RESERVED)

    def get_focused_editable(self) -> Optional[Dict[str, Any]]:
        raise NotImplementedError(_RESERVED)

    # ── 语义动作（五级递降链的 macOS 对应位）──
    def invoke(self, element: Dict[str, Any]) -> bool:
        raise NotImplementedError(_RESERVED)

    def toggle(self, element: Dict[str, Any]) -> bool:
        raise NotImplementedError(_RESERVED)

    def expand(self, element: Dict[str, Any]) -> bool:
        raise NotImplementedError(_RESERVED)

    def legacy_default(self, element: Dict[str, Any]) -> bool:
        raise NotImplementedError(_RESERVED)

    def post_click(self, element: Dict[str, Any], button: str) -> bool:
        raise NotImplementedError(_RESERVED)

    def global_click(self, element: Dict[str, Any], button: str) -> bool:
        raise NotImplementedError(_RESERVED)

    def set_value(self, element: Dict[str, Any], value: str) -> Optional[str]:
        raise NotImplementedError(_RESERVED)

    def focus(self, element: Dict[str, Any]) -> bool:
        raise NotImplementedError(_RESERVED)

    def global_type(self, value: str) -> bool:
        raise NotImplementedError(_RESERVED)
