# -*- coding: utf-8 -*-
"""
P2-b GateCatalog 声明式门控配置层防回归网（对标 QP beta.5 GateCatalog）

语义：
- 可配置 gate 白名单：iteration / token_budget / doom_loop（goal 类需要
  运行时 completion_check 回调，不走配置层——由 set_goal_gate 注入）
- pydantic 严格校验（extra=forbid：未知参数拒绝，fail fast）
- 互斥组（此层无互斥对，但结构预留）；cost 标注
- compile(specs) → List[StopGate]（按 priority 排序，可直接喂 GateRunner）
- describe() → JSON Schema 形状（给前端配置 UI）
- 编译前全量验证，再构建（原子语义：一个非法全部不建）
"""
import pytest

from pydantic import ValidationError


class TestCatalogValidation:
    def test_valid_spec_compiles(self):
        from neurova.agent.gate_catalog import GateCatalog, compile_gates

        catalog = GateCatalog()
        gates = compile_gates([
            {"type": "iteration", "params": {"max_rounds": 10}},
            {"type": "token_budget", "params": {"max_tokens": 50000}},
        ])
        assert len(gates) == 2
        names = [g.name for g in gates]
        assert "iteration" in names and "token_budget" in names
        assert gates[0].priority <= gates[1].priority  # 已排序

    def test_unknown_type_rejected(self):
        from neurova.agent.gate_catalog import compile_gates

        with pytest.raises(ValueError, match="unknown"):
            compile_gates([{"type": "carrier_pigeon", "params": {}}])

    def test_unknown_param_rejected(self):
        """extra=forbid：拼错参数名 fail fast"""
        from neurova.agent.gate_catalog import compile_gates

        with pytest.raises(ValueError):  # extra=forbid 包装为 ValueError
            compile_gates([{"type": "iteration", "params": {"max_round": 10}}])  # 少 s

    def test_param_type_rejected(self):
        from neurova.agent.gate_catalog import compile_gates

        with pytest.raises(ValueError):
            compile_gates([{"type": "iteration", "params": {"max_rounds": "ten"}}])

    def test_atomic_compile_no_partial(self):
        """第二个 spec 非法 → 第一个也不产出（原子编译）"""
        from neurova.agent.gate_catalog import compile_gates

        with pytest.raises(Exception):
            compile_gates([
                {"type": "iteration", "params": {"max_rounds": 5}},
                {"type": "token_budget", "params": {"max_tokens": "bad"}},
            ])

    def test_goal_type_not_configurable(self):
        """goal gate 需要运行时回调，不在配置白名单"""
        from neurova.agent.gate_catalog import compile_gates

        with pytest.raises(ValueError, match="unknown"):
            compile_gates([{"type": "goal", "params": {}}])


class TestGateBehaviorPreserved:
    def test_compiled_doom_loop_terminates(self):
        """编译产物行为与手写等价：重复 round_signature 达 max_interrupts → TERMINATE"""
        from neurova.agent.gate_catalog import compile_gates
        from neurova.agent.gates import StopAction

        gates = compile_gates([
            {"type": "doom_loop", "params": {"window_size": 2, "similarity_threshold": 0.9, "max_interrupts": 1}},
        ])
        doom = gates[0]
        ctx = {"round_signature": "grep:abc"}  # openai_loop 的 round_signature 形态

        # 同签名第二次出现即达 max_interrupts=1 → 直接 TERMINATE
        d1 = doom.check(ctx)  # 首次入窗 → BYPASS
        assert d1.action == StopAction.BYPASS
        d2 = doom.check(ctx)  # 第二次重复 → interrupt_count=1 >= 1 → TERMINATE
        assert d2.action == StopAction.TERMINATE

    def test_runner_accepts_compiled_gates(self):
        """编译结果直接喂 GateRunner"""
        from neurova.agent.gate_catalog import compile_gates
        from neurova.agent.gates import GateRunner

        gates = compile_gates([{"type": "iteration", "params": {"max_rounds": 3}}])
        runner = GateRunner(gates)
        assert runner._gates == gates


class TestDescribe:
    def test_describe_schema_shape(self):
        from neurova.agent.gate_catalog import GateCatalog

        schema = GateCatalog().describe()
        assert "iteration" in schema
        entry = schema["iteration"]
        assert entry["priority"] == 10
        assert "max_rounds" in entry["params"]
        assert entry["params"]["max_rounds"]["default"] == 20

    def test_describe_lists_no_goal(self):
        from neurova.agent.gate_catalog import GateCatalog

        assert "goal" not in GateCatalog().describe()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
