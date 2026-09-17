# -*- coding: utf-8 -*-
"""Phase 0 — agent_core 公开契约快照守卫。

锁定拆分全程不得破坏的四个契约面（方案 §4「行为不变的硬约束」）：

1. 模块级消费者面 —— tests/ 实测 import/patch 的符号（含 re-export 的
   get_session_manager：patch('neurova.agent_core.get_session_manager') 依赖它）；
2. Agent 类体内定义的成员 —— 名单与种类（method/property/class_attr）；
3. 关键方法签名 —— inspect.signature 逐字比对（搬迁不得改签名）；
4. Agent 实例字段（__dict__ 键集）—— ~350 处属性访问的事实接口；
   Phase 1 抽 TurnState 后允许把字段迁到 agent_instance_fields_migrated 登记
   （迁出 = 显式决策，静默消失 = 红灯）。

维护协议：
  - 每个 Phase 验收时先跑本文件；任何成员/签名/字段变化若属"有意为之"，
    更新快照 JSON 并在该次提交说明里写明去向（迁到哪个模块/转发垫片位置）。
  - 禁止用"更新快照"的方式吞掉非预期 diff——先查明变化来源。
"""
import inspect
import io
import json
import sys
import tempfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

SNAPSHOT = Path(__file__).resolve().parent / "agent_public_contract_snapshot.json"


@pytest.fixture(scope="module")
def snapshot():
    assert SNAPSHOT.exists(), (
        f"契约快照文件丢失: {SNAPSHOT.relative_to(PROJECT_ROOT)}\n"
        "恢复方式：git checkout 该文件。禁止无快照合入拆分改动。"
    )
    return json.loads(io.open(SNAPSHOT, encoding="utf-8").read())


@pytest.fixture(scope="module")
def agent_module():
    import neurova.agent_core as mod
    return mod


@pytest.fixture(scope="module")
def live_contract(agent_module):
    """按生成器同款规则实测当前契约面。"""
    import ast as ast_mod

    src = io.open(PROJECT_ROOT / "neurova" / "agent_core.py", encoding="utf-8").read()
    tree = ast_mod.parse(src)
    agent_node = next(n for n in tree.body
                      if isinstance(n, ast_mod.ClassDef) and n.name == "Agent")

    members = {}
    for n in agent_node.body:
        if isinstance(n, (ast_mod.FunctionDef, ast_mod.AsyncFunctionDef)):
            kind = "property" if any(
                (isinstance(d, ast_mod.Name) and d.id == "property")
                for d in n.decorator_list
            ) else "method"
            members[n.name] = kind
        elif isinstance(n, ast_mod.Assign):
            for t in n.targets:
                if isinstance(t, ast_mod.Name):
                    members[t.id] = "class_attr"
        elif isinstance(n, ast_mod.AnnAssign) and isinstance(n.target, ast_mod.Name):
            members[n.target.id] = "class_attr"

    signatures = {}
    for name, kind in members.items():
        attr = getattr(agent_module.Agent, name, None)
        if attr is not None and kind in ("method", "property"):
            signatures[name] = str(inspect.signature(
                attr.fget if isinstance(attr, property) else attr
            ))

    from neurova.agent_core import Agent
    with tempfile.TemporaryDirectory() as td:
        agent = Agent(workspace_path=td, enable_memory=False)
        fields = sorted(vars(agent))

    return {"members": members, "signatures": signatures, "fields": fields}


class TestModuleConsumerSurface:
    @pytest.mark.parametrize("name", [
        "Agent", "AgentConfig", "AgentLLMClient", "SubSystemContainer",
        "_NullSystem", "debug_log", "get_session_manager", "wire_memory_guards",
        "AGENT_LOOP_AVAILABLE", "COGNITIVE_GRAPH_AVAILABLE",
        "NEUHEBB_AVAILABLE", "TEMPERATURE_ENGINE_AVAILABLE",
    ])
    def test_consumer_symbol_resolvable(self, agent_module, name):
        """tests/ 实测 import/patch 的模块符号必须始终可解析。"""
        assert hasattr(agent_module, name), (
            f"neurova.agent_core.{name} 不可解析——tests 的 import/patch 目标断裂。"
            "搬迁符号时必须在 agent_core 保留 re-export（方案硬约束 2）。"
        )

    def test_snapshot_symbols_all_present(self, agent_module, snapshot):
        missing = [s for s in snapshot["module_public_symbols"]
                   if not hasattr(agent_module, s)]
        assert not missing, f"快照中的模块符号丢失: {missing}"


class TestAgentMembers:
    def test_no_member_lost(self, snapshot, live_contract):
        lost = set(snapshot["agent_members"]) - set(live_contract["members"])
        assert not lost, (
            f"Agent 成员丢失 {sorted(lost)}——拆分只许搬移+转发，不许静默删除。"
            "若属有意收编，先更新快照并在提交说明写明去向。"
        )

    def test_no_member_kind_changed(self, snapshot, live_contract):
        """property 变 method、method 变 property 都会改变访问语义。"""
        changed = {
            name: (snapshot["agent_members"][name], live_contract["members"][name])
            for name in set(snapshot["agent_members"]) & set(live_contract["members"])
            if snapshot["agent_members"][name] != live_contract["members"][name]
        }
        assert not changed, f"成员种类变更（property/method 互转）: {changed}"

    def test_no_signature_drift(self, snapshot, live_contract):
        drift = {
            name: {"snapshot": snapshot["agent_signatures"][name],
                   "live": live_contract["signatures"].get(name)}
            for name in snapshot["agent_signatures"]
            if snapshot["agent_signatures"][name] != live_contract["signatures"].get(name)
        }
        assert not drift, (
            f"签名漂移（参数名/默认值/注解变化）: {drift}。\n"
            "方案硬约束 1：搬迁方法不得改签名。"
        )


class TestInstanceFields:
    def test_no_field_silently_removed(self, snapshot, live_contract):
        migrated = set(snapshot.get("agent_instance_fields_migrated", []))
        expected = set(snapshot["agent_instance_fields"]) - migrated
        lost = expected - set(live_contract["fields"])
        assert not lost, (
            f"Agent 实例字段静默消失: {sorted(lost)}。\n"
            "~350 处属性访问依赖这些字段（_skill_registry 60 处等）。"
            "若属 Phase 迁出，把字段名加入快照的 agent_instance_fields_migrated "
            "并写明新家；静默消失 = 调用点断裂。"
        )

    def test_migrated_field_registry_honest(self, snapshot, live_contract):
        """登记为已迁出的字段必须真的不在实例上（防止登记表变垃圾抽屉）。"""
        migrated = set(snapshot.get("agent_instance_fields_migrated", []))
        still_live = migrated & set(live_contract["fields"])
        assert not still_live, (
            f"已登记迁出的字段仍出现在实例 __dict__: {sorted(still_live)}——"
            "登记与事实不符，修正登记表或恢复字段。"
        )


class TestSnapshotIntegrity:
    """快照自身的完整性（防"删快照条目来吞掉 diff"的单向盲区）。

    与 i18n 守卫的白名单死条目同理：快照若可被单方缩水，守卫就形同虚设。
    红灯验证实录：删掉快照的 skill_registry 后旧断言仍 27 passed——
    本组用例即堵这个洞。
    """

    def test_snapshot_member_set_covers_real_members(self, snapshot, live_contract):
        """快照条目集必须与实测成员集双向一致（不许任一方向单方缩水）。"""
        snap = set(snapshot["agent_members"])
        live = set(live_contract["members"])
        assert snap == live, (
            f"快照与实测成员集不一致: 快照多出 {sorted(snap - live)}，"
            f"实测多出 {sorted(live - snap)}。\n"
            "合法流程：拆分 Phase 验收时按维护协议重生成快照并说明去向；"
            "禁止顺手删条目绕过守卫。"
        )

    def test_snapshot_signatures_covers_members(self, snapshot, live_contract):
        """快照里每个 method/property 成员都必须有对应签名条目。"""
        sigs = set(snapshot["agent_signatures"])
        need = {n for n, k in snapshot["agent_members"].items() if k in ("method", "property")}
        missing = need - sigs
        assert not missing, f"快照缺签名条目: {sorted(missing)}"

    def test_fields_registry_consistent(self, snapshot, live_contract):
        """字段登记表 = 快照字段集与实测字段集之差的合法记录。"""
        migrated = set(snapshot.get("agent_instance_fields_migrated", []))
        unknown = migrated - set(snapshot["agent_instance_fields"])
        assert not unknown, (
            f"agent_instance_fields_migrated 登记了快照中不存在的字段: {sorted(unknown)}"
        )


class TestPatchTargets:
    """方案 §7 风险表第一行：patch 目标失效 = 多个测试红。"""

    @pytest.mark.parametrize("target", [
        "AgentLLMClient", "get_session_manager",  # patch("neurova.agent_core.X")
        "_load_identity", "_init_memory_modules",  # patch.object(Agent, "X")
        "chat", "chat_stream", "_on_skill_post_execute", "rebuild_loop",
        "process_multimodal",
    ])
    def test_patchable(self, agent_module, target):
        if target in ("AgentLLMClient", "get_session_manager"):
            assert hasattr(agent_module, target), (
                f"模块级 patch 目标 neurova.agent_core.{target} 断裂"
            )
        else:
            assert hasattr(agent_module.Agent, target), (
                f"Agent.{target} 不在 MRO 上——patch.object/patch 类路径目标断裂"
            )
