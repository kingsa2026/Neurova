# -*- coding: utf-8 -*-
r"""live-verify（"假可得"的写侧半区）：调用一只**空壳**技能条目，账本不许多出一份构件摘要。

真物取证（现读，不抄旧账）：本机 `data/agents/default/skills/manifest.json` 里
`builtin--adaptive-presentation-studio` 是 `enabled: true`，而它的落盘目录里只有 `manifest.json`（0 个 .py）。
今天的 `install_skill` 造不出这一形（门拦下即删 `.incoming`、不建 `target_dir`），它是 2026-10-06 旧代码留下的
陈态——但**每次调用都再污染一次**是活的：`call_skill` 里摘要对账排在入口判定之前，未钉分支"现算现钉并放行"，
于是先把空壳摘要落进账本，下一行才报 `No entry point found`。那份读数不代表任何构件；日后真把字节补进
那个目录，反被它判成**篡改**——一次误点就把"以后装上了"这条路钉死。

本档全程落在**隔离数据根的副本**上，仓内 `data/` 只读；收尾复证指纹未变。
HEAD 对照腿（同一份脚本、不含本批修复）的跑法：在仓外 worktree 里跑本文件，并把
`NEUROVA_LIVE_SOURCE_DATA` 指到主树的 `data/`——期望第 [4]/[5] 两项 FAIL，且失败就红在"账本被改写"这条读数上。
"""
from __future__ import annotations

import hashlib
import asyncio
import json
import os
import shutil
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402

SKILL_ID = "builtin--adaptive-presentation-studio"
AGENT_ID = "default"
LEDGER = "manifest.json"
SKILLS_SUB = Path("agents") / AGENT_ID / "skills"
CONTROL_ID = "control-b57"

failures = []


def read(what, probe):
    """计分读数：炸了也算失败（"没跑成"不等于"全绿"）。"""
    try:
        ok, detail = probe()
    except Exception as exc:  # noqa: BLE001
        ok, detail = False, "探针异常 %r" % (exc,)
    print("[%s] %s — %s" % ("PASS" if ok else "FAIL", what, detail))
    if not ok:
        failures.append(what[:4])


def observe(what, probe):
    try:
        print("    OBSERVE %s：%s" % (what, probe()))
    except Exception as exc:  # noqa: BLE001
        print("    OBSERVE %s：读数失败 %r" % (what, exc))


def sha16(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def dataFingerprint():
    """仓内真 data/ 的**内容**指纹（不是文件清单——清单看不见原地改写）。"""
    root = REPO / "data"
    if not root.exists():  # 仓外对照腿里根本没有 data/（它被 gitignore）
        return (0, "无 data 目录")
    files = sorted(p for p in root.rglob("*") if p.is_file())
    digest = hashlib.sha256("\n".join(
        "%s:%s" % (p.relative_to(root).as_posix(), p.stat().st_size) for p in files)
        .encode("utf-8")).hexdigest()[:12]
    return (len(files), digest)


def seedIsolated(root):
    """把真账本与真落盘目录逐字节复制进隔离根（源侧只读）。返回 (账本路径, 条目目录)。"""
    srcSkills = SRC_DATA / SKILLS_SUB
    srcLedger = srcSkills / LEDGER
    if not srcLedger.exists():
        raise RuntimeError("源账本不在：%s" % srcLedger)
    row = json.loads(srcLedger.read_text(encoding="utf-8")).get(SKILL_ID)
    if not row:
        raise RuntimeError("源账本里没有这只空壳：%s（本档的根据就没了）" % SKILL_ID)
    dstSkills = root / SKILLS_SUB
    dstSkills.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(str(srcLedger), str(dstSkills / LEDGER))
    srcDir = srcSkills / SKILL_ID
    if srcDir.is_dir():
        shutil.copytree(str(srcDir), str(dstSkills / SKILL_ID), dirs_exist_ok=True)
    # 账本里的 `path` 是**绝对路径**，照抄会让副本读到真目录（第 [6] 项就此走成
    # "仍然没入口"那条支路，看着绿其实没咬到"补上字节"这一腿）。把这一条的落点改指副本。
    ledger = json.loads((dstSkills / LEDGER).read_text(encoding="utf-8"))
    ledger[SKILL_ID]["path"] = str(dstSkills / SKILL_ID)
    (dstSkills / LEDGER).write_text(json.dumps(ledger, ensure_ascii=False), encoding="utf-8")
    return dstSkills / LEDGER, dstSkills / SKILL_ID


def shellErrorText(svc):
    return str((asyncio.run(svc.call_skill(SKILL_ID)) or {}).get("error") or "")


def replenishThenCall(ledgerPath, entryDir):
    """模拟"日后真把字节补进这个目录"：从内置包里取一个真 .py 写成入口，再走同一咽喉。

    判的是本批要保的那条路：旧形态会把空壳摘要钉进账本，这一步就会被判**摘要不符**；
    修后这一步只该做一次正常首钉，拒因里不许出现完整性/篡改字样。
    """
    bundle = REPO / "neurova" / "skills" / "market_bundles" / "adaptive-presentation-studio.zip"
    if not bundle.exists():
        raise AssertionError("内置包不在，本格没有根据：%s" % bundle)
    with zipfile.ZipFile(bundle) as zf:
        members = [m for m in zf.namelist()
                   if m.endswith(".py") and not m.endswith("__init__.py")]
        if not members:
            raise AssertionError("包里没有可执行 .py")
        victim = members[0]
        (entryDir / "main.py").write_bytes(zf.read(victim))
    before = json.loads(ledgerPath.read_text(encoding="utf-8"))[SKILL_ID]
    fresh = SkillService(agent_id=AGENT_ID, skills_dir=str(entryDir.parent))
    res = asyncio.run(fresh.call_skill(SKILL_ID))
    refused = str(res.get("error") or "")
    after = json.loads(ledgerPath.read_text(encoding="utf-8"))[SKILL_ID]
    tamperish = any(word in refused.lower() for word in ("mismatch", "digest", "tamper")) or \
        ("不符" in refused or "篡改" in refused)
    return (not tamperish), ("补的入口＝%s；此前有无摘要＝%s；回执拒因＝%r；此后已首钉＝%s"
                             % (victim, bool(before.get(AD.DIGEST_FIELD)),
                                refused[:60] or "(无拒因)", bool(after.get(AD.DIGEST_FIELD))))


def controlRealSkillPinsOnce(root):
    """对照腿：有可执行构件的未钉条目必须**仍**首钉一次并落账（TOFU 那条腿不许被改断）。"""
    skills = root / SKILLS_SUB
    src = root / "ctrlsrc" / CONTROL_ID
    src.mkdir(parents=True, exist_ok=True)
    (src / "manifest.json").write_text(
        json.dumps({"id": CONTROL_ID, "name": CONTROL_ID, "version": "1.0.0"}), encoding="utf-8")
    (src / "SKILL.md").write_text("# ctrl\n对照件。\n", encoding="utf-8")
    (src / "main.py").write_text("def main(**kwargs):\n    return {'ok': True}\n", encoding="utf-8")
    installer = SkillService(agent_id=AGENT_ID, skills_dir=str(skills))
    if not installer.install_skill(str(src)).get("success"):
        raise AssertionError("对照件装不上，这一格不成立")
    ledgerPath = skills / LEDGER
    row = json.loads(ledgerPath.read_text(encoding="utf-8"))
    row[CONTROL_ID].pop(AD.DIGEST_FIELD, None)
    ledgerPath.write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")

    reopened = SkillService(agent_id=AGENT_ID, skills_dir=str(skills))
    res = asyncio.run(reopened.call_skill(CONTROL_ID))
    after = json.loads(ledgerPath.read_text(encoding="utf-8"))[CONTROL_ID]
    return (bool(after.get(AD.DIGEST_FIELD)) and bool(res.get("success"))), (
        "回执 success=%s，首钉已落账＝%s" % (res.get("success"), bool(after.get(AD.DIGEST_FIELD))))


ROOT = isolatedDataRoot(prefix="neurovaShellB57")
SRC_DATA = Path(os.environ.get("NEUROVA_LIVE_SOURCE_DATA") or (REPO / "data"))
print("隔离数据根：%s（源：%s）" % (ROOT, SRC_DATA))

from neurova.security import artifact_digest as AD  # noqa: E402
from neurova.skills.skill_service import SkillService  # noqa: E402

startFp = dataFingerprint()

try:
    LEDGER_PATH, ENTRY_DIR = seedIsolated(ROOT)
except Exception as exc:  # noqa: BLE001
    # exc 在 except 块退出时即被删除，lambda 迟绑定会在那时取到未定义名——先收成实参
    read("[0] 隔离根取真账本副本", lambda _exc=exc: (False, repr(_exc)))
    LEDGER_PATH = ENTRY_DIR = None

if LEDGER_PATH:
    ledger0 = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    row0 = ledger0[SKILL_ID]
    sha0 = sha16(LEDGER_PATH)
    svc = SkillService(agent_id=AGENT_ID, skills_dir=str(ENTRY_DIR.parent))

    read("[1] 真形复现：条目在册且落盘无可执行构件", lambda: (
        (not list(ENTRY_DIR.glob("*.py"))) and bool(row0.get("enabled")),
        "目录内容 %s；账本 enabled=%s" % (
            sorted(p.name for p in ENTRY_DIR.iterdir()), row0.get("enabled"))))

    read("[2] 这条账目没有构件摘要那一格（＝存量形，首钉分支可达）", lambda: (
        AD.DIGEST_FIELD not in row0, "键集 %s" % sorted(row0)))

    observe("读面仍把它画成可用（这一半属产品语义，本批不动，留读数供裁定）", lambda: {
        "get_skill_info.enabled": (svc.get_skill_info(SKILL_ID) or {}).get("enabled"),
        "list_skills 里在否": any(s.get("id") == SKILL_ID for s in svc.list_skills())})

    read("[3] 真咽喉如实拒（不静默成功）", lambda: (
        "No entry point" in shellErrorText(svc), shellErrorText(svc)[:60]))

    read("[4] 本批核心读数：拒归拒，账本一个字节都不许多", lambda: (
        sha16(LEDGER_PATH) == sha0, "sha %s → %s" % (sha0, sha16(LEDGER_PATH))))

    read("[5] 连调三次仍不落账（旧形态是每次调用写一遍）", lambda: (
        all("No entry point" in shellErrorText(svc) for _ in range(3))
        and sha16(LEDGER_PATH) == sha0,
        "sha %s；该条键集 %s" % (sha16(LEDGER_PATH), sorted(
            json.loads(LEDGER_PATH.read_text(encoding="utf-8"))[SKILL_ID]))))

    read("[6] 日后补上真字节，不被空壳读数判成篡改", lambda: replenishThenCall(
        LEDGER_PATH, ENTRY_DIR))

    read("[7] 对照：有构件的未钉条目仍首钉一次并落账", lambda: controlRealSkillPinsOnce(ROOT))

endFp = dataFingerprint()
print("仓内 data/ 指纹：起 %d 文件／%s → 止 %d 文件／%s" % (
    startFp[0], startFp[1], endFp[0], endFp[1]))
print("\n==== 汇总：计分读数 7 项，失败 %d ====" % len(failures))
for f in failures:
    print("  FAIL", f)
sys.exit(1 if (failures or endFp != startFp) else 0)
