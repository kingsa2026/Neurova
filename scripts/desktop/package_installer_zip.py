# -*- coding: utf-8 -*-
"""Neurova 安装器打包：tauri build 产物 → 单文件安装器（QQ 式向导）。

默认产物 = Neurova_Setup_<版本>_x64.exe：
    WPF 界面壳内嵌 NSIS 静默内核（/resource），用户只见 QQ 式向导，
    单文件分发，无传统界面暴露。

--zip  legacy 模式：三文件 zip（壳 + 内核 + Logo），内核可独立双击安装。

用法（仓库根）：
    .venv/Scripts/python.exe scripts/desktop/package_installer_zip.py
    .venv/Scripts/python.exe scripts/desktop/package_installer_zip.py --skip-tauri
    .venv/Scripts/python.exe scripts/desktop/package_installer_zip.py --zip
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
WPF_DIR = REPO / "NeurUI" / "src-tauri" / "installer-wpf"
TAURI_CONF = REPO / "NeurUI" / "src-tauri" / "tauri.conf.json"
NSIS_BUNDLE_DIR = REPO / "NeurUI" / "src-tauri" / "target" / "release" / "bundle" / "nsis"
LOGO_SRC = REPO / "NeurUI" / "public" / "img" / "NEUROVA-LOGO350white.png"
OUT_DIR = REPO / "dist" / "installer"

KERNEL_PREFIX = "Neurova_"          # NSIS 产物名前缀（Neurova_<ver>_x64-setup.exe）
KERNEL_SUFFIX = "-setup.exe"
SHELL_NAME = "installer-shell.exe"
KERNEL_NAME = "Neurova-kernel-setup.exe"
ICON_NAME = "neurova-icon.png"


def log(msg: str) -> None:
    print(f"[pkg] {msg}", flush=True)


def run(cmd: list[str] | str, shell: bool = False, cwd: Path | None = None) -> int:
    r = subprocess.run(cmd, shell=shell, cwd=str(cwd or REPO))
    return r.returncode


def signing_identity_of_tauri_conf() -> str | None:
    """产品配置里的签名事实源：`bundle.windows.certificateThumbprint`。

    只**读**不算 —— 换机器的问题在打包侧解决，不在这里抹掉指纹
    （有证书的机器仍要按它签）。
    """
    import json

    conf = json.loads(TAURI_CONF.read_text(encoding="utf-8"))
    return conf.get("bundle", {}).get("windows", {}).get("certificateThumbprint")


def cert_is_in_store(thumbprint: str) -> bool:
    """本机证书库里有没有这枚（含私钥的）证书。

    为什么必须查：指纹写死在产品配置里，而私钥不进仓 —— 换一台构建机时
    `tauri build` 会在签名这一步硬失败（Rust 侧早已编译成功），
    失败形态与「代码有 bug」一模一样，根因却是环境依赖。故构建前先问一句
    「这台机器签得动吗」，把判断放在打包侧。
    """
    if os.name != "nt":
        return False
    ps = (
        "try { "
        f"$c = Get-Item -Path Cert:\\CurrentUser\\My\\{thumbprint},"
        f"Cert:\\LocalMachine\\My\\{thumbprint} -ErrorAction Stop; "
        "if ($c) { exit 0 } else { exit 1 } } catch { exit 1 }"
    )
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        capture_output=True, text=True,
    )
    return r.returncode == 0


def tauri_signing_args() -> tuple[list[str], bool]:
    """返回（`tauri build` 的附加参数, 本机是否真能签名）。

    证书在位 → 不加参数，按产品配置签；证书缺席 → 经 `--config` 覆盖成不签，
    并把「本产物未签名」这一事实**交回调用点去点名**（不静默弱化）。
    """
    thumb = signing_identity_of_tauri_conf()
    if thumb and cert_is_in_store(thumb):
        log(f"签名证书在位（{thumb}），按产品配置签名")
        return [], True
    if not thumb:
        log("产品配置未声明签名指纹，本次构建不签名")
        return [], False
    log(f"签名证书缺席（{thumb} 不在本机证书库），本次构建不签名 —— 产物将显式标注")
    # 覆盖成 null = 不签；只在本次构建生效，不改产品配置。
    return ["--config", '{"bundle":{"windows":{"certificateThumbprint":null}}}'], False


def build_tauri() -> Path:
    """npm run build:desktop + npx tauri build，返回 NSIS 产物路径。"""
    log("前端构建（vite build，desktop 环境）…")
    if run("npm run build:desktop", shell=True, cwd=REPO / "NeurUI") != 0:
        raise RuntimeError("前端构建失败（npm run build:desktop）")
    extra, signed = tauri_signing_args()
    build_tauri.last_signed = signed  # 交回调用点：不签名的产物要点名
    log("tauri build（Rust release + NSIS bundle，可能 10 分钟+）…")
    cmd = " ".join(["npx", "tauri", "build", *extra])
    if run(cmd, shell=True, cwd=REPO / "NeurUI") != 0:
        raise RuntimeError("tauri build 失败")
    return find_kernel()


build_tauri.last_signed = False


def find_kernel() -> Path:
    """定位最新 NSIS 产物（按修改时间取最新一个 Neurova_*-setup.exe）。"""
    if not NSIS_BUNDLE_DIR.is_dir():
        raise RuntimeError(f"NSIS 产物目录不存在：{NSIS_BUNDLE_DIR}（先跑 tauri build）")
    candidates = sorted(
        NSIS_BUNDLE_DIR.glob(f"{KERNEL_PREFIX}*{KERNEL_SUFFIX}"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise RuntimeError(f"{NSIS_BUNDLE_DIR} 下无 {KERNEL_PREFIX}*{KERNEL_SUFFIX}")
    return candidates[0]


def inject_signtool_wrapper() -> None:
    """signtool 包装器：tauri 批量签名几十个 DLL 时 digicert 时间戳服务器
    从国内网络间歇可达，单次瞬时失败即废整轮 build（黑盒 0x80093102）。
    包装器记录每次调用参数与输出到 %TEMP%\\neurova-signtool-wrap.log，
    失败自动重试 3 次（每次间隔 3s）。"""
    wrapper = WPF_DIR / "bin" / "signtool-wrapper.exe"
    if wrapper.exists():
        os.environ["TAURI_WINDOWS_SIGNTOOL_PATH"] = str(wrapper)
        log(f"signtool 包装器已注入（重试 3 次 + 调用日志）：{wrapper}")


def build_shell(kernel: Path | None) -> Path:
    """编译 WPF 壳。kernel 传入 = 内嵌内核（单文件模式）。返回壳 exe 路径。"""
    if kernel is not None:
        log(f"编译 WPF 界面壳（内嵌内核 {kernel.stat().st_size / 1048576:.0f} MB，单文件模式）…")
        # 显式 .\ 前缀：cmd 设 NoDefaultCurrentDirectoryInExePath=1 时不从 cwd 裸名解析
        if run(f'.\\build.cmd "{kernel}" "{LOGO_SRC}"', shell=True, cwd=WPF_DIR) != 0:
            raise RuntimeError("WPF 壳编译失败（build.cmd）")
    else:
        log("编译 WPF 界面壳（sidecar 模式）…")
        if run(".\\build.cmd", shell=True, cwd=WPF_DIR) != 0:
            raise RuntimeError("WPF 壳编译失败（build.cmd）")
    shell = WPF_DIR / "bin" / SHELL_NAME
    if not shell.exists():
        raise RuntimeError(f"壳产物缺失：{shell}")
    return shell


def validate_lean_backend() -> None:
    """路线 B 体积红线守卫：resources/backend/ 下不应出现 python/、node/。"""
    backend = REPO / "NeurUI" / "src-tauri" / "resources" / "backend"
    offenders = []
    for name in ("python", "node"):
        if (backend / name).exists():
            offenders.append(name)
    if offenders:
        raise RuntimeError(
            f"安装包体积红线：backend/ 下发现运行时目录 {offenders}，"
            "请确认 bundle_backend.py 已切换路线 B（首次启动自动下载）。"
        )


def version_of(kernel: Path) -> str:
    stem = kernel.name[len(KERNEL_PREFIX):-len(KERNEL_SUFFIX)]
    return stem.split("_")[0]


def package(skip_tauri: bool, legacy_zip: bool, open_dir: bool) -> int:
    inject_signtool_wrapper()

    # 1. NSIS 内核
    if skip_tauri:
        kernel = find_kernel()
        log(f"跳过 tauri build，使用现有内核：{kernel.name}")
    else:
        kernel = build_tauri()
    log(f"NSIS 内核：{kernel.name}（{kernel.stat().st_size / 1048576:.0f} MB）")

    validate_lean_backend()

    ver = version_of(kernel)
    stamp = datetime.now().strftime("%Y%m%d")
    # 不签名的产物必须在**文件名**上被点名：悄悄少签名是表面抹除（教义第 2 条），
    # 而名字是分发链上唯一跟着包走、人一眼能看到的标记。
    signed = getattr(build_tauri, "last_signed", False) if not skip_tauri else None
    mark = "" if signed is not False else "_unsigned"
    if signed is False:
        log("产物未签名（证书不在本机证书库）—— 文件名带 _unsigned 标记，分发时如实告知")

    if legacy_zip:
        # legacy：三文件 zip，内核可独立双击安装
        shell = build_shell(None)
        if not LOGO_SRC.exists():
            raise RuntimeError(f"Logo 缺失：{LOGO_SRC}")
        out_path = OUT_DIR / f"Neurova_Installer_{ver}_{stamp}_x64{mark}.zip"
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            zf.write(shell, SHELL_NAME)
            zf.write(kernel, KERNEL_NAME)
            zf.write(LOGO_SRC, ICON_NAME)
        size_mb = out_path.stat().st_size / 1048576
        log(f"legacy 三件套完成：{out_path}（{size_mb:.0f} MB）")
    else:
        # 默认：单文件 exe（QQ 式向导，内核内嵌）
        shell = build_shell(kernel)
        out_path = OUT_DIR / f"Neurova_Setup_{ver}_{stamp}_x64{mark}.exe"
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.copy2(shell, out_path)
        size_mb = out_path.stat().st_size / 1048576
        log(f"单文件安装器完成：{out_path}（{size_mb:.0f} MB）")

    if open_dir:
        subprocess.run(["explorer", "/select,", str(out_path)])
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Neurova 安装器打包")
    ap.add_argument("--skip-tauri", action="store_true",
                    help="跳过前端+tauri build，直接用现有 NSIS 产物")
    ap.add_argument("--zip", action="store_true",
                    help="legacy 三件套 zip（默认为单文件 exe，内核内嵌）")
    ap.add_argument("--open", action="store_true", help="完成后打开产物所在目录")
    args = ap.parse_args()
    return package(skip_tauri=args.skip_tauri, legacy_zip=args.zip, open_dir=args.open)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as e:
        log(f"失败：{e}")
        sys.exit(1)
