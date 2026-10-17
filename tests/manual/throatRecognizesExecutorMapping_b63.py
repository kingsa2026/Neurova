# -*- coding: utf-8 -*-
r"""live-verify（批 63）：代码映射型在**真链**上名实一致——面板说可用，点执行就得真跑出值。

走真装配点：真 `create_app()` + `TestClient` + 真签 token + 隔离数据根；执行口是
`POST /api/v1/skill-pool/private/{id}/execute`（唯一那条 HTTP 执行路），注册面是真恢复口
`restore_market_skills_from_service`。执行体经**生产缝** `registerExecutorMapping` 注册，
测试不直读私有表——这条腿本身也要被走一次。

要证的四件与一件对照：
① 在册映射的空壳条目经真 HTTP 口跑出执行体的返回值（§6-280 甲的不可逆点就在这：对外契约
   从此承认"盘上没有字节的技能"可以经池/运行口执行）；
② 同形但不在映射表 ⇒ 照旧拒（分流没把"盘上什么都没有"放行）；
③ 行级 `enabled` 闸与"账本认识"前提没被分流绕过去；
④ 内置 `web-search` 在注册面造得出真执行体（`_build_executable_skill` 与咽喉读同一张表——
   收口收到一半时这一腿会静默降级成裸壳，本轮真踩过，被既有判据抓过）；
⑤ 跑过映射那一趟之后账本摘要**不写不改**（完整性由代码本体负责，不是"摘要缺失所以放行"）。

如实记一句：这一层不证"两条腿的锁形状相反"——那是单元档里"执行体回调本服务"那一格的事；
活体跑的是单请求路径，测不出跨线程持锁的形态。
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402

ROOT = isolatedDataRoot(prefix="neurovaMappedThroatB63")
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
from neurova.api.auth import create_access_token  # noqa: E402
from neurova.security import artifact_digest as AD  # noqa: E402
from neurova.skills import library_service, market_registry  # noqa: E402
from neurova.skills.executor import BaseSkillExecutor, ExecutorBackedSkill, SkillResult  # noqa: E402
from neurova.skill_system.core import SkillRegistry  # noqa: E402
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


AGENT = "b63-live"
MAPPED_ID = "b63-live-mapped"
PLAIN_ID = "b63-live-plain"
PROBE_RAN = {"count": 0}


class _LiveProbeExecutor(BaseSkillExecutor):
    """同协议的探针执行体：经真 `registerExecutorMapping` 进表，不碰网。"""

    def __init__(self, skill_id: str):
        super().__init__(skill_id=skill_id, skill_name="批 63 活体探针")

    def execute(self, params=None, *args, **kwargs) -> SkillResult:
        PROBE_RAN["count"] += 1
        return SkillResult(success=True, output={
            "probeRan": self.skill_id, "saw": dict(params or {})})


def _installShellEntry(skill_id: str) -> Path:
    """经真安装咽喉装一只"目录里只有 manifest.json"的条目——与本机 `web-search` 同形。"""
    svc = library_service.agentLibrary(AGENT)
    src = Path(ROOT) / "src" / skill_id
    src.mkdir(parents=True, exist_ok=True)
    (src / "manifest.json").write_text(json.dumps(
        {"id": skill_id, "name": skill_id, "version": "1.0.0", "source": "marketplace"},
        ensure_ascii=False), encoding="utf-8")
    result = svc.install_skill(str(src), skill_id=skill_id)
    assert result.get("success") is True, f"装配本身没成，样本不成立：{result}"
    return svc.skills_dir / skill_id


def ledgerDigest(skill_id: str) -> str:
    ledger = json.loads(Path(library_service.agentLibrary(AGENT).manifest_path)
                        .read_text(encoding="utf-8"))
    return str((ledger.get(skill_id) or {}).get(AD.DIGEST_FIELD) or "")


failures = []


def read(what, probe):
    """读数与"为什么不健康"分开打印（PASS 行刷出缺陷文案会把绿读成红）。"""
    try:
        ok, detail, hint = probe()
    except Exception as exc:  # noqa: BLE001
        ok, detail, hint = False, "探针异常 %r" % (exc,), ""
    print("[%s] %s — %s%s" % ("PASS" if ok else "FAIL", what, detail,
                              "" if ok else ("；缺陷读法：" + hint)))
    if not ok:
        failures.append(what[:6])
    return ok


market_registry.registerExecutorMapping(MAPPED_ID, lambda: _LiveProbeExecutor(MAPPED_ID))
_installShellEntry(MAPPED_ID)
_installShellEntry(PLAIN_ID)

app = create_app()
client = TestClient(app)
token = create_access_token({"sub": "b63-live-user", "role": "admin"})
HEAD = {"Authorization": "Bearer %s" % token}


def execute(skill_id: str, arguments=None):
    r = client.post(f"/api/v1/skill-pool/private/{skill_id}/execute",
                    json={"agent_id": AGENT, "arguments": arguments or {"query": "ping"}},
                    headers=HEAD)
    return r.status_code, (r.json() if r.status_code < 500 else {})


def _poolAgent():
    """经生产缝取那一份内存账（`disable_skill` 这类写动作要它写，改文件不算）。"""
    return library_service.agentLibrary(AGENT)


# ① 在册映射 ⇒ 真 HTTP 口跑出执行体的返回值
def leg1():
    before = PROBE_RAN["count"]
    status, body = execute(MAPPED_ID, {"query": "真链一问"})
    data = (body.get("data") or {})
    ran = PROBE_RAN["count"] - before
    return (status == 200 and data.get("success") is True and ran == 1
            and (data.get("result") or {}).get("probeRan") == MAPPED_ID,
            f"HTTP {status}，data.success={data.get('success')}，执行体被跑 {ran} 次，"
            f"result={str(data.get('result'))[:70]}",
            f"跑不动即咽喉没认映射表（读面会说可用）；拒因={str(data.get('error'))[:80]}")


read("1 在册映射条目经真执行口跑出值", leg1)


# ② 同形但不在表里 ⇒ 照旧拒
def leg2():
    status, body = execute(PLAIN_ID)
    data = (body.get("data") or {})
    return (status == 200 and data.get("success") is False
            and "No entry point" in str(data.get("error") or ""),
            f"HTTP {status}，success={data.get('success')}，error={str(data.get('error'))[:60]}",
            "被执行了即分流把「盘上什么都没有」也放行——那是拆闸，不是收口")


read("2 同形不在册的空壳照旧拒（对照）", leg2)


# ③ enabled 闸与账本前提没被绕过去
def leg3():
    """停用要经**生产写侧**（`disable_skill`）——只改落盘文件不动那一份内存账，
    咽喉读的是内存态，测出来的"仍拒"会是假绿（批 60 那条同族：写完读不到）。"""
    svc = library_service.agentLibrary(AGENT)
    disabled = svc.disable_skill(MAPPED_ID)
    statusOff, bodyOff = execute(MAPPED_ID)
    errOff = str((bodyOff.get("data") or {}).get("error") or "")
    svc.enable_skill(MAPPED_ID)

    statusMiss, bodyMiss = execute("b63-live-never-installed")
    detailMiss = str((bodyMiss.get("data") or {}).get("error") or bodyMiss.get("detail") or "")

    return (statusOff == 200 and "disabled" in errOff.lower()
            and statusMiss == 404 and "not found" in detailMiss.lower(),
            f"停用那条 HTTP {statusOff} 拒因={errOff[:52]}（disable_skill 回执={str(disabled.get('success'))}）；"
            f"账本外那条 HTTP {statusMiss} 拒因={detailMiss[:40]}",
            "停用或账本外也能跑，就是分流动了那两道闸——本批只放宽「盘上有没有字节」这一道")


read("3 停用闸与账本前提没被分流绕过", leg3)


# ④ 内置 web-search 在注册面造得出真执行体（同一张表）
def leg4():
    built = market_registry._build_executable_skill("web-search", "网络搜索", "")
    registry = SkillRegistry()
    registry.register(built)
    fetched = registry.get_skill("web-search")
    return (isinstance(built, ExecutorBackedSkill) and fetched is built
            and bool(built._get_parameters().get("query")),
            f"注册面造出 {type(built).__name__}，注册表回取到 {type(fetched).__name__ if fetched else None}，"
            f"参数 schema 里 query={'query' in built._get_parameters()}",
            "造出裸壳即注册面与咽喉读的是两张表（本轮真发生过，面板可用而工具面动不了）")


read("4 注册面与咽喉读同一张映射表", leg4)


# ⑤ 面板两面投影与执行口同向（真 HTTP 面上名实一致）
def leg5():
    """条目键名是 `skill_id` 不是 `id`（第一版按 `id` 找，找到的是空 dict ⇒ `available=None`，
    看着像"面板说不可用"其实是自己没看见那一行——读数要先证"我看到了那一行"）。"""
    status, body = execute(MAPPED_ID)
    ran = bool((body.get("data") or {}).get("success"))
    readings = []
    for path in (f"/api/v1/skill-pool/private?agent_id={AGENT}",
                 f"/api/v1/skill-pool/agent/{AGENT}/skills"):
        items = client.get(path, headers=HEAD).json()
        items = items if isinstance(items, list) else (items.get("skills") or [])
        row = next((i for i in items if isinstance(i, dict) and i.get("skill_id") == MAPPED_ID), None)
        if row is None:
            return (False, f"{path} 里没有这一行（读数无从比对）", "先证看见，再谈同向")
        readings.append("%s→available=%s" % (path.split("/skill-pool/")[1].split("?")[0],
                                             row.get("available")))
        if bool(row.get("available")) is not True:
            return (False, "；".join(readings) + f"；执行口跑出={ran}",
                    "投影说不可用而执行口跑得动，是另一种名实分叉")
        if bool(row.get("available")) is not ran:
            return (False, "；".join(readings) + f"；执行口跑出={ran}",
                    "两面反向即那条分叉还在（本批收的就是它）")
    return (True, "；".join(readings) + f"；执行口跑出={ran}", "")


read("5 面板投影与执行口同向", leg5)


# ⑥ 映射那一趟不写不改账本摘要
def leg6():
    before = ledgerDigest(MAPPED_ID)
    execute(MAPPED_ID, {"query": "再跑一趟"})
    after = ledgerDigest(MAPPED_ID)
    return (before == after, f"跑前摘要={before[:18] or '(无)'} ↔ 跑后={after[:18] or '(无)'}",
            "变了即映射腿把盘上那份字节当构件权威在钉/在改")


read("6 映射那一趟不写不改构件摘要", leg6)

print("    OBSERVE 隔离根=%s" % ROOT)
read("7 仓库 data/ 未被写入",
     lambda: (fingerprint() == DATA_BEFORE,
              f"跑前 {DATA_BEFORE[:12]} ↔ 跑后 {fingerprint()[:12]}",
              "两个指纹不同即本轮活体写进了仓内真数据根"))

print("\n== 得数：%s ==" % ("全部通过（7 腿）" if not failures else f"FAIL {failures}"))
sys.exit(1 if failures else 0)
