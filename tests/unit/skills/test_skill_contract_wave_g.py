"""Wave G：技能契约归一（SkillCore + resolve_skill_identity 单源）

立项动机：三套技能模型
（skill_system.Skill 运行时基类 / skills.models.Skill dataclass /
skill_system/skill_pool_manager.SkillMetadata，已退役 2026-09-15）身份字段各异
（skill_id/id/name），全库以三跳 getattr 链缝合——且链的次序在两处消费方
**互相矛盾**（agent_core/tool_executor 取 skill_id 优先，
api/endpoints/skill.py 取 id 优先）：同一对象在工具面/漏斗与 API 展示面
可以拿到不同身份，正是"下一场契约漂移"的活体样本。

纪律：
- resolve_skill_identity 单源，规范次序 skill_id → id → name → fallback
  （与记账面 post_execute/funnel 对齐——API 显示向账本看齐）；
- register() 注册即归一化（canonicalize：无 skill_id 的运行时对象补写），
  下游单跳命中；已有 skill_id 永不覆写；
- 三跳链只允许活在 skill_contract 内：静态守卫测试扫全库。
"""

import inspect
import re
from pathlib import Path

import pytest

from neurova.skills.skill_contract import SkillCore, canonicalize_skill_identity, resolve_skill_identity

NEUROVA_PKG = Path(__file__).resolve().parents[3] / "neurova"

# 规范次序：skill_id → id → name → fallback


def test_resolver_precedence_skill_id_first():
    class _Both:
        skill_id = "ledger-id"
        id = "display-id"
        name = "tool-name"

    assert resolve_skill_identity(_Both()) == "ledger-id"


def test_resolver_id_then_name():
    from neurova.skills.models import Skill, SkillSource

    m = Skill(id="m1", name="m1-name", source=SkillSource.LOCAL)
    assert resolve_skill_identity(m) == "m1"

    class _NameOnly:
        name = "runtime-skill"

    assert resolve_skill_identity(_NameOnly()) == "runtime-skill"


def test_resolver_tuple_unwrap_and_dict():
    class _S:
        skill_id = "inner"

    assert resolve_skill_identity((_S(), Path("/x"))) == "inner"
    assert resolve_skill_identity({"skill_id": "s1", "id": "x"}) == "s1"
    assert resolve_skill_identity({"id": "x1", "name": "n"}) == "x1"
    assert resolve_skill_identity({"name": "n1"}) == "n1"


def test_resolver_fallbacks_and_garbage():
    assert resolve_skill_identity(None, fallback="fb") == "fb"
    assert resolve_skill_identity("", fallback="fb") == "fb"
    assert resolve_skill_identity(123, fallback="fb") == "fb"  # 非字符串字段值不炸
    assert resolve_skill_identity(object(), fallback="") == ""
    # 空白串字段视同缺失
    class _Blank:
        skill_id = "  "
        id = ""
        name = "real"

    assert resolve_skill_identity(_Blank()) == "real"


# ── 三套模型 + pool 元数据全部符合 SkillCore ───────────────


def test_all_three_models_resolve_via_resolver():
    """模型/条目形态的取值全部经单源解析器归一（协议成员存在性另测）。

    原第三形态 SkillMetadata（skill_pool_manager 孤岛）2026-09-15 退役——
    以 pool 条目 dict 形态顶替样本位（skill_id 键分支覆盖不减弱）。
    """
    from neurova.skill_system import Skill as RuntimeSkill
    from neurova.skills.models import Skill, SkillSource

    cases = [
        (Skill(id="m", name="m", source=SkillSource.LOCAL), "m"),
        (RuntimeSkill(name="rt"), "rt"),
        ({"skill_id": "pm", "name": "pool-meta-dict"}, "pm"),
    ]
    for obj, expect in cases:
        assert resolve_skill_identity(obj) == expect


def test_runtime_checkable_protocol():
    class _Bad:
        pass

    assert not isinstance(_Bad(), SkillCore)


# ── G-2 注册边界单源化 ─────────────────────────────────────


def test_register_canonicalizes_skill_id():
    from neurova.skill_system import Skill as RuntimeSkill
    from neurova.skill_system import SkillRegistry

    reg = SkillRegistry()
    sk = RuntimeSkill(name="chat_mem")
    reg.register(sk)
    assert resolve_skill_identity(sk) == "chat_mem"
    assert getattr(sk, "skill_id", "") == "chat_mem", "register 后身份字段应已归一"


def test_register_never_overwrites_existing_skill_id():
    from neurova.skill_system import Skill as RuntimeSkill
    from neurova.skill_system import SkillRegistry

    reg = SkillRegistry()
    sk = RuntimeSkill(name="tool-key")
    sk.skill_id = "manifest-id"
    reg.register(sk)
    assert sk.skill_id == "manifest-id", "已有身份不得被注册面覆写"


def test_register_skill_manifest_path_also_canonicalized():
    """register_skill 兼容 API（manifest 形态）同样出口归一。"""
    from neurova.skill_system import SkillRegistry
    from neurova.skills.models import Skill, SkillSource

    reg = SkillRegistry()
    ok = reg.register_skill(Skill(id="via-manifest", name="via-manifest", source=SkillSource.LOCAL))
    assert ok is True
    stored = reg.skills["via-manifest"]
    assert getattr(stored, "skill_id", "") == "via-manifest"


# ── G-4 静态纪律：三跳链只活在契约模块 ─────────────────────

_CHAIN_RE = re.compile(r'getattr\(\s*\w+\s*,\s*"skill_id"[^)]*\)\s+or\s+getattr')


def test_no_identity_chains_outside_contract():
    offenders = []
    for py in NEUROVA_PKG.rglob("*.py"):
        if py.name == "skill_contract.py" or "__pycache__" in str(py):
            continue
        try:
            text = py.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if _CHAIN_RE.search(line):
                offenders.append(f"{py.relative_to(NEUROVA_PKG)}:{n}")
    assert not offenders, f"身份三跳链必须收敛进 skill_contract，残留: {offenders}"


def test_consumers_use_resolver():
    """关键消费面接线检查（记账/漏斗/API 三处经 resolve_skill_identity）。"""
    from neurova import agent_core, tool_executor
    from neurova.api.endpoints import skill as skill_ep

    for mod in (agent_core, tool_executor, skill_ep):
        src = inspect.getsource(mod)
        assert "resolve_skill_identity" in src, f"{mod.__name__} 应改用单源解析器"
