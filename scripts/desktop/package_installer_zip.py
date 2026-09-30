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
import shutil
import subprocess
import tempfile
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

# tauri-bundler 的 NSIS 事实源（上游 `crates/tauri-bundler/src/bundle/windows/nsis/mod.rs`）：
#   NSIS 缓存落点 = <cache>/tauri/NSIS，makensis 只认缓存根下的 `makensis.exe`；
#   上游用 `env_remove("NSISDIR")` 显式丢弃该变量（mod.rs 第 705 行）——
#   故「把可用 NSIS 拷到某处、设 NSISDIR 指过去」是**死接线**（实机踩到，2026-09-30）。
TAURI_NSIS_DIRNAME = "NSIS"          # 缓存根下的 NSIS 目录名（上游 nsis_mod.rs 常量）
NSIS_CACHE_ENV = "NEUROVA_NSIS_CACHE"  # 覆盖缓存根；不设时按 LOCALAPPDATA 推导

KERNEL_PREFIX = "Neurova_"          # NSIS 产物名前缀（Neurova_<ver>_x64-setup.exe）
KERNEL_SUFFIX = "-setup.exe"
SHELL_NAME = "installer-shell.exe"
KERNEL_NAME = "Neurova-kernel-setup.exe"
ICON_NAME = "neurova-icon.png"


def log(msg: str) -> None:
    print(f"[pkg] {msg}", flush=True)


def run(cmd: list[str] | str, shell: bool = False, cwd: Path | None = None,
        env: dict | None = None) -> int:
    r = subprocess.run(cmd, shell=shell, cwd=str(cwd or REPO),
                       env={**os.environ, **(env or {})})
    return r.returncode


def tauri_nsis_cache_root() -> Path | None:
    """tauri 的 NSIS 缓存根（`<cache>/tauri`）。

    上游取 `settings.local_tools_directory().map(|d| d.join(".tauri"))
    .unwrap_or_else(|| dirs::cache_dir().join("tauri"))`。本仓 `tauri.conf.json`
    未声明 `localToolsDirectory`，故走 `dirs::cache_dir()` —— Windows 上即
    `%LOCALAPPDATA%`。这与 `tauri_build_env()` 重定向的是**同一个变量**，
    所以两处必须读同一份推导入参（单一事实源）。
    """
    if os.name != "nt":
        return None
    base = os.environ.get(NSIS_CACHE_ENV)
    if base:
        return Path(base)
    local = os.environ.get("LOCALAPPDATA", "")
    if not local:
        return None
    return Path(local) / "tauri"


def resolve_working_nsis() -> Path | None:
    """挑一份**实跑验证**能用的 NSIS 工具集，返回其目录（找不到返回 None）。

    为什么必须实跑：实机证据（2026-09-30，节点 orange-connector）——
    tauri 自带的 nsis-3.11 整树下 makensis（根 stub 与 `Bin\makensis.exe`）
    都报 `Unable to start child process, error 0x2`（stub 去起
    `Bin\makensis.exe` 失败），而系统 choco NSIS 3.13 的同一调用返回 `v3.13, exit 0`。
    「文件在位」与「跑得起来」是两件事 —— 只看文件存在与否的判据分辨不出它。

    逐个候选跑 `makensis /VERSION`，取第一份退出码为 0 的。候选含
    `NSIS_DIR_CANDIDATES` 与 `%ProgramFiles(x86)%`。全部不可用时返回 None，
    交回 bundler 响亮失败（不在这里悄悄产残缺包）。
    """
    candidates = []
    env_hint = os.environ.get("NSIS_HOME")
    if env_hint:
        candidates.append(Path(env_hint))
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    candidates += [Path(pf86) / "NSIS", Path(pf) / "NSIS"]
    for cand in candidates:
        exe = cand / "makensis.exe"
        if not exe.exists():
            continue
        try:
            r = subprocess.run([str(exe), "/VERSION"], capture_output=True,
                               text=True, timeout=30)
        except OSError:
            continue
        if r.returncode == 0:
            log(f"可用 NSIS：{cand}（makensis {r.stdout.strip() or r.stderr.strip()}）")
            return cand
        log(f"NSIS 候选不可用（exit {r.returncode}）：{cand}")
    return None


def seed_tauri_nsis_cache() -> None:
    """构建前把**可实跑**的 NSIS 种进 tauri 的缓存目录。

    根因（实机踩到，2026-09-30，节点 orange-connector）：tauri 把自带
    nsis-3.11 解到 `<cache>/tauri/NSIS`，随后直接 exec 该目录下的
    `makensis.exe`；该副本在本机起不来（`error 0x2`），于是整条 tauri build
    在 bundler 最后一步硬失败：

        Running makensis to produce ...\\bundle\\nsis\\Neurova_1.0.0-beta5_x64-setup.exe
        Unable to start child process, error 0x2
        failed to bundle project: `Failed to bundle app with makensis`

    为什么之前几轮修不掉：`NSISDIR` 是**死接线** —— 上游 mod.rs 用
    `env_remove("NSISDIR")` 显式丢弃它，指哪都没用。缓存目录里的那份才是
    真正被 exec 的那份，故根修点在**把缓存里那份换掉**，不是给 tauri 指路。

    判据与上游一致（`NSIS_REQUIRED_FILES`）：`makensis.exe` 必须位于缓存根，
    另需 `Bin/makensis.exe`、`Stubs/*`、`Include/*` 与 `nsis_tauri_utils.dll`
    插件。本函数把系统 NSIS 整树拷进去补齐前两类；插件不在系统 NSIS 里，
    从**已存在的 tauri 缓存副本**借（那是 tauri 自己下的、哈希可复核的那一份）。

    找不到可实跑的系统 NSIS 时**原样返回**（不改缓存、不吞失败）——
    交回 bundler 响亮失败，不在这里悄悄产残缺包（教义第 2 条）。
    """
    if os.name != "nt":
        return
    root = tauri_nsis_cache_root()
    if root is None:
        return
    good = resolve_working_nsis()
    if good is None:
        log("未找到可实跑的系统 NSIS —— 不种子缓存，交回 tauri 响亮失败")
        return
    target = root / TAURI_NSIS_DIRNAME
    if target.exists():
        # 已是可用副本（makensis 实跑通过）则不动：避免每次构建重拷 ~30MB。
        probe = target / "makensis.exe"
        try:
            r = subprocess.run([str(probe), "/VERSION"], capture_output=True,
                               text=True, timeout=30)
        except OSError:
            r = None
        if r is not None and r.returncode == 0:
            log(f"NSIS 缓存已可用，跳过种子：{target}")
            return
    # 插件（`nsis_tauri_utils.dll`）不在系统 NSIS 里，只存在于 tauri 的旧缓存副本中。
    # **必须在删树之前搬走**：它就在即将被 rmtree 的那棵树里 —— 先删后借的结果是
    # 「插件永远借不到」，而失败形态只是少一个文件，不会有任何红（live-verify 实测踩到：
    # 路径判据看着都对，复制那一步才 FileNotFoundError）。
    staged_plugin = None
    plugin_src = _find_cached_tauri_utils_dll(target)
    if plugin_src is not None:
        staged_plugin = Path(tempfile.mkdtemp(prefix="neurova-nsis-")) / plugin_src.name
        shutil.copy2(plugin_src, staged_plugin)
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(good, target)
    if staged_plugin is not None:
        dst = target / "Plugins" / "x86-unicode" / "additional"
        dst.mkdir(parents=True, exist_ok=True)
        shutil.copy2(staged_plugin, dst / "nsis_tauri_utils.dll")
        log(f"NSIS 插件已补齐：{plugin_src} → {dst}")
    else:
        log("未找到可借的 nsis_tauri_utils.dll —— 该件由 tauri 自行下载补齐")
    log(f"NSIS 缓存已种子：{good} → {target}")


def _find_cached_tauri_utils_dll(cache_dir: Path) -> Path | None:
    """在 tauri 的**旧缓存树**里找现成的 `nsis_tauri_utils.dll`。

    入参是缓存树本身（`<cache>/tauri/NSIS`），不是它的父目录 —— 该件只在树内
    `Plugins/x86-unicode/additional/` 下，递归范围就是这棵树。
    """
    if not cache_dir.is_dir():
        return None
    for hit in cache_dir.rglob("nsis_tauri_utils.dll"):
        if hit.is_file():
            return hit
    return None


def tauri_build_env() -> dict:
    """`tauri build` 的进程环境：把 `LOCALAPPDATA` 挪出 systemprofile。

    实机踩到（2026-09-30，节点 orange-connector，whoami=`nt authority\system`）：
    自托管 Runner 以 SYSTEM 身份跑，`%LOCALAPPDATA%` 落在
    `C:\WINDOWS\system32\config\systemprofile\AppData\Local`。Tauri 的 NSIS 打包器
    把自带 makensis 解到那里 —— 而**该位置的可执行文件加载不了**：

        该位置 makensis.exe                    → 0xC0000135（STATUS_DLL_NOT_FOUND）
        同一份字节拷到 D:\ci-localappdata\...  → v3.13 正常
        系统 choco NSIS                        → v3.13 正常

    失败形态是 `Unable to start child process, error 0x2` /
    `Failed to bundle app with makensis` —— 看着像 NSIS 缺失或脚本有错，
    根因却是**缓存目录选在了不可执行的位置**。

    根修：把 `LOCALAPPDATA` 指到一个普通目录，Tauri 据此决定 NSIS 缓存落点。
    只影响本次构建的子进程，不动机器环境。非 Windows 或已指到正常位置时原样返回。
    """
    if os.name != "nt":
        return {}
    cur = os.environ.get("LOCALAPPDATA", "")
    if "systemprofile" not in cur.lower():
        return {}
    # 与仓内其他构建产物同盘，避开系统盘权限；目录由 Tauri 自行创建子路径。
    base = Path(os.environ.get("NEUROVA_BUILD_LOCALAPPDATA", r"D:\ci-localappdata"))
    base.mkdir(parents=True, exist_ok=True)
    log(f"LOCALAPPDATA 落在 systemprofile（{cur}）—— 重定向到 {base}（该处 exe 加载不了）")
    return {"LOCALAPPDATA": str(base)}


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
    #
    # **落文件传路径，不内联 JSON**：`--config '{...}'` 经 shell 会把引号剥掉，
    # tauri 收到 `{bundle:{windows:{...}}}` 报 `key must be a string`
    # （实机踩到，2026-09-30）。结构化数据不进命令行是根本，不是加转义。
    import json

    override = Path(os.environ.get("TEMP", ".")) / "neurova-unsigned-bundle.json"
    override.write_text(
        json.dumps({"bundle": {"windows": {"certificateThumbprint": None}}}),
        encoding="utf-8",
    )
    return ["--config", str(override)], False


def build_tauri() -> Path:
    """npm run build:desktop + npx tauri build，返回 NSIS 产物路径。"""
    log("前端构建（vite build，desktop 环境）…")
    if run("npm run build:desktop", shell=True, cwd=REPO / "NeurUI") != 0:
        raise RuntimeError("前端构建失败（npm run build:desktop）")
    extra, signed = tauri_signing_args()
    build_tauri.last_signed = signed  # 交回调用点：不签名的产物要点名
    # 种子 NSIS 缓存必须在 tauri build **之前**：tauri 对缓存只查存在性/哈希，
    # 我们种进去的可用副本会被它直接用（不再下载、不再解压自带的坏副本）。
    seed_tauri_nsis_cache()
    log("tauri build（Rust release + NSIS bundle，可能 10 分钟+）…")
    # 传 argv 数组、不经 shell：`--config` 的路径可能含空格，过 shell 会被二次解析
    # （实机踩到引号被剥）。Windows 上 npx 是 npx.cmd，须经 cmd 解析扩展名。
    npx = "npx.cmd" if os.name == "nt" else "npx"
    if run([npx, "tauri", "build", *extra], cwd=REPO / "NeurUI",
           env=tauri_build_env()) != 0:
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
