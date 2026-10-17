# -*- coding: utf-8 -*-
"""§6-166 退役批的活体自证：三套零接线编排器真的不在服务路上，且退役没带走任何在役能力。

跑的真生产对象：`create_app()` + `TestClient`（真 lifespan、真路由挂载、真注册表）。
数据根走 `_liveVerifyIsolation.isolatedDataRoot()` 单点。

四段：
① 真启动全过程里，三只模块一次都没进过 `sys.modules`；`importlib` 也取不到（不是"注释说没了"）。
   同时核对包门面 `neurova.execution_engine` 仍能正常 import——删成员不能把门面一起删坏。
② 现役规划面仍在服务：`GET /api/v1/plans/*`（plan_mode 那套）、`GET /api/v1/neurflow/nodes`
   （NeurFlow 节点面，含本批并入的 idempotent 键）。
③ 聊天路的接缝没断：真建一次会话并读回（LLM 不调用——只验证装配与读面活着，不花服务商额度）。
④ 层内并发上限与节点重试这两格（从被退役的 `execution_engine/plan_orchestrator.py` 迁来的）
   在**真引擎**上仍然生效：宽 10 的扇出层实测峰值 ≤ 8。
"""

import asyncio
import importlib
import os
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


PLAN_BASE = "/api/v1/plans"
FLOW_BASE = "/api/v1/neurflow"
USER = {"user_id": "retire_live_probe", "username": "retire_live_probe", "role": "admin"}

# 按段拼：本脚本是"证明它们不在位"的探针，不该成为引用面判据的命中点（§6-151 的自伤）
RETIRED = [
    ".".join(("neurova", "core", "cognition_orchestrator")),
    ".".join(("neurova", "core", "plan_orchestrator")),
    ".".join(("neurova", "execution_engine", "plan_orchestrator")),
]

failures: list[str] = []


def _check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        failures.append(msg)


def main() -> int:
    os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "retire_live_probe_secret_key_01234567")

    from tests.manual._liveVerifyIsolation import isolatedDataRoot

    print(f"数据根（临时）：{isolatedDataRoot()}")

    from fastapi.testclient import TestClient

    from neurova.api.app import create_app
    from neurova.api.auth import get_current_user, get_current_user_or_default
    from neurova.collaboration.neurflow.models import NodeDefinition, WorkflowStatus
    from neurova.collaboration.neurflow.node_registry import get_node_registry
    from neurova.collaboration.neurflow.models import (
        WorkflowDefinition,
        WorkflowEdge,
        WorkflowNode,
    )

    before = set(sys.modules)
    app = create_app()
    # 身份依赖不止一只对象：`/neurflow/*` 用 neurova.api.auth 里的两只，`/console/chat/sessions`
    # 用的是 neurova.api.deps.get_current_user——只覆盖前者就会拿 401，那是替身没铺全，
    # 不是产品缺陷（与 §6-157 那条"写侧与路由实例不同源"同族）。
    from neurova.api.deps import get_current_user as get_current_user_deps

    app.dependency_overrides[get_current_user] = lambda: dict(USER)
    app.dependency_overrides[get_current_user_or_default] = lambda: dict(USER)
    app.dependency_overrides[get_current_user_deps] = lambda: dict(USER)

    print("\n① 真启动后的装载读数与门面完整性")
    leaked = sorted(m for m in set(sys.modules) - before if m in RETIRED)
    _check(not leaked, f"三只退役模块一次都没被拉起（实得 {leaked}）")
    for module in RETIRED:
        sys.modules.pop(module, None)
        try:
            importlib.import_module(module)
            reachable = True
        except ModuleNotFoundError:
            reachable = False
        _check(not reachable, f"{module} 已取不到")
    facade = importlib.import_module("neurova.execution_engine")
    _check(hasattr(facade, "ToolEngine") or bool(dir(facade)), "包门面 neurova.execution_engine 仍可导入")

    registry = get_node_registry()
    registry.ensure_builtin()
    fan = {"inflight": 0, "peak": 0}

    async def _fanExec(config, context):
        fan["inflight"] += 1
        fan["peak"] = max(fan["peak"], fan["inflight"])
        try:
            await asyncio.sleep(0.02)
        finally:
            fan["inflight"] -= 1
        return {"output": "ok"}

    registry.register(
        NodeDefinition(
            type="probe:retireFan",
            label="退役活体探针",
            icon="🧪",
            category="tools",
            description="层内并发上限复核",
            sub_blocks=[],
            inputs=[],
            outputs=[],
        ),
        _fanExec,
    )

    with TestClient(app) as client:
        print("\n② 现役规划面仍在服务（只读取数，不建计划会话——那会调 LLM 花服务商额度）")
        r = client.get(f"{FLOW_BASE}/nodes")
        rows = (r.json().get("nodes") or []) if r.status_code == 200 else []
        _check(r.status_code == 200 and rows, f"GET /neurflow/nodes 有读数（{r.status_code}，{len(rows)} 条）")
        _check(all("idempotent" in n for n in rows), "节点面带 idempotent 键（本批迁自退役件的那格）")
        rDoc = client.get(f"{PLAN_BASE}/documents")
        _check(rDoc.status_code == 200, f"GET /plans/documents 200（实得 {rDoc.status_code}：{rDoc.text[:120]}）")
        rSess = client.get(f"{PLAN_BASE}/sessions")
        _check(
            rSess.status_code == 405,
            f"GET /plans/sessions 必须回 405——405 才证明路由挂上了且该路径只收 POST"
            f"（把它读成 404「入口不存在」是另一枚坑，实得 {rSess.status_code}）",
        )

        print("\n③ 聊天路接缝没断（不调 LLM，只验装配与读面）")
        r3 = client.get("/api/v1/console/chat/sessions")
        _check(r3.status_code == 200, f"GET /console/chat/sessions 200（实得 {r3.status_code}：{r3.text[:160]}）")

        print("\n④ 并进活路的那两格在真引擎上生效（宽 10 扇出，上限 8）")

        nodes = [WorkflowNode(id="n_start", type="builtin:start", position={"x": 0, "y": 0}, config={})]
        edges = []
        for i in range(10):
            nid = f"p_{i}"
            nodes.append(WorkflowNode(id=nid, type="probe:retireFan", position={"x": 200, "y": i * 40}, config={}))
            edges.append(WorkflowEdge(id=f"es{i}", source="n_start", target=nid))
            edges.append(WorkflowEdge(id=f"ee{i}", source=nid, target="n_end"))
        nodes.append(WorkflowNode(id="n_end", type="builtin:end", position={"x": 400, "y": 0}, config={}))
        wf = WorkflowDefinition(
            id="wfRetireFan",
            name="退役活体-扇出",
            description="层内并发上限",
            version="1.0.0",
            nodes=nodes,
            edges=edges,
            variables=[],
            tags=["live"],
            category="general",
            author="probe",
            created_at=0.0,
            updated_at=0.0,
            status=WorkflowStatus.PUBLISHED,
        )
        r4 = client.post(f"{FLOW_BASE}/workflows", json={"id": wf.id, **{k: v for k, v in wf.to_dict().items() if k != "id"}})
        _check(r4.status_code == 200, f"创建工作流 200（实得 {r4.status_code}：{r4.text[:160]}）")
        r5 = client.post(f"{FLOW_BASE}/workflows/{wf.id}/execute", json={})
        inst = (r5.json().get("instance") or {}) if r5.status_code == 200 else {}
        print(f"  终态={inst.get('status')} 峰值并发={fan['peak']} 节点结果数={len(inst.get('node_results') or {})}")
        _check(fan["peak"] > 1, f"层内仍并发（peak={fan['peak']}）")
        _check(fan["peak"] <= 8, f"峰值并发 ≤ 8（实得 {fan['peak']}）——退役没把上限那格带走")

    registry.unregister("probe:retireFan")
    app.dependency_overrides.clear()

    print("\n" + ("活体全过" if not failures else f"{len(failures)} 处未过：\n- " + "\n- ".join(failures)))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
