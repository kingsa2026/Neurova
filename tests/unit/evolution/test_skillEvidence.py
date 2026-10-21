"""闭环 B：失败与成功执行都落全量证据；证据可被装载消费。"""

from types import SimpleNamespace

import pytest

from neurova.evolution.skill_evidence import (
    MAX_EVIDENCE_FILES,
    failureEvidenceFor,
    failureJudgeFailures,
    loadExecutionEvidence,
    recordExecutionEvidence,
    scanForGraderVerdicts,
)


@pytest.fixture(autouse=True)
def _isolated_data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path))
    yield


def _failure(output: str = "x" * 5000, error: str = "password=hunter2"):
    return SimpleNamespace(
        success=False,
        data={"text": output},
        error=error,
        metadata={"tool": "echo"},
        execution_time=0.2,
    )


def test_failure_writes_full_evidence_and_redacts():
    result = recordExecutionEvidence(
        "agent", "sk",
        user_input="u" * 5000,
        params={"p": "v"},
        result=_failure(),
        context={"c": 1},
    )

    assert result["evidence_kind"] == "full_failure"
    assert result["evidence_ref"].endswith(".json")
    data = loadExecutionEvidence(result["evidence_ref"])
    assert data is not None
    assert len(data["output"]) > 2000
    assert "x" * 5000 in data["output"]
    assert "hunter2" not in data["error"]
    assert len(data["user_input"]) == 5000


def test_success_writes_full_evidence():
    result = recordExecutionEvidence(
        "agent", "sk",
        user_input="hello",
        params={"p": "v"},
        result=SimpleNamespace(success=True, data={"ok": 1}, error="", metadata={}),
    )
    assert result["evidence_kind"] == "full_success"
    assert result["evidence_ref"].endswith(".json")
    assert "hello" in result["input_summary"]
    loaded = loadExecutionEvidence(result["evidence_ref"])
    assert loaded["outcome"] == "success"


def test_evidence_retention_is_bounded():
    for index in range(MAX_EVIDENCE_FILES + 5):
        recordExecutionEvidence(
            "agent", "sk", user_input=str(index), params={}, result=_failure(output=str(index))
        )
    from neurova.core.data_root import dataPath
    from pathlib import Path

    files = list(Path(dataPath("evolution", "evidence", "agent", "sk")).glob("*.json"))
    assert len(files) == MAX_EVIDENCE_FILES


def test_load_rejects_path_escape():
    assert loadExecutionEvidence("../../etc/passwd") is None
    assert loadExecutionEvidence("/etc/passwd") is None


def test_failure_evidence_loader_prefers_full_file():
    written = recordExecutionEvidence(
        "agent", "sk", user_input="full-input", params={}, result=_failure()
    )
    record = SimpleNamespace(
        success=False,
        input_summary="summary-only",
        output_summary="summary-out",
        error_message="err",
        metadata={"evidence_ref": written["evidence_ref"]},
    )
    loaded = failureEvidenceFor([record])
    assert loaded and loaded[0]["user_input"] == "full-input"
    assert "x" * 5000 in loaded[0]["output"]


def test_artifact_refs_from_result_is_read_only(tmp_path, monkeypatch):
    import json
    from neurova.api.endpoints import artifacts_api

    source = tmp_path / "out.pdf"
    source.write_bytes(b"%PDF-1.4 test")
    monkeypatch.setattr(artifacts_api, "_allowed_roots", lambda: [tmp_path])

    refs = artifacts_api.artifact_refs_from_result(
        "file_write", json.dumps({"file_path": str(source)})
    )
    assert refs and refs[0]["name"] == "out.pdf"
    assert refs[0]["kind"] == "pdf"
    assert refs[0]["size"] == source.stat().st_size


def test_small_binary_is_copied_into_failure_evidence(tmp_path, monkeypatch):
    import os

    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
    source = tmp_path / "out.pdf"
    source.write_bytes(b"%PDF-1.4 binary")
    written = recordExecutionEvidence(
        "agent", "sk", user_input="task", params={},
        result=_failure(output="", error="boom"),
        trace=[{
            "tool": "file_write", "artifacts": [{
                "path": str(source), "name": "out.pdf", "kind": "pdf",
                "size": source.stat().st_size,
            }],
        }],
    )
    data = loadExecutionEvidence(written["evidence_ref"])
    copied = data["tool_trace"][0]["artifacts"][0]["evidence_copy"]
    assert os.path.exists(os.path.join(os.environ["NEUROVA_DATA_DIR"], copied))


def test_grader_verdict_tripwire_is_narrow_and_warn_only(caplog):
    assert scanForGraderVerdicts('{"pass_rate": 0.9}') == ["pass_rate"]
    assert scanForGraderVerdicts("普通技能正文，提到 rubric 与 score") == []

    written = recordExecutionEvidence(
        "agent", "sk", user_input="task", params={},
        result=_failure(output="pass_rate=0.9", error=""),
    )
    record = SimpleNamespace(
        success=False, input_summary="task", output_summary="out",
        error_message="", metadata={"evidence_ref": written["evidence_ref"]},
    )
    import logging

    with caplog.at_level(logging.WARNING):
        failures = failureJudgeFailures([record])
    assert len(failures) == 1
    assert any("评分器结论标记" in item.message for item in caplog.records)


def test_record_skill_usage_links_evidence_ref(monkeypatch):
    from neurova.evolution.skill_recording import recordSkillUsage

    captured = {}
    monkeypatch.setattr(
        "neurova.evolution.skill_improver.get_skill_improver",
        lambda: SimpleNamespace(record_usage=lambda **kwargs: captured.update(kwargs)),
    )
    monkeypatch.setattr(
        "neurova.skills.library_service.agentLibrary",
        lambda *a, **k: SimpleNamespace(record_skill_usage=lambda *a, **k: None),
    )
    monkeypatch.setattr(
        "neurova.evolution.skill_experience.get_skill_experience_store",
        lambda: SimpleNamespace(record_usage=lambda *a, **k: None),
    )
    agent = SimpleNamespace(
        config=SimpleNamespace(agent_id="agent"), _current_user_input="查天气"
    )
    skill = SimpleNamespace(name="sk", config={})

    recordSkillUsage(agent, skill, _failure(), params={"city": "北京"})

    assert captured["metadata"]["evidence_kind"] == "full_failure"
    assert captured["metadata"]["evidence_ref"].endswith(".json")
