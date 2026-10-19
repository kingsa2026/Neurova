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
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "diagnostics" / "_tool_experience_loop_probe.py"
#: 取证锚点，必须写在模块级：绑在函数里的名字，面自证棘轮的取数口认不出，整档会静默掉出它的面。
REPO_AGENTS = REPO_ROOT / "data" / "agents"


def runProbeScript(*args: str, timeout: int = 300):
    """起真脚本收文本读数的唯一出口——**两头都钉**，与调用方怎么起的无关。

    只钉父端（`encoding="utf-8"`）是 §6-64 说的半修：子进程仍按本机码页写；只钉子端则父进程
    按 `locale.getpreferredencoding()` 解。而本仓跑测常带 `PYTHONIOENCODING=utf-8`：那种组合下
    reader 线程直接 UnicodeDecodeError、`proc.stdout` 变成 None，判据于是报
    `TypeError: can only concatenate str`——看着像被测对象坏了，其实是这条契约没在自己手里。
    """
    childEnv = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=REPO_ROOT,
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, env=childEnv)


class TestOfflineProbeScript:
    def test_script_exists(self):
        assert SCRIPT.exists(), "只读取证脚本没落库，现场排障没有入口"

    def test_runs_standalone_and_emits_the_three_readings(self, tmp_path):
        result = runProbeScript("--json", "--workspace", str(tmp_path))
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
        before = {p.name for p in REPO_AGENTS.iterdir()} if REPO_AGENTS.exists() else set()
        assert len(before) > 5, (
            f"取证前仓内 agents 目录现读 {len(before)} 个条目（锚＝{REPO_AGENTS}）——"
            "锚指错或目录缺席时 before/after 都是空集，「没留下 artifacts」这句判定根本不来自代码")
        runProbeScript("--json")
        after = {p.name for p in REPO_AGENTS.iterdir()} if REPO_AGENTS.exists() else set()
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
        result = runProbeScript("--json", "--workspace", str(tmp_path))
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        assert str(tmp_path) in payload["evidence_db"], (
            f"取证库没落在传入的临时目录：{payload['evidence_db']}"
        )
