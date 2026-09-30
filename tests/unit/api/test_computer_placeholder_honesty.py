# -*- coding: utf-8 -*-
"""T-01 · 占位端点不得以成功信封谎报能力存在（工单集 T-01）。

## 根因

`neurova/api/endpoints/computer.py` 有六个端点是**占位实现**，却返回
`{"code": 0, "message": "...(placeholder)", "data": {...}}`——HTTP 200、业务码成功。
其中 `smart-click` / `smart-type` 还额外回 `{"found": False}`：
**"这个能力根本没实现" 与 "我实现了、但这次没找到目标" 在响应上不可区分**。

这正是 `AGENTS.md` 修复教义第 2 条禁止的形态（不得把失败改写成warning了事，
要求以**诚实形态**暴露：显式 4xx/5xx、`not_supported`、点名失败原因）。

## 处置口径：沿用本仓既有先例，不新造第三种形态

同一病在本仓已被治过两次，形态是 `HTTPException(501)` 并在 detail 里点名原谎报方式：

- `api/endpoints/knowledge_integration.py:205` 「知识盲点分析未实现（原返回编造数据）」
- `api/endpoints/knowledge_integration.py:215` 「知识学习闭环未实现（原谎报 completed）」
- `api/endpoints/personality_router.py:102` 同型

**为何当时取 501、现在其中一条改判退役**（`test_growth_constitution_persistence.py:111`
那条"零消费方直接 404"的先例当时不适用）：六个路由已登记进路由鉴权基线
`docs/s08_route_auth_baseline_2026-09-11.txt:641-658`，且 `smartClick`/`visualParse`
已有前端封装与 11 份 i18n 文案（UI 意图在、实现不在），与 `personality/evolve` 的
"有 FE 按钮但 TODO"同形——故当时**一律保留路由，只把响应换成诚实形态**。

2026-09-30 按 D-5 复核后对 `visual-parse` 改判：它与 `computer_som_snapshot` 是
**同一能力的两条入口**（检测器注入缝在 `som.mark_screenshot(png, detector=...)`），
属修复教义第 6 条该收口的双源，故整条退役（端点 + 模型 + 前端封装 + 11 份 locale），
守卫见 `test_visual_parse_retirement.py`。其余五条仍取 501：它们各自的能力面**没有**
第二份实现可收，撤壳就等于撤意图。`smart-click` 按 D-6 走 T-08→T-10→T-11 接通。
那份带日期的鉴权基线是 2026-09-11 的一次性快照（无活守卫校验），**不改写历史快照**，
此处按事实记其已漂移一行。

## 放大视角（教义第 5 条）

`TestSweepSameContract` 扫 `neurova/api/endpoints/**/*.py` 全部 AST 返回节点，
断言不存在"同一个返回字典里既写 code 成功、又自陈 placeholder"的组合——
命中点由判据穷举，不由本文 grep 次数决定；新写一个这样的端点即红。

## 本文件自带的两条对照（判据不是纸糊的）

- **正对照**：喂一段已知违规的源码，扫描器必须报出来；否则"绿"不可信。
- **负对照**：两个函数各自合法、只是字样相近，不得误报。
  本判据初版用跨行正则时正是这样把整个 computer.py 误报了——真命中只有六个。
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import pathlib
import re
import shutil
import tempfile
import typing

import pytest
from fastapi import HTTPException

from neurova.api.endpoints import computer as computer_ep

ENDPOINT_DIR = pathlib.Path(computer_ep.__file__).parent

# (处理函数名, 该端点原先谎报成功的形态) —— 逐个点名，便于回归时定位是哪一个又躺回去
PLACEHOLDER_HANDLERS: list[typing.Tuple[str, str]] = [
    ("smart_click", "code 0 + found 恒 False"),
    ("smart_type", "code 0 + found 恒 False"),
    ("browser_extract_links", "code 0 + links 恒空"),
    ("browser_execute_js", 'code 0 + 谎报 "JS executed"'),
    ("browser_scrape", 'code 0 + 谎报 "Scrape complete"'),
]

# 各端点的最小合法请求体：只满足必填字段，不猜业务语义
_MINIMAL_BODIES = {
    "smart_click": {"target": "登录按钮"},
    "smart_type": {"target": "用户名输入框", "text": "abc"},
    "browser_extract_links": {},
    "browser_execute_js": {"script": "1 + 1"},
    "browser_scrape": {"url": "https://example.com"},
}


def _invoke(handlerName: str):
    """按签名自省地驱动占位处理函数。

    走直接调用而非 TestClient：诚实性是**处理函数**的性质，与路由/鉴权无关；
    而本仓在 Windows 上起 TestClient 会牵出 approvals.db 文件锁与临时目录 SQLite
    锁一整套无关噪声。路由面的回归另有 `docs/s08_route_auth_baseline_*.txt` 守卫。

    处理函数是 `async def`：**不 await 就不执行函数体**，`pytest.raises` 会永远
    "DID NOT RAISE" —— 本判据初版正是踩在这上面，那次的红毫无意义。
    """
    handler = getattr(computer_ep, handlerName)
    kwargs = {}
    for name, param in inspect.signature(handler).parameters.items():
        if name == "body":
            model = param.annotation
            if not isinstance(model, type):
                model = typing.get_type_hints(model)["body"]
            kwargs["body"] = model(**_MINIMAL_BODIES[handlerName])
        elif name == "current_user":
            # 注意：它的默认值是 `Depends(get_current_user)` 而非"无默认"——
            # 按"是否必填"筛会漏掉它，于是 Depends 对象被当身份传进去，
            # 报出来是 `'Depends' object has no attribute 'get'`（本判据初版即如此）。
            kwargs[name] = {"user_id": "t01-guard", "is_admin": True}
        elif param.default is inspect.Parameter.empty:
            raise AssertionError(
                f"{handlerName} 出现了未预期的必填依赖 {name}——判据需同步更新"
            )
        elif type(param.default).__name__ == "Depends":
            raise AssertionError(
                f"{handlerName} 新增了 Depends 形参 {name}——直接调用会传进 Depends 对象，"
                "须显式给它一个替身值"
            )
    return asyncio.run(handler(**kwargs))


class TestPlaceholderEndpointsAreHonest:
    """六个占位端点必须拒绝，而不是返回一个成功信封。"""

    @pytest.mark.parametrize("handlerName,oldLie", PLACEHOLDER_HANDLERS)
    def test_handlerRefusesInsteadOfReportingSuccess(self, handlerName: str, oldLie: str):
        with pytest.raises(HTTPException) as exc:
            _invoke(handlerName)
        assert exc.value.status_code == 501, (
            f"{handlerName} 仍是假成功形态（原谎报：{oldLie}）——须 501 诚实未实现"
        )

    @pytest.mark.parametrize("handlerName,oldLie", PLACEHOLDER_HANDLERS)
    def test_refusalNamesWhatWasPreviouslyFaked(self, handlerName: str, oldLie: str):
        """detail 须点名"未实现"，让调用方与运维可分诊——不许只给一句光秃秃的 501。"""
        with pytest.raises(HTTPException) as exc:
            _invoke(handlerName)
        detail = str(exc.value.detail or "")
        assert "未实现" in detail, f"{handlerName} 的拒绝理由没点名'未实现': {detail!r}"

    @pytest.mark.parametrize("handlerName,oldLie", PLACEHOLDER_HANDLERS)
    def test_refusalRecordsTheAttempt(self, handlerName: str, oldLie: str):
        """拒绝也要留痕：谁试过这个能力是运维事实，不得因为没实现就不记。"""
        calls = []
        original = computer_ep._log_action
        computer_ep._log_action = lambda *a, **k: calls.append(a)
        try:
            with pytest.raises(HTTPException):
                _invoke(handlerName)
        finally:
            computer_ep._log_action = original
        assert calls, f"{handlerName} 在拒绝前没有记录调用尝试（审计链断在拒绝分支上）"


class TestSweepSameContract:
    """整体禁止"成功信封里自陈占位"，而不是逐点修。"""

    @staticmethod
    def _offenders(rootDir: pathlib.Path) -> list:
        hits = []
        for py in sorted(rootDir.rglob("*.py")):
            text = py.read_text(encoding="utf-8", errors="replace")
            try:
                tree = ast.parse(text)
            except SyntaxError:
                # 解析不来的文件不许让守卫无声跳过
                hits.append(f"{py.name}:Unparseable")
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Return) or not isinstance(node.value, ast.Dict):
                    continue
                pairs = [
                    (key.value, value)
                    for key, value in zip(node.value.keys, node.value.values)
                    if isinstance(key, ast.Constant) and isinstance(key.value, str)
                ]
                reportsSuccess = any(
                    name == "code"
                    and isinstance(value, ast.Constant)
                    and value.value == 0
                    for name, value in pairs
                )
                if not reportsSuccess:
                    continue
                strings = [
                    c.value
                    for c in ast.walk(node.value)
                    if isinstance(c, ast.Constant) and isinstance(c.value, str)
                ]
                if any(re.search("placeholder", t, re.I) for t in strings):
                    hits.append(f"{py.name}:{node.lineno}")
        return hits

    def test_noEndpointReportsSuccessWhileAdmittingPlaceholder(self):
        offenders = self._offenders(ENDPOINT_DIR)
        assert not offenders, (
            "以下位置仍用成功信封裹着自陈占位（教义第 2 条要求诚实 5xx / not_supported）: "
            f"{offenders}"
        )

    def test_sweepDetectorIsNotVacuous(self):
        """正对照：已知违规必须被算出来，否则上一条的绿不可信。"""
        sample = "\n".join([
            "def bad():",
            "    return {",
            '        "code": 0,',
            '        "message": "done (placeholder)",',
            '        "data": {},',
            "    }",
        ])
        tmpDir = pathlib.Path(tempfile.mkdtemp())
        try:
            (tmpDir / "sample_endpoint.py").write_text(sample, encoding="utf-8")
            found = self._offenders(tmpDir)
        finally:
            shutil.rmtree(tmpDir, ignore_errors=True)
        assert found, "扫描器算不出已知违规 ⇒ 判据整体失效，test_noEndpoint... 的绿无意义"

    def test_crossFunctionBodiesAreNotOverCaptured(self):
        """负对照：字样相近但分属两个返回体，不得误报。

        本判据初版用跨行正则 `return\\s*\\{(.*?)\\n\\s*\\}` 时，会把**别的函数**的
        字样吞进当前返回体，于是真命中六个却误报整份 computer.py。
        AST 给的是节点边界，不靠缩进对齐运气。
        """
        sample = "\n".join([
            "def ok_but_wordy():",
            "    return {",
            '        "code": 0,',
            '        "message": "Scrape complete",',
            '        "data": {},',
            "    }",
            "",
            "def honest_refusal():",
            "    # the word placeholder appears only in a comment nearby",
            "    return {",
            '        "code": 501,',
            '        "detail": "placeholder behaviour removed",',
            "    }",
        ])
        tmpDir = pathlib.Path(tempfile.mkdtemp())
        try:
            (tmpDir / "neg_endpoint.py").write_text(sample, encoding="utf-8")
            assert not self._offenders(tmpDir), "扫描器跨函数过采样：把别人的字样算进来了"
        finally:
            shutil.rmtree(tmpDir, ignore_errors=True)
