"""
SkillManifestProvider 单元测试 — 按需拉取 skill manifest

TDD 红绿灯：每个测试对应一个 vertical slice，RED → GREEN → REFACTOR。

测试目标（按 vertical slice 顺序）：
1. list_manifests() 返回 SkillManifestEntry 列表（tracer bullet）
2. get_manifest(id) 单条查询，不存在返回 None
3. 源链：local builtin → remote hub fallback
4. 缓存：重复 list 不重新拉取，refresh() 失效
5. Agent 集成：agent 挂载 manifest_provider，_skill_registry 初始为 None
6. Agent.get_skill_manifest() 按需拉取
7. Agent.load_skill(id) 按需实例化 + 缓存
8. _skill_registry lazy init（兼容层）
"""
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from neurova.skills.manifest_entry import SkillManifestEntry
from neurova.skills.manifest_provider import SkillManifestProvider
from neurova.skills.manifest_source import (
    ManifestSource,
    LocalBuiltinSource,
    RemoteHubSource,
)


class TestListManifests:
    """Slice 1: list_manifests() 返回 manifest 列表（tracer bullet）"""

    def test_list_manifests_returns_list(self):
        """list_manifests() 返回列表类型"""
        provider = SkillManifestProvider(
            sources=[LocalBuiltinSource()]
        )
        manifests = provider.list_manifests()
        assert isinstance(manifests, list)

    def test_list_manifests_returns_skill_manifest_entry_instances(self):
        """列表中每个元素都是 SkillManifestEntry 实例"""
        provider = SkillManifestProvider(
            sources=[LocalBuiltinSource()]
        )
        manifests = provider.list_manifests()
        assert len(manifests) > 0
        for m in manifests:
            assert isinstance(m, SkillManifestEntry)

    def test_list_manifests_includes_github_push_builtin(self):
        """扫描 builtin 目录应至少包含 github_push 这个 builtin skill"""
        provider = SkillManifestProvider(
            sources=[LocalBuiltinSource()]
        )
        manifests = provider.list_manifests()
        ids = [m.id for m in manifests]
        assert "github_push" in ids

    def test_list_manifests_does_not_instantiate_skill_classes(self):
        """
        核心行为：list_manifests 只返回元数据，不实例化 Skill 类。
        通过检查 manifest 对象没有 execute 方法验证（manifest 是数据类，不是 Skill 实例）。
        """
        provider = SkillManifestProvider(
            sources=[LocalBuiltinSource()]
        )
        manifests = provider.list_manifests()
        for m in manifests:
            # SkillManifestEntry 是 dataclass，不应有 execute 方法
            assert not hasattr(m, "execute")
            assert not hasattr(m, "run")


class TestGetManifest:
    """Slice 2: get_manifest(id) 单条查询"""

    def test_get_manifest_returns_matching_entry(self):
        """get_manifest 已存在的 id 返回对应的 SkillManifestEntry"""
        provider = SkillManifestProvider(sources=[LocalBuiltinSource()])
        entry = provider.get_manifest("github_push")
        assert entry is not None
        assert isinstance(entry, SkillManifestEntry)
        assert entry.id == "github_push"
        assert entry.name  # name 不为空
        assert entry.version  # version 不为空

    def test_get_manifest_nonexistent_returns_none(self):
        """get_manifest 不存在的 id 返回 None"""
        provider = SkillManifestProvider(sources=[LocalBuiltinSource()])
        entry = provider.get_manifest("nonexistent_skill_id_xyz")
        assert entry is None

    def test_get_manifest_after_list_uses_same_cache(self):
        """get_manifest 与 list_manifests 共享缓存——返回的是等价对象"""
        provider = SkillManifestProvider(sources=[LocalBuiltinSource()])
        manifests = provider.list_manifests()
        entry = provider.get_manifest("github_push")
        assert entry is not None
        # 缓存命中——返回的应该是同一个对象（id 相同）
        assert entry.id == "github_push"
        # list 中的 github_push 与 get 返回的应该是同一个对象
        list_entry = next(m for m in manifests if m.id == "github_push")
        assert entry is list_entry


class TestSourceChain:
    """Slice 3: 源链 local → remote fallback"""

    def test_local_hit_not_overridden_by_remote(self):
        """local 和 remote 都有同名 skill 时，local 优先"""
        # 构造两个 fake source，都有 id="dup" 的 manifest
        class FakeLocalSource(ManifestSource):
            @property
            def name(self):
                return "fake_local"

            def list_manifests(self):
                return [SkillManifestEntry(id="dup", name="local-version", source="local")]

        class FakeRemoteSource(ManifestSource):
            @property
            def name(self):
                return "fake_remote"

            def list_manifests(self):
                return [SkillManifestEntry(id="dup", name="remote-version", source="remote")]

        provider = SkillManifestProvider(
            sources=[FakeLocalSource(), FakeRemoteSource()]
        )
        manifests = provider.list_manifests()
        # 去重后只剩 1 条
        assert len(manifests) == 1
        # local 优先——保留 local-version
        assert manifests[0].name == "local-version"
        assert manifests[0].source == "local"

    def test_local_miss_filled_by_remote(self):
        """local 没有的 skill，由 remote 补充"""
        class FakeLocalSource(ManifestSource):
            @property
            def name(self):
                return "fake_local"

            def list_manifests(self):
                return [SkillManifestEntry(id="local_skill", name="L1", source="local")]

        class FakeRemoteSource(ManifestSource):
            @property
            def name(self):
                return "fake_remote"

            def list_manifests(self):
                return [SkillManifestEntry(id="remote_skill", name="R1", source="remote")]

        provider = SkillManifestProvider(
            sources=[FakeLocalSource(), FakeRemoteSource()]
        )
        manifests = provider.list_manifests()
        ids = {m.id for m in manifests}
        # 两个 source 的 manifest 都在结果中（无 id 冲突）
        assert ids == {"local_skill", "remote_skill"}

    def test_remote_failure_does_not_break_local(self):
        """remote source 抛异常时，local 的结果仍然返回"""
        class FakeLocalSource(ManifestSource):
            @property
            def name(self):
                return "fake_local"

            def list_manifests(self):
                return [SkillManifestEntry(id="local_skill", name="L1", source="local")]

        class BrokenRemoteSource(ManifestSource):
            @property
            def name(self):
                return "broken_remote"

            def list_manifests(self):
                raise RuntimeError("network down")

        provider = SkillManifestProvider(
            sources=[FakeLocalSource(), BrokenRemoteSource()]
        )
        manifests = provider.list_manifests()
        # broken remote 不影响 local
        assert len(manifests) == 1
        assert manifests[0].id == "local_skill"


class _CountingSource(ManifestSource):
    """辅助类：记录 list_manifests 被调用次数，用于缓存测试"""

    def __init__(self, manifests):
        self._manifests = manifests
        self.call_count = 0

    @property
    def name(self):
        return "counting"

    def list_manifests(self):
        self.call_count += 1
        return list(self._manifests)


class TestCaching:
    """Slice 4: 缓存 + refresh() 失效"""

    def test_repeated_list_uses_cache(self):
        """重复调用 list_manifests() 只拉取一次"""
        source = _CountingSource(
            [SkillManifestEntry(id="s1", name="Skill 1")]
        )
        provider = SkillManifestProvider(sources=[source])

        provider.list_manifests()
        provider.list_manifests()
        provider.list_manifests()

        assert source.call_count == 1  # 只拉取一次

    def test_get_manifest_after_list_uses_cache(self):
        """list 后 get 不再拉取"""
        source = _CountingSource(
            [SkillManifestEntry(id="s1", name="Skill 1")]
        )
        provider = SkillManifestProvider(sources=[source])

        provider.list_manifests()
        provider.get_manifest("s1")
        provider.get_manifest("nonexistent")

        assert source.call_count == 1

    def test_refresh_invalidates_cache(self):
        """refresh() 后再次 list 会重新拉取"""
        source = _CountingSource(
            [SkillManifestEntry(id="s1", name="Skill 1")]
        )
        provider = SkillManifestProvider(sources=[source])

        provider.list_manifests()
        assert source.call_count == 1

        provider.refresh()
        provider.list_manifests()
        assert source.call_count == 2  # refresh 后重新拉取

    def test_refresh_returns_new_data_after_source_update(self):
        """source 数据更新后 refresh 能拿到新数据"""
        source = _CountingSource(
            [SkillManifestEntry(id="s1", name="v1")]
        )
        provider = SkillManifestProvider(sources=[source])

        # 第一次拉取
        manifests = provider.list_manifests()
        assert manifests[0].name == "v1"

        # source 数据更新
        source._manifests = [SkillManifestEntry(id="s1", name="v2")]

        # 未 refresh——缓存还是旧数据
        manifests = provider.list_manifests()
        assert manifests[0].name == "v1"

        # refresh 后拿到新数据
        provider.refresh()
        manifests = provider.list_manifests()
        assert manifests[0].name == "v2"


# ============================================================
# Agent 集成测试（Slice 5-8）
#
# 用 Agent.__new__ 绕过重量级 __init__，手动设置最小属性集，
# 测试 Agent 类上的新方法/属性的真实行为。
# 这是 TDD skill 推荐的"通过公共接口测试行为"——不 mock 内部
# 协作者，而是用真实方法+最小 fixture。
# ============================================================


def _make_minimal_agent(tmp_path=None):
    """
    创建最小 Agent 实例——绕过 __init__ 的重量级子系统初始化

    手动设置新方法所需的最小属性：
    - _skill_manifest_provider: None（待 lazy 初始化）
    - _skill_registry: None（待 lazy 初始化）
    - _loaded_skills: {}（load_skill 的实例缓存）
    - config: 带 name 和 agent_id 的简单对象

    Args:
        tmp_path: pytest 的 tmp_path fixture，用于 workspace_path
    """
    from neurova.agent_core import Agent
    from neurova.agent_core import AgentConfig
    import tempfile
    from pathlib import Path

    workspace = Path(tmp_path) if tmp_path else Path(tempfile.mkdtemp())

    agent = Agent.__new__(Agent)
    agent._skill_manifest_provider = None
    agent._skill_registry = None
    agent._loaded_skills = {}
    agent.config = AgentConfig(
        name="test", agent_id="test", workspace_path=workspace
    )
    return agent


class TestAgentManifestProvider:
    """Slice 5: Agent 挂载 skill_manifest_provider，_skill_registry 初始为 None"""

    def test_agent_has_skill_manifest_provider_attribute(self):
        """Agent 实例有 skill_manifest_provider 属性"""
        agent = _make_minimal_agent()
        # 属性存在（property getter 可调用）
        provider = agent.skill_manifest_provider
        assert provider is not None

    def test_skill_manifest_provider_is_correct_type(self):
        """skill_manifest_provider 返回 SkillManifestProvider 实例"""
        agent = _make_minimal_agent()
        provider = agent.skill_manifest_provider
        assert isinstance(provider, SkillManifestProvider)

    def test_skill_manifest_provider_lazy_created(self):
        """首次访问才创建 provider（lazy init）"""
        agent = _make_minimal_agent()
        assert agent._skill_manifest_provider is None  # 初始为 None
        _ = agent.skill_manifest_provider  # 首次访问
        assert agent._skill_manifest_provider is not None  # 已创建

    def test_skill_manifest_provider_cached(self):
        """重复访问返回同一个 provider 实例"""
        agent = _make_minimal_agent()
        p1 = agent.skill_manifest_provider
        p2 = agent.skill_manifest_provider
        assert p1 is p2

    def test_skill_registry_initially_none(self):
        """_skill_registry 初始为 None（未预注册）"""
        agent = _make_minimal_agent()
        # 不访问 skill_registry property（会触发 lazy init），
        # 直接检查内部字段
        assert agent._skill_registry is None


class TestAgentGetSkillManifest:
    """Slice 6: Agent.get_skill_manifest() 按需拉取"""

    def test_get_skill_manifest_returns_list(self):
        """get_skill_manifest() 返回列表"""
        agent = _make_minimal_agent()
        manifests = agent.get_skill_manifest()
        assert isinstance(manifests, list)

    def test_get_skill_manifest_returns_entries(self):
        """get_skill_manifest() 返回 SkillManifestEntry 列表"""
        agent = _make_minimal_agent()
        manifests = agent.get_skill_manifest()
        assert len(manifests) > 0
        for m in manifests:
            assert isinstance(m, SkillManifestEntry)

    def test_get_skill_manifest_delegates_to_provider(self):
        """get_skill_manifest() 委托给 skill_manifest_provider"""
        agent = _make_minimal_agent()
        # 注入一个 mock provider 验证委托
        mock_provider = MagicMock()
        expected = [SkillManifestEntry(id="test_skill", name="Test")]
        mock_provider.list_manifests.return_value = expected
        agent.skill_manifest_provider = mock_provider

        result = agent.get_skill_manifest()
        assert result == expected
        mock_provider.list_manifests.assert_called_once()

    def test_get_skill_manifest_caches_via_provider(self):
        """get_skill_manifest() 重复调用只拉取一次（provider 层缓存）"""
        agent = _make_minimal_agent()
        # 用真实 provider + counting source 验证缓存穿透到 source 层
        source = _CountingSource(
            [SkillManifestEntry(id="test_skill", name="Test")]
        )
        agent.skill_manifest_provider = SkillManifestProvider(sources=[source])

        agent.get_skill_manifest()
        agent.get_skill_manifest()
        agent.get_skill_manifest()
        # source 的 list_manifests 应只被调用一次（provider 内部缓存）
        assert source.call_count == 1


class TestAgentLoadSkill:
    """Slice 7: Agent.load_skill(id) 按需实例化 + 缓存"""

    def test_load_skill_with_factory_returns_instance(self):
        """load_skill 用注入的 factory 实例化 skill"""
        agent = _make_minimal_agent()

        # factory 是一个 callable，返回一个 mock skill 实例
        mock_skill = MagicMock(name="MemorySkill instance")
        factory_call_count = [0]

        def factory(agent=None):
            factory_call_count[0] += 1
            return mock_skill

        result = agent.load_skill("memory", factory=factory)
        assert result is mock_skill
        assert factory_call_count[0] == 1

    def test_load_skill_caches_instance(self):
        """重复 load_skill 同一 id 只调用 factory 一次"""
        agent = _make_minimal_agent()

        factory_call_count = [0]

        def factory(agent=None):
            factory_call_count[0] += 1
            return MagicMock(name="skill")

        agent.load_skill("memory", factory=factory)
        agent.load_skill("memory", factory=factory)  # 应命中缓存
        agent.load_skill("memory", factory=factory)  # 应命中缓存

        assert factory_call_count[0] == 1  # factory 只调用一次

    def test_load_skill_different_ids_instantiate_separately(self):
        """不同 id 的 skill 分别实例化"""
        agent = _make_minimal_agent()

        call_log = []

        def factory(skill_id, agent=None):
            call_log.append(skill_id)
            return MagicMock(name=f"skill_{skill_id}")

        # 用闭包包装，让 factory 能拿到 skill_id
        agent.load_skill("memory", factory=lambda agent=None: factory("memory", agent))
        agent.load_skill("web_search", factory=lambda agent=None: factory("web_search", agent))

        assert call_log == ["memory", "web_search"]
        # 两个 id 各自缓存
        assert "memory" in agent._loaded_skills
        assert "web_search" in agent._loaded_skills

    def test_load_skill_nonexistent_returns_none(self):
        """load_skill 不存在的 id（无 factory）返回 None"""
        agent = _make_minimal_agent()
        # 不提供 factory，且 _loaded_skills 为空
        result = agent.load_skill("nonexistent")
        assert result is None

    def test_load_skill_returns_cached_without_factory(self):
        """已缓存的 skill，再次 load 不需要 factory 也能返回"""
        agent = _make_minimal_agent()

        mock_skill = MagicMock(name="cached skill")
        # 直接预置缓存
        agent._loaded_skills["memory"] = mock_skill

        # 不传 factory，应命中缓存
        result = agent.load_skill("memory")
        assert result is mock_skill


class TestSkillRegistryLazyInit:
    """Slice 8: _skill_registry lazy init（兼容层）"""

    def test_skill_registry_lazy_init_when_none(self):
        """_skill_registry 为 None 时，访问 skill_registry 触发 lazy init"""
        agent = _make_minimal_agent()
        assert agent._skill_registry is None  # 初始为 None

        # 访问 property 触发 lazy init
        registry = agent.skill_registry
        assert registry is not None
        # lazy init 后内部字段已设置
        assert agent._skill_registry is not None

    def test_skill_registry_lazy_init_cached(self):
        """重复访问 skill_registry 返回同一个实例（缓存）"""
        agent = _make_minimal_agent()
        r1 = agent.skill_registry
        r2 = agent.skill_registry
        assert r1 is r2

    def test_skill_registry_preset_not_overridden(self):
        """_skill_registry 已设置时，property 不触发 lazy init"""
        agent = _make_minimal_agent()
        # 预置一个 mock registry
        mock_registry = MagicMock(name="preset registry")
        agent._skill_registry = mock_registry

        result = agent.skill_registry
        assert result is mock_registry  # 返回预置的，不 lazy init

    def test_skill_registry_lazy_init_populates_default_skills(self):
        """
        lazy init 后 SkillRegistry 包含默认 skill（memory/web_search/file_operation）

        兼容层行为：lazy init 调用 create_default_skills()，保证已有代码
        （router、chat_pipeline 等通过 skill_registry.list_skills() 访问）
        不受影响——只是创建时机从 init_router 延迟到首次 property 访问。
        """
        agent = _make_minimal_agent()
        registry = agent.skill_registry

        # 默认 3 个 skill 应该都注册了
        skill_names = registry.get_skill_names()
        assert "memory" in skill_names
        assert "web_search" in skill_names
        assert "file_operation" in skill_names
