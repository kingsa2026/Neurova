# -*- coding: utf-8 -*-
"""「本轮哪个用户」的两条通道之间，一致性由这张表与代码实状逐条对账（台账 §6-121 的 (a) 档）。

用户 2026-10-10 裁「先补一枚判据、合并另批」。落之前先复算所有写方的实际取值，
**推荐档原本那句"同一轮两读数必须相等"被证伪**——五处写方里没有一处可以笼统地这么判：

| 入口 | request 侧（`neurova_request_user_id`）读的是 | 轮身份侧（`neurova_turn_user_id`） |
| --- | --- | --- |
| `agent/chat_pipeline.py:477` | `(ctx.metadata or {}).get("user_id")`（调用者本人） | **同一个表达式**（`:613` 传给 `set_request_identity`） |
| `channels/channel_router.py:180` | `agent.config.owner_user_id`（渠道会话落盘归属） | 该入口的 `meta` **没有 `user_id` 键** ⇒ 轮身份落缺省 `"default"`（§6-123） |
| `api/endpoints/computer.py:729` | `get_current_user()["user_id"] or "default"`（浏览器 profile 池化） | 该入口不跑对话轮，不写轮身份 |
| `tool_executor.py:2229` | `self._agent_identity()[0]` —— 就是轮身份那一侧的读数转写过来 | 它不写，它读（读取序由 `test_b5_identity_read_order.py` 守） |
| `tool_layers/mcp_server.py:192` | `get_request_user_id()` —— 同一条通道自读自写（MCP 执行链透传） | 不涉及 |

所以本批不写"必须相等"那条恒假判据（写了就是拿一条谎报当守卫，且渠道那格当场红），
而是钉四件各自成立、且各自真会咬的事：

① **写方文件集合必须与这张表逐条相等**（`set_request_user_id`/`clear_request_user_id`）——
   新增第六个入口而不同步说明它的来源即红。漂移正是从"多一个入口没人对照"开始的；
   这张表初版只有三行，是 ① 自己把 `tool_executor` 与 `mcp_server` 两处补出来的
   （先前的 grep 被 `head` 截断 ⇒ 少数两处；"命中数被截断骗过"本卷已记，此处再证一次）。
② 标 `sameSource` 的入口：两处调用点的**来源表达式必须逐字同形**（允许 `or None` /
   `or "default"` 这类缺省补皮）——网页聊天那条链上"进记忆隔离的身份"与"进浏览器归属的
   身份"必须同一个读法，改任一侧即红。
③ 标 `derivedFromTurnRead` / `sameChannelPassThrough` / `noTurnWrite` 的入口：**该文件不得出现
   轮身份写入点**（否则"它不写轮身份"这句声明就过期了），且必须真的在同一个函数里
   读它声明的那个来源口（`_agent_identity` / `get_request_user_id`）。
④ 渠道那一格额外钉死"它的 meta 里没有 `user_id` 键"——这正是 §6-123 那条后果的成因；
   谁往里加了 `user_id`，本判据就逼他先去看 §6-123，而不是让渠道隔离语义静默改写。

分工（不重复既有判据）：轮身份自身只有一个写入口由
`tests/unit/agent/test_turnIdentitySingleSource.py` 守；`Agent._current_user_id` 与 public
别名的**读取序**由 `tests/unit/agent/test_b5_identity_read_order.py` 守。本文件只管
**两条 ContextVar 通道之间**的一致性来源，不复述它们。

未解决、且本批刻意不解决的（(a) 档的全部范围就是"让漂移可见"）：
渠道入口那格暴露的"渠道对话的轮身份落 `"default"`"⇒ 同一 agent 上所有外部发送者共享
同一个隔离域，已另立 §6-123 待裁；两条通道的合并本身是 §6-121 的 (b) 档，另批。
"""

import ast
from pathlib import Path
from typing import Dict, List

from tests import ast_scan

REPO_ROOT = Path(__file__).resolve().parents[3]
PRODUCTION = REPO_ROOT / "neurova"

#: 写 request 侧通道的两个入口函数名（清槽也算：它同样决定"这一轮是谁"）。
REQUEST_WRITERS = ("set_request_user_id", "clear_request_user_id")
#: 轮身份侧的门面函数名（②要对账的就是它的 `user_id=` 实参）。
TURN_WRITER = "set_request_identity"

#: 允许的"这一格为什么不漂"的说法，每一种在下面都有对应的机器检查。
KINDS = ("sameSource", "derivedFromTurnRead", "sameChannelPassThrough", "noTurnWrite")

ENTRY_POINTS: Dict[str, Dict[str, object]] = {
    "neurova/agent/chat_pipeline.py": {
        "kind": "sameSource",
        "requestSource": "ctx.metadata['user_id']（调用者本人）",
        "turnSource": "同一表达式经 _init_agent_state 传给 set_request_identity",
    },
    "neurova/tool_executor.py": {
        "kind": "derivedFromTurnRead",
        "requestSource": "self._agent_identity()[0]",
        "turnSource": "不写轮身份；它读的就是轮身份那一侧的读数再转写（读取序见 B-5 判据）",
        "readsVia": "_agent_identity",
        # `_agent_identity` 是**另一个方法**，所以"读的是轮身份"这句必须在它自己的函数体里验；
        # 只在写入点所在函数里找会把这条跨方法的取值链误判成缺失（本判据第一版正栽在这）。
        "readsViaResolvesTo": "_current_user_id",
    },
    "neurova/tool_layers/mcp_server.py": {
        "kind": "sameChannelPassThrough",
        "requestSource": "self._current_user_id() → get_request_user_id()（MCP 调用方身份沿执行链透传）",
        "turnSource": "不涉及轮身份",
        "readsVia": "_current_user_id",
        "readsViaResolvesTo": "get_request_user_id",
    },
    "neurova/channels/channel_router.py": {
        "kind": "noTurnWrite",
        "requestSource": "agent.config.owner_user_id（渠道会话落盘归属）",
        "turnSource": "该入口不写轮身份；其 meta 不带 user_id 键 ⇒ 轮身份落缺省 default（§6-123）",
        "metaLacksUserId": True,
    },
    "neurova/api/endpoints/computer.py": {
        "kind": "noTurnWrite",
        "requestSource": "get_current_user()['user_id'] or 'default'（浏览器 profile 按用户池化）",
        "turnSource": "该入口不跑对话轮，不写轮身份",
    },
}


def _calleeName(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _stripDefaultTail(values: List[ast.AST]) -> List[ast.AST]:
    """剥掉 `... or None` / `... or "default"` 这类**缺省补皮**。

    不剥就两头失真：`chat_pipeline` 的 request 侧写作
    `(ctx.metadata or {}).get("user_id") or None`，轮身份侧写作
    `(ctx.metadata or {}).get("user_id")` ——同一个来源、两种补皮，逐字比会判它"不同形"，
    把正确的代码报成缺陷；而补皮本身也不是语义差别（两侧各自落各自的缺省）。
    """
    out = list(values)
    while len(out) > 1 and isinstance(out[-1], ast.Constant) \
            and out[-1].value in (None, "default"):
        out.pop()
    return out


def _normalizedNode(expr: ast.AST) -> ast.AST:
    if isinstance(expr, ast.BoolOp) and isinstance(expr.op, ast.Or):
        values = _stripDefaultTail(expr.values)
        if len(values) == 1:
            return _normalizedNode(values[0])
        return ast.BoolOp(op=ast.Or(), values=[_normalizedNode(v) for v in values])
    return expr


def _normalizedDump(expr: ast.AST) -> str:
    if isinstance(expr, ast.BoolOp) and isinstance(expr.op, ast.Or):
        values = _stripDefaultTail(expr.values)
        if len(values) == 1:
            return ast.dump(_normalizedNode(values[0]))
        return ast.dump(ast.BoolOp(op=ast.Or(), values=[_normalizedNode(v) for v in values]))
    return ast.dump(_normalizedNode(expr))


def _callsNamed(scope: ast.AST, names) -> List[ast.Call]:
    return [n for n in ast.walk(scope)
            if isinstance(n, ast.Call) and _calleeName(n) in names]


def _readsNamed(scope: ast.AST, names) -> bool:
    """该作用域里是否"读到"了这些名字之一。三种写法都得认：

    - `foo()` 调用（如 `get_request_user_id()`）；
    - `x.foo` 属性读（property 门面）；
    - `getattr(x, "foo", ...)` 的**第二个位置实参**——轮身份在实现上常走 getattr
      （`_agent_identity` 就是这么读的，见 `tool_executor.py:524`）。
      只认前两种会把这条真实取值链判成不存在（假红）；而把"任意字符串常量"也算上
      又太松（会把注释性文本凑成命中），所以按 getattr 的参数位收口。
    """
    for node in ast.walk(scope):
        if isinstance(node, ast.Call):
            if _calleeName(node) in names:
                return True
            if _calleeName(node) == "getattr" and len(node.args) >= 2 \
                    and isinstance(node.args[1], ast.Constant) \
                    and node.args[1].value in names:
                return True
        if isinstance(node, ast.Attribute) and node.attr in names:
            return True
    return False


def _parents(tree: ast.AST) -> Dict[ast.AST, ast.AST]:
    parents: Dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    return parents


def _enclosingFunction(node: ast.AST, parents: Dict[ast.AST, ast.AST]):
    cur = parents.get(node)
    while cur is not None and not isinstance(
        cur, (ast.FunctionDef, ast.AsyncFunctionDef)
    ):
        cur = parents.get(cur)
    return cur


def requestSideSources(tree: ast.AST) -> List[str]:
    """request 通道写入点的来源表达式（规范化 dump）；无实参（清槽）记 `<no-arg>`。"""
    return [
        _normalizedDump(call.args[0]) if call.args else "<no-arg>"
        for call in _callsNamed(tree, REQUEST_WRITERS)
    ]


def turnSideSources(tree: ast.AST) -> List[str]:
    """轮身份写入点的 `user_id=` 实参表达式（规范化 dump）。"""
    out: List[str] = []
    for call in _callsNamed(tree, (TURN_WRITER,)):
        for keyword in call.keywords:
            if keyword.arg == "user_id":
                out.append(_normalizedDump(keyword.value))
    return out


def dictKeysOfTheFunctionThatWrites(tree: ast.AST) -> List[str]:
    """写 request 通道的那个函数里所有 dict 字面量的字符串键（④ 的靶）。"""
    parents = _parents(tree)
    keys: List[str] = []
    for call in _callsNamed(tree, REQUEST_WRITERS):
        holder = _enclosingFunction(call, parents)
        if holder is None:
            continue
        for node in ast.walk(holder):
            if isinstance(node, ast.Dict):
                for key in node.keys:
                    if isinstance(key, ast.Constant) and isinstance(key.value, str):
                        keys.append(key.value)
    return keys


def productionSources() -> Dict[str, ast.AST]:
    trees = ast_scan.parsedModules(PRODUCTION)
    assert trees, f"生产扫描面为空（{PRODUCTION}）——本文件会空转"
    return {ast_scan.relativeToRepo(path): tree for path, tree in trees}


def writerFiles() -> List[str]:
    return sorted({
        rel for rel, tree in productionSources().items()
        if _callsNamed(tree, REQUEST_WRITERS)
    })


class TestEntryPointsAreDeclared:
    def test_requestUserIdWriterFilesEqualTheTable(self):
        """① 写方清单与登记表逐条相等——多一个入口就是无人对照面。"""
        live = writerFiles()
        assert live == sorted(ENTRY_POINTS), (
            f"`set_request_user_id`/`clear_request_user_id` 的生产写方与登记表不一致：\n"
            f"  实测 {live}\n  表   {sorted(ENTRY_POINTS)}\n"
            "多出来的那一行就是两条通道之间没人对照的面（漂移从这儿开始）；"
            "少掉的那一行说明表在替已消失的代码作保。"
            "新增入口请同时写明 requestSource / turnSource / kind。"
        )

    def test_everyEntryNamesBothSidesAndAnAllowedKind(self):
        """② 的前置：每一格都得说清"两侧各从哪来"，且至少有一格承诺同形。"""
        for rel, entry in ENTRY_POINTS.items():
            assert entry.get("requestSource"), f"{rel} 没写 request 侧来源"
            assert entry.get("turnSource"), f"{rel} 没写轮身份侧来源（拿什么判分叉？）"
            assert entry.get("kind") in KINDS, f"{rel} 的 kind 不在允许集合 {KINDS}"
            if entry["kind"] in ("derivedFromTurnRead", "sameChannelPassThrough"):
                assert entry.get("readsVia"), f"{rel} 声明了派生却没写经由哪个读取口"
        assert any(e["kind"] == "sameSource" for e in ENTRY_POINTS.values()), (
            "所有入口都声明分叉 ⇒ 两条通道没有任何一处保证同读一个来源，"
            "这张表就从「对齐依据」退化成「分歧登记表」"
        )


class TestDeclaredKindsMatchCode:
    def test_sameSourceEntriesReadTheSameExpression(self):
        """② 标 `sameSource` 的入口：两处写入点的来源表达式必须逐字同形。"""
        for rel, entry in ENTRY_POINTS.items():
            if entry["kind"] != "sameSource":
                continue
            tree = productionSources()[rel]
            request, turn = requestSideSources(tree), turnSideSources(tree)
            assert len(request) == 1 and len(turn) == 1, (
                f"{rel} 标 `sameSource` 却不是一个写 request、一个写轮身份"
                f"（request {len(request)} / turn {len(turn)}）："
                "多处取值点时本判据无法回答「是不是同一个来源」，请逐点拆开登记"
            )
            assert request == turn, (
                f"{rel} 标 `sameSource` 但两处读的不是同一来源："
                f"request `{request[0]}` vs turn `{turn[0]}`——同一入口内两侧漂开，"
                "就是「记忆按 A 用户隔离、浏览器 profile 按 B 用户开」那一型"
            )

    def test_otherEntriesDoNotWriteTurnIdentityAndDoReadWhatTheyClaim(self):
        """③ 非 `sameSource` 的格：不得写轮身份（声明就过期了），且要真读它说的那个口。"""
        for rel, entry in ENTRY_POINTS.items():
            if entry["kind"] == "sameSource":
                continue
            tree = productionSources()[rel]
            assert not turnSideSources(tree), (
                f"{rel} 现在写了轮身份，但表里说它不写——kind 需要重新判定"
                "（多半要连 §6-123 一起看，别只改这张表）"
            )
            readsVia = entry.get("readsVia")
            if not readsVia:
                continue
            parents = _parents(tree)
            holders = [_enclosingFunction(call, parents)
                       for call in _callsNamed(tree, REQUEST_WRITERS)]
            assert holders and all(
                holder is not None and _callsNamed(holder, (readsVia,)) for holder in holders
            ), (
                f"{rel} 的 request 写入点所在函数里没有调用 `{readsVia}`："
                "派生说法与代码脱节——它到底从哪儿拿的身份？"
            )
            resolvesTo = entry.get("readsViaResolvesTo")
            if not resolvesTo:
                continue
            accessors = [fn for fn in ast.walk(tree)
                         if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
                         and fn.name == readsVia]
            assert accessors and _readsNamed(accessors[0], (resolvesTo,)), (
                f"{rel} 的 `{readsVia}` 里读不到它声称的 `{resolvesTo}`："
                "「这一格的 request 侧是从那条通道派生的」这句已经不是事实了"
            )

    def test_channelEntryStillLeavesTheTurnSideWithoutAUserId(self):
        """④ 渠道那格额外钉死"meta 不带 `user_id` 键"——§6-123 那条后果的成因。"""
        rel = "neurova/channels/channel_router.py"
        keys = dictKeysOfTheFunctionThatWrites(productionSources()[rel])
        assert "user_id" not in keys, (
            f"{rel} 往 metadata 里加了 `user_id` 键：渠道对话的轮身份不再落缺省，"
            "§6-123 那句「外部发送者共享 default 隔离域」的实状被改写——"
            "先去看那一格再动这里（并把本表的 metaLacksUserId 一并改掉）"
        )


class TestTheComparatorsAreNotVacuous:
    def test_defaultTailIsStrippedButRealDifferencesAreKept(self):
        pairA = ast.parse("(ctx.metadata or {}).get('user_id') or None").body[0].value
        pairB = ast.parse("(ctx.metadata or {}).get('user_id')").body[0].value
        assert _normalizedDump(pairA) == _normalizedDump(pairB), (
            "缺省补皮没被剥掉：正确的代码会被 ② 报成分叉（假红）"
        )
        drifted = ast.parse("(ctx.metadata or {}).get('owner_id') or None").body[0].value
        assert _normalizedDump(pairA) != _normalizedDump(drifted), (
            "换掉 metadata 键名也判同形 ⇒ ② 恒真，本守卫空转"
        )
        assert _normalizedDump(ast.parse("x or 'default'").body[0].value) \
            == _normalizedDump(ast.parse("x").body[0].value), "or 'default' 未被视作缺省补皮"
        assert _normalizedDump(ast.parse("a or b").body[0].value) \
            != _normalizedDump(ast.parse("a").body[0].value), "真实语义差别被剥掉了"

    def test_getattrFormReadsAreRecognisedButRandomStringsAreNot(self):
        """③ 的第三种写法（`getattr(x, "name", …)`）必须被认出，且不能靠松散匹配蒙中。"""
        assert _readsNamed(ast.parse("def f(a):\n    return getattr(a, '_current_user_id', None)\n"),
                           ("_current_user_id",)), (
            "getattr 形式的读取链认不出来——③ 会把真派生报成脱节（假红）"
        )
        assert not _readsNamed(
            ast.parse("def f(a):\n    return {'note': '_current_user_id'}\n"),
            ("_current_user_id",),
        ), "任意字符串常量也被算成读取口——③ 会被无关代码糊过去（放过）"

    def test_aSyntheticSixthEntryPointIsCaught(self):
        """①②③④ 的靶：合成一个"新入口"，四台检出器都必须对它出声。"""
        synthetic = ast.parse(
            "def _probe(meta):\n"
            "    from neurova.core.identity_context import set_request_user_id\n"
            "    set_request_user_id(meta['u'])\n"
            "    data = {'user_id': meta['u'], 'role': 'user'}\n"
            "    set_request_identity(user_input='x', user_id=meta['u'])\n"
            "    return data\n"
        )
        assert len(requestSideSources(synthetic)) == 1, "写方检出器对新入口零命中——① 会恒真"
        assert len(turnSideSources(synthetic)) == 1, "轮身份写入点检不出来——②③ 会被糊过去"
        assert requestSideSources(synthetic) == turnSideSources(synthetic), (
            "同一个键的两种写法判不出同形——② 两头失真"
        )
        assert "user_id" in dictKeysOfTheFunctionThatWrites(synthetic), (
            "dict 键收集器看不见 meta 里的 `user_id`——④ 恒真"
        )
        assert not _callsNamed(synthetic, ("get_request_user_id",)), (
            "对不存在的读取口误报命中——③ 的派生说法会被假证明"
        )
