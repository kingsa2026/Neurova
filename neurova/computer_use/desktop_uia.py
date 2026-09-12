"""桌面 UIA 语义层（CUA 升级方案 R1-1，Windows 优先）

给桌面端补齐与浏览器侧对等的"观察后行动"契约：
- snapshot：枚举前台（或指定标题）窗口的 UIA 控件树，带 index/runtime_id/generation
  与观察预算（max_nodes/max_depth）
- click_element：五级递降链，语义动作优先、全局输入必须 env 门控——
    Invoke → Toggle → ExpandCollapse → LegacyIAccessible.DoDefaultAction
    → PostMessage 直投（app_post，不抢焦点）
    → 全局 SendInput（仅 NEUROVA_ALLOW_GLOBAL_INPUT=1；会动真实光标）
- set_value：UIA ValuePattern 优先（可读回 → value_readback 证据）→ 门控键入兜底

所有动作结果携带 ActionResult 封闭契约（action_result.py）；拒绝码 vocabulary
与浏览器侧共用。参考实现：OCU apps/OpenComputerUseWindows/runtime.ps1（UIA+PostMessage）。
"""

import os
import threading
import typing
from typing import Any, Dict, Optional, Tuple

from neurova.core.logger import get_logger
from neurova.computer_use import action_result as ar

logger = get_logger(__name__)

GLOBAL_INPUT_ENV = "NEUROVA_ALLOW_GLOBAL_INPUT"

DEFAULT_MAX_NODES = 400
DEFAULT_MAX_DEPTH = 32


def _global_input_enabled() -> bool:
    raw = os.environ.get(GLOBAL_INPUT_ENV, "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def is_available() -> bool:
    """平台 + 库可用性探测（/status、/doctor 消费；任何环境不抛异常）"""
    try:
        if os.name != "nt":
            return False
        import uiautomation  # noqa: F401

        return True
    except Exception:
        return False


class DesktopUIAManager:
    """桌面 UIA 语义会话管理器（按窗口键缓存快照事实 + generation）"""

    _UNSET = object()  # 区分"未传参（自动解析真实后端）"与"显式 None（禁用）"

    def __init__(self, backend: Any = _UNSET):
        if backend is self._UNSET:
            backend = self._create_real_backend()
        self._backend = backend
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _create_real_backend() -> Optional[Any]:
        if not is_available():
            return None
        from neurova.computer_use.desktop_uia import UiautomationBackend

        return UiautomationBackend()

    # ── 快照 ──────────────────────────────────────────

    def snapshot(
        self,
        window_title: Optional[str] = None,
        max_nodes: int = DEFAULT_MAX_NODES,
        max_depth: int = DEFAULT_MAX_DEPTH,
    ) -> Dict[str, Any]:
        """枚举窗口控件树（观察，无投递语义 → 不带 action_result）"""
        if self._backend is None:
            return self._refused("桌面 UIA 层不可用（非 Windows 或缺少 uiautomation）", "unsupported_method")
        max_nodes = max(int(max_nodes or DEFAULT_MAX_NODES), 1)
        max_depth = max(int(max_depth or DEFAULT_MAX_DEPTH), 1)
        with self._lock:
            window = self._backend.get_window(window_title)
            if not window:
                return self._refused(
                    f"未找到目标窗口（window_title={window_title!r}，缺省为前台窗口）", "ref_not_found"
                )
            try:
                stored_elements = self._backend.walk(window, max_nodes, max_depth)
            except Exception as e:
                return self._refused(f"控件树枚举失败: {e}", "backend_error")

            session_key = self._session_key(window_title, window)
            public_elements = []
            for i, el in enumerate(stored_elements):
                el["index"] = i
                public_elements.append(
                    {k: v for k, v in el.items() if not k.startswith("_")}
                )
            self._sessions[session_key] = {
                "generation": self._sessions.get(session_key, {}).get("generation", 1),
                "window": {k: v for k, v in window.items() if not k.startswith("_")},
                "elements": stored_elements,
            }
            return {
                "success": True,
                "generation": self._sessions[session_key]["generation"],
                "window": self._sessions[session_key]["window"],
                "elements": public_elements,
                "truncated": len(stored_elements) >= max_nodes,
                "max_nodes": max_nodes,
                "max_depth": max_depth,
            }

    # ── 点击（五级递降链）──────────────────────────────

    def click_element(
        self,
        index: Optional[int] = None,
        runtime_id: Optional[str] = None,
        window_title: Optional[str] = None,
        button: str = "left",
        generation: Optional[int] = None,
    ) -> Dict[str, Any]:
        if self._backend is None:
            return self._refused("桌面 UIA 层不可用", "unsupported_method")
        with self._lock:
            session, err = self._lookup_session(window_title, generation)
            if err is not None:
                return err
            element, err = self._lookup_element(session, index, runtime_id)
            if err is not None:
                return err

            action_result = self._deliver_click(element, button)
            result: Dict[str, Any]
            if action_result["effect"] == "refused":
                result = {"success": False, "error": f"点击未能投递：{action_result['refusal_code']}"}
            else:
                result = {
                    "success": True,
                    "index": element.get("index"),
                    "runtime_id": element.get("runtime_id"),
                    "role": element.get("role"),
                    "name": element.get("name"),
                }
                session["generation"] += 1
                result["generation"] = session["generation"]
            result["action_result"] = action_result
            return result

    def _deliver_click(self, element: Dict[str, Any], button: str) -> Dict[str, Any]:
        """五级递降链：语义动作 → 消息直投 → 门控全局输入"""
        backend = self._backend
        evidence = ["delivery_ack"]
        if element.get("invokable") and backend.invoke(element):
            return ar.confirmed("uia", "background", evidence)
        if element.get("togglable") and backend.toggle(element):
            return ar.confirmed("uia", "background", evidence)
        if element.get("expandable") and backend.expand(element):
            return ar.confirmed("uia", "background", evidence)
        if element.get("legacy_default") and backend.legacy_default(element):
            return ar.confirmed("uia", "background", evidence)

        rect = element.get("rect")
        if rect:
            if backend.post_click(element, button):
                return ar.confirmed("app_post", "background", evidence)
            if _global_input_enabled() and backend.global_click(element, button):
                return ar.confirmed("global_input", "foreground", evidence)
            return ar.refused(
                "uia",
                "background_unavailable",
                escalation={"target": "pixel", "reason": "route_unavailable"},
            )
        return ar.refused("uia", "background_unavailable")

    # ── 赋值（ValuePattern 优先）──────────────────────

    def set_value(
        self,
        value: Any,
        index: Optional[int] = None,
        runtime_id: Optional[str] = None,
        window_title: Optional[str] = None,
        generation: Optional[int] = None,
    ) -> Dict[str, Any]:
        if self._backend is None:
            return self._refused("桌面 UIA 层不可用", "unsupported_method")
        if value is None:
            return self._refused("缺少 value 参数", "missing_params")
        with self._lock:
            session, err = self._lookup_session(window_title, generation)
            if err is not None:
                return err
            element, err = self._lookup_element(session, index, runtime_id)
            if err is not None:
                return err

            if element.get("settable"):
                readback = self._backend.set_value(element, str(value))
                if readback is not None:
                    session["generation"] += 1
                    return {
                        "success": True,
                        "index": element.get("index"),
                        "value_readback": readback,
                        "generation": session["generation"],
                        "action_result": ar.confirmed("uia", "background", ["value_readback"]),
                    }

            if _global_input_enabled():
                self._backend.focus(element)
                self._backend.global_type(str(value))
                return {
                    "success": True,
                    "index": element.get("index"),
                    "action_result": ar.unverifiable("global_input", "foreground"),
                }
            return self._refused(
                "元素不可通过 ValuePattern 赋值，且全局输入未开启"
                f"（{GLOBAL_INPUT_ENV}=1 可放开键入兜底）",
                "background_unavailable",
            )

    # ── 语义文本输入（R2-1，OCU 智能输入契约）────────

    def type_text_semantic(self, text: str) -> Optional[Dict[str, Any]]:
        """对 focused 可编辑控件直接追加写入（ValuePattern）。

        返回语义结果 dict；无可写目标 / ValuePattern 写失败 → None
        （交由执行方裁决是否回退全局键入——绝不静默假成功）。
        """
        if self._backend is None or not text:
            return None
        try:
            element = self._backend.get_focused_editable()
        except Exception:
            element = None
        if not element or not element.get("settable"):
            return None
        current = element.get("value") or ""
        readback = self._backend.set_value(element, f"{current}{text}")
        if readback is None:
            return None
        return {
            "success": True,
            "runtime_id": element.get("runtime_id"),
            "value_readback": readback,
            "action_result": ar.confirmed("uia", "background", ["value_readback"]),
        }

    # ── 会话/元素查找 ─────────────────────────────────

    @staticmethod
    def _session_key(window_title: Optional[str], window: Dict[str, Any]) -> str:
        """快照会话键：显式标题按标题存取；缺省（前台）固定 __foreground__，
        与 _lookup_session 的取键逻辑严格对齐"""
        if window_title:
            return f"win:{window_title.strip().lower()}"
        return "__foreground__"

    def _lookup_session(
        self, window_title: Optional[str], generation: Optional[int]
    ) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        if window_title:
            for key in (f"win:{window_title.strip().lower()}", "__foreground__"):
                if key in self._sessions:
                    session = self._sessions[key]
                    break
            else:
                session = None
        else:
            session = self._sessions.get("__foreground__")
        if session is None:
            return None, self._refused(
                "尚无桌面快照或快照已失效——请先调用 computer_dom_snapshot 获取元素事实",
                "stale_generation",
            )
        if generation is not None and int(generation) != session["generation"]:
            return None, self._refused(
                f"generation 过期（当前 {session['generation']}，传入 {generation}）——"
                "窗口快照事实已失效，请重新 computer_dom_snapshot",
                "stale_generation",
            )
        return session, None

    @staticmethod
    def _lookup_element(
        session: Dict[str, Any],
        index: Optional[int],
        runtime_id: Optional[str],
    ) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        elements = session["elements"]
        if index is None and runtime_id is None:
            return None, ar.attach(
                {"success": False, "error": "缺少 index 或 runtime_id（来自快照事实）"},
                ar.refused("uia", "missing_params"),
            )
        for el in elements:
            if runtime_id is not None and str(el.get("runtime_id")) == str(runtime_id):
                return el, None
        if index is not None:
            try:
                idx = int(index)
            except (TypeError, ValueError):
                idx = -1
            if 0 <= idx < len(elements):
                return elements[idx], None
        return None, ar.attach(
            {"success": False, "error": f"快照中不存在该元素（index={index}, runtime_id={runtime_id}）"},
            ar.refused("uia", "ref_not_found"),
        )

    @staticmethod
    def _refused(message: str, refusal_code: str) -> Dict[str, Any]:
        return ar.attach({"success": False, "error": message}, ar.refused("uia", refusal_code))


class UiautomationBackend:
    """真实后端：uiautomation 库（Windows）。所有 API 调用逐级守卫，
    任何异常都退化为 False/None → 由 Manager 转成精确拒绝码。"""

    _MOUSE_FLAGS = {"left": 0x0001, "right": 0x0002, "middle": 0x0010}
    _MOUSE_MSGS = {
        "left": (0x0201, 0x0202),    # WM_LBUTTONDOWN / UP
        "right": (0x0204, 0x0205),   # WM_RBUTTONDOWN / UP
        "middle": (0x0207, 0x0208),  # WM_MBUTTONDOWN / UP
    }

    def available(self) -> bool:
        return is_available()

    def get_focused_editable(self) -> Optional[Dict[str, Any]]:
        """当前焦点控件（仅当其为 ValuePattern 可写元素时返回元素事实）"""
        try:
            import uiautomation as auto

            ctrl = auto.GetFocusedControl()
            if ctrl is None:
                return None
            el = self._element_info(ctrl)
            if el and el.get("settable"):
                return el
        except Exception as e:
            logger.debug("focused editable 探测失败: %s", e)
        return None

    def get_window(self, window_title: Optional[str] = None) -> Optional[Dict[str, Any]]:
        try:
            import uiautomation as auto

            if window_title:
                needle = window_title.strip().lower()
                for child in auto.GetRootControl().GetChildren():
                    if child.Name and needle in str(child.Name).lower():
                        return self._window_info(child)
                return None
            focused = auto.GetFocusedControl()
            top = focused.GetTopLevelControl() if focused else None
            return self._window_info(top) if top else None
        except Exception as e:
            logger.debug("UIA get_window 失败: %s", e)
            return None

    def walk(self, window: Dict[str, Any], max_nodes: int, max_depth: int) -> list:
        root = window.get("_control")
        if root is None:
            raise RuntimeError("window info 缺少 _control")
        elements: list = []

        def visit(ctrl: Any, depth: int) -> None:
            if len(elements) >= max_nodes or depth > max_depth:
                return
            el = self._element_info(ctrl)
            if el is not None:
                elements.append(el)
            try:
                children = ctrl.GetChildren()
            except Exception:
                children = []
            for child in children:
                visit(child, depth + 1)

        visit(root, 0)
        return elements

    # ── 语义动作（元素 dict 携带 _control）──────────

    def invoke(self, element: Dict[str, Any]) -> bool:
        ctrl = element.get("_control")
        if ctrl is None or not element.get("invokable"):
            return False
        try:
            ctrl.GetInvokePattern().Invoke()
            return True
        except Exception:
            return False

    def toggle(self, element: Dict[str, Any]) -> bool:
        ctrl = element.get("_control")
        if ctrl is None or not element.get("togglable"):
            return False
        try:
            ctrl.GetTogglePattern().Toggle()
            return True
        except Exception:
            return False

    def expand(self, element: Dict[str, Any]) -> bool:
        ctrl = element.get("_control")
        if ctrl is None or not element.get("expandable"):
            return False
        try:
            ctrl.GetExpandCollapsePattern().Expand()
            return True
        except Exception:
            return False

    def legacy_default(self, element: Dict[str, Any]) -> bool:
        ctrl = element.get("_control")
        if ctrl is None or not element.get("legacy_default"):
            return False
        try:
            ctrl.GetLegacyIAccessiblePattern().DoDefaultAction()
            return True
        except Exception:
            return False

    def post_click(self, element: Dict[str, Any], button: str) -> bool:
        """PostMessage 直投目标窗口客户区中心（不移动真实光标、不抢焦点）"""
        rect = element.get("rect")
        hwnd = element.get("hwnd")
        msgs = self._MOUSE_MSGS.get(button)
        if not rect or not hwnd or not msgs:
            return False
        try:
            import ctypes
            import ctypes.wintypes as wintypes
            import time

            center_x = int(rect[0] + rect[2] / 2)
            center_y = int(rect[1] + rect[3] / 2)
            point = wintypes.POINT(center_x, center_y)
            if not ctypes.windll.user32.ScreenToClient(hwnd, ctypes.byref(point)):
                return False
            lparam = ((point.y & 0xFFFF) << 16) | (point.x & 0xFFFF)
            down_msg, up_msg = msgs
            ctypes.windll.user32.PostMessageW(hwnd, down_msg, self._MOUSE_FLAGS.get(button, 1), lparam)
            time.sleep(0.02)
            ctypes.windll.user32.PostMessageW(hwnd, up_msg, 0, lparam)
            return True
        except Exception as e:
            logger.debug("PostMessage 直投失败: %s", e)
            return False

    def global_click(self, element: Dict[str, Any], button: str) -> bool:
        rect = element.get("rect")
        if not rect:
            return False
        try:
            import pyautogui

            pyautogui.click(int(rect[0] + rect[2] / 2), int(rect[1] + rect[3] / 2), button=button)
            return True
        except Exception:
            return False

    def set_value(self, element: Dict[str, Any], value: str) -> Optional[str]:
        ctrl = element.get("_control")
        if ctrl is None:
            return None
        try:
            pattern = ctrl.GetValuePattern()
            pattern.SetValue(value)
            return str(pattern.Value)
        except Exception:
            return None

    def focus(self, element: Dict[str, Any]) -> bool:
        ctrl = element.get("_control")
        try:
            if ctrl is not None:
                ctrl.SetFocus()
                return True
        except Exception:
            pass
        return False

    def global_type(self, value: str) -> bool:
        try:
            import pyautogui

            pyautogui.write(value)
            return True
        except Exception:
            return False

    # ── 枚举辅助 ──────────────────────────────────────

    def _window_info(self, ctrl: Any) -> Optional[Dict[str, Any]]:
        try:
            rect = ctrl.BoundingRectangle
            info = {
                "title": str(ctrl.Name or ""),
                "rect": (int(rect.left), int(rect.top), int(rect.right - rect.left), int(rect.bottom - rect.top)),
                "pid": int(ctrl.ProcessId or 0),
                "hwnd": int(ctrl.NativeWindowHandle or 0),
                "_control": ctrl,
            }
            return info
        except Exception as e:
            logger.debug("UIA 窗口信息读取失败: %s", e)
            return None

    def _element_info(self, ctrl: Any) -> Optional[Dict[str, Any]]:
        try:
            role = str(getattr(ctrl, "ControlTypeName", "") or "")
            if role.endswith("Control"):
                role = role[: -len("Control")]
            role = role.lower() or "custom"

            rect = None
            try:
                br = ctrl.BoundingRectangle
                rect = (int(br.left), int(br.top), int(br.right - br.left), int(br.bottom - br.top))
            except Exception:
                rect = None

            value = None
            try:
                if ctrl.IsValuePatternAvailable():
                    value = ctrl.GetValuePattern().Value
            except Exception:
                value = None

            runtime_id = None
            try:
                runtime_id = ".".join(str(x) for x in ctrl.GetRuntimeId())
            except Exception:
                runtime_id = None

            return {
                "role": role,
                "name": str(ctrl.Name or ""),
                "rect": rect,
                "enabled": bool(getattr(ctrl, "IsEnabled", True)),
                "value": value,
                "focused": bool(getattr(ctrl, "HasKeyboardFocus", False)),
                "settable": self._flag(ctrl, "IsValuePatternAvailable"),
                "invokable": self._flag(ctrl, "IsInvokePatternAvailable"),
                "togglable": self._flag(ctrl, "IsTogglePatternAvailable"),
                "expandable": self._flag(ctrl, "IsExpandCollapsePatternAvailable"),
                "legacy_default": self._flag(ctrl, "IsLegacyIAccessiblePatternAvailable"),
                "runtime_id": runtime_id,
                "hwnd": self._safe_hwnd(ctrl),
                "_control": ctrl,
            }
        except Exception:
            return None

    @staticmethod
    def _flag(ctrl: Any, method_name: str) -> bool:
        try:
            method = getattr(ctrl, method_name, None)
            return bool(method()) if callable(method) else False
        except Exception:
            return False

    @staticmethod
    def _safe_hwnd(ctrl: Any) -> int:
        try:
            return int(ctrl.NativeWindowHandle or 0)
        except Exception:
            return 0


# 工厂
_uia_manager: Optional[DesktopUIAManager] = None
_uia_manager_lock = threading.Lock()


def get_desktop_uia_manager() -> DesktopUIAManager:
    global _uia_manager
    with _uia_manager_lock:
        if _uia_manager is None:
            _uia_manager = DesktopUIAManager()
        return _uia_manager


def reset_desktop_uia_manager() -> None:
    global _uia_manager
    with _uia_manager_lock:
        _uia_manager = None
