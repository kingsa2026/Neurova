# -*- coding: utf-8 -*-
"""发布链唯一入口：把本地产物上传为 Release 附件（cnb.cool 与 GitHub 两个平台）。

  .venv/Scripts/python.exe scripts/desktop/cnb_release_assets.py <tag> [--notes 正文] [--platform cnb|github|both] <file> [...]

文件名沿用 `cnb_*`（`scripts/desktop/win_installer_kit.py` 与它的常驻守卫按这个名字钉发布链，
改名等于制造第二条链）；GitHub 只是同一条 CLI 上的另一个平台适配器，正文、tag、文件清单两处共用，
不另起一份脚本。

行为：
  - Release 不存在则创建（挂靠已有 tag；tag 也不存在则由平台按 tag 自动建）。
  - CNB 附件三步上传：asset-upload-url 预签名 → PUT 文件 → 确认端点收尾，同名自动覆盖。
  - GitHub 附件走 release 的 upload_url，**没有覆盖语义**：同名先删旧附件再传（幂等靠这两步凑）。
  - token：CNB 取 `CNB_TOKEN`，否则从 git remote 的 cnb.cool URL 内嵌凭据解析；
    GitHub 取 `GH_TOKEN` / `GITHUB_TOKEN`（remote URL 里没有凭据时不做静默猜测）。
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote

import requests

API = "https://api.cnb.cool"
GH_API = "https://api.github.com"
# 平台 slug 大小写不同（cnb 全小写、GitHub 仓库名大写），故各留一份而非统一小写拼 URL
RELEASE_REPO_SLUG = {"cnb": "kingsa2026/neurova", "github": "kingsa2026/Neurova"}


def log(msg: str) -> None:
    print(f"[release] {msg}", flush=True)


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


def github_token() -> str:
    for var in ("GH_TOKEN", "GITHUB_TOKEN"):
        tok = os.environ.get(var, "").strip()
        if tok:
            return tok
    raise RuntimeError("未找到 GitHub token（设 GH_TOKEN 或 GITHUB_TOKEN）")


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


def gh_api(method: str, path: str, token: str, allow=(), **kw) -> requests.Response:
    r = requests.request(
        method, f"{GH_API}{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            **kw.pop("headers", {}),
        },
        timeout=120,
        **kw,
    )
    if r.status_code >= 400 and r.status_code not in allow:
        raise RuntimeError(f"{method} /repos/…{path.split('/repos/', 1)[-1]} -> "
                           f"{r.status_code}: {r.text[:300]}")
    return r


def ensure_release(repo: str, tag: str, token: str, notes: str) -> int:
    # 404 = release 不存在（预期路径）：创建并挂靠已有 tag
    r = api(repo, "GET", f"/-/releases/tags/{tag}", token, allow=(404,))
    if r.status_code == 200:
        rid = r.json()["id"]
        log(f"cnb release 已存在: {tag} (id={rid})")
        return rid
    if r.status_code != 404:
        raise RuntimeError(f"查询 release {tag} 异常: {r.status_code}: {r.text[:300]}")
    r = api(repo, "POST", "/-/releases", token, json={
        "tag_name": tag,
        "name": f"Neurova {tag.lstrip('v')}",
        "body": notes,
        "make_latest": "true",
    })
    rid = r.json()["id"]
    log(f"cnb release 已创建: {tag} (id={rid})")
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


def ensure_release_github(repo: str, tag: str, token: str, notes: str) -> dict:
    r = gh_api("GET", f"/repos/{repo}/releases/tags/{tag}", token, allow=(404,))
    if r.status_code == 200:
        log(f"github release 已存在: {tag} (id={r.json()['id']})")
        return r.json()
    r = gh_api("POST", f"/repos/{repo}/releases", token, json={
        "tag_name": tag,
        "name": f"Neurova {tag.lstrip('v')}",
        "body": notes,
        "make_latest": "true",
        # 既有 beta1–beta4 一律 prerelease=false，beta6 跟着这条口径，不自己发明新档
        "prerelease": False,
    })
    log(f"github release 已创建: {tag} (id={r.json()['id']})")
    return r.json()


def upload_asset_github(rel: dict, token: str, file: Path) -> None:
    name = file.name
    size = file.stat().st_size
    for a in rel.get("assets", []):
        if a["name"] != name:
            continue
        gh_api("DELETE", a["url"].split(GH_API, 1)[-1], token, allow=(404,))
        log(f"同名旧附件已删除: {name} (id={a['id']})")
        break
    endpoint = rel["upload_url"].split("{", 1)[0] + f"?name={quote(name)}"
    log(f"上传 {name}（{size / 1048576:.0f} MB）…")
    # data=文件句柄 时 requests 会走 chunked，GitHub 直接 411——Content-Length 必须显式给
    with open(file, "rb") as f:
        r = requests.post(endpoint, data=f, timeout=3600, headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/octet-stream",
            "Content-Length": str(size),
        })
    if r.status_code >= 400:
        raise RuntimeError(f"POST asset {name} -> {r.status_code}: {r.text[:300]}")
    log(f"完成 {name}（id={r.json().get('id')}）")


def publish(tag: str, notes: str, files: list[Path], platform: str) -> None:
    if platform in ("cnb", "both"):
        repo = RELEASE_REPO_SLUG["cnb"]
        token = cnb_token()
        rid = ensure_release(repo, tag, token, notes)
        for p in files:
            upload_asset(repo, rid, token, p)
    if platform in ("github", "both"):
        repo = RELEASE_REPO_SLUG["github"]
        token = github_token()
        rel = ensure_release_github(repo, tag, token, notes)
        for p in files:
            upload_asset_github(rel, token, p)
            # 上传后 rel["assets"] 是旧快照：下一件若同名会误判已存在，故整体重取
            rel = gh_api("GET", f"/repos/{repo}/releases/{rel['id']}", token).json()


def main() -> int:
    ap = argparse.ArgumentParser(description="上传 Release 附件（cnb.cool / GitHub）")
    ap.add_argument("tag")
    ap.add_argument("--notes", default="", help="Release 正文；已存在的 release 不覆盖")
    ap.add_argument("--platform", choices=("cnb", "github", "both"), default="cnb")
    ap.add_argument("files", nargs="+")
    args = ap.parse_args()

    missing = [f for f in args.files if not Path(f).exists()]
    for f in missing:
        log(f"跳过不存在的文件: {f}")
    files = [Path(f) for f in args.files if Path(f).exists()]
    if not files:
        raise RuntimeError("没有任何待上传文件存在")

    publish(args.tag,
            args.notes or f"Neurova {args.tag.lstrip('v')} — 安装包见附件。",
            files, args.platform)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as e:
        log(f"失败: {e}")
        sys.exit(1)
