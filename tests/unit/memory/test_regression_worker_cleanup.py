"""Timeout regression tests must release their own blocked worker before exit."""
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[3]


def test_hung_channel_regression_exits_cleanly(tmp_path):
    script = """
import runpy
import sys
sys.path.insert(0, sys.argv[1])
ns = runpy.run_path(sys.argv[2])
ns['TestBug8AsCompletedMissingTimeout']().test_hung_channel_does_not_cause_permanent_hang()
print('CASE_FINISHED', flush=True)
"""
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    command = [sys.executable, "-c", script, str(ROOT), str(
        ROOT / "tests/unit/memory/test_neurova_recall_audit2_bugfix.py")]
    # A passed assertion is insufficient: the interpreter must also exit.
    result = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True,
                            text=True, encoding="utf-8", timeout=12)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "CASE_FINISHED" in result.stdout
