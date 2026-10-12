# -*- coding: utf-8 -*-
"""唯一身份通道的写点，与「内联载体」`metadata['user_id']` 之间的一致性逐条对账。

沿革三段：§6-121 裁「先补一枚判据、合并另批」，本文件就是那枚判据（(a) 档）；
(a) 档的**原形态**是"两条通道之间对账"——`neurova_request_user_id` 与轮身份那条
`neurova_turn_user_id` 同答"这一轮是谁"。§6-163（批 18，裁定甲）把轮身份那条退役之后，
本文件审的东西换了一格，但**一格都没少**：现在对账的是「唯一那条通道」与「随请求内联
进来的那份 `metadata['user_id']`」之间还不对谁说话——后者仍被技能可见视图
（`resolve_user_key`）与经验检索读取，是第二条取值路径的候选孵化地。

复算所有写方的实际取值时，**推荐档原本那句"同一轮两读数必须相等"被证伪**——各写方里
没有一处可以笼统地这么判（下表每格都写清了它到底从哪取）：

| 入口 | 通道侧（`set_request_user_id`）读的是 | 载体侧（`metadata['user_id']`） |
| --- | --- | --- |
| `api/endpoints/chat.py` | 登录用户 `current_user['user_id']`（非流式 + 流式各一处） | 同一个变量塞进 metadata，由管线读取 |
| `api/endpoints/console.py` | REST 用 `current_user`，`/ws` 自验 JWT | 同一个变量进 dict 字面量 |
| `api/endpoints/mobile_pairing.py` | WS 接入层解出后按参数交给处理器（§6-154） | 同一个变量进 `turnMetadata` |
| `tool_executor.py` | `self._agent_identity()[0]` —— 门面读数转写过来 | 它不写载体，它读通道 |
| `tool_layers/mcp_server.py` | `get_request_user_id()` —— 同一条通道自读自写 | 不涉及 |
| `channels/channel_router.py` | `resolveTurnIdentity()` 产出的**发送者**（§6-163：不再写 agent 属主） | 同一个出口产出，另带显式 `session_owner_id` |
| `api/endpoints/computer.py` | `get_current_user()['user_id'] or 'default'`（profile 池化） | 该入口不跑对话轮 |

所以本文件不写"必须相等"那种恒假判据（写了就是拿一条谎报当守卫），
而是钉六件各自成立、且各自真会咬的事：

① **写方文件集合必须与这张表逐条相等**（`set_request_user_id`/`clear_request_user_id`）——
   新增一个入口而不同步说明它的来源即红。漂移正是从"多一个入口没人对照"开始的；
   这张表初版只有三行，是 ① 自己把 `tool_executor` 与 `mcp_server` 两处补出来的
   （先前的 grep 被 `head` 截断 ⇒ 少数两处；"命中数被截断骗过"本卷已记，此处再证一次）。
② 标 `boundaryFeedsMetadata` 的入口：**每一处**通道写入都只能取那个变量，且同一个变量
   必须真的交给 `metadata['user_id']`（赋值形与 dict 字面量形都算）——边界与载体同源。
③ 标 `derivedFromFacadeRead` / `sameChannelPassThrough` / `noChannelWrite` 的入口：
   不得往载体里塞 `user_id` 之外的东西（声明过期即红），且必须真在同一个函数里读它
   声明的那个来源口（`_agent_identity` / `get_request_user_id`）。
④ 渠道那一格额外钉死"meta 里的 `user_id` 只能来自解析单点 `resolveTurnIdentity`"——
   两处产出身份就会给同一个人算出两个身份。
⑤ 凡是"取到登录用户并跑一轮对话"的入口，都必须在自己那条链上建立请求级身份
   ——拦的是**登记表漏了一行**这种形态（成因见 `ownerWritesByTurnHandler` 的文档）。
⑥ §6-163 的复活闸：全仓生产侧不得有任何调用点往 `set_request_identity(...)` 里传
   `user_id=`。那个形参已随轮身份通道一起退役，传了必 TypeError；更糟的是"今天不传、
   明天加回来"——两条通道并存就是 §6-121 那条老病。

分工（不重复既有判据）：通道本身的条数、`set_turn_identity` 的签名、会话属主的显式传参
链路由 `tests/unit/core/test_identityChannelMergedToOneSource.py` 守；
`Agent._current_user_id` 与 public 别名的**读取序**由
`tests/unit/agent/test_b5_identity_read_order.py` 守。本文件只管**写点这张表**。
"""

import ast
from pathlib import Path
from typing import Dict, List

from tests import ast_scan

REPO_ROOT = Path(__file__).resolve().parents[3]
PRODUCTION = REPO_ROOT / "neurova"

#: 通道侧的写入函数名（清槽也算：它同样决定"这一轮是谁"）。
REQUEST_WRITERS = ("set_request_user_id", "clear_request_user_id")
#: 轮次内容门面的函数名——§6-163 之后它的签名里不再有 `user_id`，
#: 本文件用它做的是**复活闸**（⑥）：全仓任何调用点往里塞 `user_id=` 就是红。
TURN_WRITER = "set_request_identity"

#: 允许的"这一格为什么不漂"的说法，每一种在下面都有对应的机器检查。
#: `boundaryFeedsMetadata`：入口在**请求边界**写那唯一一条通道，同一个值又作为
#: `metadata['user_id']` 随请求内联下去（技能可见视图 `resolve_user_key`、经验检索读它）。
#: 原名 `boundaryFeedsTurn`（§6-121 (b) 乙案）里的"喂轮身份"那半在 §6-163 之后不再成立——
#: 管线只把 user_input/session_id 交给门面，身份不再经管线二次写入；名字跟着实状换，
#: 免得留一个说旧话的 kind 让下一个人以为还有第二条通道。
#: `notATurnEntry`：该入口不跑对话回合，只在边界为浏览器 profile 池设人。
KINDS = ("boundaryFeedsMetadata", "derivedFromFacadeRead",
         "sameChannelPassThrough", "notATurnEntry")

ENTRY_POINTS: Dict[str, Dict[str, object]] = {
    "neurova/api/endpoints/chat.py": {
        "kind": "boundaryFeedsMetadata",
        "requestSource": "current_user['user_id']，两处各写一次：非流式 `/chat`（含续跑原属主）"
                         "与流式 `/chat/stream`（裁定甲，§6-153——流式此前不写 ⇒ 空属主 "
                         "对全员可见）",
        "carrierSource": "同一个 user_id 赋给 call_metadata['user_id']，随请求内联给技能与经验面",
        "feedsVia": "user_id",
    },
    "neurova/api/endpoints/console.py": {
        "kind": "boundaryFeedsMetadata",
        "requestSource": "current_user['user_id']（REST `/chat`）与 JWT `_user_identity()`"
                         "（`/ws/{client_id}`）；两处都写在跑回合的那条链上、"
                         "`create_task(run_chat())` 之前",
        "carrierSource": "同一个 user_id 进 metadata['user_id']（dict 字面量）",
        "feedsVia": "user_id",
    },
    "neurova/api/endpoints/mobile_pairing.py": {
        "kind": "boundaryFeedsMetadata",
        "requestSource": "user_id 形参——由 `_get_current_user_id`（JWT）或配对码在 WS 接入层解出后"
                         "按参数交给 `_handle_chat_send`（§6-154 合修：这条面此前只把人留在参数里，"
                         "从不交给请求通道）",
        "carrierSource": "同一个 user_id 进 turnMetadata['user_id']，与管线其余入口同形",
        "feedsVia": "user_id",
    },
    "neurova/tool_executor.py": {
        "kind": "derivedFromFacadeRead",
        "requestSource": "self._agent_identity()[0]",
        "carrierSource": "不设载体；它读的就是门面读数再转写进通道（读取序见 B-5 判据）",
        "readsVia": "_agent_identity",
        # `_agent_identity` 是**另一个方法**，所以"读的是门面"这句必须在它自己的函数体里验；
        # 只在写入点所在函数里找会把这条跨方法的取值链误判成缺失（本判据第一版正栽在这）。
        "readsViaResolvesTo": "_current_user_id",
    },
    "neurova/tool_layers/mcp_server.py": {
        "kind": "sameChannelPassThrough",
        "requestSource": "self._current_user_id() → get_request_user_id()（MCP 调用方身份沿执行链透传）",
        "carrierSource": "不涉及载体",
        "readsVia": "_current_user_id",
        "readsViaResolvesTo": "get_request_user_id",
    },
    "neurova/channels/channel_router.py": {
        "kind": "boundaryFeedsMetadata",
        "requestSource": "turnIdentity['user_id'] —— §6-163 裁定甲：通道装**发送者**，"
                         "与载体同一个出口（原形态是把 agent.config.owner_user_id 写进通道，"
                         "于是「属主」与「发送者」分占两条通道，§6-127 裁定 ④ 那处声明式分叉）",
        "carrierSource": "meta['user_id'] 与 memory_scope 都由 UserIdentityManager"
                         ".resolveTurnIdentity 单点产出（已绑→平台账号对，未绑→ch:{渠道}:{发送者}）；"
                         "会话可见性另走显式元数据 `session_owner_id`（agent 属主，H-W0）",
        "feedsVia": "resolveTurnIdentity",
        "resolvedVia": "resolveTurnIdentity",
    },
    "neurova/api/endpoints/computer.py": {
        "kind": "notATurnEntry",
        "requestSource": "get_current_user()['user_id'] or 'default'（浏览器 profile 按用户池化）",
        "carrierSource": "该入口不跑对话回合，不产生 metadata 载体",
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


def requestWriteOrigins(tree: ast.AST) -> List[str]:
    """request 写入点参数的**来源名**（②b 用，与 `userIdAssignments` 同一套抽取口径）。

    不能直接拿 `requestSideSources` 的规范化 dump 比：那是给"两侧表达式逐字同形"那种
    判据用的，而乙案要问的是"这两处取的是不是同一个变量"——两边必须用同一种抽取形态，
    否则一边是 `Name(...)`、一边是 `user_id`，永不相等，判据就恒红。
    """
    return [_originOf(call.args[0], tree) for call in _callsNamed(tree, REQUEST_WRITERS)
            if call.args]


def turnSideSources(tree: ast.AST) -> List[str]:
    """调用点往 `set_request_identity(...)` 塞身份的两种写法（⑥ 的靶）。

    关键字形（`user_id=…`）与第三个**位置**实参都要抓——只认关键字会让
    `set_request_identity(user_input, session_id, someone)` 这一形从网眼里过去，
    而它同样是"把身份交回管线"的动作（那个形参已随轮身份通道退役，两种写法今天都必抛）。
    """
    out: List[str] = []
    for call in _callsNamed(tree, (TURN_WRITER,)):
        for keyword in call.keywords:
            if keyword.arg == "user_id":
                out.append(_normalizedDump(keyword.value))
        if len(call.args) >= 3:
            out.append(_normalizedDump(call.args[2]))
    return out


def metaKeysOfTheWriterFunction(tree: ast.AST) -> List[str]:
    """写 request 通道的那个函数里，metadata 的键名来源（④ 的靶）。

    两种形态都要收：dict 字面量的键，和 `meta["x"] = ...` 的下标赋值。只认前者会造
    **假绿**——批 2 之后渠道路径正是用下标赋值写 `user_id`，dict 字面量里仍然没有它。
    """
    parents = _parents(tree)
    keys: List[str] = []
    for call in _callsNamed(tree, REQUEST_WRITERS):
        holder = _enclosingFunction(call, parents)
        if holder is None:
            continue
        for node in ast.walk(holder):
            if isinstance(node, ast.Dict):
                keys += [k.value for k in node.keys
                         if isinstance(k, ast.Constant) and isinstance(k.value, str)]
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if (isinstance(target, ast.Subscript)
                            and isinstance(target.slice, ast.Constant)
                            and isinstance(target.slice.value, str)):
                        keys.append(target.slice.value)
    return keys


def _originOf(expr: ast.AST, scope: ast.AST, depth: int = 0) -> str:
    """这条值"来自哪个出口"：直接调用、或**本函数内**由那个调用赋来的局部变量（一层）。

    只追一层是为了不重造数据流引擎，同时允许
    `turnIdentity = resolveTurnIdentity(...)` 之后 `meta["user_id"] = turnIdentity["user_id"]`
    这种等价写法——判的是"值只可能来自那个出口"，不是语法形状。跨函数传值不在本判据射程内
    （真要绕过，走参数注入即可；那种改法必然要动别处，由 §6-121 的写方清单那一格兜住）。
    """
    called = {_calleeName(c) for c in ast.walk(expr) if isinstance(c, ast.Call)}
    if "resolveTurnIdentity" in called:
        return "resolveTurnIdentity"
    if depth < 2 and isinstance(expr, ast.Subscript) and isinstance(expr.value, ast.Name):
        for node in ast.walk(scope):
            if (isinstance(node, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == expr.value.id
                            for t in node.targets)):
                return _originOf(node.value, scope, depth + 1)
    return _calleeName(expr) if isinstance(expr, ast.Call) else (
        # 裸局部变量：报**变量名**而不是类型名。②b 要比的就是"这两处取的是同一个变量"，
        # 回 "Name" 会让任何两个 Name 都互相相等（同源判据恒真）。
        expr.id if isinstance(expr, ast.Name) else type(expr).__name__)


def userIdAssignments(tree: ast.AST) -> List[str]:
    """`meta["user_id"] = …` 的值来源（④ 要求它只能是解析单点）。"""
    out: List[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if (isinstance(target, ast.Subscript)
                    and isinstance(target.slice, ast.Constant)
                    and target.slice.value == "user_id"):
                out.append(_originOf(node.value, tree))
    return out


def metadataUserOrigins(tree: ast.AST) -> List[str]:
    """metadata 里 `user_id` 这一格的所有取值来源——**两种写法都算**：下标赋值与 dict 字面量。

    为什么 ②b 要用这一份而 ④ 仍用 `userIdAssignments`：`chat.py`/`channel_router.py` 是
    先建 dict 再 `meta["user_id"] = …`，而 `console.py` 直接在 dict 字面量里写
    `"user_id": user_id`。②b 问的是"边界那条 request 写入与喂轮身份的是不是同一个变量"，
    少认一种形态就会把真入口报成"没喂轮身份"（假红）；④ 问的是"渠道路径的 meta 里那一格
    只许来自解析单点"，它的靶本来就是赋值形，扩成两形会把别处 dict 里的同名字键也算进来
    （那不是同一件事）。两格各自口径，不并成一份偷懒。
    """
    out = list(userIdAssignments(tree))
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value == "user_id":
                    out.append(_originOf(value, tree))
    return out


def ownerWritesByTurnHandler(tree: ast.AST) -> Dict[str, bool]:
    """顶层函数里"既取到了登录身份（`Depends` 或自验 token）、又会跑 `agent.chat(...)`"的入口
    → 它有没有在自己的链上写请求级属主。

    这一格拦的是**登记表漏了一行**这种形态，而不是登记错：批 9 把管线里那段"每轮按
    `metadata['user_id']` 补写通道"的双写删掉、只在 `api/endpoints/chat.py` 补了边界写点，
    `console.py` 这条网页主面当场没人写属主——行为断言全绿（它只审已登记的入口），而用量
    入账落到 `"anonymous"`（`multi_model_client:876/1156`）、按日 LLM 配额整条不判
    （`:1426` 无身份即放行）、客户端自带全新 session_id 时会话落空属主
    （`session_manager:1650` 空属主＝对全员可见）。手抄清单拦不住"没抄上的那一行"，
    所以这里按形状自己数入口。
    """
    out: Dict[str, bool] = {}
    for fn in tree.body:
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        defaults = [d for d in list(fn.args.defaults) + list(fn.args.kw_defaults)
                    if d is not None]
        params = [a.arg for a in list(fn.args.args) + list(fn.args.kwonlyargs)]
        # 身份来源三种形状都算"取到了人"：`Depends(get_current_user)`（REST）、
        # 函数体里自己 `verify_access_token(...)`（WebSocket 没有 Depends 通道），
        # 以及**身份按参数传进来**（`mobile_pairing._handle_chat_send(ws, data, user_id)`——
        # 人由 WS 接入层解出后交给处理器；漏掉这一形就等于给这条面开了免检口）。
        # 只认前两种会把整条路径判成"不归本判据管"，而它同样是"已鉴权且跑回合"。
        resolvesIdentity = (
            any(isinstance(d, ast.Call) and _calleeName(d) == "Depends" for d in defaults)
            or any(_calleeName(node) == "verify_access_token"
                   for node in ast.walk(fn) if isinstance(node, ast.Call))
            or "user_id" in params
        )
        runsTurn = any(isinstance(node, ast.Call)
                       and getattr(node.func, "attr", None) == "chat"
                       and isinstance(node.func.value, ast.Name)
                       and node.func.value.id == "agent"
                       for node in ast.walk(fn))
        if resolvesIdentity and runsTurn:
            out[fn.name] = bool(_callsNamed(fn, REQUEST_WRITERS))
    return out


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
            "多出来的那一行就是通道与载体之间没人对照的面（漂移从这儿开始）；"
            "少掉的那一行说明表在替已消失的代码作保。"
            "新增入口请同时写明 requestSource / carrierSource / kind。"
        )

    def test_everyEntryNamesBothSidesAndAnAllowedKind(self):
        """② 的前置：每一格都得说清"两侧各从哪来"，且至少有一格承诺同源。"""
        for rel, entry in ENTRY_POINTS.items():
            assert entry.get("requestSource"), f"{rel} 没写通道侧来源"
            assert entry.get("carrierSource"), f"{rel} 没写载体侧来源（拿什么判分叉？）"
            assert entry.get("kind") in KINDS, f"{rel} 的 kind 不在允许集合 {KINDS}"
            if entry["kind"] in ("derivedFromFacadeRead", "sameChannelPassThrough"):
                assert entry.get("readsVia"), f"{rel} 声明了派生却没写经由哪个读取口"
            if entry["kind"] == "boundaryFeedsMetadata":
                assert entry.get("feedsVia"), (
                    f"{rel} 声明「边界写通道 + 同一个值进载体」却没写靠哪个变量把两侧串起来")
        assert any(e["kind"] == "boundaryFeedsMetadata" for e in ENTRY_POINTS.values()), (
            "所有入口都声明分叉 ⇒ 没有任何一处保证通道与载体同读一个来源，"
            "这张表就从「对齐依据」退化成「分歧登记表」"
        )

    def test_boundaryEntriesFeedBothSidesFromOneVariable(self):
        """②b 标 `boundaryFeedsMetadata` 的入口：**每一处**通道写入都只能取那个变量。

        守住的东西：通道只在一处写、载体只在一个出口产出，两者必须是同一个值——
        哪天有人把边界某处改成别的来源（比如从报文里读 `user_id`），本格立刻红。
        （原形态里这一格比的是"通道 vs 轮身份"，§6-163 并成一条之后比的是"通道 vs 载体"，
        式子一字未动，只是被比的两侧换了名字。）

        一个入口里**多处**写（非流式与流式两条端点同居 `chat.py`）是允许的，但必须逐处
        同变量——原先断"恰好一处"会在第二处合法写入（流式补属主）时假红，
        而把判据改成"至少一处对得上就放过"又会漏掉第二处取错值：所以取
        **非空且集合相等**这一形。
        """
        for rel, entry in ENTRY_POINTS.items():
            if entry["kind"] != "boundaryFeedsMetadata":
                continue
            tree = productionSources()[rel]
            origins = requestWriteOrigins(tree)
            assert origins and set(origins) == {entry["feedsVia"]}, (
                f"{rel} 写通道共 {len(origins)} 处，来源 {sorted(set(origins))}；"
                f"要求每一处都是它声称与载体同源的那个变量 {entry['feedsVia']!r}"
                "——通道与载体在此分叉"
            )
            assert entry["feedsVia"] in metadataUserOrigins(tree), (
                f"{rel} 不再把 `{entry['feedsVia']}` 交给 metadata 的 `user_id` 那一格"
                "（赋值形与 dict 字面量形都没取到）：边界只写了通道一侧，"
                "载体那一侧的来源断了（技能可见视图与经验检索会各读各的）"
            )


class TestDeclaredKindsMatchCode:
    def test_otherEntriesDoNotWriteTurnIdentityAndDoReadWhatTheyClaim(self):
        """③ 其余两件事：不得往载体里塞 `user_id`（声明就过期了），且要真读它说的那个口。"""
        for rel, entry in ENTRY_POINTS.items():
            tree = productionSources()[rel]
            assert not turnSideSources(tree), (
                f"{rel} 现在往 `{TURN_WRITER}(...)` 里传 user_id——那个形参已随轮身份通道"
                "一起退役（§6-163），传了必 TypeError；不传也不该留着这个形状"
            )
            if entry["kind"] != "boundaryFeedsMetadata":
                assert "user_id" not in metaKeysOfTheWriterFunction(tree), (
                    f"{rel} 声明「不产生载体」，却在写通道的那个函数里往 metadata 塞了 "
                    "`user_id`——kind 需要重新判定（多半要连 §6-123 一起看，别只改这张表）"
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

    def test_channelUserIdComesOnlyFromTheResolutionPoint(self):
        """④（批 2 改判）：渠道 meta 的 `user_id` **必须**存在，且只能是解析单点给的。

        改判理由（§6-127 裁定 ①/③，不是放宽）：本格原形态是"meta 里不得出现 `user_id` 键"，
        因为那时渠道路径没人解析、轮身份一律落 `"default"`（§6-123 的成因）。批 2 接上
        `UserIdentityManager.resolveTurnIdentity` 之后，"没有这个键"反而成了缺陷——
        所以现在要求：键在、值只来自那一个调用、且不来自报文自带字段（否则外部可冒充平台账号）。
        """
        rel = "neurova/channels/channel_router.py"
        tree = productionSources()[rel]
        entry = ENTRY_POINTS[rel]
        assert "user_id" in metaKeysOfTheWriterFunction(tree), (
            f"{rel} 不再往 meta 写 `user_id` ⇒ 渠道发送者退回 default 共享桶，"
            "§6-127 裁定 ①被推翻"
        )
        assert userIdAssignments(tree) == [entry["resolvedVia"]], (
            f"{rel} 的 meta['user_id'] 来源是 {userIdAssignments(tree)}，"
            f"只允许 {entry['resolvedVia']!r} 一个出口——两处产出身份，"
            "两条通道就会给同一个人算出两个身份"
        )


class TestEveryTurnEntryEstablishesTheOwner:
    """⑤ 凡是"取到登录用户并跑一轮对话"的请求入口，都必须在自己那条链上建立请求级属主。

    与 ①②③④ 的分工：那几格审的是**已登记**的入口之间对不对，本格审的是"有没有入口
    根本没登记"。成因见 `ownerWritesByTurnHandler` 的文档——批 9 删掉管线双写时漏了
    `console.py`，全仓判据当时一条都没红。
    """

    def test_noAuthenticatedTurnEntryLeavesTheOwnerUnset(self):
        offenders = [
            f"{rel}::{name}"
            for rel, tree in productionSources().items()
            for name, writesOwner in ownerWritesByTurnHandler(tree).items()
            if not writesOwner
        ]
        assert not offenders, (
            f"这些入口带鉴权依赖、会跑 `agent.chat(...)`，却没在本函数链上写 `set_request_user_id`："
            f"{offenders}\n"
            "后果不是「这一轮没有属主」这么轻：usage 记 anonymous、按日配额不判、"
            "新会话落空属主而对全员可见（`session_manager:1650`）。"
            "要么在边界写一次（写点须在 create_task 之前），要么说明它确实不该有请求级属主并"
            "把理由写进本格的例外口径——不许静默留着。"
        )

    def test_theHandlerDetectorSeesTheEntriesItClaims(self):
        """反向对照：把 console 两处写点摘掉，探测器必须点名那两个入口——否则 ⑤ 恒绿。

        这一格同时钉住前提本身：`post_console_chat` 确实在"带 Depends 且跑 agent.chat"
        的集合里。摘掉写点后它才被判成违例，说明 ⑤ 不是靠"入口压根没被数到"买来的绿。
        """
        rel = "neurova/api/endpoints/console.py"
        source = (REPO_ROOT / rel).read_text(encoding="utf-8")
        stripped = source.replace("set_request_user_id(user_id)", "pass")
        assert stripped != source, "console.py 里没有可摘的写点，本对照不可信"

        found = ownerWritesByTurnHandler(ast.parse(stripped))
        assert {"post_console_chat", "websocket_console"} <= set(found), (
            f"探测器没把这两个入口当「跑回合的鉴权端点」：{sorted(found)}——"
            "⑤ 对它们永远不会红（形状口径失效，不是代码没问题）"
        )
        assert found.get("post_console_chat") is False and found.get("websocket_console") is False, (
            f"写点已摘净却仍判「有写」：{found}——⑤ 是恒真的空守卫"
        )
        live = ownerWritesByTurnHandler(productionSources()[rel])
        assert live and all(live.values()), f"实况面本该全部有写：{live}"


class TestIdentityIsNotHandedBackToTheTurnFacade:
    """⑥ §6-163 的复活闸：全仓生产侧没有任何调用点把身份交回轮次门面。

    为什么单独一格（③ 已经对每个登记入口比过一次）：③ 的口径是"这张表里逐格看"，
    而复活可以发生在**表外**的某个模块——`memory_layer`、`cognitive_layers`、某个
    后处理步骤，那里同样调得起 `set_request_identity(...)`。本格按形状自己数全仓调用点，
    与 ⑤ 对写方的做法同形（"每个 X 都必须 Y"的契约要有一格自己枚举 X）。

    式子今天**能**咬：`Agent.set_request_identity(user_input, session_id)` 与
    `TurnState.set_request_identity(user_input, session_id=None)` 的签名里都没有 `user_id`，
    任一形（关键字或第三个位置实参）传进去都是当场 TypeError——不是"看着像死码的红"，
    而是改了立刻在那一行炸。
    """

    def test_noProductionCallSitePassesAUserIdToTheTurnFacade(self):
        offenders = [rel for rel, tree in productionSources().items() if turnSideSources(tree)]
        assert not offenders, (
            f"这些文件仍把 user_id 交给轮次门面：{offenders}——那个形参已随轮身份通道退役，"
            "两条通道并存就是 §6-121 那句「同一轮两个读数」的老病，甲就白做了"
        )

    def test_theRevivalDetectorFiresOnBothSpellings(self):
        """反向自证：两种写法都要抓，且不许把「只传两格」的正常调用报成违例。"""
        keywordForm = "def f(u, s, i):\n    set_request_identity(user_input=u, session_id=s, user_id=i)\n"
        positionalForm = "def f(u, s, i):\n    set_request_identity(u, s, i)\n"
        assert len(turnSideSources(ast.parse(keywordForm))) == 1, (
            "关键字形抓不到 ⇒ ⑥ 恒绿（复活了也没人红）")
        assert len(turnSideSources(ast.parse(positionalForm))) == 1, (
            "第三个位置实参抓不到 ⇒ 换个写法就绕过 ⑥")
        assert turnSideSources(
            ast.parse("def f(u, s):\n    set_request_identity(user_input=u, session_id=s)\n")) == [], (
            "合并后的正常调用形状被判成违例 ⇒ ⑥ 恒红，改了也白改")


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
        assert "user_id" in metaKeysOfTheWriterFunction(synthetic), (
            "键收集器看不见 meta 里的 `user_id`——④ 恒真"
        )
        assigned = ast.parse("def f(meta):\n    meta['user_id'] = resolveTurnIdentity(1)\n")
        assert userIdAssignments(assigned) == ["resolveTurnIdentity"], (
            "下标赋值的来源抽不出来——④ 会被随手赋值绕过"
        )
        assert not _callsNamed(synthetic, ("get_request_user_id",)), (
            "对不存在的读取口误报命中——③ 的派生说法会被假证明"
        )
