"""M-16 回归测试：models.py from_dict 丢字段回填。

根因：
- Memory.from_dict 只回填 created_at/updated_at，丢 `embedding` 与
  `last_accessed_at`（round-trip 后嵌入向量与最后访问时间静默丢失）；
- UserProfile/Skill/SelfModel.from_dict 不读 created_at/updated_at，
  每次加载被重置为 now。

修复后契约：有值才覆盖（解析成功才回填），缺省/非法走原 dataclass default。
"""

from datetime import datetime, timezone

from neurova.cognitive_layers.memory_layer.models import (
    Memory,
    SelfModel,
    Skill,
    UserProfile,
)


class TestM16MemoryFromDict:
    def test_embedding_and_last_accessed_at_roundtrip(self):
        # 数据源采用 MemoryRecord.to_dict() 的兼容格式（该格式含 embedding，
        # sleep.py:96 明确声明"兼容 Memory.from_dict() 格式"）；Memory.to_dict
        # 面向 API/前端, 按既有契约不携带 embedding, 不在本缺陷范围。
        data = {
            "id": "m1",
            "content": "hello",
            "embedding": [0.1, 0.25, -0.3],
            "last_accessed_at": "2026-01-02T03:04:05+00:00",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
        restored = Memory.from_dict(data)
        assert restored.embedding == [0.1, 0.25, -0.3], "from_dict 丢失 embedding"
        assert restored.last_accessed_at == datetime(
            2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc
        ), "from_dict 丢失 last_accessed_at"

    def test_missing_fields_fall_back_to_defaults(self):
        mem = Memory.from_dict({"id": "m2", "content": "c"})
        assert mem.embedding is None
        assert mem.last_accessed_at is None

    def test_last_accessed_at_none_value_stays_none(self):
        mem = Memory.from_dict({"id": "m3", "last_accessed_at": None})
        assert mem.last_accessed_at is None


class TestM16ProfileSkillSelfModelDates:
    def test_user_profile_dates_not_reset(self):
        up = UserProfile(user_id="u1")
        up.created_at = datetime(2026, 2, 1, tzinfo=timezone.utc)
        up.updated_at = datetime(2026, 2, 2, tzinfo=timezone.utc)
        restored = UserProfile.from_dict(up.to_dict())
        assert restored.created_at == datetime(2026, 2, 1, tzinfo=timezone.utc), (
            "UserProfile.from_dict 将 created_at 重置为 now"
        )
        assert restored.updated_at == datetime(2026, 2, 2, tzinfo=timezone.utc), (
            "UserProfile.from_dict 将 updated_at 重置为 now"
        )

    def test_skill_created_at_not_reset(self):
        sk = Skill(skill_id="s1")
        sk.created_at = datetime(2026, 3, 1, tzinfo=timezone.utc)
        restored = Skill.from_dict(sk.to_dict())
        assert restored.created_at == datetime(2026, 3, 1, tzinfo=timezone.utc), (
            "Skill.from_dict 将 created_at 重置为 now"
        )

    def test_self_model_updated_at_not_reset(self):
        sm = SelfModel(agent_id="a1")
        sm.updated_at = datetime(2026, 4, 1, tzinfo=timezone.utc)
        restored = SelfModel.from_dict(sm.to_dict())
        assert restored.updated_at == datetime(2026, 4, 1, tzinfo=timezone.utc), (
            "SelfModel.from_dict 将 updated_at 重置为 now"
        )

    def test_missing_dates_use_defaults(self):
        up = UserProfile.from_dict({"user_id": "u2"})
        assert isinstance(up.created_at, datetime)
        sk = Skill.from_dict({"skill_id": "s2"})
        assert isinstance(sk.created_at, datetime)
        sm = SelfModel.from_dict({"agent_id": "a2"})
        assert isinstance(sm.updated_at, datetime)

    def test_invalid_date_string_falls_back_to_default(self):
        up = UserProfile.from_dict({"user_id": "u3", "created_at": "not-a-date"})
        assert isinstance(up.created_at, datetime)
