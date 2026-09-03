"""
SkillExecutor 基类测试

验证 manifest/executor 分离模式中的 executor 层：
- SkillResult dataclass 结构
- SkillExecutor ABC 不可直接实例化
- BaseSkillExecutor 提供 __init__ 和默认行为
- 子类实现 execute() 返回 SkillResult
"""
import pytest

from neurova.skills.executor import SkillExecutor, BaseSkillExecutor, SkillResult


# ================================================================
# SkillResult dataclass
# ================================================================

class TestSkillResult:
    def test_default_values(self):
        """SkillResult 默认值：success=True, output=None, error=None, metadata={}"""
        r = SkillResult()
        assert r.success is True
        assert r.output is None
        assert r.error is None
        assert r.metadata == {}

    def test_success_with_output(self):
        """成功结果携带 output"""
        r = SkillResult(success=True, output={"key": "value"})
        assert r.success is True
        assert r.output == {"key": "value"}

    def test_failure_with_error(self):
        """失败结果携带 error"""
        r = SkillResult(success=False, error="something went wrong")
        assert r.success is False
        assert r.error == "something went wrong"

    def test_metadata_dict(self):
        """metadata 是独立 dict（不共享默认值）"""
        r1 = SkillResult()
        r1.metadata["foo"] = "bar"
        r2 = SkillResult()
        assert "foo" not in r2.metadata


# ================================================================
# SkillExecutor ABC
# ================================================================

class TestSkillExecutorABC:
    def test_cannot_instantiate_abstract(self):
        """SkillExecutor 是 ABC，不能直接实例化"""
        with pytest.raises(TypeError):
            SkillExecutor()


# ================================================================
# BaseSkillExecutor
# ================================================================

class TestBaseSkillExecutor:
    def test_requires_skill_id_and_name(self):
        """BaseSkillExecutor 需要 skill_id 和 skill_name"""

        class MyExecutor(BaseSkillExecutor):
            def execute(self, *args, **kwargs):
                return SkillResult(output="done")

        exe = MyExecutor(skill_id="my_skill", skill_name="My Skill")
        assert exe.skill_id == "my_skill"
        assert exe.skill_name == "My Skill"

    def test_execute_returns_skill_result(self):
        """子类 execute() 返回 SkillResult"""

        class MyExecutor(BaseSkillExecutor):
            def execute(self, *args, **kwargs):
                return SkillResult(success=True, output="executed")

        exe = MyExecutor(skill_id="test", skill_name="Test")
        result = exe.execute()
        assert isinstance(result, SkillResult)
        assert result.success is True
        assert result.output == "executed"

    def test_repr(self):
        """__repr__ 包含 skill_id 和 skill_name"""

        class MyExecutor(BaseSkillExecutor):
            def execute(self, *args, **kwargs):
                return SkillResult()

        exe = MyExecutor(skill_id="my_skill", skill_name="My Skill")
        repr_str = repr(exe)
        assert "my_skill" in repr_str
        assert "My Skill" in repr_str
