#!/usr/bin/env python3
"""架构即代码检查器（P1-7，对照 ZCode architecture-check 形态）。

三条机器可查的纪律：
1. 层级方向：顶层模块按 policy 分层，模块级 import 只允许指向同级或更低层；
   函数内惰性 import 豁免（与 AGENTS.md §3 懒加载教义同构）。
2. 直连 Agent 面收口：`neurova.agent` 只允许白名单模块在模块级 import——
   把「深模块经 agent_ref 依赖注入、禁止直接 import Agent」变成机器判据。
3. 尺寸棘轮：单文件硬上限 + 既有巨文件的逐文件基线（只降不升）。

配套文件：
- scripts/ci/architecture_policy.yaml   规则（人工维护、带注释）
- scripts/ci/architecture_baseline.json 基线（机器生成：尺寸基线 + 存量违规计数）

用法：
    python scripts/ci/architecture_check.py                 # 全量检查（CI 用）
    python scripts/ci/architecture_check.py --changed       # 只查相对 HEAD 变更的文件
    python scripts/ci/architecture_check.py --update-baselines
    python scripts/ci/architecture_check.py --strict-ratchet  # 基线命中数必须与基线相等

退出码：0 通过；1 存在违规；2 参数/策略错误；3 棘轮出现富余（需下调基线）。
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import sys
from pathlib import Path

DEFAULT_POLICY = Path(__file__).resolve().parent / "architecture_policy.yaml"
DEFAULT_BASELINE = Path(__file__).resolve().parent / "architecture_baseline.json"
DEFAULT_ROOT = "neurova"
REPO_ROOT = Path(__file__).resolve().parents[2]

EXIT_OK = 0
EXIT_VIOLATIONS = 1
EXIT_USAGE = 2
EXIT_RATCHET_SLACK = 3


def loadPolicy(path: Path) -> dict:
    import yaml  # 延迟导入：检查器本体保持除 pyyaml 外零三方依赖

    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"policy 必须是映射：{path}")
    return data


def loadBaseline(path: Path) -> dict:
    if not path.exists():
        return {"version": 1, "importBaselineCounts": {}, "sizeBaselines": {}}
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    data.setdefault("importBaselineCounts", {})
    data.setdefault("sizeBaselines", {})
    return data


def topLevelModules(root: Path) -> set[str]:
    mods: set[str] = set()
    for child in sorted(root.iterdir()):
        if child.name == "__pycache__":
            continue
        if child.is_dir() and (child / "__init__.py").exists():
            mods.add(child.name)
        elif child.is_file() and child.suffix == ".py" and child.name != "__init__.py":
            mods.add(child.stem)
    return mods


def iterPyFiles(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for fn in sorted(filenames):
            if fn.endswith(".py"):
                yield Path(dirpath) / fn


def resolveTargets(node: ast.stmt, pkgParts: tuple[str, ...]) -> list[tuple[str, int]]:
    """把一条模块级 import 语句解析成 neurova 顶层模块目标列表。"""
    targets: list[str] = []
    if isinstance(node, ast.Import):
        for alias in node.names:
            targets.append(alias.name)
    elif isinstance(node, ast.ImportFrom):
        if node.level == 0:
            if node.module == "neurova":
                targets = [f"neurova.{alias.name}" for alias in node.names]
            elif node.module and node.module.startswith("neurova."):
                targets = [node.module]
        else:
            base = pkgParts[: len(pkgParts) - (node.level - 1)] if len(pkgParts) >= node.level else None
            if base:
                if node.module:
                    targets = ["neurova." + ".".join(base + tuple(node.module.split(".")))]
                else:
                    targets = ["neurova." + ".".join(base + (alias.name,)) for alias in node.names]
    out = []
    for target in targets:
        rest = target.split(".")[1:]
        if rest:
            out.append((rest[0], node.lineno))
    return out


def scanFile(path: Path, root: Path) -> tuple[str | None, list[tuple[str, int]], bool]:
    """返回 (源模块名, [(目标模块, 行号)], 是否可解析)。"""
    rel = path.relative_to(root)
    parts = rel.parts
    if len(parts) == 1:
        src = parts[0][:-3]
        pkgParts: tuple[str, ...] = ()
    else:
        src = parts[0]
        pkgParts = parts[:-1]
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return src, [], False
    edges: list[tuple[str, int]] = []
    for node in tree.body:
        for dst, lineno in resolveTargets(node, pkgParts):
            if dst != src:
                edges.append((dst, lineno))
    return src, edges, True


def changedFiles(repo: Path, base: str | None) -> set[str]:
    cmd = ["git", "-C", str(repo), "diff", "--name-only"]
    if base:
        cmd = ["git", "-C", str(repo), "diff", "--name-only", f"{base}...HEAD"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    except (subprocess.CalledProcessError, OSError):
        return set()
    return {line.strip().replace("\\", "/") for line in out.splitlines() if line.strip()}


def main() -> int:
    parser = argparse.ArgumentParser(description="architecture policy gate")
    parser.add_argument("--policy", default=str(DEFAULT_POLICY))
    parser.add_argument("--baseline", default=str(DEFAULT_BASELINE))
    parser.add_argument("--root", default=DEFAULT_ROOT, help="被检包根目录（默认 neurova）")
    parser.add_argument("--changed", action="store_true", help="只检查相对 HEAD/--base 变更的文件")
    parser.add_argument("--base", default=None, help="与 --changed 连用的 git 基准 ref")
    parser.add_argument("--strict-ratchet", action="store_true", help="基线命中数必须与基线相等")
    parser.add_argument("--update-baselines", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    try:
        policy = loadPolicy(Path(args.policy))
    except (OSError, ValueError) as exc:
        print(f"[architecture-check] 策略文件不可用：{exc}")
        return EXIT_USAGE
    baseline = loadBaseline(Path(args.baseline))

    layerOrder = policy.get("layerOrder") or []
    layers = policy.get("layers") or {}
    if not layerOrder or not layers:
        print("[architecture-check] policy 缺少 layerOrder/layers")
        return EXIT_USAGE
    layerIndex = {name: idx for idx, name in enumerate(layerOrder)}
    moduleLayer: dict[str, int] = {}
    for name, members in layers.items():
        for member in members or []:
            moduleLayer[member] = layerIndex[name]
    agentAllowlist = set(policy.get("directAgentImportAllowlist") or [])
    agentExemptions = set(baseline.get("directAgentImportExemptions") or [])
    hardCap = int(policy.get("sizeHardCapLines") or 3000)
    importBaseline = baseline.get("importBaselineCounts", {})
    sizeBaseline = baseline.get("sizeBaselines", {})

    root = Path(args.root)
    if not root.is_absolute():
        root = REPO_ROOT / root
    if not root.exists():
        print(f"[architecture-check] 被检根目录不存在：{root}")
        return EXIT_USAGE

    scope = None
    if args.changed:
        scope = changedFiles(REPO_ROOT, args.base)
        if not args.quiet:
            print(f"[architecture-check] 变更文件 {len(scope)} 个（base={args.base or 'HEAD(worktree)'}）")

    violations: list[str] = []
    edgeHits: dict[str, int] = {}
    edgeWhere: dict[str, str] = {}
    agentViolations: list[str] = []
    exemptedAgentFiles: set[str] = set()
    parseFailures: list[str] = []
    sizes: dict[str, int] = {}
    inScope = (lambda rel: scope is None or rel in scope) if scope is not None else (lambda rel: True)

    present = topLevelModules(root)
    unclassified = sorted(present - set(moduleLayer))
    for name in unclassified:
        violations.append(f"unclassified-module: neurova/{name} 未在 policy 分层登记")

    for path in iterPyFiles(root):
        rel = path.relative_to(root.parent).as_posix()
        src, edges, ok = scanFile(path, root)
        if not ok:
            parseFailures.append(rel)
            continue
        sizes[rel] = len(path.read_text(encoding="utf-8", errors="replace").splitlines())
        if src is None:
            continue
        for dst, lineno in edges:
            if dst == "agent" and src != "agent" and src not in agentAllowlist:
                if rel not in agentExemptions:
                    agentViolations.append(f"{rel}:{lineno} 模块级直连 neurova.agent（白名单外）")
                else:
                    exemptedAgentFiles.add(rel)
            if dst not in moduleLayer or src not in moduleLayer:
                continue
            if moduleLayer[dst] > moduleLayer[src]:
                key = f"{src}->{dst}"
                edgeHits[key] = edgeHits.get(key, 0) + 1
                edgeWhere.setdefault(key, f"{rel}:{lineno}")

    for key, hits in sorted(edgeHits.items()):
        allowed = importBaseline.get(key)
        if allowed is None:
            violations.append(f"upward-import: {key} ×{hits}（首次出现，如 {edgeWhere.get(key)}）")
        elif hits > allowed:
            violations.append(f"upward-import: {key} ×{hits} 超出基线 {allowed}（如 {edgeWhere.get(key)}）")
        elif args.strict_ratchet and hits != allowed:
            violations.append(f"ratchet-slack: {key} 现值 {hits} < 基线 {allowed}，请下调基线")
    for key in sorted(set(importBaseline) - set(edgeHits)):
        violations.append(f"stale-baseline: {key} 已无命中，请从基线删除")

    for rel in sorted(set(agentExemptions) - exemptedAgentFiles):
        violations.append(f"stale-agent-exemption: {rel} 已无模块级直连 agent，请从基线删除")

    staleSizes = sorted(k for k in sizeBaseline if k not in sizes)
    for key in staleSizes:
        violations.append(f"stale-size-baseline: {key} 文件已不存在，请从基线删除")

    for rel in sorted(sizes):
        if not inScope(rel):
            continue
        cap = int(sizeBaseline.get(rel, hardCap))
        if sizes[rel] > cap:
            tag = "size-over-baseline" if rel in sizeBaseline else "size-over-hard-cap"
            violations.append(f"{tag}: {rel} {sizes[rel]} 行 > 上限 {cap}")

    if parseFailures:
        violations.append(f"unparseable-files: {', '.join(parseFailures)}")
    for item in sorted(set(agentViolations)):
        violations.append(f"direct-agent-import: {item}")

    if args.update_baselines:
        newSizes = {
            rel: sizes[rel]
            for rel in sorted(sizes)
            if sizes[rel] > hardCap or rel in sizeBaseline
        }
        payload = dict(baseline)
        payload["sizeBaselines"] = newSizes
        Path(args.baseline).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"[architecture-check] 基线已更新：{len(newSizes)} 个尺寸条目 -> {args.baseline}")
        return EXIT_OK

    if not args.quiet:
        print(
            f"[architecture-check] 模块 {len(present)} | 边 {sum(edgeHits.values())} | "
            f"文件 {len(sizes)} | 违规 {len(violations)}"
        )
        for item in violations[:60]:
            print(f"  - {item}")
        if len(violations) > 60:
            print(f"  ...其余 {len(violations) - 60} 条略")

    if violations:
        return EXIT_VIOLATIONS
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
