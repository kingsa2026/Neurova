"""Integration Tests for LLM Cost Control Guards (Node scripts)

系统两个 CI 防护脚本是 Node.js（scripts/guard-*.cjs），无法用 Python import。
正确测法：用 subprocess 调用真实脚本、喂入 fixture 文件、断言退出码与输出，
从而验证真实产物，而非在 Python 里重写一份假的检测逻辑。
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
BIG_BRAIN = REPO_ROOT / "scripts" / "guard-big-brain.cjs"
TRACKING = REPO_ROOT / "scripts" / "guard-llm-tracked.cjs"

# 无 node 时跳过（诚实标注：脚本为 Node 产物，非 Python）
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node runtime not available")


def _run(script: Path, target: Path):
    """运行 guard 脚本，返回 (exit_code, stdout+stderr)。"""
    proc = subprocess.run(
        [NODE, str(script), str(target)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return proc.returncode, (proc.stdout + proc.stderr)


@pytest.fixture
def big_brain_violation_file(tmp_path):
    """昂贵模型用在被禁上下文的真实 API 调用（应被 big-brain 命中）。"""
    f = tmp_path / "bad_triage.py"
    f.write_text(
        "async def triage(messages):\n"
        "    resp = await client.chat.completions.create(model='gpt-4', messages=messages)\n"
        "    return resp\n",
        encoding="utf-8",
    )
    return f


@pytest.fixture
def big_brain_clean_file(tmp_path):
    """小模型调用（big-brain 应放行）。"""
    f = tmp_path / "ok_classify.py"
    f.write_text(
        "async def classify(messages):\n"
        "    resp = await client.chat.completions.create(model='gpt-3.5-turbo', messages=messages)\n"
        "    return resp\n",
        encoding="utf-8",
    )
    return f


@pytest.fixture
def untracked_call_file(tmp_path):
    """未加装饰器的生产 LLM 调用（tracking 应命中）。"""
    f = tmp_path / "untracked.py"
    f.write_text(
        "async def do_work(messages):\n"
        "    resp = await client.chat.completions.create(model='gpt-3.5-turbo', messages=messages)\n"
        "    return resp\n",
        encoding="utf-8",
    )
    return f


@pytest.fixture
def tracked_call_file(tmp_path):
    """已加 @track_llm_call 装饰器（tracking 应放行）。"""
    f = tmp_path / "tracked.py"
    f.write_text(
        "@track_llm_call(provider='openai', model='gpt-4', agent_id='x')\n"
        "async def do_work(messages):\n"
        "    resp = await client.chat.completions.create(model='gpt-4', messages=messages)\n"
        "    return resp\n",
        encoding="utf-8",
    )
    return f


# ── 脚本存在性 ──────────────────────────────────────────────────────────


def test_guard_scripts_exist():
    assert BIG_BRAIN.exists(), "guard-big-brain.cjs 缺失"
    assert TRACKING.exists(), "guard-llm-tracked.cjs 缺失"


# ── Big-brain guard 行为 ───────────────────────────────────────────────


class TestBigBrainGuard:
    def test_flags_expensive_model_in_triage(self, big_brain_violation_file):
        code, out = _run(BIG_BRAIN, big_brain_violation_file)
        assert code != 0, "昂贵模型用于 triage 应被判定违规（非零退出）"
        assert "violation" in out.lower() or "gpt-4" in out.lower()

    def test_allows_small_model(self, big_brain_clean_file):
        code, out = _run(BIG_BRAIN, big_brain_clean_file)
        assert code == 0, "小模型调用应通过 big-brain 检查"


# ── Tracking guard 行为 ────────────────────────────────────────────────


class TestTrackingGuard:
    def test_flags_untracked_call(self, untracked_call_file):
        code, out = _run(TRACKING, untracked_call_file)
        assert code != 0, "未追踪 LLM 调用应被判定违规（非零退出）"

    def test_allows_decorated_call(self, tracked_call_file):
        code, out = _run(TRACKING, tracked_call_file)
        assert code == 0, "带 @track_llm_call 装饰器的调用应通过检查"


# ── 全库扫描（回归：现网必须 0 违规） ───────────────────────────────────


@pytest.mark.slow
def test_full_repo_scan_big_brain_clean():
    """扫描真实 neurova 包：big-brain 必须 0 违规（CI 等价）。"""
    code, out = _run(BIG_BRAIN, REPO_ROOT / "neurova")
    assert code == 0, f"big-brain 全库扫描出现违规:\n{out[-800:]}"


@pytest.mark.slow
def test_full_repo_scan_tracking_clean():
    """扫描真实 neurova 包：tracking 必须 0 违规（CI 等价）。"""
    code, out = _run(TRACKING, REPO_ROOT / "neurova")
    assert code == 0, f"tracking 全库扫描出现违规:\n{out[-800:]}"
