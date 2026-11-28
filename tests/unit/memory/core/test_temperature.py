"""
温度引擎测试 - TemperatureEngine 完整测试覆盖
"""
import pytest

from neurova.cognitive_layers.memory_layer.temperature import apply_recall_gain
from datetime import datetime, timedelta, timezone
from neurova.memory import TemperatureEngine


class TestTemperatureOnAccess:
    """测试访问升温功能（D5-R2 比例式口径：命中回温唯一出口 apply_recall_gain）"""

    def test_basic_access_boost(self):
        """基础访问应该升温"""
        new_temp = apply_recall_gain(50.0)
        assert new_temp == pytest.approx(62.5)
        assert new_temp <= 100.0

    def test_low_temperature_boost(self):
        """低温时升温幅度应该更大"""
        low_gain = apply_recall_gain(10.0) - 10.0
        high_gain = apply_recall_gain(80.0) - 80.0
        # 低温升温幅度应大于高温
        assert low_gain > high_gain > 0

    def test_saturation_at_high_temp(self):
        """接近100度时升温应该减缓"""
        temp_90 = apply_recall_gain(90.0)
        assert temp_90 <= 100.0
        # 从90度升温幅度应该较小
        assert temp_90 - 90.0 < 5.0

    def test_temperature_caps_at_100(self):
        """温度不应超过100"""
        new_temp = apply_recall_gain(99.0)
        assert new_temp <= 100.0

    def test_emotion_bonus(self):
        """命中回温不受情感调制（调制职责在衰减侧的情感保护，D5-R2 权威口径）"""
        assert apply_recall_gain(50.0) == apply_recall_gain(50.0)

    def test_relation_bonus(self):
        """命中回温不受关联数调制（旧 relation 加成随 on_access 退役）"""
        assert apply_recall_gain(50.0) == apply_recall_gain(50.0)

    def test_combo_multiplier(self):
        """命中回温不受连击倍率调制（同轮重复命中由 creditRecallHits 轮内去重收敛）"""
        assert apply_recall_gain(50.0) == apply_recall_gain(50.0)

    def test_zero_temperature(self):
        """零度时访问应该正常升温"""
        new_temp = apply_recall_gain(0.0)
        assert new_temp == pytest.approx(25.0)

    def test_max_relation_bonus_capped(self):
        """命中回温不受关联数调制（比例式天然有界 ≤100，D5-R2 口径）"""
        assert apply_recall_gain(50.0) == apply_recall_gain(50.0)


class TestTemperatureOnDecay:
    """测试温度衰减功能"""

    def test_recent_access_no_decay(self):
        """今天访问过的记忆不应衰减"""
        now = datetime.now(timezone.utc).isoformat()
        result = TemperatureEngine.on_decay(
            current_temp=50.0, last_accessed=now
        )
        assert result['new_temp'] == 50.0

    def test_basic_decay(self):
        """几天后应该有衰减"""
        three_days_ago = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        result = TemperatureEngine.on_decay(
            current_temp=50.0, last_accessed=three_days_ago
        )
        assert result['new_temp'] < 50.0
        assert result['new_temp'] >= 0.0

    def test_crystallized_no_decay(self):
        """固化记忆不应衰减"""
        result = TemperatureEngine.on_decay(
            current_temp=100.0,
            last_accessed=(datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        )
        assert result['new_temp'] == 100.0

    def test_emotion_protection(self):
        """高情感分数应该减缓衰减"""
        days_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        no_emotion = TemperatureEngine.on_decay(
            current_temp=50.0, last_accessed=days_ago, emotion_score=0.0
        )
        with_emotion = TemperatureEngine.on_decay(
            current_temp=50.0, last_accessed=days_ago, emotion_score=0.8
        )
        assert with_emotion['new_temp'] > no_emotion['new_temp']

    def test_important_protection(self):
        """重要记忆应该减缓衰减"""
        days_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        normal = TemperatureEngine.on_decay(
            current_temp=50.0, last_accessed=days_ago, is_important=False
        )
        important = TemperatureEngine.on_decay(
            current_temp=50.0, last_accessed=days_ago, is_important=True
        )
        assert important['new_temp'] > normal['new_temp']

    def test_relation_protection(self):
        """多关联记忆应该减缓衰减"""
        days_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        few_relations = TemperatureEngine.on_decay(
            current_temp=50.0, last_accessed=days_ago, relation_count=1
        )
        many_relations = TemperatureEngine.on_decay(
            current_temp=50.0, last_accessed=days_ago, relation_count=5
        )
        assert many_relations['new_temp'] >= few_relations['new_temp']

    def test_ebbinghaus_curve(self):
        """遗忘曲线应该影响衰减率"""
        days_ago_1 = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        # 6 天而非 7 天整：7 天落在曲线分段边界，微秒级 timing 抖动会两支
        # 同因子（大合批曾现 9.375 > 9.375）。残留处理 2026-09-13
        days_ago_6 = (datetime.now(timezone.utc) - timedelta(days=6)).isoformat()

        result_1 = TemperatureEngine.on_decay(
            current_temp=50.0, last_accessed=days_ago_1
        )
        result_7 = TemperatureEngine.on_decay(
            current_temp=50.0, last_accessed=days_ago_6
        )

        # 1天内衰减曲线因子2.0，7天内1.0
        assert result_1['decay_amount'] > result_7['decay_amount']

    def test_return_dict_structure(self):
        """返回字典应包含必要字段"""
        days_ago = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
        result = TemperatureEngine.on_decay(
            current_temp=50.0, last_accessed=days_ago
        )
        assert 'new_temp' in result
        assert 'lifecycle_stage' in result
        assert 'days_idle' in result
        assert 'decay_amount' in result

    def test_temperature_never_negative(self):
        """温度不应为负"""
        long_ago = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
        result = TemperatureEngine.on_decay(
            current_temp=10.0, last_accessed=long_ago
        )
        assert result['new_temp'] >= 0.0

    def test_lifecycle_stage_active(self):
        """高温且近期访问应为active阶段"""
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        result = TemperatureEngine.on_decay(
            current_temp=60.0, last_accessed=yesterday
        )
        assert result['lifecycle_stage'] == 'active'


class TestDetermineStage:
    """测试生命周期阶段判断"""

    def test_active_stage(self):
        """高温短期应为active"""
        stage = TemperatureEngine._determine_stage(
            temperature=60.0, days_idle=3, is_important=False
        )
        assert stage == 'active'

    def test_secondary_stage(self):
        """中温中期应为secondary"""
        stage = TemperatureEngine._determine_stage(
            temperature=30.0, days_idle=15, is_important=False
        )
        assert stage == 'secondary'

    def test_archived_stage(self):
        """低温长期应为archived"""
        stage = TemperatureEngine._determine_stage(
            temperature=10.0, days_idle=45, is_important=False
        )
        assert stage == 'archived'

    def test_deleted_stage(self):
        """极温超长应为deleted"""
        stage = TemperatureEngine._determine_stage(
            temperature=3.0, days_idle=65, is_important=False
        )
        assert stage == 'deleted'

    def test_important_minimum_secondary(self):
        """重要记忆最低到secondary"""
        stage = TemperatureEngine._determine_stage(
            temperature=10.0, days_idle=65, is_important=True
        )
        assert stage == 'secondary'


class TestShouldUpgradeToImportant:
    """测试升级为重要记忆的判断"""

    def test_high_temperature_upgrade(self):
        """温度>=80应该升级"""
        assert TemperatureEngine.should_upgrade_to_important(
            temperature=85.0, access_count=1, emotion_score=0.0, relation_count=0
        ) is True

    def test_frequent_access_upgrade(self):
        """访问>=10次且温度>=70应该升级"""
        assert TemperatureEngine.should_upgrade_to_important(
            temperature=75.0, access_count=12, emotion_score=0.0, relation_count=0
        ) is True

    def test_high_emotion_upgrade(self):
        """情感>=0.8且温度>=65应该升级"""
        assert TemperatureEngine.should_upgrade_to_important(
            temperature=70.0, access_count=1, emotion_score=0.9, relation_count=0
        ) is True

    def test_many_relations_upgrade(self):
        """关联>=5且温度>=60应该升级"""
        assert TemperatureEngine.should_upgrade_to_important(
            temperature=65.0, access_count=1, emotion_score=0.0, relation_count=6
        ) is True

    def test_no_upgrade(self):
        """条件不满足不应升级"""
        assert TemperatureEngine.should_upgrade_to_important(
            temperature=40.0, access_count=2, emotion_score=0.3, relation_count=1
        ) is False


class TestShouldCrystallize:
    """测试固化为永久记忆的判断"""

    def test_high_temp_important_emotion(self):
        """温度>=90且重要且情感>=0.9应该固化"""
        assert TemperatureEngine.should_crystallize(
            temperature=95.0, is_important=True, emotion_score=0.95, metadata={}
        ) is True

    def test_agent_marked_important(self):
        """agent标记重要应该固化"""
        assert TemperatureEngine.should_crystallize(
            temperature=50.0, is_important=False, emotion_score=0.0,
            metadata={'agent_marked_important': True}
        ) is True

    def test_user_locked(self):
        """用户锁定应该固化"""
        assert TemperatureEngine.should_crystallize(
            temperature=50.0, is_important=False, emotion_score=0.0,
            metadata={'user_locked': True}
        ) is True

    def test_special_keywords(self):
        """包含特殊关键词应该固化"""
        assert TemperatureEngine.should_crystallize(
            temperature=50.0, is_important=False, emotion_score=0.0,
            metadata={'content': '今天是他的生日'}
        ) is True

    def test_anniversary_keyword(self):
        """包含anniversary应该固化"""
        assert TemperatureEngine.should_crystallize(
            temperature=50.0, is_important=False, emotion_score=0.0,
            metadata={'content': 'wedding anniversary celebration'}
        ) is True

    def test_no_crystallize(self):
        """条件不满足不应固化"""
        assert TemperatureEngine.should_crystallize(
            temperature=50.0, is_important=False, emotion_score=0.5, metadata={}
        ) is False
