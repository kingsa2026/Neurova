"""U9+U16 中继侧认证加固判据（先红后绿批）。

红=旧形态三处：URL 携 token 可连、auth 前任意帧照收不拒、同 id 双连静默互抢（旧连接
无 superseded 通知、挂在原地）。绿=连接建立后首消息 auth（5s 窗）＋ URL 门 fail-closed
（兼容开关可回旧形态）＋ 令牌分型通道校验（错型=明确拒绝帧＋审计）＋ newest-wins 顶替。

令牌线格式钉子 `_signToken` 与 `protocol.signTunnelToken` 同构——测试钉的是**线上形状**，
签发实现换了形状这里先红。

跑法：`.venv/Scripts/python.exe -m pytest tests/unit/relay -q --timeout=300`
"""
import concurrent.futures
import hashlib
import hmac
import logging
import os
import secrets
import time

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_tunnel_0123456789")

from neurova.relay.app import create_relay_app  # noqa: E402
from neurova.tunnel import protocol  # noqa: E402

SECRET = "enrollment-token-aaaa"
INSTANCE = "nv-authupgrade"


def _signToken(secret: str, tokenType: str) -> str:
    stamp = int(time.time())
    nonce = secrets.token_hex(8)
    message = f"{protocol.TUNNEL_TOKEN_ENVELOPE}:{tokenType}:{stamp}:{nonce}"
    signature = hmac.new(secret.encode("utf-8"), message.encode("utf-8"),
                         hashlib.sha256).hexdigest()
    return f"{message}:{signature}"


def _authFrame(secret: str, tokenType: str) -> dict:
    return {"type": protocol.FRAME_AUTH, "token": _signToken(secret, tokenType),
            "tokenType": tokenType}


def _connectControl(client, instanceId: str = INSTANCE, enrollmentToken=None):
    query = f"instanceId={instanceId}"
    if enrollmentToken is not None:
        query += f"&{protocol.ENROLLMENT_TOKEN_PARAM}={enrollmentToken}"
    return client.websocket_connect(f"{protocol.RELAY_CONTROL_PATH}?{query}")


def _receiveWithTimeout(ws, seconds: float = 5.0):
    """带界收帧：旧形态"服务端永不关连接"时红灯快速失败，不死等。

    刻意不用 `with ThreadPoolExecutor()`：其退出会 join 仍阻塞在 receive 里的线程，
    等于把超时又变回死等。改为 `shutdown(wait=False)`，孤儿线程随会话关闭自然退出。
    """
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = pool.submit(ws.receive_json)
    try:
        return future.result(timeout=seconds)
    except concurrent.futures.TimeoutError:
        raise AssertionError(
            f"服务端未在 {seconds}s 内回帧或断开（疑似未认证连接被挂住）") from None
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def _readUntilClose(ws, seconds: float = 5.0) -> tuple:
    """收帧直到服务端断开。回 `(帧列表, 关闭码)`；超时未断开按失败处理。"""
    frames = []
    while True:
        try:
            frames.append(_receiveWithTimeout(ws, seconds))
        except concurrent.futures.TimeoutError:
            raise AssertionError(f"服务端未在 {seconds}s 内断开（疑似未认证连接被挂住）：已收 {frames}")
        except Exception as e:  # noqa: BLE001 - 服务端断开即正常收尾
            return frames, getattr(e, "code", None)


# ---------------------------------------------------------------------------
# U9.1 · token 后置：连接建立后首条 auth，auth 前不接受任何其他帧
# ---------------------------------------------------------------------------


class TestPostConnectAuth:
    def test_control_first_message_auth_registers(self):
        app = create_relay_app(SECRET)
        with TestClient(app) as c:
            with _connectControl(c) as ws:
                ws.send_json(_authFrame(SECRET, protocol.TOKEN_TYPE_SERVICE))
                registered = ws.receive_json()
        assert registered["type"] == protocol.FRAME_REGISTERED, registered
        assert registered["routeId"], registered

    def test_control_rejects_any_frame_before_auth(self):
        """auth 前的其他帧（含 ping）不受理：明确拒绝帧＋断开，不让未认证连接进服务环。"""
        app = create_relay_app(SECRET)
        with TestClient(app) as c:
            with _connectControl(c) as ws:
                ws.send_json({"type": protocol.FRAME_PING, "echo": 1.0})
                frames, code = _readUntilClose(ws)
        assert frames, "auth 前的其他帧必须给出明确拒绝帧"
        assert frames[0]["type"] == protocol.FRAME_ERROR, frames
        assert frames[0]["code"] == protocol.TUNNEL_ERROR_AUTH_REJECTED, frames
        assert code == 4401, code

    def test_control_silence_past_auth_window_is_cut(self):
        """5s auth 窗（测试用 0.2s 短窗）：窗口内不交 auth ⇒ 断开，且必须及时。"""
        app = create_relay_app(SECRET, authTimeoutSeconds=0.2)
        with TestClient(app) as c:
            started = time.time()
            with _connectControl(c) as ws:
                frames, _ = _readUntilClose(ws)
        assert time.time() - started < 5, "auth 超时必须及时断开，不许挂着"
        assert not any(f.get("type") == protocol.FRAME_REGISTERED for f in frames), frames
        assert frames and frames[0]["code"] == protocol.TUNNEL_ERROR_AUTH_TIMEOUT, frames


# ---------------------------------------------------------------------------
# U9.1 · URL 门：默认 fail-closed 拒绝 URL 携 token；开关打开才回旧形态
# ---------------------------------------------------------------------------


class TestUrlTokenGate:
    def test_control_url_token_form_rejected_by_default_even_with_valid_token(self):
        app = create_relay_app(SECRET)
        with TestClient(app) as c:
            with _connectControl(c, enrollmentToken=SECRET) as ws:
                frames, code = _readUntilClose(ws)
        assert not any(f.get("type") == protocol.FRAME_REGISTERED for f in frames), frames
        assert frames and frames[0]["type"] == protocol.FRAME_ERROR, frames
        assert frames[0]["code"] == protocol.TUNNEL_ERROR_URL_TOKEN_REJECTED, frames
        assert code == 4401, code

    def test_data_url_token_form_rejected_by_default(self):
        app = create_relay_app(SECRET)
        with TestClient(app) as c:
            with c.websocket_connect(
                    f"{protocol.RELAY_DATA_PATH}?{protocol.ENROLLMENT_TOKEN_PARAM}={SECRET}") as ws:
                frames, _ = _readUntilClose(ws)
        assert frames and frames[0]["code"] == protocol.TUNNEL_ERROR_URL_TOKEN_REJECTED, frames

    def test_url_token_compat_switch_restores_old_form(self, monkeypatch):
        """回滚闸门：`NEUROVA_TUNNEL_URL_TOKEN=1` 时旧形态照旧可用（两端同开才有效）。"""
        monkeypatch.setenv(protocol.URL_TOKEN_COMPAT_ENV, "1")
        app = create_relay_app(SECRET)
        with TestClient(app) as c:
            with _connectControl(c, enrollmentToken=SECRET) as ws:
                registered = ws.receive_json()
        assert registered["type"] == protocol.FRAME_REGISTERED, registered


# ---------------------------------------------------------------------------
# U16 · 令牌分型：控制面仅 user/service，数据面仅 agent/service，错型=拒绝帧+审计
# ---------------------------------------------------------------------------


class TestTokenTypes:
    def test_control_accepts_user_and_service_rejects_agent(self, caplog):
        app = create_relay_app(SECRET)
        with caplog.at_level(logging.WARNING, logger="neurova.relay.app"):
            with TestClient(app) as c:
                with _connectControl(c, instanceId="nv-svc") as ws:
                    ws.send_json(_authFrame(SECRET, protocol.TOKEN_TYPE_SERVICE))
                    assert ws.receive_json()["type"] == protocol.FRAME_REGISTERED
                with _connectControl(c, instanceId="nv-usr") as ws:
                    ws.send_json(_authFrame(SECRET, protocol.TOKEN_TYPE_USER))
                    assert ws.receive_json()["type"] == protocol.FRAME_REGISTERED
                with _connectControl(c, instanceId="nv-agt") as ws:
                    ws.send_json(_authFrame(SECRET, protocol.TOKEN_TYPE_AGENT))
                    frames, code = _readUntilClose(ws)
        assert frames and frames[-1].get("code") == protocol.TUNNEL_ERROR_TOKEN_TYPE_REJECTED, frames
        assert code == 4403, code
        assert "token_type_rejected" in caplog.text, caplog.text[-800:]

    def test_data_accepts_agent_and_service_rejects_user(self):
        app = create_relay_app(SECRET)
        with TestClient(app) as c:
            for tokenType, shouldPass in ((protocol.TOKEN_TYPE_AGENT, True),
                                          (protocol.TOKEN_TYPE_SERVICE, True),
                                          (protocol.TOKEN_TYPE_USER, False)):
                with c.websocket_connect(protocol.RELAY_DATA_PATH) as ws:
                    ws.send_json(_authFrame(SECRET, tokenType))
                    first = ws.receive_json()
                if shouldPass:
                    assert first["type"] == protocol.FRAME_AUTH_OK, (tokenType, first)
                else:
                    assert first["type"] == protocol.FRAME_ERROR, (tokenType, first)
                    assert first["code"] == protocol.TUNNEL_ERROR_TOKEN_TYPE_REJECTED, first

    def test_wrong_type_rejection_writes_audit_line(self, caplog):
        app = create_relay_app(SECRET)
        with caplog.at_level(logging.WARNING, logger="neurova.relay.app"):
            with TestClient(app) as c:
                with _connectControl(c) as ws:
                    ws.send_json(_authFrame(SECRET, protocol.TOKEN_TYPE_AGENT))
                    _readUntilClose(ws)
        assert "AUDIT" in caplog.text and "token_type_rejected" in caplog.text, caplog.text[-800:]


# ---------------------------------------------------------------------------
# U16 · legacy 降级与验签拒绝
# ---------------------------------------------------------------------------


class TestLegacyAndSignature:
    def test_legacy_secret_on_data_plane_works_and_is_flagged(self, caplog):
        """旧裸密钥（无 type 信封）按 agent 型降级：数据面放行＋日志标注 legacy。"""
        app = create_relay_app(SECRET)
        with caplog.at_level(logging.WARNING, logger="neurova.relay.app"):
            with TestClient(app) as c:
                with c.websocket_connect(protocol.RELAY_DATA_PATH) as ws:
                    ws.send_json({"type": protocol.FRAME_AUTH, "token": SECRET,
                                  "tokenType": protocol.TOKEN_TYPE_AGENT})
                    first = ws.receive_json()
        assert first["type"] == protocol.FRAME_AUTH_OK, first
        assert "legacy" in caplog.text.lower(), caplog.text[-800:]

    def test_legacy_secret_on_control_plane_rejected_as_wrong_type(self):
        """agent 型不进控制面：旧裸密钥降级为 agent 型后在控制面按错型拒绝。"""
        app = create_relay_app(SECRET)
        with TestClient(app) as c:
            with _connectControl(c) as ws:
                ws.send_json({"type": protocol.FRAME_AUTH, "token": SECRET,
                              "tokenType": protocol.TOKEN_TYPE_AGENT})
                frames, code = _readUntilClose(ws)
        assert frames and frames[-1].get("code") == protocol.TUNNEL_ERROR_TOKEN_TYPE_REJECTED, frames
        assert code == 4403, code

    def test_bad_signature_rejected(self):
        app = create_relay_app(SECRET)
        with TestClient(app) as c:
            with _connectControl(c) as ws:
                ws.send_json(_authFrame("a-different-secret", protocol.TOKEN_TYPE_SERVICE))
                frames, code = _readUntilClose(ws)
        assert frames and frames[-1].get("code") == protocol.TUNNEL_ERROR_AUTH_REJECTED, frames
        assert code == 4401, code

    def test_token_type_claim_mismatch_rejected(self):
        """auth 帧里声明的 tokenType 与签名内的型不一致 ⇒ 拒绝（声明不作为凭据）。"""
        token = _signToken(SECRET, protocol.TOKEN_TYPE_SERVICE)
        app = create_relay_app(SECRET)
        with TestClient(app) as c:
            with _connectControl(c) as ws:
                ws.send_json({"type": protocol.FRAME_AUTH, "token": token,
                              "tokenType": protocol.TOKEN_TYPE_AGENT})
                frames, _ = _readUntilClose(ws)
        assert frames and frames[-1].get("code") == protocol.TUNNEL_ERROR_AUTH_REJECTED, frames


# ---------------------------------------------------------------------------
# U9.2 · newest-wins：同 routeId 新连接顶替旧连接，旧连接干净退出且不回抢
# ---------------------------------------------------------------------------


class TestNewestWins:
    def test_newer_connection_supersedes_older_and_old_exits(self):
        app = create_relay_app(SECRET)
        with TestClient(app) as c:
            # 旧连接的 with 块包住新连接的建立：顶替发生时两条都在场
            with _connectControl(c) as old:
                old.send_json(_authFrame(SECRET, protocol.TOKEN_TYPE_SERVICE))
                first = old.receive_json()
                assert first["type"] == protocol.FRAME_REGISTERED, first

                with _connectControl(c) as new:
                    new.send_json(_authFrame(SECRET, protocol.TOKEN_TYPE_SERVICE))
                    second = new.receive_json()
                    assert second["type"] == protocol.FRAME_REGISTERED, second
                    assert second["routeId"] == first["routeId"], "同 instanceId 必得同 route"

                    # 旧连接必须收到 superseded 通知（旧实现静默互抢，这里红）
                    superseded = _receiveWithTimeout(old, seconds=5)
                    assert superseded["type"] == protocol.FRAME_SUPERSEDED, superseded
                    assert superseded["routeId"] == first["routeId"], superseded

                    # 随后旧连接被服务端干净断开
                    with pytest.raises(Exception):
                        _receiveWithTimeout(old, seconds=5)

                    # 不回抢：在册表只剩新连接这一份
                    deadline = time.time() + 2
                    while time.time() < deadline and len(app.state.relay.controlByRoute) != 1:
                        time.sleep(0.02)
                    assert len(app.state.relay.controlByRoute) == 1, \
                        app.state.relay.controlByRoute

                    # 新连接照常服务
                    new.send_json({"type": protocol.FRAME_PING, "echo": 1.0})
                    assert new.receive_json()["type"] == protocol.FRAME_PONG
