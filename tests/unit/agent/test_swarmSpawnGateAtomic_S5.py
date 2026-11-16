"""P2 §3.2-10a 红灯：swarm MAX_ACTIVE_CHILDREN 检查与落账是 check-then-act。

spawn 在 :369 用 _count_active() 无锁快查，真正的落账在 :451 的锁内——
并发派生可在两步之间突破硬限。修复判据：锁内复核同判据，复核不过即
结构化拒绝（MAX_ACTIVE_CHILDREN），外层无锁查询仅作快路径。
白盒确定性钉法：让 _count_active 首查（快路径）返回限额-1、复核窗口返回
限额——无锁内复核（红）则派生成功越过硬限；有锁内复核（绿）即拒绝。
"""

import pytest

from neurova.agent.swarm import SwarmManager


@pytest.mark.asyncio
async def test_spawn_rechecks_active_children_under_lock(monkeypatch):
    manager = SwarmManager()
    limit = manager.MAX_ACTIVE_CHILDREN

    monkeypatch.setattr(manager, "_resolve_agent", lambda aid: (object(), "s5-agent", False))
    monkeypatch.setattr(manager, "_over_budget", lambda aid, model: False)
    monkeypatch.setattr(manager, "_model_cooldown_remaining", lambda model: 0.0)

    async def _noopExecute(*args, **kwargs):
        return {}

    monkeypatch.setattr(manager, "_execute", _noopExecute)

    calls = {"n": 0}

    def fakeCountActive():
        calls["n"] += 1
        # 第 1 次＝外层无锁快路径（返回限额-1，放行）；此后＝锁内复核窗口
        # （返回限额，必须拒绝）
        return limit - 1 if calls["n"] == 1 else limit

    monkeypatch.setattr(manager, "_count_active", fakeCountActive)

    result = await manager.spawn("子任务", background=True)

    assert result.get("rejected") is True, (
        f"锁内未复核 MAX_ACTIVE_CHILDREN：并发派生可越过硬限（实际返回 {result}）"
    )
    assert result["rejection"]["code"] == "MAX_ACTIVE_CHILDREN"
    assert "subagent_id" not in result
