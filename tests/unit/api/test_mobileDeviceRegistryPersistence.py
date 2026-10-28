"""在册设备必须是**有状态的权威**，不是进程记忆里的一份草稿（设计方案 §4.8／§4.9／§10.2）。

三条实测现状（2026-10-24 复核，全部可在代码里逐字核出）：

1. `mobile_websocket` 的 token 认证分支只验 HMAC 签名与 24h 时效
   （[neurova/api/endpoints/mobile_pairing.py:814-821]），**不查这台设备是否还在册**。
   `revoke_pairing` 会关掉当下那条连接（`:782-788`），但拦不住设备随后重连——
   旧凭证在剩余窗口内照样连得上，连上后还照常把 `is_online` 写回 True（`:837-839`）。
   即「解除配对」在面板上看起来生效，实际只挡得住已经被断开的那一次。
2. `_paired_devices` 是模块级 dict（`:104`），进程重启即清空：升级/重启一次，
   用户配好的设备全部失联，而面板只会显示「还没有已配对的设备」——失联原因看不见。
3. `list_paired_devices` 里那条「离线且配对超 24h 就删」的回收（`:726-740`）
   会**静默删除**用户自己配的设备（AGENTS §2「只写不读」同族：删了也没人反馈）。

判据写成「写侧产出 → 读侧消费」的跨边界闭环，不自造枚举值：
设备一律经真 `generate → confirm` 端点产出，凭证用真 `confirm` 回的那条 token。

跑法：`.venv/Scripts/python.exe -m pytest -q tests/unit/api/test_mobileDeviceRegistryPersistence.py -p no:cacheprovider`
"""
import os
import time
from urllib.parse import urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_registry_0123456789")

from neurova.api.endpoints import mobile_pairing as MP  # noqa: E402
from tests.ast_scan import parseSource

PREFIX = "/api/v1/mobile"
OWNER = "kai"


def _mount() -> FastAPI:
    app = FastAPI()
    app.include_router(MP.router, prefix=PREFIX)
    app.dependency_overrides[MP._get_current_user_id] = lambda: OWNER
    return app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """数据根落到 tmp：判据要能真开库，又不许写进仓内 `data/`。"""
    monkeypatch.setenv("NEUROVA_WS_SECRET", "registry_test_secret")
    storePath = str(tmp_path / "mobile_devices.db")
    monkeypatch.setattr(MP, "deviceStorePath", lambda: storePath, raising=True)

    _resetVolatileState()
    app = _mount()
    with TestClient(app, base_url="http://testserver", raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()
    _resetVolatileState()


def _resetVolatileState() -> None:
    """回到"进程刚起来"的样子：配对码内存表清空，在册单例释放（进程重启语义）。

    `resetDeviceRegistry()` 必须在这里——不释放单例的话，第二条用例会继续读
    上一条留下的库，"重启后仍在"就被读成了"根本没重启"。
    """
    MP._pairing_codes.clear()
    MP._confirm_attempts.clear()
    MP._ws_connections.clear()
    MP.resetDeviceRegistry()


def _pairADevice(client, deviceName="HUAWEI-ABC001"):
    """走真端点产出一台在册设备，返回 (pairingId, 接入凭证, 回连地址)。"""
    gen = client.post(f"{PREFIX}/pairing/generate",
                      json={"device_name": deviceName, "device_type": "mobile"})
    assert gen.status_code == 200, f"发码失败：{gen.status_code} {gen.text[:160]}"
    code = gen.json()["code"]
    conf = client.post(f"{PREFIX}/pairing/confirm",
                       json={"code": code, "device_name": deviceName, "device_id": "dev-1"})
    assert conf.status_code == 200, f"确认失败：{conf.status_code} {conf.text[:160]}"
    body = conf.json()
    return body["pairing_id"], body["connect_ticket"], body["ws_url"], body["device_secret"]


def _connectOutcome(client, wsUrl, ticket=""):
    """照端点回出去的那条地址真连一次，返回 'accepted' 或拒绝描述。

    凭证走 header（S1b 起 URL 不带凭据，§4.2）——这一格审的正是"重连还能不能过"。
    """
    path = urlsplit(wsUrl).path
    query = urlsplit(wsUrl).query
    target = f"{path}?{query}" if query else path
    try:
        with client.websocket_connect(target,
                                      headers={"Authorization": f"Bearer {ticket}"} if ticket else {}):
            return "accepted"
    except Exception as e:  # noqa: BLE001 - 判据要的就是"连不上"这个事实
        return f"{type(e).__name__} code={getattr(e, 'code', None)}"


class TestRevocationStopsReconnect:
    def test_revoked_device_cannot_reconnect_with_its_old_token(self, client):
        """解除之后**再连**必须被拒。今天这条红：token 分支不查在册，重连照样通。"""
        pairingId, ticket, wsUrl, deviceSecret = _pairADevice(client)

        assert _connectOutcome(client, wsUrl, ticket) == "accepted", (
            "正向前提不成立：配对完就连不上，那下面那条『被拒』是恒真的空守卫")

        rev = client.delete(f"{PREFIX}/pairing/{pairingId}")
        assert rev.status_code == 200, f"解除失败：{rev.status_code} {rev.text[:160]}"

        # 换一张**新**票再连：否则"被拒"可能只是因为上一张已经消费过（一次性），
        # 而不是因为撤销生效——两件事必须分钉，不然这条判据咬不到它想咬的那个根因。
        fresh = client.post(f"{PREFIX}/pairing/refresh",
                            json={"pairing_id": pairingId, "device_secret": deviceSecret,
                                  "challenge": "after-revoke"})
        assert fresh.status_code in (401, 403, 410), (
            f"已解除的设备竟然还能续签（{fresh.status_code}）——撤销没落在放行面上")
        outcome = _connectOutcome(client, wsUrl, ticket)
        assert outcome != "accepted", (
            "设备已解除配对，旧凭证却还能重连成功——『解除』只是断掉当下那一次，"
            "凭证在剩余有效期内仍是有效身份（§4.8 第 1、2 条）")

    def test_revoke_is_observed_by_the_connection_gate_not_just_the_endpoint(self, client):
        """判据落点必须在**放行处**：光在 revoke 里写标记、连接侧不读，就是只写不读。

        钉的是**调用形态**（`getDeviceRegistry().isAdmissible(...)` 出现在 WS 函数体内），
        不钉某个状态词——状态词随实现改名，钉词会自己把自己钉红（本卷形态 410）。
        """
        import inspect

        source = inspect.getsource(MP.mobile_websocket)
        assert "getDeviceRegistry()" in source and "isAdmissible" in source, (
            "WS 放行路径不读在册注册表——撤销写的标记没有任何读者（AGENTS §2 只写不读）")

    def test_the_gate_probe_names_a_handler_that_does_not_read_the_registry(self):
        """反空转：真造一个不读注册表的放行函数，探测器必须点名它，否则上一条恒真。"""
        import ast
        import textwrap

        sample = textwrap.dedent('''
            async def openWebsocket(websocket):
                token = websocket.query_params.get("token")
                if not _verify_ws_token(token):
                    await websocket.close(code=4001)
                    return
                await websocket.accept()
        ''')
        body = parseSource(sample).body[0]
        readsRegistry = any(
            isinstance(node, ast.Attribute) and node.attr == "isAdmissible"
            for node in ast.walk(body))
        assert not readsRegistry, (
            "探测器在一处明摆着不读注册表的放行代码上说它读了——判据不判事")


class TestRegistrySurvivesProcessRestart:
    def test_paired_devices_survive_a_process_restart(self, client):
        """重启语义：内存 dict 清空后，在册设备必须能从库里读回来。"""
        pairingId, _ticket, _wsUrl, _secret = _pairADevice(client, "restart-me")

        listing = client.get(f"{PREFIX}/pairing/list")
        assert listing.status_code == 200
        assert any(d["pairing_id"] == pairingId for d in listing.json()["data"]["devices"]), (
            "正向前提不成立：刚配好的设备连 list 都不出，后面那条『重启后仍在』无从谈起")

        # 进程重启的确切形状：模块级内存态全没，只剩落盘的那份
        _resetVolatileState()

        after = client.get(f"{PREFIX}/pairing/list")
        devices = after.json()["data"]["devices"]
        assert any(d["pairing_id"] == pairingId for d in devices), (
            f"重启后在册设备全部失联（今天 `_paired_devices` 是模块 dict，`:104`）：{devices!r}")

    def test_restarted_registry_still_refuses_revoked_devices(self, client):
        """撤销标记也必须活过重启：否则重启＝把已解除的设备重新放行。"""
        pairingId, ticket, wsUrl, _secret = _pairADevice(client, "revoked-then-restart")
        assert client.delete(f"{PREFIX}/pairing/{pairingId}").status_code == 200

        _resetVolatileState()

        assert _connectOutcome(client, wsUrl, ticket) != "accepted", (
            "重启后已解除设备的旧凭证又有效了——撤销状态没有持久化")


class TestDormantDevicesAreNotedNotDeleted:
    def test_long_idle_device_stays_listed_with_last_active(self, client):
        """§4.9 已裁：长期在册，30 天无活动只提醒不代删。今天这条红：24h 就被静默删除。"""
        pairingId, _ticket, _wsUrl, _secret = _pairADevice(client, "weekend-phone")

        # 把这台设备的配对时刻推到 35 天前——用的是**产品语义的天数**，
        # 不写进实现细节常量：任何合理的"多久算久"都该保留它，只该提醒。
        self._ageTheDevice(pairingId, days=35)

        listing = client.get(f"{PREFIX}/pairing/list")
        devices = listing.json()["data"]["devices"]
        row = next((d for d in devices if d["pairing_id"] == pairingId), None)
        assert row is not None, (
            f"离线 35 天的设备被系统代删了（原 24h 静默回收的形态）：{devices!r}")
        assert row.get("last_active"), f"回不到「最近连接时间」这一列：{row!r}"
        assert row.get("dormant") is True, (
            f"超 30 天无活动却没给出提醒位，面板无从显示『是否解除』：{row!r}")

    def test_recent_device_is_listed_but_not_flagged_dormant(self, client):
        """反向格：刚配好的设备不得被标成休眠——否则提醒位恒真，等于没有提醒。"""
        pairingId, _ticket, _wsUrl, _secret = _pairADevice(client, "fresh-phone")
        listing = client.get(f"{PREFIX}/pairing/list")
        row = next(d for d in listing.json()["data"]["devices"]
                   if d["pairing_id"] == pairingId)
        assert row.get("dormant") is False, f"新配设备就被标休眠：{row!r}"

    @staticmethod
    def _ageTheDevice(pairingId: str, days: int) -> None:
        """把在册设备的最近活动时间推旧——走生产用的同一个写口，不开测试后门。"""
        MP.getDeviceRegistry().recordActivity(pairingId, at=time.time() - days * 86400)
