# -*- coding: utf-8 -*-
"""
AppContainer 沙箱真实现（遗留③，Windows 专属）

机制：CreateAppContainerProfile（幂等）→ Derive SID →
STARTUPINFOEXW + UpdateProcThreadAttribute(SECURITY_CAPABILITIES) →
CreateProcessW(EXTENDED_STARTUPINFO_PRESENT)。子进程 Low integrity
（S-1-16-4096）+ 无用户组特权（Administrators deny-only）+ 默认断网
（无 internetClient capability）。

实证锚点（本机实测）：沙箱内 whoami /groups 含
- Mandatory Label\\Low Mandatory Level (S-1-16-4096)
- Administrators/S-1-5-114 全部"仅用于拒绝的组"

实现要点（ctypes 三坑，全部踩过）：
1. DeriveAppContainerSidFromAppContainerName 第二参是 **PSID\***（非字符串）
2. lpCommandLine 需可写缓冲（create_unicode_buffer），c_wchar_p 只读会 err 2
3. **必须显式传 cwd**——容器进程 CWD 解析失败会得到"当前目录无效"
4. 结构按 c_void_p 传（argtypes+cast），PI 用独立实例（内联 byref 会 segfault）
5. 输出回传：目录先 icacls 授容器 SID 写权，子进程 cmd 自重定向到文件
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import secrets
import subprocess
import tempfile
import time
from typing import Any, Dict, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

# ── Win32 常量 ──
_EXTENDED_STARTUPINFO_PRESENT = 0x00080000
_CREATE_UNICODE_ENVIRONMENT = 0x00000400
_CREATE_NO_WINDOW = 0x08000000
_STARTF_USESTDHANDLES = 0x100
_HANDLE_FLAG_INHERIT = 1
_GENERIC_WRITE = 0x40000000
_FILE_ATTRIBUTE_NORMAL = 0x80
_PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES = 0x00020009
_WAIT_OBJECT_0 = 0

_AC_NAME_PREFIX = "neurova_ac_"


class _SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wt.DWORD)]


class _SECURITY_CAPABILITIES(ctypes.Structure):
    _fields_ = [("AppContainerSid", ctypes.c_void_p),
                ("Capabilities", ctypes.POINTER(_SID_AND_ATTRIBUTES)),
                ("CapabilityCount", wt.DWORD)]


class _SIW(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("lpReserved", wt.LPWSTR), ("lpDesktop", wt.LPWSTR),
                ("lpTitle", wt.LPWSTR), ("dwX", wt.DWORD), ("dwY", wt.DWORD),
                ("dwXSize", wt.DWORD), ("dwYSize", wt.DWORD), ("dwXCountChars", wt.DWORD),
                ("dwYCountChars", wt.DWORD), ("dwFillAttribute", wt.DWORD), ("dwFlags", wt.DWORD),
                ("wShowWindow", wt.WORD), ("cbReserved2", wt.WORD), ("lpReserved2", ctypes.c_void_p),
                ("hStdInput", ctypes.c_void_p), ("hStdOutput", ctypes.c_void_p),
                ("hStdError", ctypes.c_void_p)]


class _SIEX(ctypes.Structure):
    _anonymous_ = ["si"]
    _fields_ = [("si", _SIW), ("lpAttributeList", ctypes.c_void_p)]


class _PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [("hProcess", ctypes.c_void_p), ("hThread", ctypes.c_void_p),
                ("dwProcessId", wt.DWORD), ("dwThreadId", wt.DWORD)]


class _DLL:
    """延迟绑定 + 全 argtypes（64 位指针安全——探针 v1 教训）"""

    loaded = False

    @classmethod
    def load(cls) -> bool:
        if cls.loaded:
            return True
        try:
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            userenv = ctypes.WinDLL("userenv", use_last_error=True)
            advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

            userenv.CreateAppContainerProfile.argtypes = [
                wt.LPCWSTR, wt.LPCWSTR, wt.LPCWSTR,
                ctypes.c_void_p, wt.DWORD, ctypes.POINTER(ctypes.c_void_p),
            ]
            userenv.CreateAppContainerProfile.restype = ctypes.HRESULT
            userenv.DeriveAppContainerSidFromAppContainerName.argtypes = [
                wt.LPCWSTR, ctypes.POINTER(ctypes.c_void_p),
            ]
            userenv.DeriveAppContainerSidFromAppContainerName.restype = ctypes.HRESULT
            userenv.DeleteAppContainerProfile.argtypes = [wt.LPCWSTR]
            userenv.DeleteAppContainerProfile.restype = ctypes.HRESULT
            advapi32.ConvertSidToStringSidW.argtypes = [
                ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar_p),
            ]
            advapi32.ConvertSidToStringSidW.restype = wt.BOOL
            k32.InitializeProcThreadAttributeList.argtypes = [
                ctypes.c_void_p, wt.DWORD, wt.DWORD, ctypes.POINTER(ctypes.c_size_t),
            ]
            k32.InitializeProcThreadAttributeList.restype = wt.BOOL
            k32.UpdateProcThreadAttribute.argtypes = [
                ctypes.c_void_p, wt.DWORD, ctypes.c_void_p, ctypes.c_void_p,
                ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p,
            ]
            k32.UpdateProcThreadAttribute.restype = wt.BOOL
            k32.DeleteProcThreadAttributeList.argtypes = [ctypes.c_void_p]
            k32.CreateProcessW.restype = wt.BOOL

            cls.k32 = k32
            cls.userenv = userenv
            cls.advapi32 = advapi32
            cls.loaded = True
            return True
        except Exception as e:
            logger.warning("AppContainer API 绑定失败: %s", e)
            return False


def _sid_to_string(psid: int) -> Optional[str]:
    s = ctypes.c_wchar_p()
    if not _DLL.advapi32.ConvertSidToStringSidW(psid, ctypes.byref(s)):
        return None
    return s.value


def _decode_console_output(raw: bytes) -> str:
    for enc in ("utf-8", "gbk", "utf-16-le"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return raw.decode("utf-8", "replace")


class AppContainerSandbox:
    """AppContainer 沙箱（Low integrity + 默认断网 + 特权剥离）。"""

    def __init__(self, severity: Any = None):
        self.severity = severity
        self._profile: Optional[str] = None
        self._psid: Optional[int] = None

    def backend_name(self) -> str:
        return "appcontainer"

    def available(self) -> bool:
        """win32 且 API 绑定成功。profile 在首次 execute 时创建（幂等）。"""
        if os.name != "nt":
            return False
        return _DLL.load()

    def enforced_severities(self) -> frozenset:
        """AppContainer 默认 deny-all → 网络隔离真实生效（无 internetClient）。"""
        from neurova.sandbox.exec_sandbox import SandboxSeverity

        return frozenset({SandboxSeverity.NETWORK_OFF})

    def _create_profile_fresh(self) -> tuple:
        """一次性创建全新 AppContainer profile（探针实证：Derive 旧 profile
        的 SID 用于 CreateProcess 会 err 2——profile 实体可能已失效，
        fresh CreateAppContainerProfile 是唯一可靠路径）。返回 (name, psid)。"""
        userenv = _DLL.userenv
        name = _AC_NAME_PREFIX + secrets.token_hex(4)
        psid = ctypes.c_void_p()
        hr = userenv.CreateAppContainerProfile(
            name, "Neurova Sandbox", "Neurova tool execution sandbox",
            None, 0, ctypes.byref(psid),
        )
        if hr != 0:
            raise OSError(f"CreateAppContainerProfile hr=0x{hr & 0xFFFFFFFF:x}")
        logger.debug("AppContainer profile 创建: %s", name)
        return name, psid.value

    def _delete_profile(self, name: str) -> None:
        try:
            _DLL.userenv.DeleteAppContainerProfile(name)
        except Exception:
            pass

    def _grant_dir_access(self, directory: str, sid_string: str) -> None:
        """容器对输出目录的写权限（icacls 授 ACE）。"""
        icacls = os.path.join(os.environ["SystemRoot"], "System32", "icacls.exe")
        subprocess.run(
            [icacls, directory, "/grant", f"*{sid_string}:(OI)(CI)(R,W)"],
            capture_output=True, timeout=10,
        )

    def execute(
        self,
        command: str,
        timeout: float = 30.0,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """AppContainer 内执行命令。

        注意（探针实证）：cwd 必须显式传递——容器进程 CWD 解析失败会得到
        "当前目录无效"。输出经容器可写的临时目录文件回传。
        """
        if not _DLL.load():
            return {
                "sandbox": self.backend_name(),
                "sandbox_enforced": False,
                "isolated": False,
                "success": False,
                "output": "",
                "error": "AppContainer API 绑定不可用",
                "return_code": -1,
            }
        k32 = _DLL.k32
        base: Dict[str, Any] = {
            "sandbox": self.backend_name(),
            "sandbox_enforced": True,
            "isolated": True,
            "isolation_kind": "appcontainer",
        }

        out_dir = tempfile.mkdtemp(prefix="nv_ac_")
        out_path = os.path.join(out_dir, "out.txt")
        # 探针实证：CWD 必须是容器已被授权（icacls）的目录——TEMP 等外部
        # 目录会得到"当前目录无效"，且容器对该目录无写权时输出丢失
        work_dir = cwd if (cwd and os.path.isdir(cwd)) else out_dir

        h_process = None
        h_thread = None
        profile_name = None
        try:
            profile_name, psid = self._create_profile_fresh()
            s = ctypes.c_wchar_p()
            _DLL.advapi32.ConvertSidToStringSidW(psid, ctypes.byref(s))
            sid_string = s.value
            self._grant_dir_access(out_dir, sid_string)

            # attribute list
            size = ctypes.c_size_t(0)
            k32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
            buf = ctypes.create_string_buffer(size.value)
            if not k32.InitializeProcThreadAttributeList(buf, 1, 0, ctypes.byref(size)):
                raise OSError(f"InitializeProcThreadAttributeList err {ctypes.get_last_error()}")
            sc = _SECURITY_CAPABILITIES()
            sc.AppContainerSid = psid
            sc.CapabilityCount = 0
            if not k32.UpdateProcThreadAttribute(
                buf, 0, _PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES,
                ctypes.byref(sc), ctypes.sizeof(sc), None, None,
            ):
                raise OSError(f"UpdateProcThreadAttribute err {ctypes.get_last_error()}")

            # 子进程 cmd 自重定向（容器可写目录）
            cmdline = ctypes.create_unicode_buffer(
                f'cmd /c {command} > "{out_path}" 2>&1'
            )
            si = _SIEX()
            si.si.cb = ctypes.sizeof(si)
            si.lpAttributeList = ctypes.cast(buf, ctypes.c_void_p)
            pi = _PROCESS_INFORMATION()

            ok = k32.CreateProcessW(
                None, cmdline, None, None, 0,
                _EXTENDED_STARTUPINFO_PRESENT | _CREATE_UNICODE_ENVIRONMENT | _CREATE_NO_WINDOW,
                None, work_dir,
                ctypes.cast(ctypes.byref(si), ctypes.c_void_p),
                ctypes.byref(pi),
            )
            if not ok:
                raise OSError(f"CreateProcessW err {ctypes.get_last_error()}")
            h_process, h_thread = pi.hProcess, pi.hThread

            status = k32.WaitForSingleObject(pi.hProcess, int(timeout * 1000))
            if status != _WAIT_OBJECT_0:
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

            text = ""
            for _ in range(10):
                try:
                    text = _decode_console_output(open(out_path, "rb").read())
                    break
                except PermissionError:
                    time.sleep(0.3)
            stdout, _, stderr = text.partition("\n---stderr---\n") if "\n---stderr---\n" in text else (text, "", "")
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
            if h_process:
                k32.CloseHandle(h_process)
            if h_thread:
                k32.CloseHandle(h_thread)
            if profile_name:
                self._delete_profile(profile_name)  # 一次性容器：用完即删
            try:
                for f in os.listdir(out_dir):
                    try:
                        os.remove(os.path.join(out_dir, f))
                    except OSError:
                        pass
                os.rmdir(out_dir)
            except OSError:
                pass

    def verify_restriction_marker(self) -> bool:
        """自证：沙箱内 whoami /groups 含 Low integrity（S-1-16-4096）。"""
        system_root = os.environ.get("SystemRoot", r"C:\Windows")
        whoami = os.path.join(system_root, "System32", "whoami.exe")
        if not os.path.exists(whoami):
            return False
        # cmd /c 形态（探针实证：带引号绝对路径直接跑会 err 文件缺失）
        result = self.execute(f"cmd /c whoami /groups", timeout=20)
        if not result["success"]:
            return False
        return "S-1-16-4096" in result["output"]


def get_appcontainer_sandbox() -> AppContainerSandbox:
    from neurova.sandbox.exec_sandbox import SandboxSeverity

    return AppContainerSandbox(SandboxSeverity.NETWORK_OFF)
