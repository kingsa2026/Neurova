#!/usr/bin/env python3
"""跨生态依赖漏洞门禁（OSV）——补 pip-audit / npm audit 覆盖不到的依赖树。

背景（Issue #56 残留边界，实跑发现）：

pip-audit 与 npm audit 只覆盖"Python 声明锁"与"NeurUI 的 npm 树"。
仓库里还有两片**完全无人审计**的依赖面：

1. **Rust 依赖树** —— `NeurUI/src-tauri/Cargo.lock`（Tauri 桌面壳，447 包）。
   2026-09-18 实跑命中 8 条 RUSTSEC 公告（含 glib 0.18.5 未定义行为、
   rustls 0.23.43 TLS 1.3 跨加密层接受）。此前无任何工具看过它。
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
