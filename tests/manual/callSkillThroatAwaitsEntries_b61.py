# -*- coding: utf-8 -*-
r"""live-verify（批 61）：协程入口的技能，经**真 HTTP 执行口**必须跑得出来。

裁定（用户拍甲·分两批）：本批只做咽喉异步化；映射表分流留下一批。

真物：`create_app()` + `TestClient`（起真 lifespan），数据根经
`_liveVerifyIsolation.isolatedDataRoot()` 单点隔离；技能是**真落盘真加载**的包（不 mock 咽喉）：
一份入口是 `async def main`，一份入口是普通 `def main`，还有一份**技能体里回调本服务**——
第三份是给"把同步技能挪进线程池"那种实现准备的：咽喉全程持线程级 RLock，挪出去就死锁，
所以这里带 15s 墙钟自己红，而不是把整轮拖死。

反证腿：`python .tmp_mutate_b61.py apply P1`（端点退回同步内联）后重跑本脚本，
协程那条腿必须红在 HTTP 500 上；`restore P1` 还原并 md5 复证。
"""
from __future__ import annotations

import hashlib
import json
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402

ROOT = isolatedDataRoot(prefix="neurovaThroatB61")
DATA = REPO / "data"


def fingerprint():
    h = hashlib.md5()
    for p in sorted(DATA.rglob("*")):
        if p.is_file():
            h.update(p.relative_to(DATA).as_posix().encode("utf-8"))
            h.update(str(p.stat().st_size).encode("ascii"))
    return h.hexdigest()


DATA_BEFORE = fingerprint()

from fastapi.testclient import TestClient  # noqa: E402

from neurova.api.app import create_app  # noqa: E402
from neurova.api.deps import get_current_user  # noqa: E402

AGENT = "default"
failures = []


def read(what, probe):
    try:
        ok, detail = probe()
    except Exception as exc:  # noqa: BLE001
        ok, detail = False, "探针异常 %r" % (exc,)
    print("[%s] %s — %s" % ("PASS" if ok else "FAIL", what, detail))
    if not ok:
        failures.append(what[:6])
    return ok


def install(skillId: str, entryBody: str):
    """真装一只技能进 agent 库（写侧就用生产取法，不另开落点）。"""
    from neurova.skills.library_service import agentLibrary

    pkg = ROOT / "src" / skillId
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "manifest.json").write_text(json.dumps(
        {"id": skillId, "name": skillId, "version": "1.0.0"}), encoding="utf-8")
    (pkg / "SKILL.md").write_text("# demo\n\n演示。\n", encoding="utf-8")
    (pkg / "main.py").write_text(entryBody, encoding="utf-8")
    return agentLibrary(AGENT).install_skill(str(pkg))


CORO = "async def main(**kwargs):\n    return {'ran': 'coroutine-entry'}\n"
SYNC = ("import threading\n"
        "def main(**kwargs):\n"
        "    return {'ran': 'sync-entry', 'thread': threading.current_thread().name}\n")
CALLBACK = ("def main(**kwargs):\n"
            "    from neurova.skills.library_service import agentLibrary\n"
            "    return {'ran': 'callback', 'listed': "
            "len(agentLibrary('default').list_skills())}\n")

app = create_app()
app.dependency_overrides[get_current_user] = lambda: {
    "id": "u-b61", "sub": "u-b61", "username": "u-b61", "role": "admin"}

with TestClient(app) as client:
    def execute(skillId):
        return client.post(f"/api/v1/skill-pool/private/{skillId}/execute",
                           json={"agent_id": AGENT, "arguments": {}})

    for skillId, body in (("b61-coro", CORO), ("b61-sync", SYNC), ("b61-cb", CALLBACK)):
        put = install(skillId, body)
        read(f"0 装 {skillId}", lambda put=put: (bool(put.get("success")), str(put)[:120]))

    # ① 协程入口：真 HTTP 口必须拿到跑出来的值（改前这里是 500）
    read("1 协程入口经 HTTP 跑得出来", lambda: (
        execute("b61-coro").status_code == 200
        and ((execute("b61-coro").json() or {}).get("data") or {}).get("result")
        == {"ran": "coroutine-entry"},
        f"HTTP {execute('b61-coro').status_code} {str(execute('b61-coro').text)[:150]}"))

    # ② 同步入口：语义不变，且**不许跑在线程池里**（跑进去就破了咽喉的线程级 RLock 重入）。
    #    基准不取"主线程名"——TestClient 的 portal 线程名与技能里读到的线程名不是同一个基准，
    #    比错了会一直绿。这里判的是坏实现特有的可观测形状：asyncio 默认执行器的线程名形如
    #    `ThreadPoolExecutor-0_1`，技能体若跑进那种线程，就是被挪出了事件循环。
    resp = (execute("b61-sync").json() or {})
    data = resp.get("data") or {}
    ranThread = str((data.get("result") or {}).get("thread") or "")

    def syncLeg():
        if (data.get("result") or {}).get("ran") != "sync-entry":
            return (False, f"同步入口读数变了：{str(data)[:150]}")
        inExecutor = "ThreadPoolExecutor" in ranThread or ranThread.startswith("asyncio_")
        return (not inExecutor,
                f"技能体跑在 {ranThread!r}"
                + ("＝被挪进了线程池，RLock 重入语义已破" if inExecutor else "＝仍在事件循环线程"))

    read("2 同步入口没被挪进线程池", syncLeg)

    # ③ 重入：技能体里回调本服务，必须按时完成。这层**不能**用 asyncio.wait_for 兜——
    #    端点内部把超时转成 500，而线程卡死会让 HTTP 请求本身不返回；所以自己开线程、
    #    限时 join：到点就红，绝不让脚本挂在那里（形态集 253 的"没跑成"三形态之一就是挂死）。
    def callbackLeg():
        box = {}

        def run():
            try:
                got = execute("b61-cb")
                box["code"] = got.status_code
                box["result"] = ((got.json() or {}).get("data") or {}).get("result")
            except Exception as exc:  # noqa: BLE001
                box["err"] = repr(exc)

        t = threading.Thread(target=run, name="b61-callback-leg", daemon=True)
        start = time.time()
        t.start()
        t.join(20)
        spent = time.time() - start
        if t.is_alive():
            return (False, f"回调腿 {spent:.1f}s 还没回来＝锁重入被破坏（线程级 RLock 被跨线程持有）")
        return (box.get("code") == 200 and bool(box.get("result")),
                f"HTTP {box.get('code')}，用时 {spent:.1f}s，读数={str(box.get('result'))[:120]}"
                f"{'，异常=' + box['err'] if 'err' in box else ''}")

    read("3 技能体回调本服务不死锁（限时 20s 自己红）", callbackLeg)

    observe = lambda: print("    OBSERVE 落点：%s / agents=%s" % (
        ROOT, sorted(p.name for p in (ROOT / "agents").glob("*"))
        if (ROOT / "agents").is_dir() else "无"))
    observe()

read("4 仓库 data/ 未被写入",
     lambda: (fingerprint() == DATA_BEFORE, f"指纹 {DATA_BEFORE[:12]} 跑后未变"))

print("\n== 得数：%s ==" % ("全部通过（4 腿）" if not failures else f"FAIL {failures}"))
sys.exit(1 if failures else 0)
