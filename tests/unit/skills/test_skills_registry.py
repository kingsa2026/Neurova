"""SkillRegistry 相关 dataclass & 注册基础测试。

原测试面向已废弃的 class B SkillRegistry 完整功能（单例 _instance、register_startup_hook/
register_shutdown_hook/register_control_command/execute_*_hooks/execute_control_command/
unregister_hooks_for_skill）。这些功能在 ADR 0011 的 class A 中已不存在。

保留部分：
- HookRegistration / ControlCommandRegistration dataclass（仍在 neurova.skills.registry）
- SkillRegistry 注册基础行为（对齐 class A）

删除部分：
- 单例（class A 无 _instance）
- hooks / control commands（功能废弃且零生产调用）
"""

from threading import Thread

from neurova.skills.registry import ControlCommandRegistration, HookRegistration
from neurova.skill_system import SkillRegistry
from neurova.skills.models import SkillManifest


# --- HookRegistration / ControlCommandRegistration dataclass ---

class TestHookRegistration:
    def test_create(self):
        def cb():
            return "ok"

        h = HookRegistration("skill-1", "on_init", cb)
        assert h.skill_id == "skill-1"
        assert h.hook_name == "on_init"
        assert h.callback is cb

    def test_default_priority(self):
        h = HookRegistration("s", "on_init", lambda: None)
        assert h.priority == 100

    def test_custom_priority(self):
        h = HookRegistration("s", "on_init", lambda: None, priority=5)
        assert h.priority == 5


class TestControlCommandRegistration:
    def test_create(self):
        def handler(cmd, args):
            return cmd

        c = ControlCommandRegistration("skill-1", handler)
        assert c.skill_id == "skill-1"
        assert c.handler is handler

    def test_default_priority_level(self):
        c = ControlCommandRegistration("s", lambda cmd, args: None)
        assert c.priority_level == 10

    def test_custom_priority_level(self):
        c = ControlCommandRegistration("s", lambda cmd, args: None, priority_level=20)
        assert c.priority_level == 20


# --- SkillRegistry 基础行为（class A） ---

class TestSkillRegistryBasic:
    def _make_reg(self):
        return SkillRegistry()

    def test_register_and_get(self):
        reg = self._make_reg()
        m = SkillManifest(id="s", name="My Skill", version="1.0.0", description="d")
        assert reg.register_skill(m, None) is True
        assert reg.get_skill("My Skill") is not None

    def test_has_skill_uses_name(self):
        reg = self._make_reg()
        m = SkillManifest(id="s", name="My Skill", version="1.0.0", description="d")
        reg.register_skill(m, None)
        assert reg.has_skill("My Skill") is True
        assert reg.has_skill("s") is False

    def test_unregister(self):
        reg = self._make_reg()
        m = SkillManifest(id="s", name="My Skill", version="1.0.0", description="d")
        reg.register_skill(m, None)
        reg.unregister("My Skill")
        assert reg.has_skill("My Skill") is False

    def test_list_skills(self):
        reg = self._make_reg()
        m = SkillManifest(id="s", name="My Skill", version="1.0.0", description="d")
        reg.register_skill(m, None)
        infos = reg.list_skills()
        assert len(infos) == 1
        assert infos[0].name == "My Skill"

    def test_thread_safety_concurrent_register(self):
        reg = self._make_reg()
        errors = []

        def worker(i):
            try:
                m = SkillManifest(id=f"s{i}", name=f"Skill {i}", version="1.0.0", description="d")
                reg.register_skill(m, None)
            except Exception as e:  # pragma: no cover - 不应发生
                errors.append(e)

        threads = [Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert len(reg.get_skill_names()) == 10
