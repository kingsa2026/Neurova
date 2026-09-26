# -*- coding: utf-8 -*-
"""T-09 §10 第 2b 项：上下文池设置假面下架（Issue #90）。

## 为什么是「下架」而不是「接真值」

工单 §10 第 2b 项给这个面留了两条路，并把裁定权挂给 T-07（持久层 spec）：

> `api/endpoints/context_pool_settings.py` + `NeurUI/src/api/modules/context-pool.ts`
> **同样零 .vue 消费者**，只有 `api-modules.test.ts:228-244` 锁 URL。
> 与上一条同性质，一并处置；注意 `max_size` 在池侧已失效
> （`context_pool.py`），所以这个设置面就算接上也是假的 —— 它归 T-07 统一定夺。

T-07 的 spec 与本工单集（001–009）已全部交付，**但从未对这个面作出裁定** ——
它成了 T-09 唯一悬空的判定项。本票把它裁定完，依据是三条事实，逐条可复核：

### 一、零非测试消费者（与第 2 项同性质）

```
grep -rn 'contextPool|context-pool|PoolSettings' NeurUI/src --include=*.vue --include=*.ts
  NeurUI/src/api/modules/context-pool.ts        ← 包装自身
  NeurUI/src/api/modules/index.ts:33            ← 再导出（barrel）
  NeurUI/src/api/modules/__tests__/api-modules.test.ts  ← 锁 URL 的用例（锁自己）
```

唯一的「引用」是锁 URL 的测试 —— 那是**锁自己**，不构成消费方（同 §10 第 2 项
对假预算面的认定口径）。

### 二、这个面就算接上也是假的（工单原话，实测复核）

`GET /pool-settings` 返回 `_default_pool_settings` 这份**模块级常量**：

```
"max_size": 100,            ← ADR-0015 已判失效（池不按容量驱逐）
"max_size_effective": False,
"resident_limit": None,
"ttl_seconds": 3600,        ← 池的真值是 0（生产构造面 ttl_seconds=0）
"default_token_budget": 16000,
"model_budgets": {...12 项...}   ← ContextPool._STATIC_MODEL_BUDGETS 的第二份副本
```

- `ttl_seconds` 的**两份定义**：端点说 3600，池生产构造走 `ttl_seconds=0`
  （`orchestrator` 的永不丢失档），响应里的 3600 与任何活对象无关；
- `model_budgets` 是 `ContextPool._STATIC_MODEL_BUDGETS` 的**第二份表**
  （键集逐字相同），同一契约两份定义（修复教义第 6 条）；
- `PUT` 已于 2026-09-12 改 501 如实上报「未与运行时接线」。

即：**这个「设置面」既不可写，读出来的也不是任何活池的当前值。**

### 三、两个事实都有真有消费者的面在 serving（不是凭空删）

| 事实 | 下架面（无消费者） | 真面（有消费者） |
|---|---|---|
| 池常驻规模 / 各原因回收计数 / 归档规模 | `GET /pool-settings` 的常量 | `/metrics` 的 `neurova_context_pool_entries` / `_evicted_total` / `_ledger_rows`（`MetricsCollector.observe_context_pools`，抓取期读 `get_retention_stats()`） |
| 模型上下文窗口与视图预算 | `GET /pool-settings/token-budget/{model}` | `/context/composition` 的 `context_window`（消费者 = 聊天页环图 `ContextUsageIndicator.vue`） |

故本下架**不移除任何事实**，只移除第二份对外契约。

## 「一并处置」的边界（放大视角，教义第 5 条）

同契约的命中点一次扫净：端点模块、注册表行、前端模块与 barrel 再导出、锁 URL 的
用例、文档与生成物。**但有一处不能删** —— `ContextPool.get_token_budget_for_model`：

它有**真实生产消费者**（`orchestrator.__init__` 取模型窗口算视图预算、
`_compute_window_budget` 的元数据路径），是池侧的活能力，不是这个 HTTP 面的附属。
删它就是「把同一个动词的两个面当成一个面」（与 §30 保留它同一条判据）。
本守卫配反向控制专钉这一条。

## 本守卫钉什么

1. 注册表里不再有该模块，真装配路由表里不再有 `/api/v1/context-pool`；
2. 前端不再有 `context-pool.ts` 与 `contextPool` 再导出；
3. 仓内（前端源码 + 测试根）不再有**代码**锁该 URL —— 判定面停在字面量上，
   注释与 docstring 里的提及不算（根因与反向控制见
   `TestRetiredUrlJudgementReadsCodeNotProse`）；
4. 两个事实仍由真面 serving（`/metrics` 的池 gauges 与 `/context/composition`）；
5. 池侧的 `get_token_budget_for_model` **必须仍在**（反向控制）。
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests import ast_scan

PROTECTED = PROJECT_ROOT / "scripts" / "ci" / "protected_tests.txt"
GUARD_REL = "tests/unit/api/test_context_pool_settings_face_retirement.py"

ENDPOINT_MODULE = (
    PROJECT_ROOT / "neurova" / "api" / "endpoints" / "context_pool_settings.py"
)
FRONTEND_MODULE = PROJECT_ROOT / "NeurUI" / "src" / "api" / "modules" / "context-pool.ts"
FRONTEND_BARREL = PROJECT_ROOT / "NeurUI" / "src" / "api" / "modules" / "index.ts"

#: 下架面的 URL 形态：后端前缀 `/v1/context-pool`，前端模板 `/context-pool`。
#: 负向断言把 `/context-pool-settings` 排除 —— 那是 README 里的历史口径字符串，
#: 不在本票范围内，误伤它就是把两个面当一个面。
RETIRED_URL_PATTERN = re.compile(r"/v1/context-pool(?![-\w])|(?<!/v1)/context-pool(?![-\w])")

#: 锁该 URL 的字符串可能出现的两个根（前端源码 + 测试根）。
SCAN_ROOTS = ("NeurUI/src", "tests")
PY_SUFFIX = ".py"
FRONTEND_SUFFIXES = (".ts", ".vue", ".js")

#: 本守卫自身要写这个 URL 才能做负向断言，故显式豁免（不靠"它能读到自己"这条巧合）。
SELF_EXEMPT = {GUARD_REL}


def _literalText(node) -> str:
    """节点承载的字符串文本：常量字面量，或 f-string 的静态片段拼接。

    f-string 在 Python 里即使无占位符也是 `JoinedStr`（实测 `f"/x"` 即此形态），
    只认 `ast.Constant` 会漏掉「用 f-string 拼后端 URL」这一半写法。
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            part.value
            for part in node.values
            if isinstance(part, ast.Constant) and isinstance(part.value, str)
        )
    return ""


#: 函数/类/模块体首条字符串 = docstring（`ast.walk` 是**广度优先**，父节点必先于
#: 子节点出现，故单趟即可把「文档节点」认全，不必物化整棵树）。
DOCSTRING_OWNERS = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


def _docstringValue(owner) -> int:
    """`owner` 的 docstring 字面量节点 `id()`；无 docstring 时回 0。

    回 `id()` 是因为调用方要在**节点流**里认出「这一个节点是文档」——
    判定面因此停在可执行代码上，与本仓其余「注释里提一句不算引用」的判据同形。
    """
    body = getattr(owner, "body", None) or []
    first = body[0] if body else None
    if (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    ):
        return id(first.value)
    return 0


def _stripJsComments(text: str) -> str:
    """抹掉 JS/TS/Vue 的 `//` 与 `/* */` 注释，**保留行数**（行号要对得上）。

    引号（含模板串反引号）内的 `//` 不是注释 —— `https://` 即此形态，
    按子串直接截断会把真命中一起抹掉。故按状态机扫，不做正则近似。
    """
    lines = []
    inBlock = False
    for raw in text.splitlines():
        line = raw
        if inBlock:
            end = line.find("*/")
            if end < 0:
                lines.append("")
                continue
            line = " " * (end + 2) + line[end + 2:]
            inBlock = False
        out = []
        index = 0
        quote = None
        while index < len(line):
            char = line[index]
            if quote:
                out.append(char)
                if char == "\\" and index + 1 < len(line):
                    out.append(line[index + 1])
                    index += 2
                    continue
                if char == quote:
                    quote = None
                index += 1
                continue
            if char in "\"'`":
                quote = char
                out.append(char)
                index += 1
                continue
            if line.startswith("//", index):
                break
            if line.startswith("/*", index):
                end = line.find("*/", index + 2)
                if end < 0:
                    inBlock = True
                    break
                index = end + 2
                continue
            out.append(char)
            index += 1
        lines.append("".join(out))
    return "\n".join(lines)


#: 文本预筛词：URL 的**共同片段**。两侧语言都以它拼出该 URL
#: （后端常量 `/v1/context-pool`、前端模板 `/context-pool`），
#: 连这几个字都没出现的文件不可能命中 —— 预筛只缩「要解析哪些文件」，
#: 不参与「怎么判」（`tests/ast_scan.sourceRefsUnder` 的同一口径）。
TEXT_HINTS = ("context-pool", "context_pool_settings")


def _codeReferences(root: Path) -> list:
    """`root` 子树里**可执行代码**引用该 URL 的命中点 `(路径, 行号)`。

    判定面是「代码里的字面量」，不是「文本里出现过该串」—— 注释与 docstring
    里的提及是叙述。两侧语言同一口径，各自按语言形态取字面量。
    """
    hits = []
    seen = set()
    docstrings = set()
    for path, node in ast_scan.nodeScan(root, PY_SUFFIX, TEXT_HINTS):
        if isinstance(node, DOCSTRING_OWNERS):
            anchor = _docstringValue(node)
            if anchor:
                docstrings.add(anchor)
            continue
        if id(node) in docstrings:
            continue
        text = _literalText(node)
        if not text or not RETIRED_URL_PATTERN.search(text):
            continue
        if (path, node.lineno) in seen:
            continue
        seen.add((path, node.lineno))
        hits.append((path, node.lineno))
    for suffix in FRONTEND_SUFFIXES:
        for reference in ast_scan.sourceRefsUnder(root, suffix, TEXT_HINTS):
            code = _stripJsComments(reference.code)
            for lineno, line in enumerate(code.splitlines(), start=1):
                if RETIRED_URL_PATTERN.search(line):
                    hits.append((reference.path, lineno))
    return hits


def _registeredModules() -> set:
    import neurova.api.endpoints as endpoints_pkg

    return {module for module, _prefix, _desc in endpoints_pkg.ENDPOINT_MODULES}


class TestEndpointModuleIsGone:
    """端点模块退役 + 注册表行删净 —— 「删了文件但注册表还在」这类半删会被抓到。"""

    def test_endpoint_module_not_importable(self):
        import importlib

        import pytest

        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("neurova.api.endpoints.context_pool_settings")

    def test_endpoint_file_removed(self):
        assert not ENDPOINT_MODULE.is_file(), (
            f"{ENDPOINT_MODULE.relative_to(PROJECT_ROOT)} 仍在仓里 —— "
            "该面无任何非测试消费者，下架必须连模块一起去掉。"
        )

    def test_registry_has_no_entry(self):
        offenders = sorted(
            m for m in _registeredModules() if m.endswith(".context_pool_settings")
        )
        assert not offenders, (
            f"端点注册表仍挂着已下架的面：{offenders} —— 半删（文件没了、注册表还在）"
            "会让启动期 ERROR 日志常驻，属新的断点。"
        )


class TestMountedRouteIsGone:
    """真装配路由表里不再有该前缀 —— 「模块删了但别处又挂上」会被抓到。"""

    def test_no_mounted_leaf_route_under_retired_prefix(self):
        from neurova.api.app import create_app
        from tests.route_table import mountedLeafRoutes

        paths = {path for path, _route in mountedLeafRoutes(create_app())}
        offenders = sorted(p for p in paths if p.startswith("/api/v1/context-pool"))
        assert not offenders, (
            f"真装配路由表里仍有该前缀：{offenders} —— 下架必须是真的从对外契约里消失。"
        )

    def test_composition_face_still_mounted(self):
        """下架不得把同批事实的真面一起删掉（能力净损失）。"""
        from neurova.api.app import create_app
        from tests.route_table import mountedLeafRoutes

        paths = {path for path, _route in mountedLeafRoutes(create_app())}
        assert "/api/v1/context/composition" in paths, (
            "承载模型窗口事实的真面不见了 —— 下架把能力一起删掉了。"
        )


class TestFrontendFaceIsGone:
    """前端模块与 barrel 再导出同删 —— 留着就是「调一个后端已不存在的路径」的幻影契约。"""

    def test_frontend_module_removed(self):
        assert not FRONTEND_MODULE.is_file(), (
            f"{FRONTEND_MODULE.relative_to(PROJECT_ROOT)} 仍在仓里 —— "
            "后端路由已删，留着的包装一调就 404（幻影契约）。"
        )

    def test_barrel_no_longer_reexports_it(self):
        source = FRONTEND_BARREL.read_text(encoding="utf-8")
        assert "context-pool" not in _stripJsComments(source), (
            "barrel（index.ts）仍在再导出已下架的前端模块 —— 再导出即对外契约。"
        )


class TestRetiredUrlIsNotLockedAnywhere:
    """代码里锁该 URL 的必须同删：它是唯一「消费」该面的东西。"""

    def test_no_source_or_test_locks_the_retired_url(self):
        offenders = []
        for root_name in SCAN_ROOTS:
            root = PROJECT_ROOT / root_name
            if not root.is_dir():
                continue
            for path, lineno in _codeReferences(root):
                relative = path.relative_to(PROJECT_ROOT).as_posix()
                if relative in SELF_EXEMPT:
                    continue
                offenders.append(f"{relative}:{lineno}")
        offenders.sort()
        assert not offenders, (
            "仓内仍有代码/测试锁着已下架的池设置 URL：\n  "
            + "\n  ".join(offenders[:12])
            + "\n修法：端点、注册表行、前端包装 + barrel、锁 URL 的测试同删"
            "（工单 §10 第 2b 项）。"
        )


class TestRetiredUrlJudgementReadsCodeNotProse:
    """判据的判定面必须停在「代码」上：注释与 docstring 里的提及是叙述。

    这与 §30 的同类守卫同形（构建 `cnb-7n5-1k3cvqhq6` 实测过它的必要性）：
    按**文本**逐行匹配会把 live-verify 脚本里「断言该面已下架」的说明判成
    「锁该面」—— 负向判据的叙述被当成了它的反面。
    """

    _PROSE = (
        '"""说明：`/v1/context-pool` 已下架，见台账 §32。"""\n'
        "\n"
        "def use() -> str:\n"
        '    """docstring 里再提一次 /v1/context-pool，不算引用。"""\n'
        "    return 'x'\n"
    )
    _LOCKING = "PAT = '/v1/context-pool'\nOTHER = f'/v1/context-pool'\n"
    _LOCKING_TS = (
        "// 注释里的 /context-pool 是叙述\n"
        "/* 块注释里的 /context-pool 也是叙述 */\n"
        "const BASE = '/context-pool'\n"
        "const link = 'https://example.com//keep'\n"
    )

    def test_prose_is_not_a_lock(self, tmp_path):
        (tmp_path / "prose.py").write_text(self._PROSE, encoding="utf-8")
        (tmp_path / "prose.ts").write_text("// /v1/context-pool 已下架\n", encoding="utf-8")
        hits = _codeReferences(tmp_path)
        assert not hits, (
            "文档里的提及被判成「锁 URL」—— 这是误报：负向叙述与锁契约正好相反。\n"
            f"实得：{hits}"
        )

    def test_code_is_still_a_lock(self, tmp_path):
        """反向控制：代码里的字面量仍必须命中（含 f-string 与模板串）。"""
        (tmp_path / "locker.py").write_text(self._LOCKING, encoding="utf-8")
        (tmp_path / "wired.ts").write_text(self._LOCKING_TS, encoding="utf-8")
        hits = _codeReferences(tmp_path)
        names = sorted(path.name for path, _lineno in hits)
        assert names == ["locker.py", "locker.py", "wired.ts"], (
            "代码里的字面量未被命中（判据空转）：期望 locker.py 两处（常量 + f-string）、"
            f"wired.ts 一处（模板串），实得 {names}"
        )
        assert all(path.name != "prose.ts" for path, _ in hits)


class TestLiveFactsStillHaveTheirRealFace:
    """契约搬到真面：下架不得移除任何事实（否则就是"删干净"式的能力净损失）。"""

    def test_metrics_still_serves_pool_retention_facts(self):
        """池常驻/回收/归档规模仍可从 `/metrics` 的 gauges 读到（真读取面）。"""
        from prometheus_client import REGISTRY

        from neurova.context_pool import ContextPool
        from neurova.core.metrics import get_metrics

        pool = ContextPool(user_id="u-retire", agent_id="a-retire", session_id="s1")
        try:
            get_metrics().observe_context_pools()
        finally:
            pool.close()

        for name in (
            "neurova_context_pool_entries",
            "neurova_context_pool_evicted_total",
            "neurova_context_pool_ledger_rows",
        ):
            samples = [
                s
                for metric in REGISTRY.collect()
                if metric.name == name
                for s in metric.samples
            ]
            assert samples, (
                f"`/metrics` 上取不到 `{name}` —— 「池规模/回收」这一事实在下架后没有真面"
                "（它必须由 observe_context_pools 的 gauges 承担）。"
            )

    def test_composition_endpoint_still_serves_context_window(self):
        """模型上下文窗口这一事实仍由 `/context/composition` 的 context_window 提供。"""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from neurova.api.auth import get_current_user
        from neurova.api.endpoints import context as endpoint
        from neurova.context.composition import measure_composition, reset_composition

        reset_composition()
        measure_composition(
            "agent-pool-retire",
            [{"role": "user", "content": "本轮 prompt 正文" * 20}],
            None,
            context_window=128000,
        )
        app = FastAPI()
        app.include_router(endpoint.router, prefix="/context")
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1"}
        try:
            resp = TestClient(app).get(
                "/context/composition", params={"agent_id": "agent-pool-retire"}
            )
        finally:
            app.dependency_overrides.clear()
            reset_composition()

        assert resp.status_code == 200, resp.text[:300]
        assert resp.json()["context_window"] == 128000, (
            "「模型上下文窗口」这一事实在下架后取不到了 —— "
            "它必须由有真实消费者的 `/context/composition` 承担。"
        )


class TestPoolSideCapabilitySurvives:
    """反向控制：池侧的模型窗口查询**不能**被连带删掉（放大视角的边界）。

    `get_token_budget_for_model` 与这个 HTTP 面是两个东西：它是池的活能力，
    生产消费者在 `orchestrator.__init__`（取模型窗口算视图预算）。把它一起删掉
    就是「删干净」式的能力净损失 —— 本用例若红，说明下架越界了。
    """

    def test_pool_token_budget_for_model_still_exists(self):
        from neurova.context_pool import ContextPool

        assert hasattr(ContextPool, "get_token_budget_for_model"), (
            "池侧的模型窗口查询被连带删掉了 —— 它有真实生产消费者"
            "（orchestrator 构造期算视图预算），不是这个 HTTP 面的附属。"
        )
        assert ContextPool.get_token_budget_for_model("gpt-4") == 4915, (
            "池侧查询的读数变了（model_limits 8192 × 0.6 = 4915）"
        )


class TestGuardIsInProtectedSubset:
    def test_listed_in_protected_tests(self):
        listed = {
            line.split("#", 1)[0].strip()
            for line in PROTECTED.read_text(encoding="utf-8").splitlines()
            if line.split("#", 1)[0].strip()
        }
        assert GUARD_REL in listed, (
            f"{GUARD_REL} 不在受保护子集 —— 本守卫的判据在 CI 上不会执行"
            "（B5 收口时正是这个形态：文件在仓、单跑全绿、清单里没有）。"
        )
