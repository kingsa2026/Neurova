"""Explicit creation evidence for lifecycle fixtures, never a gate monkeypatch."""
import inspect


def register_proven_skill(service, *args, **kwargs):
    call = inspect.signature(service.register_auto_skill).bind(*args, **kwargs)
    call.apply_defaults()
    values = call.arguments
    config = dict(values["config"] or {})
    steps = config.setdefault("tool_sequence", [{"tool": "fixture_read", "params": {"id": values["skill_id"]}}])
    purpose = config.get("task_purpose") or config.get("context_template") or values["description"]
    if not purpose:
        purpose = config.setdefault("task_purpose", values["skill_id"])
    for index in range(3):
        service.creation_evidence.record(f"fixture-{values['skill_id']}-{index}", steps, purpose, True)
    values["config"] = config
    return service.register_auto_skill(**values)
