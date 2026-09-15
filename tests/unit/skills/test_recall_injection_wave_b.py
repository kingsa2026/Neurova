"""Wave B 召回注入（OpenSpace 对比 P0-3/P2-2/P2-5）

三件套（互补，默认关闭/无 paths=零行为变化，满足增量原则）：
- P0-3 render_skill_catalog 从死接线变成有消费方：orchestrator 单源
  `_skill_catalog_section()`（描述 250 字上限/超预算别名压缩/行数上限+未列提示）；
- P2-2 select_skills_for_turn 阶梯：≤max 全量（现状）；>max 时精确名必进 +
  关键词打分 top-k；零命中回退全量（可用性优先，宁全不缺）；
- P2-5 config.paths glob：设定即条件激活（输入未触及路径 → 不进目录/工具面），
  未设定行为与今日完全一致。
"""

import types

from neurova.skills.skill_injection import (
    match_skill_paths,
    render_skill_catalog,
    score_skill_for_query,
    select_skills_for_turn,
)


class _Skill:
    def __init__(self, name, description="", config=None, enabled=True):
        self.name = name
        self.description = description
        self.config = config or {}
        self.enabled = enabled


class _Registry:
    def __init__(self, skills):
        self.skills = skills


# ── P0-3 目录渲染预算 ───────────────────────────────────────


def test_catalog_lists_name_and_description():
    reg = _Registry({"web-search": _Skill("web-search", "搜索互联网获取实时信息")})
    text = render_skill_catalog(reg, max_chars=8000)
    assert "- web-search" in text
    assert "搜索互联网" in text


def test_catalog_description_capped_250():
    reg = _Registry({"a": _Skill("a", "x" * 600)})
    text = render_skill_catalog(reg, max_chars=8000)
    line = next(ln for ln in text.splitlines() if ln.startswith("- a"))
    assert len(line) <= 10 + 250, "描述须截到 250 字符（OpenSpace MAX_LISTING_DESC_CHARS）"


def test_catalog_over_budget_compresses_to_names():
    reg = _Registry({f"s{i}": _Skill(f"s{i}", "y" * 200) for i in range(50)})
    text = render_skill_catalog(reg, max_chars=300)
    assert "- s1" in text
    assert "yyy" not in text, "超预算必须别名压缩（丢描述保名字）"


def test_catalog_row_cap_with_hint():
    reg = _Registry({f"s{i}": _Skill(f"s{i}", "d") for i in range(50)})
    text = render_skill_catalog(reg, max_chars=8000, max_lines=30)
    assert "- s29" in text
    assert "- s30" not in text
    assert "还有 20 个技能" in text, "必须提示未列数与发现途径"


def test_catalog_empty_inputs():
    assert render_skill_catalog(_Registry({}), max_chars=8000) == ""
    assert render_skill_catalog(None, max_chars=8000) == ""


def test_catalog_skips_disabled_and_non_invocable():
    reg = _Registry(
        {
            "on1": _Skill("on1", "d1"),
            "off2": _Skill("off2", "d2", config={"model_invocable": False}),
            "dis3": _Skill("dis3", "d3", enabled=False),
        }
    )
    text = render_skill_catalog(reg, max_chars=8000)
    assert "- on1" in text
    assert "- off2" not in text, "model_invocable=False 不进模型目录"
    assert "- dis3" not in text, "禁用技能不进模型目录"


def test_catalog_inactive_paths_skill_skipped():
    reg = _Registry({"py": _Skill("py", "python 工具", config={"paths": ["*.py"]})})
    assert render_skill_catalog(reg, max_chars=8000, user_input="写首诗") == ""
    text = render_skill_catalog(reg, max_chars=8000, user_input="改 app.py")
    assert "- py" in text


# ── P2-2 阶梯检索 ──────────────────────────────────────────


def test_select_under_budget_returns_all_in_order():
    skills = {f"s{i}": _Skill(f"s{i}", "d") for i in range(5)}
    picked = select_skills_for_turn(skills, "随便聊聊", max_skills=20)
    assert picked == list(skills.keys())


def test_select_exact_name_always_in():
    skills = {f"s{i}": _Skill(f"s{i}", "无关描述") for i in range(25)}
    skills["deploy"] = _Skill("deploy", "部署")
    picked = select_skills_for_turn(skills, "帮我 deploy 一下", max_skills=10)
    assert "deploy" in picked
    assert len(picked) <= 10


def test_score_prefers_keyword_overlap():
    pdf = _Skill("pdf-tool", "转换 PDF 文档")
    music = _Skill("music", "播放音乐")
    assert score_skill_for_query(pdf, "把 pdf 转成文档") > score_skill_for_query(
        music, "把 pdf 转成文档"
    )


def test_score_quality_micro_adjust():
    """质量微调（OpenSpace +min(completions,5)*0.05 − min(fallbacks,5)*0.05 同源）。"""
    a = _Skill("good", "deploy 部署")
    b = _Skill("bad", "deploy 部署")
    sa = score_skill_for_query(a, "deploy 部署", quality={"completions": 5, "fallbacks": 0})
    sb = score_skill_for_query(b, "deploy 部署", quality={"completions": 0, "fallbacks": 5})
    assert sa > sb


def test_select_zero_match_falls_back_full():
    """零命中必须回退全量——宁可全而不缺（不可让模型瞎掉所有技能）。"""
    skills = {f"s{i}": _Skill(f"s{i}", "d") for i in range(25)}
    picked = select_skills_for_turn(skills, "xyzzy nothing", max_skills=10)
    assert set(picked) == set(skills.keys())


def test_select_excludes_inactive_paths_skills():
    skills = {
        "hidden": _Skill("hidden", "pdf 工具", config={"paths": ["*.pdf"]}),
        "open": _Skill("open", "pdf 转换"),
    }
    picked = select_skills_for_turn(skills, "处理 pdf 文件", max_skills=20)
    assert "open" in picked
    assert "hidden" not in picked


# ── P2-5 paths 条件激活 ────────────────────────────────────


def test_paths_unset_always_active():
    assert match_skill_paths(_Skill("a"), "anything") is True
    assert match_skill_paths(_Skill("a", config={}), "anything") is True


def test_paths_glob_match_on_input():
    skill = _Skill("py", config={"paths": ["*.py"]})
    assert match_skill_paths(skill, "帮我修一下 app.py 的 bug") is True


def test_paths_no_match_inactive():
    skill = _Skill("py", config={"paths": ["*.py", "src/**"]})
    assert match_skill_paths(skill, "今天天气怎么样") is False


def test_paths_exact_token_match():
    skill = _Skill("docker", config={"paths": ["docker-compose.yml"]})
    assert match_skill_paths(skill, "更新 docker-compose.yml 配置") is True


# ── orchestrator 接线（单源 helper，仿 _workspace_docs_section 契约）───


def _catalog_section(config_enabled, skills=None, budget=8000):
    from neurova.context.orchestrator import ContextOrchestrator

    class _Cfg:
        skill_catalog_enabled = config_enabled
        skill_catalog_budget_chars = budget

    stub = types.SimpleNamespace(config=_Cfg(), skill_registry=_Registry(skills or {}))
    stub._resolve_recall_flag = types.MethodType(ContextOrchestrator._resolve_recall_flag, stub)
    return types.MethodType(ContextOrchestrator._skill_catalog_section, stub)()


def test_catalog_section_disabled_zero_injection():
    assert _catalog_section(False, {"a": _Skill("a", "d")}) == ""


def test_catalog_section_enabled_injects():
    text = _catalog_section(True, {"web-search": _Skill("web-search", "搜索")})
    assert "可用技能目录" in text
    assert "- web-search" in text


def test_catalog_section_none_registry_safe():
    import types as _t

    from neurova.context.orchestrator import ContextOrchestrator

    class _Cfg:
        skill_catalog_enabled = True
        skill_catalog_budget_chars = 8000

    stub = _t.SimpleNamespace(config=_Cfg(), skill_registry=None)
    stub._resolve_recall_flag = _t.MethodType(ContextOrchestrator._resolve_recall_flag, stub)
    assert _t.MethodType(ContextOrchestrator._skill_catalog_section, stub)() == ""
