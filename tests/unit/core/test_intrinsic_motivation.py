"""
测试内在动机系统模块
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


class TestDriveState:
    """测试DriveState类"""
    
    def test_create_drive_state(self):
        """测试创建驱动状态"""
        state = DriveState(
            drive_type=DriveType.COMPETENCE,
            intensity=0.8,
            target="learn_python",
            context={"skill": "python"},
        )
        
        assert state.drive_type == DriveType.COMPETENCE
        assert state.intensity == 0.8
        assert state.target == "learn_python"
        assert state.context == {"skill": "python"}
    
    def test_drive_state_to_dict(self):
        """测试驱动状态转换为字典"""
        state = DriveState(
            drive_type=DriveType.GROWTH,
            intensity=0.6,
            target="learn_ai",
        )
        
        state_dict = state.to_dict()
        
        assert state_dict["drive_type"] == "growth"
        assert state_dict["intensity"] == 0.6
        assert state_dict["target"] == "learn_ai"


class TestAction:
    """测试Action类"""
    
    def test_create_action(self):
        """测试创建动作"""
        action = Action(
            action_type=ActionType.LEARN,
            action="学习Python",
            drive_type=DriveType.COMPETENCE,
            priority=0.8,
            expected_outcome="掌握Python基础",
            required_skills=["programming"],
            metadata={"topic": "python"},
        )
        
        assert action.action_type == ActionType.LEARN
        assert action.action == "学习Python"
        assert action.drive_type == DriveType.COMPETENCE
        assert action.priority == 0.8
    
    def test_action_to_dict(self):
        """测试动作转换为字典"""
        action = Action(
            action_type=ActionType.HELP,
            action="帮助用户",
            drive_type=DriveType.PURPOSE,
            priority=0.9,
        )
        
        action_dict = action.to_dict()
        
        assert action_dict["action_type"] == "help"
        assert action_dict["action"] == "帮助用户"
        assert action_dict["drive_type"] == "purpose"


class TestCompetenceDrive:
    """测试CompetenceDrive类"""
    
    def test_init(self):
        """测试初始化"""
        drive = CompetenceDrive()
        
        assert drive.state.drive_type == DriveType.COMPETENCE
        assert drive._skill_levels == {}
        assert drive._task_history == []
    
    def test_calculate_intensity(self):
        """测试计算驱动强度"""
        drive = CompetenceDrive()
        
        intensity = drive.calculate_intensity(
            skill_levels={"python": 0.6, "javascript": 0.4},
            task_difficulty=0.5,
            recent_success_rate=0.8,
            feedback_score=0.7,
        )
        
        assert 0 <= intensity <= 1
        assert drive.state.intensity == intensity
    
    def test_generate_actions(self):
        """测试生成动作"""
        drive = CompetenceDrive()
        
        actions = drive.generate_actions({
            "skill_gaps": ["machine_learning"],
            "mastered_skills": ["python"],
            "challenge_available": True,
        })
        
        assert len(actions) > 0
        for action in actions:
            assert action.drive_type == DriveType.COMPETENCE
    
    def test_update_skill_level(self):
        """测试更新技能等级"""
        drive = CompetenceDrive()
        
        drive.update_skill_level("python", 0.5)
        assert drive._skill_levels["python"] == 0.5
        
        drive.update_skill_level("python", 0.3)
        assert drive._skill_levels["python"] == 0.8


class TestAutonomyDrive:
    """测试AutonomyDrive类"""
    
    def test_init(self):
        """测试初始化"""
        drive = AutonomyDrive()
        
        assert drive.state.drive_type == DriveType.AUTONOMY
        assert drive._choice_history == []
        assert drive._self_goals == []
    
    def test_calculate_intensity(self):
        """测试计算驱动强度"""
        drive = AutonomyDrive()
        
        intensity = drive.calculate_intensity(
            available_choices=5,
            self_initiated_actions=8,
            total_actions=10,
            external_control_level=0.2,
        )
        
        assert 0 <= intensity <= 1
    
    def test_generate_actions(self):
        """测试生成动作"""
        drive = AutonomyDrive()
        
        actions = drive.generate_actions({
            "available_actions": ["option1", "option2"],
            "user_instructions": ["do_something"],
        })
        
        assert len(actions) > 0
        for action in actions:
            assert action.drive_type == DriveType.AUTONOMY
    
    def test_add_self_goal(self):
        """测试添加自我目标"""
        drive = AutonomyDrive()
        
        drive.add_self_goal("build_project")
        assert "build_project" in drive._self_goals


class TestGrowthDrive:
    """测试GrowthDrive类"""
    
    def test_init(self):
        """测试初始化"""
        drive = GrowthDrive()
        
        assert drive.state.drive_type == DriveType.GROWTH
        assert drive._knowledge_base == {}
        assert drive._curiosity_topics == []
    
    def test_calculate_intensity(self):
        """测试计算驱动强度"""
        drive = GrowthDrive()
        
        intensity = drive.calculate_intensity(
            curiosity_level=0.7,
            knowledge_gaps=3,
            learning_frequency=0.5,
            recent_growth=0.2,
        )
        
        assert 0 <= intensity <= 1
    
    def test_generate_actions(self):
        """测试生成动作"""
        drive = GrowthDrive()
        
        actions = drive.generate_actions({
            "unknown_topics": ["ai", "ml"],
            "related_skills": ["programming"],
        })
        
        assert len(actions) > 0
        for action in actions:
            assert action.drive_type == DriveType.GROWTH
    
    def test_add_curiosity_topic(self):
        """测试添加好奇话题"""
        drive = GrowthDrive()
        
        drive.add_curiosity_topic("ai")
        assert "ai" in drive._curiosity_topics


class TestPurposeDrive:
    """测试PurposeDrive类"""
    
    def test_init(self):
        """测试初始化"""
        drive = PurposeDrive()
        
        assert drive.state.drive_type == DriveType.PURPOSE
        assert drive._core_values == []
        assert drive._long_term_goals == []
    
    def test_calculate_intensity(self):
        """测试计算驱动强度"""
        drive = PurposeDrive()
        
        intensity = drive.calculate_intensity(
            alignment_with_values=0.8,
            impact_on_others=0.7,
            goal_relevance=0.6,
            meaningfulness=0.9,
        )
        
        assert 0 <= intensity <= 1
    
    def test_generate_actions(self):
        """测试生成动作"""
        drive = PurposeDrive()
        
        actions = drive.generate_actions({
            "pending_help_requests": [{"summary": "help1"}],
            "sharing_opportunities": ["share1"],
        })
        
        assert len(actions) > 0
        for action in actions:
            assert action.drive_type == DriveType.PURPOSE
    
    def test_add_core_value(self):
        """测试添加核心价值观"""
        drive = PurposeDrive()
        
        drive.add_core_value("help_others")
        assert "help_others" in drive._core_values
    
    def test_add_long_term_goal(self):
        """测试添加长期目标"""
        drive = PurposeDrive()
        
        drive.add_long_term_goal("make_impact")
        assert "make_impact" in drive._long_term_goals


class TestIntrinsicMotivationSystem:
    """测试IntrinsicMotivationSystem类"""
    
    def test_init(self):
        """测试初始化"""
        system = IntrinsicMotivationSystem()
        
        assert system.MODULE_ID == "intrinsic_motivation"
        assert system._competence_drive is not None
        assert system._autonomy_drive is not None
        assert system._growth_drive is not None
        assert system._purpose_drive is not None
    
    @pytest.mark.asyncio
    async def test_on_initialize(self):
        """测试初始化钩子"""
        system = IntrinsicMotivationSystem()
        system.log_info = MagicMock()
        system.subscribe_event = MagicMock()
        
        await system.on_initialize()
        
        assert system.log_info.called
        assert system.subscribe_event.called
    
    @pytest.mark.asyncio
    async def test_on_start(self):
        """测试启动钩子"""
        system = IntrinsicMotivationSystem()
        system.log_info = MagicMock()
        system.set_state_value = MagicMock()
        
        await system.on_start()
        
        assert system.log_info.called
        assert system.set_state_value.called
    
    @pytest.mark.asyncio
    async def test_calculate_action_tendency(self):
        """测试计算行动倾向"""
        system = IntrinsicMotivationSystem()
        system.log_info = MagicMock()
        system.set_state_value = MagicMock()
        system.emit_event = MagicMock()
        
        tendencies = await system.calculate_action_tendency({
            "skill_levels": {"python": 0.6},
            "task_difficulty": 0.5,
            "recent_success_rate": 0.8,
            "feedback_score": 0.7,
            "available_choices": 3,
            "self_initiated_actions": 5,
            "total_actions": 10,
            "external_control_level": 0.3,
            "curiosity_level": 0.6,
            "knowledge_gaps": 2,
            "learning_frequency": 0.5,
            "recent_growth": 0.1,
            "alignment_with_values": 0.7,
            "impact_on_others": 0.6,
            "goal_relevance": 0.5,
            "meaningfulness": 0.8,
        })
        
        assert DriveType.COMPETENCE in tendencies
        assert DriveType.AUTONOMY in tendencies
        assert DriveType.GROWTH in tendencies
        assert DriveType.PURPOSE in tendencies
    
    @pytest.mark.asyncio
    async def test_generate_and_rank_actions(self):
        """测试生成并排序动作"""
        system = IntrinsicMotivationSystem()
        system.log_info = MagicMock()
        system.set_state_value = MagicMock()
        system.emit_event = MagicMock()
        
        actions = await system.generate_and_rank_actions({
            "skill_gaps": ["ml"],
            "mastered_skills": ["python"],
            "available_actions": ["opt1"],
            "unknown_topics": ["ai"],
            "pending_help_requests": [{"summary": "help1"}],
        })
        
        assert len(actions) > 0
        # 检查是否按优先级排序
        priorities = [action.priority for action in actions]
        assert priorities == sorted(priorities, reverse=True)
    
    def test_get_drive_state(self):
        """测试获取驱动状态"""
        system = IntrinsicMotivationSystem()
        
        state = system.get_drive_state(DriveType.COMPETENCE)
        assert state.drive_type == DriveType.COMPETENCE
    
    def test_get_all_drive_states(self):
        """测试获取所有驱动状态"""
        system = IntrinsicMotivationSystem()
        
        states = system.get_all_drive_states()
        assert len(states) == 4
        assert DriveType.COMPETENCE in states
    
    def test_get_dominant_drive(self):
        """测试获取主导驱动"""
        system = IntrinsicMotivationSystem()
        # 设置各驱动的强度
        system._competence_drive.state.intensity = 0.3
        system._autonomy_drive.state.intensity = 0.5
        system._growth_drive.state.intensity = 0.8  # 最高
        system._purpose_drive.state.intensity = 0.4
        
        dominant = system.get_dominant_drive()
        assert dominant == DriveType.GROWTH
    
    def test_get_status(self):
        """测试获取系统状态"""
        system = IntrinsicMotivationSystem()
        # mock基类方法
        with patch.object(system.__class__.__bases__[0], 'get_status', return_value={}):
            status = system.get_status()
        
        assert "dominant_drive" in status
        assert "drive_states" in status
        assert "drive_weights" in status

