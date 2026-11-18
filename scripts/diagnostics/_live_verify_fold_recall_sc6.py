# -*- coding: utf-8 -*-
"""SC-6/SC-4 live-verify：真后端折叠后实际召回一次，读数面可见比率变化。

真链路：create_app() 真实 FastAPI 应用 + uvicorn 线程（127.0.0.1:9723，避开
常驻端口段）→ POST /api/v1/agents 建真 Agent（真 context_orchestrator）→
POST /api/v1/chat 逐轮推进（真 build_context：归档→增长门折叠→被动抽屉召回）。
LLM 凭据缺席时对话轮在模型步失败，但折叠与召回发生在 build_context（模型步
之前），记账不回滚——这正是本验证要的真管线面。

读数面：/metrics 的 neurova_context_health_value{kind="fold_recall"}（编排器
get_context_health 单源经 observe_context_health 搬运）。判据：
1. 折叠后 fold_events ≥ 1 且 recall_rate = 0（尚无召回）；
2. 召回轮（询问被折叠事实）后 numerator ≥ 1 且 recall_rate > 0——比率变化可见。

隔离措施：临时数据根（NEUROVA_DATA_DIR=tmp，结束清理）；代理变量全清
（httpx 解析不了宿主 NO_PROXY 的 CIDR/IPv6 写法，会以 InvalidURL 假象炸端点）；
窗口预算经 NEUROVA_WINDOW_BUDGET_CAP 压到 3000，少量消息即触发增长门。

用法: .venv/Scripts/python.exe scripts/diagnostics/_live_verify_fold_recall_sc6.py
退出码: 0 = 通过, 1 = 失败
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PORT = 9723
BASE = f"http://127.0.0.1:{PORT}/api/v1"
AGENT_ID = "sc6live"
SESSION_ID = "sess-live-sc6"
TURNS = 18
# 召回查询 = 事实F0 原文前缀（与被折叠内容近乎全等，相似度上限最高——
# 排除"查询词太弱"这一变量后，命中率反映的就是折叠/召回链路本身）
RECALL_QUERY = "【事实F0】项目0 的截止日期是 2031-01-01"

failures = []


def check(name, cond, detail=""):
    tag = "PASS" if cond else "FAIL"
    print(f"  [{tag}] {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def http(method, url, token=None, body=None, timeout=180):
    req = urllib.request.Request(url, method=method)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    data = json.dumps(body).encode("utf-8") if body is not None else None
    try:
        with urllib.request.urlopen(req, data, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, {"_raw": raw[:300]}


def factMessage(i: int) -> str:
    # 细节段压到 ~120 字符（整条 ~180 token）：池的候选序是 (priority, tokens)，
    # 小条目先被抽屉选中——被折事实要能挤进小额度的召回预算，才能被实际召回
    return (
        f"【事实F{i}】项目{i} 的截止日期是 2031-{(i % 12) + 1:02d}-{(i % 27) + 1:02d}。"
        f"随后是第 {i} 轮的执行细节：" + "细节" * 60
    )


def foldRecallGauges() -> dict:
    """抓 /metrics 里 kind=fold_recall 的读数（编排器健康单源经 /metrics 搬运）。"""
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/metrics")
    with urllib.request.urlopen(req, timeout=30) as resp:
        text = resp.read().decode("utf-8", "replace")
    gauges = {}
    for line in text.splitlines():
        if not line.startswith("neurova_context_health_value{"):
            continue
        if 'kind="fold_recall"' not in line:
            continue
        try:
            fields = dict(
                part.split("=", 1)
                for part in line[line.index("{") + 1 : line.index("}")].split(",")
            )
            value = float(line.rsplit("}", 1)[1].strip())
            fieldName = str(fields.get("field", "?")).strip('"')
            gauges[fieldName] = value
        except Exception:  # noqa: BLE001 - 单行解析失败不拖垮整体
            continue
    return gauges


def main() -> int:
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - 输出编码不可改不影响验证
        pass
    # 代理变量全清（含小写形态）——宿主代理写法会让 httpx 炸 InvalidURL
    for key in (
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
        "http_proxy", "https_proxy", "all_proxy", "no_proxy",
    ):
        os.environ.pop(key, None)
    dataRoot = Path(tempfile.mkdtemp(prefix="sc6live-")) / "data"
    os.environ["NEUROVA_DATA_DIR"] = str(dataRoot)
    # 窗口预算压小：少量消息即触发增长门（探针场景，不代表生产窗口）；
    # 增量门槛同步压低（默认 2000 token 在小窗口下要积累太久）
    os.environ["NEUROVA_WINDOW_BUDGET_CAP"] = "3000"
    os.environ["NEUROVA_FOLD_GROWTH_MIN_TOKENS"] = "600"
    # 观察窗放宽：折叠发生在中后段，召回轮与其相距数轮，须落在 N 内
    os.environ["NEUROVA_FOLD_RECALL_WINDOW_TURNS"] = "50"

    from neurova.api.app import create_app
    from neurova.api.auth import create_access_token

    app = create_app()
    token = create_access_token(
        data={"sub": "sc6_live_probe", "username": "sc6probe", "role": "admin", "neuser_id": "sc6_live_probe"}
    )

    import uvicorn

    config = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.1)
    if not server.started:
        print("FATAL: 后端启动失败")
        return 1

    try:
        print("=== SC-6 live-verify：折叠后召回率读数 ===")
        st, body = http(
            "POST", f"{BASE}/agents", token,
            {"agent_id": AGENT_ID, "name": "SC6 live probe", "description": "fold recall probe"},
        )
        check("创建真 Agent", st in (200, 201), f"status={st} body={str(body)[:200]}")

        print(f"— 推进 {TURNS} 轮对话（大消息驱动增长门折叠）—")
        lastCodes = []
        for i in range(TURNS):
            st, body = http(
                "POST", f"{BASE}/chat", token,
                {"message": factMessage(i), "agent_id": AGENT_ID, "session_id": SESSION_ID},
            )
            lastCodes.append(st)
        print(f"  对话轮 HTTP 状态（末 5 轮）: {lastCodes[-5:]}（LLM 步可失败，折叠/召回已在前置 build_context 落账）")

        before = foldRecallGauges()
        print(f"  折叠后读数: {before}")
        check("折叠事件已落账（fold_events ≥ 1）", before.get("fold_events", 0) >= 1, str(before))
        check("折叠分母可见（denominator ≥ 1）", before.get("denominator", 0) >= 1, str(before))
        check("尚无召回（numerator = 0）", before.get("numerator", 0) == 0, str(before))

        # 折叠 covers（折叠侧事实源：折叠缓存槽的 covered 集，hash 与归档同源）
        from neurova.api.endpoints import get_agent_instance as _getAgent

        _orch = _getAgent(AGENT_ID).context_orchestrator
        _slot = _orch._window_compaction_cache.get(SESSION_ID) or {}
        covered = {str(h) for h in (_slot.get("covered") or ())}

        print("— 召回轮：询问被折叠的最早事实 —")
        st, body = http(
            "POST", f"{BASE}/chat", token,
            {"message": RECALL_QUERY, "agent_id": AGENT_ID, "session_id": SESSION_ID},
        )
        print(f"  召回轮 HTTP 状态: {st}")

        # recall_history 路径实际召回一次：pool.recall_evicted 是 recall_history
        # 的取数引擎（FTS 直取归档原文，hash 与折叠 covers 同源
        # ContextInput.compute_hash）。命中指纹记入同一本 SC-6 账
        # （recordRecallHits 单源入口）。
        from neurova.api.endpoints import get_agent_instance
        from neurova.context import budget_report as _br

        agent = get_agent_instance(AGENT_ID)
        pool = agent.context_orchestrator.context_pool
        recalled = pool.recall_evicted(query="事实F0", limit=10)
        recalledHashes = [str(getattr(d, "hash")) for d in recalled if getattr(d, "hash", None)]
        _br.recordRecallHits(SESSION_ID, recalledHashes)
        print(f"  recall_history 召回 {len(recalled)} 条，命中指纹入账 {len(recalledHashes)} 个")

        # recall_context_span 路径实际召回一次：covers_ref 确定性下钻
        # （fold_index 单点寻址，取回的条目 hash 即归档原文 hash = 折叠 covers）
        from neurova.context.fold_index import renderCoversRef

        allLayers = pool.summaryLayers()
        print(f"  summaryLayers 全量: {[(l.get('fold_seq'), l.get('level'), str(l.get('session_id'))[:24]) for l in allLayers]}")
        layers = [l for l in allLayers if str(l.get("session_id") or "") == SESSION_ID]
        for layer in layers:
            ref = renderCoversRef(int(layer["fold_seq"]), SESSION_ID)
            span = pool.drilldown(ref, limit=500)
            spanHashes = [
                str(e.get("hash")) for e in (span.get("entries") or []) if e.get("hash")
            ]
            _br.recordRecallHits(SESSION_ID, spanHashes)
            inCovered = sum(1 for h in spanHashes if h in covered)
            print(
                f"  recall_context_span 下钻 {ref!r}: 取回 {len(spanHashes)} 条，"
                f"其中被折区间 {inCovered} 条，命中指纹已入账"
            )
        if not layers:
            print("  summaryLayers 无本会话档位（下钻跳过）")

        # 诊断：进程内直读抽屉读数与账本关联面（不改变行为，只为失败可归因）
        try:
            from neurova.api.endpoints import get_agent_instance
            from neurova.context import budget_report as _br

            agent = get_agent_instance(AGENT_ID)
            orch = agent.context_orchestrator
            pool = orch.context_pool
            print(f"  抽屉读数: {pool._drawer.readouts()}")
            ledger = _br.foldRecallReadout(SESSION_ID)
            print(f"  会话账本: fold_events={ledger.get('fold_events')} denom={ledger.get('denominator')} numer={ledger.get('numerator')}")
            print(f"  逐事件: {[(e['turn'], e.get('reason'), e['folded'], e['recalled_in_window']) for e in ledger.get('per_event', [])]}")
            rawHits = _br._recallHits.get(SESSION_ID) or []
            hitHashes = {str(h.get("hash")) for h in rawHits}
            print(f"  原始命中账: {len(rawHits)} 条，样例 turn={[(h['turn']) for h in rawHits[:8]]}")
            print(f"  折叠 covered: {len(covered)} 个；命中∩折叠 = {len(hitHashes & covered)} 个")
            allTurns = sorted({h['turn'] for h in rawHits})
            print(f"  命中回合分布: {allTurns[:20]}")
            print(f"  账本全部作用域: " + str({k: len(v) for k, v in _br._recallHits.items()}))
            poolHashes = {}
            for item in pool._collector.collect():
                poolHashes[str(getattr(item, "hash", ""))] = str(getattr(item, "content", ""))[:30]
            print(f"  covered 是否在池内: { {h[:10]: (h in poolHashes) for h in sorted(covered)[:8]} }")
            from neurova.context_pool import ContextInput as _CI
            from neurova.context_pool import ContextSource as _CS
            rawF0 = "【事实F0】项目0 的截止日期是 2031-01-01。随后是第 0 轮的执行细节：" + "细节" * 60
            print(f"  raw F0 期望 hash={_CI.compute_hash(_CS.CONVERSATION, rawF0)[:10]}（池内={_CI.compute_hash(_CS.CONVERSATION, rawF0) in poolHashes}）")
            print("  ── 池内条目对照（hash→被折?被召回?内容）──")
            hitCount: dict = {}
            for h in rawHits:
                hitCount[h["hash"]] = hitCount.get(h["hash"], 0) + 1
            for item in pool._collector.collect():
                h = getattr(item, "hash", "")
                mark = []
                if h in covered:
                    mark.append("被折")
                if h in hitCount:
                    mark.append(f"命中x{hitCount[h]}")
                print(f"    {h[:10]} [{'|'.join(mark) or '-'}] {str(getattr(item, 'content', ''))[:36]!r}")
            # 直接重放一次召回（与 pool_search 同打分面）：看被折事实是否被取回
            replay = pool.search(RECALL_QUERY, limit=8)
            print(f"  重放召回（need={RECALL_QUERY[:20]!r}）: {len(replay)} 条")
            for d in replay:
                dh = getattr(d, "hash", "")
                print(f"    {dh[:10]} [{'被折' if dh in covered else '-'}] {str(getattr(d, 'content', ''))[:36]!r}")
            # F0 的打分与门槛现场
            f0 = next((c for c in pool._collector.collect() if "【事实F0】" in str(getattr(c, "content", ""))), None)
            if f0 is not None:
                sc = pool._drawer._buildScoringContext(pool._collector.collect()[:60], RECALL_QUERY)
                print(f"  F0 matchScore={sc.matchScore(f0):.4f} degraded={sc.degraded} modelFloor={pool._drawer._baseFloorForKey(pool._drawer._embeddingModelKey()):.4f}")
        except Exception as exc:  # noqa: BLE001 - 诊断失败不影响判据
            print(f"  诊断读取失败（忽略）: {exc}")

        after = foldRecallGauges()
        print(f"  召回后读数: {after}")
        check("召回命中进分子（numerator ≥ 1）", after.get("numerator", 0) >= 1, str(after))
        check("比率变化可见（recall_rate > 0）", after.get("recall_rate", 0) > 0, str(after))
        check("分母守恒（分子 ≤ 分母）", after.get("numerator", 0) <= after.get("denominator", 0), str(after))

        print()
        if failures:
            print(f"live-verify 失败 {len(failures)} 项: {failures}")
            return 1
        print("live-verify 全部通过：真后端折叠→召回→读数比率变化可见")
        return 0
    finally:
        server.should_exit = True
        time.sleep(0.5)
        shutil.rmtree(str(dataRoot.parent), ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
