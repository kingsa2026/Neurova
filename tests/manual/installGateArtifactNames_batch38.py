# -*- coding: utf-8 -*-
"""live-verify（工单 2026-10-13 批 38，§6-194）：安装门的名称级闸与代码后缀盲区。

判据档在 tmp 里造场景；这一支要在**真 HTTP 安装面 + 真盘账本 + 仓内真资产 zip**上读：

1. 包里塞 `.env` ⇒ 真 HTTP 面拒装，拒因点名凭据文件，agent 目录不留条目；
2. 包里塞 `bin/updater.exe` ⇒ 拒（真可执行产物）；
3. 包里塞 `scripts/payload.mjs`（内含 `eval(`）⇒ 拒——这条原是先盲区：37 个 .mjs 从不进扫描；
4. 只带无害资产（.png/.csv）的包 ⇒ 装上，但 `unscanned_file_count` 与 `unscanned_artifact`
   读数必须在（放行≠没看）；
5. 仓内真资产 zip 对账：已扫 + 未扫 == zip 内文件总数，一个文件都不许两头不计；
   且名称级规则对它零命中（第一方资产名不得被冤枉）；
6. 反向校准（反证）：把两张名称表桩成空集 ⇒ 那只 `.env` 包必须**变可装**，
   证明拒它的确实是这条闸，而不是别处的误拦；
7. 撤桩复证：同形状的另一只 `.env` 包必须重新被拒（不是桩件留下的假绿）；
8. 拒因走批 37 那张诚实回执：顶层 success=False，且点名 credential_artifact_name。

跑法：`PYTHONPATH=$(git rev-parse --show-toplevel) python tests/manual/installGateArtifactNames_batch38.py`
"""

from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402

WORK_ROOT = isolatedDataRoot(prefix="neurovaGateB38")

from fastapi.testclient import TestClient  # noqa: E402

from neurova.security import skill_scanner as SS  # noqa: E402
from neurova.skills.market_importer import read_builtin_bundle  # noqa: E402
from neurova.skills.skill_service import SkillService  # noqa: E402

failures: list[str] = []
BENIGN_MD = """---
name: live-b38
description: 演示
---

# 演示

按说明使用本技能即可。
"""
MJS_WITH_EVAL = "export function run(userInput) {\n    return eval(userInput);\n}\n"


def _manifest(sid: str) -> bytes:
    return ("{\"id\": \"%s\", \"name\": \"%s\", \"version\": \"1.0.0\"}" % (sid, sid)).encode()


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(name)


def _zip(entries: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, body in entries.items():
            zf.writestr(name, body if isinstance(body, bytes) else body.encode("utf-8"))
    return buf.getvalue()


def main() -> int:
    import os

    os.environ["NEUROVA_JWT_SECRET_KEY"] = "live_b38_secret_key_for_p0_fixes_0123"

    from neurova.api.app import create_app
    from neurova.api.deps import get_current_user
    from neurova.skills import skill_install_gate as GATE

    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": "live-b38", "username": "live-b38", "role": "admin", "neuser_id": "live-b38"}
    service = SkillService(agent_id="default")

    def install(sid: str, entries: dict):
        """每例一个新技能 id：同一 id 的第二次安装会被咽喉判成"重复"而短路在门之前
        （批 37 记下的方法学），拿它量门等于量缓存。"""
        raw = _zip(dict({"manifest.json": _manifest(sid)}, **entries))
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/api/v1/skill-pool/install-from-zip",
                               files={"file": (f"{sid}.zip", raw, "application/zip")},
                               data={"target": ""})
        body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        return resp, body, service.skills_dir / sid

    resp, body, entryDir = install("live-b38-env", {"SKILL.md": BENIGN_MD, ".env": "API_KEY=x\n"})
    check("[1] 包里塞 .env ⇒ 真 HTTP 面拒装（回执顶层 success=False）",
          body.get("success") is False, f"{resp.status_code} {str(body)[:160]}")
    check("[1b] 被拒的那次没在 agent 目录留下条目目录",
          not entryDir.exists(), str(entryDir))
    check("[1c] 拒因走诚实回执且点名凭据规则（不只 200 报成功）",
          "credential_artifact_name" in str(body.get("result", {})) or "凭据" in str(body),
          str(body)[:180])

    resp, body, _ = install("live-b38-exe",
                            {"SKILL.md": BENIGN_MD, "bin/updater.exe": b"MZ\x90\x00bin",
                             "lib/native.dll": b"MZ\x90\x00bin"})
    check("[2] 包里塞 .exe/.dll ⇒ 拒，拒因点名可执行产物",
          body.get("success") is False and "可执行产物" in str(body),
          f"{resp.status_code} {str(body)[:170]}")

    mjsDir = WORK_ROOT / "mjsPkg"
    (mjsDir / "scripts").mkdir(parents=True, exist_ok=True)
    (mjsDir / "SKILL.md").write_text(BENIGN_MD, encoding="utf-8")
    (mjsDir / "scripts" / "payload.mjs").write_text(MJS_WITH_EVAL, encoding="utf-8")
    directGate = GATE.scan_skill_for_install("live-b38-mjs-direct", str(mjsDir))
    check("[3] 危险字节写在 .mjs 里也拦得住（原盲区：这类后缀从不进扫描）",
          directGate.get("blocked") is True
          and any(f.get("rule_id") == "dangerous_exec" and str(f.get("file_path", "")).endswith(".mjs")
                  for f in directGate.get("findings") or []),
          f"blocked={directGate.get('blocked')} {str(directGate.get('error'))[:120]}")

    resp, body, _ = install("live-b38-mjs", {"SKILL.md": BENIGN_MD,
                                             "scripts/payload.mjs": MJS_WITH_EVAL})
    check("[3b] 同一只包经真 HTTP 安装面也被拒（门与回执同向）",
          body.get("success") is False, f"{str(body)[:170]}")

    resp, body, assetDir = install("live-b38-asset", {"SKILL.md": BENIGN_MD,
                                                      "assets/logo.png": b"\x89PNG\r\n\x1a\n",
                                                      "data/table.csv": "a,b\n1,2\n"})
    check("[4] 只带无害资产的包照常装上（未知后缀不参与 DENY）",
          resp.status_code == 200 and body.get("success") is True,
          f"{resp.status_code} {str(body)[:150]}")
    scanA = SS.SkillScanner().scan_skill("live-b38-asset-scan", str(assetDir),
                                         mode=SS.ScanMode.QUICK)
    unscanned = (scanA.metadata or {}).get("unscanned_file_count")
    check("[4b] 放行但留读数：未扫文件数与 unscanned_artifact 报告项都在",
          unscanned == 2 and "unscanned_artifact" in (scanA.metadata or {}).get("report_only_rules", []),
          f"unscanned={unscanned} report_only={sorted(set((scanA.metadata or {}).get('report_only_rules') or []))}")

    import neurova.security.safe_archive as SA

    studio = WORK_ROOT / "studio"
    studio.mkdir(parents=True, exist_ok=True)
    payload = read_builtin_bundle("adaptive-presentation-studio.zip")
    SA.safe_extract_zip(payload, studio)
    with zipfile.ZipFile(io.BytesIO(payload)) as z:
        total = sum(1 for i in z.infolist() if not i.is_dir())
    scanS = SS.SkillScanner().scan_skill("builtin--adaptive-presentation-studio-b38",
                                         str(studio), mode=SS.ScanMode.QUICK)
    nameHits = [f for f in scanS.findings
                if f.rule_id in ("credential_artifact_name", "executable_artifact")]
    check("[5] 真资产包对账：已扫+未扫 == 包内总数，且名称级规则零误伤",
          scanS.file_count + (scanS.metadata or {}).get("unscanned_file_count", -1) == total
          and not nameHits,
          f"已扫={scanS.file_count} 未扫={(scanS.metadata or {}).get('unscanned_file_count')} "
          f"总数={total} 名称级命中={len(nameHits)}")

    origCred, origExe = SS.CREDENTIAL_BASENAMES, SS.EXECUTABLE_SUFFIXES
    SS.CREDENTIAL_BASENAMES = frozenset()
    SS.EXECUTABLE_SUFFIXES = frozenset()
    try:
        GATE.reset_install_gate_scanner()
        resp, body, _ = install("live-b38-stub", {"SKILL.md": BENIGN_MD, ".env": "API_KEY=x\n"})
        check("[6] 反向校准：摘掉名称表 ⇒ 那只 .env 包必须变可装（闸确实在管事）",
              body.get("success") is True, f"{str(body)[:170]}")
    finally:
        SS.CREDENTIAL_BASENAMES = origCred
        SS.EXECUTABLE_SUFFIXES = origExe
        GATE.reset_install_gate_scanner()

    resp, body, _ = install("live-b38-retry", {"SKILL.md": BENIGN_MD, ".env": "API_KEY=x\n"})
    check("[7] 撤桩复证：同形状的另一只 .env 包重新被拒（不是桩件留下的假绿）",
          body.get("success") is False, f"{str(body)[:170]}")

    print(f"\n读数 11 项，失败 {len(failures)} 项: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
