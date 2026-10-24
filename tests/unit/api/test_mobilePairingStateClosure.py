"""一次性 `ref`、`resolve` 与接入凭证的分层（设计方案 §3.4／§4.1／§4.2／§4.7，S1b 批）。

现状（2026-10-24 实测）：
- 二维码渲的是**含 host 的完整回连地址**（`mobile_pairing.py:633` 把 `_build_ws_url(...)` 交出去），
  于是「谁在配对」与「服务在哪」写进了同一串字节——地址一漂移，已发的码与已配设备一起作废；
- 两端载荷各说各话：App 声明 `neurova://pair?code=`，服务端出的是裸 `ws://…?code=`，
  今天只靠 `code=` 这个子串巧合对上（`PairingPage.ets:50-51` vs `mobile_pairing.py:633`）；
- 凭证挂在 query（`_build_ws_url(..., token=...)`），经中继必然落进中继的访问日志。

本批判四件事：
1. 载荷 = `neurova://pair?ref=<22B base62>`，**不含任何 host**；`ref` 与 6 位短码是
   同一条配对记录的两个入口，不是两个凭据；
2. `resolve` 一次性消费 `ref`（`pending → scanned`），**没有 `scanned → pending` 回边**；
3. `confirm` 回一次性 `connectTicket`；回连地址里**不带任何凭证**；
4. 接入凭证过期后由设备身份（`pairingId + deviceSecret`）经 `/pairing/refresh` 续期，
   **续签不改在册状态**（§5.1b）——重扫只应发生在"设备已被解除"之后。

跑法：`.venv/Scripts/python.exe -m pytest -q tests/unit/api/test_mobilePairingStateClosure.py -p no:cacheprovider`
"""
import ast
import io
import os
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_stateclosure_0123")
# 刻意**不**在这里 setdefault NEUROVA_WS_SECRET：`test_mobile_pairing_p0.py` 那一格审的
# 正是"生产环境没配 WS_SECRET 必须拒绝"，模块顶层写这个 env 会把它的读数污染成"配了"
# ——跨档污染且无声（本卷形态 396：抄既有夹具会继承它的跨档污染）。
# 开发态本来就有兜底密钥，本档不需要它。

from neurova.api.endpoints import mobile_pairing as MP  # noqa: E402
from neurova.tunnel import protocol  # noqa: E402

PREFIX = "/api/v1/mobile"
REPO = Path(__file__).resolve().parents[3]
OWNER = "kai"


@pytest.fixture()
def app_and_client():
    MP._pairing_codes.clear()
    MP._ws_connections.clear()
    MP.resetDeviceRegistry()
    app = FastAPI()
    app.include_router(MP.router, prefix=PREFIX)
    app.dependency_overrides[MP._get_current_user_id] = lambda: OWNER
    with TestClient(app, base_url="http://testserver") as c:
        yield app, c
    app.dependency_overrides.clear()
    MP._pairing_codes.clear()
    MP.resetDeviceRegistry()


def _generate(client):
    resp = client.post(f"{PREFIX}/pairing/generate",
                       json={"device_name": "probe", "device_type": "mobile"})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _qrBytes(client, code):
    img = client.get(f"{PREFIX}/pairing/qrcode/{code}")
    assert img.status_code == 200, img.text
    return img.content


class TestQrPayloadCarriesNoAddress:
    """载荷只回答「谁」，不回答「在哪」——这是无固定 IP 场景的前提，不是风格偏好。"""

    def test_qr_text_is_a_bare_ref_and_contains_no_host(self, app_and_client, monkeypatch):
        _app, c = app_and_client
        monkeypatch.setenv("NEUROVA_ADVERTISED_BASE_URL", "https://home.example.net")
        body = _generate(c)
        assert protocol.isPairingRefShape(body["ref"]), body

        payload = protocol.pairingQrPayload(body["ref"])
        assert payload == f"neurova://pair?ref={body['ref']}"
        for forbidden in ("home.example.net", "testserver", "ws://", "wss://", "http"):
            assert forbidden not in payload, f"载荷里出现了地址成分 {forbidden!r}：{payload}"

    def test_the_text_handed_to_the_single_renderer_has_no_address(self, app_and_client, monkeypatch):
        """真读那次渲染的入参，而不是读"应当是什么"。

        为什么不用图回解：`pyzbar` 不在依赖清单里，写成回解判据会**永久 skip**——
        "跑不起来的判据"比没有判据更糟，它让这一格看起来在跑（教义第 2 条禁止的形态）。
        渲染器是全仓唯一那份（`qrcode_auth.generate_qrcode_image`，segno），
        它收到的文本就是图的内容；渲染不出会显式 500，不会静默出占位图（批 25 已钉）。
        """
        from neurova.channels import qrcode_auth

        _app, c = app_and_client
        monkeypatch.setenv("NEUROVA_ADVERTISED_BASE_URL", "https://home.example.net")
        body = _generate(c)

        captured = []
        real = qrcode_auth.generate_qrcode_image

        def spy(scan_url: str) -> str:
            captured.append(scan_url)
            return real(scan_url)

        monkeypatch.setattr(qrcode_auth, "generate_qrcode_image", spy)
        png = _qrBytes(c, body["code"])
        assert png[:4] == b"\x89PNG", "回来的不是真图"

        assert captured == [protocol.pairingQrPayload(body["ref"])], (
            f"渲染出去的文本不是无地址载荷：{captured!r}")
        for forbidden in ("home.example.net", "testserver", "ws://", "wss://"):
            assert forbidden not in captured[0], f"图里含地址成分 {forbidden!r}"

    def test_short_code_and_ref_address_the_same_record(self, app_and_client):
        """两个入口一条记录（教义第 6 条：不建第二套凭据体系）。"""
        _app, c = app_and_client
        body = _generate(c)
        record = MP._pairing_codes[body["code"]]
        assert record["ref"] == body["ref"]
        assert record["pairing_id"] == body["pairing_id"]


class TestResolveIsOneTime:
    def test_resolve_returns_route_and_moves_record_to_scanned(self, app_and_client, monkeypatch):
        _app, c = app_and_client
        monkeypatch.setenv("NEUROVA_ADVERTISED_BASE_URL", "https://home.example.net")
        body = _generate(c)

        resolved = c.post(f"{PREFIX}/pairing/resolve", json={"ref": body["ref"]})
        assert resolved.status_code == 200, resolved.text
        data = resolved.json()
        assert urlsplit(data["ws_url"]).netloc == "home.example.net", data
        assert MP._pairing_codes[body["code"]]["status"] == "scanned"

    def test_second_resolve_of_the_same_ref_is_refused(self, app_and_client):
        """一次性：拍下降来的那张图，超时后也换不到第二次地址。"""
        _app, c = app_and_client
        body = _generate(c)
        assert c.post(f"{PREFIX}/pairing/resolve", json={"ref": body["ref"]}).status_code == 200

        again = c.post(f"{PREFIX}/pairing/resolve", json={"ref": body["ref"]})
        assert again.status_code in (409, 410), f"同一个 ref 被兑换了两次：{again.status_code}"

    def test_resolve_is_rate_limited_per_ip(self, app_and_client):
        """匿名口必须有闸：高熵 ref 不等于不限流，否则中继被当成放大器打。"""
        _app, c = app_and_client
        codes = {c.post(f"{PREFIX}/pairing/resolve",
                        json={"ref": "x" * protocol.PAIRING_REF_LENGTH}).status_code
                 for _ in range(protocol.CONFIRM_RATE_LIMIT + 3)}
        assert 429 in codes, f"resolve 打了 {protocol.CONFIRM_RATE_LIMIT + 3} 次没有一个 429：{codes}"


class TestTicketStaysOutOfUrl:
    def test_confirm_returns_ticket_but_a_clean_ws_url(self, app_and_client):
        _app, c = app_and_client
        body = _generate(c)
        conf = c.post(f"{PREFIX}/pairing/confirm",
                      json={"ref": body["ref"], "device_name": "phone", "device_id": "d1"})
        assert conf.status_code == 200, conf.text
        data = conf.json()

        assert data["connect_ticket"], "确认了却没拿到接入凭证"
        assert "ticket" not in data["ws_url"] and "token" not in data["ws_url"], (
            f"凭证又回到了 URL 里，经中继必然落进中继的访问日志：{data['ws_url']}")
        assert parse_qs(urlsplit(data["ws_url"]).query) == {}, data["ws_url"]

    def test_ticket_is_single_use_across_connections(self, app_and_client):
        """一次性凭证用第二次必须被拒（可重放的接入凭证＝中继日志泄露后的现成钥匙）。"""
        _app, c = app_and_client
        body = _generate(c)
        conf = c.post(f"{PREFIX}/pairing/confirm", json={"ref": body["ref"]}).json()
        path = urlsplit(conf["ws_url"]).path
        ticket = conf["connect_ticket"]

        first = _connectOutcome(c, path, ticket)
        assert first == "accepted", f"首次连接就该成：{first}"
        second = _connectOutcome(c, path, ticket)
        assert second != "accepted", f"同一个 ticket 第二次仍然连上：{second}"


def _connectOutcome(client, path: str, ticket: str) -> str:
    """带凭证连一次——凭证走 **header**，不走 URL（§4.2：进 URL 就会被中继记进访问日志）。"""
    try:
        with client.websocket_connect(path, headers={"Authorization": f"Bearer {ticket}"}):
            return "accepted"
    except Exception as e:  # noqa: BLE001 - 要的就是连不上这件事
        return f"{type(e).__name__} code={getattr(e, 'code', None)}"


class TestRefreshExtendsWithoutRePairing:
    def test_refresh_issues_a_new_ticket_and_keeps_registry_state(self, app_and_client):
        """续签是**续期**不是重新配对：状态必须原地不动（§5.1b）。"""
        _app, c = app_and_client
        body = _generate(c)
        conf = c.post(f"{PREFIX}/pairing/confirm", json={"ref": body["ref"]}).json()
        pairingId = conf["pairing_id"]
        secret = conf["device_secret"]
        before = MP.getDeviceRegistry().get(pairingId)

        refreshed = c.post(f"{PREFIX}/pairing/refresh",
                           json={"pairing_id": pairingId, "device_secret": secret,
                                 "challenge": "nonce-1"})
        assert refreshed.status_code == 200, refreshed.text
        assert refreshed.json()["connect_ticket"], refreshed.text

        after = MP.getDeviceRegistry().get(pairingId)
        assert after["state"] == before["state"], (
            f"续签把在册态从 {before['state']} 改成了 {after['state']}——那是重新配对，不是续期")

    def test_refresh_with_wrong_device_secret_is_refused(self, app_and_client):
        _app, c = app_and_client
        body = _generate(c)
        conf = c.post(f"{PREFIX}/pairing/confirm", json={"ref": body["ref"]}).json()

        bad = c.post(f"{PREFIX}/pairing/refresh",
                     json={"pairing_id": conf["pairing_id"], "device_secret": "guess",
                           "challenge": "nonce-1"})
        assert bad.status_code in (401, 403), f"错的设备身份却续上了：{bad.status_code}"

    def test_revoked_device_cannot_refresh(self, app_and_client):
        """解除是唯一需要重扫的路径：撤销之后续签必须一起断掉。"""
        _app, c = app_and_client
        body = _generate(c)
        conf = c.post(f"{PREFIX}/pairing/confirm", json={"ref": body["ref"]}).json()
        assert c.delete(f"{PREFIX}/pairing/{conf['pairing_id']}").status_code == 200

        again = c.post(f"{PREFIX}/pairing/refresh",
                       json={"pairing_id": conf["pairing_id"],
                             "device_secret": conf["device_secret"], "challenge": "n"})
        assert again.status_code in (401, 403, 410), f"已解除的设备还能续签：{again.status_code}"


class TestCodeAndRevokedStatesAreProduced:
    """§2.5 那两格缺口：`revoked` 此前从不产生、过期直接 pop 让面板只能读到 404。"""

    def test_revoke_marks_the_pairing_code_revoked_and_it_is_readable(self, app_and_client):
        _app, c = app_and_client
        body = _generate(c)
        conf = c.post(f"{PREFIX}/pairing/confirm", json={"ref": body["ref"]}).json()
        assert c.delete(f"{PREFIX}/pairing/{conf['pairing_id']}").status_code == 200

        status = c.get(f"{PREFIX}/pairing/status/{body['code']}")
        assert status.status_code == 200, (
            f"解除后读不到终态（回 {status.status_code}）——面板只能把『有人解除了设备』"
            "渲染成网络故障")
        assert status.json()["status"] == "revoked"

    def test_cancel_aborts_the_code_and_a_fresh_code_follows(self, app_and_client):
        """面板上的「取消并换码」要有落点：`aborted` 是可达态（§5.1）。"""
        _app, c = app_and_client
        body = _generate(c)
        aborted = c.post(f"{PREFIX}/pairing/cancel", json={"code": body["code"]})
        assert aborted.status_code == 200, aborted.text
        assert MP._pairing_codes[body["code"]]["status"] == "aborted"

    def test_there_is_no_back_edge_from_scanned_to_pending(self, app_and_client):
        """§10.1 已裁：`ref` 消费后不回边。这里验**行为**，枚举集合那条在单源守卫里。"""
        _app, c = app_and_client
        body = _generate(c)
        assert c.post(f"{PREFIX}/pairing/resolve", json={"ref": body["ref"]}).status_code == 200
        # 让码"过期"再试图走通：必须回终态，而不是回到待扫
        MP._pairing_codes[body["code"]]["expires_at"] = 0
        assert c.post(f"{PREFIX}/pairing/resolve", json={"ref": body["ref"]}).status_code in (409, 410)
        assert MP._pairing_codes[body["code"]]["status"] != "pending"


class TestLegacyQueryTokenStillGuarded:
    """旧形态退役要与新接线同批（教义第 7 条）：留一版兼容，但必须被点名。

    这两格**按 AST 取代码文本**，先剥掉 docstring——本卷形态 410 记过：
    拿整份文件做子串包含断言，会被"解释旧坑的那句注释"自己撞红，
    也会被"注释里写了正确做法"糊成假绿。钉的是代码形态，不是词。
    """

    @staticmethod
    def _functionCodeText(moduleTree: ast.AST, functionName: str) -> str:
        """函数体原文，**去掉 docstring**（docstring 里写着"原先挂过 ?token="是历史说明）。"""
        for node in ast.walk(moduleTree):
            if isinstance(node, ast.FunctionDef) and node.name == functionName:
                body = list(node.body)
                if body and isinstance(body[0], ast.Expr) \
                        and isinstance(body[0].value, ast.Constant) \
                        and isinstance(body[0].value.value, str):
                    body = body[1:]
                return "\n".join(ast.unparse(item) for item in body)
            if isinstance(node, ast.AsyncFunctionDef) and node.name == functionName:
                body = list(node.body)
                if body and isinstance(body[0], ast.Expr) \
                        and isinstance(body[0].value, ast.Constant) \
                        and isinstance(body[0].value.value, str):
                    body = body[1:]
                return "\n".join(ast.unparse(item) for item in body)
        raise AssertionError(f"函数 {functionName} 不在了——判据读的对象已经不存在")

    @classmethod
    def _literalStringsOutsideDocstrings(cls, moduleTree: ast.AST) -> list:
        """全模块的字符串**字面量**（表达式与赋值里的），排除各处 docstring。"""
        docstrings = set()
        for node in ast.walk(moduleTree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                first = (node.body or [None])[0]
                if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                        and isinstance(first.value.value, str):
                    docstrings.add(id(first.value))
        return [node.value for node in ast.walk(moduleTree)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in docstrings]

    def test_ws_url_builder_puts_no_credential_into_the_url(self):
        tree = ast.parse(io.open(REPO / "neurova/api/endpoints/mobile_pairing.py",
                                 encoding="utf-8").read())
        body = self._functionCodeText(tree, "_build_ws_url")
        for forbidden in ("token", "ticket", "code"):
            assert forbidden + "=" not in body, (
                f"_build_ws_url 又开始往 URL 里塞 {forbidden}：经中继它就进中继日志")

    def test_payload_text_is_built_in_exactly_one_place(self):
        """载荷文本只在 `protocol.pairingQrPayload()` 造一次，端点不自己拼第二份。"""
        endpointTree = ast.parse(io.open(REPO / "neurova/api/endpoints/mobile_pairing.py",
                                         encoding="utf-8").read())
        protocolTree = ast.parse(io.open(REPO / "neurova/tunnel/protocol.py",
                                         encoding="utf-8").read())
        endpointLiterals = self._literalStringsOutsideDocstrings(endpointTree)
        assert not [s for s in endpointLiterals if "neurova://pair" in s], (
            f"端点里还有第二份载荷拼法：{[s for s in endpointLiterals if 'neurova' in s]}")
        protocolLiterals = self._literalStringsOutsideDocstrings(protocolTree)
        assert [s for s in protocolLiterals if "neurova://pair" in s], (
            "单源那侧反而没有载荷形状了——上面那条排除型断言就会恒真")

    def test_the_docstring_stripper_is_not_hiding_a_real_regression(self):
        """反空插：把"真把凭证拼进 URL"的形态喂给同一个抽取器，必须命中。"""
        sample = (
            'async def _build_ws_url(request):\n'
            '    """原先这里挂过 ?token=，那是历史说明，不是当前行为。"""\n'
            '    return f"ws://h/ws?token={tok}"\n'
        )
        body = self._functionCodeText(ast.parse(sample), "_build_ws_url")
        assert "token=" in body, "剥完 docstring 把真回归也一起剥掉了——判据失明"
