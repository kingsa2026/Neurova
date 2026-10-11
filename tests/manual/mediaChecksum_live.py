# -*- coding: utf-8 -*-
"""活体自证（§6-139 · 甲方案媒体半区）：校验位走真 HTTP 栈一次，不靠单测里的最小 app。

判据（缺一条这条链就是断的）：
1. 真 `TestClient` 走 `POST /api/v1/media/save` 上传一份已知字节的文件 ⇒ 磁盘上真有那份文件，
   且索引里存的 `checksum` 等于**磁盘字节**重算的 sha256（不是请求里传来的字符串）；
2. `GET /api/v1/media/{id}/metadata` 回 `checksum_ok=True`（端点自己读盘重算，不是复读存过的值）；
3. 篡改磁盘字节后同一端点必须回 `checksum_ok=False`——校验位的实质在这一步，前两步只是记账；
4. 换一只新进程对象 `_load_index()`（模拟重启）后校验位仍在；
5. 反向对照：索引里没有校验位的旧条目（升级前落盘的那些）必须回 `checksum_ok is None`，
   而不是 False——否则"老数据一律判损坏"会把这格判据用成事故发生器。

跑法（仓根）：PYTHONPATH=. .venv/Scripts/python.exe tests/manual/mediaChecksum_live.py
"""
from __future__ import annotations

import sys


def main() -> int:
    import hashlib
    import io
    import json
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from tests.manual._liveVerifyIsolation import isolatedDataRoot

    root = isolatedDataRoot()
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from neurova.api.auth import get_current_user
    from neurova.api.endpoints import media as MEDIA

    MEDIA._INDEX_FILE = str(root / "media_index.json")
    MEDIA._CONFIG_FILE = str(root / "media_config.json")
    MEDIA._media_config["storage_path"] = str(root / "media_storage")
    MEDIA._media_store.clear()

    app = FastAPI()
    app.include_router(MEDIA.router, prefix="/api/v1/media")
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "a1", "role": "admin"}

    payload = b"\x89PNG\r\n\x1a\n" + bytes(range(200))
    want = hashlib.sha256(payload).hexdigest()
    failures: list[str] = []

    with TestClient(app, raise_server_exceptions=False) as c:
        up = c.post("/api/v1/media/save",
                    files={"file": ("real.png", io.BytesIO(payload), "image/png")},
                    data={"media_type": "image", "agent_id": "ag1"})
        if up.status_code != 200:
            print(f"\nFAIL\n - 上传就失败了：{up.status_code} {up.text}")
            return 1
        mid = up.json()["data"]["media_id"]

        stored = json.loads(Path(MEDIA._INDEX_FILE).read_text(encoding="utf-8"))["media"][mid]
        # 落盘名带 `{media_id}_` 前缀，按索引自己记的 storage_path 找，不猜文件名规则
        disk = Path(stored["storage_path"])
        onDisk = disk.read_bytes() if disk.is_file() else b""
        print(f"1 磁盘字节重算 sha256 == 索引里的 checksum："
              f"{hashlib.sha256(onDisk).hexdigest() == want}（文件在位={disk.is_file()}）")
        if stored.get("checksum") != want or hashlib.sha256(onDisk).hexdigest() != want:
            failures.append("索引里的校验位与磁盘字节对不上")

        meta = c.get(f"/api/v1/media/{mid}/metadata").json()["data"]
        print(f"2 metadata 读数：checksum_ok={meta.get('checksum_ok')} "
              f"checksum 前 12 位={str(meta.get('checksum'))[:12]}")
        if meta.get("checksum_ok") is not True:
            failures.append("完好文件被报成不通过——校验位读侧没真读盘")

        disk.write_bytes(onDisk + b"tampered")
        after = c.get(f"/api/v1/media/{mid}/metadata").json()["data"]
        print(f"3 篡改后：checksum_ok={after.get('checksum_ok')}")
        if after.get("checksum_ok") is not False:
            failures.append("字节被改过仍不报 False——校验位是摆设")

        # 反向对照：旧条目（无 checksum 字段，升级前落盘的那种）必须回 None 而非 False
        legacy = dict(stored)
        legacy.pop("checksum", None)
        MEDIA._media_store[mid + "-legacy"] = legacy
        old = c.get(f"/api/v1/media/{mid}-legacy/metadata").json()["data"]
        print(f"4 无校验位的旧条目：checksum_ok={old.get('checksum_ok')}（应为 None，不判坏）")
        if old.get("checksum_ok") is not None:
            failures.append("旧条目被判损坏——升级即事故")

    MEDIA._media_store.clear()
    MEDIA._load_index()
    revived = MEDIA._media_store.get(mid, {})
    print(f"5 重启后（清内存 + _load_index）校验位仍在：{revived.get('checksum') == want}")
    if revived.get("checksum") != want:
        failures.append("校验位没随索引落盘，重启即丢")

    app.dependency_overrides.clear()
    if failures:
        print("\nFAIL")
        for f in failures:
            print(" -", f)
        return 1
    print("\nPASS：校验位走真 HTTP 栈写得上、读得回、改得出来、重启不丢，旧条目不误判")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
