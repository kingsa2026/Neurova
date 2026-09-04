# -*- coding: utf-8 -*-
"""后端启动环境预检：torch DLL 故障 → VC++ 运行库自动下载安装。

背景（2026-09-04 安装版日志）：干净机器上 `torch/lib/c10.dll` 报
WinError 1114（DLL 初始化例程失败），3 个路由 + Default Agent 初始化
失败。典型根因是目标机缺 VC++ 2015-2022 x64 运行库（开发机装了全套
开发工具所以从不复现）。

预检流程（preflight_torch_runtime，任何失败只告警、不阻断启动）：
1. 试导入 torch；OSError 且 winerror=1114（或 torch 的
   "Error loading *.dll" 文案）→ 判定 DLL 故障
2. 查注册表 VC++ 2015-2022 x64 运行库版本（<14.30 视为缺 2022 运行库）
3. 缺失 → 从官方固定 URL（aka.ms → Microsoft CDN）下载 vc_redist.x64.exe，
   校验 Microsoft Authenticode 签名后提权静默安装（触发一次 UAC）
4. 装完用独立子进程复验 torch 可导入（DLL 加载失败会污染当前进程，
   进程内重试不可信）

仅 Windows 生效；非 Windows 全部 no-op。
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# 官方永久链接：指向最新 VC++ 2022 x64 可再发行包（向下兼容 2015-2019）
VC_REDIST_URL = "https://aka.ms/vs/17/release/vc_redist.x64.exe"
# VC2022 运行库版本下限（2015-2019 系列止步 14.29，torch 需要新 msvcp140）
_VC2022_MIN = (14, 30)
_VC_REGISTRY_KEY = r"SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64"
_VC_SUCCESS_EXIT = {0, 3010}  # 3010 = 成功但需重启

_IS_WINDOWS = sys.platform == "win32"


@dataclass
class TorchDllProblem:
    winerror: int | None
    dll: str | None


@dataclass
class EnsureResult:
    installed: bool
    reason: str


def _import_torch():
    """seam：延迟导入 torch（测试注入点；导入本身重且可能抛 OSError）。"""
    import torch  # noqa: F401

    return torch


def detect_torch_dll_problem() -> TorchDllProblem | None:
    """试导入 torch；DLL 初始化类失败返回问题描述，其余返回 None。

    只识别 DLL 加载族错误（winerror=1114 初始化失败 / torch 的
    "Error loading xxx.dll" 文案）；普通 ImportError（未安装）不属于
    本模块职责，不误报。
    """
    try:
        _import_torch()
        return None
    except ImportError:
        return None
    except OSError as e:
        # Windows API 抛出时错误码在 winerror；两参构造的 OSError 在 errno。
        # 文案兜底：torch 的报错是 "Error loading ...dll or one of its dependencies"。
        code = getattr(e, "winerror", None) or getattr(e, "errno", None)
        msg = str(e)
        if code == 1114 or "error loading" in msg.lower():
            dll = None
            for token in msg.replace("(", " ").replace(")", " ").split():
                if token.lower().endswith(".dll"):
                    dll = token
                    break
            return TorchDllProblem(winerror=code, dll=dll)
        return None


def _read_vc_runtime_version() -> str | None:
    """读注册表 VC++ x64 运行库版本号（键缺失/异常 → None）。"""
    if not _IS_WINDOWS:
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _VC_REGISTRY_KEY) as key:
            version, _ = winreg.QueryValueEx(key, "Version")
            return str(version)
    except Exception:  # noqa: BLE001 - 键不存在/权限不足都视为未安装
        return None


def is_vc_redist_installed() -> bool:
    if not _IS_WINDOWS:
        return True
    version = _read_vc_runtime_version()
    if version is None:
        return False
    try:
        parts = version.lstrip("vV").split(".")
        return (int(parts[0]), int(parts[1])) >= _VC2022_MIN
    except (ValueError, IndexError):
        return False


def _download_file(url: str, dest: Path) -> None:
    """seam：下载安装包到本地（生产走 urllib；测试注入桩）。"""
    import urllib.request

    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "Neurova-EnvCheck/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as f:
        while True:
            chunk = resp.read(256 * 1024)
            if not chunk:
                break
            f.write(chunk)


def _verify_authenticode(exe: Path) -> bool:
    """校验下载包的 Microsoft Authenticode 签名——执行外部二进制的红线。

    签名无效/校验失败一律拒绝执行（供应链防线）。
    """
    try:
        r = subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                "(Get-AuthenticodeSignature -FilePath '%s').Status -eq 'Valid'"
                % exe,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0 and "True" in r.stdout


def _run_elevated_installer(exe: Path) -> int:
    """seam：提权静默安装（-Verb RunAs 触发 UAC），返回安装器退出码。"""
    ps = (
        "$p = Start-Process -FilePath '{exe}' "
        "-ArgumentList '/install','/quiet','/norestart' "
        "-Verb RunAs -Wait -PassThru; exit $p.ExitCode"
    ).format(exe=str(exe))
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=600,
        )
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning("vc_redist 提权执行失败: %s", e)
        return -1
    return r.returncode


def torch_imports_ok(python_exe: str | None = None) -> bool:
    """独立子进程复验 torch 可导入（当前进程 DLL 失败态不可信）。"""
    exe = python_exe or sys.executable
    try:
        r = subprocess.run(
            [exe, "-c", "import torch"],
            capture_output=True,
            timeout=300,
        )
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning("torch 复验子进程失败: %s", e)
        return False
    return r.returncode == 0


def ensure_vc_redist(
    auto_install: bool = True, download_dir: Path | None = None
) -> EnsureResult:
    """VC++ 运行库缺失时下载并提权安装；已装/关闭/非 Windows 时 no-op。"""
    if not _IS_WINDOWS:
        return EnsureResult(installed=False, reason="not-windows")
    if is_vc_redist_installed():
        return EnsureResult(installed=False, reason="already-installed")
    if not auto_install:
        return EnsureResult(installed=False, reason="auto-install-off")

    dest = (download_dir or Path(tempfile.gettempdir()) / "neurova_envcheck") / "vc_redist.x64.exe"
    try:
        logger.info("检测到 VC++ 2022 运行库缺失，开始下载: %s", VC_REDIST_URL)
        _download_file(VC_REDIST_URL, dest)
    except Exception as e:  # noqa: BLE001 - 网络/磁盘错误都归为下载失败
        return EnsureResult(installed=False, reason=f"download-failed: {e}")

    if not _verify_authenticode(dest):
        _cleanup(dest)
        return EnsureResult(installed=False, reason="signature-invalid")

    logger.info("开始安装 VC++ 运行库（如弹出 UAC 请确认）…")
    exit_code = _run_elevated_installer(dest)
    _cleanup(dest)
    if exit_code not in _VC_SUCCESS_EXIT:
        return EnsureResult(installed=False, reason=f"install-failed exit={exit_code}")
    return EnsureResult(installed=True, reason="ok")


def _cleanup(exe: Path) -> None:
    try:
        if exe.exists():
            exe.unlink()
    except OSError:
        pass


def preflight_torch_runtime(auto_install: bool = True) -> None:
    """启动预检编排入口。永不抛异常——环境修复失败不阻断后端启动。"""
    try:
        if not _IS_WINDOWS:
            return
        problem = detect_torch_dll_problem()
        if problem is None:
            return
        logger.warning(
            "torch DLL 加载异常 (winerror=%s, dll=%s)——典型根因是缺 VC++ 运行库，"
            "进入自动修复流程",
            problem.winerror,
            problem.dll,
        )
        result = ensure_vc_redist(auto_install=auto_install)
        if not result.installed:
            logger.warning(
                "VC++ 运行库自动安装未完成（%s）。请手动安装: %s（装完重启后端）",
                result.reason,
                VC_REDIST_URL,
            )
            return
        if torch_imports_ok():
            logger.info("VC++ 运行库安装完成，torch 已恢复可导入")
        else:
            logger.warning(
                "VC++ 运行库已安装但 torch 仍不可导入（可能需重启后端进程使 DLL 生效）"
            )
    except Exception as e:  # noqa: BLE001 - 预检绝不阻断启动
        logger.warning("torch 环境预检异常（忽略）: %s", e)
