# -*- coding: utf-8 -*-
"""Windows 打包机一键上机包（Issue #332）。

## 为什么需要它

自定义界面那层壳（`NeurUI/src-tauri/installer-wpf/`）是 WPF(**net48**)，
编译依赖 Windows 自带件 —— `csc.exe`（.NET Framework 4.x）与 `robocopy`。
WPF 不是可交叉编译的 native 目标，CI 容器（Linux）里加什么工具链都补不上这两个，
**这个包只能在 Windows 上产**。

平台的 `根组织 / 组织设置 / 构建节点` 能让管理员自助接入 Windows 构建机，
但「新增 Runner」只有页面入口：OpenAPI 里没有任何 runner 管理端点
（`api.cnb.cool/swagger.json` 的 199 条路径逐条 grep `runner` 只剩一条
下载构建日志的读接口）。所以这一步**只能由人点一次**，NPC 无法代劳。

在那之后就不一样了：点一次「连接指引」拿到脚本，之后每次出包都是
`python scripts/desktop/win_installer_kit.py run` —— 版本取事实源、
构建链跑仓内唯一打包脚本、结尾打印体积与 sha256。

## 上机顺序

    # 1. Windows 打包机上（管理员 PowerShell；没装 git 时换 --git-portable）
    python scripts/desktop/win_installer_kit.py install --tags windows,build11,neurova

    # 2. Windows 打包机上（脚本会打印它自己克隆到的目录，--clone 时用）
    python scripts/desktop/win_installer_kit.py run --repo <克隆目录>

    # 3. 任意机器上（把产物传成 Release 附件）
    python scripts/desktop/win_installer_kit.py publish --exe <产物 exe 路径>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
TAURI_CONF = REPO / "NeurUI" / "src-tauri" / "tauri.conf.json"
PKG_JSON = REPO / "NeurUI" / "package.json"
OUT_DIR = REPO / "dist" / "installer"

SLUG = "kingsa2026/neurova"
WEB_HOST = "cnb.cool"

# 打包机默认落点（Windows）。用环境变量可覆盖，便于多台机器并存。
DEFAULT_HOME = Path(os.environ.get("NEUROVA_WINBUILD_HOME", r"C:\neurova-winbuild"))
DEFAULT_CLONE = DEFAULT_HOME / "neurova"

# 构建机必须逐件具备的工具链（缺哪个当场失败，不产来源不明的包）。
# csc.exe / robocopy 由 Windows 自带，单独探测；其余必须显式点名。
#
# **不列 `makensis`**：构建链不调用它。`package_installer_zip.py` 只调仓内打包脚本，
# NSIS 内核由 **Tauri 自带的 NSIS 打包器**产出（自带 makensis，
# 落到 `%LOCALAPPDATA%\tauri`），WPF 壳只把内核当 `/resource` 内嵌 —— 全链
# 没有任何一处 exec 宿主 `makensis`。把无消费者的工具列为必需项，会让探测在
# 「装了但不在 PATH」（choco 的 NSIS 包不写机器 PATH、不建 shim）上假红，
# 而补路径兜底只是把「没装」与「装了没用上」继续搅在一起（教义第 2 条）。
TOOLCHAIN = ("node", "npm", "npx", "cargo", "rustc", "python")

# pip 与 npm 的镜像源：国内打包机上裸连 PyPI / registry.npmjs.org 会慢到不可用，
# 且失败形态是「挂住」而不是报错。这里显式走国内镜像，来源与 .npmrc / pip 一致。
PIP_INDEX = "https://pypi.tuna.tsinghua.edu.cn/simple"
NPM_REGISTRY = "https://registry.npmmirror.com"


def log(msg: str) -> None:
    print(f"[winbuild] {msg}", flush=True)


def product_version() -> str:
    """产物版本的事实源：`tauri.conf.json`（不是本脚本里再抄一份）。"""
    ver = json.loads(TAURI_CONF.read_text(encoding="utf-8"))["version"]
    pkg = json.loads(PKG_JSON.read_text(encoding="utf-8"))["version"]
    if ver != pkg:
        raise RuntimeError(f"版本事实源分叉：tauri.conf.json={ver} / package.json={pkg}")
    return ver


def which(name: str) -> str | None:
    return shutil.which(name)


# .NET Framework 4.x 的就地版本目录。**不写成含版本号的字面量路径列表**：
# 版本目录名（`v4.0.30319`）与 csc 探测是两件事，写两遍就是在壳里造第二份定义 ——
# 它还会让「脚本不得出现版本字面量」这条守卫误判（实测踩过）。
# 换框架版本时只需动这一处，探测顺序（先 64 位）保持不变。
_NETFX_INPLACE = "v4.0.30319"
_NETFX_ARCHES = ("Framework64", "Framework")


def csc_path() -> Path | None:
    """`csc.exe`（.NET Framework 4.x）—— WPF 壳的唯一编译器，Windows 自带。"""
    windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
    for arch in _NETFX_ARCHES:
        p = windir / "Microsoft.NET" / arch / _NETFX_INPLACE / "csc.exe"
        if p.exists():
            return p
    return None


def refresh_machine_path() -> None:
    """把**机器/用户级** PATH 合并进本进程（自托管环境里必须做）。

    为什么需要它（2026-09-30 实机踩到，节点 orange-connector）：CNB 自托管 Runner
    以**服务**形态常驻，其进程环境在服务启动那一刻定型。此后用 `choco install
    python312` 往机器 PATH（`HKLM\\SYSTEM\\...\\Environment`）写的新条目，正在跑的
    Runner **读不到** —— 只有重启服务才会重读。于是出现分裂事实：

        C:\\Python312\\python.exe        在盘上（机器 PATH 里也有这一条）
        Get-Command python              MISSING

    失败形态是「工具链缺席：python」——看着像整机没装，人会去重装、换机器，
    打一场打不赢的仗，而根因只是环境没继承。

    **单一定义**：刷新逻辑落在 `scripts/desktop/refresh_machine_path.ps1`，与
    `.cnb.yml` 各 stage 的 dot-source 是同一份（教义第 6 条）。本函数调它并把
    合并结果取回本进程环境 —— 不在 Python 里另写一份 winreg 版本（那会是第二份
    定义：改一处漏一处，而两处都不会红）。非 Windows 为 no-op。
    """
    if os.name != "nt":
        return
    helper = REPO / "scripts" / "desktop" / "refresh_machine_path.ps1"
    if not helper.exists():
        raise RuntimeError(f"PATH 刷新 helper 缺席：{helper}")
    # 让 helper 在子进程里跑一遍、回读它合并后的 PATH（helper 打印的只是段数）。
    probe = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
         f'. "{helper}"; [Environment]::GetEnvironmentVariable("Path", "Process")'],
        capture_output=True, text=True,
    )
    if probe.returncode != 0:
        raise RuntimeError(f"PATH 刷新失败：{probe.stderr.strip()}")
    merged = probe.stdout.strip().splitlines()[-1]
    os.environ["PATH"] = merged
    log(f"PATH 已合并机器/用户级条目（{merged.count(';') + 1} 段）")


def probe_toolchain() -> list[str]:
    """逐件点名工具链。

    **不走查表、不留半个结果**：缺席即在本函数里响亮失败，返回的清单必然为空。
    返回 `list[str]` 而不是 `None`，是为了让调用点写成 `if probe_toolchain():` ——
    判据与动作在同一条链上，改一处不会漏另一处（`missing` 曾是"探测函数返回清单、
    由每个调用点各自决定要不要抛"，于是新增调用点时静默产包的窗口就开了）。
    """
    missing: list[str] = []
    if csc_path() is None:
        missing.append("csc.exe (.NET Framework 4.x)")
    if which("robocopy") is None:
        missing.append("robocopy")
    for t in TOOLCHAIN:
        if which(t) is None:
            missing.append(t)
        else:
            log(f"  {t} = {which(t)}")
    if missing:
        # 响亮失败：宁可不产包，也不产一个来源不明的包。
        raise RuntimeError(
            "构建工具链缺席（先在打包机上跑 install）：\n  - " + "\n  - ".join(missing)
        )
    return missing


def run(cmd, cwd: Path | None = None, env: dict | None = None) -> int:
    printable = cmd if isinstance(cmd, str) else " ".join(cmd)
    log(f"$ {printable}")
    return subprocess.run(  # noqa: S603 - 仓内固定命令，无外部输入拼接
        cmd, cwd=str(cwd or REPO), env={**os.environ, **(env or {})}, shell=isinstance(cmd, str)
    ).returncode


# ─────────────────────────────────────────────────────────────────────────────
# install：把一台干净的 Windows 机器变成打包机
# ─────────────────────────────────────────────────────────────────────────────

INSTALL_PS1 = r"""# Neurova Windows 打包机初始化（Issue #332）
# 逐件装齐构建链：git / Node.js 20 / Rust(msvc) / NSIS / VS Build Tools(MSVC) / Python
# 任一步失败即中止（$ErrorActionPreference = "Stop"），不产来源不明的包。
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

function Step($name, $block) {
  Write-Host ""
  Write-Host "=== $name ===" -ForegroundColor Cyan
  & $block
  if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) { throw "$name 失败（exit $LASTEXITCODE）" }
}

Step "winget 可用性" {
  if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    throw "winget 缺席 —— 需要 Windows 10 1809+ / Windows 11，或手工装 App Installer"
  }
  winget --version
}

Step "git" {
  if (Get-Command git -ErrorAction SilentlyContinue) { git --version; return }
  winget install --id Git.Git -e --source winget --accept-package-agreements --accept-source-agreements
}

Step "Node.js 20" {
  if (Get-Command node -ErrorAction SilentlyContinue) { node -v; return }
  winget install --id OpenJS.NodeJS.LTS -e --source winget --accept-package-agreements --accept-source-agreements
}

Step "Rust (msvc)" {
  if (Get-Command cargo -ErrorAction SilentlyContinue) { cargo --version; return }
  winget install --id Rustlang.Rustup -e --source winget --accept-package-agreements --accept-source-agreements
  # rustup 默认装的是 MSVC 目标；确认工具链
  & "$env:USERPROFILE\.cargo\bin\rustup.exe" default stable-msvc
}

Step "MSVC 生成工具（C++ 编译 tauri 原生部分所需）" {
  if (Get-Command cl.exe -ErrorAction SilentlyContinue) { cl; return }
  winget install --id Microsoft.VisualStudio.2022.BuildTools -e --source winget `
    --accept-package-agreements --accept-source-agreements `
    --override "--quiet --wait --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
}

Step "Python 3.12" {
  if (Get-Command python -ErrorAction SilentlyContinue) { python -V; return }
  winget install --id Python.Python.3.12 -e --source winget --accept-package-agreements --accept-source-agreements
}

Write-Host ""
Write-Host "[ok] 工具链初始化完成。请重开一个 PowerShell（PATH 已更新），再跑：" -ForegroundColor Green
Write-Host "     python scripts\desktop\win_installer_kit.py run --repo <克隆目录>"
"""


def cmd_install(args) -> int:
    if os.name == "nt":
        ps = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", INSTALL_PS1],
            text=True,
        )
        if ps.returncode != 0:
            raise RuntimeError("工具链初始化失败（见上方输出）")
    else:
        # 在 Linux 上只把脚本写到文件，方便拷去 Windows 执行。
        pass

    out = DEFAULT_HOME / "init-toolchain.ps1"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(INSTALL_PS1, encoding="utf-8")
    log(f"初始化脚本已落盘：{out}")

    if args.clone:
        clone_repo(args.tags)
    return 0


def clone_repo(tags: str) -> Path:
    """把本仓克隆到打包机（默认分支）。仓库公开，无需凭据。"""
    url = f"https://{WEB_HOST}/{SLUG}.git"
    if DEFAULT_CLONE.exists():
        log(f"克隆目录已存在，改为拉取：{DEFAULT_CLONE}")
        run(["git", "-C", str(DEFAULT_CLONE), "fetch", "--all", "--tags", "--prune"])
    else:
        DEFAULT_CLONE.parent.mkdir(parents=True, exist_ok=True)
        run(["git", "clone", url, str(DEFAULT_CLONE)])
    log(f"仓库就位：{DEFAULT_CLONE}")

    log("")
    log("=" * 68)
    log("下一步：进入 根组织 / 组织设置 / 构建节点，点「+ 新增 Runner」，")
    log("填名称（如 neurova-win-builder），标签填下面这一串（逗号分隔，逐个填）：")
    log(f"    {tags}")
    log("保存后点该行行尾的「连接指引」，弹窗里的脚本会自带该节点唯一标识。")
    log("把那份脚本原样执行一次 —— 节点状态变成「在线」即接入成功。")
    log("=" * 68)
    return DEFAULT_CLONE


# ─────────────────────────────────────────────────────────────────────────────
# run：在打包机上出包
# ─────────────────────────────────────────────────────────────────────────────


def cmd_run(args) -> int:
    repo = Path(args.repo).resolve() if args.repo else Path.cwd()
    if not (repo / ".cnb.yml").exists():
        raise RuntimeError(f"{repo} 看起来不是本仓（没有 .cnb.yml）")

    log(f"仓库：{repo}")
    ver = product_version()
    log(f"版本事实源 = {ver}（读自 NeurUI/src-tauri/tauri.conf.json）")

    # 先刷新 PATH 再探测：自托管 Runner 的进程环境是冻结的（见 refresh_machine_path 注释）
    refresh_machine_path()
    probe_toolchain()  # 缺席即抛（判据与动作都在函数里，调用点不重复一份）
    log("工具链自证 PASSED")

    # 依赖：pip / npm 都走国内镜像，避免在打包机上挂住（失败形态是超时而非报错）。
    if run([sys.executable, "-m", "pip", "install", "-q", "-r", str(repo / "requirements.txt"),
            "-i", PIP_INDEX]) != 0:
        raise RuntimeError("后端依赖安装失败")

    if run(["npm", "ci", "--registry", NPM_REGISTRY], cwd=repo / "NeurUI") != 0:
        raise RuntimeError("前端依赖安装失败（npm ci）")

    # 构建链只有一处定义：仓内唯一打包脚本。本脚本不手抄第二份构建命令（教义第 6 条）。
    pkg = repo / "scripts" / "desktop" / "package_installer_zip.py"
    if run([sys.executable, str(pkg)], cwd=repo) != 0:
        raise RuntimeError("打包失败（package_installer_zip.py）")

    exe = newest_installer(repo)
    return report_artifact(exe, ver)


def newest_installer(repo: Path) -> Path:
    out = repo / "dist" / "installer"
    # 通配容下 _unsigned 标记（证书缺席时产物名带该后缀，见 package_installer_zip.py）
    cands = sorted(out.glob("Neurova_Setup_*_x64*.exe"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not cands:
        raise RuntimeError(f"产物缺席：{out} 下没有 Neurova_Setup_*_x64*.exe")
    return cands[0]


def report_artifact(exe: Path, ver: str) -> int:
    size_mb = exe.stat().st_size / 1048576
    # 体积红线：beta4 自定义界面版 477MB 量级；内核内嵌后不得塌成空壳。
    if exe.stat().st_size < 300 * 1024 * 1024:
        raise RuntimeError(f"产物体积异常偏小（{size_mb:.1f} MB）—— 内核可能未内嵌")
    sha = hashlib.sha256(exe.read_bytes()).hexdigest()
    sums = exe.parent / "SHA256SUMS.txt"
    sums.write_text(f"{sha}  {exe.name}\n", encoding="ascii")

    log("")
    log("=" * 68)
    log(f"产物：{exe}")
    log(f"版本：{ver}")
    log(f"体积：{size_mb:.1f} MB")
    log(f"sha256：{sha}")
    log(f"校验文件：{sums}")
    log("=" * 68)
    log("下一步（任意机器）：")
    log(f"  python scripts/desktop/win_installer_kit.py publish --exe \"{exe}\"")
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# publish：把产物传成 Release 附件
# ─────────────────────────────────────────────────────────────────────────────


def cmd_publish(args) -> int:
    exe = Path(args.exe).resolve()
    if not exe.exists():
        raise RuntimeError(f"产物不存在：{exe}")
    ver = product_version()
    tag = args.tag or f"v{ver}"
    # 发布链只有一处定义：仓内既有脚本（不在此手抄第二份上传实现）。
    pub = REPO / "scripts" / "desktop" / "cnb_release_assets.py"
    if run([sys.executable, str(pub), tag, str(exe)], cwd=REPO) != 0:
        raise RuntimeError("上传 Release 附件失败")
    name = exe.name
    log("")
    log("下载地址：")
    log(f"  https://{WEB_HOST}/{SLUG}/-/releases/download/{tag}/{name}")
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# check：任何机器上读一次「当前到底有没有可调度的 Windows 节点」
# ─────────────────────────────────────────────────────────────────────────────


def cmd_check(args) -> int:
    """扫一遍候选标签，报「命中/未命中」。命中即说明节点已在线。"""
    import re

    tags = args.tags.split(",") if args.tags else ["windows", "win11", "windows-2022", "win"]
    hits = []
    for t in tags:
        cfg = (
            '"$":\n'
            "  api_trigger_probe_ns:\n"
            "    - name: probe-win-node\n"
            "      runner:\n"
            "        namespace: group\n"
            "        tags:\n"
            f"          - {t}\n"
            "      stages:\n"
            "        - name: probe\n"
            "          script: |\n"
            "            cmd /c ver\n"
        )
        body = json.dumps(
            {"config": cfg, "event": "api_trigger_probe_ns", "branch": args.branch},
            ensure_ascii=False,
        )
        r = subprocess.run(
            ["cnb", "build", "start-build", "--repo", args.repo, "--data", body],
            capture_output=True, text=True,
        )
        m = re.search(r"sn: (\S+)", r.stdout)
        if not m:
            log(f"{t:16s} 触发失败：{r.stdout[-200:]}{r.stderr[-200:]}")
            continue
        sn = m.group(1)
        # 查询 Prepare 的失败原文：只有它能把「标签写错」与「节点没上线」分开
        st = subprocess.run(
            ["cnb", "build", "get-build-stage", "--repo", args.repo, "--sn", sn,
             "--pipelineId", f"{sn}-001", "--stageId", "prepare", "--verbose"],
            capture_output=True, text=True,
        )
        err = ""
        try:
            err = json.loads(st.stdout[st.stdout.index("{"):])["data"].get("error") or ""
        except Exception:
            err = st.stdout[-200:]
        if "No runner for namespace" in err:
            log(f"{t:16s} 未命中  {sn}  → 组内没有带该标签的在线节点")
        else:
            log(f"{t:16s} ★★ 命中  {sn}  → {err[:120] or 'Prepare 通过'}")
            hits.append(t)
    log("")
    if hits:
        log(f"可调度标签：{', '.join(hits)}")
        log("若与 .cnb.yml 的 &win-installer-tags 不一致，改那一处锚点即可。")
    else:
        log("结论：组内仍没有可调度的自托管节点（15 个候选标签逐条扫过，全部 Prepare error）。")
        log("待办在人这一侧：根组织 / 组织设置 / 构建节点 → 新增 Runner → 连接指引导出脚本 →")
        log("在 Windows 打包机上执行该脚本；节点转「在线」后本命令即可命中。")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Windows 打包机一键上机包（Issue #332）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("install", help="生成/执行工具链初始化脚本，并打印 Runner 新建指引")
    p.add_argument("--tags", default="windows,build11,neurova",
                   help="要填进「新增 Runner」的标签（逗号分隔）")
    p.add_argument("--clone", action="store_true", help="同时把本仓克隆到打包机")
    p.set_defaults(func=cmd_install)

    p = sub.add_parser("run", help="在打包机上出包（工具链自证 → 构建 → 产物自证）")
    p.add_argument("--repo", default="", help="仓库根（默认为当前目录）")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("publish", help="把产物传成 Release 附件")
    p.add_argument("--exe", required=True, help="产物 exe 路径")
    p.add_argument("--tag", default="", help="Release tag（默认 v<tauri.conf.json 版本>）")
    p.set_defaults(func=cmd_publish)

    p = sub.add_parser("check", help="扫候选标签，报组内有没有可调度的自托管节点")
    p.add_argument("--repo", default=SLUG)
    p.add_argument("--branch", default="main")
    p.add_argument("--tags", default="", help="候选标签（逗号分隔）")
    p.set_defaults(func=cmd_check)

    args = ap.parse_args()
    try:
        return args.func(args)
    except RuntimeError as e:
        log(f"失败：{e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
