# -*- coding: utf-8 -*-
"""
Windows 受限令牌沙箱（P2 可选项③，SRP/SAFER 机制）

机制：SaferCreateLevel(NormalUser) → SaferComputeTokenFromLevel →
CreateProcessAsUserW。派生令牌剥离管理员特权（Administrators/
S-1-5-114 等组转 deny-only），子进程以 Basic User 完整性运行——
真实的安全增益（防提权破坏），非 AppContainer（未实现，见
AppContainerSandbox 诚实声明）。

诚实边界（不谎报）：
- 强制能力 = 特权剥离（privileges）；severity 枚举中的 NETWORK_OFF/
  READ_ONLY/FULL **不**由此后端强制（无网络/文件系统隔离语义）——
  governance 的高风险 DENY 判定不受本后端影响（Windows 无 bwrap/
  docker/seatbelt 时依旧拒绝）。
- 结果 dict 的 sandbox_enforced=True 仅指"受限令牌生效"，enforced_
  severities 恒为空集合供调用方核查。
"""

from __future__ import annotations

import ctypes
import os
import tempfile
import time
from typing import Any, Dict, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

# ── Win32 常量 ──
_SAFER_SCOPEID_USER = 1
_SAFER_LEVELID_NORMALUSER = 0x20000
_GENERIC_WRITE = 0x40000000
_CREATE_ALWAYS = 2
_CREATE_NO_WINDOW = 0x08000000
_STARTF_USESTDHANDLES = 0x100
_HANDLE_FLAG_INHERIT = 1
_FILE_ATTRIBUTE_NORMAL = 0x80
_INVALID_HANDLE = ctypes.c_void_p(-1).value
_STILL_ACTIVE = 259

# 令牌受限特征（deny-only 管理员组，跨语言判定用 SID 而非本地化文案）
_RESTRICTED_MARKER_SID = b"S-1-5-114"


class _STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_uint32), ("lpReserved", ctypes.c_wchar_p),
        ("lpDesktop", ctypes.c_wchar_p), ("lpTitle", ctypes.c_wchar_p),
        ("dwX", ctypes.c_uint32), ("dwY", ctypes.c_uint32),
        ("dwXSize", ctypes.c_uint32), ("dwYSize", ctypes.c_uint32),
        ("dwXCountChars", ctypes.c_uint32), ("dwYCountChars", ctypes.c_uint32),
        ("dwFillAttribute", ctypes.c_uint32), ("dwFlags", ctypes.c_uint32),
        ("wShowWindow", ctypes.c_uint16), ("cbReserved2", ctypes.c_uint16),
        ("lpReserved2", ctypes.c_void_p), ("hStdInput", ctypes.c_void_p),
        ("hStdOutput", ctypes.c_void_p), ("hStdError", ctypes.c_void_p),
    ]


class _PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", ctypes.c_void_p), ("hThread", ctypes.c_void_p),
        ("dwProcessId", ctypes.c_uint32), ("dwThreadId", ctypes.c_uint32),
    ]


def _decode_console_output(raw: bytes) -> str:
    """cmd 重定向输出编码链：UTF-8 → GBK(中文控制台) → UTF-16 → 宽松替换。"""
    for enc in ("utf-8", "gbk", "utf-16-le"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return raw.decode("utf-8", "replace")


class RestrictedTokenSandbox:
    """SAFER 受限令牌沙箱（Windows 专属，特权剥离隔离）。"""

    def __init__(self, severity: Any = None):
        self.severity = severity

    def backend_name(self) -> str:
        return "restricted_token"

    @property
    def enforced_severities(self) -> frozenset:
        """本后端真实强制的能力（特权剥离≠severity 枚举语义）。"""
        return frozenset()

    def available(self) -> bool:
        """win32 且 SAFER API 可达（轻探测：不 spawn，仅 API 绑定）。"""
        if os.name != "nt":
            return False
        try:
            adv = ctypes.windll.advapi32
            return hasattr(adv, "SaferComputeTokenFromLevel") and hasattr(
                ctypes.windll.kernel32, "CreateProcessAsUserW"
            )
        except Exception:
            return False

    def _make_inheritable(self, path: str) -> int:
        k32 = ctypes.windll.kernel32
        h = k32.CreateFileW(
            path, _GENERIC_WRITE, 0, None, _CREATE_ALWAYS, _FILE_ATTRIBUTE_NORMAL, None
        )
        if h in (_INVALID_HANDLE, 0):
            raise OSError(f"CreateFileW 失败: {ctypes.GetLastError()}")
        k32.SetHandleInformation(h, _HANDLE_FLAG_INHERIT, _HANDLE_FLAG_INHERIT)
        return h

    def _derive_restricted_token(self) -> int:
        adv = ctypes.windll.advapi32
        h_level = ctypes.c_void_p()
        if not adv.SaferCreateLevel(
            _SAFER_SCOPEID_USER, _SAFER_LEVELID_NORMALUSER, 0,
            ctypes.byref(h_level), None,
        ):
            raise OSError(f"SaferCreateLevel 失败: {ctypes.GetLastError()}")
        h_token = ctypes.c_void_p()
        try:
            if not adv.SaferComputeTokenFromLevel(h_level, None, ctypes.byref(h_token), 0, None):
                raise OSError(f"SaferComputeTokenFromLevel 失败: {ctypes.GetLastError()}")
        finally:
            adv.SaferCloseLevel(h_level)
        return h_token.value

    def execute(
        self,
        command: str,
        timeout: float = 30.0,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """受限令牌执行：特权剥离隔离；输出经临时文件回传。"""
        import subprocess as _sp

        k32 = ctypes.windll.kernel32
        base: Dict[str, Any] = {
            "sandbox": self.backend_name(),
            # 诚实自报：受限令牌生效（特权剥离），但 severity 声明（网络/FS）
            # 不由本后端强制——调用方按 enforced_severities 核查
            "sandbox_enforced": True,
            "isolated": True,
            "enforced_severities": list(self.enforced_severities),
            "isolation_kind": "privilege_drop",
        }
        if self.severity is not None and getattr(self.severity, "value", "none") != "none":
            base["warning"] = (
                f"受限令牌后端已剥离特权，但 severity={self.severity.value} "
                "声明的网络/文件系统隔离未强制（SRP 无该语义）"
            )

        out_path = os.path.join(tempfile.gettempdir(), f"neurova_sbx_out_{os.getpid()}_{int(time.time()*1000)}")
        err_path = out_path.replace("_out_", "_err_")
        h_token = None
        try:
            h_token = self._derive_restricted_token()
            h_out = self._make_inheritable(out_path)
            h_err = self._make_inheritable(err_path)

            si = _STARTUPINFOW()
            si.cb = ctypes.sizeof(si)
            si.dwFlags = _STARTF_USESTDHANDLES
            si.hStdOutput = h_out
            si.hStdError = h_err
            pi = _PROCESS_INFORMATION()

            ok = ctypes.windll.advapi32.CreateProcessAsUserW(
                h_token, None, ctypes.c_wchar_p(command), None, None,
                1,  # bInheritHandles
                _CREATE_NO_WINDOW, None, cwd,
                ctypes.byref(si), ctypes.byref(pi),
            )
            k32.CloseHandle(h_out)
            k32.CloseHandle(h_err)
            if not ok:
                raise OSError(f"CreateProcessAsUserW 失败: {ctypes.GetLastError()}")

            # 进程级超时（超过即终止——受限令牌子进程无完成的必要条件）
            wait_ms = int(timeout * 1000)
            status = k32.WaitForSingleObject(pi.hProcess, wait_ms)
            if status == _STILL_ACTIVE or status == 0x102:
                k32.TerminateProcess(pi.hProcess, 1)
                return {
                    **base,
                    "success": False,
                    "output": "",
                    "error": f"Command timed out after {timeout} seconds",
                    "return_code": -1,
                }
            code = ctypes.c_uint32(-1)
            k32.GetExitCodeProcess(pi.hProcess, ctypes.byref(code))
            k32.CloseHandle(pi.hProcess)
            k32.CloseHandle(pi.hThread)

            stdout = _decode_console_output(open(out_path, "rb").read())
            stderr = _decode_console_output(open(err_path, "rb").read())
            return {
                **base,
                "success": code.value == 0,
                "output": stdout,
                "error": stderr,
                "return_code": code.value,
            }
        except OSError as e:
            return {
                **base,
                "success": False,
                "output": "",
                "error": str(e),
                "return_code": -1,
            }
        finally:
            if h_token:
                k32.CloseHandle(h_token)
            for p in (out_path, err_path):
                try:
                    if os.path.exists(p):
                        os.remove(p)
                except OSError:
                    pass

    def verify_restriction_marker(self) -> bool:
        """自证：沙箱内 whoami /groups 含 deny-only 管理员组 SID（真隔离证据）。"""
        system_root = os.environ.get("SystemRoot", r"C:\Windows")
        whoami = os.path.join(system_root, "System32", "whoami.exe")
        if not os.path.exists(whoami):
            return False
        result = self.execute(f'"{whoami}" /groups', timeout=15)
        if not result["success"]:
            return False
        # 原始输出被解码过——SID 是 ASCII，跨编码保留
        return _RESTRICTED_MARKER_SID.decode() in result["output"] or _RESTRICTED_MARKER_SID.decode() in result["error"]


# 模块级缓存实例
_restricted_instance: Optional[RestrictedTokenSandbox] = None


def get_restricted_token_sandbox() -> RestrictedTokenSandbox:
    global _restricted_instance
    if _restricted_instance is None:
        _restricted_instance = RestrictedTokenSandbox()
    return _restricted_instance
