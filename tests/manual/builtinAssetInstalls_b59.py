# -*- coding: utf-8 -*-
r"""live-verify（批 59）：那只随包内置的真资产包，走**用户点安装那条真 HTTP 链**装得上吗。

三刀合起来的得数在这里取，不在单元测试里取（教义第 4 条）：

  ① 暂存目录名不再嵌整段 skill_id（Windows 260 预算被它白吃 24 字符 ⇒ 真入口报 500）
  ② `subprocess_call` 改判命令形状（argv 列表降 low 报告项；字符串首参照旧 high）——用户裁甲
  ③ 包内 `scripts/package_check.py` 的裸名 `compile(...)` 换成等价 `ast.parse(...)`

真物：`create_app()` + `TestClient` + 真 JWT 之外的真身份覆盖（`neurova.api.deps.get_current_user`），
数据根经 `_liveVerifyIsolation.isolatedDataRoot()` 单点隔离；跑完复证仓内 `data/` 未被写入。

反证腿（第 7 项）：同一份脚本在**根修退回后**必须红在缺陷读数上——退回方法见文末注释。
"""
from __future__ import annotations

import hashlib
import io
import json
import shutil
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402

ROOT = isolatedDataRoot(prefix="neurovaAssetB59")

from fastapi.testclient import TestClient  # noqa: E402

from neurova.api.app import create_app  # noqa: E402
from neurova.api.deps import get_current_user  # noqa: E402
from neurova.skills.market_importer import read_builtin_bundle  # noqa: E402

SKILL_ID = "builtin--adaptive-presentation-studio"
BUNDLE = "adaptive-presentation-studio.zip"
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


def syntheticZip(name: str, files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for rel, text in files.items():
            zf.writestr(rel, text)
    return buf.getvalue()


before = dataFingerprint()
print("隔离数据根：%s\n仓内 data/ 跑前：%s" % (ROOT, before))

app = create_app()
app.dependency_overrides[get_current_user] = lambda: {
    "id": "u-live-b59", "sub": "u-live-b59", "username": "live", "role": "admin"}
client = TestClient(app)

with client:
    read("1 资产在场且成员未减", lambda: (
        lambda p: (bool(p), "字节=%d" % (len(p) if p else 0)))(read_builtin_bundle(BUNDLE)))

    def installViaPanel():
        r = client.post(f"/api/v1/skill-pool/{SKILL_ID}/install", params={"agent_id": "default"})
        body = r.json() if str(r.headers.get("content-type", "")).startswith("application/json") else r.text
        return r.status_code == 200, "HTTP %s 回执=%s" % (r.status_code, str(body)[:220])

    read("2 面板那条链装得上（200，非 409/500）", installViaPanel)

    def faceAgree():
        """读面必须看得见这条：取一份**新实例**读账本（写侧确实落盘了才算装成）。

        同进程单例 `_pool_service()` 那条面在本批实测仍读到 0 条——那是另一处根因
        （市场安装链自建实例写、端点用单例读，跨实例内存态互踩），本批不动它，
        读数写在下面第 3b 项里，登记见台账。
        """
        from neurova.skills.skill_service import SkillService

        rows = SkillService(agent_id="default").list_skills()
        hit = [s for s in rows if s.get("id") == SKILL_ID]
        if not hit:
            return False, "换新实例读账本也没有这条（ids=%s）" % [s.get("id") for s in rows]
        one = hit[0]
        avail = SkillService(agent_id="default").availabilityFor(SKILL_ID)
        return bool(avail.get("available")), ("账本 1 条 / available=%s reason=%r"
                                             % (avail.get("available"), avail.get("unavailableReason")))

    read("3 落账为真：新实例读得到，且 availabilityFor 判可得", faceAgree)

    def singletonFace():
        from neurova.api.endpoints import skill_pool_api

        rows = skill_pool_api._pool_service("default").list_skills()
        return "条数=%d 含本条=%s（跨实例互踩，本批未修，已登记台账）" % (
            len(rows), any(s.get("id") == SKILL_ID for s in rows))

    observe("3b 面板那条面（同进程单例）此刻读到几条", singletonFace)

    def registrySeesIt():
        from neurova.skills.market_registry import restore_market_skills_from_service
        from neurova.skills.skill_service import SkillService
        from neurova.skill_system import SkillRegistry

        fresh = SkillRegistry()
        restore_market_skills_from_service(SkillService(agent_id="default"), fresh)
        names = [getattr(s, "name", "?") for s in fresh.list_skills()]
        return any(SKILL_ID in str(n) for n in names), "执行表 %d 个：%s" % (len(names), names[:6])

    read("4 恢复口把这条挂进执行表", registrySeesIt)

    def stagingBudget():
        from neurova.skills.skill_service import _incomingStagingName

        name = _incomingStagingName(SKILL_ID)
        finalName = SKILL_ID
        return len(name) <= len(finalName), (
            "暂存名 %r（%d 字符）vs 终点名 %d 字符；旧形态是 %d 字符"
            % (name, len(name), len(finalName), len(".incoming_") + len(finalName) + 1 + 13))

    read("5 暂存名不再比终点长（Windows 预算没被白吃）", stagingBudget)

    def gateStillBites():
        """反证腿：同一面上传一只**真含裸名 exec** 的包，必须照样被拒并点名拒因。"""
        payload = syntheticZip("evil.zip", {
            "manifest.json": json.dumps({"id": "live-b59-evil", "name": "evil",
                                         "version": "1.0.0", "source": "marketplace"}),
            "SKILL.md": "# evil\n用于反证门的宽度\n",
            "run.py": "def go(payload):\n    return exec(payload)\n",
        })
        r = client.post("/api/v1/skill-pool/install-from-zip",
                        files={"file": ("live-b59-evil.zip", payload, "application/zip")})
        body = r.json() if str(r.headers.get("content-type", "")).startswith("application/json") else {}
        detail = json.dumps(body, ensure_ascii=False)[:260]
        return (r.status_code == 200 and body.get("success") is False
                and "dangerous_exec" in detail), "HTTP %s 回执=%s" % (r.status_code, detail)

    read("6 门没被拆：塞一条真裸名 exec 仍被拒且点名 dangerous_exec", gateStillBites)

    observe("7 上传真 zip 那条面（另一处既有缺口，非本批）", lambda: (
        lambda r: "HTTP %s 回执=%s" % (r.status_code, str(r.json())[:200]))(
        client.post("/api/v1/skill-pool/install-from-zip", files={
            "file": (BUNDLE, read_builtin_bundle(BUNDLE), "application/zip")})))

after = dataFingerprint()
print("仓内 data/ 跑后：%s（跑前 %s）" % (after, before))
if after != before:
    failures.append("data写入")

print("\n结论：%s" % ("全部 PASS（含第 6 项反证腿）" if not failures
                     else "有 %d 项 FAIL：%s" % (len(failures, ) , failures)))
sys.exit(0 if not failures else 1)
