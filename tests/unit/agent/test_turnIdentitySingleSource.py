# -*- coding: utf-8 -*-
"""轮身份只有一个写入口；`sender` 走传输面，不得长成第二条身份通道（台账 §6-98 末段）。

来历：`Agent.process_message` 断链根修（`10724888`）之后留下半截事实——入口把 `sender`
放进 `Message.sender_id`，而 `process_message → MessageRouter._route_chat → agent.chat`
这一跳**不读**它（`_route_chat` 只取 `content` 与 `metadata`）。用户 2026-10-10 裁定
**不接线**，本文件就是把那半句裁定钉成可证伪的东西：

- `sender_id` 不是无人读的字段——传输面确有读方（协议层 `to_dict`/回复、ACP 端点），
  不接线不留下"只写不读"的断点（第 ⑥ 格把它钉成读数，免得下次有人当死码摘掉）；
- 一旦把 `Message.sender_id` 喂进轮身份，"这一轮是谁"就多了第二条写入路径：
  与 `set_turn_identity()`（工具层三层隔离、蜂群事件广播都读它）并存的、
  "某个信封字段顺手抄过来"的那条。后者按调用点手感存在，正是教义第 6 条要禁的平行体系。

**通道按声明名认，不按局部变量名认**（本判据第一版就是这样误报的）：
`neurova/core/identity_context.py` 里另有一条 ContextVar，局部名同样叫 `_user_id_var`，
但声明的是 `neurova_request_user_id`——与轮身份的 `neurova_turn_user_id` 是两条运行时通道。
按局部名匹配会把它的两处正常写点报成"轮身份被旁路直写"，那种假红比没有判据更坏
（读者会学会无视它）。所以检出器先解析 `_x = ContextVar("名字")` 的**声明名**，
再按声明名归账，并把"同名不同通道"这一形态本身钉成一条反证（见 ⑦）。

顺带抓出的真事实（不在本裁范围内，已登记台账待裁）：`neurova_request_user_id` 确实
是"本轮哪个用户"的第二条通道——三处生产写方（`chat_pipeline.py:477`、
`api/endpoints/computer.py:729`、`channels/channel_router.py:180`）与两处读方
（`computer_use/browser_manager.py:1790`、`camofox_server_backend.py:79`）。
它不与轮身份同写一条变量，所以本文件把它**作为独立通道逐条登记**（多一处写点即红），
而不是假装它不存在，也不在这里合并它（合并动到浏览器/计算机使用的按用户隔离，
属另一批）。
"""

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List, Optional, Set, Tuple

from neurova.agent.turn_state import TurnState
from neurova.agent_core import Agent
from neurova.router import MessageRouter, RouteResult
from tests import ast_scan

REPO_ROOT = Path(__file__).resolve().parents[3]
PRODUCTION = REPO_ROOT / "neurova"

#: 四条身份通道的**声明名**（ContextVar 的运行时身份）。新增第五条时本表必须跟着长，
#: 否则新通道无人守；`test_theDetectorsAreNotVacuous` 只保证检出现有的写法。
#: 前三条 = 轮身份；第四条 = 已知并行的"本轮哪个用户"第二通道（见文件头）。
WRITERS: Dict[str, Set[str]] = {
    "neurova_turn_user_input": {
        "neurova/core/turn_context.py::set_turn_identity",
        # A-04 契约的单字段 setter：`Agent._current_user_input` 的后端，
        # 只动 user_input 一格、不碰 session/user 两个身份字段。写成"整个身份一个写方"
        # 会把这条既有契约谎报成违规，也拦不住它长大。
        "neurova/core/turn_context.py::set_turn_user_input",
    },
    "neurova_turn_session_id": {"neurova/core/turn_context.py::set_turn_identity"},
    "neurova_turn_user_id": {"neurova/core/turn_context.py::set_turn_identity"},
    "neurova_request_user_id": {
        "neurova/core/identity_context.py::set_request_user_id",
        "neurova/core/identity_context.py::clear_request_user_id",
    },
}

#: 轮身份三通道（不含那条并行通道）——`set_turn_identity` 只该写这三条。
TURN_IDENTITY = ("neurova_turn_user_input", "neurova_turn_session_id", "neurova_turn_user_id")

#: 每条通道变量的**声明所在文件**（一条通道只许一处声明，否则连"是哪条通道"都有两说）。
DECLARED_IN: Dict[str, str] = {
    "neurova_turn_user_input": "neurova/core/turn_context.py",
    "neurova_turn_session_id": "neurova/core/turn_context.py",
    "neurova_turn_user_id": "neurova/core/turn_context.py",
    "neurova_request_user_id": "neurova/core/identity_context.py",
}

#: 轮身份唯一入口在生产侧的唯一调用方。
SET_IDENTITY_CALLERS: Set[str] = {
    "neurova/agent/turn_state.py::TurnState.set_request_identity",
}

#: 传输面读方的最低要求：协议层至少有一处把 `sender_id` **读**出来（不是构造点）。
TRANSPORT_READER_PREFIX = "neurova/agent/protocols/"

#: 判定"这是一条身份类 ContextVar"的词根——用于第 ⑦ 格的防扩散网，不用于归账。
_IDENTITY_WORD_ROOTS = ("user", "session", "identity", "tenant")


def _attrHead(node: ast.AST) -> str:
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else ""


def declaredVars(tree: ast.AST) -> Dict[str, str]:
    """局部名 → ContextVar 声明名（`_x: ContextVar = ContextVar("NAME", ...)`）。"""
    out: Dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        value = node.value
        if not (isinstance(value, ast.Call)
                and (_attrHead(value.func) == "ContextVar"
                     or getattr(value.func, "attr", "") == "ContextVar")
                and value.args and isinstance(value.args[0], ast.Constant)
                and isinstance(value.args[0].value, str)):
            continue
        name = value.args[0].value
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Name):
                out[target.id] = name
    return out


def _dottedOf(rel: str) -> str:
    stem = rel[:-3] if rel.endswith(".py") else rel
    if stem.endswith("/__init__"):
        stem = stem[: -len("/__init__")]
    return stem.replace("/", ".")


#: `dotted 模块名 → 该模块声明的 ContextVar`，整进程一趟建好。
#:
#: 走仓内共享扫描器 `tests/ast_scan.py`（同一份源码只编译一次），而不是在本文件
#: 再起一个 `io.open + ast.parse` 的私有缓存：后者是全仓第三份"扫一遍生产面"的
#: 实现（教义第 6 条），而且实测把两格各推到 ≈25s——默认 `timeout = 30`，
#: 受保护子集与 4000+ 条用例共享 2 vCPU，判据自己就能把门禁拖红。
_declIndex: Optional[Dict[str, Dict[str, str]]] = None


def declIndex() -> Dict[str, Dict[str, str]]:
    global _declIndex
    if _declIndex is None:
        trees = ast_scan.parsedModules(PRODUCTION)
        assert trees, f"生产扫描面为空（{PRODUCTION}）——本文件会空转"
        _declIndex = {
            _dottedOf(ast_scan.relativeToRepo(path)): declaredVars(tree)
            for path, tree in trees
        }
    return _declIndex


def channelMap(tree: ast.AST) -> Tuple[Dict[str, str], Dict[str, Dict[str, str]]]:
    """本文件的 `(局部名→通道名, 模块别名→该模块的 局部名→通道名)`。

    两条解析路都要：`from x import _user_id_var`（直接名字）与
    `from neurova.core import turn_context` 后的 `turn_context._user_id_var.set(...)`
    （模块别名 + 属性）——漏掉任一条，旁路写点就从网眼里过去。
    """
    direct = declaredVars(tree)
    index = declIndex()
    aliased: Dict[str, Dict[str, str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            if not node.module.startswith("neurova"):
                continue
            decls = index.get(node.module, {})
            for alias in node.names:
                if alias.name in decls:
                    direct[alias.asname or alias.name] = decls[alias.name]
                else:
                    # `from neurova.core import turn_context` 引进来的是**模块**本身：
                    # 后面 `turn_context._user_id_var.set(...)` 是一条完整的旁路写点，
                    # 这一支不解析，② 就会漏掉"隔着模块点名直写"这种写法。
                    submodule = f"{node.module}.{alias.name}"
                    if submodule in index:
                        aliased[alias.asname or alias.name] = index[submodule]
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("neurova"):
                    aliased[alias.asname or alias.name.rpartition(".")[2]] = index.get(
                        alias.name, {})
    return direct, aliased


def _resolve(target: ast.AST, direct: Dict[str, str],
             aliased: Dict[str, Dict[str, str]]) -> Optional[str]:
    if isinstance(target, ast.Name):
        return direct.get(target.id)
    if isinstance(target, ast.Attribute):
        parts: List[str] = []
        cur = target
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
            return aliased.get(parts[-1], {}).get(parts[0])
    return None


def _parents(tree: ast.AST) -> Dict[ast.AST, ast.AST]:
    parents: Dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    return parents


def _qualName(node: ast.AST, parents: Dict[ast.AST, ast.AST]) -> str:
    parts: List[str] = []
    cur = node
    while cur is not None:
        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            parts.append(cur.name)
        cur = parents.get(cur)
    return ".".join(reversed(parts))


def _enclosingFunction(node: ast.AST, parents: Dict[ast.AST, ast.AST]) -> str:
    holder = parents.get(node)
    while holder is not None and not isinstance(
        holder, (ast.FunctionDef, ast.AsyncFunctionDef)
    ):
        holder = parents.get(holder)
    return _qualName(holder, parents) if holder else "<module>"


def identityWritesIn(tree: ast.AST, rel: str) -> List[Tuple[str, str]]:
    """对身份通道调 `.set()` 的落点：`(通道声明名, 相对路径::限定名)`。

    成对返回而不是只返回串：判据要**按通道**归账，在串里猜变量名会把两件事混成一件，
    而那条同名的并行通道正是会混进去的那种。
    """
    parents = _parents(tree)
    direct, aliased = channelMap(tree)
    hits: List[Tuple[str, str]] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "set"):
            continue
        channel = _resolve(node.func.value, direct, aliased)
        if channel in WRITERS:
            hits.append((channel, f"{rel}::{_enclosingFunction(node, parents)}"))
    return hits


def identityWrites(source: str, rel: str) -> List[Tuple[str, str]]:
    """合成样本入口：与生产侧**共用同一套** tree 级检出器（各写一台，反向控制就只证明了
    那台空的那台会抓）。"""
    return identityWritesIn(ast.parse(source), rel)


def setIdentityCallersIn(tree: ast.AST, rel: str) -> List[str]:
    """对 `set_turn_identity(...)` 的**调用**落点（`__all__` 里的字符串不是调用）。"""
    parents = _parents(tree)
    hits: List[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else (
            func.attr if isinstance(func, ast.Attribute) else "")
        if name == "set_turn_identity":
            hits.append(f"{rel}::{_enclosingFunction(node, parents)}")
    return hits


def setIdentityCallers(source: str, rel: str) -> List[str]:
    return setIdentityCallersIn(ast.parse(source), rel)


def senderIdReadersIn(tree: ast.AST) -> int:
    """把 `.sender_id` 当**读**用（Load）的次数；赋值左侧（Store）不计。"""
    return sum(
        1 for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr == "sender_id"
        and isinstance(node.ctx, ast.Load)
    )


def senderIdReaders(source: str) -> int:
    return senderIdReadersIn(ast.parse(source))


_scan: Optional[Dict[str, Dict[str, object]]] = None


def scanProduction() -> Dict[str, Dict[str, object]]:
    """一趟扫完生产面，逐文件备好四件读数；本文件六格共用这一份。

    语法树取自 `tests/ast_scan.py` 的整进程缓存（同一份源码只编译一次），本函数只
    在此之上做一次归账遍历。分格各扫一遍实测把两格各推到 ≈25s，而默认 `timeout = 30`、
    受保护子集与 4000+ 条用例共享 2 vCPU——判据自己就能把门禁拖红。
    """
    global _scan
    if _scan is None:
        out: Dict[str, Dict[str, object]] = {}
        for path, tree in ast_scan.parsedModules(PRODUCTION):
            rel = ast_scan.relativeToRepo(path)
            out[rel] = {
                "writes": identityWritesIn(tree, rel),
                "callers": setIdentityCallersIn(tree, rel),
                "readers": senderIdReadersIn(tree),
                "declared": declaredVars(tree),
            }
        _scan = out
    return _scan


def liveWriterLedger() -> Dict[str, Set[str]]:
    live: Dict[str, Set[str]] = {name: set() for name in WRITERS}
    for entry in scanProduction().values():
        for channel, hit in entry["writes"]:  # type: ignore[index]
            live[channel].add(hit)
    return live


class _IdentityRecordingAgent:
    """下游 agent：在**被路由到的那一刻**记录轮身份（事后读会读到别的轮写进去的）。"""

    def __init__(self):
        self.seen: List[Dict[str, object]] = []

    async def chat(self, content, **kwargs):
        state = TurnState()
        self.seen.append({
            "content": content,
            "session_id": state.current_session_id,
            "user_id": state.current_user_id,
            "user_input": state.current_user_input,
        })
        return {"text": "pong"}


class _EntryHost:
    """只借出真实 `Agent.process_message` 本体的最小宿主（与 D1 判据那批同形）。"""

    def __init__(self, router):
        self._router = router
        self._skill_registry = None
        self.config = SimpleNamespace(name="identity-probe")

    def init_router(self):  # pragma: no cover
        raise AssertionError("不该走自动装配支路：_router 已注入")


class TestIdentityChannelsHaveOneWriter:
    def test_eachChannelWritersMatchTheLedgerExactly(self):
        """① 每条通道的写方与台账逐条相等。"""
        live = liveWriterLedger()
        drifted = [
            f"  {name}: 台账 {sorted(WRITERS[name])} / 实测 {sorted(live[name])}"
            for name in sorted(WRITERS) if live[name] != WRITERS[name]
        ]
        assert drifted == [], (
            "身份通道的写方与台账不一致——多一处即第二条写入路径：\n" + "\n".join(drifted)
        )

    def test_noIdentityChannelIsWrittenOutsideItsOwningModule(self):
        """② 旁路写点：在自己模块之外直接 `.set()` 一条身份通道即红。"""
        offenders = [
            f"{channel}@{hit}"
            for entry in scanProduction().values()
            for channel, hit in entry["writes"]
            if not hit.startswith(f"{DECLARED_IN[channel]}::")
        ]
        assert offenders == [], (
            f"身份通道在自己模块之外被直接 `.set()`：{offenders}——绕过门面的写点就是"
            "第二条身份通道，而且它不会出现在任何一处 `set_turn_identity` 的调用面上"
        )

    def test_eachChannelIsDeclaredExactlyOnce(self):
        """⑦ 防扩散：身份类 ContextVar 的清单必须就是台账这几条，且各只声明一处。"""
        found: Dict[str, Set[str]] = {}
        for rel, entry in scanProduction().items():
            for name in entry["declared"].values():
                if any(root in name for root in _IDENTITY_WORD_ROOTS):
                    found.setdefault(name, set()).add(rel)
        assert found == {name: {rel} for name, rel in DECLARED_IN.items()}, (
            "身份类 ContextVar 的分布变了（多一条＝新的身份通道，少一条＝台账在替"
            "已消失的代码作保），实测：\n"
            + "\n".join(f"  {k}: {sorted(v)}" for k, v in sorted(found.items()))
        )

    def test_theDetectorsAreNotVacuous(self):
        """⑧ 反向自证：三台检出器各喂合成样本必须真抓到，且不被同名不同通道骗过去。"""
        rogue = (
            "from contextvars import ContextVar\n"
            "_user_id_var = ContextVar('neurova_turn_user_id', default=None)\n"
            "def rogueWriter(value):\n    _user_id_var.set(value)\n"
        )
        assert identityWrites(rogue, "synthetic.py") == [
            ("neurova_turn_user_id", "synthetic.py::rogueWriter")
        ], "检出器抓不到模块级通道的旁路写点——①② 两格都会空转"

        lookAlike = (
            "from contextvars import ContextVar\n"
            "_user_id_var = ContextVar('neurova_request_user_id', default=None)\n"
            "def set_request_user_id(value):\n    _user_id_var.set(value)\n"
        )
        assert identityWrites(lookAlike, "synthetic.py") == [
            ("neurova_request_user_id", "synthetic.py::set_request_user_id")
        ], "按声明名归账失效：同名不同通道被记成了轮身份的写点——那种假红会让人无视本判据"

        viaAlias = (
            "from neurova.core import turn_context\n"
            "def bypass(v):\n    turn_context._user_id_var.set(v)\n"
        )
        assert identityWrites(viaAlias, "synthetic.py") == [
            ("neurova_turn_user_id", "synthetic.py::bypass")
        ], "模块别名 + 属性形式的旁路写点没被解析出来——② 会漏这一整类写法"

        assert identityWrites("def f():\n    somethingElse.set(1)\n", "s.py") == [], (
            "非身份通道的 `.set()` 也被算进来——台账会被无关代码打红"
        )
        assert setIdentityCallers(
            "def set_turn_identity(a, b=None, c=None): pass\n"
            "def otherEntry(u, s, i):\n    set_turn_identity(u, s, i)\n",
            "synthetic.py",
        ) == ["synthetic.py::otherEntry"], "检出器抓不到第二调用方——③ 会空转"
        assert setIdentityCallers("__all__ = ['set_turn_identity']\n", "s.py") == [], (
            "把名字出现在 `__all__` 里当成调用——③ 会把声明当成写方"
        )
        assert senderIdReaders("def f(m):\n    m.sender_id = 'x'\n") == 0, (
            "检出器把写点算成读点——⑥ 会恒真"
        )
        assert senderIdReaders("def g(m):\n    return m.sender_id\n") == 1, (
            "检出器对真实读点零命中——⑥ 会恒假"
        )


class TestIdentityEntryHasOneCaller:
    def test_onlyTheTurnStateFacadeCallsIt(self):
        """③ 生产侧只有一个门面调得起 `set_turn_identity`。"""
        live = {
            hit
            for entry in scanProduction().values()
            for hit in entry["callers"]
        }
        assert live == SET_IDENTITY_CALLERS, (
            f"`set_turn_identity` 的调用方应为 {sorted(SET_IDENTITY_CALLERS)}，"
            f"实测 {sorted(live)}——多一处就多一条轮身份写入路径，"
            "工具层三层隔离读到的身份将取决于走哪条入口"
        )


class TestEntryDoesNotOpenASecondChannel:
    def test_processMessageLeavesTurnIdentityUntouched(self):
        """④ 行为面：入口带 sender 走传输面，但不得改写已进入的轮身份。"""
        downstream = _IdentityRecordingAgent()
        router = MessageRouter(agent=downstream, skill_registry=None, memory_manager=None)
        host, process_message = _EntryHost(router), Agent.process_message

        TurnState().set_request_identity("原输入", "sess-A", "user-A")
        result = asyncio.run(process_message(host, "你好", sender="someone"))

        assert result.success is True, result
        assert downstream.seen, "根本没走到被路由的那一跳——本格的断言是空的"
        observed = downstream.seen[0]
        assert (
            observed["session_id"] == "sess-A" and observed["user_id"] == "user-A"
            and observed["user_input"] == "原输入"
        ), (
            f"入口改写了轮身份：{observed}——`Message.sender_id` 一旦成为身份来源，"
            "同一轮就有两处身份写入点，而两者语义并不等价"
            "（信封里的 sender 是「谁发的」，轮身份里的 user_id 是「按哪个用户隔离记忆」）"
        )
        assert observed["content"] == "你好", observed

    def test_senderStillReachesTheTransportPlane(self):
        """⑤ 不接线的前提之一：入口确实把 sender 交给了信封，没半路丢掉。"""
        caught: Dict[str, str] = {}

        async def probeHandler(message, args):
            caught["sender_id"] = message.sender_id
            return RouteResult(success=True, response="ok", handler="command",
                               message_type=message.message_type)

        router = MessageRouter(agent=None, skill_registry=None, memory_manager=None)
        router.register_command_handler("probe", probeHandler)
        host, process_message = _EntryHost(router), Agent.process_message

        asyncio.run(process_message(host, "/probe", sender="alice"))

        assert caught.get("sender_id") == "alice", caught

    def test_senderIdHasProductionReadersOutsideItsOwnConstruction(self):
        """⑥ 不接线的前提之二：`sender_id` 在生产侧真有读方，不是只写不读的断点。"""
        readers = {
            rel: entry["readers"]
            for rel, entry in scanProduction().items()
            if entry["readers"]
        }
        assert readers, (
            "全仓生产侧再无一处**读** `.sender_id`：那「不接线」这一裁就不成立了，"
            "须回去补读方或退役该字段（AGENTS.md §2 写了没人读即红）"
        )
        assert any(rel.startswith(TRANSPORT_READER_PREFIX) for rel in readers), (
            f"传输面读方消失（实测 {sorted(readers)}）——协议层不再把 sender 带出信封，"
            "`sender_id` 只剩构造点，等同死字段"
        )
