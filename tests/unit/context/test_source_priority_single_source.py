# -*- coding: utf-8 -*-
"""T-09 残余：上下文的「来源 → 优先级」收口为单一事实源（审计 §10 第 3 项 / P2-3）。

## 缺陷（改前实证）

池内优先级是**多个生产者各写一个数**：

- 编排器声明自己的阶梯：`SYSTEM_INSTRUCTION 100 / DEVELOPER_INSTRUCTION 90 /
  USER_INPUT 90 / MEMORY 70 / MULTIMODAL 70 / CONVERSATION 60 / REFLECTION 60 /
  EMOTION 50`；
- 端点 `/context/build`、`/context/build/v2` 写 `priority=10`，注释却写「高优先级」
  —— 池内 60–100 才是高档，10 属最低档（审计原文：注释与真值不符）；
- `voice_context_module` 又给 `EMOTION` 写 60，与编排器同一来源的 50 冲突。

于是同一个来源在不同写入点拿到不同的分：`draw` 按 `priority` 打分排序，
同一来源的内容按写入方不同而争位——这正是"同一契约两份定义"的形态
（`AGENTS.md` 修复教义第 6 条）。

## 契约（修复后）

1. 阶梯只有一处：`context.pool_models.priorityForSource(source)`；
2. `ContextInput` 不显式给优先级时**由来源派生**（缺省不再是独立的第二个数 50）；
3. 生产侧不得再对 `ContextInput` 传**整数字面量**优先级（动态取值不受限）；
4. 端点写入的用户输入与阶梯一致。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from neurova.context.pool_models import ContextInput, ContextSource  # noqa: E402


class TestLadderIsSingleSource:
    def test_priority_derives_from_source_when_omitted(self):
        """缺省优先级由来源派生——不再是一个与阶梯无关的常数。"""
        from neurova.context.pool_models import priorityForSource

        for source in ContextSource:
            item = ContextInput(source=source, content="x")
            assert item.priority == priorityForSource(source), (
                f"{source} 的缺省优先级与阶梯不一致：{item.priority} != "
                f"{priorityForSource(source)}"
            )

    def test_explicit_priority_still_honoured(self):
        """证据驱动的显式取值（如经验按采纳结果定档）不被阶梯覆盖。"""
        item = ContextInput(source=ContextSource.EXPERIENCE, content="x", priority=78)
        assert item.priority == 78


class TestEndpointUsesLadder:
    def _client(self, agent):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from neurova.api.auth import get_current_user
        from neurova.api.endpoints import context as ctx_mod

        app = FastAPI()
        app.include_router(ctx_mod.router, prefix="/context")
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1"}
        return ctx_mod, TestClient(app)

    def _agent_with_pool(self):
        from unittest.mock import MagicMock

        from neurova.context_pool import ContextPool

        pool = ContextPool(user_id="u1", agent_id="a1", session_id=None)
        agent = MagicMock()
        agent.context_orchestrator = MagicMock()
        agent.context_orchestrator.context_pool = pool
        return agent, pool

    @pytest.mark.parametrize("path", ["/context/build", "/context/build/v2"])
    def test_build_writes_ladder_priority(self, path):
        """端点写入的用户输入必须与池内阶梯同源（改前写死 10 且注释称"高优先级"）。"""
        from unittest.mock import patch

        from neurova.context.pool_models import priorityForSource

        agent, pool = self._agent_with_pool()
        ctx_mod, client = self._client(agent)
        with patch.object(ctx_mod, "_get_agent", return_value=agent):
            resp = client.post(path, json={"agent_id": "a1", "user_input": "端点写入"})
        assert resp.status_code == 200, resp.text[:300]

        written = [c for c in pool.get_contexts() if c.content == "端点写入"]
        assert written, "端点写入没进池"
        assert written[0].priority == priorityForSource(ContextSource.USER_INPUT), (
            "端点写入的优先级与池内阶梯不一致（同一来源两份口径）"
        )


class TestNoLiteralPriorityInProduction:
    def test_production_never_passes_integer_literal_priority(self):
        """生产侧不得再对 `ContextInput` 传整数字面量优先级。

        判据只禁**字面量**：证据驱动等动态取值（变量/表达式）不受限——
        那是有单一来源的政策，不是各写一份的阶梯。
        """
        import ast

        from tests import ast_scan

        offenders = []
        for path, node in ast_scan.walkedModules(
            ast_scan.PRODUCTION_ROOT, hints=ast_scan.textHints("ContextInput")
        ):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = getattr(func, "id", None) or getattr(func, "attr", None)
            if name != "ContextInput":
                continue
            for kw in node.keywords:
                if kw.arg == "priority" and isinstance(kw.value, ast.Constant):
                    offenders.append(f"{path.relative_to(ast_scan.REPO_ROOT)}:{node.lineno}")
        assert not offenders, (
            "这些生产调用点仍在自写优先级字面量（阶梯应只有 priorityForSource 一处）："
            + ", ".join(sorted(offenders))
        )
