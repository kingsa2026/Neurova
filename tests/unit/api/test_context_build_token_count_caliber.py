# -*- coding: utf-8 -*-
"""`/context/build` 的 `token_count` 必须走全仓唯一 token 尺子（T-01 契约的端点面）。

## 缺陷（改前实证）

T-01 的 DoD 原文是「判据路径统一走 EXACT（tiktoken o200k）」并要求
「grep 证明不再有第二份 token 计数参与门判」。端点这条读数是**第二把尺子**：

```python
token_count=len(context_content.split())  # 简单估算
```

中文整句在 `split()` 下是 **1 个词**，于是同一条读数在中文输入上被低估到
真值的十分之一量级——实测 `"user: 今天天气怎么样，帮我看看要不要带伞"`：

```
split 口径: 2   唯一尺子: 15
```

`token_count` 是响应契约字段（`BuildContextResponse.token_count`，前端
`BuildContextResponse` 同名字段），读数偏低不是"粗略"，而是**报了一个假数**，
且与同仓 `context/composition` 的面板、`token_estimator` 的判据不同源
（`AGENTS.md` 修复教义第 6 条：口径只允许一处定义）。

## 契约（修复后）

1. `token_count` 等于 `context.token_estimator.estimate_tokens(正文)` 的数；
2. 生产侧不得再用 `len(<text>.split())` 充当 token 计数。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _client():
    from neurova.api.auth import get_current_user
    from neurova.api.endpoints import context as ctx_mod

    app = FastAPI()
    app.include_router(ctx_mod.router, prefix="/context")
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1"}
    return ctx_mod, TestClient(app)


def _fake_agent():
    agent = MagicMock()

    async def real_build_context(user_input, **kwargs):
        return [{"role": "system", "content": "sys"}, {"role": "user", "content": user_input}]

    agent.build_context = real_build_context
    agent.unified_injector = None
    return agent


class TestTokenCountUsesSingleRuler:
    @pytest.mark.parametrize("path", ["/context/build", "/context/build/v2"])
    def test_token_count_matches_estimator(self, path):
        """读数是唯一尺子的输出，不是 `split()` 的词数。"""
        from neurova.context.token_estimator import estimate_tokens

        ctx_mod, client = _client()
        with patch.object(ctx_mod, "_get_context_builder", return_value=None), patch.object(
            ctx_mod, "_get_agent", return_value=_fake_agent()
        ):
            resp = client.post(
                path,
                json={"agent_id": "default", "user_input": "今天天气怎么样，帮我看看要不要带伞"},
            )
        assert resp.status_code == 200, resp.text[:300]
        body = resp.json()
        assert body["token_count"] == estimate_tokens(body["content"]), (
            f"{path} 的 token_count 与全仓唯一尺子不一致："
            f"{body['token_count']} != {estimate_tokens(body['content'])}"
        )

    @pytest.mark.parametrize("path", ["/context/build", "/context/build/v2"])
    def test_chinese_is_not_undercounted(self, path):
        """前置条件自证：中文输入下旧口径会低一个量级——判据必须真咬合。"""
        ctx_mod, client = _client()
        with patch.object(ctx_mod, "_get_context_builder", return_value=None), patch.object(
            ctx_mod, "_get_agent", return_value=_fake_agent()
        ):
            resp = client.post(
                path, json={"agent_id": "default", "user_input": "中文整句在空白分词下只算一个词"}
            )
        body = resp.json()
        assert body["token_count"] > len(body["content"].split()), (
            "token_count 仍等于空白分词数 —— 第二把尺子还在"
        )


class TestNoWordSplitTokenCountingInProduction:
    """判据收窄口径：只咬「**以 token 命名**的那一位」。

    为什么不能一刀切禁 `len(x.split())`：`split()` 的**词数**在别处是正当用途
    （`moe_router` 的重叠比例、`plan_orchestrator` 的 `word_count`），它们不是
    token 计数。判据若按形状一刀切，就会把这些正当用途一起打红——那是判据
    越界，不是缺陷。真正的判据是「这个值被当成 token 数用」，而"被当成 token 数"
    在 AST 上有客观落点：关键字参数名、赋值目标名、或字典键名里含 `token`。
    """

    @staticmethod
    def _isLenSplit(node) -> bool:
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "len"
            and len(node.args) == 1
            and isinstance(node.args[0], ast.Call)
            and isinstance(node.args[0].func, ast.Attribute)
            and node.args[0].func.attr == "split"
            and not node.args[0].args
            and not node.args[0].keywords
        )

    @classmethod
    def _containsLenSplit(cls, node) -> bool:
        return any(cls._isLenSplit(sub) for sub in ast.walk(node)) if node is not None else False

    @staticmethod
    def _nameHasToken(name) -> bool:
        return isinstance(name, str) and "token" in name.lower()

    def test_production_has_no_len_split_token_count(self):
        from tests import ast_scan

        offenders = []
        for path, node in ast_scan.walkedModules(
            ast_scan.PRODUCTION_ROOT, hints=ast_scan.textHints("split", "token")
        ):
            # ① 关键字参数名含 token
            if isinstance(node, ast.Call):
                for kw in node.keywords:
                    if self._nameHasToken(kw.arg) and self._containsLenSplit(kw.value):
                        offenders.append(f"{path.relative_to(ast_scan.REPO_ROOT)}:{node.lineno}")
            # ② 字典键名含 token
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if isinstance(key, ast.Constant) and self._nameHasToken(key.value) and self._containsLenSplit(value):
                        offenders.append(f"{path.relative_to(ast_scan.REPO_ROOT)}:{node.lineno}")
            # ③ 赋值目标名含 token
            targets = []
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
            tokenNamed = any(
                self._nameHasToken(getattr(t, "id", None) or getattr(t, "attr", None)) for t in targets
            )
            value = node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
            if tokenNamed and self._containsLenSplit(value):
                offenders.append(f"{path.relative_to(ast_scan.REPO_ROOT)}:{node.lineno}")

        assert not offenders, (
            "这些生产调用点把空白分词数当成 token 数（全仓唯一尺子是 "
            "context.token_estimator.estimate_tokens）：" + ", ".join(sorted(offenders))
        )
