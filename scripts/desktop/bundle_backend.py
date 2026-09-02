# -*- coding: utf-8 -*-
"""桌面壳后端全量打包（路线 A：Python 运行时+依赖+源码+模型 一次装齐）。

产物 = NeurUI/src-tauri/resources/backend/：
    python/            ← python-build-standalone CPython 3.12（安装即用运行时）
      Lib/site-packages/  ← 叠加 .venv/Lib/site-packages（同版本 CPython，ABI 兼容）
    neurova/           ← 后端包源码
    start_server.py    ← 后端入口
    models/ config/    ← 模型与配置
    MANIFEST.json      ← 增量构建标记

增量策略：venv site-packages 的（文件数, 总大小）指纹与上次一致时跳过
最重的三步大拷贝；neurova/config/models 走快速校验重拷。

用法（仓库根）：
    .venv/Scripts/python.exe scripts/desktop/bundle_backend.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
VENV_SP = REPO / ".venv" / "Lib" / "site-packages"
STAGE = REPO / "NeurUI" / "src-tauri" / "resources" / "backend"
MANIFEST = STAGE / "MANIFEST.json"

PYPSA_REPO = "astral-sh/python-build-standalone"
PYPSA_VERSION_PREFIX = "cpython-3.12."

EXCLUDE_DIR_NAMES = {"__pycache__", ".mimosa", ".pytest_cache"}


def log(msg: str) -> None:
    print(f"[bundle] {msg}", flush=True)


def dir_fingerprint(d: Path) -> dict:
    files = 0
    total = 0
    for f in d.rglob("*"):
        try:
            if f.is_file():
                files += 1
                total += f.stat().st_size
        except OSError:
            continue
    return {"files": files, "bytes": total}


def robocopy(src: Path, dst: Path, extra: list[str] | None = None) -> int:
    """Windows 原生 robocopy（/E 递归，不带 /PURGE——绝不删目标已有文件）。"""
    cmd = ["robocopy", str(src), str(dst), "/E", "/NFL", "/NDL", "/NJH", "/NJS", "/NP"]
    if extra:
        cmd += extra
    r = subprocess.run(cmd, capture_output=True, text=True)
    # robocopy 返回码 < 8 都算成功（1=拷了文件，3=拷了文件+ Extra 等）
    return r.returncode


def ensure_standalone_python(stage_python: Path) -> None:
    """下载并展开 python-build-standalone CPython 3.12（已存在则跳过）。"""
    if (stage_python / "python.exe").exists():
        log(f"运行时已存在: {stage_python}")
        return
    if stage_python.exists():
        shutil.rmtree(stage_python)

    log("查询 python-build-standalone 最新 release…")
    api = "https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest"
    req = urllib.request.Request(api, headers={"Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        release = json.loads(resp.read().decode("utf-8"))
    tag = release["tag_name"]
    asset = next(
        a["browser_download_url"]
        for a in release["assets"]
        if a["name"].startswith(PYPSA_VERSION_PREFIX)
        and "x86_64-pc-windows-msvc-install_only.tar.gz" in a["name"]
        and "_stripped" not in a["name"]
    )
    log(f"下载运行时 {asset}（约 12MB）…")
    tgz = STAGE / "_python-runtime.tar.gz"
    tgz.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(asset, timeout=300) as resp, open(tgz, "wb") as f:
        shutil.copyfileobj(resp, f)

    log(f"展开到 {stage_python} …")
    extract_dir = STAGE / "_python-extract"
    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    with tarfile.open(tgz, "r:gz") as tf:
        tf.extractall(extract_dir)
    # 布局兼容：部分版本解出 <prefix>/install/，部分直接 python/
    install_dir = None
    for n in extract_dir.iterdir():
        if not n.is_dir():
            continue
        if (n / "install" / "python.exe").exists():
            install_dir = n / "install"
            break
        if (n / "python.exe").exists():
            install_dir = n
            break
    if install_dir is None:
        raise RuntimeError("运行时包内未找到 python.exe")
    shutil.move(str(install_dir), stage_python)
    shutil.rmtree(extract_dir)
    tgz.unlink()
    log(f"运行时就绪: {stage_python / 'python.exe'}")


def copy_venv_site_packages(stage_python: Path, manifest: dict) -> None:
    sp_dst = stage_python / "Lib" / "site-packages"
    fp_now = dir_fingerprint(VENV_SP)
    if manifest.get("venv_sp") == fp_now and sp_dst.exists():
        log("site-packages 指纹未变，跳过大拷贝")
        return
    log(f"拷贝 site-packages → {sp_dst}（{fp_now['files']} 文件 / {fp_now['bytes'] / 1e6:.0f}MB）…")
    t0 = time.time()
    rc = robocopy(VENV_SP, sp_dst)
    if rc >= 8:
        raise RuntimeError(f"robocopy site-packages 失败 rc={rc}")
    log(f"site-packages 拷贝完成（{time.time() - t0:.0f}s）")
    manifest["venv_sp"] = fp_now


def copy_tree_light(src: Path, dst: Path, manifest: dict, key: str) -> None:
    """小目录/文件快速同步：先粗校验（文件数+大小），不一致才重拷。"""
    fp = dir_fingerprint(src) if src.is_dir() else {"files": 0, "bytes": src.stat().st_size if src.exists() else 0}
    if manifest.get(key) == fp and (dst.exists() if src.is_dir() else dst.exists()):
        log(f"{key} 未变，跳过")
        return
    if dst.is_dir():
        shutil.rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns(*EXCLUDE_DIR_NAMES))
    else:
        shutil.copy2(src, dst)
    manifest[key] = fp
    log(f"{key} 同步完成")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="忽略指纹强制重拷")
    args = ap.parse_args()

    if not VENV_SP.exists():
        log(f"venv 不存在: {VENV_SP}")
        return 1

    STAGE.mkdir(parents=True, exist_ok=True)
    manifest: dict = {}
    if MANIFEST.exists():
        try:
            manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        except Exception:
            manifest = {}
    if args.force:
        manifest = {}

    stage_python = STAGE / "python"
    ensure_standalone_python(stage_python)

    t0 = time.time()
    copy_venv_site_packages(stage_python, manifest)

    copy_tree_light(REPO / "neurova", STAGE / "neurova", manifest, "neurova")
    copy_tree_light(REPO / "models", STAGE / "models", manifest, "models")
    copy_tree_light(REPO / "config", STAGE / "config", manifest, "config")
    copy_tree_light(REPO / "start_server.py", STAGE / "start_server.py", manifest, "start_server")

    manifest["built_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    manifest["python"] = sys.version.split()[0]
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"后端打包完成 → {STAGE}（用时 {time.time() - t0:.0f}s）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
