# -*- coding: utf-8 -*-
"""QwenPaw 对照批 C5：keyring 条目按数据根派生 + 旧条目灰度迁移。

- 派生：同机多部署（不同数据根）的 keyring 条目互不覆盖；
- 迁移：旧固定条目 `config-secret-key` 仍可读，命中后回填新条目——
  存量部署已封存凭据不受影响（双读期安全）；
- 链序不变：env NEUROVA_SECRET_KEY 仍最优先（容器/CI 部署的覆盖通道）。
"""

import sys
from pathlib import Path

import pytest

from neurova.security import secret_store

SERVICE = "Neurova"
LEGACY_ENTRY = "config-secret-key"


class FakeKeyring:
    def __init__(self, store=None):
        self.store = dict(store or {})
        self.set_calls = []

    def get_password(self, service, entry):
        return self.store.get((service, entry))

    def set_password(self, service, entry, value):
        self.set_calls.append((service, entry, value))
        self.store[(service, entry)] = value


@pytest.fixture
def no_env_key(monkeypatch):
    monkeypatch.delenv("NEUROVA_SECRET_KEY", raising=False)


def derivedEntryFor(monkeypatch, tmp_path, name):
    root = tmp_path / name
    monkeypatch.setattr(secret_store, "_KEY_FILE", str(root / ".secret_key"))
    return secret_store._keyringEntry()


class TestKeyringAccountDerivation:
    def test_entry_derived_from_data_root(self, monkeypatch, tmp_path):
        entry_a = derivedEntryFor(monkeypatch, tmp_path, "deploy_a")
        entry_b = derivedEntryFor(monkeypatch, tmp_path, "deploy_b")
        assert entry_a != entry_b, "不同数据根必须派生不同 keyring 条目"
        assert entry_a.startswith(LEGACY_ENTRY + "-"), entry_a
        digest = entry_a[len(LEGACY_ENTRY) + 1:]
        assert len(digest) == 12 and all(c in "0123456789abcdef" for c in digest), digest

    def test_legacy_entry_migrates_to_derived(self, monkeypatch, tmp_path, no_env_key):
        entry = derivedEntryFor(monkeypatch, tmp_path, "legacy_deploy")
        fake = FakeKeyring({(SERVICE, LEGACY_ENTRY): "old-key"})
        monkeypatch.setitem(sys.modules, "keyring", fake)

        key = secret_store._load_or_create_key()

        assert key == b"old-key", "旧条目命中必须继续可用（灰度迁移不弃钥）"
        assert (SERVICE, entry, "old-key") in fake.set_calls, (
            f"旧条目值应回填到派生条目：{fake.set_calls}"
        )

    def test_derived_entry_hit_skips_migration(self, monkeypatch, tmp_path, no_env_key):
        entry = derivedEntryFor(monkeypatch, tmp_path, "fresh_deploy")
        fake = FakeKeyring({(SERVICE, entry): "new-key"})
        monkeypatch.setitem(sys.modules, "keyring", fake)

        key = secret_store._load_or_create_key()

        assert key == b"new-key"
        assert fake.set_calls == [], "派生条目命中时不应再触旧条目"

    def test_env_key_still_wins_over_keyring(self, monkeypatch, tmp_path):
        """链序钉住：env 最优先（容器/CI 覆盖通道不被 keyring 顶掉）。"""
        derivedEntryFor(monkeypatch, tmp_path, "env_deploy")
        fake = FakeKeyring({(SERVICE, LEGACY_ENTRY): "ring-key"})
        monkeypatch.setitem(sys.modules, "keyring", fake)
        monkeypatch.setenv("NEUROVA_SECRET_KEY", "env-key")

        key = secret_store._load_or_create_key()

        assert key == b"env-key"
        assert fake.set_calls == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
