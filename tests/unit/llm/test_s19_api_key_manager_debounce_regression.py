"""S-19 回归测试：validate_key 的 touch 落盘防抖。

红绿：无修复时 validate_key 每次成功都 api_key.touch() + self._save_keys()
全量 JSON 重写 data/api_keys.json → 高 QPS IO 放大。断言：
1. validate_key 只改内存态 + 脏标记，不立即落盘；
2. 防抖间隔到期后由定时器落盘（last_used_at 持久化）；
3. 创建/删除/撤销等关键变更仍立即落盘；
4. flush()/退出钩子立即持久化脏状态。
"""

import json
import time

import pytest

from neurova.api.api_key_manager import APIKeyManager


def _read(path):
    return path.read_text(encoding="utf-8")


@pytest.fixture
def mgr(tmp_path, monkeypatch):
    """默认被测管理器：防抖窗口拉长到 3600s，验证"不立即落盘"。"""
    monkeypatch.setattr(APIKeyManager, "SAVE_DEBOUNCE_SECONDS", 3600.0)
    m = APIKeyManager(storage_path=tmp_path / "api_keys.json")
    yield m
    if m._save_timer is not None:
        m._save_timer.cancel()


class TestS19DebouncedSave:
    def test_validate_key_does_not_rewrite_immediately(self, mgr, tmp_path):
        raw, key = mgr.generate_key("agent1", "user1", "n", ["read"])
        path = tmp_path / "api_keys.json"
        before = _read(path)

        assert mgr.validate_key(raw) is not None
        assert _read(path) == before, "S-19: validate_key 不得每次全量重写 JSON"
        # 内存态已更新（行为不回退）
        assert mgr.get_key_by_id(key.key_id).last_used_at is not None

    def test_flush_persists_last_used(self, mgr, tmp_path):
        raw, key = mgr.generate_key("agent1", "user1", "n", ["read"])
        path = tmp_path / "api_keys.json"
        before = _read(path)

        mgr.validate_key(raw)
        mgr.flush()

        entry = [k for k in json.loads(_read(path))["keys"] if k["key_id"] == key.key_id][0]
        assert entry["last_used_at"] is not None
        assert _read(path) != before

    def test_debounced_timer_writes_after_interval(self, tmp_path, monkeypatch):
        monkeypatch.setattr(APIKeyManager, "SAVE_DEBOUNCE_SECONDS", 0.05)
        m = APIKeyManager(storage_path=tmp_path / "k.json")
        try:
            raw, key = m.generate_key("a", "u", "n", ["read"])
            path = tmp_path / "k.json"
            before = _read(path)

            m.validate_key(raw)
            assert _read(path) == before, "防抖窗口内不应落盘"

            time.sleep(0.3)  # 等防抖定时器触发
            entry = [k for k in json.loads(_read(path))["keys"] if k["key_id"] == key.key_id][0]
            assert entry["last_used_at"] is not None, "防抖到期后 last_used_at 必须持久化"
            assert _read(path) != before
        finally:
            if m._save_timer is not None:
                m._save_timer.cancel()

    def test_critical_changes_save_immediately(self, mgr, tmp_path):
        """撤销/删除等关键变更绕过防抖，立即落盘。"""
        raw, key = mgr.generate_key("agent1", "user1", "n", ["read"])
        path = tmp_path / "api_keys.json"

        assert mgr.revoke_key(key.key_id) is True
        entry = [k for k in json.loads(_read(path))["keys"] if k["key_id"] == key.key_id][0]
        assert entry["is_active"] is False, "关键变更必须立即落盘"

        assert mgr.delete_key(key.key_id) is True
        remaining = [k for k in json.loads(_read(path))["keys"] if k["key_id"] == key.key_id]
        assert remaining == []

    def test_exit_flush_hook_persists_dirty_state(self, mgr, tmp_path):
        raw, key = mgr.generate_key("agent1", "user1", "n", ["read"])
        path = tmp_path / "api_keys.json"

        mgr.validate_key(raw)
        mgr._flush_on_exit()

        entry = [k for k in json.loads(_read(path))["keys"] if k["key_id"] == key.key_id][0]
        assert entry["last_used_at"] is not None, "退出钩子必须把内存态 flush 到存储"
