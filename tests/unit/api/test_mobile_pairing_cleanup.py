# -*- coding: utf-8 -*-
"""P2-8 防回归：mobile_pairing 三只全局 dict 不得只增不清。

原缺陷（docs/资源型Bug扫描报告_2026-09-11.md P2 第5条）：
- ``_pairing_codes``：过期只改 status 从不 pop（每次生成配对码永久+1）；
- ``_confirm_attempts``：IP 时间线整条滑窗后键残留（每新 IP 永久+1）；
- ``_paired_devices``：无 unpair 的失效设备条目永驻（附随 _user_devices 空集键）。

修复方向：过期码在创建新码时顺带 pop；限流清扫整条过期的 IP 键；
设备列表检查过期时移除「离线且超过 WS Token 有效期（24h）」的失效条目；
unpair 后空用户键一并删除。响应契约不变。

隔离纪律：全部走模块内全局状态的构造/清理，无真实 WS、无真实 JWT。
"""

import asyncio
import time
from types import SimpleNamespace

import pytest

from neurova.api.endpoints import mobile_pairing as mp


@pytest.fixture(autouse=True)
def _clean_state():
    stores = (mp._pairing_codes, mp._paired_devices, mp._user_devices, mp._confirm_attempts)
    for s in stores:
        s.clear()
    yield
    for s in stores:
        s.clear()


def _request() -> SimpleNamespace:
    return SimpleNamespace(
        state=SimpleNamespace(request_id="t"),
        client=SimpleNamespace(host="203.0.113.9"),
        headers={"host": "localhost:9527"},
        url=SimpleNamespace(scheme="http"),
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
    """confirmed 且过期的码条目同样回收（设备信息已在 _paired_devices，条目冗余）。"""
    mp._pairing_codes["111111"] = {
        "code": "111111", "pairing_id": "pair-c", "user_id": "u1",
        "status": "confirmed", "created_at": time.time() - 400,
        "expires_at": time.time() - 100,
    }
    mp._paired_devices["pair-c"] = {"pairing_id": "pair-c", "user_id": "u1"}

    asyncio.run(
        mp.generate_pairing(
            request=_request(),
            body=mp.GeneratePairingRequest(device_type="mobile"),
            user_id="u1",
        )
    )

    assert "111111" not in mp._pairing_codes
    assert "pair-c" in mp._paired_devices, "设备条目不得随码回收"


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


def test_list_paired_devices_removes_stale_offline_devices():
    """离线且超过 WS Token 有效期的设备被回收；在线/新鲜设备保留。"""
    now = time.time()

    def _dev(pid, user, paired_at, online):
        return {
            "pairing_id": pid, "user_id": user, "device_name": pid,
            "device_type": "mobile", "paired_at": paired_at,
            "last_active": None, "is_online": online,
        }

    mp._paired_devices["p-stale"] = _dev("p-stale", "u1", now - mp._WS_TOKEN_TTL_SECONDS - 10, False)
    mp._paired_devices["p-fresh"] = _dev("p-fresh", "u1", now - 60, False)
    mp._paired_devices["p-online"] = _dev("p-online", "u1", now - mp._WS_TOKEN_TTL_SECONDS - 10, True)
    mp._user_devices["u1"] = {"p-stale", "p-fresh", "p-online"}

    resp = asyncio.run(mp.list_paired_devices(user_id="u1"))

    ids = {d["pairing_id"] for d in resp["data"]["devices"]}
    assert ids == {"p-fresh", "p-online"}, f"设备列表契约被破坏: {ids}"
    assert "p-stale" not in mp._paired_devices, "失效设备条目未被回收（P2-8）"
    assert "p-online" in mp._paired_devices, "在线设备不得被回收"
    assert "p-fresh" in mp._paired_devices, "有效期内设备不得被回收"
    assert mp._user_devices["u1"] == {"p-fresh", "p-online"}


def test_revoke_pairing_removes_empty_user_key():
    """unpair 后空设备集连用户键一起删（原实现残留空集键）。"""
    mp._paired_devices["p1"] = {
        "pairing_id": "p1", "user_id": "u9", "device_name": "d",
        "device_type": "mobile", "paired_at": time.time(), "is_online": False,
    }
    mp._user_devices["u9"] = {"p1"}

    resp = asyncio.run(mp.revoke_pairing(pairing_id="p1", user_id="u9"))

    assert resp["code"] == 0
    assert "p1" not in mp._paired_devices
    assert "u9" not in mp._user_devices, "空设备集的用户键残留（P2-8）"


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
