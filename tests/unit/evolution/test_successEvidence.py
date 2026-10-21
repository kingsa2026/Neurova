"""成功轨迹落全量证据；大产物以 hash + 引用入清单，小产物复制。"""

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from neurova.evolution.skill_evidence import (
    MAX_SUCCESS_EVIDENCE_FILES,
    loadExecutionEvidence,
    recordExecutionEvidence,
    successEvidenceFor,
)


@pytest.fixture(autouse=True)
def _isolated_data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
    yield


def _success(output: str = "ok"):
    return SimpleNamespace(
        success=True,
        data={"text": output},
        error="",
        metadata={"m": 1},
        execution_time=0.1,
    )


def _artifact(path: Path):
    return {
        "path": str(path),
        "name": path.name,
        "kind": path.suffix.lstrip("."),
        "size": path.stat().st_size,
    }


def test_success_writes_full_evidence_and_loads_back():
    written = recordExecutionEvidence(
        "agent",
        "sk",
        user_input="hello",
        params={"p": "v"},
        result=_success("full output"),
        context={"c": 1},
    )

    assert written["evidence_kind"] == "full_success"
    assert written["evidence_ref"]
    data = loadExecutionEvidence(written["evidence_ref"])
    assert data is not None
    assert data["outcome"] == "success"
    assert data["user_input"] == "hello"
    assert "full output" in data["output"]
    assert data["context"]


def test_success_retention_is_bounded():
    for index in range(MAX_SUCCESS_EVIDENCE_FILES + 3):
        recordExecutionEvidence(
            "agent", "sk", user_input=str(index), params={}, result=_success(str(index))
        )

    from neurova.core.data_root import dataPath

    files = list(
        Path(dataPath("evolution", "evidence", "agent", "sk", "success")).glob("*.json")
    )
    assert len(files) == MAX_SUCCESS_EVIDENCE_FILES


def test_small_artifact_is_copied_with_digest(tmp_path):
    source = tmp_path / "small.txt"
    source.write_bytes(b"small artifact")
    written = recordExecutionEvidence(
        "agent",
        "sk",
        user_input="task",
        params={},
        result=_success("ok"),
        trace=[{"tool": "file_write", "artifacts": [_artifact(source)]}],
    )

    data = loadExecutionEvidence(written["evidence_ref"])
    art = data["tool_trace"][0]["artifacts"][0]
    assert art["storage"] == "copied"
    assert art["evidence_copy"]
    assert art["sha256"] == hashlib.sha256(b"small artifact").hexdigest()


def test_large_artifact_keeps_digest_and_reference(tmp_path):
    source = tmp_path / "big.bin"
    source.write_bytes(b"x" * 3_000_000)
    written = recordExecutionEvidence(
        "agent",
        "sk",
        user_input="task",
        params={},
        result=_success("ok"),
        trace=[{"tool": "file_write", "artifacts": [_artifact(source)]}],
    )

    data = loadExecutionEvidence(written["evidence_ref"])
    art = data["tool_trace"][0]["artifacts"][0]
    assert art["storage"] == "reference"
    assert "evidence_copy" not in art
    assert art["sha256"] == hashlib.sha256(b"x" * 3_000_000).hexdigest()
    assert data["artifacts"][0]["storage"] == "reference"


def test_success_evidence_loader_returns_full_record():
    written = recordExecutionEvidence(
        "agent", "sk", user_input="hello", params={}, result=_success("answer")
    )
    record = SimpleNamespace(
        success=True,
        input_summary="summary",
        output_summary="summary",
        error_message="",
        metadata={"evidence_ref": written["evidence_ref"]},
    )

    items = successEvidenceFor([record])

    assert len(items) == 1
    assert items[0]["user_input"] == "hello"
    assert "answer" in items[0]["output"]
    assert items[0]["outcome"] == "success"


def test_pruned_success_evidence_removes_orphan_artifact_copies(tmp_path):
    sources = []
    for index in range(MAX_SUCCESS_EVIDENCE_FILES + 2):
        source = tmp_path / f"artifact-{index}.txt"
        source.write_bytes(f"payload-{index}".encode())
        sources.append(source)
        recordExecutionEvidence(
            "agent",
            "sk",
            user_input=str(index),
            params={},
            result=_success(str(index)),
            trace=[{"tool": "file_write", "artifacts": [_artifact(source)]}],
        )

    from neurova.core.data_root import dataPath

    artifact_dir = Path(
        dataPath("evolution", "evidence", "agent", "sk", "success", "artifacts")
    )
    kept = {p.name for p in artifact_dir.glob("*") if p.is_file()}
    assert len(kept) == MAX_SUCCESS_EVIDENCE_FILES
