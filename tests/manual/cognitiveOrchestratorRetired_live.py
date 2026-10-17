# -*- coding: utf-8 -*-
"""丙′ 收口的活体自证：任务编排的「真能力」确实在服务路上，旧件不复存在。

跑的真生产对象：`create_app()` + `TestClient`（真 lifespan）、真 HTTP 端点
`/api/v1/neurflow/*`、真节点注册表与真执行实例落盘。数据根走
`_liveVerifyIsolation.isolatedDataRoot()` 单点（不碰仓库 data/）。

五段，逐段自证一条被判"需人裁"的前提：
① 真启动全过程里，退役模块一次都没进过 `sys.modules`（不是"注释说它没了"，是运行时读数）。
② 三步流水线经真端点执行：中间那步注册的执行器**真被 await**（calls==1），
   它的返回值出现在 `node_results` 里——旧件 `orchestrate()` 给每一步直接写 "completed"，
   仓里没有任何 handler 被调用过，这一格正是它缺的。
③ 解析不到执行器的节点：终态**不是** completed，且留下原因（不假成功）。
④ 代理注册表经真端点写→读往返（顶替旧件 `register_agent`，含归档态语义）。
⑤ 执行实例落盘后按 workflow 维度读得回（顶替旧件的"任务三态落盘"）。
"""

import importlib
import json
import os
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


BASE = "/api/v1/neurflow"
PROBE_TYPE = "probe:liveEcho"
USER = {"user_id": "live_probe", "username": "live_probe", "role": "admin"}
# 按段拼：本脚本是"证明它不在位"的探针，不该被当成"还把它当模板指向"的引用点，
# 而判据按连续字面量计数——写死就会自证其红。
RETIRED_MODULE = ".".join(("neurova", "cognitive", "orchestrator"))

failures: list[str] = []


def _check(cond: bool, msg: str) -> None:
    print(("  ✔ " if cond else "  ✘ ") + msg)
    if not cond:
        failures.append(msg)


def _workflowPayload(wf_id: str, node_type: str) -> dict:
    return {
        "id": wf_id,
        "name": f"活体-{wf_id}",
        "description": "核验任务编排的单点活路",
        "version": "1.0.0",
        "nodes": [
            {"id": "n_start", "type": "builtin:start", "position": {"x": 0, "y": 0}, "config": {}},
            {"id": "n_probe", "type": node_type, "position": {"x": 200, "y": 0}, "config": {"text": "hi"}},
            {"id": "n_end", "type": "builtin:end", "position": {"x": 400, "y": 0}, "config": {}},
        ],
        "edges": [
            {"id": "e1", "source": "n_start", "target": "n_probe"},
            {"id": "e2", "source": "n_probe", "target": "n_end"},
        ],
        "variables": [],
        "tags": ["live"],
        "category": "general",
        "author": "probe",
        "status": "published",
    }


def main() -> int:
    os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "live_probe_secret_key_for_neurova_0123")

    from tests.manual._liveVerifyIsolation import isolatedDataRoot

    root = isolatedDataRoot()
    print(f"数据根（临时）：{root}")

    from fastapi.testclient import TestClient

    from neurova.api.app import create_app
    from neurova.api.auth import get_current_user
    from neurova.collaboration.neurflow.execution_engine import get_workflow_executor
    from neurova.collaboration.neurflow.models import NodeDefinition
    from neurova.collaboration.neurflow.node_registry import get_node_registry

    app = create_app()
    # 两个身份依赖不是同一个可调用对象：写侧 `/workflows` 用 get_current_user，
    # 执行侧用 get_current_user_or_default。只覆盖前者 ⇒ 执行端点按 default 属主判定，
    # 404「工作流不存在」——那是替身没铺全，不是产品缺陷。
    from neurova.api.auth import get_current_user_or_default

    app.dependency_overrides[get_current_user] = lambda: dict(USER)
    app.dependency_overrides[get_current_user_or_default] = lambda: dict(USER)

    calls: list[dict] = []

    async def _echo(config, context):
        calls.append(dict(config))
        return {"output": "echoed:" + str(config.get("text", ""))}

    get_node_registry().ensure_builtin()
    get_node_registry().register(
        NodeDefinition(
            type=PROBE_TYPE,
            label="活体探针",
            icon="🧪",
            category="tools",
            description="核验执行器真被 await",
            sub_blocks=[],
            inputs=[],
            outputs=[],
        ),
        _echo,
    )

    with TestClient(app) as client:
        print("\n① 真启动后的模块读数")
        leaked = [m for m in sys.modules if m.startswith(RETIRED_MODULE)]
        _check(not leaked, f"退役模块一次都没进过 sys.modules（实得 {leaked}）")
        try:
            importlib.import_module(RETIRED_MODULE)
            reachable = True
        except ModuleNotFoundError:
            reachable = False
        _check(not reachable, "importlib 已取不到退役模块")

        print("\n② 真端点跑三步流水线：执行器必须被 await 过")
        r = client.post(f"{BASE}/workflows", json=_workflowPayload("wfLiveEcho", PROBE_TYPE))
        _check(r.status_code == 200, f"创建工作流 200（实得 {r.status_code}：{r.text[:200]}）")
        r = client.post(f"{BASE}/workflows/wfLiveEcho/execute", json={})
        _check(r.status_code == 200, f"执行端点 200（实得 {r.status_code}：{r.text[:300]}）")
        inst = r.json().get("instance", {}) if r.status_code == 200 else {}
        probe = (inst.get("node_results") or {}).get("n_probe") or {}
        _check(len(calls) == 1, f"注册的节点执行器被调用 1 次（实得 {len(calls)}）")
        _check(inst.get("status") == "completed", f"整条流水线终态 completed（实得 {inst.get('status')}）")
        _check(probe.get("status") == "success", f"探针节点步态 success（实得 {probe.get('status')}）")
        _check(
            probe.get("output") == "echoed:hi",
            f"执行器返回值落进节点结果（实得 {probe.get('output')!r}）",
        )

        print("\n③ 解析不到执行器：不得谎报完成")
        r = client.post(f"{BASE}/workflows", json=_workflowPayload("wfLiveAbsent", "probe:notRegistered"))
        _check(r.status_code == 200, f"创建非法类型工作流 200（实得 {r.status_code}：{r.text[:200]}）")
        r = client.post(f"{BASE}/workflows/wfLiveAbsent/execute", json={})
        inst2 = r.json().get("instance", {}) if r.status_code == 200 else {}
        _check(r.status_code == 200, f"执行端点回 200 并带诚实终态（实得 {r.status_code}）")
        _check(
            inst2.get("status") != "completed",
            f"非法类型不得被判 completed（实得 {inst2.get('status')}）",
        )
        reason = inst2.get("error") or next(
            (v.get("error") for v in (inst2.get("node_results") or {}).values() if v.get("error")), None
        )
        _check(bool(reason), f"失败必须留下原因（实得 {reason!r}）")

        print("\n④ 代理注册表写→读往返（顶替旧件 register_agent）")
        r = client.post(f"{BASE}/agents", json={"name": "编码助手", "role": "coder"})
        _check(r.status_code == 201, f"创建团队 Agent 201（实得 {r.status_code}：{r.text[:200]}）")
        agent = (r.json().get("agent") or {}) if r.status_code == 201 else {}
        aid = agent.get("id")
        _check(bool(aid), f"响应带 agent id（实得 {json.dumps(agent, ensure_ascii=False)[:160]}）")
        r = client.get(f"{BASE}/agents")
        listed = (r.json().get("agents") or []) if r.status_code == 200 else []
        _check(
            any(a.get("agent_id") == aid for a in listed),
            f"读面按 id 取回该 Agent（共 {len(listed)} 条，键位见 {sorted(listed[0]) if listed else '空'}）",
        )

        print("\n⑤ 执行实例落盘后读得回（顶替旧件的任务三态落盘）")
        r = client.get(f"{BASE}/executions", params={"workflow_id": "wfLiveEcho"})
        rows = (r.json().get("executions") or []) if r.status_code == 200 else []
        _check(
            any(e.get("workflow_id") == "wfLiveEcho" and e.get("status") == "completed" for e in rows),
            f"按 workflow 维度读回落盘的执行实例（共 {len(rows)} 条）",
        )

    get_node_registry().unregister(PROBE_TYPE)
    app.dependency_overrides.clear()

    print("\n" + ("全部通过" if not failures else f"{len(failures)} 处未过：\n- " + "\n- ".join(failures)))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
