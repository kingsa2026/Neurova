"""任务2 切片2：actionability 纯决策（与开关来源/IO 解耦）。

规格（机器源 + 近期无人类 才抑制；其余一律可行）：
- 门控关闭 → 可行（不改现状）。
- human / unknown 源 → 可行（永不抑制人类或存疑轮次）。
- 机器源但近期有intervention人类 → 可行（防误杀）。
- 机器源且近期无人类 → 不可行，给结构化 reason。
"""
from __future__ import annotations

from neurova.agent.actionability import evaluate_actionability
from neurova.agent.turn_origin import TurnOrigin


def test_gate_disabled_is_actionable():
    ok, reason = evaluate_actionability(enabled=False, origin=TurnOrigin.BOT_PEER, human_recent=False)
    assert ok is True and reason == ""


def test_human_origin_always_actionable_even_when_enabled():
    ok, reason = evaluate_actionability(enabled=True, origin=TurnOrigin.HUMAN, human_recent=False)
    assert ok is True and reason == ""


def test_machine_origin_without_recent_human_is_not_actionable():
    ok, reason = evaluate_actionability(
        enabled=True, origin=TurnOrigin.SWARM, human_recent=False
    )
    assert ok is False
    assert reason  # 必须给出可诊断的 reason


def test_machine_origin_with_recent_human_is_actionable():
    # 防误杀：人类刚发言、下一轮是 agent 转述 → 仍放行
    ok, reason = evaluate_actionability(
        enabled=True, origin=TurnOrigin.BOT_PEER, human_recent=True
    )
    assert ok is True and reason == ""


# ── 切片3：开关作为"系统设置·LLM 路由"持久化可控参数 ───────────
class TestActionabilityConfig:
    def test_default_off(self, tmp_path):
        from neurova.agent.actionability import get_actionability_config

        enabled, lookback = get_actionability_config(path=tmp_path / "s.json")
        assert enabled is False
        assert lookback == 20

    def test_persisted_on_when_env_unset(self, tmp_path, monkeypatch):
        from neurova.agent.actionability import get_actionability_config
        from neurova.core.app_settings import save_app_settings

        monkeypatch.delenv("NEUROVA_ACTIONABILITY_GATE", raising=False)
        save_app_settings("routing", {"actionability_enabled": True}, path=tmp_path / "s.json")
        enabled, _ = get_actionability_config(path=tmp_path / "s.json")
        assert enabled is True

    def test_env_forces_off_overrides_persisted_on(self, tmp_path, monkeypatch):
        """运维逃生门：env 显式 off 优先于设置持久化的 on。"""
        from neurova.agent.actionability import get_actionability_config
        from neurova.core.app_settings import save_app_settings

        monkeypatch.setenv("NEUROVA_ACTIONABILITY_GATE", "off")
        save_app_settings("routing", {"actionability_enabled": True}, path=tmp_path / "s.json")
        enabled, _ = get_actionability_config(path=tmp_path / "s.json")
        assert enabled is False
