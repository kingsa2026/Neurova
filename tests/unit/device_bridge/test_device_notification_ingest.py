# -*- coding: utf-8 -*-
"""A5 通知事件入库判据（device:event 推送路径的落地 store）。"""
import json

import pytest


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
    from neurova.device_bridge import notification_ingest

    notification_ingest.resetForTests()
    yield
    notification_ingest.resetForTests()


class TestNotificationIngest:
    def test_record_writes_jsonl_with_provenance(self, tmp_path):
        from neurova.device_bridge import notification_ingest

        n = notification_ingest.recordDeviceEvents(
            "pair-a", "u-1",
            [{"package": "com.example", "title": "t", "text": "b", "posted_at": 1}])
        assert n == 1
        path = tmp_path / "data" / "device_notifications" / "pair-a.jsonl"
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
        assert rows[0]["pairing_id"] == "pair-a"
        assert rows[0]["user_id"] == "u-1"
        assert rows[0]["item"]["package"] == "com.example"

    def test_read_returns_latest_tail(self, tmp_path):
        from neurova.device_bridge import notification_ingest

        for i in range(5):
            notification_ingest.recordDeviceEvents(
                "pair-a", "u-1", [{"package": "p", "title": f"t{i}", "text": "", "posted_at": i}])
        events = notification_ingest.readDeviceEvents("pair-a", limit=3)
        assert [e["item"]["title"] for e in events] == ["t2", "t3", "t4"]

    def test_record_rejects_bad_items(self):
        from neurova.device_bridge import notification_ingest

        assert notification_ingest.recordDeviceEvents("pair-a", "u-1", "not-a-list") == 0
        assert notification_ingest.recordDeviceEvents("pair-a", "u-1", [{"nope": 1}]) == 0

    def test_devices_are_isolated(self, tmp_path):
        from neurova.device_bridge import notification_ingest

        notification_ingest.recordDeviceEvents("pair-a", "u-1", [{"package": "p", "title": "a", "text": "", "posted_at": 1}])
        notification_ingest.recordDeviceEvents("pair-b", "u-1", [{"package": "p", "title": "b", "text": "", "posted_at": 2}])
        assert [e["item"]["title"] for e in notification_ingest.readDeviceEvents("pair-a", limit=10)] == ["a"]
        assert [e["item"]["title"] for e in notification_ingest.readDeviceEvents("pair-b", limit=10)] == ["b"]
