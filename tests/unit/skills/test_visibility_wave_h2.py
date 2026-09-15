"""Wave H-W2 可见装配：轮级 SkillView（agent私+用户私+公共，就近优先遮蔽）

规则（需求 2 落地）：
- 装配 = 三库 manifest 合并：public → user → agent 逐层写入，同名后写遮蔽
  前写（agent > user > public，越私有越具体）；
- 无用户身份（default/system/匿名/后台任务）→ view = agent + public，与现状
  等价（agent 库不变 + 公共库只增可见）；
- 执行链校验：view 在场即"不可见即不可调"（含点名 $mention 与跨用户派发）；
  view 缺席（脚本/评测/旧链路）保持现行为零变化。
"""

import types

import pytest

from neurova.skills import library_service as lib
from neurova.skills.skill_visibility import (
    SkillView,
    build_turn_view,
    resolve_user_key,
)


@pytest.fixture(autouse=True)
def lib_base(tmp_path, monkeypatch):
    monkeypatch.setattr(lib, "_BASE_DIR", tmp_path)
    lib.reset_libraries_for_tests()
    yield tmp_path
    lib.reset_libraries_for_tests()


def _seed(pool, owner, skill_id, description="d", **kw):
    svc = lib.get_library(pool, owner)
    assert svc.register_auto_skill(
        skill_id,
        name=description or skill_id,
        description=description,
        config={"tool_sequence": ["a", "b"], **kw.get("config", {})},
        manifest_source="auto",
        pool_type=pool,
        owner_user_id=owner,
    )
    return svc


# ── 用户键解析 ─────────────────────────────────────────────


def test_resolve_user_key_http_account():
    assert resolve_user_key(user_id="42") == "u:42"


def test_resolve_user_key_system_identities_none():
    for anon in ("", "default", "system", "anonymous", None):
        assert resolve_user_key(user_id=anon) is None


def test_resolve_user_key_channel_namespace():
    assert resolve_user_key(channel_user_id="ou_55", channel="feishu") == "ch:feishu:ou_55"


# ── 合并与遮蔽 ─────────────────────────────────────────────


def test_view_merges_three_libraries():
    _seed("agent", "a1", "own_skill")
    _seed("user", "u:9", "my_skill")
    _seed("public", "", "pub_skill")
    view = build_turn_view("a1", "u:9")
    assert set(view.skills) == {"own_skill", "my_skill", "pub_skill"}
    assert view.skills["own_skill"].pool == "agent"
    assert view.skills["my_skill"].pool == "user"
    assert view.skills["pub_skill"].pool == "public"


def test_nearest_wins_shadow():
    _seed("agent", "a1", "deploy", description="agent 版")
    _seed("user", "u:9", "deploy", description="用户版")
    _seed("public", "", "deploy", description="公共版")
    view = build_turn_view("a1", "u:9")
    assert len(view.skills) == 1
    assert view.skills["deploy"].pool == "agent"


def test_user_absent_excludes_other_users_skills():
    _seed("user", "u:9", "mine")
    _seed("user", "u:10", "theirs")
    view = build_turn_view("a1", "u:9")
    assert "mine" in view.skills
    assert "theirs" not in view.skills, "跨用户私库不得进入视图（需求 2）"


def test_other_agent_absent():
    _seed("agent", "a1", "me")
    _seed("agent", "a2", "other_agent_skill")
    view = build_turn_view("a1", None)
    assert "me" in view.skills and "other_agent_skill" not in view.skills


# ── 质量/信任读数按库 ──────────────────────────────────────


def test_quality_readings_scoped_per_library():
    from neurova.skills.skill_injection import QualityInfo

    svc = _seed("public", "", "pub")
    svc.record_skill_funnel("pub", selections=5, applications=4, completions=1, fallbacks=3)
    view = build_turn_view("a1", None)
    q = view.quality_for("pub")
    assert isinstance(q, QualityInfo) and q.applications == 4
    assert view.quality_for("not_exist") is None


# ── 可调用判定 ─────────────────────────────────────────────


def test_invocable_gate():
    _seed("user", "u:9", "secret_move")
    view = build_turn_view("a1", "u:9")
    assert view.invocable("secret_move") is True
    assert view.invocable("nope") is False
    other = build_turn_view("a1", "u:10")
    assert other.invocable("secret_move") is False


# ── turn_context 快照 ──────────────────────────────────────


def test_turn_view_slot_roundtrip():
    from neurova.core import turn_context

    turn_context.reset_turn_tool_messages()
    assert turn_context.get_turn_skill_view() is None
    tok = turn_context.set_turn_skill_view(SkillView(agent_id="a1"))
    assert turn_context.get_turn_skill_view().agent_id == "a1"
    turn_context.reset_turn_skill_view(tok)
    assert turn_context.get_turn_skill_view() is None
    turn_context.clear_turn_state()


# ── 账本 provenance 供给（执行采集点从 view 取库归属）─────


def test_funnel_entry_gets_provenance_from_view():
    _seed("user", "u:3", "mv")
    from neurova.core import turn_context

    turn_context.reset_turn_tool_messages()
    view = build_turn_view("a1", "u:3")
    tok = turn_context.set_turn_skill_view(view)
    try:
        prov = view.provenance_for("mv")
    finally:
        turn_context.reset_turn_skill_view(tok)
    assert prov == ("user", "u:3")


def test_disabled_entry_excluded():
    svc = _seed("agent", "a1", "off_one")
    svc.disable_skill("off_one")
    view = build_turn_view("a1", None)
    assert "off_one" not in view.skills


def test_registry_builtins_are_visible_base():
    """内置技能不落 manifest——registry 运行时技能必须进视图（否则过滤误伤）。"""
    reg = {"memory_search": types.SimpleNamespace(name="memory_search", description="检索", config={})}
    view = build_turn_view("a1", None, registry_skills=reg)
    assert view.invocable("memory_search") is True
    assert view.skills["memory_search"].pool == "agent"


def test_manifest_entry_overrides_registry_base():
    """同名 manifest 条目（带账本）覆盖 registry 底座条目。"""
    svc = _seed("agent", "a1", "deploy_helper", description="账本版")
    svc.record_skill_funnel("deploy_helper", selections=2, applications=2, completions=2)
    reg = {"deploy_helper": types.SimpleNamespace(name="x", description="运行时壳", config={})}
    view = build_turn_view("a1", None, registry_skills=reg)
    assert view.skills["deploy_helper"].description == "账本版"
    q = view.quality_for("deploy_helper")
    assert q is not None and q.completions == 2


# ── 消费接线：执行门与工具面过滤 ───────────────────────────


@pytest.mark.asyncio
async def test_execute_skill_tool_denies_out_of_view():
    """咽喉执行门：视图外技能即使 registry 有执行体也拒绝且不调用。"""
    from unittest.mock import AsyncMock, MagicMock

    from neurova.core import turn_context
    from neurova.tool_executor import ToolExecutor

    runtime = MagicMock()
    runtime.name = "theirs_secret"
    runtime.config = {}
    registry = MagicMock()
    registry.skills = {"theirs_secret": runtime}
    registry.execute_skill = AsyncMock()
    agent = MagicMock()
    agent._skill_registry = registry
    ex = ToolExecutor(agent)

    turn_context.reset_turn_tool_messages()
    view = build_turn_view("myagent", "u:9")  # 视图不含 theirs_secret
    tok = turn_context.set_turn_skill_view(view)
    try:
        out = await ex.execute_skill_tool("theirs_secret", {})
    finally:
        turn_context.reset_turn_skill_view(tok)
    assert "error" in out
    registry.execute_skill.assert_not_awaited()
    # 被拒不入账（不可见技能不产生账本噪声）
    assert turn_context.get_turn_skill_funnel() == []
    turn_context.clear_turn_state()


@pytest.mark.asyncio
async def test_build_tools_section_filters_by_view():
    """工具面：视图在场时 registry 技能按可见集过滤（视图外不进 schema）。"""
    from unittest.mock import MagicMock

    from neurova.context.orchestrator import _build_tools_for_llm
    from neurova.core import turn_context

    def _sk(name):
        s = MagicMock()
        s.name = name
        s.description = name + " desc"
        s.config = {}
        s._get_parameters.return_value = {}
        return s

    registry = MagicMock()
    registry.skills = {"visible_one": _sk("visible_one"), "hidden_two": _sk("hidden_two")}
    self_mock = MagicMock(spec=[])
    self_mock.config = MagicMock()
    self_mock.skill_registry = registry
    self_mock.tool_router = None

    turn_context.reset_turn_tool_messages()
    view = SkillView(agent_id="a1")
    view.skills["visible_one"] = types.SimpleNamespace(
        name="visible_one", skill_id="visible_one", pool="agent", owner_key="a1",
        entry={"enabled": True, "description": "d", "manifest": {"config": {}}},
    )
    tok = turn_context.set_turn_skill_view(view)
    try:
        tools = await _build_tools_for_llm(self_mock)
    finally:
        turn_context.reset_turn_skill_view(tok)
    names = {t["function"]["name"] for t in tools or []}
    assert "visible_one" in names
    assert "hidden_two" not in names, "视图外技能不得进 function schema"
    turn_context.clear_turn_state()


# ── V 轮执行桥（需求 2：可见且可调用，修复"可见但不可执行"断点）────


def test_restore_library_skills_for_turn_bridges_user_and_public(lib_base):
    from neurova.skill_system import SkillRegistry

    from neurova.skills.market_registry import restore_library_skills_for_turn

    _seed("user", "u:7", "csv_report")
    _seed("public", "", "shared_tool")
    _seed("agent", "a1", "own_tool")  # agent 层归启动恢复管，桥不越权
    lib.get_library("user", "u:7").register_auto_skill(
        "meta_only", name="元目", config={}, manifest_source="user"
    )
    reg = SkillRegistry()
    view = build_turn_view("a1", "u:7", registry_skills=dict(reg.skills))
    n = restore_library_skills_for_turn(reg, view)
    assert n == 2, "仅用户库/公共库的 tool_sequence 条目物化"
    assert "csv_report" in reg.skills and "shared_tool" in reg.skills
    assert "meta_only" not in reg.skills, "元目类条目不物化成空壳"
    assert "own_tool" not in reg.skills, "agent 层条目不进桥"
    assert restore_library_skills_for_turn(reg, view) == 0, "幂等：二次调用零副作用"
    # 视图可调用面与执行池对齐（桥后 invocable ⇒ registry 可解析）
    assert view.invocable("csv_report") and reg.skills.get("csv_report") is not None
