# -*- coding: utf-8 -*-
"""配对码 WS 通道必须拒过期，并在首次接入后一次性消费。"""

from neurova.api.endpoints import mobile_pairing as pairing


def setup_function():
    pairing._pairing_codes.clear()


def test_confirmed_code_is_rejected_after_expiry(monkeypatch):
    monkeypatch.setattr(pairing.time, "time", lambda: 1_800_000_100.0)
    pairing._pairing_codes["123456"] = {
        "status": "confirmed",
        "user_id": "u1",
        "pairing_id": "pair-1",
        "expires_at": 1_800_000_000.0,
    }

    assert pairing._consumePairingCode("123456") is None
    assert pairing._pairing_codes["123456"]["status"] == "expired"


def test_confirmed_code_can_only_open_one_connection(monkeypatch):
    monkeypatch.setattr(pairing.time, "time", lambda: 1_800_000_000.0)
    pairing._pairing_codes["123456"] = {
        "status": "confirmed",
        "user_id": "u1",
        "pairing_id": "pair-1",
        "expires_at": 1_800_000_300.0,
    }

    first = pairing._consumePairingCode("123456")
    second = pairing._consumePairingCode("123456")

    assert first == {"user_id": "u1", "pairing_id": "pair-1"}
    assert second is None
    assert pairing._pairing_codes["123456"]["status"] == "used"
