"""Computer Use 环境安装 / 体检脚本

一次性搞定桌面控制 + 浏览器自动化所需的后端环境：

    python scripts/setup_computer_use.py            # 体检：报告各项能力是否就绪
    python scripts/setup_computer_use.py --install  # 安装缺失的包 + Chromium 内核

覆盖内容：
- Pillow        桌面截图（PIL.ImageGrab）
- pyautogui     鼠标/键盘控制
- playwright    浏览器自动化（含 Chromium 内核下载，约 150MB）

说明：所有包都装进"当前解释器"（即运行本脚本的 python/venv），
后端必须用同一解释器启动才能生效。项目运行时请使用 .venv。
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
import typing
from pathlib import Path

# pip 包名（带版本约束）→ 导入名映射
PYTHON_PACKAGES: typing.Dict[str, str] = {
    "pillow": "Pillow>=10.0.0",
    "pyautogui": "pyautogui>=0.9.54",
    "playwright": "playwright>=1.40.0",
}

IMPORT_NAMES: typing.Dict[str, str] = {
    "pillow": "PIL",
    "pyautogui": "pyautogui",
    "playwright": "playwright",
}


def _importable(import_name: str) -> bool:
    try:
        return importlib.util.find_spec(import_name) is not None
    except (ImportError, ValueError):
        return False


def _ms_playwright_dir() -> Path:
    """Playwright 浏览器内核缓存目录（Windows 用 LOCALAPPDATA，其余用 ~/.cache）"""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "ms-playwright"
    return Path.home() / ".cache" / "ms-playwright"


def chromium_installed() -> bool:
    """探测 Chromium 内核是否已下载"""
    base = _ms_playwright_dir()
    return base.exists() and any(base.glob("chromium-*"))


def probe_capabilities() -> typing.Dict[str, bool]:
    """探测 Computer Use 各项能力在当前解释器中的就绪状态"""
    caps: typing.Dict[str, bool] = {}
    for pkg, import_name in IMPORT_NAMES.items():
        caps[pkg] = _importable(import_name)
    # Chromium 仅在 playwright 包就绪时才有意义，但独立报告便于诊断半装状态
    caps["chromium"] = chromium_installed()
    return caps


def missing_packages() -> typing.List[str]:
    """列出当前解释器缺失的包名（probe 的 key 形式）"""
    return [pkg for pkg in PYTHON_PACKAGES if not _importable(IMPORT_NAMES[pkg])]


def install_missing(packages: typing.Optional[typing.List[str]] = None) -> typing.Dict[str, bool]:
    """pip 安装缺失的包到当前解释器；返回每个包的安装结果"""
    targets = packages if packages is not None else missing_packages()
    results: typing.Dict[str, bool] = {}
    for pkg in targets:
        spec = PYTHON_PACKAGES.get(pkg)
        if not spec:
            results[pkg] = False
            continue
        print(f"  → pip install {spec} ...")
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "install", spec],
            capture_output=True,
            text=True,
        )
        ok = proc.returncode == 0 and _importable(IMPORT_NAMES[pkg])
        results[pkg] = ok
        print(f"    {'✓ 成功' if ok else '✗ 失败'}")
        if not ok and proc.stderr:
            print(f"    {proc.stderr.strip().splitlines()[-1]}")
    return results


def install_chromium() -> bool:
    """下载 Playwright 的 Chromium 内核"""
    if not _importable("playwright"):
        print("  ✗ playwright 未安装，无法下载 Chromium")
        return False
    if chromium_installed():
        print("  ✓ Chromium 内核已存在，跳过下载")
        return True
    print("  → playwright install chromium （约 150MB，请耐心等待）...")
    proc = subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
    )
    ok = proc.returncode == 0 and chromium_installed()
    print(f"    {'✓ 成功' if ok else '✗ 失败'}")
    return ok


def print_report() -> bool:
    """打印能力体检报告；返回是否全部就绪"""
    caps = probe_capabilities()
    labels = {
        "pillow": ("桌面截图", "Pillow"),
        "pyautogui": ("鼠标/键盘控制", "pyautogui"),
        "playwright": ("浏览器自动化", "playwright"),
        "chromium": ("Chromium 内核", "playwright install chromium"),
    }
    print("Computer Use 能力体检")
    print(f"  解释器: {sys.executable}")
    all_ready = True
    for key, (label, hint) in labels.items():
        ready = caps.get(key, False)
        all_ready = all_ready and ready
        mark = "✓" if ready else "✗"
        extra = "" if ready else f"   ← 缺少，可执行: pip install {hint}"
        print(f"  {mark} {label} ({key}){extra}")
    if all_ready:
        print("全部就绪。Agent 可使用 computer_* / browser_* 工具。")
    else:
        print("存在缺失项，可执行: python scripts/setup_computer_use.py --install")
    return all_ready


def main(argv: typing.Optional[typing.List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Computer Use 环境安装/体检")
    parser.add_argument("--install", action="store_true", help="安装缺失依赖 + Chromium 内核")
    args = parser.parse_args(argv)

    if args.install:
        missing = missing_packages()
        if missing:
            print(f"安装缺失包: {', '.join(missing)}")
            install_missing(missing)
        else:
            print("Python 包均已就绪")
        install_chromium()
        print()

    ok = print_report()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
