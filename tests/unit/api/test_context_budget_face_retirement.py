# -*- coding: utf-8 -*-
"""T-09：假预算面下架——端点 + 前端包装 + 锁 URL 的测试同删（Issue #90 §10 第 2 项）。

## 为什么这是「下架」而不是「修读数」

审计 P2-2 的原始形态是**假读数**：GET 恒返回硬编码 `16000/0/16000`、PUT 恒返回
成功而零效果，两个分支都挂在 `agent.unified_injector` 上——该属性全仓零赋值点。
B6-2 把读数接回了真源（`ContextOrchestrator` 的窗口预算，取不到即 503 点名），
**假读数这一面已消**，剩下的判定是「这个 HTTP 面还要不要」。

判定依据（工单 §10 第 2 项已给，2026-09-21 核过前端消费面）：

- `NeurUI/src/api/modules/context.ts` 的两个包装函数**无任何 .vue / store 调用**；
- 唯一的「引用」是 `api-modules.test.ts` 里锁 URL 的两条用例——那是**锁自己**，
  不构成消费方。

于是它是一个「无消费者却有对外契约」的面。按修复教义第 5 条（放大视角），下架
必须**整条契约一次扫净**，否则会在别处长出新的孤儿：端点删了而编排器上的读写方法
留着，就是新鲜的「零生产消费点」。

## 契约搬到哪面（不是凭空删）

两个事实都有**有真实消费者的面**在serving：

| 事实 | 下架面（无消费者） | 真面（有消费者） |
|---|---|---|
| 本轮 prompt 实测规模 | `get_token_budget()["used_tokens"]` | `GET /context/composition` 的 `total_tokens` |
| 模型上下文窗口 | `get_token_budget()["max_tokens"]` | 同响应的 `context_window` |

`/context/composition` 的消费者是聊天页环图（`ContextUsageIndicator.vue`），
且它读的就是同一份 compose 侧实测快照。故本下架**不移除任何事实**，只移除
第二份对外契约——这正是「单一事实源」要求的形态。

## 本守卫钉什么

1. 路由表里不再有 `/token-budget`（GET / PUT）；
2. 前端模块不再导出这两个包装（含类型声明）；
3. 仓内（前端 + 测试）不再有任何锁该 URL 的字符串——「同删」是机器可验的；
4. 编排器上不在保留只服务该端点的读写方法（否则是新的零消费点）。
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
GUARD_REL = "tests/unit/api/test_context_budget_face_retirement.py"

CONTEXT_ENDPOINT = PROJECT_ROOT / "neurova" / "api" / "endpoints" / "context.py"
FRONTEND_MODULE = PROJECT_ROOT / "NeurUI" / "src" / "api" / "modules" / "context.ts"

#: 下架面的 URL 形态：后端字面量 `/context/token-budget`，前端模板 `${BASE}/token-budget`。
#: 负向断言 `(?![-\w/{])` 把 `/context-pool/pool-settings/token-budget/{model}` 排除——
#: 那是**另一个面**的路径（`ContextPool.get_token_budget_for_model`，有真实消费者），
#: 不在本单范围内，误伤它就是把两个面当成一个面。
RETIRED_URL_PATTERN = re.compile(r"(?:/context/token-budget|\$\{BASE\}/token-budget)(?![-\w/{])")

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
    if (isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)):
        return id(first.value)
    return 0


def _stripJsComments(text: str) -> str:
    """抹掉 JS/TS/Vue 的 `//` 与 `/* */` 注释，**保留行数**（行号要对得上）。

    引号（含模板串反引号）内的 `//` 不是注释——`https://` 即此形态，
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
#: （后端常量 `/context/token-budget`、前端模板 `${BASE}/token-budget`），
#: 连这两个字都没出现的文件不可能命中——预筛只缩"要解析哪些文件"，
#: 不参与"怎么判"（`tests/ast_scan.sourceRefsUnder` 的同一口径）。
TEXT_HINT = "token-budget"
TEXT_HINTS = (TEXT_HINT,)


def _codeReferences(root: Path) -> list:
    """`root` 子树里**可执行代码**引用该 URL 的命中点 `(路径, 行号)`。

    判定面是「代码里的字面量」，不是「文本里出现过该串」——注释与 docstring
    里的提及是叙述。两侧语言同一口径，各自按语言形态取字面量。

    取数走本仓唯一 AST 入口 `tests/ast_scan`（预筛 + 整进程复用解析）：
    解析量与**命中面**挂钩，不随代码总量涨（`tests/` 下近两千个 `.py` 里含该词的
    只有个位数；全量 parse 会与本仓「判据不得与代码总量捆绑」的门禁同形）。
    前端侧取文本（同一预筛入口），按状态机剥注释后逐行匹配。
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
        # f-string 的静态片段本身也是 `Constant` 节点（`ast.walk` 会同时走到
        # `JoinedStr` 与它的每个片段），故按位置去重，避免同一处报两次。
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


class TestRetiredRouteIsGone:
    """路由表里不再有该面——「删了函数但装饰器还在」这类半删会被抓到。"""

    def test_router_serves_no_token_budget_route(self):
        from neurova.api.endpoints import context as endpoint

        paths = {
            (getattr(route, "path", ""), method)
            for route in endpoint.router.routes
            for method in (getattr(route, "methods", None) or ())
        }
        offenders = sorted(p for p in paths if p[0] == "/token-budget")
        assert not offenders, (
            f"上下文端点仍挂着假预算路由 {offenders} —— 该面无任何非测试消费者"
            "（工单 §10 第 2 项），下架必须连端点一起去掉。"
        )

    def test_no_budget_holder_resolver_left_behind(self):
        """`_resolve_budget_holder` 只服务那两个路由，路由没了它就该没了。"""
        source = CONTEXT_ENDPOINT.read_text(encoding="utf-8")
        assert "_resolve_budget_holder" not in source, (
            "`_resolve_budget_holder` 仍留在端点模块里 —— 只服务已下架路由的解析函数"
            "留着就是新的零消费点（修复教义第 5 条：同一契约整条扫净）。"
        )


class TestRetiredFrontendWrapperIsGone:
    """前端包装同删——留着就是「调用一个后端已不存在的路径」的幻影契约。"""

    def test_frontend_module_exposes_no_budget_wrapper(self):
        source = FRONTEND_MODULE.read_text(encoding="utf-8")
        offenders = [
            name
            for name in ("getTokenBudget", "setTokenBudget", "interface TokenBudget")
            if name in source
        ]
        assert not offenders, (
            f"前端 context 模块仍导出已下架面的包装：{offenders}\n"
            "后端路由已删，留着的包装一调就 404（幻影契约）。"
        )


class TestRetiredUrlIsNotLockedAnywhere:
    """代码里锁该 URL 的必须同删：它是唯一「消费」该面的东西，留着等于锁一个空契约。

    判定面只认**代码里的字面量**（根因与反向控制在
    `TestRetiredUrlJudgementReadsCodeNotProse`）。
    """

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
            "仓内仍有代码/测试锁着已下架的预算 URL：\n  "
            + "\n  ".join(offenders[:12])
            + "\n修法：端点、前端包装、锁 URL 的测试三处同删（工单 §10 第 2 项）。"
        )


class TestRetiredUrlJudgementReadsCodeNotProse:
    """判据的判定面必须停在「代码」上：注释与 docstring 里的提及是叙述。

    根因（本轮 CI 实测，构建 `cnb-7n5-1k3cvqhq6`）：判据按**文本**逐行匹配 URL，
    于是把 live-verify 脚本 `tests/manual/context_budget_face_retirement_90.py`
    模块 docstring 里的两行说明判成违规 —— 那两行的内容是「断言该 URL 已不在
    对外契约里」，**与「锁该 URL」正好相反**（负向判据的叙述被当成了它的反面）。

    修法不是豁免某个文件：豁免会把该文件变成免检通道（真正的锁 URL 代码写进去
    也不会红）。判据要修在判定处 —— 靶点从来是「有没有代码指向这个面」，
    文档里点名它反而正是判据自己的工作方式（本守卫自身也不得不写这个 URL）。
    """

    _PROSE = (
        '"""说明：`/context/token-budget` 已下架，见台账 §30。"""\n'
        "\n"
        "def use() -> str:\n"
        '    \"\"\"docstring 里再提一次 /context/token-budget，不算引用。\"\"\"\n'
        "    return 'x'\n"
    )
    _LOCKING = (
        "PAT = '/context/token-budget'\n"
        "OTHER = f'/context/token-budget'\n"
    )
    _LOCKING_TS = (
        "// 注释里的 ${BASE}/token-budget 是叙述\n"
        "/* 块注释里的 ${BASE}/token-budget 也是叙述 */\n"
        "const url = `${BASE}/token-budget`\n"
        "const link = 'https://example.com//keep'\n"
    )

    def test_prose_is_not_a_lock(self, tmp_path):
        """docstring / 注释里的提及 → 零命中（同一输入在旧口径下会红）。"""
        (tmp_path / "prose.py").write_text(self._PROSE, encoding="utf-8")
        (tmp_path / "prose.ts").write_text("// /context/token-budget 已下架\n", encoding="utf-8")
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
            "代码里的字面量未被命中（判据空转）："
            "期望 locker.py 两处（常量 + f-string）、wired.ts 一处（模板串），"
            f"实得 {names}"
        )
        # 模板串里的 `//` 不算注释：`https://example.com//keep` 这一行不得被截断成注释
        assert all(path.name != "prose.ts" for path, _ in hits)

    def test_shipped_repo_has_no_locking_code(self):
        """收官自证：真仓（两个扫描根）在没有豁免任何 live-verify 脚本的前提下零命中。"""
        offenders = []
        for root_name in SCAN_ROOTS:
            root = PROJECT_ROOT / root_name
            if not root.is_dir():
                continue
            for path, lineno in _codeReferences(root):
                relative = path.relative_to(PROJECT_ROOT).as_posix()
                if relative not in SELF_EXEMPT:
                    offenders.append(f"{relative}:{lineno}")
        assert not offenders, f"真仓仍有代码锁着该 URL：{offenders}"


class TestOrchestratorBudgetFaceIsGone:
    """编排器上只服务该端点的读写方法一并退役——否则是新鲜的零消费点。"""

    def test_orchestrator_has_no_budget_read_write_face(self):
        from neurova.context.orchestrator import ContextOrchestrator

        offenders = [
            name
            for name in ("get_token_budget", "set_token_budget")
            if hasattr(ContextOrchestrator, name)
        ]
        assert not offenders, (
            f"`ContextOrchestrator` 仍保留 {offenders} —— 它们的唯一消费方是已下架的"
            "端点（B6-2 为接真读数而加）。留着就是「写了没人读」的断点，"
            "且与 `/context/composition` 的实测快照构成第二份对外读数。"
        )


class TestLiveFactsStillHaveTheirRealFace:
    """契约搬到真面：下架不得移除任何事实（否则就是"删干净"式的能力净损失）。"""

    def test_composition_endpoint_still_serves_both_facts(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from neurova.api.auth import get_current_user
        from neurova.api.endpoints import context as endpoint
        from neurova.context.composition import measure_composition, reset_composition

        reset_composition()
        measure_composition(
            "agent-budget-retire",
            [{"role": "user", "content": "本轮 prompt 正文" * 20}],
            None,
            context_window=128000,
        )
        app = FastAPI()
        app.include_router(endpoint.router, prefix="/context")
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1"}
        try:
            resp = TestClient(app).get(
                "/context/composition", params={"agent_id": "agent-budget-retire"}
            )
        finally:
            app.dependency_overrides.clear()
            reset_composition()

        assert resp.status_code == 200, resp.text[:300]
        data = resp.json()
        assert data["total_tokens"] > 0, (
            "「本轮 prompt 实测规模」这一事实在下架后取不到了 —— "
            "它必须由有真实消费者的 `/context/composition` 承担（total_tokens）。"
        )
        assert data["context_window"] == 128000, (
            "「模型上下文窗口」这一事实在下架后取不到了 —— "
            "同响应应以 context_window 提供。"
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
