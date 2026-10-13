# -*- coding: utf-8 -*-
"""live-verify（工单 2026-10-13 批 32，§6-172 / P3 旁路收口）：市场安装这条活路真的走咽喉、真的把摘要钉进账。

判据档（`tests/unit/skills/test_marketInstallUsesSingleFaceAndPins.py`）在 tmp_path 里搭场景；
这一支要证的是**真包内资产走真安装路**之后的产物：

1. 真 `MarketImporter` + 真内置 bundle（零网络）装完 ⇒ 盘上的 `skill.json` 里带着摘要；
2. 摘要等于落位那份字节的聚合值（不是凭空写的一个哈希）；
3. 换一字节 / 加一个文件 ⇒ 读侧按同一口径报不符（钉是有牙的，不是装饰）；
4. 反向校准：抹掉摘要 ⇒ 退回 `unpinned` 首钉（否则第 3 项可能只是"永远拒"的假绿）；
5. zip-slip / 超字节 / 超成员三种载荷过真市场侧函数 ⇒ 全拒且目录外什么都没落，
   而**不递上限时**咽喉仍不设限（另外 6 个调用点的形状没被本批挪动）；
6. 全仓按 AST 数"往目录里写压缩包成员"的落点 ⇒ 只剩咽喉那一个文件。

跑法：`PYTHONPATH=$(git rev-parse --show-toplevel) python tests/manual/marketInstallSingleFace_batch32.py`
"""

from __future__ import annotations

import ast
import io
import json
import sys
import zipfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
WORK_ROOT = isolatedDataRoot(prefix="neurovaMarketB32")

from neurova.security import artifact_digest as AD  # noqa: E402
from neurova.security import safe_archive as SA  # noqa: E402
from neurova.skills import market_sources as MS  # noqa: E402
from neurova.skills.market_importer import MarketImporter  # noqa: E402

failures: list[str] = []
BUNDLE = "multi-search-engine.zip"


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(name)


def _zipBytes(entries: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, body in entries.items():
            zf.writestr(name, body)
    return buf.getvalue()


def _extractallFiles(root: Path) -> list:
    """按 AST 找"真的调了 extractall"的文件（注释里那句『原 extractall 无成员校验』不算）。"""
    hits = []
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "extractall":
                    hits.append(path.relative_to(root).as_posix())
                    break
    return hits


def main() -> int:
    print(f"数据根（注入隔离）: {WORK_ROOT}")
    skills = WORK_ROOT / "s"          # 短名：长路径会撞 Windows 260 字符墙（与本批无关的预存坑）
    importer = MarketImporter(skills)
    importer._lookup_catalog_entry = lambda skill_id: {"bundle_zip": BUNDLE, "version": "1.0.0"}

    task = importer.import_skill("live-b32")
    dest = skills / "live-b32"
    meta = json.loads((dest / "skill.json").read_text(encoding="utf-8")) if (dest / "skill.json").exists() else {}
    check("[1] 真内置 bundle 安装完成", task.status.value == "completed", str(task.error_message))
    check("[2] 盘上 skill.json 带摘要键", bool(meta.get(AD.DIGEST_FIELD)), repr(meta.get(AD.DIGEST_FIELD)))

    pinned = str(meta.get(AD.DIGEST_FIELD) or "")
    now = AD.digestDir(dest)
    check("[3] 钉的就是落位那份字节", pinned == now, f"pinned={pinned[:20]} now={now[:20]}")

    status, _ = AD.checkArtifact(dest, pinned)
    check("[4] 未改动时读侧报 match", status == AD.STATUS_MATCH, status)

    victim = next((p for p in dest.rglob("*") if p.is_file() and p.name != "skill.json"), None)
    victim.write_bytes(b"T" + victim.read_bytes()[1:])
    status, actual = AD.checkArtifact(dest, pinned)
    check("[5] 改一字节即被读侧拒", status == AD.STATUS_MISMATCH, f"{status} actual={actual[:20] if actual else actual}")
    status, _ = AD.checkArtifact(dest, pinned)
    check("[6] 拒因文案点名构件不符", AD.refusalReason(status) == AD.REASON_MISMATCH, AD.refusalReason(status))

    clean = WORK_ROOT / "clean"
    cleanImporter = MarketImporter(clean)
    cleanImporter._lookup_catalog_entry = lambda skill_id: {"bundle_zip": BUNDLE, "version": "1.0.0"}
    cleanImporter.import_skill("clean-b32")
    cleanDir = clean / "clean-b32"
    cleanPinned = json.loads((cleanDir / "skill.json").read_text(encoding="utf-8"))[AD.DIGEST_FIELD]
    (cleanDir / "extra.py").write_text("print('x')\n", encoding="utf-8")
    status, _ = AD.checkArtifact(cleanDir, cleanPinned)
    check("[7] 目录内新增文件也算篡改", status == AD.STATUS_MISMATCH, status)
    (cleanDir / "extra.py").unlink()
    status, _ = AD.checkArtifact(cleanDir, cleanPinned)
    check("[8] 撤掉新增即复原（拒因不是随机数）", status == AD.STATUS_MATCH, status)

    status, _ = AD.checkArtifact(cleanDir, None)
    check("[9] 反向校准：抹掉摘要退回首钉", status == AD.STATUS_UNPINNED, status)

    seed = WORK_ROOT / "seed"
    seedImporter = MarketImporter(seed)
    seedImporter._lookup_catalog_entry = lambda skill_id: {"version": "1.0.0"}
    seedImporter.import_skill("seed-b32")
    seedMeta = json.loads((seed / "seed-b32" / "skill.json").read_text(encoding="utf-8"))
    check("[10] 没取回字节的那支不钉", AD.DIGEST_FIELD not in seedMeta, repr(sorted(seedMeta)))

    escape = WORK_ROOT / "e"
    escape.mkdir(parents=True, exist_ok=True)
    ok = MS.extract_remote_skill_zip("slip", _zipBytes({"../escaped.txt": "pwned"}), escape / "d")
    check("[11] zip-slip 被拒", ok is False, f"returns={ok}")
    check("[12] 目录外确实没落文件", not (escape / "escaped.txt").exists(), "")

    big = b"z" * (MS.MAX_SKILL_ZIP_BYTES + 1)
    check("[13] 超字节上限被拒", MS.extract_remote_skill_zip("big", big, escape / "b") is False, "")
    many = _zipBytes({f"f{i}.txt": "x" for i in range(MS.MAX_ZIP_ENTRIES + 1)})
    destMany = escape / "m"
    check("[14] 超成员上限被拒", MS.extract_remote_skill_zip("many", many, destMany) is False, "")
    check("[15] 拒时一个文件都不落", not any(p.is_file() for p in destMany.rglob("*")) if destMany.exists() else True, "")

    wide = _zipBytes({f"w{i}.txt": "x" for i in range(MS.MAX_ZIP_ENTRIES + 1)})
    try:
        SA.safe_extract_zip(wide, escape / "wide")
        uncapped = True
        why = "未设限即解出"
    except SA.UnsafeArchiveError as e:
        uncapped = False
        why = str(e)
    check("[16] 不递上限时咽喉不自设限（另 6 个调用点形状未动）", uncapped, why)

    hits = _extractallFiles(REPO_ROOT / "neurova")
    check("[17] 全仓落盘解包只剩咽喉一个文件", hits == ["security/safe_archive.py"], str(hits))

    print(f"\n读数 {17} 项，失败 {len(failures)} 项: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
