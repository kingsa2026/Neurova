# -*- coding: utf-8 -*-
"""B6-3：工作流上下文节点必须能取到 Agent 的池（P2-1 根因侧）。

红灯依据（改前实证）：

```
$ python3 -c "from neurova.context_pool import get_context_pool"
ImportError: cannot import name 'get_context_pool' from 'neurova.context_pool'
```

`_get_context_pool()` 把这个 `ImportError` 吞成 `logger.debug` 并返回 `None`，
于是 `exec_context` 在"未显式注入"时恒 `failed`——**取不到池**与**池里没内容**
在日志里长得一样。

契约（修复后）：

1. 符号存在，且 `_get_context_pool` 按身份取**已登记**的池；
2. 未显式注入时，节点能凭执行上下文里的身份（agent_id / user_id）取到池并成功；
3. 真取不到时 `failed` 且**点名原因**（不静默降级成 DEBUG）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _clean_registry():
    from neurova.context_pool_registry import ContextPoolRegistry

    ContextPoolRegistry._instance = None
    yield
    ContextPoolRegistry._instance = None


def _registerPool(user_id="u1", agent_id="a1", session_id=None):
    from neurova.context_pool import ContextInput, ContextPool, ContextSource
    from neurova.context_pool_registry import get_registry

    pool = ContextPool(user_id=user_id, agent_id=agent_id, session_id=session_id)
    pool.add_context(
        ContextInput(source=ContextSource.MEMORY, content="记得带伞", priority=80, tokens=10)
    )
    get_registry().adopt(pool)
    return pool


class TestResolverFindsRegisteredPool:
    def test_resolver_returns_pool_by_identity(self):
        """符号级根因：解析函数必须真能取到池，而不是恒 None。"""
        from neurova.collaboration.neurflow.builtin import _get_context_pool

        pool = _registerPool()
        assert _get_context_pool(user_id="u1", agent_id="a1", session_id=None) is pool

    def test_resolver_returns_none_without_registration(self):
        from neurova.collaboration.neurflow.builtin import _get_context_pool

        assert _get_context_pool(user_id="u-x", agent_id="a-x", session_id=None) is None


class TestExecContextWithoutInjection:
    @pytest.mark.asyncio
    async def test_exec_context_succeeds_via_identity(self):
        """未显式注入时凭身份取池——改前此处恒 failed（P2-1）。"""
        from neurova.collaboration.neurflow.builtin import exec_context

        _registerPool()
        result = await exec_context({}, {"agent_id": "a1", "user_id": "u1"})
        assert result["status"] == "success", (
            f"节点仍取不到池（P2-1 未修）：{result}"
        )
        assert result["output"], "取到池却没有内容"

    @pytest.mark.asyncio
    async def test_exec_context_explicit_injection_still_wins(self):
        """显式注入优先——既有契约不得因新入口而回退。"""
        from neurova.collaboration.neurflow.builtin import exec_context

        pool = _registerPool()
        result = await exec_context({}, {"context_pool": pool})
        assert result["status"] == "success"
        assert result["metadata"]["total_contexts"] == 1

    @pytest.mark.asyncio
    async def test_failure_names_the_identity(self):
        """真取不到时点名身份（不静默降级成 DEBUG）。"""
        from neurova.collaboration.neurflow.builtin import exec_context

        result = await exec_context({}, {"agent_id": "a-none", "user_id": "u-none"})
        assert result["status"] == "failed"
        assert "a-none" in result["error"] and "u-none" in result["error"], (
            "失败原因没点名身份，无法定位是『没池』还是『池空』："
            f"{result['error']}"
        )
