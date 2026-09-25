"""任务2 切片1：可信 TurnOrigin 信号解析（纯函数，默认即安全）。

规格：
- 缺失/非法/未识别 → HUMAN（永不抑制人类/存疑轮次）。
- 显式 turn_origin 命中枚举 → 对应源。
- 仅有 source=="swarm"（蜂群既有约定）→ SWARM。
- 机器源集合 = {bot_peer, swarm, collaboration, system}；human/unknown 不算机器源。
"""
from __future__ import annotations

from neurova.agent.turn_origin import TurnOrigin, is_machine_origin, resolve_turn_origin


def test_missing_metadata_is_human_safe():
    assert resolve_turn_origin(None) is TurnOrigin.HUMAN
    assert resolve_turn_origin({}) is TurnOrigin.HUMAN


def test_explicit_turn_origin_recognized():
    assert resolve_turn_origin({"turn_origin": "bot_peer"}) is TurnOrigin.BOT_PEER
    assert resolve_turn_origin({"turn_origin": "collaboration"}) is TurnOrigin.COLLABORATION
    assert resolve_turn_origin({"turn_origin": "SWARM"}) is TurnOrigin.SWARM  # 大小写不敏感


def test_swarm_source_convention_maps_to_swarm():
    # 蜂群 spawn_metadata 既有 source="swarm"，无需改 swarm 也能识别
    assert resolve_turn_origin({"source": "swarm"}) is TurnOrigin.SWARM


def test_garbage_origin_falls_back_to_human():
    assert resolve_turn_origin({"turn_origin": "totally-unknown"}) is TurnOrigin.HUMAN


def test_machine_origin_membership():
    assert is_machine_origin(TurnOrigin.BOT_PEER) is True
    assert is_machine_origin(TurnOrigin.SWARM) is True
    assert is_machine_origin(TurnOrigin.COLLABORATION) is True
    assert is_machine_origin(TurnOrigin.HUMAN) is False
