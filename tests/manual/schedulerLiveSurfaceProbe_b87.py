# -*- coding: utf-8 -*-
"""批 87 活体验证：走**真 app + 真端点**验 §6-312 乙案的在役面（不是夹具自造）。

跑法（仓根，PYTHONIOENCODING 必带，见形态集 269）：
    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe tests/manual/schedulerLiveSurfaceProbe_b87.py

为什么还要这一档：常驻判据 `test_schedulerLiveSurfaceIsPinned.py` 的静态格认的是三个文件，
其中端点那两档是**按 AST 读源码**判的——源码里没读 `context` 不等于真端点跑起来后那条路还通。
本探针把四件事在真装配上复证一遍：
① 数据根与 agent 工作区根都落在仓外（`isolatedDataRoot()` 单点，§6-310）；
② 经真端点创建/列出的任务，其字段面与判据钉的那一份一致；
③ 立即运行走真 handler 派发路（未注册/解析不到 agent ⇒ failed 且错误文本出得来）；
④ 调度器 store 落在隔离根内、仓内 `data/` 一字节未动（指纹比对，不是文件清单）。
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402

#: 本档打出 `⇒`／`①` 这类 cp936 编不出的字符：不自己钉 stdout 编码时，`print` 抛的
#: UnicodeEncodeError 会把退出码变成 1，读起来像"有一条腿 FAIL"（常驻判据
#: `test_manualScriptStdoutEncoding` 拦的就是这一形）。
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

WORK_ROOT = isolatedDataRoot(prefix="neurovaSchedulerB87")
#: store 的路径在 `main()` 里注入 env——模块顶层改 `os.environ` 正是
#: `test_manualScriptsEnvMutationRatchet` 拦的形态（顶层那一条 import 即执行，会把变量带进整个跑测进程）。

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))


def digest(root: pathlib.Path) -> str:
    """数据根内容指纹：逐文件 (相对路径, 字节数, md5) 汇总——清单相同但内容变了也要现形。"""
    if not root.exists():
        return "<absent>"
    h = hashlib.md5()
    for p in sorted(root.rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(root)).encode("utf-8"))
            h.update(str(p.stat().st_size).encode("ascii"))
            h.update(hashlib.md5(p.read_bytes()).hexdigest().encode("ascii"))
    return h.hexdigest()


def main() -> int:
    from fastapi.testclient import TestClient

    from neurova.api.app import create_app
    from neurova.api.auth import create_access_token
    from neurova.collaborate.workflow.scheduler import AgentScheduler
    from neurova.collaborate.workflow.models import FlowContext

    store = WORK_ROOT / "scheduler_tasks.json"
    os.environ["NEUROVA_SCHEDULER_STORE"] = str(store)
    AgentScheduler._instance = None
    dataBefore = digest(DATA_DIR)
    app = create_app()
    token = create_access_token({"sub": "b87-user", "user_id": "b87-user", "role": "admin"})
    headers = {"Authorization": f"Bearer {token}"}
    registered = app.openapi()["paths"]
    base = next((p[: -len("/tasks")] for p in registered if p.endswith("/tasks")
                 and "scheduler" in p), "")
    check("① 真 app 里挂着调度端点", bool(base), f"paths={base!r}")
    if not base:
        return finish(dataBefore)

    client = TestClient(app, raise_server_exceptions=False)

    created = client.post(f"{base}/tasks", headers=headers, json={
        "name": "b87-live", "action": "send_message", "cron_expression": "*/5 * * * *",
        "parameters": {"message": "从真端点建的任务"}, "description": "活体", "agent_id": "b87-none"})
    check("② 创建任务 200", created.status_code == 200, created.text[:200])
    if created.status_code != 200:
        return finish(dataBefore)
    body = created.json()
    taskId = body.get("task_id") or ""
    pinned = {"task_id", "name", "description", "scheduled_at", "interval_seconds", "cron_expression",
              "agent_id", "action", "status", "created_at", "updated_at", "last_run_at",
              "next_run_at", "run_count", "max_runs"}
    missing = sorted(pinned - set(body))
    extra = sorted(set(body) - pinned)
    check("③ 端点回包字段面 == 判据钉的那一份", not missing and not extra,
          f"缺={missing} 多={extra}")
    check("④ cron 任务在建单时就被排上程（next_run_at 非空）", body.get("next_run_at") is not None,
          f"next_run_at={body.get('next_run_at')}")

    listed = client.get(f"{base}/tasks", headers=headers)
    check("⑤ 列表端点能看见它", listed.status_code == 200
          and any(t.get("task_id") == taskId for t in listed.json()),
          f"text={listed.text[:160]}")

    ran = client.post(f"{base}/tasks/{taskId}/run", headers=headers)
    after = client.get(f"{base}/tasks/{taskId}", headers=headers)
    payload = after.json() if after.status_code == 200 else {}
    check("⑥ 立即运行走真派发：解析不到 agent 即如实 failed 并带错误文本",
          ran.status_code == 200 and payload.get("status") == "failed",
          f"run={ran.status_code} status={payload.get('status')}")

    store = pathlib.Path(os.environ["NEUROVA_SCHEDULER_STORE"])
    onDisk = json.loads(store.read_text(encoding="utf-8")) if store.exists() else []
    check("⑦ 落盘发生在隔离根内且带满字段", bool(onDisk) and pinned <= set(onDisk[0]),
          f"store keys={sorted(set(onDisk[0]))[:6] if onDisk else '空'}")
    check("⑧ store 不在仓内：路径以隔离根为前缀",
          str(store).startswith(str(WORK_ROOT)), f"store={store}")

    ctx = FlowContext()
    check("⑨ 交付面：无参构造即得一个未被触碰的上下文（与判据同一形状）",
          all(getattr(ctx, k, None) == getattr(FlowContext(), k, None)
              for k in ("template_id", "current_step_id", "error_message"))
          and ctx.completed_steps == [] and ctx.shared_data == {}
          and not any(hasattr(ctx, gone) for gone in ("current_phase", "event_history")),
          f"字段面={sorted(vars(ctx))}")
    AgentScheduler._instance = None
    return finish(dataBefore)


def finish(dataBefore: str) -> int:
    after = digest(DATA_DIR)
    check("⑩ 仓内 data/ 一字节未动（内容指纹比对）", after == dataBefore,
          f"{dataBefore[:10]} → {after[:10]}")
    width = max(len(n) for n, _, _ in RESULTS)
    bad = [n for n, ok, _ in RESULTS if not ok]
    for name, ok, detail in RESULTS:
        print(f"{'PASS' if ok else 'FAIL'}  {name.ljust(width)}  {detail}")
    print(f"\n调度器活体面：{len(RESULTS) - len(bad)}/{len(RESULTS)} PASS，"
          f"隔离根={WORK_ROOT}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
