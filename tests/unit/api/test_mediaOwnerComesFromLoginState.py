"""媒体归属从登录态取（§6-172 批 24；浏览器实跑验收撞出的第三项）。

来历：`POST /v1/media/save` 的 `user_id` 是**可选表单字段**（`media.py:331`），而现役前端
`saveMedia()` 从不传它（`NeurUI/src/api/modules/media.ts:81` 只带 file/agent_id/metadata）——
于是索引里每一条媒体记录的 `user_id` 恒为 null：**归属这一格从来没被写侧填过**。
按教义第 1 条，这不是"前端补传一个字段"能了事的：客户端自报归属意味着任何人
都能把产物记到别人名下（`user_id` 是标识而非凭证）。修复点在上游——路由本就挂了
`Depends(get_current_user)`（`media.py:40`），登录态就是那份唯一事实源。

口径沿用本仓既有裁定（批 12 流式回合、批 14 语言偏好）：**属主只从登录态取**，
请求体/表单里不给它留口。

判据：
1. 上传后索引里那条的 `user_id` 等于登录用户（不是 null、不是空串）；
2. 报文里塞 `user_id` 不生效——仍以登录态为准（不接受客户端自报）；
3. `save_media` 的签名里没有 `user_id` 形参，只有 `current_user`（形状钉住"不留自报口"，
   否则哪天有人把它接回来，第 2 格会红得毫无征兆）；
4. 元数据读面把归属回得出来（写→读闭环，不是又一次只写不读）；
5. 重启（清索引 + `_load_index()`）后归属仍在盘上读得回来；
6. 身份不可归因时（令牌无 `sub` ⇒ 身份层兜成 `"unknown"`）**显式 401**，不把它当归属写进去。

隔离口径沿用 `test_mediaChecksumIsRecorded.py`：索引/配置常量按 tmp 改指 +
`dependency_overrides` 顶掉鉴权（本仓 `create_app` 是单例，绝不去碰它的全局 overrides）。
"""
import io
import json
import os
import inspect

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_media_0123456789")

from neurova.api.auth import get_current_user
from neurova.api.endpoints import media as MEDIA

OWNER = {"user_id": "kai", "username": "kai", "role": "user"}
PAYLOAD = b"\x89PNG\x0d\x0a\x1a\x0a" + bytes(range(32))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(MEDIA, "_INDEX_FILE", str(tmp_path / "media_index.json"))
    monkeypatch.setattr(MEDIA, "_CONFIG_FILE", str(tmp_path / "media_config.json"))
    MEDIA._media_store.clear()
    MEDIA._media_config["storage_path"] = str(tmp_path / "media_storage")
    app = FastAPI()
    app.include_router(MEDIA.router, prefix="/api/v1/media")
    app.dependency_overrides[get_current_user] = lambda: dict(OWNER)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c, tmp_path
    app.dependency_overrides.clear()
    MEDIA._media_store.clear()


def _upload(c, extra_form=None, name="pic.png"):
    form = {"media_type": "image", "agent_id": "ag1"}
    form.update(extra_form or {})
    r = c.post(
        "/api/v1/media/save",
        files={"file": (name, io.BytesIO(PAYLOAD), "image/png")},
        data=form,
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]["media_id"]


class TestMediaOwnerComesFromLoginState:
    def test_index_record_carries_the_logged_in_owner(self, client):
        c, tmp = client
        mid = _upload(c)
        rec = json.loads((tmp / "media_index.json").read_text(encoding="utf-8"))["media"][mid]
        assert rec.get("user_id") == "kai", (
            f"媒体归属没从登录态填：{rec.get('user_id')!r}——上传面认不到是谁传的")

    def test_self_reported_user_id_in_the_form_is_ignored(self, client):
        """这一格是第 1 格的反照：去掉"不接受自报"这道约束，它必须立刻红。"""
        c, tmp = client
        mid = _upload(c, {"user_id": "someone-else"})
        rec = json.loads((tmp / "media_index.json").read_text(encoding="utf-8"))["media"][mid]
        assert rec.get("user_id") == "kai", (
            f"报文里塞的 user_id 生效了（{rec.get('user_id')!r}）——归属可被任意冒充")

    def test_handler_signature_has_no_client_supplied_owner_slot(self):
        sig = inspect.signature(MEDIA.save_media)
        assert "user_id" not in sig.parameters, (
            "`save_media` 还留着 user_id 形参——客户端自报归属那条口没关掉")
        assert "current_user" in sig.parameters, (
            "签名里没有 current_user，说明归属不是从登录依赖来的")

    def test_metadata_endpoint_returns_the_owner(self, client):
        c, _ = client
        mid = _upload(c, name="meta.png")
        data = c.get(f"/api/v1/media/{mid}/metadata").json()["data"]
        assert data.get("user_id") == "kai", (
            "写侧填了、读面回不出来——归属仍是只写不读的字段")

    def test_owner_survives_restart(self, client):
        c, _ = client
        mid = _upload(c, name="keep.png")
        MEDIA._media_store.clear()
        MEDIA._load_index()
        assert MEDIA._media_store[mid].get("user_id") == "kai", (
            "归属没随索引落盘，或加载时被丢掉")

    def test_unattributable_identity_is_rejected_not_recorded_as_unknown(self, tmp_path, monkeypatch):
        """无 `sub` 的令牌在身份层兜成 "unknown"——照直写进索引就是批 12 那枚
        「usage 落 anonymous」的同形缺陷：归属看着有值，其实谁都不是。显式 401 才诚实。
        """
        monkeypatch.setattr(MEDIA, "_INDEX_FILE", str(tmp_path / "media_index.json"))
        monkeypatch.setattr(MEDIA, "_CONFIG_FILE", str(tmp_path / "media_config.json"))
        MEDIA._media_store.clear()
        MEDIA._media_config["storage_path"] = str(tmp_path / "media_storage")
        app = FastAPI()
        app.include_router(MEDIA.router, prefix="/api/v1/media")
        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": "unknown", "username": "unknown", "role": "user"}
        with TestClient(app, raise_server_exceptions=False) as c:
            r = c.post(
                "/api/v1/media/save",
                files={"file": ("x.png", io.BytesIO(PAYLOAD), "image/png")},
                data={"media_type": "image", "agent_id": "ag1"},
            )
        assert r.status_code == 401, f"本该显式 401 点名身份不可用，实得 {r.status_code}"
        assert "身份" in r.text or "sub" in r.text, f"401 没点名原因：{r.text}"
        assert not MEDIA._media_store, "拒了却还是把产物记进了索引"
        app.dependency_overrides.clear()
        MEDIA._media_store.clear()
