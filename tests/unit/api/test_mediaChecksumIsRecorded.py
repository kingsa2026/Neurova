"""媒体产物的 sha256 校验位（§6-139；序 6 甲方案的媒体半区）。

来历：`neurova/media/manager.py`(184) 与 REST 端点自持那份是同职两份，AST 复算它
**生产零消费者**、唯一用者是它自己的测试（§6-128/§6-135）。但逐格比对显示它握着一格端点那份
没有的东西——**落盘字节记 sha256 校验位**（`manager.py:65`），而 `api/endpoints/media.py` 全档
不出现 `sha256`/`checksum`。按教义第 7 条这不叫"删弱者"，要先取长补短：校验位并进端点索引，
再退 manager.py（用户裁甲）。

判据按能力实质写，不按"多存了一个字段"写：

1. 上传后索引里那条必须带**真等于字节**的 64 位十六进制 sha256（哈希值可核，不是占位串）；
2. 元数据端点回 checksum 并**真读盘重算**给出 `checksum_ok`——"校验位"的意义在于能判好坏；
3. 篡改盘上字节后 `checksum_ok` 必须翻 False（这一格红，前两格才算不是摆设）；
4. 重启（清内存索引 + `_load_index()`）后校验位仍在——否则它只是又一次"只写不读"；
5. 索引的写侧要受锁（manager.py 那份有 `self._lock`，端点这份此前是裸 dict + 裸 dump）：
   并发上传后条目一个不丢、索引文件仍可解析。

隔离口径沿用 `test_media_persistence.py`：`NEUROVA_MEDIA_INDEX_PATH` 那两份常量按 tmp 改指 +
`dependency_overrides` 顶掉鉴权（本仓 create_app 是单例，绝不去碰它的全局 overrides）。
"""
import hashlib
import io
import json
import os
import threading

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_media_0123456789")

from neurova.api.auth import get_current_user
from neurova.api.endpoints import media as MEDIA

ADMIN = {"user_id": "a1", "username": "a1", "role": "admin"}
PAYLOAD = b"\x89PNG\x0d\x0a\x1a\x0a" + bytes(range(64))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(MEDIA, "_INDEX_FILE", str(tmp_path / "media_index.json"))
    monkeypatch.setattr(MEDIA, "_CONFIG_FILE", str(tmp_path / "media_config.json"))
    MEDIA._media_store.clear()
    # 存储根必须走 monkeypatch（整份字典替换），不能就地改模块级 `_media_config`：
    # 就地改是**没有回滚**的——本档跑完，`storage_path` 停在本文用例的 tmp_path 上，
    # 后续同进程的媒体判据（`test_mediaTrashLifecycle` 的 `defaultConfigClient`
    # 会复制当前 `_media_config`）读到别人的绝对路径，明明"未配置"却指到别处，
    # 于是 `TestStorageRootIsNeverCwdRelative` 两格在整批里必红、单跑却绿。
    monkeypatch.setitem(MEDIA._media_config, "storage_path", str(tmp_path / "media_storage"))
    app = FastAPI()
    app.include_router(MEDIA.router, prefix="/api/v1/media")
    app.dependency_overrides[get_current_user] = lambda: dict(ADMIN)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c, tmp_path
    app.dependency_overrides.clear()
    MEDIA._media_store.clear()


def _upload(c, name="pic.png", payload=PAYLOAD):
    r = c.post(
        "/api/v1/media/save",
        files={"file": (name, io.BytesIO(payload), "image/png")},
        data={"media_type": "image", "agent_id": "ag1"},
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]["media_id"]


class TestChecksumIsRecorded:
    def test_index_record_carries_the_real_sha256(self, client):
        c, tmp = client
        mid = _upload(c)
        rec = json.loads((tmp / "media_index.json").read_text(encoding="utf-8"))["media"][mid]
        checksum = rec.get("checksum")
        assert checksum, "索引里没有校验位——产物落盘后无法证明它还是当初那份"
        assert checksum == hashlib.sha256(PAYLOAD).hexdigest(), (
            f"校验位与字节不符（是占位串不是真哈希）：{checksum}")

    def test_metadata_reports_checksum_and_verifies_from_disk(self, client):
        c, _ = client
        mid = _upload(c)
        data = c.get(f"/api/v1/media/{mid}/metadata").json()["data"]
        assert data.get("checksum") == hashlib.sha256(PAYLOAD).hexdigest()
        assert data.get("checksum_ok") is True, (
            "checksum_ok 必须真读盘重算——只回存过的字符串等于没有校验")

    def test_tampered_bytes_are_detected(self, client):
        """这一条是校验位的实质：不篡改能过、篡改必须翻红。"""
        c, tmp = client
        mid = _upload(c)
        path = tmp / "media_storage" / "ag1" / "image"
        victim = next(p for p in path.rglob("*") if p.is_file())
        victim.write_bytes(victim.read_bytes() + b"appended")

        data = c.get(f"/api/v1/media/{mid}/metadata").json()["data"]
        assert data.get("checksum_ok") is False, (
            "字节被改过仍报 ok——那格校验位是摆设")

    def test_checksum_survives_restart(self, client):
        c, tmp = client
        mid = _upload(c, "keep.png")
        MEDIA._media_store.clear()
        MEDIA._load_index()
        rec = MEDIA._media_store[mid]
        assert rec.get("checksum") == hashlib.sha256(PAYLOAD).hexdigest(), (
            "校验位没落盘或加载时被丢掉——那就是一次新的只写不读")

    def test_concurrent_uploads_lose_no_entry(self, client):
        """锁的实质：8 路并发上传后索引一个不丢、文件仍可解析（manager 那份有 self._lock）。"""
        c, tmp = client
        ids, errors = [], []
        gate = threading.Barrier(8)

        def one(n):
            gate.wait(timeout=10)
            try:
                ids.append(_upload(c, f"c{n}.png", PAYLOAD + bytes([n])))
            except Exception as e:  # noqa: BLE001
                errors.append(f"{type(e).__name__}: {e}")

        threads = [threading.Thread(target=one, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert not errors, f"并发上传抛错：{errors}"
        assert len(ids) == 8
        onDisk = json.loads((tmp / "media_index.json").read_text(encoding="utf-8"))["media"]
        assert len(onDisk) == 8, f"索引只剩 {len(onDisk)} 条——后写的把先写的覆盖掉了"
