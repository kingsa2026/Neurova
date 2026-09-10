"""
D3 测试：验证 sync_skills() 返回值（不再永远返回 0）

P1.2 已修复 dict 访问 Bug，sync_skills() 应返回真实的同步数量。
"""

import pytest


def test_sync_skills_returns_count():
    """D3.1: sync_skills() 应返回真实的同步数量（默认 3 个 skill）"""
    from neurova.collaboration.neurflow.adapters import sync_skills
    from neurova.collaboration.neurflow.node_registry import NodeRegistry
    from neurova.skills import get_skill_registry

    # 重置全局单例确保干净状态
    import neurova.skills as skills_module
    skills_module._skill_registry_instance = None

    registry = get_skill_registry()
    nr = NodeRegistry()
    count = sync_skills(nr)
    # 真实契约：全部技能节点同步成功（数量 = 注册表技能数；内置技能
    # 随版本增长，旧断言硬编码 3 是被 sync 中途崩溃掩盖的假契约）
    assert count >= 3, f"sync_skills 至少应同步 3 个技能，实际 {count}"
    assert count == len(registry.list_skills()), (
        f"sync 应全量转换（一条畸形 schema 不得使同步归零），{count} vs {len(registry.list_skills())}"
    )


def test_sync_skills_idempotent():
    """D3.2: sync_skills() 多次调用应稳定返回相同数量"""
    from neurova.collaboration.neurflow.adapters import sync_skills
    from neurova.collaboration.neurflow.node_registry import NodeRegistry

    nr1 = NodeRegistry()
    count1 = sync_skills(nr1)
    nr2 = NodeRegistry()
    count2 = sync_skills(nr2)
    assert count1 == count2, f"多次调用 sync_skills 应稳定，{count1} vs {count2}"


def test_sync_skills_registers_nodes():
    """D3.3: sync_skills() 后，NodeRegistry 应包含同步的节点"""
    from neurova.collaboration.neurflow.adapters import sync_skills
    from neurova.collaboration.neurflow.node_registry import NodeRegistry

    nr = NodeRegistry()
    count = sync_skills(nr)
    nodes = nr.list_all()
    assert len(nodes) >= count, f"NodeRegistry 应包含 {count} 个节点，实际 {len(nodes)}"
