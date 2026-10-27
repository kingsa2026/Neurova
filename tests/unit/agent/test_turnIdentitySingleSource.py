# -*- coding: utf-8 -*-
"""轮身份只有一个写入口；`sender` 走传输面，不得长成第二条身份通道（台账 §6-98 末段）。

来历：`Agent.process_message` 断链根修（`10724888`）之后留下半截事实——入口把 `sender`
放进 `Message.sender_id`，而 `process_message → MessageRouter._route_chat → agent.chat`
这一跳**不读**它（`_route_chat` 只取 `content` 与 `metadata`）。用户 2026-10-10 裁定
**不接线**，本文件就是把那半句裁定钉成可证伪的东西：

- `sender_id` 不是无人读的字段——传输面确有读方（协议层 `to_dict`/回复、ACP 端点），
  不接线不留下"只写不读"的断点（第 ⑥ 格把它钉成读数，免得下次有人当死码摘掉）；
- 一旦把 `Message.sender_id` 喂进身份通道，"这一轮是谁"就多了第二条写入路径：
  与边界处的 `set_request_user_id()`（工具层三层隔离、蜂群事件广播都读它）并存的、
  "某个信封字段顺手抄过来"的那条。后者按调用点手感存在，正是教义第 6 条要禁的平行体系。

**通道按声明名认，不按局部变量名认**（本判据第一版就是这样误报的）：
`neurova/core/identity_context.py` 里那条 ContextVar 的局部名与轮次上下文里原先那条
同名（都叫 `_user_id_var`），声明的却是不同运行时通道——按局部名匹配会把另一条通道上的
正常写点报成"本通道被旁路直写"，那种假红比没有判据更坏（读者会学会无视它）。
所以检出器先解析 `_x = ContextVar("名字")` 的**声明名**，再按声明名归账，并把
"同名不同通道"这一形态本身钉成一条反证（见 ⑦）。

**身份通道今昔只有一条**（§6-163 · 批 18 按裁定甲合并）：与轮身份并存的
`neurova_turn_user_id` 已退役，读口 `get_turn_user_id()` 一并删，`set_turn_identity()`
的签名里不再收 `user_id`。合并方向取「唯一那条通道装 **sender（谁在说话）**」，
会话记录的可见性改由显式参数 `session_owner` 承载（链路见
`tests/unit/core/test_identityChannelMergedToOneSource.py`）。本文件因此从"两条通道各自
单一写方"升级为"这条通道就是全部"：多一条身份类 ContextVar、多一处写点、
少一处读点，都在这里红。读方台账那八→九处的实测来由照旧成立——
合并与否曾按"读两处"的错误数拍过板，读数必须自己算。
"""

import ast
import asyncio
import inspect
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List, Optional, Set, Tuple

from neurova.agent.turn_state import TurnState
from neurova.agent_core import Agent
from neurova.core.identity_context import get_request_user_id, set_request_user_id
from neurova.router import MessageRouter, RouteResult
from tests import ast_scan
from tests.ast_scan import parseSource

REPO_ROOT = Path(__file__).resolve().parents[3]
PRODUCTION = REPO_ROOT / "neurova"

#: 三条通道变量的**声明名**（ContextVar 的运行时身份）。新增第四条时本表必须跟着长，
#: 否则新通道无人守；`test_theDetectorsAreNotVacuous` 只保证检出现有的写法。
#: 前两条 = 轮次内容（user_input / session_id），第三条 = **唯一**的身份通道
#: （§6-163 按裁定甲合并后，`neurova_turn_user_id` 已退役，本表里不许再长出第二条装
#: user_id 的通道——两条并存就是 §6-121 那句"同一轮两个读数"的老问题）。
WRITERS: Dict[str, Set[str]] = {
    "neurova_turn_user_input": {
        "neurova/core/turn_context.py::set_turn_identity",
        # A-04 契约的单字段 setter：`Agent._current_user_input` 的后端，
        # 只动 user_input 一格、不碰 session 那一格。写成"整个身份一个写方"
        # 会把这条既有契约谎报成违规，也拦不住它长大。
        "neurova/core/turn_context.py::set_turn_user_input",
    },
    "neurova_turn_session_id": {"neurova/core/turn_context.py::set_turn_identity"},
    "neurova_request_user_id": {
        "neurova/core/identity_context.py::set_request_user_id",
        "neurova/core/identity_context.py::clear_request_user_id",
    },
}

#: 轮次内容两通道（不含身份通道）——`set_turn_identity` 只该写这两条。
TURN_IDENTITY = ("neurova_turn_user_input", "neurova_turn_session_id")

#: 身份通道 `neurova_request_user_id` 的**读方台账**。
#:
#: 立账的缘由：§6-121 把这条通道的读面写成"两处（browser_manager / camofox_server_backend）"，
#: 那条数是用 computer_use 目录筛出来的，不是全仓复算。本文件的探测器实测**九处**，
#: 且各处的兜底口径不同（`or "default"` / `or "anonymous"` / 回落 `backend._user_id` /
#: `or self._agent_identity()[0]` / 裸取无兜底）——按名推断裁会把成本归因、会话属主、
#: MCP 身份三条不同的关注点当成"同一个用户键"一起搬走。
#: §6-163 合并让读数发生两处变化，逐条记在这里免得下次当成漂移：
#: `MemCore.save_to_session` 的 ambient 读**退役**（会话属主改由显式参数传，合并后这条
#: 通道装的是发送者，拿它当属主会让渠道会话从 agent 属主的控制台里消失）；
#: 新增 `TurnState.current_user_id`（门面直读唯一通道，不再自带 'default' 兜底——
#: 兜底口径属于消费方，门面再兜一层就是第二个事实源）
#: 与 `post_chat_pipeline.resolveSessionOwner`（属主取法单点：显式键优先，缺省才读通道）。
#: 先钉住读面：多一处读点即红（少一处也要红，退役一条读点同样是一次口径变更）。
READERS: Dict[str, Set[str]] = {
    "neurova_request_user_id": {
        "neurova/agent/turn_state.py::TurnState.current_user_id",
        "neurova/computer_use/browser_manager.py::BrowserManager._get_or_create_user_camofox_backend",
        "neurova/computer_use/camofox_server_backend.py::CamofoxServerBackend._eff_user_id",
        "neurova/llm/multi_model_client.py::MultiModelLLMClient._chat_single_attempt",
        "neurova/llm/multi_model_client.py::MultiModelLLMClient.chat_stream",
        "neurova/llm/multi_model_client.py::_consume_llm_quota",
        "neurova/post_chat_pipeline.py::resolveSessionOwner",
        "neurova/tool_executor.py::ToolExecutor._execute_computer_ssh_exec",
        "neurova/tool_layers/mcp_server.py::NeurovaMCPServer._current_user_id",
    },
}

#: 每条通道变量的**声明所在文件**（一条通道只许一处声明，否则连"是哪条通道"都有两说）。
DECLARED_IN: Dict[str, str] = {
    "neurova_turn_user_input": "neurova/core/turn_context.py",
    "neurova_turn_session_id": "neurova/core/turn_context.py",
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
    return declaredVarsAmong(tuple(ast.walk(tree)))


def declaredVarsAmong(nodes) -> Dict[str, str]:
    """已走查过的版本（见 `identityWritesAmong` 对"遍历与判定拆开"的说明）。"""
    out: Dict[str, str] = {}
    for node in nodes:
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
    """`dotted 模块名 → 该模块声明的 ContextVar`。

    **文本预筛 `ContextVar`**：`declaredVars` 只认 `ContextVar(...)` 的赋值，连这个
    词都没出现的文件必然给出空表——它进不了索引，也就无人能隔着模块点名直写这条通道。
    索引的**键仍是全量清单**（`sourceRefsUnder` 的枚举口径不变），只是不解析那些
    不可能贡献声明的文件（实测 `neurova/` 1021 → 27 文件）。
    """
    global _declIndex
    if _declIndex is None:
        refs = ast_scan.sourceRefsUnder(PRODUCTION, hints=("ContextVar",))
        assert refs, f"预筛后声明面为空（{PRODUCTION}）——本文件会空转"
        _declIndex = {
            _dottedOf(ast_scan.relativeToRepo(ref.path)):
                declaredVars(ast_scan.transientTree(ref.path))
            for ref in refs
        }
    return _declIndex


def channelMap(tree: ast.AST) -> Tuple[Dict[str, str], Dict[str, Dict[str, str]]]:
    """本文件的 `(局部名→通道名, 模块别名→该模块的 局部名→通道名)`。

    两条解析路都要：`from x import _user_id_var`（直接名字）与
    `from neurova.core import turn_context` 后的 `turn_context._user_id_var.set(...)`
    （模块别名 + 属性）——漏掉任一条，旁路写点就从网眼里过去。
    """
    return channelMapAmong(tuple(ast.walk(tree)), tree)


def channelMapAmong(nodes, tree: ast.AST) -> Tuple[Dict[str, str], Dict[str, Dict[str, str]]]:
    """已走查过的版本（见 `identityWritesAmong` 对"遍历与判定拆开"的说明）。"""
    direct = declaredVarsAmong(nodes)
    index = declIndex()
    aliased: Dict[str, Dict[str, str]] = {}
    for node in nodes:
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
    return identityWritesAmong(tuple(ast.walk(tree)), tree, rel)


def identityWritesAmong(nodes, tree: ast.AST,
                        rel: str) -> List[Tuple[str, str]]:
    """已走查过的版本：`scanProduction` 逐文件只趟一次节点。

    本文件六格共用一趟扫描，若每格各自 `ast.walk(tree)`，同一棵树要被走查四到五遍
    （实测 `neurova/` 1021 棵树 = 1750 万次 `ast.walk`，两条用例各 14.5s 级 / 552MB）。
    判据的成本于是绑在**代码总量**上——正是 `tests/ast_scan.py` 开头点名的那形态。
    故把「遍历」与「判定」拆开：遍历由调用方一次给（`scanProduction` 之上去共享节点
    预算），判定在这里字字不动。
    """
    parents = _parents(tree)
    direct, aliased = channelMapAmong(nodes, tree)
    hits: List[Tuple[str, str]] = []
    for node in nodes:
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
    return identityWritesIn(parseSource(source), rel)


def setIdentityCallersIn(tree: ast.AST, rel: str) -> List[str]:
    """对 `set_turn_identity(...)` 的**调用**落点（`__all__` 里的字符串不是调用）。"""
    return setIdentityCallersAmong(tuple(ast.walk(tree)), tree, rel)


def setIdentityCallersAmong(nodes, tree: ast.AST, rel: str) -> List[str]:
    """已走查过的版本（见 `identityWritesAmong` 对"遍历与判定拆开"的说明）。"""
    parents = _parents(tree)
    hits: List[str] = []
    for node in nodes:
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else (
            func.attr if isinstance(func, ast.Attribute) else "")
        if name == "set_turn_identity":
            hits.append(f"{rel}::{_enclosingFunction(node, parents)}")
    return hits


def setIdentityCallers(source: str, rel: str) -> List[str]:
    return setIdentityCallersIn(parseSource(source), rel)


def senderIdReadersIn(tree: ast.AST) -> int:
    """把 `.sender_id` 当**读**用（Load）的次数；赋值左侧（Store）不计。"""
    return senderIdReadersAmong(tuple(ast.walk(tree)))


def senderIdReadersAmong(nodes) -> int:
    """已走查过的版本（见 `identityWritesAmong` 对"遍历与判定拆开"的说明）。"""
    return sum(
        1 for node in nodes
        if isinstance(node, ast.Attribute) and node.attr == "sender_id"
        and isinstance(node.ctx, ast.Load)
    )


def senderIdReaders(source: str) -> int:
    return senderIdReadersIn(parseSource(source))


def requestUserIdReadersIn(tree: ast.AST, rel: str) -> List[str]:
    """读 `get_request_user_id()` 的落点（`file::限定函数名`）。

    并行通道只有写方入账、读方无人登记，是 §6-121 那句"读两处"被算错的根子：
    实测这条通道上挂着八处生产读点，兜底口径各不相同（`or "default"` /
    `or "anonymous"` / `or self._agent_identity()[0]` / 裸取）。合并与否要按真读数裁，
    不能按名字推断裁——所以先把读面钉成台账，多一处读点即红。
    """
    return requestUserIdReadersAmong(tuple(ast.walk(tree)), tree, rel)


def requestUserIdReadersAmong(nodes, tree: ast.AST, rel: str) -> List[str]:
    """已走查过的版本（见 `identityWritesAmong` 对"遍历与判定拆开"的说明）。"""
    parents = _parents(tree)
    hits: List[str] = []
    for node in nodes:
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else (
            func.attr if isinstance(func, ast.Attribute) else "")
        if name == "get_request_user_id":
            hits.append(f"{rel}::{_enclosingFunction(node, parents)}")
    return hits


def requestUserIdReaders(source: str, rel: str) -> List[str]:
    return requestUserIdReadersIn(parseSource(source), rel)


#: 生产扫描面的**文本预筛词**：本文件六格的判据只可能命中含这些符号（或须建
#: ContextVar 索引）的文件。三个通道声明名、轮身份唯一入口、两条 ContextVar 读写口、
#: 以及 `sender_id` 那个属性。预筛是判据的**充分条件**，不是把面砍窄——键仍按
#: `neurova/` 全量清单枚举，只是不解析那些不可能命中的文件（实测 1021 → 57，
#: 取数经全量口径逐条比对，零漏报）。
SCAN_HINTS = (
    "ContextVar", "set_turn_identity", "get_request_user_id",
    "set_request_user_id", "get_turn_user_id", "neurova_request_user_id",
    "neurova_turn_user_input", "neurova_turn_session_id", "sender_id",
)

_scan: Optional[Dict[str, Dict[str, object]]] = None


def scanProduction() -> Dict[str, Dict[str, object]]:
    """一趟扫完生产面，逐文件备好五件读数；本文件六格共用这一份。

    语法树取自 `tests/ast_scan.py` 的整进程缓存（同一份源码只编译一次），本函数只
    在此之上做一次归账遍历。分格各扫一遍实测把两条用例各推到 14.5s 级 / 552MB，
    而默认 `timeout = 30`、受保护子集与 6000 条用例共享 CI 的 2~4 vCPU——判据自己
    就能把门禁拖红（实测 `cnb-mei-1k4odroc5-003` 与 `cnb-o9g-1k4oij3vm-003`）。

    两层收口（同根：判据的成本不许绑在代码总量上）：

    1. **文本预筛** `SCAN_HINTS` 把解析量从「代码总量」降到「命中面」；
    2. **每文件只趟一遍节点**：五个检出器共用同一趟 `nodes` 与同一份 `_parents`
       （改前每格各自 `ast.walk`，实测 1021 棵树 = 1750 万次 walk）。
    """
    global _scan
    if _scan is None:
        out: Dict[str, Dict[str, object]] = {}
        for ref in ast_scan.sourceRefsUnder(PRODUCTION, hints=SCAN_HINTS):
            tree = ast_scan.transientTree(ref.path)
            nodes = tuple(ast.walk(tree))
            rel = ast_scan.relativeToRepo(ref.path)
            out[rel] = {
                "writes": identityWritesAmong(nodes, tree, rel),
                "callers": setIdentityCallersAmong(nodes, tree, rel),
                "readers": senderIdReadersAmong(nodes),
                "requestReaders": requestUserIdReadersAmong(nodes, tree, rel),
                "declared": declaredVarsAmong(nodes),
            }
        assert out, (
            f"预筛后面为空（{PRODUCTION} / {SCAN_HINTS}）——判据会空转，"
            "预筛词必须与判据同源"
        )
        _scan = out
    return _scan


def liveReaderLedger() -> Dict[str, Set[str]]:
    live: Dict[str, Set[str]] = {name: set() for name in READERS}
    for entry in scanProduction().values():
        for hit in entry["requestReaders"]:  # type: ignore[union-attr]
            channel = "neurova_request_user_id"
            if channel in live:
                live[channel].add(hit)
    return live


def liveWriterLedger() -> Dict[str, Set[str]]:
    live: Dict[str, Set[str]] = {name: set() for name in WRITERS}
    for entry in scanProduction().values():
        for channel, hit in entry["writes"]:  # type: ignore[index]
            live[channel].add(hit)
    return live


class _IdentityRecordingAgent:
    """下游 agent：在**被路由到的那一刻**记录轮次与身份（事后读会读到别的轮写进去的）。

    形参名照真 `Agent.chat` 写：§6-161 那枚教训是「桩件的签名替坏掉的契约背书」——
    这里若把首个形参写成 `content`，路由隔着位置参数调用照样绿，而真 `Agent.chat`
    的形参叫 `user_input`，下一个按关键字改调用点的人就得不到任何预警。
    """

    def __init__(self):
        self.seen: List[Dict[str, object]] = []

    async def chat(self, user_input, session_id=None, metadata=None, **kwargs):
        state = TurnState()
        self.seen.append({
            "content": user_input,
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

    def test_requestUserIdReadersMatchTheLedgerExactly(self):
        """⑨ 并行通道的**读方**逐处入账：多一处、少一处都红。

        立这格的动因是一次算错的读数：§6-121 写这条通道"读两处"，实为八处，
        且兜底口径各不相同。合并两条"本轮哪个用户"的通道是个隔离语义的决定，
        必须按真读数做——先把面钉住，别让下一个人在同样一个错数上拍板。
        少一处也红：退役一条读点是同一次口径变更，不能悄悄发生。
        """
        live = liveReaderLedger()
        drifted = [
            f"  {name}: 台账 {sorted(READERS[name])} / 实测 {sorted(live[name])}"
            for name in sorted(READERS) if live[name] != READERS[name]
        ]
        assert drifted == [], "并行通道的读方与台账不一致：\n" + "\n".join(drifted)

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
            "_session_id_var = ContextVar('neurova_turn_session_id', default=None)\n"
            "def rogueWriter(value):\n    _session_id_var.set(value)\n"
        )
        assert identityWrites(rogue, "synthetic.py") == [
            ("neurova_turn_session_id", "synthetic.py::rogueWriter")
        ], "检出器抓不到模块级通道的旁路写点——①② 两格都会空转"

        lookAlike = (
            "from contextvars import ContextVar\n"
            "_user_id_var = ContextVar('neurova_request_user_id', default=None)\n"
            "def set_request_user_id(value):\n    _user_id_var.set(value)\n"
        )
        assert identityWrites(lookAlike, "synthetic.py") == [
            ("neurova_request_user_id", "synthetic.py::set_request_user_id")
        ], "按声明名归账失效：局部名 `_user_id_var` 被按名字记到了轮次内容通道上——" \
           "那种假红会让人无视本判据（合并后两模块里同局部名的还有 `_user_input_var`）"

        viaAlias = (
            "from neurova.core import turn_context\n"
            "def bypass(v):\n    turn_context._user_input_var.set(v)\n"
        )
        assert identityWrites(viaAlias, "synthetic.py") == [
            ("neurova_turn_user_input", "synthetic.py::bypass")
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
        assert set(requestUserIdReaders(
            "from neurova.core.identity_context import get_request_user_id\n"
            "def reader():\n    return get_request_user_id() or 'default'\n"
            "def viaModule():\n"
            "    from neurova.core import identity_context\n"
            "    return identity_context.get_request_user_id()\n",
            "synthetic.py",
        )) == {"synthetic.py::reader", "synthetic.py::viaModule"}, (
            "并行通道的读点没被抓出来——读方台账 ⑨ 会空转，第八处读点悄悄长出来无人知道"
        )
        assert requestUserIdReaders(
            "def get_request_user_id():\n    return None\n", "s.py") == [], (
            "把声明本身当成读点——读方台账会被定义处自己打红"
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
    def test_processMessageLeavesIdentityUntouched(self):
        """④ 行为面：入口带 sender 走传输面，但不得改写已进入的唯一身份通道。"""
        downstream = _IdentityRecordingAgent()
        router = MessageRouter(agent=downstream, skill_registry=None, memory_manager=None)
        host, process_message = _EntryHost(router), Agent.process_message

        previous = get_request_user_id()
        TurnState().set_request_identity("原输入", "sess-A")
        set_request_user_id("user-A")
        try:
            result = asyncio.run(process_message(host, "你好", sender="someone"))
        finally:
            set_request_user_id(previous)

        assert result.success is True, result
        assert downstream.seen, "根本没走到被路由的那一跳——本格的断言是空的"
        observed = downstream.seen[0]
        assert (
            observed["session_id"] == "sess-A" and observed["user_id"] == "user-A"
            and observed["user_input"] == "原输入"
        ), (
            f"入口改写了身份：{observed}——`Message.sender_id` 一旦成为身份来源，"
            "同一轮就有两处身份写入点，而两者语义并不等价"
            "（信封里的 sender 是「谁发的」，通道里的 user_id 是「按哪个用户隔离与计费」）"
        )
        assert observed["content"] == "你好", observed

    def test_theRecordingStubStillMatchesTheRealChatContract(self):
        """④b 桩件不许替坏掉的契约背书（§6-161 同族）：路由那处调用得能绑上真签名。

        只查桩件形参名不够——本格的靶是**调用点**：路由隔着 `chat(message.content,
        metadata=...)` 调用，若哪天有人把它改成 `chat(content=...)`，桩件带 `**kwargs`
        照样绿，而真 `Agent.chat` 必 TypeError。合并动过这条链的签名面，就该在这里被钉住。
        """
        realParams = set(inspect.signature(Agent.chat).parameters)
        stubParams = set(inspect.signature(_IdentityRecordingAgent.chat).parameters) - {"self", "kwargs"}
        assert stubParams <= realParams, (
            f"桩件形参 {sorted(stubParams)} 里有真 `Agent.chat` 不认的名字"
            f"（真签名：{sorted(realParams)}）——桩件在替一个不存在的契约背书")

        calls: List[Tuple[int, Dict[str, object]]] = []
        routerTree = parseSource((REPO_ROOT / "neurova/router.py").read_text(encoding="utf-8"))
        for node in ast.walk(routerTree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "chat" and "agent" in ast.unparse(node.func.value)):
                calls.append((len(node.args), {kw.arg: kw for kw in node.keywords if kw.arg}))
        assert calls, "router 里找不到 `…agent.chat(...)` 调用点——本格的靶已换"
        for nPositional, kwargs in calls:
            # 首个 None 占掉 `self`（这里是未绑定的函数对象），其余按调用点**真实**的位置
            # 参数量铺——调用点少给了必填项，这里就该红，而不是被测试自己补一个占位填平。
            args = (None,) + ("占位",) * nPositional
            inspect.signature(Agent.chat).bind(*args, **kwargs)
            inspect.signature(_IdentityRecordingAgent.chat).bind(*args, **kwargs)

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


def test_productionSurfaceIsNotEmpty():
    """面自证：本档两条腿都从 `neurova/` 取数，根被改窄时读数是「零旁路」而不是红。

    两条腿的扫描都带**文本预筛**（`ContextVar` / `SCAN_HINTS`），预筛命中数不随根的大小变，
    所以面另由共享枚举入口量一次。这一格独立存在是因为把 `filesUnder` 塞进被消费的 helper 里，
    会让该 helper 的调用闭包同时具备「枚举 + 私有解析」两条落点——正是预算门禁点名要红的形状
    （`tests/unit/test_ci_ast_scan_budget_guard.py`），而门禁的判断在这里是对的：
    面读数不该让判据为它多付一趟解析。
    """
    surface = len(ast_scan.filesUnder(PRODUCTION))
    assert surface > 500, (
        f"扫描面现读 {surface} 档 .py（根＝{PRODUCTION}，本判据的域＝生产源码）"
        "——量级对不上生产源码总数＝根被改窄，下面那些「零命中」都不来自代码")
