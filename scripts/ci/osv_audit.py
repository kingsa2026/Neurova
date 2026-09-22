#!/usr/bin/env python3
"""跨生态依赖漏洞门禁（OSV）——补 pip-audit / npm audit 覆盖不到的依赖树。

背景（Issue #56 残留边界，实跑发现）：

pip-audit 与 npm audit 只覆盖"Python 声明锁"与"NeurUI 的 npm 树"。
仓库里还有两片**完全无人审计**的依赖面：

1. **Rust 依赖树** —— `NeurUI/src-tauri/Cargo.lock`（Tauri 桌面壳，447 包）。
   2026-09-18 实跑命中 8 条 RUSTSEC 公告（含 glib 0.18.5 未定义行为、
   rustls 0.23.43 TLS 1.3 跨加密层接受）。此前无任何工具看过它。
   （glib 0.18.5 已于 Issue #109 由仓内补丁修复：OSV 不解析 [patch] 段，故靠
   下方 LOCAL_PATCHES 逐条核验"版本未变但源码已修"这件事是否仍然成立。）
2. **运行时经 npx 拉取的 Node 包** —— camofox-browser / context7 / dbhub /
   server-filesystem 等由 `npx -y <pkg>` 在用户机器上现拉现跑，
   既无锁文件、也不进任何 audit 覆盖面（而这些包在生产路径上执行）。
   （NeurUI 自身的 npm 树不在此列——那份由 frontend job 的 npm audit 负责。）

本脚本用 OSV-Scanner（Google 维护，单一静态二进制）统一扫这些锁/清单，
把结果并入门禁。设计要点：

- **单侧实现、双侧复用**：`.cnb.yml` 与 `.github/workflows/ci.yml` 调同一条命令，
  由 tests/unit/test_ci_parity_guard.py 保证命令逐字一致。
- **二进制指纹校验**：按平台下载后核对 SHA256（常量内联），不信任传输通道。
- **允许清单带理由与到期日**：`scripts/ci/osv-allowlist.toml`，过期即重新报红
  （`ignoreUntil` 由 osv-scanner 强制），防"永久静音"。
- **失败即红灯**：扫描器跑不起来（下载失败/清单缺失）按基础设施错误退出非 0。
  "跑不起来就算过"的安全门禁是安全剧场，本仓库不收。
- **本地补丁必须被核验**：OSV 按 `name + version` 判定，看的是清单里的版本字符串，
  不是实际编译的源码——`[patch.crates-io]` 换成仓内源码后它照旧报同一个版本。
  于是"某条允许清单靠本地补丁成立"这件事，只能由本脚本自己核验：`LOCAL_PATCHES`
  逐条绑定「锁文件 → 包 → 仓内路径」，路径不在、或锁里该包仍带 `source`（说明补丁
  没生效），一律按基础设施错误退出 2。清单与补丁只绑一头，等于给不存在的修复背书。

用法：
    python scripts/ci/osv_audit.py                 # CI 用法
    OSV_SCANNER_BIN=/path/to/osv-scanner python scripts/ci/osv_audit.py   # 离线/本地

退出码：0 = 无未允许的漏洞；1 = 有未允许的漏洞；2 = 基础设施错误。
"""

from __future__ import annotations

import argparse
import hashlib
import os
import platform
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# ── 扫描器版本与二进制指纹（升级须同时改这里与 allowlist 里的说明） ──────────
OSV_SCANNER_VERSION = "2.6.0"
_RELEASE_BASE = (
    f"https://github.com/google/osv-scanner/releases/download/v{OSV_SCANNER_VERSION}"
)
# 官方 osv-scanner_SHA256SUMS（2026-09-18 核对，与发布页一致）
_BINARY_SHA256 = {
    "linux_amd64": "ca69b3d3cd08f889a49dc0a383122f71cc528b83803671df5fd874d97485b108",
    "linux_arm64": "2c71403eb443d05891c4f268c3ad771cf4f16e5443463fd7851ef8f454d3c7e4",
    "darwin_amd64": "60c5296637e977b28eeda5c7f13573e447659a632922737f94d11fa7e30ad6ca",
    "darwin_arm64": "98c460dcd37de25819babd757d04542045b6243113e209edcd4d89fedb0256b4",
}

# ── 被扫锁文件/清单：仓库内全部"非 pip、非 NeurUI-npm-audit"依赖载体 ─────────
SCAN_TARGETS = (
    # Rust：Tauri 桌面壳依赖树（pip-audit / npm audit 都看不到）
    "NeurUI/src-tauri/Cargo.lock",
    # 运行时 npx 拉取的 Node 包清单（生产路径上执行，此前无锁无审计）
    "tools/npx-runtime/package-lock.json",
)

ALLOWLIST = "scripts/ci/osv-allowlist.toml"

# ── 本地补丁登记：允许清单里"靠仓内源码修复"的条目必须在此逐条对账 ─────────────
# 键是锁文件路径，值是「包名 → 仓内目录」。判据：目录存在、且锁文件里该包
# 不再带 source（带 source = cargo 仍在用 registry 版本，补丁未生效）。
# 为什么必须核验：OSV 不解析 [patch] 段，只按锁文件里的 name+version 查库，
# 所以"版本没变但源码已修"这种形态它能看出的只有旧版本号——谁修的、修还在不在，
# 扫描器不知道。少了这一步，删掉 vendor 目录 CI 照样全绿。
LOCAL_PATCHES = {
    "NeurUI/src-tauri/Cargo.lock": {
        "glib": "NeurUI/src-tauri/vendor/glib-0.18.5",
    },
}


def verify_local_patches() -> list:
    """核验本地补丁登记与磁盘/锁文件一致，返回问题清单（空 = 通过）。"""
    problems = []
    for lock_rel, patches in LOCAL_PATCHES.items():
        lock_path = PROJECT_ROOT / lock_rel
        if not lock_path.is_file():
            problems.append(f"锁文件缺失，无法核验本地补丁: {lock_rel}")
            continue
        lock_text = lock_path.read_text(encoding="utf-8")
        for crate, vendor_rel in patches.items():
            vendor_dir = PROJECT_ROOT / vendor_rel
            if not (vendor_dir / "Cargo.toml").is_file():
                problems.append(
                    f"本地补丁目录不存在或不是 crate: {vendor_rel}"
                    f"（{lock_rel} 的 {crate} 正靠它修复）"
                )
            block = re.search(
                r'\[\[package\]\]\nname = "'
                + re.escape(crate)
                + r'"\nversion = "([^"]+)"\n(.*?)(?:\n\n|\Z)',
                lock_text,
                re.S,
            )
            if block is None:
                problems.append(f"{lock_rel} 里找不到包 {crate}（补丁登记已陈旧）")
                continue
            if "source = " in block.group(2):
                problems.append(
                    f"{lock_rel} 的 {crate} 仍带 source 字段——"
                    f"[patch.crates-io] 未生效，实际编译的不是 {vendor_rel}"
                )
    return problems


def _platform_key() -> str:
    sysname = platform.system().lower()
    machine = platform.machine().lower()
    os_part = {"linux": "linux", "darwin": "darwin"}.get(sysname)
    arch_part = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(machine)
    if not os_part or not arch_part:
        raise SystemExit(f"不支持的平台: {sysname}/{machine}（请设置 OSV_SCANNER_BIN 指向本地二进制）")
    return f"{os_part}_{arch_part}"


def _download_scanner(dest_dir: Path) -> Path:
    key = _platform_key()
    expected = _BINARY_SHA256.get(key)
    if expected is None:
        raise SystemExit(f"无 {key} 的二进制指纹，拒绝下载（请设置 OSV_SCANNER_BIN）")

    suffix = ".exe" if platform.system().lower() == "windows" else ""
    url = f"{_RELEASE_BASE}/osv-scanner_{key}{suffix}"
    dest = dest_dir / f"osv-scanner{suffix}"

    print(f"[osv] 下载 {url}")
    try:
        with urllib.request.urlopen(url, timeout=180) as resp, open(dest, "wb") as f:
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
    except Exception as e:  # noqa: BLE001 - 基础设施错误，下面统一报错退出
        raise SystemExit(f"osv-scanner 下载失败: {e}") from e

    digest = hashlib.sha256(dest.read_bytes()).hexdigest()
    if digest != expected:
        dest.unlink(missing_ok=True)
        raise SystemExit(
            f"osv-scanner 指纹不符——拒绝执行（供应链完整性）\n"
            f"  期望 {expected}\n  实得 {digest}"
        )
    dest.chmod(0o755)
    print(f"[osv] 指纹校验通过 ({key})")
    return dest


def _resolve_scanner() -> Path:
    env_bin = os.environ.get("OSV_SCANNER_BIN", "").strip()
    if env_bin:
        p = Path(env_bin)
        if not p.is_file():
            raise SystemExit(f"OSV_SCANNER_BIN 指向的文件不存在: {p}")
        print(f"[osv] 使用本地二进制: {p}")
        return p
    tmp = Path(tempfile.mkdtemp(prefix="osv-scanner-"))
    return _download_scanner(tmp)


def main() -> int:
    ap = argparse.ArgumentParser(description="跨生态依赖漏洞门禁（OSV-Scanner）")
    ap.add_argument(
        "--targets",
        nargs="*",
        default=None,
        help="覆盖被扫锁文件（默认取 SCAN_TARGETS 中存在者）",
    )
    args = ap.parse_args()

    targets = []
    for rel in args.targets if args.targets else SCAN_TARGETS:
        p = PROJECT_ROOT / rel
        if p.is_file():
            targets.append(str(p))
        elif args.targets:
            print(f"[osv] 指定的目标不存在: {rel}", file=sys.stderr)
            return 2

    if not targets:
        print("[osv] 无扫描目标——资产被删则该门禁失去意义，按错误处理", file=sys.stderr)
        return 2

    allowlist = PROJECT_ROOT / ALLOWLIST
    if not allowlist.is_file():
        print(f"[osv] 允许清单缺失: {ALLOWLIST}（无清单不容许静默放行）", file=sys.stderr)
        return 2

    patch_problems = verify_local_patches()
    if patch_problems:
        print("[osv] 本地补丁核验失败——允许清单正在为不存在的修复背书:", file=sys.stderr)
        for item in patch_problems:
            print(f"      - {item}", file=sys.stderr)
        return 2

    scanner = _resolve_scanner()

    cmd = [str(scanner), "scan", "source", "--config", str(allowlist)]
    for t in targets:
        cmd += ["--lockfile", t]
    print("[osv] 扫描目标:")
    for t in targets:
        print("      -", Path(t).relative_to(PROJECT_ROOT))

    proc = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    if proc.returncode == 0:
        print("\n[osv] ✅ 无未允许的已知漏洞")
        return 0
    if proc.returncode == 1:
        print(
            "\n[osv] ❌ 发现未允许的漏洞。处置二选一：\n"
            "  (a) 升级依赖修掉（首选）；\n"
            f"  (b) 确无修复/不可达时，在 {ALLOWLIST} 登记 id+理由+到期日。\n"
            "  注：清单条目过期后本条会重新报红——这是刻意设计，防永久静音。",
            file=sys.stderr,
        )
        return 1
    print(f"[osv] 扫描器异常退出（code={proc.returncode}）", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
