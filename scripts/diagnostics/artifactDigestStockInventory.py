# -*- coding: utf-8 -*-
"""存量构件摘要清单（只读）：哪些已装技能/插件没有钉、钉了却不符、或锚缺。

背景：§6-383 三票收口时把「存量未钉条目」登记为待办（`pinnedDigest=None` 的 TOFU 口径/
首次装载才补钉）。这份脚本就是那张清单——**只读生产数据根，不写一个字节**：

- 技能：扫 `<数据根>/*/skills/manifest.json`（含更深一层的同名文件），对每条 **path 非空** 的
  记录给出四态：`pinned-ok` / `pinned-mismatch` / `unpinned`（从未钉过，首次调用会 TOFU 首钉）/
  `missing-dir`（目录没了）；`path` 为空的自动/合成技能不在本清单（没有盘上字节）。
- 插件：读 `<数据根>/plugins/state.json`，同一套四态。
- 锚文件：读 `artifact_digest.anchorPath()` 那一址（数据根下的 `artifacts/`），给出每个键是 `match` / `anchor-missing` /
  `anchor-mismatch`（不写、不补）。

用法：`PYTHONPATH=$(git rev-parse --show-toplevel) python scripts/diagnostics/artifactDigestStockInventory.py [--json]`
退出码：0＝清单已产出（与是否有存量无关）；2＝连数据根都读不出（这时别把"读不到"当"没有"）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from neurova.core.data_root import get_data_root  # noqa: E402
from neurova.security import artifact_digest  # noqa: E402

UNPINNED = "unpinned"
OK = "pinned-ok"
MISMATCH = "pinned-mismatch"
MISSING = "missing-dir"
#: 没有"盘上可执行字节"的条目（映射型执行体、或目录里没有 SKILL.md/入口）：摘要对它不适用。
NO_BYTES = "no-artifact-bytes"


def _hasArtifactBytes(root: Path) -> bool:
    if not root.is_dir():
        return False
    if (root / "SKILL.md").is_file():
        return True
    return any(child.suffix == ".py" for child in root.rglob("*.py"))


def _statusFor(root: Path, pinned: str) -> str:
    status, _actual = artifact_digest.checkArtifact(root, pinned)
    if status == artifact_digest.STATUS_MATCH:
        return OK
    if status == artifact_digest.STATUS_MISMATCH:
        return MISMATCH
    if status == artifact_digest.STATUS_MISSING:
        return MISSING
    return UNPINNED


def _anchorStatus(anchorKey: str, actual: str, anchors: dict) -> str:
    pinned = (anchors or {}).get(anchorKey)
    if not artifact_digest.isPinned(pinned):
        return "anchor-missing"
    return "match" if artifact_digest.digestMatches(pinned, actual) else "anchor-mismatch"


def collect(dataRoot: Path) -> dict:
    anchors = artifact_digest.readAnchors()
    skills = []
    for manifestPath in sorted(dataRoot.glob("*/skills/manifest.json")):
        try:
            manifest = json.loads(manifestPath.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001 —— 坏文件出声跳过，不当成"没有条目"
            skills.append({"manifest": str(manifestPath), "entry": "<unreadable>",
                           "status": "unreadable", "detail": str(e)})
            continue
        for name, entry in (manifest or {}).items():
            if name.startswith("__") or not isinstance(entry, dict):
                continue
            path = str(entry.get("path") or "")
            if not path:
                continue
            pinned = str(entry.get(artifact_digest.DIGEST_FIELD) or "")
            from neurova.skills.market_registry import hasExecutorMapping
            if hasExecutorMapping(name) or not _hasArtifactBytes(Path(path)):
                skills.append({"manifest": str(manifestPath), "entry": name, "path": path,
                               "status": NO_BYTES, "pinned": pinned[:26],
                               "anchor": "n/a"})
                continue
            status = _statusFor(Path(path), pinned)
            actual = artifact_digest.digestDir(Path(path)) if Path(path).exists() else ""
            skills.append({
                "manifest": str(manifestPath), "entry": name, "path": path,
                "status": status, "pinned": pinned[:26],
                "anchor": _anchorStatus(artifact_digest.artifactKey("skill", name), actual, anchors)
                if actual else "no-bytes",
            })

    plugins = []
    statePath = dataRoot / "plugins" / "state.json"
    if statePath.exists():
        try:
            state = json.loads(statePath.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            plugins.append({"name": "<state-unreadable>", "status": "unreadable",
                            "detail": str(e)})
            state = {}
        for name, entry in ((state or {}).get("plugins") or {}).items():
            if not isinstance(entry, dict):
                continue
            path = str(entry.get("path") or "")
            pinned = str(entry.get(artifact_digest.DIGEST_FIELD) or "")
            status = _statusFor(Path(path), pinned) if path else MISSING
            actual = artifact_digest.digestDir(Path(path)) if path and Path(path).exists() else ""
            plugins.append({
                "name": name, "path": path, "status": status, "pinned": pinned[:26],
                "anchor": _anchorStatus(artifact_digest.artifactKey("plugin", name), actual, anchors)
                if actual else "no-bytes",
            })

    return {"data_root": str(dataRoot), "anchor_file": str(artifact_digest.anchorPath()),
            "skills": skills, "plugins": plugins}


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        dataRoot = Path(get_data_root())
        if not dataRoot.exists():
            print("数据根不存在：%s" % dataRoot, file=sys.stderr)
            return 2
        report = collect(dataRoot)
    except Exception as e:  # noqa: BLE001
        print("清单读不出：%s" % e, file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    counts = {}
    for row in report["skills"] + report["plugins"]:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    print("数据根：%s" % report["data_root"])
    print("锚文件：%s" % report["anchor_file"])
    print("条目数：技能 %d / 插件 %d；状态计数：%s"
          % (len(report["skills"]), len(report["plugins"]), counts or "{}"))
    for section in ("skills", "plugins"):
        for row in report[section]:
            if row["status"] != OK:
                print("  [%s] %s %s <- %s（anchor=%s）"
                      % (section, row.get("entry") or row.get("name"), row["status"],
                         row.get("path") or row.get("manifest"), row.get("anchor")))
    gaps = [row for row in report["skills"] + report["plugins"]
            if row["status"] not in (OK, NO_BYTES)]
    print("需要处置的条目：%d（no-artifact-bytes 不计入）" % len(gaps))
    if not gaps:
        print("（没有需要处置的条目）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
