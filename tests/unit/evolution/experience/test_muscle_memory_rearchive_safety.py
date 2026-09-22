"""008 残留 · 作废重攒必须**可回退**：归档即经 git 留底，不依赖 `.gitignore` 之外的幻影。

票据 008 要求现网脏条目「**作废重攒**，且作废动作可回退：归档名挂在原文件名之后
（`.pre-muscle-ngram-<UTC>` 形状），**不删除**」。

脚本已落库，但**可回退**这一半在原状下不成立：`agent_workspaces/` 被 `.gitignore`
整目录忽略，归档副本既不入版本库也不进任何留底，一旦有人 `git clean -xfd` 或换机器，
原始数据就永久消失——"可回退"变成只存在于注释里的承诺。

本文件把"可回退"钉成可验证事实：脚本必须把归档目标写到**版本库内**的留底目录，
且留底内容与源文件逐字节一致；`.gitignore` 不得吞掉留底路径。
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = REPO_ROOT / "scripts" / "diagnostics" / "muscle_memory_rearchive.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("_rearchive_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


DIRTY = [
    {"id": "deadbeef", "tool_name": "weather", "query_fingerprint": "许昌天气",
     "vector_fingerprint": "ab", "parameters": {"_raw": 'location="许昌"'},
     "result_summary": "", "level": "l2", "success_count": 2, "failure_count": 0,
     "consecutive_successes": 2},
]


class TestArchiveIsRecoverable:
    def test_archive_lands_inside_version_control(self, tmp_path, monkeypatch):
        module = _load_script()
        source = tmp_path / "agent_workspaces" / "kai" / "memory" / "muscle_memory"
        source.mkdir(parents=True)
        target = source / "muscle_l2.json"
        target.write_text(json.dumps(DIRTY), encoding="utf-8")

        ledger = tmp_path / "docs" / "05-reports" / "muscle-memory-ledger"
        monkeypatch.setattr(module, "LEDGER_DIR", ledger, raising=False)

        archived = module.archive_dirty_memory(target)

        assert archived is not None, "有脏条目却没归档"
        assert ledger in Path(archived).parents, (
            f"归档没落进版本库内的留底目录（可回退是幻影）：{archived}"
        )
        assert Path(archived).exists()
        assert json.loads(Path(archived).read_text(encoding="utf-8")) == DIRTY, (
            "留底内容与源文件不一致，回退不了"
        )

    def test_source_is_emptied_not_deleted(self, tmp_path, monkeypatch):
        module = _load_script()
        source = tmp_path / "ws" / "memory" / "muscle_memory"
        source.mkdir(parents=True)
        target = source / "muscle_l2.json"
        target.write_text(json.dumps(DIRTY), encoding="utf-8")
        monkeypatch.setattr(module, "LEDGER_DIR", tmp_path / "ledger", raising=False)

        module.archive_dirty_memory(target)

        assert target.exists(), "源文件被删了（票面要求不删除）"
        assert json.loads(target.read_text(encoding="utf-8")) == []

    def test_clean_file_is_left_alone(self, tmp_path, monkeypatch):
        module = _load_script()
        target = tmp_path / "muscle_l1.json"
        target.write_text("[]", encoding="utf-8")
        monkeypatch.setattr(module, "LEDGER_DIR", tmp_path / "ledger", raising=False)
        assert module.archive_dirty_memory(target) is None


class TestLedgerIsNotIgnored:
    def test_ledger_path_is_trackable(self):
        """`.gitignore` 不得吞掉留底路径——否则归档依旧只活在磁盘上。"""
        ledger_rel = "docs/05-reports/muscle-memory-ledger/probe.json"
        result = subprocess.run(
            ["git", "check-ignore", "-q", ledger_rel],
            cwd=REPO_ROOT, capture_output=True,
        )
        assert result.returncode != 0, f"留底路径被 .gitignore 忽略：{ledger_rel}"


class TestRsiGradientAccount:
    """008 要求的「阈值可达性重算 + ADR 0016 梯度账重验」必须可复算。

    ADR 0016 的结论是"11 颗参数里只剩 `muscle_memory_threshold` 一颗有真实梯度
    （起点 0.85 / setpoint 0.8）"。008 换了指纹口径与写侧参数形状之后，这条结论
    **不得默认仍成立**：阈值 0.8 → 0.85 只有在置信度落在开区间 (0.8, 0.85) 的
    真输入上才改变裁定。重算脚本给出这个带的实测规模，本用例把它钉成断言。
    """

    def test_report_runs_and_declares_its_denominator(self):
        import importlib.util

        script = REPO_ROOT / "scripts" / "diagnostics" / "muscle_memory_threshold_attainability.py"
        assert script.exists(), "阈值可达性重算脚本没落库"
        spec = importlib.util.spec_from_file_location("_attainability", script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        report = module.build_report()

        assert report["start"]["denominator"] == len(module.QUERY_PAIRS) > 0
        assert report["start"]["relevant_denominator"] > 0, "分母为零的读数等于没测"
        for block in (report["start"], report["setpoint"]):
            assert block["unrelated_false_positive"] == 0, (
                f"无关对照越过阈值 {block['threshold']}：阈值失去区分力"
            )
        assert report["gradient_band_population"] >= 0
        assert isinstance(report["decision_changes"], bool)

    def test_adr_records_the_recheck(self):
        adr = (REPO_ROOT / "docs" / "01-architecture" / "adr" / "0016-rsi-parameter-source-of-truth.md")
        text = adr.read_text(encoding="utf-8")
        assert "梯度账" in text and "重验" in text, (
            "ADR 0016 的梯度账没有随 008 的指纹换代重验（票面明令不得默认它仍成立）"
        )
        assert "muscle_memory_threshold_attainability" in text, (
            "ADR 里没有指向可复算的重验入口"
        )
