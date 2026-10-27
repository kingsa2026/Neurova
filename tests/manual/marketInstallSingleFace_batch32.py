# -*- coding: utf-8 -*-
"""live-verify（工单 2026-10-13 批 32，§6-177）：市场安装真走咽喉解包，仓内不再有两份解压判定。

判据档（`tests/unit/skills/test_marketInstallUsesSingleFace.py`）在 tmp_path 里搭场景；这一支
要在**真包内资产**与**真模块**上自证：

1. 真内置 bundle 的字节经真市场侧函数落盘 ⇒ 解出的文件集与 zip 成员一致（咽喉没把正常件焊死）；
2. zip-slip / 绝对成员 / 超字节 / 超成员四种载荷四种**互不掩盖**的拒因，且拒绝时一个文件都不落；
3. 反向校准：把咽喉桩成"一律拒"，市场侧必须跟着拒——若它手里还留着第二份判定，这一跑会照旧解出来；
4. 不递上限时咽喉不自设限（另外 6 个调用点的形状没被本批挪动）；
5. 全仓按 AST 数"往目录里写压缩包成员"的落点 ⇒ 只剩咽喉那一个文件。

另附一条**只取证不判定**的观察（它决定本批为何不给市场侧钉摘要）：`skill.json` 的读者数。
写了没人读就是 §2 的断点，判据不该给坏状态焊死修复路，故这条进台账 §6-177 待人裁。

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

from tests.ast_scan import parseSource
from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
WORK_ROOT = isolatedDataRoot(prefix="neurovaMarketB32")

from neurova.security import safe_archive as SA  # noqa: E402
from neurova.skills import market_sources as MS  # noqa: E402
from neurova.skills.market_importer import read_builtin_bundle  # noqa: E402

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
            tree = parseSource(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "extractall":
                    hits.append(path.relative_to(root).as_posix())
                    break
    return hits


def _ledgerFileSites(relName: str) -> list:
    """逐条列出 `"skill.json"` 这个字面量在 `neurova/` 的出现处并按**那一行自己**写得清的
    动作分类（写盘／读盘／其余＝路径拼接或常量集）。经变量转手的读写不在这里计数——所以
    整张表一起打出来：「读侧为 0」这件事要由人来核，不由脚本自证。"""
    sites = []
    for path in sorted((REPO_ROOT / "neurova").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        try:
            tree = parseSource("\n".join(lines))
        except (SyntaxError, UnicodeDecodeError):
            continue
        rel = path.relative_to(REPO_ROOT / "neurova").as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value == relName:
                line = lines[node.lineno - 1].strip() if node.lineno - 1 < len(lines) else ""
                if "write_text" in line or "write_bytes" in line:
                    kind = "写"
                elif any(tok in line for tok in ("read_text", "read_bytes", "json.load")):
                    kind = "读"
                else:
                    kind = "其它"
                sites.append(f"{kind} | {rel}:{node.lineno} | {line[:70]}")
    return sites


def main() -> int:
    print(f"数据根（注入隔离）: {WORK_ROOT}")
    work = WORK_ROOT / "e"
    work.mkdir(parents=True, exist_ok=True)

    payload = read_builtin_bundle(BUNDLE)
    check("[1] 真内置 bundle 取得到", bool(payload), f"{len(payload or b'')} bytes")
    dest = work / "bundle"
    check("[2] 真市场侧函数解真 bundle 成功",
          MS.extract_remote_skill_zip("live", payload, dest) is True, "")
    names = sorted(str(p.relative_to(dest).as_posix()) for p in dest.rglob("*") if p.is_file())
    inZip = sorted(i.filename for i in zipfile.ZipFile(io.BytesIO(payload)).infolist()
                   if not i.is_dir())
    check("[3] 落盘文件集与 zip 成员一致", names == inZip, f"盘上={names} 包内={inZip}")

    refused = {}
    for label, sample, target in [
        ("slip", _zipBytes({"../escaped.txt": "pwned"}), work / "slip"),
        ("abs", _zipBytes({"/etc/escaped.txt": "pwned"}), work / "abs"),
        ("big", b"z" * (MS.MAX_SKILL_ZIP_BYTES + 1), work / "big"),
        ("many", _zipBytes({f"f{i}.txt": "x" for i in range(MS.MAX_ZIP_ENTRIES + 1)}), work / "many"),
    ]:
        refused[label] = MS.extract_remote_skill_zip(label, sample, target) is False
    check("[4] 四种恶意/超限样本全拒", all(refused.values()), str(refused))
    check("[5] 目录外没落任何文件", not (work / "escaped.txt").exists(), "")
    for label in ("slip", "abs", "many"):
        d = work / label
        left = [p.name for p in d.rglob("*") if p.is_file()] if d.exists() else []
        check(f"[6.{label}] 拒时一个文件都不落", left == [], str(left))

    reasons = {}
    for label, sample, kwargs in [
        ("big", b"z" * (MS.MAX_SKILL_ZIP_BYTES + 1), {"maxPayloadBytes": MS.MAX_SKILL_ZIP_BYTES}),
        ("many", _zipBytes({f"f{i}.txt": "x" for i in range(501)}), {"maxEntries": MS.MAX_ZIP_ENTRIES}),
        ("slip", _zipBytes({"../e.txt": "x"}), {}),
    ]:
        try:
            SA.safe_extract_zip(sample, work / f"r{label}", **kwargs)
            reasons[label] = "没拒"
        except SA.UnsafeArchiveError as e:
            reasons[label] = str(e)
    check("[7] 三条拒因互不掩盖且点名",
          "字节" in reasons["big"] and "成员" in reasons["many"]
          and ("穿越" in reasons["slip"] or "越出" in reasons["slip"]),
          json.dumps(reasons, ensure_ascii=False))

    original = SA.safe_extract_zip
    try:
        def refuse(*a, **k):
            raise SA.UnsafeArchiveError("桩：一律拒")

        SA.safe_extract_zip = refuse
        stubbed = MS.extract_remote_skill_zip("stub", payload, work / "stub")
    finally:
        SA.safe_extract_zip = original
    check("[8] 反向校准：咽喉桩成拒 ⇒ 市场侧必须拒（手里不许还留着第二份判定）",
          stubbed is False, f"returns={stubbed}")

    wide = _zipBytes({f"w{i}.txt": "x" for i in range(MS.MAX_ZIP_ENTRIES + 1)})
    try:
        SA.safe_extract_zip(wide, work / "wide")
        uncapped, why = True, "未设限即解出"
    except SA.UnsafeArchiveError as e:
        uncapped, why = False, str(e)
    check("[9] 不递上限时咽喉不自设限（另 6 个调用点形状未动）", uncapped, why)

    hits = _extractallFiles(REPO_ROOT / "neurova")
    check("[10] 全仓落盘解包只剩咽喉一个文件", hits == ["security/safe_archive.py"], str(hits))

    obs = _ledgerFileSites("skill.json")
    readers = [o for o in obs if o.startswith("读")]
    print('[OBSERVE] "skill.json" 在 neurova/ 的每个出现处（读侧 %d 条）——本批因此不给市场侧'
          "钉摘要：写进没人读的文件就是 §2 的断点。影响面与待裁三项见台账 §6-177。" % len(readers))
    for o in obs:
        print("          " + o)

    print(f"\n读数 {10} 项，失败 {len(failures)} 项: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
