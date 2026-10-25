# -*- coding: utf-8 -*-
"""P2-8 防回归（内存态只增不清）＋ §4.9 改判后的在册设备判据。

原缺陷（P2 第5条）：
- ``_pairing_codes``：过期只改 status 从不 pop（每次生成配对码永久+1）；
- ``_confirm_attempts``：IP 时间线整条滑窗后键残留（每新 IP 永久+1）；
- ``_paired_devices``：无 unpair 的失效设备条目永驻（附随 _user_devices 空集键）。

**2026-10-24 改判（设计方案 §4.8／§4.9）**：后两条的载体已经退役——在册设备不再是
内存 dict，而是 `mobile_device_store` 的持久权威。于是这一档里：

- 「设备列表把离线满 24h 的条目删掉」**不再是期望行为**：那是系统代属主删掉他自己
  配的设备，且删完不吭声。现在的契约是**长期在册**，满 30 天只投一个 `dormant` 提醒位。
- 「unpair 后空用户键连键删除」这条判据的对象（`_user_devices`）不存在了，
  改判成**撤销必须落进持久标记并递增 epoch**——它守的是同一件事的另一半：
  撤销要留下可被读者消费的痕迹，而不是只把内存条目抹掉。

隔离纪律：配对码/限流走模块内全局状态；在册库按 `deviceStorePath` 单点重定向到 tmp，
**不写进仓内 `data/`**（本仓有逐用例仓库根污染守卫）。
"""

import asyncio
import time
from types import SimpleNamespace

import pytest

from neurova.api.endpoints import mobile_pairing as mp


@pytest.fixture(autouse=True)
def _clean_state(_isolateMobileDeviceRegistry):
    """每用例回到"进程刚起来"：内存表清空，在册单例释放并把库指向 tmp。"""
    # 库路径与限流桶由 `tests/unit/api/conftest.py` 单点隔离。这里原来自己
    # `setattr(mp, "deviceStorePath", ...)` 指到本档 tmp——teardown 恢复函数后，
    # 后一档拿到的解析结果退回数据根，正是那格混档红的通道。自己只清本档要的配对码表。
    mp._pairing_codes.clear()
    yield
    mp._pairing_codes.clear()


def _request() -> SimpleNamespace:
    return SimpleNamespace(
        state=SimpleNamespace(request_id="t"),
        client=SimpleNamespace(host="203.0.113.9"),
        headers={"host": "localhost:9527"},
        url=SimpleNamespace(scheme="http"),
        # §6-172 批 25：`generate_pairing` 现在向框架要自家二维码地址（`request.url_for`），
        # 这两格审的是**过期码回收**，与那条 URL 无关——这里替的是 Starlette 的请求对象，
        # 不是被审逻辑。同源判据本身在 `test_mobilePairingQrSameOrigin.py`（真 app 真路由）。
        url_for=lambda name, **params: (
            f"http://localhost:9527/api/v1/mobile/pairing/qrcode/{params.get('code', '')}"),
    )


def test_generate_pairing_prunes_expired_codes():
    """创建新码时顺带 pop 已过期码（原实现只改 status 从不删）。"""
    mp._pairing_codes["000000"] = {
        "code": "000000", "pairing_id": "pair-old", "user_id": "u1",
        "status": "pending", "created_at": time.time() - 400,
        "expires_at": time.time() - 100,
    }

    resp = asyncio.run(
        mp.generate_pairing(
            request=_request(),
            body=mp.GeneratePairingRequest(device_type="mobile"),
            user_id="u1",
        )
    )

    assert "000000" not in mp._pairing_codes, "过期配对码未被回收（P2-8）"
    assert resp.code in mp._pairing_codes, "新码必须仍在"
    assert len(mp._pairing_codes) == 1, "回收不得误伤有效码"


def test_generate_pairing_prunes_confirmed_codes_past_expiry():
    """confirmed 且过期的码条目同样回收；**在册设备不随码回收**（两套寿命，§5.0）。"""
    mp._pairing_codes["111111"] = {
        "code": "111111", "pairing_id": "pair-c", "user_id": "u1",
        "status": "confirmed", "created_at": time.time() - 400,
        "expires_at": time.time() - 100,
    }
    mp.getDeviceRegistry().register(pairingId="pair-c", userId="u1", deviceName="phone-c")

    asyncio.run(
        mp.generate_pairing(
            request=_request(),
            body=mp.GeneratePairingRequest(device_type="mobile"),
            user_id="u1",
        )
    )

    assert "111111" not in mp._pairing_codes
    assert mp.getDeviceRegistry().get("pair-c") is not None, "设备条目不得随码回收"


def test_confirm_rate_limit_sweeps_stale_ip_keys():
    """时间线整条滑出窗口的 IP 连键删除（原实现键永久残留）。"""
    old = time.time() - mp._CONFIRM_RATE_WINDOW_SECONDS - 1
    mp._confirm_attempts["1.1.1.1"] = [old, old]
    mp._confirm_attempts["2.2.2.2"] = [time.time() - 1]  # 窗口内，保留

    mp._check_confirm_rate_limit("3.3.3.3")

    assert "1.1.1.1" not in mp._confirm_attempts, "过期 IP 键未被清扫（P2-8）"
    assert "2.2.2.2" in mp._confirm_attempts, "清扫不得误伤窗口内 IP"
    assert "3.3.3.3" in mp._confirm_attempts


def test_confirm_rate_limit_sweep_keeps_block_semantics():
    """清扫后限流语义不变：窗口内第 5 次尝试仍必须 429。"""
    now = time.time()
    mp._confirm_attempts["9.9.9.9"] = [now - 1] * mp._CONFIRM_RATE_LIMIT

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as ei:
        mp._check_confirm_rate_limit("9.9.9.9")
    assert ei.value.status_code == 429


def test_long_offline_devices_are_listed_and_flagged_not_deleted():
    """§4.9 已裁改判的原 P2-8 判据：离线很久的设备**不删**，只投 `dormant` 提醒位。

    原判据写的是「离线且超过 WS Token 有效期（24h）的设备被回收」——那条契约的实质是
    **系统代属主删掉他自己配的设备**，且删完不吭声；面板只会说「还没有已配对的设备」。
    现在长期在册，满 30 天给一位提醒，处置权回到人手上。
    """
    now = time.time()
    registry = mp.getDeviceRegistry()
    for pid, days in (("p-dormant", 35), ("p-fresh", 0), ("p-online", 40)):
        registry.register(pairingId=pid, userId="u1", deviceName=pid)
        registry.recordActivity(pid, at=now - days * 86400)
    # 「在线」不靠库里的标记：叠的是当下活连接（唯一活连接源）
    mp._ws_connections["p-online"] = object()  # 只当占位，list 只看键在不在

    resp = asyncio.run(mp.list_paired_devices(user_id="u1"))

    ids = {d["pairing_id"] for d in resp["data"]["devices"]}
    assert ids == {"p-dormant", "p-fresh", "p-online"}, f"在册设备被代删了: {ids}"
    rows = {d["pairing_id"]: d for d in resp["data"]["devices"]}
    assert rows["p-dormant"]["dormant"] is True, "满 30 天无活动却没提醒位"
    assert rows["p-fresh"]["dormant"] is False, "新鲜设备被标休眠＝提醒位恒真，等于没有提醒"
    assert rows["p-online"]["is_online"] is True, "活连接没被叠进在线读数"
    assert rows["p-online"]["dormant"] is False, "有活连接的设备不该被算成休眠（在线优先）"


def test_revoke_leaves_a_durable_marker_and_bumps_the_epoch():
    """改判后的「撤销要留下可消费的痕迹」：对象从内存键残留换成**持久标记＋epoch**。

    原判据审的是 `_user_devices` 里空集键残留（载体已随 P2-8 的实现一起退役）。
    它守的那件事本身没错——撤销必须产生一个下游会读的结果——只是今天读的人变了：
    少了 epoch，`revoke` 就只是把当下那条连接关掉，设备随后重连照样放行（§4.8）。
    """
    registry = mp.getDeviceRegistry()
    registry.register(pairingId="p1", userId="u9", deviceName="d")
    before = registry.epochOf("p1")

    resp = asyncio.run(mp.revoke_pairing(pairing_id="p1", user_id="u9"))

    assert resp["code"] == 0
    assert registry.epochOf("p1") == before + 1, "撤销没递增 epoch——旧凭证仍然自洽"
    assert not registry.isAdmissible("p1", str(before)), "撤销后旧 epoch 仍被放行"
    listing = asyncio.run(mp.list_paired_devices(user_id="u9"))
    assert listing["data"]["devices"] == [], "撤销的设备还出现在在册列表里"


def test_expired_pairing_code_confirm_still_410():
    """回收不破坏 confirm 契约：过期码 confirm 仍 410（码尚在、未到生成新码时机）。"""
    mp._pairing_codes["222222"] = {
        "code": "222222", "pairing_id": "pair-x", "user_id": "u1",
        "status": "pending", "created_at": time.time() - 400,
        "expires_at": time.time() - 100,
    }

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as ei:
        asyncio.run(
            mp.confirm_pairing(
                request=_request(),
                body=mp.ConfirmPairingRequest(code="222222", device_name="phone"),
            )
        )
    assert ei.value.status_code == 410
