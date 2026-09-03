"""SkillRegistry 事件回调链断点修复验证。

背景：agent_core._init_router 通过
`SkillRegistry.register_event_callback(SkillEvent.POST_EXECUTE, handler)` 注册回调，
并在 skill 执行后把 (skill, result) 传给 handler。但 class A SkillRegistry 只有
`add_event_handler(handler)`（handler 收 SkillEvent 对象），无 register_event_callback、
无 SkillEvent.POST_EXECUTE 常量、handler 签名也不匹配，导致运行时 NameError/AttributeError。

本文件验证该断点已修复：
1. SkillEvent 具有 PRE_EXECUTE / POST_EXECUTE / ERROR 常量
2. register_event_callback(event_type, handler) 可按类型注册
3. _emit_event 触发时把 (skill, data) 分发给按类型注册的回调
"""

from unittest.mock import MagicMock

from neurova.skill_system import SkillEvent, SkillRegistry


def test_skill_event_constants():
    """SkillEvent 事件类型常量存在且与 _emit_event 字符串一致"""
    assert SkillEvent.PRE_EXECUTE == "before_execute"
    assert SkillEvent.POST_EXECUTE == "after_execute"
    assert SkillEvent.ERROR == "error"


def test_register_event_callback_distributes_skill_and_data():
    """按类型注册的回调收到 (skill, data)"""
    reg = SkillRegistry()
    skill = MagicMock()
    skill.name = "test-skill"
    reg.register(skill)

    received = []
    reg.register_event_callback(SkillEvent.POST_EXECUTE, lambda s, r: received.append((s, r)))

    reg._emit_event(SkillEvent.POST_EXECUTE, "test-skill", {"ok": True})

    assert received == [(skill, {"ok": True})]


def test_register_event_callback_unknown_skill_gets_none():
    """未注册的 skill_name 时，回调收到的 skill 为 None"""
    reg = SkillRegistry()
    received = []
    reg.register_event_callback(SkillEvent.ERROR, lambda s, r: received.append(s))
    reg._emit_event(SkillEvent.ERROR, "missing-skill", "boom")
    assert received == [None]


def test_registered_callback_only_fires_for_matching_type():
    """不同事件类型的回调不会互相触发"""
    reg = SkillRegistry()
    skill = MagicMock()
    skill.name = "test-skill"
    reg.register(skill)

    post, pre = [], []
    reg.register_event_callback(SkillEvent.POST_EXECUTE, lambda s, r: post.append(r))
    reg.register_event_callback(SkillEvent.PRE_EXECUTE, lambda s, r: pre.append(r))

    reg._emit_event(SkillEvent.POST_EXECUTE, "test-skill", {"ok": True})

    assert post == [{"ok": True}]
    assert pre == []


def test_registered_callback_exception_does_not_break():
    """回调抛异常被捕获，不影响其他回调与 add_event_handler"""
    reg = SkillRegistry()
    skill = MagicMock()
    skill.name = "test-skill"
    reg.register(skill)

    seen = []
    reg.register_event_callback(SkillEvent.POST_EXECUTE, lambda s, r: (_ for _ in ()).throw(RuntimeError("boom")))
    reg.register_event_callback(SkillEvent.POST_EXECUTE, lambda s, r: seen.append((s, r)))

    reg._emit_event(SkillEvent.POST_EXECUTE, "test-skill", {"ok": True})

    assert seen == [(skill, {"ok": True})]
