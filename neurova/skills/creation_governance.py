"""Server-owned execution evidence and conservative structural skill identity.

No model-supplied counters are accepted. SQLite serializes creation across service
instances/processes; manifests remain in place, including all historical entries.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import copy
import hashlib
import json
import sqlite3
import threading
import uuid

MIN_SUCCESSES = 3
_locks = {}
_locks_guard = threading.RLock()
_execution = ContextVar("skill_creation_execution", default=None)


def normalize_steps(steps):
    if not isinstance(steps, list) or not steps:
        return []
    normalized = []
    for step in steps:
        if isinstance(step, str):
            tool, params = step, {}
        elif isinstance(step, dict):
            tool = step.get("tool") or step.get("name") or step.get("tool_name")
            params = step.get("params", step.get("parameters", {}))
        else:
            raise ValueError("Invalid skill step")
        if not isinstance(tool, str) or not tool.strip() or not isinstance(params, dict):
            raise ValueError("Invalid skill tool/params")
        # Do not trim parameter values, sort steps, or discard repeated tools.
        normalized.append({"tool": tool.strip(), "params": copy.deepcopy(params)})
    return normalized


def fingerprint(steps, purpose=""):
    steps = normalize_steps(steps)
    if not steps:
        return None
    identity = {"steps": steps}
    if not any(step["params"] for step in steps):
        # A bare tool list is not sufficient to infer business equivalence.
        identity["purpose"] = " ".join(str(purpose or "").casefold().split())
        if not identity["purpose"]:
            return None
    return hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def shared_lock(directory):
    key = str(directory.resolve()).casefold()
    with _locks_guard:
        return _locks.setdefault(key, threading.RLock())


class EvidenceStore:
    def __init__(self, directory, agent_id):
        self.directory, self.agent_id = directory, agent_id
        self.lock = shared_lock(directory)

    @contextmanager
    def transaction(self):
        with self.lock:
            db = sqlite3.connect(str(self.directory / ".creation.sqlite3"), timeout=30)
            try:
                db.execute("CREATE TABLE IF NOT EXISTS evidence (agent TEXT, fingerprint TEXT, task TEXT, "
                           "success INTEGER NOT NULL, PRIMARY KEY(agent, fingerprint, task))")
                db.execute("BEGIN IMMEDIATE")
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise
            finally:
                db.close()

    def record(self, task_id, steps, purpose, success):
        key = fingerprint(steps, purpose)
        if not isinstance(task_id, str) or not task_id or not key:
            return False
        with self.transaction() as db:
            # Failure is sticky: replay/retry cannot convert a failed task into a vote.
            db.execute("INSERT INTO evidence VALUES (?, ?, ?, ?) ON CONFLICT(agent,fingerprint,task) "
                       "DO UPDATE SET success=MIN(success,excluded.success)",
                       (self.agent_id, key, task_id, int(success is True)))
        return True

    def task_results(self, steps, purpose="", db=None):
        if db is None:
            with self.transaction() as connection:
                return self.task_results(steps, purpose, connection)
        return dict(db.execute(
            "SELECT task, success FROM evidence WHERE agent=? AND fingerprint=?",
            (self.agent_id, fingerprint(steps, purpose))))

    def success_tasks(self, steps, purpose="", db=None):
        return [task for task, success in self.task_results(steps, purpose, db).items() if success]

    def eligible(self, steps, purpose="", db=None):
        return len(self.success_tasks(steps, purpose, db)) >= MIN_SUCCESSES


def begin_task():
    # Server allocated, request-local, unaffected by global session turn counters.
    _execution.set({"id": uuid.uuid4().hex, "steps": [], "success": True,
                    "closed": False, "lock": threading.RLock()})


def record_tool_execution(tool_name, params, success, result):
    task = _execution.get()
    if task is None or tool_name == "create_skill":
        return
    from neurova.security.governance import is_policy_denial
    ok = (success is True and result is not None and not is_policy_denial(result)
          and not (isinstance(result, dict) and
                   (result.get("error") or result.get("success") is False)))
    with task["lock"]:
        if not task["closed"]:
            task["steps"].append({"tool": tool_name, "params": copy.deepcopy(params)})
            task["success"] = task["success"] and ok


def finish_task(agent, purpose, completed):
    task = _execution.get()
    if task is None:
        return
    with task["lock"]:
        if task["closed"] or not task["steps"]:
            flush_task(None, purpose, completed)
            return
    from neurova.skills.skill_service import SkillService

    service = SkillService(agent_id=agent.config.agent_id)
    record = flush_task(service, purpose, completed)
    builder = getattr(agent, "skill_packer", None)
    if builder is not None and record:
        builder.evidence_store = service.creation_evidence
        builder.observe(record["steps"], context=purpose, success=record["success"],
                        metadata={"source_key": record["source_key"]})
        builder.register_to_skill_registry(getattr(agent, "_skill_registry", None), service)


def flush_task(service, purpose, completed):
    task = _execution.get()
    if task is None:
        return None
    with task["lock"]:
        _execution.set(None)
        if task["closed"]:
            return None
        task["closed"] = True
        if not task["steps"]:
            return None
        success = completed is True and task["success"]
        service.creation_evidence.record(task["id"], task["steps"], purpose, success)
        return {"source_key": task["id"], "steps": copy.deepcopy(task["steps"]),
                "purpose": purpose, "success": success}


def manifest_fingerprint(manifest):
    config = manifest.get("config") or {}
    return fingerprint(config.get("tool_sequence"),
                       config.get("task_purpose") or config.get("context_template")
                       or manifest.get("description", ""))


def publish_automatic(service, registry, manifest):
    """Disk first; restore the canonical identity without bypassing evidence."""
    config = dict(manifest.config or {})
    result = service.create_automatic_skill(
        manifest.id, manifest.name, manifest.description, config,
        version=getattr(manifest, "version", "1.0.0"))
    if not result.get("success"):
        return result
    from types import SimpleNamespace
    info = service.get_skill_info(result["skill_id"])
    stored = info.get("manifest") or {}
    runtime = SimpleNamespace(id=info["id"], name=info["name"],
                              description=info.get("description", ""), config=stored.get("config", {}))
    if registry is None or not registry.register_skill(runtime, None):
        return {**result, "success": False, "persisted": True,
                "error": "Skill persisted but runtime registration failed; retry restores it"}
    if hasattr(registry, "set_skill_enabled"):
        registry.set_skill_enabled(runtime.name, info.get("enabled", True))
    return {**result, "skill_name": runtime.name}
