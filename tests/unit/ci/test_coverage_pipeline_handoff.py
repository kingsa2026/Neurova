from pathlib import Path

import yaml
from coverage import Coverage

from scripts.ci import coverage_ratchet, coverage_report


def _writeCoverageFile(target: Path) -> None:
    source = target.parent / "sample.py"
    source.write_text("def value():\n    return 1\n\nvalue()\n", encoding="utf-8")
    measured = Coverage(data_file=str(target), config_file=False)
    measured.start()
    exec(compile(source.read_text(encoding="utf-8"), str(source), "exec"), {})
    measured.stop()
    measured.save()


def testCoverageReportPreservesMergedFileForRatchet(tmp_path):
    shardDir = tmp_path / "coverage"
    shardDir.mkdir()
    _writeCoverageFile(shardDir / ".coverage.test")
    merged = shardDir / ".coverage.merged"

    exitCode = coverage_report.main(
        ["--data-dir", str(shardDir), "--merged", str(merged), "--fail-under", "0"]
    )

    assert exitCode == 0
    assert merged.is_file(), "合判脚本删除了后续覆盖率棘轮要读取的合并文件"


def testCoverageRatchetConsumesMergedFile(tmp_path):
    merged = tmp_path / ".coverage.merged"
    _writeCoverageFile(merged)
    ratchet = tmp_path / "ratchet.json"

    exitCode = coverage_ratchet.main(
        ["--merged", str(merged), "--ratchet", str(ratchet), "--floor", "0"]
    )

    assert exitCode == 0
    assert ratchet.is_file()


def testCoverageWorkflowHandsOffMergedFile():
    workflow = yaml.safe_load(
        Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    )
    commands = [str(step.get("run", "")) for step in workflow["jobs"]["coverage"]["steps"]]
    ratchetCommand = next(command for command in commands if "coverage_ratchet.py" in command)
    assert "--merged data/coverage/.coverage.merged" in ratchetCommand
