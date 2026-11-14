"""架构即代码门禁守卫（P1-7）。

钉住四件事：
1. policy 声明自洽：层级有序、成员唯一、当前仓库全部顶层模块已分类；
2. 当前仓库对检查器全绿（层级方向 / 直连 agent / 尺寸基线零违规）；
3. 检查器有牙：合成树上的上行依赖、越权直连 agent、超尺寸、基线滥用均判红；
4. 基线棘轮：基线内条目不许反弹，修复后残留的陈旧基线条目本身即违规。

判据同源：AGENTS.md §3（深模块经 agent_ref 注入、禁止直连 Agent）与尺寸棘轮先例
（tests/unit/agent/test_agent_core_size_ratchet.py）。
"""

import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKER = REPO_ROOT / "scripts" / "ci" / "architecture_check.py"
POLICY = REPO_ROOT / "scripts" / "ci" / "architecture_policy.yaml"
BASELINE = REPO_ROOT / "scripts" / "ci" / "architecture_baseline.json"

sys.path.insert(0, str(REPO_ROOT / "scripts" / "ci"))
architecture_check = importlib.import_module("architecture_check")


def runChecker(root: Path, *extra: str, baseline: Path | None = None) -> subprocess.CompletedProcess:
    cmd = [
        sys.executable,
        str(CHECKER),
        "--root",
        str(root),
        "--policy",
        str(POLICY),
        "--baseline",
        str(baseline or BASELINE),
        *extra,
    ]
    return subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", cwd=str(REPO_ROOT)
    )


def writeTree(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


def emptyBaseline(tmp_path: Path, **payload) -> Path:
    baseline = tmp_path / "baseline.json"
    data = {"version": 1, "importBaselineCounts": {}, "sizeBaselines": {}}
    data.update(payload)
    baseline.write_text(json.dumps(data), encoding="utf-8")
    return baseline


def testPolicyDeclaresOrderedUniqueLayers() -> None:
    policy = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
    order = policy["layerOrder"]
    assert order == sorted(order, key=order.index)
    seen: list[str] = []
    for name in order:
        members = policy["layers"][name]
        assert members, f"{name} 成员为空"
        seen.extend(members)
    assert len(seen) == len(set(seen)), "模块在多层重复登记"


def testAllTopLevelModulesClassified() -> None:
    policy = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
    declared = {m for members in policy["layers"].values() for m in members}
    present = architecture_check.topLevelModules(REPO_ROOT / "neurova")
    assert present <= declared, f"未分类模块: {sorted(present - declared)}"


def testCheckerGreenOnCurrentRepo() -> None:
    result = runChecker(REPO_ROOT / "neurova")
    assert result.returncode == 0, f"当前树存在违规:\n{result.stdout}"


def testCheckerCatchesUpwardImport(tmp_path: Path) -> None:
    root = writeTree(
        tmp_path / "neurova",
        {
            "core/__init__.py": "",
            "core/bad.py": "from neurova.llm import LLMConfig\n",
        },
    )
    result = runChecker(root, baseline=emptyBaseline(tmp_path))
    assert result.returncode == 1
    assert "upward-import: core->llm" in result.stdout


def testLazyImportInsideFunctionAllowed(tmp_path: Path) -> None:
    root = writeTree(
        tmp_path / "neurova",
        {
            "core/__init__.py": "",
            "core/ok.py": (
                "def helper():\n"
                "    from neurova.llm import LLMConfig\n"
                "    return LLMConfig\n"
            ),
        },
    )
    result = runChecker(root, baseline=emptyBaseline(tmp_path))
    assert result.returncode == 0, result.stdout


def testDirectAgentImportOutsideAllowlistRed(tmp_path: Path) -> None:
    root = writeTree(
        tmp_path / "neurova",
        {
            "llm/__init__.py": "",
            "llm/bad.py": "import neurova.agent\n",
        },
    )
    result = runChecker(root, baseline=emptyBaseline(tmp_path))
    assert result.returncode == 1
    assert "direct-agent-import" in result.stdout
    assert "llm/bad.py" in result.stdout


def testSizeOverHardCapThenBaseline(tmp_path: Path) -> None:
    root = tmp_path / "neurova"
    big = "x = 0\n" * 3100
    writeTree(root, {"core/__init__.py": "", "core/huge.py": big})
    result = runChecker(root)
    assert result.returncode == 1
    assert "size-over-hard-cap: neurova/core/huge.py" in result.stdout

    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps({"version": 1, "importBaselineCounts": {}, "sizeBaselines": {"neurova/core/huge.py": 3100}}),
        encoding="utf-8",
    )
    result = runChecker(root, baseline=baseline)
    assert result.returncode == 0, result.stdout

    (root / "core/huge.py").write_text("x = 0\n" * 3200, encoding="utf-8")
    result = runChecker(root, baseline=baseline)
    assert result.returncode == 1
    assert "size-over-baseline: neurova/core/huge.py 3200" in result.stdout


def testStaleBaselineEntriesAreViolations(tmp_path: Path) -> None:
    root = writeTree(
        tmp_path / "neurova",
        {"core/__init__.py": "", "core/clean.py": "from neurova.models import X\n"},
    )
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "version": 1,
                "importBaselineCounts": {"core->security": 1},
                "directAgentImportExemptions": ["neurova/core/clean.py"],
                "sizeBaselines": {"neurova/core/gone.py": 10},
            }
        ),
        encoding="utf-8",
    )
    result = runChecker(root, baseline=baseline)
    assert result.returncode == 1
    assert "stale-baseline: core->security" in result.stdout
    assert "stale-agent-exemption: neurova/core/clean.py" in result.stdout
    assert "stale-size-baseline: neurova/core/gone.py" in result.stdout


def testStrictRatchetFlagsBaselineSlack(tmp_path: Path) -> None:
    root = writeTree(
        tmp_path / "neurova",
        {"core/__init__.py": "", "core/bad.py": "from neurova.llm import X\n"},
    )
    baseline = emptyBaseline(tmp_path, importBaselineCounts={"core->llm": 5})
    assert runChecker(root, baseline=baseline).returncode == 0
    result = runChecker(root, "--strict-ratchet", baseline=baseline)
    assert result.returncode == 1
    assert "ratchet-slack: core->llm 现值 1 < 基线 5" in result.stdout


def testUpdateBaselinesRecordsSizes(tmp_path: Path) -> None:
    root = tmp_path / "neurova"
    writeTree(root, {"core/__init__.py": "", "core/huge.py": "x = 0\n" * 3100})
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"version": 1, "importBaselineCounts": {}, "sizeBaselines": {}}), encoding="utf-8")
    result = runChecker(root, "--update-baselines", baseline=baseline)
    assert result.returncode == 0
    saved = json.loads(baseline.read_text(encoding="utf-8"))
    assert saved["sizeBaselines"]["neurova/core/huge.py"] == 3100


@pytest.mark.parametrize("flag", ["--changed"])
def testChangedModeRuns(flag: str, tmp_path: Path) -> None:
    root = writeTree(
        tmp_path / "neurova",
        {"core/__init__.py": "", "core/clean.py": "from neurova.models import X\n"},
    )
    result = runChecker(root, flag, baseline=emptyBaseline(tmp_path))
    assert result.returncode == 0, result.stdout
