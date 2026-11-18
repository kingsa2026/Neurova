"""QwenPaw 对照批 C6：覆盖率棘轮 + 前端 bundle 预算门。

- 棘轮判定纯函数四态：退步红 / 低于下限红 / 持平绿上调 / 超越绿上调；
- bundle 计量：只统计 JS/CSS（gzip KB）、目录缺失走标定态；
- 预算判定：未标定（null）→ 标定态通过；超限 → 红；
- CI 接线钉住：ci.yml 的 coverage job 必须有棘轮步、frontend job 必须有
  build+预算步（接线被删即红）。
"""

import json
from pathlib import Path

import pytest
import yaml

from neurova.ci.bundle_budget_core import collectBundleStats, judgeBudget
from neurova.ci.ci_ratchet_core import judgeAndUpdate


class TestRatchetJudge:

    def test_regression_is_red(self):
        passed, record = judgeAndUpdate(58.0, 61.0, floor=60.0)
        assert passed is False and record == 61.0

    def test_below_floor_is_red_even_without_ratchet(self):
        passed, record = judgeAndUpdate(59.0, 59.0, floor=60.0)
        assert passed is False and record == 59.0

    def test_equal_passes_and_bumps(self):
        passed, record = judgeAndUpdate(61.0, 61.0, floor=60.0)
        assert passed is True and record == 61.0

    def test_improvement_passes_and_bumps(self):
        passed, record = judgeAndUpdate(63.5, 61.0, floor=60.0)
        assert passed is True and record == 63.5


class TestBundleStats:

    def test_only_js_css_counted(self, tmp_path):
        (tmp_path / "assets").mkdir()
        (tmp_path / "assets" / "index.js").write_bytes(b"a" * 2048)
        (tmp_path / "assets" / "style.css").write_bytes(b"b" * 1024)
        (tmp_path / "notes.txt").write_bytes(b"c" * 9999)
        stats = collectBundleStats(tmp_path)
        assert stats["missing"] is False
        assert len(stats["files"]) == 2
        assert stats["total_gzip_kb"] == pytest.approx(
            sum(f["gzip_kb"] for f in stats["files"]))

    def test_missing_dir_is_calibration_shape(self, tmp_path):
        stats = collectBundleStats(tmp_path / "nope")
        assert stats["missing"] is True and stats["total_gzip_kb"] == 0


class TestBudgetJudge:

    def test_none_budget_is_calibration_pass(self):
        ok, mode = judgeBudget(123.4, None)
        assert ok is True and mode == "calibrate"

    def test_over_budget_is_red(self):
        ok, mode = judgeBudget(200.0, 150.0)
        assert ok is False and mode == "over_budget"

    def test_within_budget_is_ok(self):
        ok, mode = judgeBudget(100.0, 150.0)
        assert ok is True and mode == "ok"


class TestCiWiring:

    @pytest.fixture
    def ci_jobs(self):
        data = yaml.safe_load(
            Path(".github/workflows/ci.yml").read_text(encoding="utf-8"))
        return data["jobs"]

    def test_coverage_job_has_ratchet_step(self, ci_jobs):
        steps = json.dumps(ci_jobs["coverage"]["steps"], ensure_ascii=False)
        assert "coverage_ratchet" in steps, "coverage job 必须接覆盖率棘轮步"

    def test_frontend_job_has_build_and_budget(self, ci_jobs):
        steps = json.dumps(ci_jobs["frontend"]["steps"], ensure_ascii=False)
        assert "vite build" in steps or "npm run build" in steps, "frontend 必须构建产物"
        assert "bundle_budget" in steps, "frontend 必须接 bundle 预算步"

    def test_ratchet_file_seeded_at_floor(self):
        data = json.loads(
            Path("scripts/ci/coverage_ratchet.json").read_text(encoding="utf-8"))
        assert data["fail_under"] >= 60
