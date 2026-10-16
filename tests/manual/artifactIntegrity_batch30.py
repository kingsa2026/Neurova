# -*- coding: utf-8 -*-
"""live-verify（工单 2026-10-13 批 30，§6-172 / P3 技能半区）：钉下的摘要真能在 HTTP 装上后拦住换包。

判据档（`tests/unit/skills/test_artifactIntegrityAtInstallAndLoad.py`）直接构造 `SkillService`；
这一支要证的是另一件事——**从 HTTP 安装面进来的那份字节**，账本里落的是不是它、
exec 之前对的是不是同一本账：

1. 真 `create_app()` + 真 `POST /api/v1/skill-pool/install-from-zip`（zip 是当场造的）；
2. 读**磁盘上的 manifest.json**（不是内存字典）——摘要必须真落了账；
3. 摘要等于「zip 里那份原始字节」的聚合值：证明钉的是取回来的那份，不是落盘后被谁动过的；
4. 照常执行 ⇒ 通过（钉与验不许把正常件焊死）；
5. 篡改盘上 main.py 一个字节 ⇒ 执行被**结构化拒因**挡下（`artifact_digest_mismatch`）；
6. 反向校准：把账本里的摘要抹掉 ⇒ 首钉放行（TOFU），否则第 5 项可能只是"永远拒"的假绿。

跑法：`PYTHONPATH=$(git rev-parse --show-toplevel) python tests/manual/artifactIntegrity_batch30.py`
"""

from __future__ import annotations

import io
import asyncio
import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402

WORK_ROOT = isolatedDataRoot(prefix="neurovaArtifactB30")

from fastapi.testclient import TestClient  # noqa: E402

from neurova.security import artifact_digest as AD  # noqa: E402
from neurova.skills.skill_service import SkillService  # noqa: E402

failures: list[str] = []
CLEAN_BODY = "def main(**kwargs):\n    return {'ok': True}\n"
CLEAN_MANIFEST = json.dumps({"id": "live-b30", "name": "live-b30", "version": "1.0.0"})
CLEAN_MD = "# helper\n\n把日期格式化为 ISO 标准格式的技能说明。\n"


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(name)


def _zipBytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", CLEAN_MANIFEST)
        zf.writestr("SKILL.md", CLEAN_MD)
        zf.writestr("main.py", CLEAN_BODY)
    return buf.getvalue()


def _digestOfZipBytes(raw: bytes) -> str:
    """把 zip 里那份字节解到临时目录后，交回**生产那个取法函数**折一遍。

    不在这里手写折叠逻辑：复刻被审那一行的话，两边一起错也会对上，红就退化成无效红
    （本卷记过的桩件替坏契约背书同族）。排除清单因此只由 `artifact_digest` 一处决定。
    """
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            zf.extractall(str(root))
        return AD.digestDir(root)


def main() -> int:
    print(f"数据根（注入隔离）: {WORK_ROOT}")

    from neurova.api.app import create_app
    from neurova.api.deps import get_current_user as depsUser

    app = create_app(enable_memory=False, enable_channels=False)
    # 鉴权替身打在 `api.deps.get_current_user` 上：`skill_pool_api.py:37` 引的是**这一个**。
    # 仓里有两份同名不同体的 get_current_user（auth 与 deps），override 打错对象会
    # **静默失效**得到 401——那会被读成"安装面坏了"，其实是探针没接上（本卷记过那形）。
    app.dependency_overrides[depsUser] = lambda: {
        "user_id": "u-live-30", "username": "u-live-30", "role": "admin"}
    try:
        raw = _zipBytes()
        expected = _digestOfZipBytes(raw)
        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/skill-pool/install-from-zip",
                files={"file": ("live-b30.zip", raw, "application/zip")},
                data={"target": ""},
            )
            check("[1] 真 HTTP 安装面装上并回执成功", resp.status_code == 200,
                  f"{resp.status_code} {resp.text[:180]}")
            if resp.status_code != 200:
                return 1

            service = SkillService(agent_id="default")
            manifestFile = Path(service.skills_dir) / "manifest.json"
            check("[2] manifest.json 真在盘上", manifestFile.exists(), str(manifestFile))
            ledger = json.loads(manifestFile.read_text(encoding="utf-8"))
            entry = ledger.get("live-b30") or {}
            pinned = str(entry.get(AD.DIGEST_FIELD) or "")
            check("[3] 账本里落了构件摘要（读磁盘不是读内存）",
                  pinned.startswith(AD.DIGEST_PREFIX), pinned[:24] or "(缺)")
            check("[4] 钉的就是 zip 里那份字节", pinned == expected,
                  f"钉={pinned[:20]}… zip 折={expected[:20]}…")

            first = asyncio.run(service.call_skill("live-b30"))
            check("[5] 没动过 ⇒ 照常执行", first.get("success") is True, str(first)[:160])

            installed = Path(str(entry.get("path") or ""))
            (installed / "main.py").write_text(
                "def main(**kwargs):\n    return {'stolen': True}\n", encoding="utf-8")
            second = asyncio.run(service.call_skill("live-b30"))
            check("[6] 盘上被换一个字节 ⇒ 装载前结构化拒绝",
                  second.get("success") is not True
                  and second.get("error") == AD.REASON_MISMATCH,
                  str(second)[:200])
            check("[7] 拒因带两边读数（可归因，不是一句话）",
                  str(second.get("expected_digest") or "").startswith(AD.DIGEST_PREFIX)
                  and str(second.get("actual_digest") or "").startswith(AD.DIGEST_PREFIX),
                  f"expected={str(second.get('expected_digest'))[:18]}… "
                  f"actual={str(second.get('actual_digest'))[:18]}…")

            # 反向校准：抹掉摘要必须退回"首钉放行"，否则上面两格可能只是"永远拒"
            ledger["live-b30"][AD.DIGEST_FIELD] = ""
            manifestFile.write_text(json.dumps(ledger), encoding="utf-8")
            reloaded = SkillService(agent_id="default")
            third = asyncio.run(reloaded.call_skill("live-b30"))
            check("[8] 反照：抹掉摘要后是 TOFU 首钉放行，不是拒绝",
                  third.get("success") is True, str(third)[:160])
            relatched = str(json.loads(manifestFile.read_text(encoding="utf-8"))
                            ["live-b30"].get(AD.DIGEST_FIELD) or "")
            check("[9] 首钉落账且等于当前盘上字节（篡改后的那份）",
                  relatched == AD.digestDir(installed) and relatched != pinned,
                  relatched[:24] or "(没落账)")
    finally:
        app.dependency_overrides.clear()

    print("\nLIVE-VERIFY PASSED / 工单 2026-10-13 批 30（P3 构件完整性·技能半区）"
          if not failures else f"\nLIVE-VERIFY FAILED：{failures}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
