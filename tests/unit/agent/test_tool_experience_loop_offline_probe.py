"""001 残留 · 只读取证脚本必须可独立重跑（不依赖 pytest 也能出读数）。

票据 001 的落点原文：「只读取证脚本：`scripts/diagnostics/_tool_experience_loop_probe.py`，
对**复制**到 `tmp_path` 的库跑，输出三读数 + 票据 `lookup`/`ticket_reason` 的 JSON
（禁止指向 `data/` 生产库）」。

前一轮只把探针写成 pytest 用例：三条读数只能在测试运行器里看到，现场排障
（"这台机器上到底产不产票"）没有任何可独立重跑的取证入口。本文件钉住这支脚本的
**存在性与只读性**：它能被直接 `python` 起来、输出 JSON、并且绝不打开 `data/`。

脚本用**离线替身**驱动（真 `ToolExecutor` + 真 `creation_governance` 票据账本，
模型边界只回一条预置 tool_call），不触网、不写生产库。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "diagnostics" / "_tool_experience_loop_probe.py"


class TestOfflineProbeScript:
    def test_script_exists(self):
        assert SCRIPT.exists(), "只读取证脚本没落库，现场排障没有入口"

    def test_runs_standalone_and_emits_the_three_readings(self, tmp_path):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--json", "--workspace", str(tmp_path)],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=300,
        )
        assert result.returncode == 0, f"脚本跑不起来：{result.stderr[-2000:]}"
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        for key in ("ticket_lookup", "ticket_reason", "shape_violations", "outcome",
                    "ticket_evidenced", "evidence_rows"):
            assert key in payload, f"读数缺失：{key}"
        assert payload["evidence_rows"] >= 1, "离线替身一轮之后证据库没有行"

    def test_probe_leaves_no_artifacts_in_the_repo(self, tmp_path):
        """取证不得在仓库里长出 `data/agents/<id>/skills`。

        技能库路径在生产装配点里是相对路径，脚本若不在临时目录下跑，
        一次只读取证就会往仓库里落下 `data/agents/loop-probe-cli/skills`。
        """
        repo_agents = REPO_ROOT / "data" / "agents"
        before = {p.name for p in repo_agents.iterdir()} if repo_agents.exists() else set()
        subprocess.run(
            [sys.executable, str(SCRIPT), "--json"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=300,
        )
        after = {p.name for p in repo_agents.iterdir()} if repo_agents.exists() else set()
        assert after - before == set(), (
            f"只读取证在仓库里留下了目录/文件：{sorted(after - before)}"
        )

    def test_probe_never_points_at_the_production_db(self, tmp_path):
        """脚本必须把库落进临时目录，禁止把生产库路径写进代码。"""
        import ast

        tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
        offenders = [
            node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
            and node.value.startswith(("data/", "/data/"))
        ]
        assert offenders == [], f"脚本里出现生产库路径字面量：{offenders}"
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--json", "--workspace", str(tmp_path)],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=300,
        )
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        assert str(tmp_path) in payload["evidence_db"], (
            f"取证库没落在传入的临时目录：{payload['evidence_db']}"
        )
