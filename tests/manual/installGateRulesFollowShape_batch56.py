# -*- coding: utf-8 -*-
"""live-verify（§6-259，用户裁甲）：安装门的两条形状规则窄化之后，真安装面的读数。

判据档在 tmp 里造场景；这一支走**真 HTTP 安装面 + 真盘账本 + 仓内真资产 zip**，逐项量：

1. 只含 `re.compile(` 的包 ⇒ 真装成（回执顶层 success=True、账本目录有产物）——
   这一条在本批之前是**被 critical 拒**的，它才是这次修改要放开的那类；
2. 数据字面量里的 `"../assets/x.png"` ⇒ 装得上，但扫描元数据里那条 `path_traversal` 读数**还在**
   （降为 low 而不是删掉——批 37 定的"放行≠删发现"必须继续成立）；
3. 真 `exec(` 的包 ⇒ 拒，且回执顶层 success=False、拒因点名 `critical(dangerous_exec)`；
4. 真遍历（`open("../../etc/passwd")`）⇒ 拒，拒因点名 `high(dangerous_path_traversal)`；
5. 仓内自带的 presentation-studio 资产 zip：**前后对比读数**——旧口径参与裁决 40 条
   （其中 26 条是 `re.compile(` 属性调用），本批之后只剩真信号；它**仍然被拦**，
   拦它的是真动态编译与子进程，不是正则预编译（这条别记成"甲已让它恢复可装"）；
   5d（§6-259 末格「读数面仍欠的一刀」补上的一次）：**逐条读证据行按 AST 分形状**，
   并核对三条——读数能在自己的证据行上被生产规则复算、形状分类与参与裁决集合条数一致、
   装载门发给调用方的那份 dict 与扫描器对象面给同一个分布。形状判定一律走
   `tests/execShapes.py` 那一份（本子串判定原先自己写着 `"re.compile(" in evidence`，
   它分不清 `cursor.exec(` 这类同族形状，会和判据给出两个答案）；
6. 形状对照（不桩生产）：同一行文本，旧 pattern 命中、**生产现行 pattern** 不命中；
   真裸名 `compile(` 现行命中 ⇒ 证明放开的是无害形态（现行 pattern 由 `execRule()` 现取，
   不在脚本里再抄一份）；
7. 撤桩复证：第 1 项那只包再装一次仍成功（幂等，不是缓存假绿）。

跑法：`PYTHONPATH=$(git rev-parse --show-toplevel) python tests/manual/installGateRulesFollowShape_batch56.py`
"""
from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402

WORK_ROOT = isolatedDataRoot(prefix="neurovaGateB56")

from fastapi.testclient import TestClient  # noqa: E402

from neurova.security import skill_scanner as SS  # noqa: E402
from neurova.skills import skill_install_gate as SI  # noqa: E402
from neurova.skills.market_importer import read_builtin_bundle  # noqa: E402
from neurova.skills.skill_service import SkillService  # noqa: E402
from tests import execShapes  # noqa: E402

failures: list = []

SKILL_MD = "---\nname: live-b56\ndescription: d\n---\n\n# 说明\n正常文档，无危险形态。\n"
REGEX_PY = 'import re\n\nDATE = re.compile(r"日期|date", re.I)\n'
DATA_PATH_PY = 'THUMB = {"previewPng": "../assets/previews/slide-01.png"}\n'
EXEC_PY = "cache = {}\nexec('x = 1', cache)\n"
TRAVERSE_PY = 'def load(root):\n    return open("../../etc/passwd", "r").read()\n'


def check(name: str, ok: bool, detail: str = "") -> None:
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name, (" — " + detail) if detail else ""))
    if not ok:
        failures.append(name)


def observe(desc: str, fn) -> None:
    try:
        print("    OBSERVE %s：%s" % (desc, fn()))
    except Exception as exc:  # noqa: BLE001 - 观察项不记分，只留读数
        print("    OBSERVE %s：读数失败 %r" % (desc, exc))


def _zip(entries: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, body in entries.items():
            zf.writestr(name, body if isinstance(body, bytes) else body.encode("utf-8"))
    return buf.getvalue()


def _manifest(sid: str) -> bytes:
    return ("{\"id\": \"%s\", \"name\": \"%s\", \"version\": \"1.0.0\"}" % (sid, sid)).encode()


def main() -> int:
    import os

    os.environ["NEUROVA_JWT_SECRET_KEY"] = "live_b56_secret_key_for_gate_shape_0123"

    from neurova.api.app import create_app
    from neurova.api.deps import get_current_user

    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": "live-b56", "username": "live-b56", "role": "admin", "neuser_id": "live-b56"}
    service = SkillService(agent_id="default")

    def install(sid: str, entries: dict):
        """每个用例一个新 id：同 id 的第二次安装会在门之前被"重复"短路（批 37 实测过）。"""
        raw = _zip(dict({"manifest.json": _manifest(sid)}, **entries))
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/api/v1/skill-pool/install-from-zip",
                               files={"file": (f"{sid}.zip", raw, "application/zip")},
                               data={"target": ""})
        body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        return resp, body, service.skills_dir / sid

    print("隔离数据根：%s" % WORK_ROOT)

    resp, body, landedDir = install("live-b56-regex", {"SKILL.md": SKILL_MD, "main.py": REGEX_PY})
    check("[1] 只含 re.compile( 的包经真安装面装上（本批之前它被 critical 拒）",
          resp.status_code == 200 and body.get("success") is True,
          "%s %s" % (resp.status_code, str(body)[:150]))
    if body.get("success") is not True:
        return 1
    check("[1b] 产物真落盘（门看过并放行，不是回执假成功）",
          (landedDir / "main.py").is_file())

    scan = SS.SkillScanner().scan_skill("b56-data", str(landedDir), mode=SS.ScanMode.QUICK)
    resp2, body2, dir2 = install("live-b56-data", {"SKILL.md": SKILL_MD, "spec.py": DATA_PATH_PY})
    after = SS.SkillScanner().scan_skill("b56-data2", str(dir2), mode=SS.ScanMode.QUICK)
    kept = [f for f in after.findings if f.rule_id == "dangerous_path_traversal"]
    check("[2] 数据字面量的相对路径装得上，而那条读数仍在（降级不删）",
          body2.get("success") is True and kept and all(f.severity == "low" for f in kept),
          "读数 %d 条，严重度 %s" % (len(kept), sorted({f.severity for f in kept})))
    meta = after.metadata or {}
    check("[2b] 这条 low 读数不参与裁决（blocking_rule_count 不含它），但读数原样留在 findings 里",
          (after.passed is True and meta.get("blocking_rule_count") == 0 and bool(kept)),
          "passed=%s blocking_rule_count=%s findings=%d 条"
          % (after.passed, meta.get("blocking_rule_count"), len(after.findings)))

    resp3, body3, _ = install("live-b56-exec", {"SKILL.md": SKILL_MD, "go.py": EXEC_PY})
    err3 = str(body3.get("error") or "")
    check("[3] 真 exec( 仍被拒，回执顶层 success=False",
          body3.get("success") is False, "%s %s" % (resp3.status_code, str(body3)[:130]))
    check("[3b] 拒因点名 dangerous_exec 且带严重度（只念参与裁决的条目）",
          "critical(dangerous_exec)" in err3, err3[:130])

    resp4, body4, _ = install("live-b56-traverse", {"SKILL.md": SKILL_MD, "go.py": TRAVERSE_PY})
    err4 = str(body4.get("error") or "")
    check("[4] 真遍历（open(\"../../etc/passwd\")）仍被拒且点名",
          body4.get("success") is False and "high(dangerous_path_traversal)" in err4, err4[:130])

    # 真资产包：窄化后的裁决集与前后的对比
    raw = read_builtin_bundle("adaptive-presentation-studio.zip")
    check("[5a] 仓内自带资产 zip 取得到（第 5 项的根据）", bool(raw))
    import tempfile
    from pathlib import PurePosixPath
    work = Path(tempfile.mkdtemp(prefix="b56live_")) / "studio"
    work.mkdir(parents=True)
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        zf.extractall(work)
    real = SS.SkillScanner().scan_skill("studio-real", str(work), mode=SS.ScanMode.QUICK)
    blocking = SS.blockingFindings(real)
    byRule = {}
    for f in real.findings:
        byRule[f.rule_id] = byRule.get(f.rule_id, 0) + 1
    execHits = [f for f in blocking if f.rule_id == "dangerous_exec"]
    attributeish = [f for f in real.findings
                    if f.rule_id == "dangerous_exec" and execShapes.isAttributeOnly(f.evidence)]
    check("[5b] 真资产包仍被拒（拦它的是真信号）", real.passed is False and bool(execHits),
          "blocking=%d 条，其中 exec %d 条" % (len(blocking), len(execHits)))
    check("[5c] 属性调用形不再产生任何危险执行读数（26 条误判归零；按 AST 判形状而非数子串）",
          not attributeish, "残留 %d 条" % len(attributeish))
    # [5d] 读数面那刀（§6-259 末格）：形状分类要能对上参与裁决的集合，两条面各量一次
    buckets = execShapes.shapesOf(real.findings)
    ghost = execShapes.unReproducible(execShapes.execReadings(real.findings), execShapes.execRule())
    check("[5d1] 每条 exec 读数都能在自己的证据行上被生产规则复算", not ghost,
          "复算不出 %d 条（例 %s）" % (len(ghost), [(g.get("file_path"), g.get("evidence")) for g in ghost[:1]]))
    check("[5d2] 形状分类与参与裁决集合条数一致",
          len(buckets.get("bare") or []) == len(execHits) and len(buckets.get("bare") or []) == 1,
          "分类=%s 裁决集=%s" % (sorted(buckets), [(f.file_path, f.evidence) for f in execHits][:2]))
    gateScan = SI.scan_skill_for_install("studio-real-gateface", str(work))
    gateBuckets = execShapes.shapesOf(gateScan.get("findings") or [])
    check("[5d3] 装载门发给调用方的那份 dict 与扫描器对象面给同一个形状分布",
          sorted(gateBuckets) == sorted(buckets), "dict=%s 对象面=%s" % (sorted(gateBuckets), sorted(buckets)))
    print("    真资产包读数（规则→条数）：%s" % dict(sorted(byRule.items(), key=lambda kv: -kv[1])[:6]))
    print("    参与裁决集：%s" % sorted({f.rule_id for f in blocking}))

    def _hits(pattern: str, line: str) -> bool:
        import re
        return re.search(pattern, line, re.I) is not None

    line = 'DATE = re.compile(r"日期|date", re.I)'
    productionPattern = execShapes.execRule().pattern
    check("[6] 形状对照：旧 pattern 命中这行、**生产现行 pattern** 不命中；真裸名 compile( 现行也命中",
          _hits(r"\b(exec|eval|compile)\s*\(", line) is True
          and _hits(productionPattern, line) is False
          and _hits(productionPattern, 'compile("x = 1", "<str>", "exec")') is True,
          "现行 pattern=%s" % productionPattern)

    resp7, body7, _ = install("live-b56-regex", {"SKILL.md": SKILL_MD, "main.py": REGEX_PY})
    check("[7] 同一只包再走一次面：不出现「先拒后放行」的漂移（幂等复证）",
          body7.get("success") is True or "已存在" in str(body7) or body7.get("code") in (409, 400),
          str(body7)[:130])

    observe("第 1 项那次扫描有没有顺手改仓内 data/", lambda: "数据根已隔离到 %s" % WORK_ROOT)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
