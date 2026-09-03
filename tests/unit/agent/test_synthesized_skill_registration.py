"""
红灯测试：合成工具注册到 SkillRegistry 时，应保留可执行元数据(config)，而非仅 name/description 的 "空壳"

复现 bug：
    `_register_synthesized_tool`(chat_pipeline.py) 用 `neurova.skills.models.Skill` 构造
    携带 config(parameters_schema/tool_sequence/confidence) 的 manifest 后调用
    `skill_registry.register_skill(manifest, path)`。

    但 `skill_system.SkillRegistry.register_skill` 里的
    `isinstance(manifest, skill_system.Skill)` 对 `neurova.skills.models.Skill` 实例返回
    False（两者是独立类），于是走 fallback 分支，只用 name/description 构造
    `skill_system.Skill(name, description)` —— 合成工具的可执行逻辑(config)被彻底丢弃，
    注册成无法执行的空壳。
"""

from types import SimpleNamespace

from neurova.skill_system import SkillRegistry
from neurova.skills.models import Skill as ModelsSkill, SkillSource


class TestRegisterSkillPreservesConfig:
    """注册带 config 的合成工具 manifest 时，应保留 config 元数据"""

    def _make_registry(self) -> SkillRegistry:
        return SkillRegistry()

    def test_register_models_skill_preserves_config(self):
        """合成工具(neurova.skills.models.Skill)注册后，get_skill 应保留 config。"""
        reg = self._make_registry()
        manifest = ModelsSkill(
            id="web_search_v2",
            name="web_search_v2",
            description="搜索网页",
            source=SkillSource.LOCAL,
            config={
                "parameters_schema": {
                    "type": "object",
                    "properties": {"q": {"type": "string"}},
                },
                "tool_sequence": ["search", "parse"],
                "synthesized": True,
            },
        )
        ok = reg.register_skill(manifest, None)
        assert ok is True
        stored = reg.get_skill("web_search_v2")
        assert stored is not None
        assert getattr(stored, "config", {}) == manifest.config

    def test_register_generic_manifest_preserves_config(self):
        """非 Skill 实例但携带 config 的占位对象，注册后也应保留 config。"""
        reg = self._make_registry()
        manifest = SimpleNamespace(
            name="data_clean_v3",
            description="清洗数据",
            config={"parameters_schema": {"type": "object"}, "synthesized": True},
        )
        ok = reg.register_skill(manifest, None)
        assert ok is True
        stored = reg.get_skill("data_clean_v3")
        assert stored is not None
        assert getattr(stored, "config", {}) == manifest.config

    def test_register_manifest_without_config_gets_empty_dict(self):
        """无 config 的 manifest 注册后，skill 的 config 为空 dict（不报错）。"""
        reg = self._make_registry()
        manifest = SimpleNamespace(name="simple_skill", description="简单技能")
        ok = reg.register_skill(manifest, None)
        assert ok is True
        stored = reg.get_skill("simple_skill")
        assert stored is not None
        assert getattr(stored, "config", None) in (None, {})

    def test_stored_skill_retains_name_and_description(self):
        """注册后的技能仍保留 name/description（供防重复合成与匹配使用）。"""
        reg = self._make_registry()
        manifest = ModelsSkill(
            id="pdf_extract",
            name="pdf_extract",
            description="提取 PDF 文本",
            config={"parameters_schema": {"type": "object"}},
        )
        reg.register_skill(manifest, None)
        stored = reg.get_skill("pdf_extract")
        assert stored.name == "pdf_extract"
        assert stored.description == "提取 PDF 文本"
