"""技能执行证据：失败与成功都落全量轨迹（有界），产物带 hash 清单。

失败证据落 `data/evolution/evidence/<agent>/<skill>/`，成功落同目录 `success/`，
两者都供审计面读取；每技能分别保留 100 份失败与 20 份成功。所有字段写入前
脱敏、截断；小产物复制进证据包，大产物保留路径 + SHA-256 引用。
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Iterable, Optional

from neurova.core.data_root import dataPath, get_data_root
from neurova.skills.evolution_inputs_guard import bound_text, redact_secrets

FULL_FIELD_CAP = 50_000
MAX_EVIDENCE_FILES = 100
MAX_SUCCESS_EVIDENCE_FILES = 20
ARTIFACT_COPY_MAX_BYTES = 2_000_000
ARTIFACT_COPY_MAX_FILES = 5
ARTIFACT_COPY_TOTAL_BYTES = 10_000_000
ARTIFACT_HASH_MAX_BYTES = 64_000_000
_SAFE = re.compile(r"[^\w.-]")

# C6：窄标记，只认评分器结论，不把 rubric/score 这类常见词算进来（warn-only）。
GRADER_VERDICT_MARKERS = (
    "deterministic_eval_summary",
    "deterministic_eval_result",
    "judge_scope_and_deterministic_status",
    "passed_count",
    "pass_rate",
    "test_pass_rate",
)


def scanForGraderVerdicts(value: Any) -> list[str]:
    """扫描一段证据里的评分器结论标记；只返回命中标记，不阻断。"""
    if value is None:
        return []
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        except (TypeError, ValueError):
            text = repr(value)
    return [marker for marker in GRADER_VERDICT_MARKERS if marker in text]


def summarizeSkillIO(value: Any, *, max_chars: int = 2000) -> str:
    """把一次技能执行的输入/产物压成有界、脱敏的证据摘要。"""
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        except (TypeError, ValueError):
            text = repr(value)
    return bound_text(redact_secrets(text), max_chars=max_chars)


def _full(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        except (TypeError, ValueError):
            text = repr(value)
    return bound_text(redact_secrets(text), max_chars=FULL_FIELD_CAP)


def _safe(value: Any) -> str:
    cleaned = _SAFE.sub("_", str(value or "")).strip("._") or "_"
    return cleaned[:80]


def _outputOf(result: Any) -> Any:
    value = getattr(result, "data", None)
    if value is None:
        value = getattr(result, "output", None)
    return value


def _sanitizeTrace(trace: list) -> list[dict]:
    out: list[dict] = []
    for item in list(trace or [])[:100]:
        if not isinstance(item, dict):
            continue
        entry = {
            "tool": str(item.get("tool") or ""),
            "layer": str(item.get("layer") or ""),
            "params": bound_text(
                redact_secrets(str(item.get("params") or "")), max_chars=500
            ),
            "success": item.get("success"),
            "error": bound_text(
                redact_secrets(str(item.get("error") or "")), max_chars=300
            ),
            "duration_ms": item.get("duration_ms", 0),
        }
        artifacts = []
        for art in list(item.get("artifacts") or [])[:8]:
            if not isinstance(art, dict):
                continue
            artifacts.append(
                {
                    "path": str(art.get("path") or ""),
                    "name": str(art.get("name") or ""),
                    "kind": str(art.get("kind") or ""),
                    "size": int(art.get("size") or 0),
                }
            )
        if artifacts:
            entry["artifacts"] = artifacts
        out.append(entry)
    return out


def _sha256Of(path: Path, size: int) -> str:
    if size <= 0 or size > ARTIFACT_HASH_MAX_BYTES:
        return ""
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return ""
    return digest.hexdigest()


def _materializeTraceArtifacts(trace: list[dict], directory: Path) -> list[dict]:
    """把 trace 里的产物落成可追溯清单（每文件 2MB、最多 5 个/10MB 复制）。"""
    target_dir = directory / "artifacts"
    total = 0
    copied = 0
    copied_paths: dict[str, str] = {}
    inventory: list[dict] = []
    for entry in trace:
        for art in entry.get("artifacts") or []:
            source = Path(str(art.get("path") or ""))
            try:
                exists = source.is_file()
            except OSError:
                exists = False
            if not exists:
                art["storage"] = "missing"
                art["sha256"] = ""
                inventory.append(dict(art))
                continue
            try:
                size = source.stat().st_size
            except OSError:
                art["storage"] = "missing"
                art["sha256"] = ""
                inventory.append(dict(art))
                continue
            art["size"] = size
            art["sha256"] = _sha256Of(source, size)
            if size > ARTIFACT_HASH_MAX_BYTES:
                art["hash_skipped"] = "too_large"
            key = str(source.resolve())
            if key in copied_paths:
                art["evidence_copy"] = copied_paths[key]
                art["storage"] = "copied"
                inventory.append(dict(art))
                continue
            if (size > 0 and size <= ARTIFACT_COPY_MAX_BYTES
                    and copied < ARTIFACT_COPY_MAX_FILES
                    and total < ARTIFACT_COPY_TOTAL_BYTES):
                try:
                    target_dir.mkdir(parents=True, exist_ok=True)
                    dest = target_dir / source.name
                    if dest.exists():
                        dest = target_dir / f"{source.stem}-{uuid.uuid4().hex[:6]}{source.suffix}"
                    shutil.copy2(source, dest)
                    art["evidence_copy"] = dest.relative_to(get_data_root()).as_posix()
                    art["storage"] = "copied"
                    copied_paths[key] = art["evidence_copy"]
                    total += size
                    copied += 1
                except (OSError, ValueError):
                    art["storage"] = "reference"
            else:
                art["storage"] = "reference"
            inventory.append(dict(art))
    return inventory


def _evidenceDir(agent_id: str, skill_id: str) -> Path:
    return Path(dataPath("evolution", "evidence", _safe(agent_id), _safe(skill_id)))


def _prune(directory: Path, keep: int) -> bool:
    try:
        files = sorted(directory.glob("*.json"))
    except OSError:
        return False
    removed = False
    for stale in files[:-max(1, int(keep))]:
        try:
            stale.unlink()
            removed = True
        except OSError:
            pass
    return removed


def _pruneArtifacts(directory: Path) -> None:
    """删掉已不在保留证据里的产物副本（共享 artifacts 目录的配额回收）。"""
    artifact_dir = directory / "artifacts"
    try:
        if not artifact_dir.is_dir():
            return
        referenced: set[str] = set()
        for evidence_file in directory.glob("*.json"):
            try:
                payload = json.loads(evidence_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, ValueError):
                continue
            for entry in payload.get("tool_trace") or []:
                for art in (entry or {}).get("artifacts") or []:
                    copied = str((art or {}).get("evidence_copy") or "")
                    if copied:
                        referenced.add(Path(copied).name)
        for artifact in artifact_dir.iterdir():
            if artifact.is_file() and artifact.name not in referenced:
                try:
                    artifact.unlink()
                except OSError:
                    pass
    except OSError:
        return


def recordExecutionEvidence(
    agent_id: str,
    skill_id: str,
    *,
    user_input: str = "",
    params: Any = None,
    result: Any = None,
    context: Any = None,
    trace: Optional[list] = None,
) -> dict:
    """写一条执行证据；成功与失败都落全量文件（有界），返回摘要与引用。"""
    input_summary = summarizeSkillIO({"user_input": user_input or "", "params": params})
    output_summary = summarizeSkillIO(_outputOf(result))
    trace = list(trace or [])
    success = bool(getattr(result, "success", False))
    evidence_kind = "full_success" if success else "full_failure"
    directory = _evidenceDir(agent_id, skill_id)
    if success:
        directory = directory / "success"
    trace_payload = _sanitizeTrace(trace)
    payload = {
        "v": 2,
        "ts": time.time(),
        "outcome": "success" if success else "failure",
        "agent_id": str(agent_id or ""),
        "skill_id": str(skill_id or ""),
        "user_input": _full(user_input),
        "params": _full(params),
        "error": _full(getattr(result, "error", "")),
        "output": _full(_outputOf(result)),
        "metadata": _full(getattr(result, "metadata", None)),
        "context": _full(context),
        "tool_trace": trace_payload,
    }
    try:
        directory.mkdir(parents=True, exist_ok=True)
        payload["artifacts"] = _materializeTraceArtifacts(trace_payload, directory)
        name = (
            f"{'success' if success else 'failure'}-"
            f"{time.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}.json"
        )
        path = directory / name
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        if _prune(directory, MAX_SUCCESS_EVIDENCE_FILES if success else MAX_EVIDENCE_FILES):
            _pruneArtifacts(directory)
        ref = path.relative_to(get_data_root()).as_posix()
    except (OSError, ValueError):
        return {
            "input_summary": input_summary,
            "output_summary": output_summary,
            "evidence_kind": "summary" if success else "full_failure",
            "evidence_ref": "",
            "tool_trace_count": len(trace),
        }
    return {
        "input_summary": input_summary,
        "output_summary": output_summary,
        "evidence_kind": evidence_kind,
        "evidence_ref": ref,
        "tool_trace_count": len(trace),
    }


def loadExecutionEvidence(ref: str) -> Optional[dict]:
    """读取证据文件；路径越界或坏 JSON 返回 None。"""
    raw = str(ref or "").strip().replace("\\", "/")
    if not raw or raw.startswith("/") or ".." in raw.split("/"):
        return None
    root = get_data_root().resolve()
    candidate = (root / raw).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    try:
        data = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def failureEvidenceFor(records: Iterable[Any], *, limit: int = 5) -> list[dict]:
    """把失败使用记录（含 evidence_ref）装载成变异器可消费的证据列表。"""
    out: list[dict] = []
    for record in records:
        if getattr(record, "success", True):
            continue
        ref = (getattr(record, "metadata", None) or {}).get("evidence_ref")
        data = loadExecutionEvidence(ref) if ref else None
        item = {
            "user_input": (data or {}).get("user_input") or getattr(record, "input_summary", ""),
            "output": (data or {}).get("output") or getattr(record, "output_summary", ""),
            "error": (data or {}).get("error") or getattr(record, "error_message", ""),
            "evidence_ref": ref or "",
            "tool_trace": (data or {}).get("tool_trace") or [],
        }
        item["grader_leak_suspected"] = scanForGraderVerdicts(
            "\n".join(str(item[key]) for key in ("user_input", "output", "error"))
        )
        out.append(item)
        if len(out) >= max(1, int(limit)):
            break
    return out


def failureJudgeFailures(records: Iterable[Any], *, limit: int = 5) -> list:
    """把失败证据转成 runner 的 JudgeFailure 列表（自动/人工两条 service 路径共用）。

    C6：证据里出现评分器结论标记时只记 warning（warn-only），不阻断；
    命中项仍作为普通失败证据进入变异器。
    """
    from neurova.core.logger import get_logger
    from neurova.evolution.eval.mutator import JudgeFailure

    failures = []
    for item in failureEvidenceFor(records, limit=limit):
        hits = item.get("grader_leak_suspected") or []
        if hits:
            get_logger(__name__).warning(
                "失败证据含评分器结论标记（warn-only）: markers=%s ref=%s",
                ",".join(hits), item.get("evidence_ref", ""),
            )
        failures.append(
            JudgeFailure(
                task_input=item["user_input"] or "(未记录输入)",
                output=item["output"] or "(无输出)",
                feedback=item["error"] or "",
                score=0.0,
                tool_trace=list(item.get("tool_trace") or []),
            )
        )
    return failures


def executionEvidenceFor(
    records: Iterable[Any],
    *,
    kind: str = "all",
    limit: int = 5,
    agent_id: str = "",
) -> list[dict]:
    """把成功/失败使用记录装载成可审计的完整证据列表。

    `kind` 限定 success/failure/all；记录里的 agent_id 与入参不一致时跳过
    （旧记录没记 agent_id 的不被藏起来）。
    """
    if kind not in ("success", "failure", "all"):
        raise ValueError("kind 取值: success|failure|all")
    out: list[dict] = []
    for record in records:
        success = bool(getattr(record, "success", False))
        if kind == "success" and not success:
            continue
        if kind == "failure" and success:
            continue
        metadata = getattr(record, "metadata", None) or {}
        record_agent = str(metadata.get("agent_id") or "")
        if agent_id and record_agent and record_agent != agent_id:
            continue
        ref = str(metadata.get("evidence_ref") or "")
        data = loadExecutionEvidence(ref) if ref else None
        out.append({
            "outcome": "success" if success else "failure",
            "evidence_kind": "full" if data else "summary",
            "evidence_ref": ref,
            "user_input": (data or {}).get("user_input") or getattr(record, "input_summary", ""),
            "params": (data or {}).get("params", ""),
            "output": (data or {}).get("output") or getattr(record, "output_summary", ""),
            "error": (data or {}).get("error") or getattr(record, "error_message", ""),
            "metadata": (data or {}).get("metadata", ""),
            "context": (data or {}).get("context", ""),
            "tool_trace": (data or {}).get("tool_trace") or [],
            "artifacts": (data or {}).get("artifacts") or [],
            "ts": (data or {}).get("ts"),
        })
        if len(out) >= max(1, int(limit)):
            break
    return out


def successEvidenceFor(records: Iterable[Any], *, limit: int = 5,
                       agent_id: str = "") -> list[dict]:
    """把成功使用记录（含 evidence_ref）装载成完整轨迹列表。"""
    return executionEvidenceFor(records, kind="success", limit=limit, agent_id=agent_id)
