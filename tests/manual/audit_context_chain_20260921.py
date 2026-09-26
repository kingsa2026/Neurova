"""上下文三条链路（压缩 / 组装 / 池）审计取证脚本 — 2026-09-21。

手工运行，不进 CI：
    .venv/Scripts/python.exe tests/manual/audit_context_chain_20260921.py

只做取证，不修改仓库状态；所有写盘（驱逐台账 DB）重定向到系统临时目录。
每条探针输出 PROBE 名称 + 结论行，报告按此编号引用实测结果。
"""

from __future__ import annotations

import shutil
import tempfile
from types import SimpleNamespace
from pathlib import Path

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402
isolatedDataRoot()

RESULTS: list[tuple[str, str]] = []


def emit(probe: str, verdict: str) -> None:
    RESULTS.append((probe, verdict))
    print(f"[{probe}] {verdict}")


def _fold_cache(orch) -> tuple:
    """取折叠缓存的唯一条目（键名随实现演进：`_` → 会话/作用域键）。

    探针不锁键名，只锁"条目数与内容"——键名本身由 P2 的期望值判定。
    """
    cache = orch._window_compaction_cache
    key = next(iter(cache), None)
    return key, dict(cache[key]) if key else {}


def _tmp_ledger_dir() -> Path:
    base = Path(tempfile.mkdtemp(prefix="neurovaCtxAudit_"))
    # 驱逐台账按 f"data/context_ledger/{agent_id}.db" 建库，重定向进临时目录，
    # 避免探针在仓库 data/ 留下一次性文件。
    import neurova.context.eviction_ledger_db as ledger_mod

    real = ledger_mod.EvictionLedgerDB

    def _redirected(**kwargs):
        kwargs["db_path"] = str(base / Path(kwargs["db_path"]).name)
        return real(**kwargs)

    ledger_mod.EvictionLedgerDB = _redirected
    return base


# ─────────────────────────────────────────────────────────────────────────────
# P1 池召回路径的会话作用域隔离是否为恒真判断
# ─────────────────────────────────────────────────────────────────────────────
def p1():
    """走**生产写入咽喉**：build_context 每轮把 turn_scope/session_id 设进池，
    打标发生在 ContextPool.add_context（`_inject_isolation_tags`）。
    旧版探针手工造无 chat_scope 的条目，测的是修复前的形状 → 假阴。"""
    from neurova.collaboration.memory_scope import filter_by_scope
    from neurova.context_pool import ContextInput, ContextPool, ContextSource

    pool = ContextPool(user_id="u1", agent_id="a1", session_id=None, ttl_seconds=0)
    # 复刻群轮 B 的归档（orchestrator.build_context 的写法）
    pool.turn_scope = "room:project_roomB"
    pool.session_id = "project_roomB"
    pool.add_context(
        ContextInput(
            source=ContextSource.CONVERSATION,
            content="协作房间 project_roomB 里透露的报价数字",
            priority=60,
            metadata={"role": "user", "turn_id": "turn_1"},
        )
    )
    chunk = pool.get_contexts()[0]
    drawn = pool.draw(need="报价")
    single = filter_by_scope(drawn, lambda c: c.metadata or {}, collab=False, room_id="")
    other_room = filter_by_scope(
        drawn, lambda c: c.metadata or {}, collab=True, room_id="project_roomA"
    )
    same_room = filter_by_scope(
        drawn, lambda c: c.metadata or {}, collab=True, room_id="project_roomB"
    )
    emit(
        "P1",
        f"chunk.metadata 含 chat_scope={'chat_scope' in chunk.metadata}; "
        f"单聊轮保留={len(single)}/{len(drawn)}; 他群轮保留={len(other_room)}/{len(drawn)}; "
        f"本群轮保留={len(same_room)}/{len(drawn)}（期望 0/1、0/1、1/1）",
    )

    # 对照组：旧形状（调用方绕过咽喉手工写入、且 turn_scope 未设）
    pool2 = ContextPool(user_id="u1", agent_id="a2", session_id=None, ttl_seconds=0)
    pool2.add_context(
        ContextInput(source=ContextSource.CONVERSATION, content="未打标的历史条目", priority=60)
    )
    legacy = filter_by_scope(pool2.get_contexts(), lambda c: c.metadata or {}, collab=False, room_id="")
    emit("P1-对照", f"绕过咽喉且未设 turn_scope 的条目在单聊轮保留={len(legacy)} 条（缺标即恒判 direct）")


# ─────────────────────────────────────────────────────────────────────────────
# P2 折叠跨轮缓存的 session 维度
# ─────────────────────────────────────────────────────────────────────────────
def _make_orchestrator(tmp_base: Path):
    from neurova.context.orchestrator import ContextOrchestrator

    cfg = SimpleNamespace(
        llm_model="gpt-4o", agent_id="audit_agent", workspace_path="", name="audit",
        constitution="", behavior_rules=[], show_empathy=True,
    )
    agent_ref = SimpleNamespace(
        config=cfg, user_id="u1", agent_id="audit_agent",
        llm_client=None, memory_manager=None, growth_log_manager=None,
    )
    orch = ContextOrchestrator(agent_ref, use_pool=True, session_id=None)
    return orch


def p2(tmp_base: Path):
    """折叠跨轮缓存的会话维度。

    生产里键由 `_resolve_window_cache_key()` = `_turn_room_id or _session_id or "direct"`
    决定，而 `_turn_room_id` 在 build_context 里被设为 `chat_room_id or (self._session_id or "")`。
    两种形状分别验：群轮（有房间 id）与两个普通单聊会话（无房间 id、且 agent_core 未传 session_id）。
    """
    import asyncio

    orch = _make_orchestrator(tmp_base)
    emit("P2-session_id", f"orch.session_id={orch.session_id!r} pool.session_id={orch.context_pool.session_id!r}")

    async def fake_summarize(dropped_msgs, previous_summary=""):
        """摘要文本必须**由输入决定**，否则"串台"判据会被桩自身污染（假阳）。"""
        text = " ".join((m or {}).get("content", "") for m in dropped_msgs or [])
        topic = "量子" if "量子" in text else ("火星" if "火星" in text else "未知")
        return f"本段摘要：讨论{topic}"

    orch._window_summarizer = fake_summarize  # 占位摘要桥，绕开摘要器初始化路径

    histA = [{"role": "user", "content": f"A轮{i} " + "量子" * 60} for i in range(12)]
    histB = [{"role": "user", "content": f"B轮{i} " + "火星" * 60} for i in range(12)]

    async def fold(room_id_a, room_id_b):
        orch._turn_room_id = room_id_a
        wa = await orch._apply_window_budget(histA, 300)
        orch._turn_room_id = room_id_b
        wb = await orch._apply_window_budget(histB, 300)
        return wa, wb

    # 形状一：两个普通单聊会话（生产当前值：都是 ""）
    wa, wb = asyncio.run(fold("", ""))
    direct_bleed = "量子" in wb[0]["content"]
    # 形状二：两个不同协作房间（房间 id 可区分）
    wa2, wb2 = asyncio.run(fold("project_roomA", "project_roomB"))
    room_bleed = "量子" in wb2[0]["content"]
    emit(
        "P2",
        f"缓存键集合={sorted(orch._window_compaction_cache)}; "
        f"单聊两会话串台={direct_bleed}; 两个房间串台={room_bleed}（两者都应为 False）",
    )


# ─────────────────────────────────────────────────────────────────────────────
# P3 视图归一化剥掉 tool 身份字段 → microcompact 占位指针失去硬地址
# ─────────────────────────────────────────────────────────────────────────────
def p3(tmp_base: Path):
    import asyncio

    orch = _make_orchestrator(tmp_base)
    big = "x" * 9000
    msgs = [
        {
            "role": "tool",
            "tool_call_id": "call_7F3k",
            "name": "web_search",
            "content": "检索结果正文 " + big,
        },
        {"role": "user", "content": "继续" + big},
        {"role": "assistant", "content": "好的" + big},
    ]
    kept = asyncio.run(orch._apply_window_budget(msgs, 100000))
    fields = sorted(kept[0].keys()) if kept else []
    cleared = orch._clear_old_tool_results(kept)
    placeholder = next((m["content"] for m in cleared if str(m["content"]).startswith("[工具输出已移出")), "")
    emit("P3", f"归一化后 role=tool 消息字段={fields}; 占位指针={placeholder[:70]!r}")


# ─────────────────────────────────────────────────────────────────────────────
# P4 归档 hash 与防召回 hash 命名空间不一致
# ─────────────────────────────────────────────────────────────────────────────
def p4():
    from neurova.context_pool import ContextInput, ContextSource

    content = "工具返回的一段结果正文"
    h_conv = ContextInput.compute_hash(ContextSource.CONVERSATION, content)
    h_tool = ContextInput.compute_hash(ContextSource.TOOL_CALL, content)
    emit("P4", f"CONVERSATION hash={h_conv[:10]} TOOL_CALL hash={h_tool[:10]} 相等={h_conv == h_tool}")


# ─────────────────────────────────────────────────────────────────────────────
# P5 生产形状的池：驱逐台账是否真的被写入
# ─────────────────────────────────────────────────────────────────────────────
def p5(tmp_base: Path):
    from neurova.context.eviction_ledger_db import EvictionLedgerDB
    from neurova.context_pool import ContextInput, ContextPool, ContextSource

    db = EvictionLedgerDB(
        db_path=str(tmp_base / "audit_ledger.db"), user_id="u1", agent_id="audit_agent"
    )
    pool = ContextPool(
        user_id="u1", agent_id="audit_agent", session_id=None, ledger_db=db,
        max_tokens=16000, ttl_seconds=0,
    )
    for i in range(600):
        pool.add_context(
            ContextInput(source=ContextSource.CONVERSATION, content=f"第{i}轮对话内容", priority=60)
        )
    emit(
        "P5",
        f"resident_limit={pool.resident_limit} ttl={pool.ttl_seconds} cleanup_expired()={pool.cleanup_expired()} "
        f"内存台账={len(pool._eviction_ledger)} 台账行数={db.search(None, session_id=None, limit=50) and len(db.search(None, session_id=None, limit=50))} "
        f"recall_evicted()={len(pool.recall_evicted('第599轮'))}",
    )


# ─────────────────────────────────────────────────────────────────────────────
# P6 neurflow 上下文节点依赖的符号是否存在
# ─────────────────────────────────────────────────────────────────────────────
def p6():
    try:
        from neurova.context_pool import get_context_pool  # noqa: F401

        emit("P6", "get_context_pool 可导入")
    except ImportError as e:
        emit("P6", f"ImportError: {e}")
    from neurova.collaboration.neurflow.builtin import _get_context_pool, exec_context
    import asyncio

    emit("P6-2", f"_get_context_pool()={_get_context_pool()!r}; exec_context 无注入结果={asyncio.run(exec_context({}, {})).get('status')}")


# ─────────────────────────────────────────────────────────────────────────────
# P7 API 端点的池是否为跨请求共享
# ─────────────────────────────────────────────────────────────────────────────
def p7():
    from neurova.api.endpoints.context import _get_context_builder
    from neurova.context_pool import ContextInput, ContextSource

    b1 = _get_context_builder(user_id="u1", agent_id="a1", session_id="s1")
    b2 = _get_context_builder(user_id="u1", agent_id="a1", session_id="s1")
    b1.add_context(ContextInput(source=ContextSource.USER_INPUT, content="上一条请求写入", priority=10))
    emit(
        "P7",
        f"两次端点取到同一池={b1 is b2}; 第二次请求可见条目数={len(b2.get_contexts())}; "
        f"写入条目 priority={b1.get_contexts()[0].priority}",
    )


# ─────────────────────────────────────────────────────────────────────────────
# P8 token 估算口径分歧
# ─────────────────────────────────────────────────────────────────────────────
def p8():
    from neurova.context.token_estimator import estimate_tokens
    from neurova.context.composition import _estimate as comp_estimate
    from neurova.context.window_compactor import estimate_window_tokens

    texts = {
        "中文": "请帮我压缩上下文并检查上下文池的召回是否漏掉了群聊内容",
        "英文": "Please compact the context window and audit the retrieval pool for missing chunks",
        "混合": "把 context pool 的 draw 预算调低一点，谢谢",
    }
    rows = []
    for label, text in texts.items():
        rows.append(
            f"{label}: 统一BALANCED={estimate_tokens(text)} EXACT={comp_estimate(text)} "
            f"len//4={len(text) // 4} len*1.5={int(len(text) * 1.5)} 字符={len(text)}"
        )
    try:
        import tiktoken

        c100 = tiktoken.get_encoding("cl100k_base")
        o200 = tiktoken.get_encoding("o200k_base")
        t = texts["英文"]
        enc = f" cl100k={len(c100.encode(t))} o200k={len(o200.encode(t))}"
    except Exception as e:  # noqa: BLE001
        enc = f" tiktoken不可用({type(e).__name__})"
    one = estimate_window_tokens([{"role": "user", "content": texts["中文"]}])
    emit("P8", " | ".join(rows) + f" || 窗口口径(含每条+4)={one} ||{enc}")


# ─────────────────────────────────────────────────────────────────────────────
# P9 draw 预算联动：system 前缀挤占后召回额度落到地板
# ─────────────────────────────────────────────────────────────────────────────
def p9(tmp_base: Path):
    from neurova.context.window_compactor import estimate_window_tokens

    orch = _make_orchestrator(tmp_base)
    sys_prefix = ["你是神经瓦……" + "人格设定" * 800, "行为准则" * 1200]
    dev = ["工具使用方法论" * 900]
    budget = orch._compute_window_budget(sys_prefix, dev, "")
    resolved = orch._resolve_window_token_budget()
    window_msgs = [{"role": "user", "content": "短问题"}] * 6
    remaining = max(1000, budget - estimate_window_tokens(window_msgs))
    drawer_before = orch.context_pool._drawer.max_tokens
    emit(
        "P9",
        f"模型预算={resolved} 扣 system 前缀后窗口预算={budget}（floor=1000） "
        f"drawer 初值(=池 max_tokens)={drawer_before} → 每轮改写为={remaining}",
    )


# ─────────────────────────────────────────────────────────────────────────────
# P10 摘要器缺失时的折叠退化
# ─────────────────────────────────────────────────────────────────────────────
def p10(tmp_base: Path):
    import asyncio

    orch = _make_orchestrator(tmp_base)
    orch.context_pool._summarizer = None  # 等价于 SummarizingCompressor 初始化失败
    msgs = [{"role": "user", "content": f"轮{i} " + "很长" * 200} for i in range(10)]
    window = asyncio.run(orch._apply_window_budget(msgs, 300))
    cache_key, cache = _fold_cache(orch)
    emit(
        "P10",
        f"窗口首条={window[0]['content'][:46]!r} 缓存键={cache_key!r} cache.summary={cache.get('summary')!r} "
        f"cache.covered_size={len(cache.get('covered') or ())} last_count={cache.get('last_count')}",
    )


def p11(tmp_base: Path):
    """压缩触发判据的度量单位：BALANCED vs 真 tokenizer 在高 Latin/代码内容上的偏差。"""
    import asyncio

    from neurova.context.token_estimator import estimate_tokens
    from neurova.context.window_compactor import estimate_window_tokens

    prose = (
        "The retrieval pool keeps every archived chunk forever, so the drawer has to "
        "select the most relevant entries under the remaining token budget each turn. "
    )
    code = (
        '{"chunks":[{"hash":"a91f2c","source":"conversation","tokens":128,'
        '"metadata":{"role":"assistant","turn_id":"turn_7"}}],'
        '"stats":{"resident":4210,"evicted":0,"budget":24575}} '
    )
    blob = "x" * 9000
    msgs = [
        {"role": "user", "content": prose * 12},
        {"role": "assistant", "content": code * 12},
        {"role": "user", "content": blob},
    ]
    est = estimate_window_tokens(msgs)
    try:
        import tiktoken

        enc = tiktoken.get_encoding("o200k_base")
        real = sum(len(enc.encode(m["content"])) + 4 for m in msgs)
        tk = f"真o200k={real} 低估倍数={real / max(1, est):.1f}x"
    except Exception as e:  # noqa: BLE001
        tk = f"tiktoken不可用({type(e).__name__})"
    orch = _make_orchestrator(tmp_base)
    budget = orch._compute_window_budget(["系统提示" * 100], [], "")
    folded = asyncio.run(orch._apply_window_budget(msgs, budget))
    emit(
        "P11",
        f"BALANCED窗口估算={est} {tk} || 预算={budget} 判据=估算{est}<=预算{budget} "
        f"→ 折叠消息数={len(msgs) - len(folded)} 视图仍含 9000 字符块={any('xxxxx' in m['content'] for m in folded)}",
    )
    emit("P11-单点", f"9000字符无空格块 estimate_tokens={estimate_tokens(blob)}；"
                     f"同长度带空格文本 estimate_tokens={estimate_tokens('word ' * 1800)}")


def p12(tmp_base: Path):
    """摘要器失败语义：SummarizingCompressor 失败返回 previous_summary，
    折叠层把它当"新摘要成功"，据此推进 last_count 并把新消息标记为已覆盖。"""
    import asyncio

    from neurova.context.summarizing_compressor import SummarizingCompressor

    calls = {"n": 0}

    async def llm(prompt: str) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            return "只覆盖第 1 次折叠内容的摘要"
        raise RuntimeError("provider 500")

    orch = _make_orchestrator(tmp_base)
    orch.context_pool._summarizer = SummarizingCompressor(llm_call=llm, timeout_s=5)

    hist1 = [{"role": "user", "content": f"甲{i} " + "量子" * 60} for i in range(10)]
    hist2 = hist1 + [{"role": "user", "content": f"乙{i} " + "火星" * 60} for i in range(10)]

    async def run():
        await orch._apply_window_budget(hist1, 300)
        key1, cache1 = _fold_cache(orch)
        await orch._apply_window_budget(hist2, 300)
        key2, cache2 = _fold_cache(orch)
        return key1, cache1, key2, cache2

    key1, c1, key2, c2 = asyncio.run(run())
    emit(
        "P12",
        f"llm调用次数={calls['n']}; 摘要文本未变={c1.get('summary') == c2.get('summary')}; "
        f"last_count {c1.get('last_count')}→{c2.get('last_count')}; "
        f"covered {len(c1.get('covered') or ())}→{len(c2.get('covered') or ())}; "
        f"缓存键 {key1!r}→{key2!r}（失败仍推进 last_count 即为谎报覆盖）",
    )


def p13():
    """抽屉截断是否就地改写池内归档原文。"""
    from neurova.context_pool import ContextInput, ContextPool, ContextSource

    pool = ContextPool(user_id="u1", agent_id="a1", session_id=None, max_tokens=500, ttl_seconds=0)
    original = "这段归档原文很长必须被截断才能进入视图" * 60
    pool.add_context(
        ContextInput(source=ContextSource.CONVERSATION, content=original, priority=60)
    )
    pool._drawer.max_tokens = 500  # 生产里 draw 预算地板为 1000，>200 才进截断分支
    drawn = pool.draw(need="归档")
    stored = pool.get_contexts()[0]
    drift = ContextInput.compute_hash(stored.source, stored.content) != stored.hash
    emit(
        "P13",
        f"原文字符={len(original)} 池内现存字符={len(stored.content)} 被截断={stored.content != original} "
        f"hash与内容失配={drift} 视图条数={len(drawn)}",
    )


def p14():
    """调取路径成本随池规模的增长（每轮对全池逐条语义编码，无嵌入缓存）。"""
    import time

    from neurova.context_pool import ContextInput, ContextPool, ContextSource

    pool = ContextPool(user_id="u1", agent_id="a1", session_id=None, ttl_seconds=0)
    for i in range(200):
        pool.add_context(
            ContextInput(
                source=ContextSource.CONVERSATION,
                content=f"第{i}轮：上下文池的召回门槛与预算联动讨论记录{i}",
                priority=60,
            )
        )
    drawer = pool._drawer
    backend = type(drawer.vector_store).__name__ if drawer.vector_store else "关键词降级"
    t0 = time.perf_counter()
    n = len(pool.draw(need="预算联动"))
    elapsed = time.perf_counter() - t0
    emit(
        "P14",
        f"池规模=200 单轮 draw={elapsed * 1000:.1f}ms 命中={n} 向量后端={backend} "
        f"每条目≈{elapsed * 1000 / 200:.2f}ms（10k 条目线性外推≈{elapsed * 1000 / 200 * 10000 / 1000:.1f}s/轮）",
    )


def p16():
    """P16（工单 §12.6 DoD）：任取一档摘要，按其 covers 引用取回原文并逐条 hash 对齐。

    走**生产构造面**：真 `ContextOrchestrator.build_context` → 真折叠 → 真池索引
    → 真 `ContextPool.drilldown`（引用解析 → 索引 → 原文直取 → 作用域闸门）。
    判据取工单 §12.7 第 5 条：对齐率必须 100%；取不回时必须点名原因（不伪装空成功）。
    """
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    from neurova.context.fold_index import parseCoversRef
    from neurova.context.orchestrator import ContextOrchestrator

    agent = MagicMock()
    agent.config = MagicMock()
    agent.config.name = "p16"
    agent.config.constitution = ""
    agent.config.behavior_rules = []
    agent.config.llm_model = "test-model"
    agent.memory_manager = MagicMock()
    agent.context_builder = MagicMock()
    agent.tool_router = None
    agent._skill_registry = None
    agent.soul = "探针"
    agent.personality = ""
    agent.conversation_history = []
    agent.growth_log_manager = MagicMock()
    agent.user_id = "u1"
    agent.agent_id = "a-p16"
    agent.current_session_id = "sess-p16"

    orch = ContextOrchestrator(agent, use_pool=True, auto_tag=False, session_id="sess-p16")
    orch._window_token_budget = 1200
    orch._DELTA_RESUMMARY_MSGS = 0
    calls = {"n": 0}

    async def _summarize(dropped_msgs, previous_summary=""):
        calls["n"] += 1
        return f"第{calls['n']}代摘要：覆盖 {len(dropped_msgs)} 条"

    orch._window_summarizer = _summarize

    async def _build(history):
        with patch.object(orch, "get_tools_description", new_callable=AsyncMock) as m:
            m.return_value = "工具描述"
            return await orch.build_context(
                user_input="继续", session_context=history, relevant_memories=[]
            )

    history = [{"role": "user", "content": f"第{i}轮的长讨论：" + "内容" * 200} for i in range(14)]
    view = asyncio.run(_build(history))
    history = history + [
        {"role": "user", "content": f"第{i}轮的长讨论：" + "内容" * 200} for i in range(14, 30)
    ]
    view = asyncio.run(_build(history))

    line = next(
        (str(m["content"]) for m in view if m.get("role") == "system" and "早期对话摘要" in str(m.get("content", ""))),
        "",
    )
    parsed = parseCoversRef(line)
    pool = orch.context_pool
    layers = pool.summaryLayers()
    span = pool.drilldown(line) if line else {"resolved": False, "reason": "NoSummaryLine"}
    wanted = set()
    if parsed:
        layer = next((l for l in layers if l["fold_seq"] == parsed[0]), None)
        wanted = set((layer or {}).get("covers", {}).get("hashes") or ())
    got = {e["hash"] for e in span.get("entries", [])}
    aligned = bool(wanted) and wanted == got

    bogus = pool.drilldown("covers_ref=fold:99@sess-p16")
    honest = (not bogus.get("resolved")) and bool(bogus.get("reason"))
    pool.close()

    emit(
        "P16",
        f"摘要行带引用={bool(parsed)} 引用={parsed} 索引档数={len(layers)} "
        f"covers 条数={len(wanted)} 取回条数={len(got)} 对齐率="
        f"{(len(wanted & got) / len(wanted) * 100) if wanted else 0:.0f}% 逐条相等={aligned} "
        f"假引用如实报错={honest}",
    )


def p15():
    """P15（工单 §12.6 DoD）：30 轮长轨迹后视图内分辨率档数 ≥3 且预算比≈1:4:16。

    走**生产构造面**：真 `ContextOrchestrator.build_context` → 真折叠 → 真池层索引
    → 真分辨率装配器 → 真 `get_context_health()["fold_resolution"]`。

    测量规程（§12.7）：轨迹 30 轮、每轮 ≥800 token、三形态混合；token 口径同
    `estimate_tokens`（T-01 之后的唯一判据尺）；预算取 128k 档型号的窗口份额
    （8000 ≈ 该档 `_resolve_window_token_budget()` 的一档形态）。

    判据三条（都取**实测**读数，不自己算几何比 —— 自算就是恒真断言）：
    1. 视图内档数 ≥ 3（§12.7 判据 1）；
    2. 相邻档预算比落在 4 ±25%（即 1:4:16 的相邻比，同判据 1）；
    3. **顶概览常驻**：连续 30 轮里凡发生折叠的轮次，视图必含一档触达本会话
       覆盖起点（§12.7 判据 4）。判定与常驻判据同源
       `tests/unit/context/test_fold_top_overview_resident_t11c.py`
       的 `topOverviewReachesSessionStart` —— 两处各写一份判定就是第二份口径。
    """
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    from neurova.context.orchestrator import ContextOrchestrator

    agent = MagicMock()
    agent.config = MagicMock()
    agent.config.name = "p15"
    agent.config.constitution = ""
    agent.config.behavior_rules = []
    agent.config.llm_model = "test-model"
    agent.memory_manager = MagicMock()
    agent.context_builder = MagicMock()
    agent.tool_router = None
    agent._skill_registry = None
    agent.soul = "探针"
    agent.personality = ""
    agent.conversation_history = []
    agent.growth_log_manager = MagicMock()
    agent.user_id = "u1"
    agent.agent_id = "a-p15"

    orch = ContextOrchestrator(agent, use_pool=True, auto_tag=False, session_id="sess-p15")
    orch._window_token_budget = 8000
    orch._DELTA_RESUMMARY_MSGS = 0
    calls = {"n": 0}

    async def _summarize(dropped_msgs, previous_summary=""):
        calls["n"] += 1
        return f"第{calls['n']}代摘要：覆盖 {len(dropped_msgs)} 条。" + "细节" * 120

    orch._window_summarizer = _summarize

    # 三形态混合（中文散文 : 英文散文 : JSON+无空格块 = 4 : 4 : 2），每轮 ≥800 token
    def _round(i: int) -> dict:
        kind = i % 5
        if kind in (0, 1):
            body = "本轮讨论产品演进路线与验收口径。" * 60
        elif kind in (2, 3):
            body = "This round reviews the roadmap and the acceptance criteria. " * 40
        else:
            body = '{"trace":["' + "a" * 1200 + '"],"ok":true}'
        return {"role": "user", "content": f"第{i}轮：{body}"}

    async def _build(history):
        with patch.object(orch, "get_tools_description", new_callable=AsyncMock) as m:
            m.return_value = "工具描述"
            return await orch.build_context(
                user_input="继续", session_context=history, relevant_memories=[]
            )

    from neurova.context.fold_index import parseCoversRef
    from neurova.context.window_compactor import SUMMARY_PREFIX

    def _overviewRows(view):
        return [
            str(m.get("content", ""))
            for m in (view or [])
            if m.get("role") == "system" and SUMMARY_PREFIX in str(m.get("content", ""))
        ]

    def _sessionStart():
        pool = orch.context_pool
        lefts = []
        for layer in pool.summaryLayers():
            if layer.get("session_id") != pool.session_id:
                continue
            span = (layer.get("covers") or {}).get("turn_range") or []
            if span:
                lefts.append(int(span[0]))
        return min(lefts) if lefts else None

    def _reachesStart(rows):
        pool = orch.context_pool
        start = _sessionStart()
        if start is None:
            return False
        bySeq = {
            layer["fold_seq"]: layer
            for layer in pool.summaryLayers()
            if layer.get("session_id") == pool.session_id
        }
        for row in rows:
            parsed = parseCoversRef(row)
            layer = bySeq.get(parsed[0]) if parsed else None
            if layer is None:
                continue
            span = (layer.get("covers") or {}).get("turn_range") or []
            if span and int(span[0]) <= start:
                return True
        return False

    history = [_round(i) for i in range(14)]
    asyncio.run(_build(history))
    foldedTurns = 0
    residentViolations = []
    for rnd in range(29):
        history = history + [_round(100 + rnd)]
        view = asyncio.run(_build(history))
        if not getattr(orch, "_last_folded_hashes", None):
            continue  # 未折叠的轮次没有概览行是正确形状（不凭空造行）
        foldedTurns += 1
        rows = _overviewRows(view)
        if not rows:
            residentViolations.append((rnd + 1, "无任何概览行"))
        elif not _reachesStart(rows):
            residentViolations.append((rnd + 1, "概览不触达会话起点"))

    readout = orch.get_context_health()["fold_resolution"]
    levels = readout["levels"]
    budgets = list(readout["level_budgets"])[:3]
    ratios = [round(near / far, 2) for near, far in zip(budgets, budgets[1:])]
    inTolerance = len(ratios) >= 2 and all(4 * 0.75 <= r <= 4 * 1.25 for r in ratios)
    resident = foldedTurns > 0 and not residentViolations
    ok = levels >= 3 and inTolerance and resident
    poolLayers = len(orch.context_pool.summaryLayers()) if orch.context_pool else 0
    orch.context_pool.close()
    emit(
        "P15",
        f"30 轮后视图档数={levels}（池内索引档数={poolLayers}）"
        f" 前{len(budgets)}档预算={budgets} 相邻比={ratios} 1:4:16 容差内={inTolerance} "
        f"摘要调用={calls['n']} 截断字符={readout['truncated_chars']} | "
        f"判据4 折叠轮={foldedTurns} 未触达起点轮={residentViolations[:3]} 常驻={resident} "
        f"{'PASS' if ok else 'FAIL'}",
    )


def main():
    tmp_base = _tmp_ledger_dir()
    try:
        p1()
        p2(tmp_base)
        p3(tmp_base)
        p4()
        p5(tmp_base)
        p6()
        p7()
        p8()
        p9(tmp_base)
        p10(tmp_base)
        p11(tmp_base)
        p12(tmp_base)
        p13()
        p14()
        p15()
        p16()
    finally:
        shutil.rmtree(tmp_base, ignore_errors=True)
    print("\n===== 汇总 =====")
    for probe, verdict in RESULTS:
        print(f"{probe}: {verdict}")


if __name__ == "__main__":
    main()
