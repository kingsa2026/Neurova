# -*- coding: utf-8 -*-
r"""live-verify（读面对账，§6-272 用户裁甲）：真 HTTP 面上，空壳条目不得被报成可得。

真物：本机 `data/agents/default/skills/manifest.json` 的 8 条里 **7 条是空壳**（目录只有 manifest.json，
2026-10-06 那批旧代码留下的），`web-search` 是唯一有代码映射执行体的那条。本档把这份真账本逐字节
复制进隔离数据根（并把条目里的绝对 `path` 改指副本——上一批的教训：不改就会读到真目录，
判据走成没咬到的支路），然后走三条真面：

  A. `GET /api/v1/skill-pool/agent/default/skills`（面板的数据源，真 FastAPI + TestClient + 真身份覆盖）
  B. `SkillService.get_skill_info`（详情投影）
  C. `restore_market_skills_from_service` → `SkillRegistry`（"能不能被调用"这一面的事实源）
  D. `VisibleSkill.enabled`（工具 schema／提示词目录那条链的判据）

判据形状是**四面对同一条目必须同向**：投影说不可得 ⇒ 执行表里就不许有它、可见性闸就不许放行。
任何一面单独放宽都会红（这就是本档比"各测各的"强的地方）。

HEAD 对照腿（无本批修复）的跑法见文末；期望 A/C/D 三组读数翻红。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402

AGENT = "default"
MAPPED = "web-search"          # 有代码映射执行体：盘上无字节也算可得，不许误灰
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


def dataFingerprint():
    root = REPO / "data"
    if not root.exists():
        return (0, "无 data 目录")
    files = sorted(p for p in root.rglob("*") if p.is_file())
    digest = hashlib.sha256("\n".join(
        "%s:%s" % (p.relative_to(root).as_posix(), p.stat().st_size) for p in files)
        .encode("utf-8")).hexdigest()[:12]
    return (len(files), digest)


ROOT = isolatedDataRoot(prefix="neurovaReadB58")
SRC_DATA = Path(os.environ.get("NEUROVA_LIVE_SOURCE_DATA") or (REPO / "data"))
print("隔离数据根：%s（源：%s）" % (ROOT, SRC_DATA))

from neurova.security import artifact_digest as AD  # noqa: E402
from neurova.skills import library_service as lib  # noqa: E402
from neurova.skills.skill_service import SkillService  # noqa: E402

startFp = dataFingerprint()


def seed():
    srcSkills = SRC_DATA / "agents" / AGENT / "skills"
    if not (srcSkills / "manifest.json").exists():
        raise RuntimeError("源账本不在：%s" % srcSkills)
    dst = ROOT / "agents" / AGENT / "skills"
    dst.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(str(srcSkills / "manifest.json"), str(dst / "manifest.json"))
    ledger = json.loads((dst / "manifest.json").read_text(encoding="utf-8"))
    for sid, row in ledger.items():
        if not isinstance(row, dict) or not row.get("path"):
            continue
        srcDir = Path(row["path"])
        if srcDir.is_dir():
            shutil.copytree(str(srcDir), str(dst / sid), dirs_exist_ok=True)
        # 账本里是绝对路径，不改指副本就读真目录（上一批的活体假绿就是这么来的）
        row["path"] = str(dst / sid)
    (dst / "manifest.json").write_text(json.dumps(ledger, ensure_ascii=False), encoding="utf-8")
    return dst, ledger


try:
    SKILLS_DIR, LEDGER = seed()
except Exception as exc:  # noqa: BLE001
    readFailure = repr(exc)  # PEP 3110：`exc` 出了 except 块就不再绑定，先取值再交给懒求值的 lambda
    read("[0] 复制真账本到隔离根", lambda: (False, readFailure))
    sys.exit(1)

svc = SkillService(agent_id=AGENT, skills_dir=str(SKILLS_DIR))
rows = [r for r in svc.list_skills()]
# 映射执行体型单列：它是「盘上没字节也真能跑」那一形，混进空壳就是探针自己冤枉判据。
# 直连公共读面，不留同名桩：留一枚 `except ImportError` 里定义的 `hasExecutorMapping`，
# 一旦真触发就把「在册判定」静默换成本档自己拼的字符串比较，读的人还以为在读同一个事实源。
from neurova.skills.market_registry import hasExecutorMapping  # noqa: E402


def classify(entry):
    # 映射执行体型单列：它是「盘上没字节也真能跑」那一形，混进空壳就是探针自己冤枉判据。
    # 取数口是上面那句**直连**导入（模块级，无 try + 同名 def 桩）：桩一旦触发，探针问的
    # 就不是产品那一句，而对照腿要比的读数反而被自己的兜底改掉了（§6-228 零容忍那一条）。
    sid = entry["id"]
    d = SKILLS_DIR / sid
    hasBytes = (d / "SKILL.md").exists() or bool(list(d.glob("*.py")))
    mapped = hasExecutorMapping(sid)
    return sid, hasBytes, mapped


perEntry = [classify(r) for r in rows]
shells = sorted(i for i, has, mapped in perEntry if not has and not mapped)
mappedOnly = sorted(i for i, has, mapped in perEntry if not has and mapped)
withBytes = sorted(i for i, has, _ in perEntry if has)

read("[1] 真形：账本在册的条目里，落盘无构件的有几条", lambda: (
    len(shells) >= 1, "空壳 %d 条 %s；仅映射执行体 %s；有字节 %d 条 %s" % (
        len(shells), shells, mappedOnly, len(withBytes), withBytes)))

read("[2] 详情投影：空壳给 available=False＋原因，有构件的不误灰", lambda: (
    all(svc.get_skill_info(s).get("available") is False and svc.get_skill_info(s).get("unavailableReason")
        for s in shells)
    and all(svc.get_skill_info(w).get("available") is True for w in withBytes),
    "空壳读数 %s；有字节 %s" % (
        {s: svc.get_skill_info(s).get("available") for s in shells[:2]},
        {w: svc.get_skill_info(w).get("available") for w in withBytes})))

read("[3] 映射执行体型不被误灰（web-search 盘上无字节但真能跑）", lambda: (
    MAPPED in [r["id"] for r in rows] and svc.get_skill_info(MAPPED).get("available") is True,
    "available=%s" % svc.get_skill_info(MAPPED).get("available")))

# ── 真 HTTP 面 ────────────────────────────────────────────────────────────────
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from neurova.api.deps import get_current_user  # noqa: E402 — 端点 import 的就是这个对象，patch 别处静默失效
from neurova.api.endpoints import skill_pool_api  # noqa: E402
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


lib.reset_libraries_for_tests()
monkey_app = FastAPI()
monkey_app.include_router(skill_pool_api.router, prefix="/api/v1/skill-pool")
monkey_app.dependency_overrides[get_current_user] = lambda: {
    "user_id": "1", "username": "qa", "role": "admin", "neuser_id": "1"}
# 端点走 library_service 的单例库；把库根指到副本，保证这一面读的就是刚那份账本
lib._BASE_DIR = ROOT  # 库根＝ROOT：agent 库解析成 ROOT/agents/<id>/skills
lib.reset_libraries_for_tests()

with TestClient(monkey_app) as http:
    resp = http.get("/api/v1/skill-pool/agent/%s/skills" % AGENT)
    items = resp.json() if resp.status_code == 200 else []

byId = {i.get("skill_id"): i for i in items}
read("[4] 面板数据源（真 HTTP 面）同向：空壳 available=False＋原因", lambda: (
    bool(items) and all(byId.get(s, {}).get("available") is False and byId.get(s, {}).get("unavailable_reason")
                        for s in shells),
    "HTTP %s、%d 条；样例 %s" % (resp.status_code, len(items),
                                {k: (byId[k].get("available"), byId[k].get("unavailable_reason")[:18])
                                 for k in list(shells)[:2]})))

def _restoreRead():
    from neurova.skill_system import SkillRegistry
    from neurova.skills.market_registry import restore_market_skills_from_service

    registry = SkillRegistry()
    n = restore_market_skills_from_service(svc, registry)
    listed = [s.name for s in registry.list_skills()]
    leaked = [s for s in shells if s in listed]
    return (not leaked, "恢复了 %d 条；执行表里 %s；空壳漏进的 %s" % (
        n, sorted(listed)[:4], leaked))


def _visibilityRead():
    from neurova.skills.skill_visibility import VisibleSkill

    def gate(sid):
        e = dict(svc.get_skill_info(sid) or {})
        e.setdefault("name", sid)
        return VisibleSkill(name=sid, skill_id=sid, pool="agent", owner_key=AGENT, entry=e).enabled

    shellFlags = {s: gate(s) for s in shells}
    okFlags = {w: gate(w) for w in withBytes}
    return (all(v is False for v in shellFlags.values())
            and all(v is True for v in okFlags.values()),
            "空壳闸 %s；有字节闸 %s" % (shellFlags, okFlags))


read("[5] 恢复口：空壳不进执行表，有构件的照旧进", lambda: _restoreRead())


read("[6] 可见性闸：空壳条目喂进 VisibleSkill 即不可调，有构件的照旧可调", lambda: _visibilityRead())


observe("账本落盘有没有被这次读操作改写（读面不该写账本）", lambda: (
    len(json.loads((SKILLS_DIR / "manifest.json").read_text(encoding="utf-8"))),
    "副本条目数"))

observe("AD.DIGEST_FIELD 有没有被空壳条目吃进（批 57 那条腿的复证）", lambda: [
    s for s in shells if AD.DIGEST_FIELD in (LEDGER.get(s) or {})][:3])

endFp = dataFingerprint()
print("仓内 data/ 指纹：起 %d 文件／%s → 止 %d 文件／%s" % (
    startFp[0], startFp[1], endFp[0], endFp[1]))
print("\n==== 汇总：计分读数 6 项，失败 %d ====" % len(failures))
for f in failures:
    print("  FAIL", f)
sys.exit(1 if (failures or endFp != startFp) else 0)
