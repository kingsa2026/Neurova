# -*- coding: utf-8 -*-
r"""live-verify（批 60）：同一进程里"写完立刻读得到"必须在**真 HTTP 面**上成立。

缺陷实形（本批开工前的读数，不是推断）：`POST /api/v1/skill-pool/{id}/install` 回 200
`installed successfully`，紧接着同进程 `GET /api/v1/skill-pool/agent/default/skills` 读到 **0 条**
——写侧 `marketplace.py` 自建 `SkillService(agent_id=…)`（4 处），读侧 `_pool_service()` 走
`library_service.get_library` 的同进程单例，同一本 `manifest.json` 两份内存账，而
`list_skills()`/`iter_skills()` 不重载磁盘。用户裁乙：全量收进单例。

真物：`create_app()` + `TestClient`（起真 lifespan）+ 真身份覆盖；数据根经
`_liveVerifyIsolation.isolatedDataRoot()` 单点隔离；跑前跑后各取一次仓内 `data/` 内容指纹。

反证腿见文末：把 marketplace 那一处退回自建实例，第 2 腿必须红在缺陷读数上。
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402

ROOT = isolatedDataRoot(prefix="neurovaLibB60")
DATA = REPO / "data"


def fingerprint():
    """仓内 data/ 的**内容**指纹（清单集合差看不见原地改写与等量搬移，故带上字节数）。"""
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

SKILL_ID = "builtin--multi-search-engine"
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


def observe(what, probe):
    try:
        print("    OBSERVE %s：%s" % (what, probe()))
    except Exception as exc:  # noqa: BLE001
        print("    OBSERVE %s：读数失败 %r" % (what, exc))


app = create_app()
app.dependency_overrides[get_current_user] = lambda: {
    "id": "u-b60", "sub": "u-b60", "username": "u-b60", "role": "admin"}

with TestClient(app) as client:

    def faceRows():
        got = client.get(f"/api/v1/skill-pool/agent/{AGENT}/skills")
        assert got.status_code == 200, f"读面本身 HTTP {got.status_code}"
        return [r.get("skill_id") for r in (got.json() or [])]

    # ① 真安装链装上一只内置包
    installed = client.post(f"/api/v1/skill-pool/{SKILL_ID}/install", params={"agent_id": AGENT})
    read("1 安装回执", lambda: (installed.status_code == 200,
                                f"HTTP {installed.status_code} {str(installed.text)[:160]}"))

    # ② 主格：同进程紧接着读面必须看见（原缺陷读数＝0 条）
    read("2 同进程读面立刻认账",
         lambda: (SKILL_ID in faceRows(), f"读面 {len(faceRows())} 条 {faceRows()[:6]}"))

    # ③ 闭环另一半：撤掉之后同进程读面必须**不再**看见（只验"写能读"是半个闭环）。
    #    卸载口在市场面（`DELETE /marketplace/skills/{id}/install`），池路由没有 DELETE 这条——
    #    第一版我把 URL 写成池面的 `/skill-pool/{id}/install`，读数回来是 405（脚本自己的错，不是产品）。
    removed = client.delete(f"/api/v1/marketplace/skills/{SKILL_ID}/install",
                            params={"agent_id": AGENT})
    read("3 卸载后读面同进程就失账",
         lambda: (removed.status_code == 200 and SKILL_ID not in faceRows(),
                  f"HTTP {removed.status_code}，读面仍含它={SKILL_ID in faceRows()}"))

    # ④ 写侧与读侧必须是**同一个对象**（"两份内存账"这句话的正身）
    def sameInstance():
        from neurova.api.endpoints import skill_pool_api
        from neurova.skills.library_service import agentLibrary

        a = skill_pool_api._pool_service(AGENT)
        b = agentLibrary(AGENT)
        return (a is b, f"读面实例 is 写侧实例 = {a is b}")

    read("4 读写同实例", sameInstance)

    # ⑤ 非法 agent_id：合流后写面要与读面同形——显式 5xx 点名原因，不许静默写错根再回 200
    bad = client.post(f"/api/v1/skill-pool/{SKILL_ID}/install",
                      params={"agent_id": "bad/../escape"})
    read("5 非法 agent_id 出声且点名",
         lambda: (bad.status_code >= 400 and "非法 agent id" in str(bad.text),
                  f"HTTP {bad.status_code} {str(bad.text)[:150]}"))

    observe("6 隔离根落点", lambda: {"root": str(ROOT),
                                     "agents": sorted(p.name for p in (ROOT / "agents").glob("*"))
                                     if (ROOT / "agents").is_dir() else "无"})

read("7 仓库 data/ 未被写入",
     lambda: (fingerprint() == DATA_BEFORE, f"指纹 {DATA_BEFORE[:12]} 跑后未变"))

print("\n== 得数：%s ==" % ("全部通过（7 腿）" if not failures else f"FAIL {failures}"))
sys.exit(1 if failures else 0)

# 反证腿（第 2 腿必须红在缺陷读数上）：
#   .venv/Scripts/python.exe .tmp_mutate_b60.py apply N1
#   .venv/Scripts/python.exe tests/manual/librarySingletonClosesReadFace_b60.py
#   .venv/Scripts/python.exe .tmp_mutate_b60.py restore N1
