"""
测试内在动机系统模块（对齐 neurova/core/intrinsic_motivation.py 真实契约）
"""
import pytest
from unittest.mock import patch, MagicMock
from neurova.core.intrinsic_motivation import (
    DriveType,
    ActionType,
    DriveState,
    Action,
    CompetenceDrive,
    AutonomyDrive,
    GrowthDrive,
    PurposeDrive,
    IntrinsicMotivationSystem,
)


class TestEnums:
    """测试枚举类"""

    def test_drive_type_members(self):
        """测试驱动类型枚举"""
        assert DriveType.COMPETENCE.value == "competence"
        assert DriveType.AUTONOMY.value == "autonomy"
        assert DriveType.GROWTH.value == "growth"
        assert DriveType.PURPOSE.value == "purpose"

    def test_action_type_members(self):
        """测试动作类型枚举"""
        assert ActionType.LEARN.value == "learn"
        assert ActionType.PRACTICE.value == "practice"
        assert ActionType.EXPLORE.value == "explore"
        assert ActionType.REFLECT.value == "reflect"
        assert ActionType.HELP.value == "help"
        assert ActionType.CREATE.value == "create"
        assert ActionType.OPTIMIZE.value == "optimize"
        assert ActionType.COLLABORATE.value == "collaborate"


class TestDriveState:
    """测试DriveState类"""

    def test_create_drive_state(self):
        """测试创建驱动状态（字段面 drive_type/intensity/satisfaction/history）"""
        state = DriveState(
            drive_type=DriveType.COMPETENCE,
            intensity=0.8,
            satisfaction=0.6,
        )

        assert state.drive_type == DriveType.COMPETENCE
        assert state.intensity == 0.8
        assert state.satisfaction == 0.6
        assert state.history == []

    def test_drive_state_to_dict(self):
        """测试驱动状态转换为字典"""
        state = DriveState(
            drive_type=DriveType.GROWTH,
            intensity=0.6,
            satisfaction=0.4,
        )

        state_dict = state.to_dict()

        assert state_dict["drive_type"] == "growth"
        assert state_dict["intensity"] == 0.6
        assert state_dict["satisfaction"] == 0.4
        assert "history" in state_dict
        assert "last_update" in state_dict


class TestAction:
    """测试Action类"""

    def test_create_action(self):
        """测试创建动作（描述字段为 description）"""
        action = Action(
            action_type=ActionType.LEARN,
            description="学习Python",
            drive_type=DriveType.COMPETENCE,
            priority=0.8,
            difficulty=0.4,
        )

        assert action.action_type == ActionType.LEARN
        assert action.description == "学习Python"
        assert action.drive_type == DriveType.COMPETENCE
        assert action.priority == 0.8

    def test_action_to_dict(self):
        """测试动作转换为字典"""
        action = Action(
            action_type=ActionType.HELP,
            description="帮助用户",
            drive_type=DriveType.PURPOSE,
            priority=0.9,
        )

        action_dict = action.to_dict()

        assert action_dict["action_type"] == "help"
        assert action_dict["description"] == "帮助用户"
        assert action_dict["drive_type"] == "purpose"


class TestCompetenceDrive:
    """测试CompetenceDrive类"""

    def test_init(self):
        """测试初始化（状态为公开属性）"""
        drive = CompetenceDrive()

        assert drive.skill_level == 0.5
        assert drive.task_completion_rate == 0.5
        assert drive.completed_tasks == []
        assert drive.feedback_history == []

    def test_calculate_intensity(self):
        """测试计算驱动强度（契约：单参 task_difficulty）"""
        drive = CompetenceDrive()

        intensity = drive.calculate_intensity(task_difficulty=0.5)

        assert 0 <= intensity <= 1

    def test_calculate_intensity_matches_skill(self):
        """难度与技能匹配时强度更高"""
        drive = CompetenceDrive()
        drive.skill_level = 0.5

        matched = drive.calculate_intensity(task_difficulty=0.5)
        mismatched = drive.calculate_intensity(task_difficulty=0.95)

        assert matched > mismatched

    def test_generate_actions(self):
        """测试生成动作（无参，全部归属 COMPETENCE）"""
        drive = CompetenceDrive()

        actions = drive.generate_actions()

        assert len(actions) > 0
        for action in actions:
            assert action.drive_type == DriveType.COMPETENCE

    def test_update_skill_level(self):
        """测试更新技能水平（契约：(success, difficulty)，成功升失败微降）"""
        drive = CompetenceDrive()
        initial = drive.skill_level

        drive.update_skill_level(success=True, difficulty=1.0)
        assert drive.skill_level > initial

        current = drive.skill_level
        drive.update_skill_level(success=False, difficulty=1.0)
        assert drive.skill_level < current

    def test_record_task_updates_completion_rate(self):
        """记录任务更新完成率"""
        drive = CompetenceDrive()

        drive.record_task("t1", success=True)
        drive.record_task("t2", success=False)
        drive.record_task("t3", success=True)

        assert drive.task_completion_rate == pytest.approx(2 / 3)
        assert len(drive.completed_tasks) == 3

    def test_record_feedback(self):
        """记录反馈"""
        drive = CompetenceDrive()

        drive.record_feedback("干得不错", sentiment=0.9)

        assert len(drive.feedback_history) == 1
        assert drive.feedback_history[0]["sentiment"] == 0.9


class TestAutonomyDrive:
    """测试AutonomyDrive类"""

    def test_init(self):
        """测试初始化"""
        drive = AutonomyDrive()

        assert drive.freedom_level == 0.5
        assert drive.choice_satisfaction == 0.5
        assert drive.choice_history == []
        assert drive.self_goals == []

    def test_calculate_intensity(self):
        """测试计算驱动强度（无参）"""
        drive = AutonomyDrive()

        intensity = drive.calculate_intensity()

        assert 0 <= intensity <= 1

    def test_generate_actions(self):
        """测试生成动作"""
        drive = AutonomyDrive()

        actions = drive.generate_actions()

        assert len(actions) > 0
        for action in actions:
            assert action.drive_type == DriveType.AUTONOMY

    def test_add_self_goal(self):
        """测试添加自我目标（幂等）"""
        drive = AutonomyDrive()

        drive.add_self_goal("build_project")
        drive.add_self_goal("build_project")

        assert drive.self_goals == ["build_project"]

    def test_record_choice(self):
        """测试记录选择"""
        drive = AutonomyDrive()

        drive.record_choice("use_tool_a", satisfaction=0.8)

        assert len(drive.choice_history) == 1
        assert drive.choice_history[0]["satisfaction"] == 0.8


class TestGrowthDrive:
    """测试GrowthDrive类"""

    def test_init(self):
        """测试初始化"""
        drive = GrowthDrive()

        assert drive.knowledge_level == 0.5
        assert drive.curiosity_topics == []
        assert drive.learning_history == []
        assert drive.concepts_learned == 0

    def test_calculate_intensity(self):
        """测试计算驱动强度（无参）"""
        drive = GrowthDrive()

        intensity = drive.calculate_intensity()

        assert 0 <= intensity <= 1

    def test_calculate_intensity_curiosity_boosts(self):
        """好奇心话题越多强度越高"""
        drive = GrowthDrive()
        base = drive.calculate_intensity()

        for i in range(10):
            drive.add_curiosity_topic(f"topic_{i}")

        assert drive.calculate_intensity() > base

    def test_generate_actions(self):
        """测试生成动作"""
        drive = GrowthDrive()

        actions = drive.generate_actions()

        assert len(actions) > 0
        for action in actions:
            assert action.drive_type == DriveType.GROWTH

    def test_add_curiosity_topic(self):
        """测试添加好奇话题（幂等）"""
        drive = GrowthDrive()

        drive.add_curiosity_topic("ai")
        drive.add_curiosity_topic("ai")

        assert drive.curiosity_topics == ["ai"]

    def test_record_learning(self):
        """测试记录学习"""
        drive = GrowthDrive()

        drive.record_learning("concepts", understanding=0.8)

        assert len(drive.learning_history) == 1
        assert drive.concepts_learned == 1

    def test_calculate_growth_rate(self):
        """测试成长率（无学习历史为 0）"""
        drive = GrowthDrive()

        assert drive.calculate_growth_rate() == 0.0

        drive.record_learning("x")
        assert 0 <= drive.calculate_growth_rate() <= 1


class TestPurposeDrive:
    """测试PurposeDrive类"""

    def test_init(self):
        """测试初始化"""
        drive = PurposeDrive()

        assert drive.core_values == []
        assert drive.long_term_goals == []
        assert drive.impact_score == 0.5
        assert drive.meaning_level == 0.5

    def test_calculate_intensity(self):
        """测试计算驱动强度（无参）"""
        drive = PurposeDrive()

        intensity = drive.calculate_intensity()

        assert 0 <= intensity <= 1

    def test_calculate_intensity_values_and_goals(self):
        """价值观与目标越充实强度越高"""
        drive = PurposeDrive()
        base = drive.calculate_intensity()

        drive.add_core_value("help_others")
        drive.add_long_term_goal("make_impact")

        assert drive.calculate_intensity() > base

    def test_generate_actions(self):
        """测试生成动作"""
        drive = PurposeDrive()

        actions = drive.generate_actions()

        assert len(actions) > 0
        for action in actions:
            assert action.drive_type == DriveType.PURPOSE

    def test_add_core_value(self):
        """测试添加核心价值观（幂等）"""
        drive = PurposeDrive()

        drive.add_core_value("help_others")
        drive.add_core_value("help_others")

        assert drive.core_values == ["help_others"]

    def test_add_long_term_goal(self):
        """测试添加长期目标（幂等）"""
        drive = PurposeDrive()

        drive.add_long_term_goal("make_impact")
        drive.add_long_term_goal("make_impact")

        assert drive.long_term_goals == ["make_impact"]

    def test_record_contribution_updates_impact(self):
        """记录贡献更新影响力分数"""
        drive = PurposeDrive()

        drive.record_contribution("fix bug", impact=0.9)
        drive.record_contribution("write docs", impact=0.5)

        assert drive.impact_score == pytest.approx(0.7)
        assert len(drive.contributions) == 2

    def test_calculate_impact_score(self):
        """测试影响力分数回读"""
        drive = PurposeDrive()
        assert drive.calculate_impact_score() == 0.5


class TestIntrinsicMotivationSystem:
    """测试IntrinsicMotivationSystem类"""

    def test_init(self):
        """测试初始化（驱动为公开属性，权重均分）"""
        system = IntrinsicMotivationSystem()

        assert system.competence_drive is not None
        assert system.autonomy_drive is not None
        assert system.growth_drive is not None
        assert system.purpose_drive is not None
        assert set(system.drive_weights.values()) == {0.25}
        assert system.action_history == []

    def test_on_initialize(self):
        """初始化回调同步执行不崩"""
        system = IntrinsicMotivationSystem()
        system.on_initialize()

    def test_on_start(self):
        """启动回调同步执行不崩"""
        system = IntrinsicMotivationSystem()
        system.on_start()

    def test_on_stop(self):
        """停止回调同步执行不崩"""
        system = IntrinsicMotivationSystem()
        system.on_stop()

    def test_calculate_action_tendency(self):
        """测试计算行动倾向（契约：传 ActionType，返回标量）"""
        system = IntrinsicMotivationSystem()

        tendency = system.calculate_action_tendency(ActionType.PRACTICE)

        assert 0 <= tendency <= 1

    def test_calculate_action_tendency_primary_weighted(self):
        """主驱动行动倾向高于其他行动"""
        system = IntrinsicMotivationSystem()
        system.growth_drive.knowledge_level = 0.9
        for i in range(5):
            system.growth_drive.add_curiosity_topic(f"t{i}")

        learn_tendency = system.calculate_action_tendency(ActionType.LEARN)  # GROWTH 主导
        help_tendency = system.calculate_action_tendency(ActionType.HELP)  # PURPOSE 弱

        assert learn_tendency > help_tendency

    def test_generate_and_rank_actions(self):
        """测试生成并排序动作（无参，按优先级降序）"""
        system = IntrinsicMotivationSystem()

        actions = system.generate_and_rank_actions()

        assert len(actions) > 0
        priorities = [action.priority for action in actions]
        assert priorities == sorted(priorities, reverse=True)

    def test_get_drive_state(self):
        """测试获取驱动状态"""
        system = IntrinsicMotivationSystem()

        state = system.get_drive_state(DriveType.COMPETENCE)
        assert state.drive_type == DriveType.COMPETENCE
        assert 0 <= state.intensity <= 1
        assert 0 <= state.satisfaction <= 1

    def test_get_all_drive_states(self):
        """测试获取所有驱动状态"""
        system = IntrinsicMotivationSystem()

        states = system.get_all_drive_states()
        assert len(states) == 4
        assert DriveType.COMPETENCE in states

    def test_get_dominant_drive(self):
        """测试获取主导驱动（返回 (类型, 强度) 元组）"""
        system = IntrinsicMotivationSystem()
        # 把 GROWTH 拉满（knowledge=1 + 10 个好奇话题 → intensity=1.0，加权 0.25）
        system.growth_drive.knowledge_level = 1.0
        for i in range(10):
            system.growth_drive.add_curiosity_topic(f"t{i}")
        # 压低默认最强的 COMPETENCE（intensity 0.9，加权 0.225）
        system.competence_drive.skill_level = 1.0
        system.competence_drive.challenge_preference = 0.0

        dominant, intensity = system.get_dominant_drive()
        assert dominant == DriveType.GROWTH
        assert 0 <= intensity <= 1

    def test_update_drive_weights_normalizes(self):
        """测试更新驱动权重（传入键归一化，未提及键保持不变）"""
        system = IntrinsicMotivationSystem()

        system.update_drive_weights({DriveType.COMPETENCE: 2.0, DriveType.GROWTH: 2.0})

        assert system.drive_weights[DriveType.COMPETENCE] == pytest.approx(0.5)
        assert system.drive_weights[DriveType.GROWTH] == pytest.approx(0.5)
        assert system.drive_weights[DriveType.AUTONOMY] == pytest.approx(0.25)

    def test_get_status(self):
        """测试获取系统状态键面"""
        system = IntrinsicMotivationSystem()

        status = system.get_status()

        assert "dominant_drive" in status
        assert "dominant_intensity" in status
        assert "drive_states" in status
        assert "drive_weights" in status
        assert status["dominant_drive"] in (dt.value for dt in DriveType)

    def test_action_executed_records_history(self):
        """执行行动回调写入行动历史"""
        system = IntrinsicMotivationSystem()
        action = Action(
            action_type=ActionType.LEARN,
            description="学习",
            drive_type=DriveType.GROWTH,
        )

        system._on_action_executed(action, success=True)

        assert len(system.action_history) == 1
        assert system.action_history[0]["success"] is True
