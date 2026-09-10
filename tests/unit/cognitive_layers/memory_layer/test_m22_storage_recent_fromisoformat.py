"""M-22 回归测试：get_recent_memories 时间过滤口径。

根因：storage.py get_recent_memories 仍用裸 ISO 字符串比较时间
（同文件 query() Bug 19 已修为 fromisoformat + 失败回退字符串比较）。
不同时区表示（+08:00 vs +00:00）的相同时刻字符串序 != 时间序。

用例：now 固定为 2026-09-11T15:00:00Z，days=1 → cutoff=2026-09-10T15:00Z。
记录 created_at="2026-09-10T20:00:00+08:00"（实为 12:00 UTC，早于 cutoff）
—— 字符串比较误判为晚于 cutoff（"20">"15"），fromisoformat 正确排除。

修复后契约：与 query() 相同的 fromisoformat 口径；过滤在锁内完成
（MemoryRecord 属性为共享可变对象，对齐 query() 的锁内过滤先例）。
"""

from datetime import datetime

import pytest

from neurova.cognitive_layers.memory_layer import storage as storage_mod
from neurova.cognitive_layers.memory_layer.storage import MemoryStorage


class _FixedNowDatetime(datetime):
    """固定 now() 的 datetime 子类（storage.py 以 `datetime.datetime.now` 取时）。"""

    @classmethod
    def now(cls, tz=None):
        base = cls(2026, 9, 11, 15, 0, 0)
        return base if tz is None else base.replace(tzinfo=tz)


@pytest.fixture()
def store(tmp_path):
    return MemoryStorage(storage_dir=str(tmp_path / "m22store"))


def test_recent_memories_uses_fromisoformat_not_string_compare(
    store, monkeypatch
):
    monkeypatch.setattr(storage_mod.datetime, "datetime", _FixedNowDatetime)

    store.batch_save(
        [
            # 20:00+08:00 == 12:00 UTC，早于 cutoff 15:00Z → 应排除
            {"content": "tz-shifted-old", "created_at": "2026-09-10T20:00:00+08:00"},
            # 16:00 UTC 晚于 cutoff → 应保留
            {"content": "utc-inside", "created_at": "2026-09-10T16:00:00+00:00"},
            # 明确早于 cutoff → 应排除
            {"content": "utc-old", "created_at": "2026-09-09T00:00:00+00:00"},
        ]
    )

    result = store.get_recent_memories(days=1, limit=10)
    contents = [r["content"] for r in result]
    assert "tz-shifted-old" not in contents, (
        "裸字符串比较把 +08:00 表示的更早时间误判为更新（M-22 未修复）"
    )
    assert contents == ["utc-inside"]
