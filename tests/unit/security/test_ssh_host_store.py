"""SSH 主机密钥确认库（U1：弃 AutoAddPolicy 后的信任锚）

验收：
- 按 (agent_id, host, port) 落盘 data/<agent_id>/ssh_known_hosts.json
- lookup / mark_confirmed / is_mismatch 三原语
- 记录字段：host、port、key_fingerprint(sha256)、first_seen、confirmed_via
- 多 agent / 多端口互不串；复确认更新指纹；坏文件不炸（按空库处理）
"""

import json

import pytest

from neurova.security.ssh_host_store import SshHostStore, get_ssh_host_store

FP_A = "SHA256:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
FP_B = "SHA256:BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"


@pytest.fixture
def store(tmp_path):
    return SshHostStore(root_dir=tmp_path / "agents")


class TestSshHostStore:
    def test_lookup_missing_returns_none(self, store):
        assert store.lookup("agent-1", "h1", 22) is None

    def test_mark_then_lookup_roundtrip(self, store):
        assert store.mark_confirmed("agent-1", "h1", 22, FP_A, confirmed_via="user_card")
        entry = store.lookup("agent-1", "h1", 22)
        assert entry["host"] == "h1"
        assert entry["port"] == 22
        assert entry["key_fingerprint"] == FP_A
        assert entry["confirmed_via"] == "user_card"
        assert entry["first_seen"], "首见时间必须记录"

    def test_file_lands_under_agent_bucket(self, store, tmp_path):
        store.mark_confirmed("agent-1", "h1", 22, FP_A)
        path = tmp_path / "agents" / "agent-1" / "ssh_known_hosts.json"
        assert path.exists(), "确认记录必须落 data/<agent_id>/ssh_known_hosts.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert any(e["host"] == "h1" and e["port"] == 22 for e in data["hosts"].values())

    def test_is_mismatch(self, store):
        store.mark_confirmed("agent-1", "h1", 22, FP_A)
        assert store.is_mismatch("agent-1", "h1", 22, FP_A) is False
        assert store.is_mismatch("agent-1", "h1", 22, FP_B) is True

    def test_is_mismatch_unknown_host_is_not_mismatch(self, store):
        assert store.is_mismatch("agent-1", "nope", 22, FP_A) is False

    def test_port_isolates_entries(self, store):
        store.mark_confirmed("agent-1", "h1", 22, FP_A)
        assert store.lookup("agent-1", "h1", 2222) is None

    def test_agent_buckets_isolated(self, store):
        store.mark_confirmed("agent-1", "h1", 22, FP_A)
        assert store.lookup("agent-2", "h1", 22) is None
        store.mark_confirmed("agent-2", "h1", 22, FP_B)
        assert store.lookup("agent-1", "h1", 22)["key_fingerprint"] == FP_A
        assert store.lookup("agent-2", "h1", 22)["key_fingerprint"] == FP_B

    def test_reconfirm_updates_fingerprint(self, store):
        store.mark_confirmed("agent-1", "h1", 22, FP_A)
        store.mark_confirmed("agent-1", "h1", 22, FP_B, confirmed_via="user_card")
        assert store.lookup("agent-1", "h1", 22)["key_fingerprint"] == FP_B

    def test_empty_agent_id_falls_back_to_default_bucket(self, store, tmp_path):
        store.mark_confirmed("", "h1", 22, FP_A)
        assert (tmp_path / "agents" / "default" / "ssh_known_hosts.json").exists()
        assert store.lookup("", "h1", 22)["key_fingerprint"] == FP_A

    def test_corrupt_file_treated_as_empty(self, store, tmp_path):
        bucket = tmp_path / "agents" / "agent-1"
        bucket.mkdir(parents=True)
        (bucket / "ssh_known_hosts.json").write_text("{broken", encoding="utf-8")
        assert store.lookup("agent-1", "h1", 22) is None
        # 坏文件之后照常可写
        store.mark_confirmed("agent-1", "h1", 22, FP_A)
        assert store.lookup("agent-1", "h1", 22)["key_fingerprint"] == FP_A

    def test_rejects_empty_host_and_fingerprint(self, store):
        assert store.mark_confirmed("agent-1", "  ", 22, FP_A) is False
        assert store.mark_confirmed("agent-1", "h1", 22, "") is False

    def test_singleton_is_stable(self):
        assert get_ssh_host_store() is get_ssh_host_store()
