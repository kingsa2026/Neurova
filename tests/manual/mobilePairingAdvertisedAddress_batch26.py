# -*- coding: utf-8 -*-
"""live-verify（工单 2026-10-13 批 26，§6-172）：**发出去的那条回连地址**在活 app 上真连得上。

判据档（`tests/unit/api/test_mobilePairingAdvertisedWsPathResolves.py`）挂的是手搭 `FastAPI()`
+ 注册表同款前缀；这一支要证的是另一件事：在 `create_app()` 的真实路由表上，

- 配对流程发出去的 `ws_url` 与 `qr_code_url`，指向的都是**这台 app 上真实存在**的路径；
- 那张二维码图在活 app 上真渲染得出来（segno 那条路，不是缺依赖的降级）；
- 反向校准：批 25 之前手抄的 `/mobile/ws` 在活 app 上就是连不上——
  否则「照发出去的地址能连上」这一格可能是"怎么连都算通"。

刻意不打真 LLM：本批读的是地址来源，把配额花在读判据上是另一回事（本卷记过）。

跑法：`PYTHONPATH=$(git rev-parse --show-toplevel) python tests/manual/mobilePairingAdvertisedWsPath_batch26.py`
"""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402

WORK_ROOT = isolatedDataRoot(prefix="neurovaMobileAddr26")

from fastapi.testclient import TestClient  # noqa: E402

from neurova.api.app import create_app  # noqa: E402
from neurova.api.endpoints import mobile_pairing as mobile_ep  # noqa: E402

failures: list[str] = []
OWNER = "u-live-26"


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(name)


def main() -> int:
    print(f"数据根（注入隔离）: {WORK_ROOT}")
    mobile_ep._pairing_codes.clear()
    mobile_ep._paired_devices.clear()
    mobile_ep._user_devices.clear()

    app = create_app()
    app.dependency_overrides[mobile_ep._get_current_user_id] = lambda: OWNER
    try:
        with TestClient(app, base_url="http://live.test") as client:
            wsPath = app.router.url_path_for("mobile_websocket")

            gen = client.post("/api/v1/mobile/pairing/generate",
                              json={"device_name": "live-26", "device_type": "mobile"})
            check("[0] 活 app 上 generate 200", gen.status_code == 200,
                  f"{gen.status_code} {gen.text[:120]}")
            if gen.status_code != 200:
                return 1
            body = gen.json()
            code, qrUrl = body["code"], body["qr_code_url"]

            qrPath = urlsplit(qrUrl).path
            check("[1] 发出的 qr_code_url 同源且落在自家渲染端点上",
                  urlsplit(qrUrl).netloc == "live.test" and qrPath == f"/api/v1/mobile/pairing/qrcode/{code}",
                  qrUrl)

            img = client.get(qrPath)
            check("[2] 活 app 上那张图真渲染得出来（PNG 魔数，不是缺依赖的降级）",
                  img.status_code == 200 and img.content[:4] == b"\x89PNG"
                  and img.headers.get("content-type", "").startswith("image/png"),
                  f"{img.status_code} {img.headers.get('content-type')} {len(img.content)}B")

            conf = client.post("/api/v1/mobile/pairing/confirm",
                               json={"code": code, "device_name": "live-26", "device_id": "dev-26"})
            check("[3] 活 app 上 confirm 200 并回出回连地址", conf.status_code == 200,
                  f"{conf.status_code} {conf.text[:120]}")
            if conf.status_code != 200:
                return 1
            wsUrl = conf.json()["ws_url"]
            advertised = urlsplit(wsUrl).path

            check("[4] 发给设备的回连路径 == 活 app 路由表里那条 WS（不是手抄的前缀）",
                  advertised == wsPath, f"发出 {advertised} / 路由表 {wsPath}")

            connected = None
            try:
                with client.websocket_connect(f"{advertised}{_queryOf(wsUrl)}"):
                    connected = "accepted"
            except Exception as e:  # noqa: BLE001
                connected = f"{type(e).__name__} code={getattr(e, 'code', None)}"
            check("[5] 照发出去的那条地址真能连上", connected == "accepted", str(connected))

            legacy = None
            try:
                with client.websocket_connect(f"/mobile/ws{_queryOf(wsUrl)}"):
                    legacy = "accepted"
            except Exception as e:  # noqa: BLE001
                legacy = f"{type(e).__name__} code={getattr(e, 'code', None)}"
            check("[6] 反向校准：旧那条形如 /mobile/ws 的地址在活 app 上连不上",
                  legacy != "accepted", str(legacy))
    finally:
        app.dependency_overrides.clear()
        mobile_ep._pairing_codes.clear()
        mobile_ep._paired_devices.clear()
        mobile_ep._user_devices.clear()

    print("\nLIVE-VERIFY PASSED / 工单 2026-10-13 批 26（配对回连地址向路由表要）"
          if not failures else f"\nLIVE-VERIFY FAILED：{failures}")
    return 0 if not failures else 1


def _queryOf(url: str) -> str:
    q = urlsplit(url).query
    return f"?{q}" if q else ""


if __name__ == "__main__":
    sys.exit(main())
