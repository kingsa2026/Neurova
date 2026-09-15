"""Wave F：DiscoverSkills 元数据工具 + replay 种子采集器

② discover_skills（builtin_tools schema + tool_executor 执行体 + governance
failopen 白名单三处接线）：目录/预算裁剪后模型的主动发现通道，对齐

③ collect_warm_seeds_from_patterns：AutoSkillBuilder ToolPattern → A/B warm
种子（独立成功源 ≥2 才入种子——回声室红线；sanitize 白名单结构性剥答案）。
"""

import asyncio
import types

import pytest

from neurova.skills.skill_injection import QualityInfo  # noqa: F401 - 兼容导入面

# ── ② discover_skills 接线 ─────────────────────────────────


def test_discover_skills_schema_registered():
    from neurova.builtin_tools import get_builtin_tool_params

    schema = get_builtin_tool_params("discover_skills")
    assert schema is not None, "discover_skills 必须进 _BUILTIN_SCHEMAS 单一事实源"
    props = schema["parameters"]["properties"]
    assert "query" in props and "limit" in props
    assert schema["parameters"]["required"] == ["query"]


def test_discover_skills_dispatch_and_failopen():
    from neurova.tool_executor import ToolExecutor

    assert ToolExecutor._builtin_dispatch.get("discover_skills") == "_execute_discover_skills"
    assert "discover_skills" in ToolExecutor._GOVERNANCE_FAILOPEN_READONLY_TOOLS
    assert hasattr(ToolExecutor, "_execute_discover_skills")


def _make_executor(skills):
    """skills: {name: Skill-like}；返回 (executor, registry)。"""
    from unittest.mock import AsyncMock, MagicMock

    from neurova.tool_executor import ToolExecutor

    registry = MagicMock()
    registry.skills = skills
    registry.execute_skill = AsyncMock()
    agent = MagicMock()
    agent._skill_registry = registry
    executor = ToolExecutor(agent)
    return executor, registry


def _skill(name, description):
    from neurova.skills.models import Skill, SkillSource

    return Skill(
        id=name, name=name, version="1.0.0", description=description,
        source=SkillSource.LOCAL, enabled=True, config={},
    )


@pytest.mark.asyncio
async def test_discover_returns_metadata_never_body():
    from neurova.core import turn_context

    turn_context.reset_turn_tool_messages()
    executor, _ = _make_executor(
        {
            "pdf-converter": _skill("pdf-converter", "把扫描文档转换成 PDF"),
            "music-box": _skill("music-box", "播放无损音乐"),
        }
    )
    out = await executor._execute_discover_skills({"query": "pdf 转换"})
    assert out["results"], "词面命中必须返回候选"
    first = out["results"][0]
    assert first["name"] == "pdf-converter"
    assert first["how_to_invoke"] == "$pdf-converter"
    assert "description" in first and "config" not in first
    # 渐进披露红线：正文/指令体字段绝不出现
    assert not any(k in first for k in ("body", "doc_text", "skill_md", "content"))
    # "music-box" 不该在 pdf 查询里排前面
    assert out["results"][0]["name"] == "pdf-converter"


@pytest.mark.asyncio
async def test_discover_zero_match_honest_empty():
    executor, _ = _make_executor({"a": _skill("a", "天气查询")})
    out = await executor._execute_discover_skills({"query": "完全不搭界zzz"})
    assert out["results"] == []
    assert "无匹配" in out["note"]


@pytest.mark.asyncio
async def test_discover_limit_and_skip_non_invocable():
    skills = {f"s{i}": _skill(f"s{i}", f"pdf 工具 {i}") for i in range(8)}
    skills["hidden"] = _skill("hidden", "pdf 隐蔽")
    skills["hidden"].config = {"model_invocable": False}
    executor, _ = _make_executor(skills)
    out = await executor._execute_discover_skills({"query": "pdf", "limit": 3})
    names = [r["name"] for r in out["results"]]
    assert len(names) == 3
    assert "hidden" not in names


@pytest.mark.asyncio
async def test_discover_requires_query():
    executor, _ = _make_executor({})
    assert "error" in await executor._execute_discover_skills({})


@pytest.mark.asyncio
async def test_discover_no_registry_degrades():
    from unittest.mock import MagicMock

    from neurova.tool_executor import ToolExecutor

    agent = MagicMock()
    agent._skill_registry = None
    executor = ToolExecutor(agent)
    out = await executor._execute_discover_skills({"query": "x"})
    assert out["results"] == []


# ── ③ 种子采集器 ───────────────────────────────────────────


def _pattern(seq=("web_search", "file_write"), keywords=("查", "写"), evidence=None):
    return types.SimpleNamespace(
        tool_sequence=list(seq),
        context_keywords=list(keywords),
        source_evidence=evidence if evidence is not None else {"t1": "s", "t2": "s"},
    )


def test_collect_seeds_requires_independent_evidence():
    from neurova.evolution.eval.ab_library import collect_warm_seeds_from_patterns

    good = _pattern()
    single = _pattern(seq=("a", "b"), evidence={"only-task": "s"})
    failed = _pattern(seq=("c", "d"), evidence={"t1": "f", "t2": "f"})
    seeds = collect_warm_seeds_from_patterns([good, single, failed])
    assert len(seeds) == 1
    assert seeds[0]["tool_sequence"] == ["web_search", "file_write"]


def test_collect_seeds_never_carry_answer_keys():
    from neurova.evolution.eval.ab_library import collect_warm_seeds_from_patterns

    seeds = collect_warm_seeds_from_patterns([_pattern()])
    flat = repr(seeds)
    for marker in ("verifier", "reward", "expected", "acceptance"):
        assert marker not in flat


def test_collect_seeds_short_seq_excluded():
    from neurova.evolution.eval.ab_library import collect_warm_seeds_from_patterns

    assert collect_warm_seeds_from_patterns([_pattern(seq=("one",))]) == []


def test_collect_seeds_empty_input_safe():
    from neurova.evolution.eval.ab_library import collect_warm_seeds_from_patterns

    assert collect_warm_seeds_from_patterns([]) == []
    assert collect_warm_seeds_from_patterns(None) == []
