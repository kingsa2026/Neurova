# -*- coding: utf-8 -*-
"""P2-7（审计 2026-11-04）：supervisor 幂等账本单例不许被带参调用静默覆盖。

缺陷：`if _ledger is None or dbPath:` —— 传 dbPath 即无条件覆盖全局实例：
旧实例 sqlite 连接不 close、不走 reset；已持旧引用的调用方与后续取到的不是
同一份，账本唯一目的（跨重启/多 Worker 幂等去重）失效。

契约：实例已存在时，相同路径复用；不同路径必须显式 `reset_supervisor_ledger()`
后再取，直接带参覆盖要诚实报错。
"""
import pytest

from neurova.agent.supervisor.ledger import (
    get_supervisor_ledger,
    reset_supervisor_ledger,
)


@pytest.fixture(autouse=True)
def _cleanLedger():
    reset_supervisor_ledger()
    yield
    reset_supervisor_ledger()


def test_samePathReusesSingleton(tmp_path):
    path = str(tmp_path / "tasks.db")
    first = get_supervisor_ledger(path)
    assert get_supervisor_ledger(path) is first
    assert get_supervisor_ledger() is first


def test_differentPathRequiresExplicitReset(tmp_path):
    first = get_supervisor_ledger(str(tmp_path / "a.db"))
    with pytest.raises(ValueError, match="reset_supervisor_ledger"):
        get_supervisor_ledger(str(tmp_path / "b.db"))
    assert get_supervisor_ledger() is first, "被拒的带参调用不得改变全局实例"

    reset_supervisor_ledger()
    second = get_supervisor_ledger(str(tmp_path / "b.db"))
    assert second is not first
