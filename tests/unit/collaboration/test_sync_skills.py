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
    # 默认注册了 3 个 skill：memory, web_search, file_operation
    assert count == 3, f"sync_skills 应返回 3，实际返回 {count}"


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
