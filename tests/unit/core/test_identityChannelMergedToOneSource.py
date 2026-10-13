# -*- coding: utf-8 -*-
"""§6-163（工单 2026-10-12 批 18，裁定甲「身份通道全量合并」）：一条通道、一处派生。

裁定沿革：§6-121 (b) 先裁「合并到轮身份」→ §6-143 实测否证其前提（`computer.py` 不跑回合，
把读点改指轮身份会让两个控制台用户共用一个浏览器 profile；渠道路径两条通道装的是不同的人）
→ 回到人裁取了乙（只并同源那半区，`582836da`）。本批按**再次裁定的甲**做完，合并方向取
"唯一那条通道装 **sender（谁在说话）**"——另一方向要求给 14 个不跑回合的浏览器端点新造
一条假轮身份，那条代价在隐私侧（profile 共用）。

三条不变量（每一面都配一正一反，证明它不是照着新码抄的形状）：

1. **只有一条身份通道**：`neurova_turn_user_id` 与其读口 `get_turn_user_id()` 退役；
   `set_turn_identity()` 不再收 `user_id`——那个参数一旦留着，两条通道就会在下一个人的
   "顺手补一下"里长回来，这才是本批真正要防的事。
2. **写点仍在请求边界，且渠道写的是发送者**：`channel_router` 不再把 owner 写进这条通道。
3. **会话属主改为显式传参**：`MemCore.save_to_session` 收 `session_owner` 且不再读环境；
   取法单点在 `post_chat_pipeline`（渠道给显式属主，其余入口说话人即属主）。
   拿"谁在说话"当属主会让渠道会话从 agent 属主的控制台里消失（Issue #290 Wave H-W0 回退）。

两条语义变更是本批落地的内容，不是副产品：渠道回合的 usage/按日配额从"按 agent 属主计"
改为**按发送者计**；camofox profile 池在渠道群里**按发送者各开一个**。
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Dict, List

import pytest

from tests import ast_scan as _astScan

REPO = Path(__file__).resolve().parents[3]
CHANNEL_FILES = ("neurova/core/identity_context.py", "neurova/core/turn_context.py")


def source(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def tree(rel: str) -> ast.AST:
    return ast.parse(source(rel))


def functions(root: ast.AST) -> Dict[str, ast.AST]:
    return {n.name: n for n in ast.walk(root)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _callee(call: ast.Call) -> str:
    return getattr(call.func, "id", None) or getattr(call.func, "attr", None) or ""


def _callsNamed(scope: ast.AST, name: str) -> List[ast.Call]:
    return [n for n in ast.walk(scope) if isinstance(n, ast.Call) and _callee(n) == name]


# --- 形状探测器（真码与合成样本共用同一份式子，否则对照是假的）-----------------


def retiredChannelRefs(text: str) -> int:
    """退役那条通道的**代码**痕迹：ContextVar 声明、读口定义、它的调用、`__all__` 导出名。

    刻意按 AST 取，不按全文包含：本批在好几处注释里写了"原先有 `neurova_turn_user_id`"
    这条沿革，按字符串计数会把解释性注释算成通道复活——判据于是永远红，而下次为了让它绿
    的人会把注释删掉，历史就没头了（本卷记过这一族）。
    """
    tree = ast.parse(text)
    hits = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            callee = _callee(node)
            if callee == "ContextVar" and any(
                    isinstance(a, ast.Constant) and a.value == "neurova_turn_user_id"
                    for a in node.args):
                hits += 1
            elif callee == "get_turn_user_id":
                hits += 1
        elif (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
              and node.name == "get_turn_user_id"):
            hits += 1
        elif isinstance(node, ast.Constant) and node.value == "get_turn_user_id":
            hits += 1
    return hits


def turnIdentityParamNames(text: str) -> List[str]:
    fn = functions(ast.parse(text)).get("set_turn_identity")
    assert fn is not None, "找不到 set_turn_identity——轮次上下文本身换了，本档须重写"
    return [a.arg for a in list(fn.args.args) + list(fn.args.kwonlyargs)]


def requestChannelDecls(root: Path) -> List[str]:
    """身份通道的 `ContextVar` 声明处（按 AST，不按文本包含）。

    取数走共享解析预算 `tests/ast_scan`（Issue #148：私有 `rglob + ast.parse`
    把「解析量」绑成「代码总量」，与其余受保护文件共享机器时撞 30s 墙钟）。
    `neurova_request_user_id` 字面量是判据的**充分条件**——不出现这个串的文件
    不可能命中；本函数被两格消费且扫的是同一片树，故走保留型
    `sourceRefsUnder` + 文本预筛。
    """
    out = []
    for ref in _astScan.sourceRefsUnder(root, hints=("neurova_request_user_id",)):
        tree = _astScan._cachedParse(ref.stamp, ref.code)
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and _callee(node) == "ContextVar"
                    and any(isinstance(a, ast.Constant)
                            and a.value == "neurova_request_user_id" for a in node.args)):
                out.append(ref.path.relative_to(REPO).as_posix())
    return out


def channelBoundaryWriteExpressions(text: str) -> List[str]:
    """`_handler` 里每次 `set_request_user_id(...)` 的实参来源（裸变量展开一层赋值）。

    不展开就会放过真形状：路由里写的是 `set_request_user_id(owner)`，`owner` 的上一行才是
    `config.owner_user_id`。只看实参那一格会以为"里面没有 owner_user_id"，判成已合并干净。
    """
    fn = functions(ast.parse(text)).get("_handler")
    assert fn is not None, "找不到 channel_router 的 _handler，本档的靶已换"
    out: List[str] = []
    for call in _callsNamed(fn, "set_request_user_id"):
        if not call.args:
            out.append("<无实参>")
            continue
        arg = call.args[0]
        parts = [ast.dump(arg)]
        if isinstance(arg, ast.Name):
            for node in ast.walk(fn):
                if isinstance(node, ast.Assign) and any(
                        isinstance(t2, ast.Name) and t2.id == arg.id for t2 in node.targets):
                    parts.append(ast.dump(node.value))
        out.append(" | ".join(parts))
    return out


def sessionOwnerFlowsToDisk(texts: Dict[str, str]) -> List[str]:
    """显式属主要一路走到写盘：路由 → post_chat → `_save_to_session` → mem_core。"""
    return [rel for rel, needle in (
        ("neurova/channels/channel_router.py", "session_owner_id"),
        ("neurova/post_chat_pipeline.py", "session_owner"),
        ("neurova/agent_core.py", "session_owner"),
        ("neurova/mem_core.py", "session_owner"),
    ) if needle not in texts[rel]]


class TestOnlyOneIdentityChannelRemains:
    def test_turnIdentityUserChannelIsRetiredEverywhere(self):
        offenders = {rel: retiredChannelRefs(source(rel)) for rel in CHANNEL_FILES
                     if retiredChannelRefs(source(rel))}
        assert not offenders, (
            f"轮身份那条 user_id 通道还在：{offenders}——两条通道并存就是 §6-121 那条"
            "『同一轮两个读数』的老问题，甲没落地")

    def test_setTurnIdentityNoLongerTakesAUserId(self):
        """签名里不许再有 `user_id`：留着它，合并后的第二条通道就有复活的地方。"""
        params = turnIdentityParamNames(source("neurova/core/turn_context.py"))

        assert "user_id" not in params, f"`set_turn_identity` 仍收 user_id：{params}"
        assert {"user_input", "session_id"} <= set(params), (
            f"轮次内容那两格反而被一起删了：{params}——本批只并身份，不并轮次")

    def test_requestChannelIsStillDeclaredExactlyOnce(self):
        decls = requestChannelDecls(REPO / "neurova")
        assert decls == ["neurova/core/identity_context.py"], (
            f"身份通道声明处数 {len(decls)}：{decls}——退役一条不等于允许再造两条")

    def test_noProductionCodeReadsTheRetiredChannel(self):
        # 预筛词是判据的**充分条件**：`retiredChannelRefs` 只认
        # `neurova_turn_user_id` / `get_turn_user_id` 两个符号，连其中之一都没出现的
        # 文件不可能命中。本格只做文本判定（`ref.code`），不建语法树。
        hits = [ref.path.relative_to(REPO).as_posix()
                for ref in _astScan.sourceRefsUnder(
                    REPO / "neurova",
                    hints=("neurova_turn_user_id", "get_turn_user_id"))
                if retiredChannelRefs(ref.code)]
        assert not hits, f"退役通道仍有生产引用：{hits}"


class TestChannelPathCarriesTheSenderOnly:
    def test_channelRouterWritesSenderNotAgentOwner(self):
        dumps = channelBoundaryWriteExpressions(source("neurova/channels/channel_router.py"))

        assert dumps, "渠道路径不再在边界建立身份了？§6-153 的第四条边界塌了"
        for dump in dumps:
            assert "user_id" in dump, f"渠道写点不再取解析单点产出的 user_id：{dump[:140]}"
            assert "owner_user_id" not in dump, (
                f"渠道写点仍在取 agent 属主：{dump[:140]}——owner 与 sender 合并到一条通道"
                "正是本批否掉的方向（会话属主改走显式参数）")

    def test_sessionOwnerIsHandedDownExplicitly(self):
        texts = {rel: source(rel) for rel in
                 ("neurova/channels/channel_router.py", "neurova/post_chat_pipeline.py",
                  "neurova/agent_core.py", "neurova/mem_core.py")}
        missing = sessionOwnerFlowsToDisk(texts)

        assert not missing, (
            f"会话属主在这一环还断了：{missing}——只要有一处仍从环境读身份当属主，"
            "渠道会话就会从 agent 属主的控制台里消失（H-W0 回退＝空属主对全员可见）")

    def test_saveToSessionTakesAnExplicitOwnerAndStopsGuessing(self):
        fn = functions(tree("neurova/mem_core.py"))["save_to_session"]
        params = [a.arg for a in list(fn.args.args) + list(fn.args.kwonlyargs)]

        assert "session_owner" in params, f"`save_to_session` 不显式收属主：{params}"
        assert "get_request_user_id" not in ast.dump(fn), (
            "`save_to_session` 仍从环境里读身份当属主——合并后那条装的是发送者")


class TestTheDetectorsDiscriminateBothWays:
    """每一面都一正一反：合并前那些形状必须被抓，合并后的形状必须放过。"""

    def test_retiredChannelDetectorFiresOnARevival(self):
        base = source("neurova/core/turn_context.py")
        assert retiredChannelRefs(base) == 0, "实现面还没干净，对照无从做起"

        revived = (base + '\nvar2 = ContextVar("neurova_turn_user_id", default=None)\n\n\n'
                   "def get_turn_user_id():\n    return var2.get()\n\n\n"
                   'def currentUserIdShadow():\n    return get_turn_user_id() or "default"\n\n\n'
                   '__all__ = ["get_turn_user_id"]\n')
        hits = retiredChannelRefs(revived)
        assert hits >= 4, (
            f"复活样本只抓到 {hits} 处（声明/定义/调用/导出四形）⇒ 探测器漏形，前面几格不可信")

    def test_commentsAboutTheRetiredNameDoNotCount(self):
        """反方向：把沿革写成注释不许被判成复活——否则下一次为了变绿会去删注释。"""
        commented = ('# 原先这里有第三条 `neurova_turn_user_id`，与 identity_context 那条同答一个问题\n'
                     '"""沿革见 `neurova_turn_user_id` 与 `get_turn_user_id` 两个名字。"""\n')
        assert retiredChannelRefs(commented) == 0, "注释被算成代码 ⇒ 本档那几格会把文档判成缺陷"

    def test_ownerOnChannelPathDetectorFires(self):
        probe = ('async def _handler():\n'
                 '    owner = str(getattr(getattr(agent, "config", None), "owner_user_id", "") or "")\n'
                 "    set_request_user_id(owner)\n")
        dumps = channelBoundaryWriteExpressions(probe)
        assert dumps and all("owner_user_id" in d for d in dumps), \
            f"合成样本造不出旧形状（裸变量没展开一层）：{dumps}"

        merged = probe.replace("set_request_user_id(owner)",
                               'set_request_user_id(turnIdentity["user_id"])')
        assert all("owner_user_id" not in d for d in channelBoundaryWriteExpressions(merged)), \
            "新形状也被抓 ⇒ 上一格恒红，改了也白改"

    def test_sessionOwnerFlowDetectorFiresWhenAStepIsMissing(self):
        complete = {rel: source(rel) for rel in
                    ("neurova/channels/channel_router.py", "neurova/post_chat_pipeline.py",
                     "neurova/agent_core.py", "neurova/mem_core.py")}
        assert not sessionOwnerFlowsToDisk(complete), f"实现未走完：{sessionOwnerFlowsToDisk(complete)}"

        broken = dict(complete)
        broken["neurova/mem_core.py"] = complete["neurova/mem_core.py"].replace(
            "session_owner", "so_wners")
        assert sessionOwnerFlowsToDisk(broken) == ["neurova/mem_core.py"], \
            "把写盘那一环改断也不报 ⇒ 这一面是恒真的空守卫"


class TestTheOwnerResolverIsTheOnlyPlaceAmbientStillCounts:
    """`resolveSessionOwner` 是合并后**唯一**还允许"从环境猜属主"的地方，且只在渠道之外猜。

    为什么用行为格而不是形状格：这一格决定的是渠道群里"谁的控制台看得见这条会话"，
    形状对了而取值顺序反了（先读通道再看显式键）照样把 H-W0 打回原形——
    那时通道里坐的是发送者，属主就会被覆盖成群成员。
    """

    def _withChannel(self, value):
        from neurova.core.identity_context import get_request_user_id, set_request_user_id

        previous = get_request_user_id()
        set_request_user_id(value)
        return previous

    def test_explicitOwnerWinsOverTheSpeaker(self):
        from neurova.post_chat_pipeline import resolveSessionOwner

        previous = self._withChannel("ch:feishu:ou_55")  # 发送者在通道里
        try:
            assert resolveSessionOwner({"session_owner_id": "owner-of-kai"}) == "owner-of-kai", (
                "通道把显式属主盖掉了——渠道会话将从 agent 属主的控制台里消失（H-W0 回退）")
        finally:
            from neurova.core.identity_context import set_request_user_id

            set_request_user_id(previous)

    def test_absentKeyFallsBackToTheSpeakerAndEmptyMeansShared(self):
        from neurova.core.identity_context import set_request_user_id
        from neurova.post_chat_pipeline import resolveSessionOwner

        previous = self._withChannel("u-alice")
        try:
            # 网页/移动端：说话人即属主
            assert resolveSessionOwner({"user_id": "u-alice"}) == "u-alice"
            # 显式带键但为空＝如实声明"没有属主"，不许回落到通道（否则后台任务
            # 会把触发它的那个人的名字写进一条本该共享的会话）
            assert resolveSessionOwner({"session_owner_id": ""}) == ""
            assert resolveSessionOwner(None) == "u-alice"
            set_request_user_id(None)
            assert resolveSessionOwner({}) == "", "无身份时该落共享口径，而不是凭空造一个用户"
        finally:
            set_request_user_id(previous)

    def test_saveToSessionOnlyHonoursTheParameter(self):
        """写盘那一侧：`MemCore.save_to_session` 只把参数交给 `add_message(user_id=…)`。

        它若还从环境读一次，渠道路径上"说话的人"就会覆盖"会话归谁"——那正是本批
        从它身上摘掉的那一行，摘掉就要钉住不许长回来。
        """
        from types import SimpleNamespace

        from neurova.mem_core import MemCore

        captured: Dict[str, object] = {}

        class _RecordingSessions:
            def add_message(self, **kwargs):
                captured.update(kwargs)
                return "sess-1"

        host = SimpleNamespace(session_manager=_RecordingSessions(),
                               config=SimpleNamespace(agent_id="agent-x"))
        MemCore(host).save_to_session("问", "答", session_id="sess-1",
                                      metadata={"user_id": "ch:feishu:ou_55"},
                                      session_owner="owner-of-kai")
        assert captured.get("user_id") == "owner-of-kai", captured
        assert captured.get("metadata") == {"user_id": "ch:feishu:ou_55"}, (
            "发送者那一格被属主覆盖——记忆隔离与可见性本来就是两件事")

        captured.clear()
        MemCore(host).save_to_session("问", "答", session_id="sess-1", metadata={})
        assert captured.get("user_id") == "", (
            f"没给属主时写盘落的是 {captured.get('user_id')!r}——它必须只认参数，"
            "环境里坐着谁都与之无关")


class TestRetiredFacadeStillAnswersTheSameQuestion:
    """`current_user_id` 这类门面不许在合并时改语义，也不许自己再兜一层缺省。"""

    def test_turnStateReadsTheOneChannelDirectly(self):
        fn = functions(tree("neurova/agent/turn_state.py"))["current_user_id"]
        body = ast.dump(fn)

        assert "get_request_user_id" in body, (
            f"`current_user_id` 没读唯一那条通道：{ast.unparse(fn)}")
        assert "Constant(value='default')" not in body, (
            "`current_user_id` 自带 'default' 兜底——兜底口径属于消费方（属主＝空、配额＝anonymous、"
            "池化＝default），门面里再兜一层就是第二个事实源")
