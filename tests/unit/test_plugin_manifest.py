"""
插件清单模块单元测试

测试 SemVersion、VersionConstraint、PluginType、PluginState、PluginFrameworkSurface、
PluginManifest 和 parse_manifest 的功能。（§6-157 收口：能力面词汇单点在 skills，
本文件只钉插件自己的清单形状。）
"""

import sys
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import pytest
from neurova.plugins.plugin_manifest import (
    SemVersion,
    VersionConstraint,
    PluginType,
    PluginFrameworkSurface,
    PluginState,
    PluginManifest,
    parse_manifest,
)


class TestSemVersion:
    """测试语义化版本"""

    def test_basic_version(self):
        """测试基本版本解析"""
        v = SemVersion("1.2.3")
        assert v.major == 1
        assert v.minor == 2
        assert v.patch == 3
        assert v.prerelease == ""
        assert v.build == ""

    def test_prerelease_version(self):
        """测试预发布版本"""
        v = SemVersion("1.0.0-alpha")
        assert v.major == 1
        assert v.minor == 0
        assert v.patch == 0
        assert v.prerelease == "alpha"

    def test_build_metadata(self):
        """测试构建元数据"""
        v = SemVersion("1.0.0+build.123")
        assert v.major == 1
        assert v.minor == 0
        assert v.patch == 0
        assert v.build == "build.123"

    def test_prerelease_with_build(self):
        """测试预发布版本+构建元数据"""
        v = SemVersion("1.0.0-beta.1+build.456")
        assert v.prerelease == "beta.1"
        assert v.build == "build.456"

    def test_version_with_v_prefix(self):
        """测试 v 前缀"""
        v = SemVersion("v1.2.3")
        assert v.major == 1
        assert v.minor == 2
        assert v.patch == 3

    def test_default_version(self):
        """测试默认版本"""
        v = SemVersion()
        assert v.major == 0
        assert v.minor == 0
        assert v.patch == 0

    def test_str(self):
        """测试字符串表示"""
        assert str(SemVersion("1.2.3")) == "1.2.3"
        assert str(SemVersion("1.0.0-alpha")) == "1.0.0-alpha"
        assert str(SemVersion("1.0.0+build")) == "1.0.0+build"
        assert str(SemVersion("1.0.0-beta+build")) == "1.0.0-beta+build"

    def test_repr(self):
        """测试 repr"""
        assert repr(SemVersion("1.2.3")) == "SemVersion('1.2.3')"

    def test_equality(self):
        """测试相等性"""
        assert SemVersion("1.0.0") == SemVersion("1.0.0")
        assert SemVersion("1.0.0-alpha") == SemVersion("1.0.0-alpha")
        assert SemVersion("1.0.0") != SemVersion("2.0.0")
        assert SemVersion("1.0.0") != SemVersion("1.0.0-alpha")

    def test_less_than(self):
        """测试小于比较"""
        assert SemVersion("1.0.0") < SemVersion("2.0.0")
        assert SemVersion("1.0.0") < SemVersion("1.1.0")
        assert SemVersion("1.0.0") < SemVersion("1.0.1")
        assert SemVersion("1.0.0-alpha") < SemVersion("1.0.0")
        assert SemVersion("1.0.0-alpha") < SemVersion("1.0.0-beta")

    def test_greater_than(self):
        """测试大于比较"""
        assert SemVersion("2.0.0") > SemVersion("1.0.0")
        assert SemVersion("1.1.0") > SemVersion("1.0.0")
        assert SemVersion("1.0.1") > SemVersion("1.0.0")
        assert SemVersion("1.0.0") > SemVersion("1.0.0-alpha")

    def test_less_equal(self):
        """测试小于等于"""
        assert SemVersion("1.0.0") <= SemVersion("1.0.0")
        assert SemVersion("1.0.0") <= SemVersion("2.0.0")
        assert not SemVersion("2.0.0") <= SemVersion("1.0.0")

    def test_greater_equal(self):
        """测试大于等于"""
        assert SemVersion("1.0.0") >= SemVersion("1.0.0")
        assert SemVersion("2.0.0") >= SemVersion("1.0.0")
        assert not SemVersion("1.0.0") >= SemVersion("2.0.0")

    def test_to_tuple(self):
        """测试转换为元组"""
        assert SemVersion("1.2.3").to_tuple() == (1, 2, 3)

    def test_is_compatible_with(self):
        """测试兼容性检查"""
        v1 = SemVersion("1.2.3")
        v2 = SemVersion("1.9.9")
        v3 = SemVersion("2.0.0")
        assert v1.is_compatible_with(v2)
        assert not v1.is_compatible_with(v3)


class TestVersionConstraint:
    """测试版本约束"""

    def test_exact_constraint(self):
        """测试精确版本约束"""
        c = VersionConstraint("1.0.0")
        assert c.satisfies(SemVersion("1.0.0"))
        assert not c.satisfies(SemVersion("1.0.1"))

    def test_gte_constraint(self):
        """测试大于等于约束"""
        c = VersionConstraint(">=1.0.0")
        assert c.satisfies(SemVersion("1.0.0"))
        assert c.satisfies(SemVersion("1.1.0"))
        assert not c.satisfies(SemVersion("0.9.0"))

    def test_lte_constraint(self):
        """测试小于等于约束"""
        c = VersionConstraint("<=1.0.0")
        assert c.satisfies(SemVersion("1.0.0"))
        assert c.satisfies(SemVersion("0.9.0"))
        assert not c.satisfies(SemVersion("1.1.0"))

    def test_gt_constraint(self):
        """测试大于约束"""
        c = VersionConstraint(">1.0.0")
        assert c.satisfies(SemVersion("1.0.1"))
        assert not c.satisfies(SemVersion("1.0.0"))
        assert not c.satisfies(SemVersion("0.9.0"))

    def test_lt_constraint(self):
        """测试小于约束"""
        c = VersionConstraint("<1.0.0")
        assert c.satisfies(SemVersion("0.9.0"))
        assert not c.satisfies(SemVersion("1.0.0"))
        assert not c.satisfies(SemVersion("1.1.0"))

    def test_caret_constraint(self):
        """测试 ^ 约束 (兼容版本)"""
        c = VersionConstraint("^1.2.3")
        assert c.satisfies(SemVersion("1.2.3"))
        assert c.satisfies(SemVersion("1.9.9"))
        assert not c.satisfies(SemVersion("2.0.0"))
        assert not c.satisfies(SemVersion("1.2.2"))

    def test_tilde_constraint(self):
        """测试 ~ 约束 (近似版本)"""
        c = VersionConstraint("~1.2.3")
        assert c.satisfies(SemVersion("1.2.3"))
        assert c.satisfies(SemVersion("1.2.9"))
        assert not c.satisfies(SemVersion("1.3.0"))
        assert not c.satisfies(SemVersion("1.2.2"))

    def test_range_constraint(self):
        """测试范围约束"""
        c = VersionConstraint(">=1.0.0,<=2.0.0")
        assert c.satisfies(SemVersion("1.5.0"))
        assert c.satisfies(SemVersion("1.0.0"))
        assert c.satisfies(SemVersion("2.0.0"))
        assert not c.satisfies(SemVersion("0.9.0"))
        assert not c.satisfies(SemVersion("2.1.0"))

    def test_repr(self):
        """测试 repr"""
        c = VersionConstraint(">=1.0.0")
        assert "VersionConstraint" in repr(c)
        assert ">=1.0.0" in repr(c)


class TestPluginType:
    """测试插件类型枚举"""

    def test_plugin_types(self):
        """测试插件类型值"""
        assert PluginType.CORE.value == "core"
        assert PluginType.SKILL.value == "skill"
        assert PluginType.CHANNEL.value == "channel"
        assert PluginType.TOOL.value == "tool"
        assert PluginType.THEME.value == "theme"
        assert PluginType.FUNCTIONAL.value == "functional"
        assert PluginType.EXTENSION.value == "extension"

    def test_from_string(self):
        """测试从字符串创建"""
        assert PluginType("core") == PluginType.CORE
        assert PluginType("skill") == PluginType.SKILL


class TestPluginState:
    """测试插件状态枚举"""

    def test_plugin_states(self):
        """测试插件状态值"""
        assert PluginState.INSTALLED.value == "installed"
        assert PluginState.ENABLED.value == "enabled"
        assert PluginState.DISABLED.value == "disabled"
        assert PluginState.LOADED.value == "loaded"
        assert PluginState.ERROR.value == "error"
        assert PluginState.UPDATING.value == "updating"

    def test_from_string(self):
        """测试从字符串创建"""
        assert PluginState("installed") == PluginState.INSTALLED
        assert PluginState("enabled") == PluginState.ENABLED


class TestPluginFrameworkSurface:
    """§6-157 收口：这里只剩**插件独有**的框架中介面，能力面词汇单点在 skills。

    原来这一族有八项 `PluginPermission`，其中四项与 `skills/permissions.py` 的
    `KNOWN_CAPABILITY_KEYS` 是同一件事的两份定义——而那一份才是真在 `tool_executor`
    里拦的。本族因此改成钉三件事：只剩两档、旧值不再被认、旧清单字段被拒而不是被猜。
    """

    def test_surface_values_are_exactly_the_event_bus_pair(self):
        assert [s.value for s in PluginFrameworkSurface] == ["read:events", "emit:events"]

    def test_from_string(self):
        assert PluginFrameworkSurface("emit:events") == PluginFrameworkSurface.EMIT_EVENTS

    def test_retired_capability_values_are_not_surfaces(self):
        """被收口掉的六个值不能"顺手也认一下"——那等于给第二份词汇留入口。"""
        for retired in ("http:request", "read:files", "write:files",
                        "network:access", "execute:commands", "admin"):
            with pytest.raises(ValueError):
                PluginFrameworkSurface(retired)

    def test_legacy_required_permissions_field_is_rejected_not_guessed(self):
        data = {"plugin_id": "p", "name": "p", "version": "1.0.0",
                "required_permissions": ["read:events"]}
        with pytest.raises(ValueError) as caught:
            parse_manifest(data)
        assert "不做自动映射" in str(caught.value), (
            "旧字段被静默忽略＝旧授权语义被悄悄改掉；报错要写明为什么不能自动映射")


class TestPluginManifest:
    """测试插件清单"""

    def test_basic_manifest(self):
        """测试基本清单"""
        manifest = PluginManifest(
            plugin_id="test-plugin",
            name="Test Plugin",
            version=SemVersion("1.0.0"),
            description="A test plugin",
            author="Test Author",
            plugin_type=PluginType.SKILL,
        )
        assert manifest.plugin_id == "test-plugin"
        assert manifest.name == "Test Plugin"
        assert manifest.version == SemVersion("1.0.0")
        assert manifest.description == "A test plugin"
        assert manifest.author == "Test Author"
        assert manifest.plugin_type == PluginType.SKILL

    def test_manifest_defaults(self):
        """测试清单默认值"""
        manifest = PluginManifest(
            plugin_id="test",
            name="Test",
            version=SemVersion("1.0.0"),
        )
        assert manifest.description == ""
        assert manifest.author == ""
        assert manifest.plugin_type == PluginType.FUNCTIONAL
        assert manifest.dependencies == {}
        assert manifest.permissions == {}
        assert manifest.framework_surfaces == []
        assert manifest.entry_point == ""
        assert manifest.module_class == ""
        assert manifest.config_schema == {}
        assert manifest.default_config == {}

    def test_manifest_with_dependencies(self):
        """测试带依赖的清单"""
        manifest = PluginManifest(
            plugin_id="test",
            name="Test",
            version=SemVersion("1.0.0"),
            dependencies={"neurova-core": ">=1.0.0"},
        )
        assert manifest.dependencies == {"neurova-core": ">=1.0.0"}

    def test_manifest_with_permissions(self):
        """§6-157 收口后的清单形状：能力面是 dict（原样带过，合法性由 skills 那道门判），
        框架中介面是封闭枚举列表。"""
        manifest = PluginManifest(
            plugin_id="test",
            name="Test",
            version=SemVersion("1.0.0"),
            permissions={"network": True, "file": {"enabled": True, "read_only": True}},
            framework_surfaces=[PluginFrameworkSurface.READ_EVENTS],
        )
        assert manifest.permissions["network"] is True
        assert manifest.framework_surfaces == [PluginFrameworkSurface.READ_EVENTS]

    def test_manifest_does_not_validate_capability_keys(self):
        """清单层**不判**能力键合法性——判它是 `skill_install_gate` 的活（单点）。
        这一格钉的是"别在这儿再写一套校验"：写第二套就会与那道门漂移。"""
        manifest = PluginManifest(plugin_id="t", name="T", version=SemVersion("1.0.0"),
                                  permissions={"teleport": True})
        assert manifest.permissions == {"teleport": True}

    def test_manifest_to_dict(self):
        """测试清单转换为字典"""
        manifest = PluginManifest(
            plugin_id="test-plugin",
            name="Test Plugin",
            version=SemVersion("1.0.0"),
            plugin_type=PluginType.SKILL,
            permissions={"network": True},
            framework_surfaces=[PluginFrameworkSurface.EMIT_EVENTS],
        )
        d = manifest.to_dict()
        assert d["plugin_id"] == "test-plugin"
        assert d["name"] == "Test Plugin"
        assert d["version"] == "1.0.0"
        assert d["plugin_type"] == "skill"
        assert d["permissions"] == {"network": True}
        assert d["framework_surfaces"] == ["emit:events"]

    def test_manifest_from_dict(self):
        """测试从字典创建清单"""
        data = {
            "plugin_id": "test-plugin",
            "name": "Test Plugin",
            "version": "1.0.0",
            "plugin_type": "skill",
            "permissions": {"system": True},
            "framework_surfaces": ["read:events"],
        }
        manifest = PluginManifest.from_dict(data)
        assert manifest.plugin_id == "test-plugin"
        assert manifest.version == SemVersion("1.0.0")
        assert manifest.plugin_type == PluginType.SKILL
        assert manifest.permissions == {"system": True}
        assert manifest.framework_surfaces == [PluginFrameworkSurface.READ_EVENTS]

    def test_manifest_roundtrip(self):
        """测试清单序列化往返"""
        original = PluginManifest(
            plugin_id="test-plugin",
            name="Test Plugin",
            version=SemVersion("1.2.3"),
            plugin_type=PluginType.CHANNEL,
            dependencies={"dep1": ">=1.0.0"},
            permissions={"network": True},
            framework_surfaces=[PluginFrameworkSurface.READ_EVENTS],
        )
        d = original.to_dict()
        restored = PluginManifest.from_dict(d)
        assert restored.plugin_id == original.plugin_id
        assert restored.version == original.version
        assert restored.plugin_type == original.plugin_type
        assert restored.dependencies == original.dependencies
        assert restored.permissions == original.permissions
        assert restored.framework_surfaces == original.framework_surfaces


class TestParseManifest:
    """测试 parse_manifest 函数"""

    def test_parse_json_manifest(self):
        """测试解析 JSON 清单"""
        json_str = '''
        {
            "plugin_id": "test-plugin",
            "name": "Test Plugin",
            "version": "1.0.0",
            "description": "A test plugin",
            "author": "Test Author",
            "plugin_type": "skill",
            "dependencies": {
                "neurova-core": ">=1.0.0"
            },
            "permissions": {"file": {"enabled": true, "read_only": true}},
            "framework_surfaces": ["emit:events"],
            "entry_point": "plugin.py",
            "module_class": "TestPlugin"
        }
        '''
        manifest = parse_manifest(json_str)
        assert manifest.plugin_id == "test-plugin"
        assert manifest.name == "Test Plugin"
        assert manifest.version == SemVersion("1.0.0")
        assert manifest.plugin_type == PluginType.SKILL
        assert "neurova-core" in manifest.dependencies
        assert manifest.permissions["file"]["read_only"] is True
        assert manifest.framework_surfaces == [PluginFrameworkSurface.EMIT_EVENTS]

    def test_parse_dict_manifest(self):
        """测试解析字典清单"""
        data = {
            "plugin_id": "test-plugin",
            "name": "Test Plugin",
            "version": "1.0.0",
        }
        manifest = parse_manifest(data)
        assert manifest.plugin_id == "test-plugin"

    def test_parse_invalid_json(self):
        """测试解析无效 JSON"""
        with pytest.raises(ValueError):
            parse_manifest("invalid json")

    def test_parse_missing_required_fields(self):
        """测试解析缺少必填字段"""
        data = {
            "plugin_id": "test-plugin",
            # 缺少 name 和 version
        }
        with pytest.raises(ValueError):
            parse_manifest(data)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])