# -*- coding: utf-8 -*-
"""活体（批 76 笔 1）：`ExecutionEngine` 只剩监控器那一条活路，且那条活路读数一字未变。

两侧同跑差分（基线＝退役前的 HEAD，本批侧＝改后），三组读数各证一件事：

① **活路不变**：三个 monitor 端点（`/api/v1/monitor/status`、`/alerts`、`/connections`）经真
   `create_app()` + lifespan + 真 JWT（`create_access_token` 带 `role=admin`，这些端点挂 `require_admin()`）
   在两侧给出**同一组状态码与同一形状**——这条是"退役没打断唯一来路"的正面证据。
② **第二把 ToolEngine 从此不再被装配**：给 `execution_engine.tool_engine.ToolEngine.__init__` 包计数 wrapper
   后跑同一串请求。改前基线是 **2 次**（`shared_core/execution_engine.py` 的 `_init_components` 一份 +
   `api/endpoints/tool_layers.py` 一份，批 68 就是量到这个数才立票的），改后应为 **1 次**——
   差的那一把正是本批删掉的孤儿组件。
③ **声明面收口**：实例上残留的可变字段（`vars(engine)` 的键集）与类上的方法集，改后只剩监控器那一圈。
   这一组是形状读数，单独看不能证行为（形态集 278），所以它与①同批取、 mutually 约束。

②③ 两组在基线侧必须 FAIL——那是探针有牙的证明，不是脚本走偏。
"""
from __future__ import annotations

import hashlib
import sys
import typing
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402

ROOT = isolatedDataRoot(prefix="neurovaSharedCoreB76")
DATA = REPO / "data"
FAILURES = []

#: 本批之后类上应当只剩这四条（多一条＝没删净，少一条＝删过头）
SURVIVING_METHODS = {"__new__", "__init__", "_init_components", "get_execution_monitor"}
#: 本批之后实例上不该再有只写不读的组件位
ORPHAN_FIELDS = {"_executions", "_tool_engine", "_workflow_engine", "_event_bus", "_running"}


def fingerprint():
    h = hashlib.md5()
    for p in sorted(DATA.rglob("*")):
        if p.is_file():
            h.update(p.relative_to(DATA).as_posix().encode("utf-8"))
            h.update(str(p.stat().st_size).encode("ascii"))
    return h.hexdigest()


BEFORE = fingerprint()


def leg(name, ok, reading):
    print(f"[{'PASS' if ok else 'FAIL'}] {name} :: {reading}")
    if not ok:
        FAILURES.append(name)


# ② 计数 wrapper：必须在起 app 之前包上
from neurova.execution_engine import tool_engine as TE  # noqa: E402

toolEngineBuilds = {"n": 0}
_origToolEngineInit = TE.ToolEngine.__init__


def _countingInit(self, *a, **k):
    toolEngineBuilds["n"] += 1
    return _origToolEngineInit(self, *a, **k)


TE.ToolEngine.__init__ = _countingInit

from fastapi.testclient import TestClient  # noqa: E402

from neurova.api.app import create_app  # noqa: E402
from neurova.api.auth import create_access_token  # noqa: E402

app = create_app()
paths = set(app.openapi()["paths"])
HDR = {"Authorization": f"Bearer {create_access_token({'sub': 'b76-user', 'role': 'admin'})}"}

MONITOR_CALLS = ["/api/v1/monitor/status", "/api/v1/monitor/alerts", "/api/v1/monitor/connections"]
monitorReadout: typing.Dict[str, object] = {}
listCount = -1
executeBody: typing.Dict[str, object] = {}

with TestClient(app) as client:
    missing = [p for p in MONITOR_CALLS if p not in paths]
    for p in MONITOR_CALLS:
        r = client.get(p, headers=HDR)
        payload = r.json() if r.status_code == 200 else None
        monitorReadout[p] = {
            "status": r.status_code,
            "shape": sorted(payload.keys()) if isinstance(payload, dict) else type(payload).__name__,
        }

    listPath = next((p for p in paths if p.endswith("/tool-layers/tools")), "")
    listCount = len(client.get(listPath, headers=HDR).json())
    execPath = next((p for p in paths if p.endswith("/tool-layers/tools/execute")), "")
    r = client.post(execPath, json={"tool_name": "file_read",
                                    "arguments": {"path": "README.md"}}, headers=HDR)
    executeBody = {"status": r.status_code, "code": r.json().get("code")}

from neurova.shared_core import execution_engine as EE  # noqa: E402

engine = EE.get_execution_engine()
classMethods = {m for m in dir(engine) if callable(getattr(engine, m, None))
                and not m.startswith("__")}
instanceFields = set(vars(engine))

# ① 活路：三个端点必须全 200 且回包形状非空
leg("①monitor 三端点（这把引擎唯一的生产来路）全部可达",
    not missing and all(v["status"] == 200 and v["shape"] for v in monitorReadout.values()),
    f"缺席路由={missing} 读数={monitorReadout}")

# ② 第二把 ToolEngine 不再被装配（改前＝2，改后＝1）
leg("②shared_core 侧不再构造第二把 ToolEngine",
    toolEngineBuilds["n"] == 1,
    f"真 app + 6 个请求期间 ToolEngine 构造次数={toolEngineBuilds['n']}（改前基线读数应为 2）")

# ③a 类上声明面只剩四条（按 dir 取，覆盖"删了但还挂着名字"的形态）
left = sorted(classMethods - SURVIVING_METHODS)
leg("③a类上不再挂着孤儿方法（含同名陷阱自查：只算这张类自己的成员）",
    not left, f"仍挂在实例上的公开方法={left or '无'}；存活集={sorted(SURVIVING_METHODS)}")

# ③b 实例上不再有只写不读的组件位
fieldsLeft = sorted(instanceFields & ORPHAN_FIELDS)
leg("③b实例上不再有只写不读的组件位",
    not fieldsLeft, f"残留字段={fieldsLeft or '无'}；现字段集={sorted(instanceFields)}")

# ④ 单例语义与监控器装配没被动
leg("④真单例照常给出监控器",
    EE.get_execution_engine() is engine and engine.get_execution_monitor() is not None,
    f"单例同一={EE.get_execution_engine() is engine} "
    f"监控器={type(engine.get_execution_monitor()).__name__}")

# ⑤ 列表面与工具执行面不受影响（对照格，两侧同绿）
leg("⑤对照：工具列表面与 execute 端点行为不变",
    listCount > 0 and executeBody.get("status") == 200,
    f"列表面条目数={listCount} execute 状态={executeBody.get('status')} code={executeBody.get('code')}")

AFTER = fingerprint()
leg("⑥仓内 data/ 未被写入", BEFORE == AFTER, f"md5 {BEFORE[:12]} -> {AFTER[:12]}（数据根={ROOT}）")

print("\n" + ("全部 PASS" if not FAILURES else f"存在 FAIL: {FAILURES}"))
sys.exit(0 if not FAILURES else 1)
