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
    finally:
        shutil.rmtree(tmp_base, ignore_errors=True)
    print("\n===== 汇总 =====")
    for probe, verdict in RESULTS:
        print(f"{probe}: {verdict}")


if __name__ == "__main__":
    main()
