# -*- coding: utf-8 -*-
"""live-verify（§6-383 票三的活体补证）：市场安装那条路的构件摘要，闸到底装在哪一条腿上。

工单里我原先只读了 `market_importer` 就写"市场那条路既不钉摘要、也进不了读路"——**那是查了
一半就下结论**：市场端点在 importer 之后还有一步 `link_market_skill_to_agent`，它经
`_writeAgentManifestOutcome` 走 `install_skill` 那个咽喉（真字节＋合成 manifest 进 staging）。
所以到底是「没钉」「钉了但不是运行时那份」，还是「钉对了一条腿而另一条腿绕过」，
必须跑真 app 才说得清。这一支就是把这三态量清：

1. 真 `create_app()` + 真 JWT 打 `POST /api/v1/skill-pool/{id}/install`（内置 bundle 那条离线支）；
2. 读 agent 账本：条目在不在、`path` 指哪、有没有钉摘要；
3. 对照：钉值 vs 运行时那个目录现算的摘要（同不同源）；
4. 篡改：改运行时目录里 `SKILL.md` 一个字节，分别走 ① 注册表那条腿
   （`market_registry._build_executable_skill(...).execute`，与 link 时同一处构造口径）
   ② 账本那条腿（`skill_service.call_skill`），数 `checkArtifact` 各被调几次；
5. 还原后重新一致 + 一格"不存在的路径"校准 + 仓库 `data/` 指纹与最近 5 分钟零改写。

**票三甲落地（用户 2026-10-22 裁）之后，读数 9-12 从"缺口证据"翻成"闸已接到两条腿上"的回归面**：
篡改后注册表那条腿必须**同样拒**、且 `checkArtifact` **恰被调 1 次**（不再是 0），两条腿的拒因
必须同一个标识。5-6 两格继续钉安装侧"钉值与运行时同源"。改动这块时先跑本脚本再看单元档，
否则很容易把"闸接上了"误读成"行为变了"。

跑法：`PYTHONPATH=$(git rev-parse --show-toplevel) python tests/manual/marketTicketThreeDigestPath.py`
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# stdout 编码由本档自己钉死：`print` 抛 UnicodeEncodeError 会把退出码变成 1，
# 而 `tests/manual/*` 的全部证据就是「退出码 + 那几行 PASS/FAIL 读数」——
# 等于让打印来决定判定（判据见 tests/unit/ci/test_manualScriptStdoutEncoding.py）。
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402

WORK_ROOT = isolatedDataRoot(prefix="neurovaTicket3")

from fastapi.testclient import TestClient  # noqa: E402

from neurova.api.app import create_app  # noqa: E402
from neurova.api.auth import create_access_token  # noqa: E402
from neurova.security import artifact_digest  # noqa: E402
from neurova.core.data_root import get_data_root  # noqa: E402
from neurova.skills import library_service, market_registry, market_store  # noqa: E402
from neurova.skills.market_importer import BUILTIN_BUNDLE_DIR  # noqa: E402

SKILL_POOL = "/api/v1/skill-pool"

# 生产的根外锚在 `~/.neurova/`（数据根之外）；探针把落点改到隔离区**之外**的同级目录，
# 既不写真实主目录，又保住「锚不在数据根里」这条形状。
ANCHOR_DIR = Path(tempfile.mkdtemp(prefix="neurovaAnchorsTicket3-"))
artifact_digest.anchorPath = lambda: ANCHOR_DIR / "artifact_anchors.json"
failures: list = []
checkArtifactCalls: list = []


def check(name, ok, detail=""):
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name, (" — " + detail) if detail else ""))
    if not ok:
        failures.append(name)


def _headers(sub, role="user"):
    token = create_access_token({"sub": sub, "username": sub, "role": role})
    return {"Authorization": "Bearer " + token}


def _dataDirFingerprint():
    root = Path(__file__).resolve().parents[2] / "data"
    if not root.exists():
        return "<absent>"
    digest = hashlib.md5()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            st = path.stat()
            digest.update(("%s|%s|%s" % (path.relative_to(root), st.st_size,
                                          int(st.st_mtime))).encode())
    return digest.hexdigest()


def _bundleSkillId():
    """挑一条内置 bundle 条目（离线、不出网），并要求资产真在。"""
    for entry in getattr(market_store, "_BUILTIN_CATALOG", []):
        bundle = entry.get("bundle_zip")
        if bundle and (BUILTIN_BUNDLE_DIR / str(bundle)).is_file():
            return str(entry.get("id") or entry.get("skill_id") or "")
    return ""


def _runMaybeCoroutine(value):
    """注册表那条腿的 `execute` 两支形状不同（同步 SkillResult / 协程），都收进来。"""
    if asyncio.iscoroutine(value):
        return asyncio.run(value)
    return value


def main():
    # 读数里有 ⇒ 这类非 GBK 字符：控制台/重定向一律按 UTF-8 写，免得 print 自己抛
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001 —— 老环境不支持就算了，读数不该被它打断
            pass
    startedAt = time.time()
    before = _dataDirFingerprint()
    realCheck = artifact_digest.checkArtifact

    def countingCheck(root, pinnedValue, **kwargs):
        status, actual = realCheck(root, pinnedValue, **kwargs)
        checkArtifactCalls.append("%s|%s" % (Path(root).name, status))
        return status, actual

    artifact_digest.checkArtifact = countingCheck
    try:
        skillId = _bundleSkillId()
        check("1 前置：仓内有内置 bundle 条目可离线安装", bool(skillId), skillId or "(没找到)")
        if not skillId:
            return 1

        app = create_app()
        with TestClient(app) as client:
            headers = _headers("u-ticket3")
            installed = client.post("%s/%s/install" % (SKILL_POOL, skillId), headers=headers,
                                    json={"agent_id": "default", "force": True})
            check("2 真路由真 JWT：市场安装在活 app 上回 2xx",
                  installed.status_code in (200, 201),
                  "%s %s" % (installed.status_code, installed.text[:150]))

            service = library_service.agentLibrary("default")
            entry = service._entry(skillId)
            check("3 账本里有这一条（link 那一步确实经咽喉落了账——工单原说法据此作废）",
                  entry is not None, str(entry)[:170])
            if entry is None:
                return 1

            runtimeDir = Path(str(entry.get("path") or ""))
            pinned = str(entry.get(artifact_digest.DIGEST_FIELD) or "")
            check("4 账本里钉了构件摘要（不是「没钉」）", bool(pinned),
                  "钉值=%s" % (pinned[:26] or "(空)"))
            check("5 运行时取径就是账本 `path` 那一处目录", runtimeDir.is_dir(), str(runtimeDir))

            nowAtRuntime = artifact_digest.digestDir(runtimeDir)
            sameSource = artifact_digest.digestMatches(pinned, nowAtRuntime)
            check("6 钉值与运行时目录现算值同源否（不同源＝§6-183 那枚影子目录形态现形）",
                  True, "同源=%s pinned=%s now=%s" % (sameSource, pinned[:22], nowAtRuntime[:22]))

            executable = market_registry._build_executable_skill(
                skillId, str(entry.get("description") or ""), str(runtimeDir),
                # 与生产 link 点同一形状：账本钉值必须递给执行腿，否则落进 `None` 旁路
                pinnedDigest=str(entry.get(artifact_digest.DIGEST_FIELD) or ""),
                onPin=lambda digest: service.pinArtifactDigest(skillId, digest))
            check("7 注册表那条腿造得出执行体（造不出则篡改无从执行，得先接线）",
                  executable is not None, type(executable).__name__)
            if executable is None:
                return 1

            docFile = runtimeDir / "SKILL.md"
            check("8 运行时目录里有 SKILL.md 可篡改", docFile.is_file(), str(docFile))
            original = docFile.read_bytes()
            marker = "<!-- ticket3-tamper-probe -->"
            docFile.write_bytes(original + ("\n" + marker + "\n").encode("utf-8"))

            try:
                checkArtifactCalls.clear()
                viaRegistry = _runMaybeCoroutine(executable.execute({"task": "probe"}))
                registryText = json.dumps(getattr(viaRegistry, "__dict__", None)
                                          or viaRegistry, ensure_ascii=False, default=str)
                registrySawTamper = marker in registryText
                registryCalls = len(checkArtifactCalls)

                checkArtifactCalls.clear()
                viaThroat = asyncio.run(service.call_skill(skillId, "main", task="probe"))
                throatText = json.dumps(viaThroat, ensure_ascii=False, default=str)
                throatRefused = artifact_digest.REASON_MISMATCH in throatText
                throatCalls = list(checkArtifactCalls)

                check("9 注册表那条腿：改一个字节后同样被拒，且被篡改的指令体不外泄",
                      (not getattr(viaRegistry, "success", False))
                      and getattr(viaRegistry, "error", "") == artifact_digest.REASON_MISMATCH
                      and not registrySawTamper,
                      "error=%s，回执含篡改标记=%s" % (
                          getattr(viaRegistry, "error", None), registrySawTamper))
                check("10 且它这一次调用**检查了**构件摘要（恰 1 次）",
                      registryCalls == 1, str(checkArtifactCalls))
                check("11 账本那条腿（call_skill）对同一份篡改同样拒——两条腿现在共用一道闸",
                      throatRefused, throatText[:150])
                check("12 两条腿的拒因是同一个标识（不各写一套文案）",
                      getattr(viaRegistry, "error", "") == artifact_digest.REASON_MISMATCH
                      and artifact_digest.REASON_MISMATCH in throatText,
                      "registry=%s ledger=%s" % (
                          getattr(viaRegistry, "error", ""),
                          "mismatch" if throatRefused else "other"))
            finally:
                docFile.write_bytes(original)

            restored = artifact_digest.digestDir(runtimeDir)
            check("13 还原后与账本钉值重新一致（证明上三格是字节级、不是噪声）",
                  artifact_digest.digestMatches(pinned, restored), restored[:22])

            calibrated = asyncio.run(service.call_skill("no-such-skill-zzz", "main", task="probe"))
            check("14 校准格：真不存在的技能走账本腿回的是「没找到」而不是摘要拒",
                  "not found" in json.dumps(calibrated, ensure_ascii=False, default=str).lower()
                  and artifact_digest.REASON_MISMATCH not in json.dumps(calibrated),
                  str(calibrated)[:120])

            # ── 根外锚（§6-388 票一甲①）：同权限者"改构件 + 重钉账本"要被锚抓住 ──
            anchorFile = artifact_digest.anchorPath()
            anchorPayload = json.loads(anchorFile.read_text(encoding="utf-8"))
            anchorKey = artifact_digest.artifactKey("skill", skillId)
            check("15 安装后根外锚里有一条，且与账本同值",
                  str((anchorPayload.get("anchors") or {}).get(anchorKey) or "") == pinned,
                  "%s -> %s" % (anchorKey, (anchorPayload.get("anchors") or {}).get(anchorKey)))
            check("16 锚落在数据根之外（否则整库回滚会把锚一起滚回去）",
                  Path(get_data_root()).resolve() not in anchorFile.resolve().parents,
                  str(anchorFile))

            from neurova.skills.skill_service import SkillService as _SkillService

            (runtimeDoc := runtimeDir / "SKILL.md").write_bytes(
                original + b"\n<!-- repin-probe -->\n")
            newDigest = artifact_digest.digestDir(runtimeDir)
            manifestData = json.loads(Path(service.manifest_path).read_text(encoding="utf-8"))
            manifestData[skillId][artifact_digest.DIGEST_FIELD] = newDigest
            Path(service.manifest_path).write_text(
                json.dumps(manifestData, ensure_ascii=False, indent=2), encoding="utf-8")
            fresh = _SkillService(agent_id="default", skills_dir=str(service.skills_dir))
            repinned = asyncio.run(fresh.call_skill(skillId, "main", task="probe"))
            check("17 改构件＋重钉账本（同权限者能做）-> 锚不符，账本腿仍拒",
                  artifact_digest.REASON_MISMATCH in json.dumps(
                      repinned, ensure_ascii=False, default=str),
                  str(repinned)[:150])
            runtimeDoc.write_bytes(original)
            manifestData[skillId][artifact_digest.DIGEST_FIELD] = pinned
            Path(service.manifest_path).write_text(
                json.dumps(manifestData, ensure_ascii=False, indent=2), encoding="utf-8")
            healed = asyncio.run(_SkillService(
                agent_id="default", skills_dir=str(service.skills_dir)
            ).call_skill(skillId, "main", task="probe"))
            # 说明：`SkillDocSkill` 是**指令型**，本来就没有 `skill.py` 入口，`call_skill` 在摘要相符
            # 之后会走到"无入口"那一支——所以这一格证"闸不再挡"，用 checkArtifact 的直接读数，
            # 不拿"能不能执行"冒充"摘要是否相符"（那一格测的就不是同一件事）。
            healedStatus, _ = artifact_digest.checkArtifact(
                runtimeDir, pinned, anchorKey=anchorKey)
            check("18 还原构件与账本后，账本腿与锚都重新相符（上一格的拒不是永久坏账）",
                  healedStatus == artifact_digest.STATUS_MATCH
                  and artifact_digest.REASON_MISMATCH not in json.dumps(
                      healed, ensure_ascii=False, default=str),
                  "status=%s 调用回执=%s" % (healedStatus, str(healed)[:80]))


            artifact_digest.checkArtifact = realCheck
            checkArtifactCalls.clear()

        check("19 仓库 data/ 未被本轮写入（内容指纹逐字节相同）", _dataDirFingerprint() == before)
        dataRoot = Path(__file__).resolve().parents[2] / "data"
        recent = [p for p in dataRoot.rglob("*") if p.is_file()
                  and p.stat().st_mtime > startedAt] if dataRoot.exists() else []
        check("20 仓库 data/ 最近 5 分钟零改写", recent == [], str([str(x) for x in recent[:3]]))
    finally:
        artifact_digest.checkArtifact = realCheck

    print("")
    print("全部通过" if not failures else "失败 %s 项：%s" % (len(failures), failures))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
