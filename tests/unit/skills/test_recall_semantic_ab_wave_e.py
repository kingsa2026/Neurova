"""Wave E：召回闭环（语义档+熔断+目录标注）+ skills_off A/B 接线 + 开关三级

- §2.5 trust/质量的召回消费面：高 fallback / 零完成技能在阶梯预算中被熔断
；目录对 provisional 打标（软信号，
  同它 listing 里 "(provisional; success 3/5)" 的语义）；
- §2.4 检索阶梯补 embedding 档：keyword→semantic 混合打分；向量缓存以
 **内容哈希为键**；
- P2-4 replay 接线：turn 级 skills_off 上下文 + make_agent_ab_executor
  （cold 臂=技能库对模型不可见：schema 与目录同时缺席；warm=正常）；
- A6 tool_search 开关三级化：env 显式 > app_settings（新增 tool_search_enabled，
  默认 True=现状）> True。
"""

import types

import pytest

from neurova.core import turn_context
from neurova.skills.skill_injection import (
    QualityInfo,
    render_skill_catalog,
    select_skills_for_turn,
)


class _Skill:
    def __init__(self, name, description="", config=None):
        self.name = name
        self.description = description
        self.config = config or {}


# ── 1. 质量熔断（select_skills_for_turn 的 quality_lookup）───


def _q(applications=0, completions=0, fallbacks=0):
    return QualityInfo(applications=applications, completions=completions, fallbacks=fallbacks)


def test_quality_excludes_chronic_fallback():
    """applications>=2 且 fallback 率>0.5 → 熔断出局。"""
    skills = {n: _Skill(n, "pdf 工具") for n in ("good", "bad")}
    lookup = {"bad": _q(applications=3, completions=1, fallbacks=2)}
    picked = select_skills_for_turn(
        skills, "处理 pdf", max_skills=20, quality_lookup=lookup.get
    )
    assert picked == ["good"]


def test_quality_excludes_zero_completion():
    skills = {n: _Skill(n, "pdf 工具") for n in ("ok", "never_done")}
    lookup = {"never_done": _q(applications=2, completions=0, fallbacks=2)}
    picked = select_skills_for_turn(
        skills, "pdf", max_skills=20, quality_lookup=lookup.get
    )
    assert "never_done" not in picked


def test_quality_no_data_keeps_skill():
    """无质量数据 = 不熔断（增量不下降：新键冷启动零误杀）。"""
    skills = {"a": _Skill("a", "pdf 工具")}
    picked = select_skills_for_turn(
        skills, "pdf", max_skills=20, quality_lookup=lambda n: None
    )
    assert picked == ["a"]


def test_quality_below_sample_floor_exempt():
    """1 次观测不足样本（对齐 P2-3 小样本免疫精神）。"""
    skills = {n: _Skill(n, "pdf") for n in ("a", "b")}
    picked = select_skills_for_turn(
        skills, "pdf", max_skills=20, quality_lookup={"b": _q(applications=1, fallbacks=1)}.get
    )
    assert "b" in picked


# ── 2. 语义档混合打分 ──────────────────────────────────────


def test_semantic_lifts_relevant_skill():
    skills = {
        "shipper": _Skill("shipper", "物流相关"),
        "music": _Skill("music", "播放"),
    }
    # keyword 都为 0（输入无词面交集）；预算 1 激活阶梯淘汰，semantic 只认可 shipper
    semantic = {"shipper": 0.71, "music": 0.05}
    picked = select_skills_for_turn(
        skills, "帮我发个包裹", max_skills=1, semantic_scores=semantic
    )
    assert "shipper" in picked
    # 有语义命中 → 不触发"零命中回退全量"，弱相关（<floor）的 music 出局
    assert "music" not in picked


def test_semantic_within_cap_reorders_not_excludes():
    """预算内语义不淘汰技能（宁可全而不缺）——只影响排序。"""
    skills = {"a": _Skill("a", "x"), "b": _Skill("b", "x")}
    picked = select_skills_for_turn(
        skills, "无交集输入", max_skills=20, semantic_scores={"a": 0.9}
    )
    assert set(picked) == {"a", "b"}


def test_semantic_none_keeps_pure_keyword_behavior():
    skills = {"a": _Skill("a", "pdf 转换")}
    assert select_skills_for_turn(skills, "pdf", max_skills=20) == ["a"]


def test_semantic_respects_quality_circuit_first():
    """熔断先于排序：被熔断的语义最优者也不得进。"""
    skills = {"good": _Skill("good", "x"), "burned": _Skill("burned", "x")}
    picked = select_skills_for_turn(
        skills,
        "无关输入zz",
        max_skills=20,
        semantic_scores={"burned": 0.9, "good": 0.1},
        quality_lookup=lambda n: _q(applications=4, completions=0, fallbacks=4) if n == "burned" else None,
    )
    assert "burned" not in picked


# ── 3. 目录 provisional 标注 ───────────────────────────────


def test_catalog_annotates_provisional():
    reg = types.SimpleNamespace(
        skills={
            "auto1": _Skill("auto1", "自动封装"),
            "imp": _Skill("imp", "导入"),
        }
    )
    trust = {"auto1": "provisional", "imp": "trusted"}
    text = render_skill_catalog(reg, max_chars=8000, trust_lookup=trust.get)
    assert text.count("(provisional)") == 1
    assert "auto1 —" in text and "imp —" in text


def test_catalog_no_trust_lookup_zero_change():
    reg = types.SimpleNamespace(skills={"a": _Skill("a", "d")})
    assert "(provisional)" not in render_skill_catalog(reg, max_chars=8000)


# ── 4. 向量缓存：内容哈希键 + 持久化 ───────────────────────


def test_vector_cache_recomputes_on_content_change(tmp_path):
    from neurova.skills.skill_semantics import SkillVectorCache

    class _FakeEngine:
        def __init__(self):
            self.calls = []

        def is_initialized(self):
            return True

        def encode(self, text):
            self.calls.append(text)
            return [float(len(text) % 7), 1.0]

    eng = _FakeEngine()
    cache = SkillVectorCache(eng, cache_file=tmp_path / "emb.json")
    s = _Skill("a", "第一版描述")
    v1 = cache.vectors_for({"a": s})["a"]
    assert v1 and eng.calls == ["a\n\n第一版描述"]
    # 内容不变 → 命中缓存不重编码
    cache.vectors_for({"a": _Skill("a", "第一版描述")})
    assert len(eng.calls) == 1
    # 内容变 → 哈希失配重编码
    cache.vectors_for({"a": _Skill("a", "第二版描述")})
    assert len(eng.calls) == 2
    # 重启可复用（持久化 + 哈希键）
    cache2 = SkillVectorCache(_FakeEngine(), cache_file=tmp_path / "emb.json")
    cache2.engine.calls = []
    v = cache2.vectors_for({"a": _Skill("a", "第二版描述")})
    assert v["a"] == v1 or len(cache2.engine.calls) == 0  # 命中即零调用
    assert cache2.engine.calls == []


def test_vector_cache_engine_none_graceful(tmp_path):
    from neurova.skills.skill_semantics import SkillVectorCache

    cache = SkillVectorCache(None, cache_file=tmp_path / "e.json")
    assert cache.vectors_for({"a": _Skill("a", "d")}) == {}


def test_vector_cache_zero_vector_not_trusted(tmp_path):
    """引擎失败会返回零向量——不得投毒缓存/参与排序。"""
    from neurova.skills.skill_semantics import SkillVectorCache

    class _BoomEngine:
        def is_initialized(self):
            return True

        def encode(self, text):
            return [0.0, 0.0]

    cache = SkillVectorCache(_BoomEngine(), cache_file=tmp_path / "z.json")
    assert cache.vectors_for({"a": _Skill("a", "d")}) == {}


# ── 5. turn 级 skills_off 上下文 ───────────────────────────


def test_skills_off_context_roundtrip():
    turn_context.reset_turn_tool_messages()
    assert turn_context.get_turn_skills_off() is False
    tok = turn_context.set_turn_skills_off(True)
    assert turn_context.get_turn_skills_off() is True
    turn_context.reset_turn_skills_off(tok)
    assert turn_context.get_turn_skills_off() is False
    turn_context.clear_turn_state()


def _catalog_section(stub_extra=None):
    from neurova.context.orchestrator import ContextOrchestrator

    class _Cfg:
        skill_catalog_enabled = True
        skill_catalog_budget_chars = 8000

    reg = types.SimpleNamespace(skills={"a": _Skill("a", "d")})
    stub = types.SimpleNamespace(config=_Cfg(), skill_registry=reg)
    stub._resolve_recall_flag = types.MethodType(ContextOrchestrator._resolve_recall_flag, stub)
    if stub_extra:
        for k, v in stub_extra.items():
            setattr(stub, k, types.MethodType(v, stub))
    return types.MethodType(ContextOrchestrator._skill_catalog_section, stub)()


def test_catalog_section_empty_when_skills_off():
    turn_context.reset_turn_tool_messages()
    tok = turn_context.set_turn_skills_off(True)
    try:
        assert _catalog_section() == ""
    finally:
        turn_context.reset_turn_skills_off(tok)


def test_catalog_section_normal_when_not_off():
    turn_context.reset_turn_tool_messages()
    assert "可用技能目录" in _catalog_section()


@pytest.mark.asyncio
async def test_build_tools_skips_skills_when_off():
    from unittest.mock import AsyncMock, MagicMock

    from neurova.skill_system import SkillResult  # noqa: F401  (注册表替身契约同款)
    from neurova.tool_executor import ToolExecutor  # noqa: F401 - 保 import 顺序稳定

    from neurova.context.orchestrator import _build_tools_for_llm

    skill = MagicMock()
    skill.name = "normal_skill"
    skill.description = "d"
    skill.config = {}
    skill._get_parameters.return_value = {}
    registry = MagicMock()
    registry.skills = {"normal_skill": (skill, None)}

    self_mock = MagicMock(spec=[])
    self_mock.config = MagicMock()
    self_mock.skill_registry = registry
    self_mock.tool_router = None

    turn_context.reset_turn_tool_messages()
    tools = await _build_tools_for_llm(self_mock)
    assert any(t["function"]["name"] == "normal_skill" for t in tools or [])

    tok = turn_context.set_turn_skills_off(True)
    try:
        tools_off = await _build_tools_for_llm(self_mock)
    finally:
        turn_context.reset_turn_skills_off(tok)
    names = [t["function"]["name"] for t in tools_off or []]
    assert "normal_skill" not in names


# ── 6. A/B 执行器适配器 ────────────────────────────────────


@pytest.mark.asyncio
async def test_make_agent_ab_executor_toggles_skills_off_per_arm():
    from neurova.evolution.eval.ab_library import make_agent_ab_executor

    seen = []

    class _Res:
        response = "ok answer"

    class _Agent:
        async def process_message(self, text, sender="user"):
            seen.append({"text": text, "skills_off": turn_context.get_turn_skills_off()})
            return _Res()

    executor = make_agent_ab_executor(_Agent())
    out = await executor("任务一", skills_enabled=True)
    assert out == "ok answer"
    assert seen[0]["skills_off"] is False
    await executor("任务一", skills_enabled=False)
    assert seen[1]["skills_off"] is True
    # 离开后上下文已复位
    assert turn_context.get_turn_skills_off() is False


@pytest.mark.asyncio
async def test_ab_executor_warm_only_seed_note():
    from neurova.evolution.eval.ab_library import make_agent_ab_executor

    seen = []

    class _Res:
        response = "r"

    class _Agent:
        async def process_message(self, text, sender="user"):
            seen.append(text)
            return _Res()

    executor = make_agent_ab_executor(_Agent())
    seed = {"task_input": "t", "tool_sequence": ["web_search", "file_write"]}
    await executor("任务", skills_enabled=True, seed=seed)
    assert "web_search" in seen[-1]
    await executor("任务", skills_enabled=False, seed=seed)
    assert "web_search" not in seen[-1]


@pytest.mark.asyncio
async def test_ab_executor_feeds_cold_warm_pipeline():
    """端到端：harness 双臂跑通（cold 全败 / warm 全过 → delta=1）。"""
    from neurova.evolution.eval.ab_library import make_agent_ab_executor, run_cold_warm_ab

    class _Res:
        def __init__(self, r):
            self.response = r

    class _Agent:
        async def process_message(self, text, sender="user"):
            # 技能库开着才会做对
            return _Res("done: pdf ok" if not turn_context.get_turn_skills_off() else "cannot")

    executor = make_agent_ab_executor(_Agent())
    cases = [{"task_input": f"转 pdf {i}", "expected": "ok"} for i in range(3)]
    report = await run_cold_warm_ab(cases, executor)
    assert report["cold_pass_rate"] == 0.0
    assert report["warm_pass_rate"] == 1.0
    assert len(report["fixed"]) == 3


# ── 7. tool_search 开关三级化 ──────────────────────────────


def test_tool_search_enabled_default_on(monkeypatch, tmp_path):
    from neurova.context.tool_search import tool_search_enabled
    from neurova.core import app_settings as appset

    monkeypatch.delenv("NEUROVA_TOOL_SEARCH", raising=False)
    monkeypatch.setattr(appset, "_settings_path", lambda p=None: tmp_path / "s.json")
    assert tool_search_enabled() is True


def test_tool_search_enabled_env_off_wins(monkeypatch, tmp_path):
    from neurova.context.tool_search import tool_search_enabled
    from neurova.core import app_settings as appset

    monkeypatch.setenv("NEUROVA_TOOL_SEARCH", "0")
    monkeypatch.setattr(appset, "_settings_path", lambda p=None: tmp_path / "s.json")
    assert tool_search_enabled() is False


def test_tool_search_enabled_settings_off_without_env(monkeypatch, tmp_path):
    from neurova.context.tool_search import tool_search_enabled
    from neurova.core import app_settings as appset

    monkeypatch.delenv("NEUROVA_TOOL_SEARCH", raising=False)
    path = tmp_path / "s.json"
    appset.save_app_settings("advanced", {"tool_search_enabled": False}, path=path)
    monkeypatch.setattr(appset, "_settings_path", lambda p=None: path)
    assert tool_search_enabled() is False
