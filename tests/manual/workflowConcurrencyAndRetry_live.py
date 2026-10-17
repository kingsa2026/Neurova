# -*- coding: utf-8 -*-
"""§6-157 活体自证：层内并发上限与节点级重试经真 HTTP 端点跑通。

跑的真生产对象：`create_app()` + `TestClient`（真 lifespan）、真 `/api/v1/neurflow/*` 端点、
真节点注册表与真事件流。数据根走 `_liveVerifyIsolation.isolatedDataRoot()` 单点。

四段，逐段对应判据里的一格，但取数方式不同——判据在进程内直接调引擎，这里必须经 HTTP：
① 宽 12 的扇出层：峰值并发 ≤ 上限，且 > 1（限流没把并发压成串行）。
② 声明幂等的节点：前两次抛错第三次成功 ⇒ 经端点回 completed、调用 3 次、事件流里
   node_retry 恰 2 条、node_failed 0 条（这条是"画布不闪红"的实证）。
③ 未声明幂等的节点：抛一次即 failed、调用 1 次（默认拒绝侧）。
④ `GET /nodes` 把 idempotent 带得出来（声明面有读者，不是只写不读的新字段）。
"""

import asyncio
import json
import os
import sys
import time
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


BASE = "/api/v1/neurflow"
USER = {"user_id": "cap_live_probe", "username": "cap_live_probe", "role": "admin"}
PEAK_ENV = "NEUROVA_NEURFLOW_MAX_CONCURRENT_NODES"

failures: list[str] = []


def _check(cond: bool, msg: str) -> None:
    print(("  ✔ " if cond else "  ✘ ") + msg)
    if not cond:
        failures.append(msg)


def _workflowPayload(wf_id: str, node_types: list[str], width: int = 0) -> dict:
    """node_types 里每个类型各铺 width 个同层节点（同层＝互不依赖＝可并发）。"""
    nodes = [{"id": "n_start", "type": "builtin:start", "position": {"x": 0, "y": 0}, "config": {}}]
    edges = []
    i = 0
    for node_type in node_types:
        for _ in range(width):
            i += 1
            nid = f"p_{i}"
            nodes.append({"id": nid, "type": node_type, "position": {"x": 200, "y": i * 40}, "config": {}})
            edges.append({"id": f"es{nid}", "source": "n_start", "target": nid})
            edges.append({"id": f"ee{nid}", "source": nid, "target": "n_end"})
    nodes.append({"id": "n_end", "type": "builtin:end", "position": {"x": 400, "y": 0}, "config": {}})
    return {
        "id": wf_id,
        "name": f"活体-{wf_id}",
        "description": "并发上限与节点重试",
        "version": "1.0.0",
        "nodes": nodes,
        "edges": edges,
        "variables": [],
        "tags": ["live"],
        "category": "general",
        "author": "probe",
        "status": "published",
    }


def main() -> int:
    os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "cap_live_probe_secret_key_0123456789")

    from tests.manual._liveVerifyIsolation import isolatedDataRoot

    root = isolatedDataRoot()
    cap = int(os.environ.get(PEAK_ENV) or "8")
    print(f"数据根（临时）：{root}  期望上限={cap}")

    from fastapi.testclient import TestClient

    from neurova.api.app import create_app
    from neurova.api.auth import get_current_user, get_current_user_or_default
    from neurova.collaboration.neurflow.execution_engine import get_workflow_executor
    from neurova.collaboration.neurflow.models import NodeDefinition
    from neurova.collaboration.neurflow.node_registry import get_node_registry

    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: dict(USER)
    app.dependency_overrides[get_current_user_or_default] = lambda: dict(USER)

    registry = get_node_registry()
    registry.ensure_builtin()

    fan = {"inflight": 0, "peak": 0}
    flaky = {"n": 0}
    deny = {"n": 0}

    async def _fanExecutor(config, context):
        fan["inflight"] += 1
        fan["peak"] = max(fan["peak"], fan["inflight"])
        try:
            await asyncio.sleep(0.02)
        finally:
            fan["inflight"] -= 1
        return {"output": "ok"}

    async def _flakyExecutor(config, context):
        flaky["n"] += 1
        if flaky["n"] < 3:
            raise RuntimeError(f"瞬时故障 #{flaky['n']}")
        return {"output": "recovered"}

    async def _denyExecutor(config, context):
        deny["n"] += 1
        raise RuntimeError("这一步有副作用")

    def register(node_type: str, executor, *, idempotent: bool = False) -> None:
        definition = NodeDefinition(
            type=node_type,
            label="活体探针",
            icon="🧪",
            category="tools",
            description="并发/重试活体",
            sub_blocks=[],
            inputs=[],
            outputs=[],
        )
        if idempotent:
            definition.idempotent = True
        registry.register(definition, executor)

    register("probe:liveFan", _fanExecutor)
    register("probe:liveFlaky", _flakyExecutor, idempotent=True)
    register("probe:liveDeny", _denyExecutor)

    events: list = []
    executor = get_workflow_executor()
    executor.on_event(lambda e: events.append(e))

    try:
        with TestClient(app) as client:
            print("\n① 宽 12 扇出层：并发受限但没被串行化")
            r = client.post(f"{BASE}/workflows", json=_workflowPayload("wfLiveFan", ["probe:liveFan"], 12))
            _check(r.status_code == 200, f"创建工作流 200（实得 {r.status_code}：{r.text[:150]}）")
            r = client.post(f"{BASE}/workflows/wfLiveFan/execute", json={})
            inst = (r.json().get("instance") or {}) if r.status_code == 200 else {}
            print(f"  终态={inst.get('status')} 峰值并发={fan['peak']} 节点数={len(inst.get('node_results') or {})}")
            _check(r.status_code == 200, f"执行端点 200（实得 {r.status_code}：{r.text[:200]}）")
            _check(fan["peak"] > 1, f"层内仍在并发（peak={fan['peak']}）——上限不该把并发压成 1")
            _check(fan["peak"] <= cap, f"峰值并发 ≤ {cap}（实得 {fan['peak']}）")

            print("\n② 声明幂等：两次瞬时故障后自愈，事件流不得出现 node_failed")
            events.clear()
            r = client.post(f"{BASE}/workflows", json=_workflowPayload("wfLiveFlaky", ["probe:liveFlaky"], 1))
            _check(r.status_code == 200, f"创建幂等探针流 200（实得 {r.status_code}）")
            r = client.post(f"{BASE}/workflows/wfLiveFlaky/execute", json={})
            inst2 = (r.json().get("instance") or {}) if r.status_code == 200 else {}
            types = [str(getattr(e.type, "value", e.type)) for e in events]
            probe_res = (inst2.get("node_results") or {}).get("p_1") or {}
            print(f"  终态={inst2.get('status')} 调用次数={flaky['n']} 事件序列={types}")
            _check(flaky["n"] == 3, f"重试到第 3 次才成功（实得调用 {flaky['n']} 次）")
            _check(inst2.get("status") == "completed", f"整条流终态 completed（实得 {inst2.get('status')}）")
            _check(probe_res.get("status") == "success", f"探针节点终态 success（实得 {probe_res.get('status')}）")
            _check(types.count("node_retry") == 2, f"node_retry 恰 2 条（实得 {types.count('node_retry')}）")
            _check(types.count("node_failed") == 0, f"被重试吸收的失败不发 node_failed（实得 {types.count('node_failed')} 条）")

            print("\n③ 默认拒绝：未声明幂等的节点抛一次即失败")
            events.clear()
            r = client.post(f"{BASE}/workflows", json=_workflowPayload("wfLiveDeny", ["probe:liveDeny"], 1))
            _check(r.status_code == 200, f"创建副作用探针流 200（实得 {r.status_code}）")
            r = client.post(f"{BASE}/workflows/wfLiveDeny/execute", json={})
            inst3 = (r.json().get("instance") or {}) if r.status_code == 200 else {}
            types3 = [str(getattr(e.type, "value", e.type)) for e in events]
            print(f"  终态={inst3.get('status')} 调用次数={deny['n']} 事件序列={types3}")
            _check(deny["n"] == 1, f"未声明幂等不得重试（实得调用 {deny['n']} 次）")
            _check(inst3.get("status") == "failed", f"副作用节点失败必须让整条流 failed（实得 {inst3.get('status')}）")
            _check("node_retry" not in types3, "默认拒绝侧不得发 node_retry")

            print("\n④ 声明面的读者：GET /nodes 带得出 idempotent")
            r = client.get(f"{BASE}/nodes", params={"source": "builtin"})
            rows = (r.json().get("nodes") or []) if r.status_code == 200 else []
            mine = next((n for n in rows if n.get("type") == "probe:liveFlaky"), None)
            print(f"  GET /nodes 条数={len(rows)} 探针条目={json.dumps(mine, ensure_ascii=False)[:120] if mine else None}")
            _check(mine is not None and mine.get("idempotent") is True,
                   f"节点列表须暴露 idempotent（实得 {mine}）")
            _check(all("idempotent" in n for n in rows), "其余节点也要带这个键（缺了就等于前端无法判）")
    finally:
        for node_type in ("probe:liveFan", "probe:liveFlaky", "probe:liveDeny"):
            registry.unregister(node_type)
        app.dependency_overrides.clear()

    print("\n" + ("活体全过" if not failures else f"{len(failures)} 处未过：\n- " + "\n- ".join(failures)))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
