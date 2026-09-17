# -*- coding: utf-8 -*-
"""Phase 1（拆分方案）— TurnState 门面与 Agent 转发层契约。

锁定三层语义（docs/04-plans/agent-core-decomposition-plan.md Phase 1）：

1. TurnState 本体：17 个轮次 API 全集存在、签名正确、读写走
   neurova.core.turn_context 的 ContextVar（并发隔离）；
2. Agent 转发层：同名 API 经 agent.turn_state 委托；`__new__` 直构路径
   （套件既有轻量构造）下 turn_state 懒建可用；
3. 分叉修复防回归（Phase 1 顺手根治的两处 P0-B1 遗留）：
   - `_collect_tool_messages` 必须读 ContextVar（原死列表读恒 []，
     post_chat_pipeline 3 处消费点拿不到工具消息）；
   - `_set_reasoning` 必须写入与 current_reasoning 同一存储（原写死
     实例属性，所有读取方恒拿 None）；
4. 无反向依赖：turn_state.py 不得 import agent_core（组合方向单向）。
"""
import inspect
import textwrap

import pytest

from neurova.core import turn_context


@pytest.fixture(autouse=True)
def _clean_turn_state():
    turn_context.clear_turn_state()
    yield
    turn_context.clear_turn_state()


class TestTurnStateFacade:
    """TurnState 门面本体（不经 Agent）。"""

    def _ts(self):
        from neurova.agent.turn_state import TurnState

        return TurnState()

    def test_identity_roundtrip_and_default_user(self):
        ts = self._ts()
        ts.set_request_identity("问题", session_id="s1")
        assert ts.current_user_input == "问题"
        assert ts.current_session_id == "s1"
        assert ts.current_user_id == "default"  # 缺省语义
        ts.set_request_identity("问题2", session_id="s1", user_id="u9")
        assert ts.current_user_id == "u9"

    def test_reasoning_roundtrip(self):
        ts = self._ts()
        ts.set_current_reasoning("思考中")
        assert ts.current_reasoning == "思考中"
        ts.set_current_reasoning(None)
        assert ts.current_reasoning is None

    def test_tool_messages_reset_append_snapshot_is_copy(self):
        ts = self._ts()
        ts.reset_tool_messages()
        assert ts.get_tool_messages_snapshot() == []
        ts.append_tool_messages([{"type": "tool_call", "tool_name": "t"}])
        snap = ts.get_tool_messages_snapshot()
        snap.clear()  # 副本：改快照不回写
        assert len(ts.get_tool_messages_snapshot()) == 1

    def test_tool_events_self_heal(self):
        ts = self._ts()
        ts.append_tool_event({"type": "tools_degraded"})
        assert ts.tool_events == [{"type": "tools_degraded"}]

    def test_turn_count_increment_and_session_keyed(self):
        ts = self._ts()
        assert ts.turn_count == 0
        assert ts.increment_turn_count() == 1
        assert ts.turn_count == 1

    def test_session_id_empty_str_when_unset(self):
        assert self._ts().session_id == ""

    def test_signatures_frozen(self):
        """签名冻结（方案硬约束 1）：与迁移前 Agent API 逐字一致（self→门面）。"""
        from neurova.agent.turn_state import TurnState

        expected = {
            "set_request_identity": "(self, user_input: str, session_id: Optional[str] = None, user_id: Optional[str] = None) -> None",
            "set_current_reasoning": "(self, reasoning: Optional[str]) -> None",
            "reset_tool_messages": "(self) -> None",
            "append_tool_messages": "(self, records: List[Dict[str, Any]]) -> None",
            "get_tool_messages_snapshot": "(self) -> List[Dict[str, Any]]",
            "collect_tool_messages": "(self) -> List[Dict[str, Any]]",
            "append_tool_event": "(self, event: Dict[str, Any]) -> None",
            "increment_turn_count": "(self) -> int",
        }
        for name, sig in expected.items():
            actual = str(inspect.signature(getattr(TurnState, name)))
            assert actual == sig, f"TurnState.{name} 签名漂移: {actual}"

    def test_no_reverse_dependency_on_agent_core(self):
        """硬约束 4：turn_state 不得 import agent_core（组合单向）。"""
        import ast as ast_mod
        import pathlib

        src_path = (
            pathlib.Path(__file__).resolve().parents[3]
            / "neurova"
            / "agent"
            / "turn_state.py"
        )
        tree = ast_mod.parse(src_path.read_text(encoding="utf-8"))
        bad = [
            n for n in ast_mod.walk(tree)
            if isinstance(n, ast_mod.Import)
            and any(a.name.startswith("neurova.agent_core") for a in n.names)
        ] + [
            n for n in ast_mod.walk(tree)
            if isinstance(n, ast_mod.ImportFrom)
            and (n.module or "").startswith("neurova.agent_core")
        ]
        assert not bad, "turn_state 反向依赖 agent_core 会成环"


class TestAgentForwarding:
    """Agent 同名 API 经 turn_state 委托（含 __new__ 直构路径）。"""

    def _agent(self):
        from neurova.agent_core import Agent

        return Agent.__new__(Agent)  # 套件既有轻量构造路径

    def test_turn_state_lazy_built_on_new_bare_instance(self):
        agent = self._agent()
        assert "_turn_state" not in vars(agent)
        ts = agent.turn_state
        assert ts is agent.turn_state  # 懒建后复用同一实例
        assert "_turn_state" in vars(agent)

    def test_agent_api_delegates_to_same_facade(self):
        agent = self._agent()
        agent.set_request_identity("输入", session_id="s9")
        assert agent.current_user_input == "输入"
        assert agent.turn_state.current_user_input == "输入"  # 同源
        agent.append_tool_messages([{"type": "tool_call"}])
        assert agent.get_tool_messages_snapshot() == agent.turn_state.get_tool_messages_snapshot()
        assert agent.tool_events == agent.turn_state.tool_events
        assert agent.session_id == agent.turn_state.session_id

    def test_private_name_contract_preserved(self):
        """A-04 契约：_current_user_input 读写与公有名同存储（getter+setter）。"""
        agent = self._agent()
        agent._current_user_input = "查天气"
        assert agent.current_user_input == "查天气"
        assert agent._current_user_input == "查天气"
        agent._current_user_input = None  # init_conversation 重置语义
        assert agent.current_user_input is None
        assert agent._current_user_input is None


class TestForkFixes:
    """P0-B1 遗留分叉的根治防回归。"""

    def _agent(self):
        from neurova.agent_core import Agent

        return Agent.__new__(Agent)

    def test_collect_tool_messages_reads_contextvar_not_dead_list(self):
        """原实现读 `_tool_messages_list` 死实例属性 → post_chat 3 处恒拿 []。

        经 API 写入后，私有收集器必须能读到（同一 ContextVar 存储）。
        """
        agent = self._agent()
        assert agent._collect_tool_messages() == []
        agent.append_tool_messages([{"type": "tool_call", "tool_name": "t1"}])
        collected = agent._collect_tool_messages()
        assert [m["tool_name"] for m in collected] == ["t1"], (
            "_collect_tool_messages 不得再读死实例属性 _tool_messages_list"
        )

    def test_set_reasoning_writes_same_storage_as_reader(self):
        """原实现写 `self._current_reasoning` 死属性 → 所有读取方恒 None。

        channels/post_chat 经 getattr(agent, "current_reasoning") 读取。
        """
        agent = self._agent()
        agent._set_reasoning("思考内容")
        assert agent.current_reasoning == "思考内容", (
            "_set_reasoning 必须写入与 current_reasoning 同一存储（ContextVar）"
        )

    def test_reasoning_via_public_api_equivalent(self):
        agent = self._agent()
        agent.set_current_reasoning("via public")
        assert agent.current_reasoning == "via public"

    def test_agent_core_has_no_dead_storage_writes(self):
        """agent_core 不得再对 _current_reasoning/_tool_messages_list 死存储赋值。"""
        import ast as ast_mod
        import pathlib

        src = (
            pathlib.Path(__file__).resolve().parents[3]
            / "neurova"
            / "agent_core.py"
        ).read_text(encoding="utf-8")
        tree = ast_mod.parse(src)

        class V(ast_mod.NodeVisitor):
            def __init__(self):
                self.hits = []

            def visit_Assign(self, node):
                for t in ast_mod.walk(node):
                    if (
                        isinstance(t, ast_mod.Attribute)
                        and isinstance(t.value, ast_mod.Name)
                        and t.value.id == "self"
                        and t.attr in ("_current_reasoning", "_tool_messages_list")
                    ):
                        self.hits.append(node.lineno)
                self.generic_visit(node)

        v = V()
        v.visit(tree)
        assert not v.hits, f"agent_core 仍有死存储写点: 行 {v.hits}"
