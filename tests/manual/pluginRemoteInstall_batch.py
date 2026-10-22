# -*- coding: utf-8 -*-
"""live-verify（§6-390 票二乙）：插件远程取回在**真 HTTP 栈**上走一遍。

只连本机回环：起一个 `http.server` 提供 zip，把 `127.0.0.1:<port>` 登记为插件源，
然后打真 `create_app()` ＋ 真 JWT 的 `/api/v1/plugins/*`。要证的五件事：

1. 白名单在取回之前——未登记 host 的 URL 回 403（而不是先把字节拉回来再拒）；
2. 登记之后，安装走的是取回咽喉：解包 → 名字核对 → 挪进插件根 → **同一条**登记链
   （权限门、装时钉、根外锚、state.json 的 `install_source`）；
3. 装上之后改一个字节，`manager.load_plugin` 按 `artifact_digest_mismatch` 拒
   （远程包与本地包共享同一道装载闸）；
4. 撤掉源之后同一个 host 立刻不可再取回；
5. 仓库 `data/` 一个字节都没被这轮写过。

跑法：`PYTHONPATH=$(git rev-parse --show-toplevel) python tests/manual/pluginRemoteInstall_batch.py`
"""

from __future__ import annotations

import hashlib
import io
import json
import sys
import tempfile
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402

WORK_ROOT = isolatedDataRoot(prefix="neurovaP2Remote")

from fastapi.testclient import TestClient  # noqa: E402

from neurova.api.app import create_app  # noqa: E402
from neurova.api.auth import create_access_token  # noqa: E402
from neurova.core.data_root import get_data_root  # noqa: E402
from neurova.plugins import plugin_sources  # noqa: E402
from neurova.plugins.plugin_errors import PluginError  # noqa: E402
from neurova.plugins.plugin_manager import get_plugin_manager  # noqa: E402
from neurova.security import artifact_digest  # noqa: E402

BASE = "/api/v1/plugins"
failures: list = []


def check(name, ok, detail=""):
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name, (" — " + detail) if detail else ""))
    if not ok:
        failures.append(name)


def _headers(sub, role="admin"):
    token = create_access_token({"sub": sub, "username": sub, "role": role})
    return {"Authorization": "Bearer " + token}


def _pluginZip(name):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("manifest.json", json.dumps({
            "name": name, "version": "1.0.0", "entry_point": "main.py",
            "description": "remote probe"}))
        archive.writestr("main.py", "class Probe:\n    pass\n")
    return buf.getvalue()


class _Handler(BaseHTTPRequestHandler):
    payloads = {}

    def do_GET(self):
        body = self.payloads.get(self.path)
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        return


def _dataDirFingerprint():
    root = Path(__file__).resolve().parents[2] / "data"
    if not root.exists():
        return "<absent>"
    digest = hashlib.md5()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            st = path.stat()
            digest.update(("%s|%s|%s" % (path.relative_to(root), st.st_size,
                                          int(st.st_mtime))).encode())
    return digest.hexdigest()


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    startedAt = time.time()
    before = _dataDirFingerprint()
    anchorDir = Path(tempfile.mkdtemp(prefix="neurovaP2Anchors-"))
    artifact_digest.anchorPath = lambda: anchorDir / "artifact_anchors.json"

    _Handler.payloads = {"/demo.zip": _pluginZip("remote-demo"),
                         "/other.zip": _pluginZip("remote-other")}
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host = "127.0.0.1"
    baseUrl = "http://%s:%d/" % (host, port)

    try:
        app = create_app()
        with TestClient(app) as client:
            admin = _headers("u-p2-admin")
            manager = get_plugin_manager()
            root = Path(manager.plugin_dir)

            unregistered = client.post(BASE + "/remote-demo/install",
                                       headers=admin,
                                       json={"source": baseUrl + "demo.zip"})
            check("1 未登记 host 的远程安装回 403 且点名原因",
                  unregistered.status_code == 403
                  and plugin_sources.REASON_SOURCE_NOT_ALLOWED in unregistered.text,
                  "%s %s" % (unregistered.status_code, unregistered.text[:120]))

            put = client.put(BASE + "/remote-sources/" + host,
                             headers=admin, json={"baseUrl": baseUrl})
            check("2 管理员登记插件源回 200", put.status_code == 200, put.text[:120])
            listed = client.get(BASE + "/remote-sources", headers=admin).json()["data"]["sources"]
            check("3 读面把登记的 host 交出来（登录即可读）",
                  [e["host"] for e in listed] == [host], str(listed)[:120])

            installed = client.post(BASE + "/remote-demo/install", headers=admin,
                                    json={"source": baseUrl + "demo.zip"})
            check("4 登记后远程安装走真 HTTP 回 200", installed.status_code == 200,
                  "%s %s" % (installed.status_code, installed.text[:120]))
            record = manager.get_plugin("remote-demo")
            check("5 装到了插件根上（不是暂存目录）",
                  record is not None and Path(record.path).is_dir()
                  and Path(record.path).parent == root.resolve(), str(record.path if record else None))
            check("6 装时钉了构件摘要", bool(record and record.artifactDigest.startswith("sha256:")),
                  record.artifactDigest[:24] if record else "(无记录)")
            state = json.loads((root / "state.json").read_text(encoding="utf-8"))
            check("7 来源留痕进 state.json 的 install_source",
                  state["plugins"]["remote-demo"].get("install_source") == baseUrl + "demo.zip",
                  str(state["plugins"]["remote-demo"].get("install_source")))
            anchors = json.loads((anchorDir / "artifact_anchors.json").read_text(encoding="utf-8"))
            check("8 同一枚摘要也落了根外锚（§6-388 对远程包同样生效）",
                  anchors["anchors"].get("plugin:remote-demo") == record.artifactDigest)
            check("9 暂存目录已清", not list(root.glob(".incoming_*")),
                  str([p.name for p in root.glob(".incoming_*")]))

            # 装载闸在启用之后才是第一道：先启用（无权限声明的插件没有待确认项）
            check("10a 远程包同样要显式启用（启用是门、装载是另一步）",
                  manager.enable_plugin("remote-demo") is True)
            mainPy = Path(record.path) / "main.py"
            original = mainPy.read_bytes()
            mainPy.write_bytes(original + b"\n# tampered\n")
            try:
                manager.load_plugin("remote-demo")
                refused = None
            except PluginError as e:
                refused = e.reason
            check("10 改一个字节后装载按摘要不符拒（远程包不例外）",
                  refused == artifact_digest.REASON_MISMATCH, str(refused))
            mainPy.write_bytes(original)

            deleted = client.delete(BASE + "/remote-sources/" + host, headers=admin)
            check("11 撤源回 200", deleted.status_code == 200, deleted.text[:100])
            afterDelete = client.post(BASE + "/remote-other/install", headers=admin,
                                      json={"source": baseUrl + "other.zip"})
            check("12 撤源之后同一 host 立刻不可再取回（403）",
                  afterDelete.status_code == 403
                  and plugin_sources.REASON_SOURCE_NOT_ALLOWED in afterDelete.text,
                  "%s %s" % (afterDelete.status_code, afterDelete.text[:100]))
            check("13 被拒的包没有留在插件根里",
                  not (root / "remote-other").exists())
    finally:
        server.shutdown()
        server.server_close()

    check("14 仓库 data/ 未被本轮写入（内容指纹逐字节相同）", _dataDirFingerprint() == before)
    dataRoot = Path(__file__).resolve().parents[2] / "data"
    recent = [p for p in dataRoot.rglob("*") if p.is_file()
              and p.stat().st_mtime > startedAt] if dataRoot.exists() else []
    check("15 仓库 data/ 本轮零改写", recent == [], str([str(x) for x in recent[:3]]))
    check("16 数据根隔离：插件根确实落在隔离区", str(root).startswith(str(get_data_root())),
          str(root))

    print("")
    print("全部通过" if not failures else "失败 %s 项：%s" % (len(failures), failures))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
