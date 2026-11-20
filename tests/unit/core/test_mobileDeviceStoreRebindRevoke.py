# -*- coding: utf-8 -*-
"""项 6（Linger 对照）换绑即吊销：同设备重新配对时，旧绑定必须当场失效。

Linger 纪律：凭据绑定 placement，新 binding 生效 → 旧 revision 立即过期。
本仓映射：同一物理设备（user_id + device_id 相同）经新配对码再次入册时，
旧 pairing_id 的绑定行转为 revoked 并递增 token_epoch——旧凭证（connect
ticket/续签）随之全部失效；同 pairing 重复确认（幂等重确认）不得自吊销；
不同设备各自入册互不影响（多设备并存是合法形态）。
"""
import pytest

from neurova.core.mobile_device_store import MobileDeviceStore


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_MOBILE_DEVICES_DB", str(tmp_path / "mobile_devices.db"))
    from neurova.core import mobile_device_store as mds

    monkeypatch.setattr(mds, "refuseSharedRootInTests", lambda path: None)
    s = MobileDeviceStore(dbPath=tmp_path / "mobile_devices.db")
    yield s
    s.close()


class TestRebindRevokesOldBinding:
    def test_same_device_new_pairing_revokes_old(self, store):
        store.register(pairingId="pair-old", userId="u1", deviceName="手机",
                       deviceId="dev-1", deviceSecret="s-old")
        assert store.isAdmissible("pair-old") is True

        store.register(pairingId="pair-new", userId="u1", deviceName="手机",
                       deviceId="dev-1", deviceSecret="s-new")

        old = store.get("pair-old")
        assert old is not None and old["state"] == "revoked", "换绑后旧绑定必须吊销"
        assert store.isAdmissible("pair-old") is False
        # 旧密钥彻底失效（即使拿着旧 secret 来核验也不通过）
        assert store.verifyDeviceSecret("pair-old", "s-old") is False
        # 新绑定在册可用
        assert store.isAdmissible("pair-new") is True
        assert store.verifyDeviceSecret("pair-new", "s-new") is True

    def test_reconfirm_same_pairing_is_idempotent(self, store):
        store.register(pairingId="pair-a", userId="u1", deviceName="手机",
                       deviceId="dev-1", deviceSecret="s1")
        # 同 pairing 重复确认（网络重试形态）：不得把自己吊销
        store.register(pairingId="pair-a", userId="u1", deviceName="手机",
                       deviceId="dev-1", deviceSecret="s1")
        row = store.get("pair-a")
        assert row is not None and row["state"] == "paired"
        assert store.isAdmissible("pair-a") is True

    def test_different_devices_coexist(self, store):
        store.register(pairingId="pair-phone", userId="u1", deviceName="手机",
                       deviceId="dev-phone", deviceSecret="sp")
        store.register(pairingId="pair-pad", userId="u1", deviceName="平板",
                       deviceId="dev-pad", deviceSecret="sd")
        assert store.isAdmissible("pair-phone") is True
        assert store.isAdmissible("pair-pad") is True

    def test_old_epoch_bumped_so_stale_tickets_die(self, store):
        store.register(pairingId="pair-old", userId="u1", deviceName="手机",
                       deviceId="dev-1", deviceSecret="s-old")
        oldEpoch = store.epochOf("pair-old")
        store.register(pairingId="pair-new", userId="u1", deviceName="手机",
                       deviceId="dev-1", deviceSecret="s-new")
        assert store.epochOf("pair-old") == oldEpoch + 1, "换绑须递增旧绑定 epoch"
        # 带旧 epoch 的凭证不再可放行（isAdmissible 的 epoch 半边）
        assert store.isAdmissible("pair-old", oldEpoch) is False
