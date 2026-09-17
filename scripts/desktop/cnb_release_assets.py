# -*- coding: utf-8 -*-
"""把产物上传为 cnb.cool 仓库 Release 附件。

对齐 GitHub `gh release create <tag> <files>` 的本地使用方式：
  .venv/Scripts/python.exe scripts/desktop/cnb_release_assets.py <tag> <file> [<file>...]

行为：
  - Release 不存在则创建（tag 已存在则挂靠该 tag；不存在则按 tag 自动建）。
  - 附件三步上传：asset-upload-url 预签名 → PUT 文件 → 确认端点收尾。
  - 幂等：同名附件自动覆盖（overwrite=true）。
  - token 优先取环境变量 CNB_TOKEN，否则从 git remote "cnb" 的 URL 凭据解析。
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

import requests

API = "https://api.cnb.cool"


def log(msg: str) -> None:
    print(f"[cnb] {msg}", flush=True)


def cnb_token() -> str:
    tok = os.environ.get("CNB_TOKEN", "").strip()
    if tok:
        return tok
    # fallback: git remote url 里的内嵌凭据 https://<user>:<token>@cnb.cool/...
    out = os.popen("git remote get-url cnb 2>nul").read().strip()
    m = re.search(r"https://[^:]+:([^@]+)@cnb\.cool", out)
    if not m:
        raise RuntimeError("未找到 CNB token（设 CNB_TOKEN 或检查 git remote cnb 的 URL 凭据）")
    return m.group(1)


def api(repo: str, method: str, path: str, token: str, allow=(), **kw) -> requests.Response:
    url = f"{API}/{repo}{path}"
    r = requests.request(
        method, url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.cnb.api+json",
            **kw.pop("headers", {}),
        },
        timeout=120,
        **kw,
    )
    # 2xx 一律成功（POST 创建类端点返回 201）；allow 豁免预期内的 4xx（如查不存在 = 404）
    if r.status_code >= 400 and r.status_code not in allow:
        raise RuntimeError(f"{method} {url} -> {r.status_code}: {r.text[:300]}")
    return r


def ensure_release(repo: str, tag: str, token: str) -> int:
    # 404 = release 不存在（预期路径）：创建并挂靠已有 tag
    r = api(repo, "GET", f"/-/releases/tags/{tag}", token, allow=(404,))
    if r.status_code == 200:
        rid = r.json()["id"]
        log(f"release 已存在: {tag} (id={rid})")
        return rid
    if r.status_code != 404:
        raise RuntimeError(f"查询 release {tag} 异常: {r.status_code}: {r.text[:300]}")
    r = api(repo, "POST", "/-/releases", token, json={
        "tag_name": tag,
        "name": f"Neurova {tag.lstrip('v')}",
        "body": f"Neurova {tag.lstrip('v')} — 安装包见附件。",
        "make_latest": "true",
    })
    rid = r.json()["id"]
    log(f"release 已创建: {tag} (id={rid})")
    return rid


def upload_asset(repo: str, rid: int, token: str, file: Path) -> None:
    name = file.name
    size = file.stat().st_size
    r = api(repo, "POST", f"/-/releases/{rid}/asset-upload-url", token, json={
        "asset_name": name,
        "size": size,
        "overwrite": True,
    })
    info = r.json()
    upload_url, verify_url = info["upload_url"], info["verify_url"]
    log(f"上传 {name}（{size / 1048576:.0f} MB）…")
    with open(file, "rb") as f:
        put = requests.put(upload_url, data=f, timeout=3600,
                           headers={"Content-Type": "application/octet-stream"})
    if put.status_code >= 400:
        raise RuntimeError(f"PUT {name} -> {put.status_code}: {put.text[:300]}")
    # 确认直接用预签名 verify_url（upload_token 已内嵌, 响应无独立 token 字段）
    conf = requests.post(verify_url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.cnb.api+json",
    }, json={}, timeout=120)
    if conf.status_code >= 400:
        raise RuntimeError(f"confirm {name} -> {conf.status_code}: {conf.text[:300]}")
    log(f"完成 {name}（确认 {conf.status_code}）")


def main() -> int:
    ap = argparse.ArgumentParser(description="上传 cnb.cool Release 附件")
    ap.add_argument("tag")
    ap.add_argument("files", nargs="+")
    args = ap.parse_args()

    repo = "kingsa2026/neurova"
    token = cnb_token()
    rid = ensure_release(repo, args.tag, token)
    for f in args.files:
        p = Path(f)
        if not p.exists():
            log(f"跳过不存在的文件: {p}")
            continue
        upload_asset(repo, rid, token, p)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as e:
        log(f"失败: {e}")
        sys.exit(1)
