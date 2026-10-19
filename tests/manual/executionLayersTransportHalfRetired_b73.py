# -*- coding: utf-8 -*-
"""活体（批 73）：execution_layers 退役的是传输那半，运行时那半仍在生产路上且真跑得通。

这个文件 719 行是**两半**，判"退役"必须分开验——整包判死会误杀在役符号。脚本按这个分法走：
- **活的那半走真生产入口**：`neurova.tool_executor.ToolExecutor._execute_run_code(...)` 才是
  `execution_layers` 运行时符号在生产里的真消费点（`RuntimeFactory`／`RuntimeType`／
  `LocalExecutor`／`get_runtime_manager` 都在这里被取用），执行体是**真子进程**，读数取真 stdout；
  `agent_ref` 只是构造期的依赖注入壳，这条腿不读它（`_execute_run_code` 全文不取 `self._agent`）。
- **死的那半只能验"不再在场"**：那五个传输符号与模块级 `execute_skill()` 在两侧都零消费者，
  所以它在活体里只有一种合法读数——门面上取不到。基线树（退役前）这一腿 **FAIL**，
  本批侧 PASS；这条差就是探针有牙的证明，不是脚本走偏。

改前实状（同一份脚本、基线树 35121a57）：② **FAIL**，读数为门面里还挂着 6 个已退役名字；
其余 ①③④⑤⑥⑦ 六腿**两侧同绿**——① 那条尤其关键：它两侧给出同一个读数（`42` / `runtime_type=local`），
这才是"删的是死半区、行为中性"的正面证据，而不是只证"名字没了"。
同名陷阱另有一格（⑤）：当时 `execution_engine/mcp_manager.py` 里那份 `TransportType` 是它自己的
枚举，按名字扫全仓去删就会把在役符号一起删掉，所以这一格必须在两侧都绿。那份枚举随
§6-349 整档退役，⑤ 改为验「岛不再在场」——同名陷阱的教训留在按导入通道取数的口径里。
"""
from __future__ import annotations

import asyncio
import hashlib
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402

ROOT = isolatedDataRoot(prefix="neurovaExecLayersB73")
DATA = REPO / "data"

#: 传输那半——票④包 4 的退役对象（含那个"接了 transport 却从头到尾不用"的模块级 helper）
RETIRED = ("TransportType", "ExecutionTransport", "HTTPTransport",
           "WebSocketTransport", "TransportFactory", "execute_skill")
#: 运行时那半——各有 1–3 个生产文件取用，一条都不许被删过头
LIVE = ("RuntimeType", "LocalExecutor", "DockerExecutor",
        "RuntimeFactory", "RuntimeManager", "get_runtime_manager")
FAILURES = []


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


import neurova.execution_layers as EL  # noqa: E402

# ① 活的那半：真生产入口真跑一个子进程回来
from neurova.tool_executor import ToolExecutor  # noqa: E402

runResult = asyncio.run(ToolExecutor(None)._execute_run_code(
    {"code": "print(6*7)", "language": "python", "timeout": 20}))
leg("①运行时那半经真生产入口（run_code 内置工具）执行得回来",
    runResult.get("success") is True and "42" in (runResult.get("stdout") or "")
    and runResult.get("runtime_type") == "local",
    f"success={runResult.get('success')} stdout={runResult.get('stdout')!r} "
    f"runtime_type={runResult.get('runtime_type')} exit_code={runResult.get('exit_code')} "
    f"err={runResult.get('error')}")

# ② 死的那半：门面上必须取不到（这一腿就是基线与本批的差分）
stillThere = [n for n in RETIRED if hasattr(EL, n)]
leg("②传输那半（含假参数 helper）在门面上一个都不剩",
    not stillThere, f"仍挂在门面上的退役名={stillThere or '无'}")

# ③ 声明面与真身对齐：__all__ 里不许留空头声明
declared = list(getattr(EL, "__all__", []))
missing = [n for n in declared if not hasattr(EL, n)]
leg("③门面声明不留空头（__all__ 每个名字都取得到）",
    not missing, f"__all__ 共 {len(declared)} 名，取不到的={missing or '无'}")

# ④ 对照：在役六符号仍在，且工厂口径没被动
liveOk = [n for n in LIVE if hasattr(EL, n)]
supported = EL.RuntimeFactory.list_supported_types()
leg("④对照：运行时那六个在役符号照常从门面取到",
    liveOk == list(LIVE) and supported == [EL.RuntimeType.LOCAL, EL.RuntimeType.DOCKER],
    f"取到 {len(liveOk)}/{len(LIVE)}；工厂支持类型={supported}")

# ⑤ 同名陷阱：那枚同名枚举住在已退役的 mcp_manager 里（§6-334 D 票 → §6-349 落地）。
#   岛没了以后这一格不再 import 它（那会留一条「实现已删、探针还在引用」的悬空），
#   改为验「确实不在场」——同名陷阱的教训不靠这个文件活着来承载，靠判据按导入通道取数。
mmGone = not (REPO / "neurova" / "execution_engine" / "mcp_manager.py").exists()
leg("⑤同名陷阱格：mcp_manager 已退役且不再在场", mmGone, f"岛仍在场={not mmGone}")

# ⑥ 退役没打断装配：真 app 起得来、工具列表面照常出条目
from fastapi.testclient import TestClient  # noqa: E402

from neurova.api.app import create_app  # noqa: E402
from neurova.api.auth import create_access_token  # noqa: E402

app = create_app()
listPath = next((p for p in app.openapi()["paths"] if p.endswith("/tool-layers/tools")), "")
HDR = {"Authorization": f"Bearer {create_access_token({'sub': 'b73-user'})}"}
with TestClient(app) as client:
    resp = client.get(listPath, headers=HDR)
entries = resp.json()
leg("⑥真 app + lifespan 起得来，工具列表面照常（退役不在装配路上）",
    resp.status_code == 200 and isinstance(entries, list) and len(entries) > 0,
    f"GET {listPath} -> {resp.status_code}，条目数={len(entries) if isinstance(entries, list) else '非列表'}")

AFTER = fingerprint()
leg("⑦仓内 data/ 未被写入", BEFORE == AFTER, f"md5 {BEFORE[:12]} -> {AFTER[:12]}（数据根={ROOT}）")

print("\n" + ("全部 PASS" if not FAILURES else f"存在 FAIL: {FAILURES}"))
sys.exit(0 if not FAILURES else 1)
