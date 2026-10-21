"""N7 匿名盲选：只读产物、不看来源，作为近平分时的补充读数。

不参与 accept/reject，也不改判分：`ab_compare` 的均值差落在噪声带内时，
把两臂产物匿名成 A/B 让选择器选优，结果仅作为审批证据返回。
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Sequence

_BLIND_SYSTEM = (
    "你在两份匿名答案之间做选择。你不知道它们由谁、用什么配置产生。"
    "只根据任务要求判断哪一份更好：覆盖是否完整、事实是否自洽、格式是否符合要求。"
    "不要因为篇幅更长或措辞更华丽而加分。"
    '只输出 JSON：{"choice": "A"} 或 {"choice": "B"}。'
)
_TRUNC = "…[truncated]"


def _clip(text: Any, max_chars: int) -> str:
    value = "" if text is None else str(text)
    if max_chars > 0 and len(value) > max_chars:
        return value[: max_chars - len(_TRUNC)] + _TRUNC
    return value


def _candidateIsA(seed: int, task_input: str, baseline: str, candidate: str) -> bool:
    digest = hashlib.sha1(
        f"{seed}|{task_input}|{baseline}|{candidate}".encode("utf-8", errors="replace")
    ).hexdigest()
    return int(digest[:8], 16) % 2 == 1


def _parseChoice(text: Any) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            choice = str(parsed.get("choice") or "").strip().upper()
            if choice in ("A", "B"):
                return choice
    except json.JSONDecodeError:
        pass
    match = re.search(r"\b([AB])\b", raw)
    return match.group(1) if match else ""


async def blind_ab(
    *,
    judge: Any,
    examples: Sequence[Any],
    baseline_outputs: Sequence[Any],
    candidate_outputs: Sequence[Any],
    seed: int = 42,
    max_chars: int = 4000,
) -> dict:
    """逐例匿名比较；返回候选/基线胜场与首选臂。"""
    call = getattr(judge, "_call_llm", None)
    if not callable(call) or len(examples) != len(baseline_outputs) or len(examples) != len(candidate_outputs):
        return {"state": "unavailable", "reason": "no_blind_selector"}
    model = str(getattr(getattr(judge, "config", None), "judge_model", "") or "")
    candidate_wins = baseline_wins = unparsed = 0
    for example, baseline, candidate in zip(examples, baseline_outputs, candidate_outputs):
        baseline = _clip(baseline, max_chars)
        candidate = _clip(candidate, max_chars)
        candidate_is_a = _candidateIsA(
            int(seed), str(getattr(example, "task_input", "")), baseline, candidate
        )
        a, b = (candidate, baseline) if candidate_is_a else (baseline, candidate)
        messages = [
            {"role": "system", "content": _BLIND_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"【任务】\n{getattr(example, 'task_input', '')}\n\n"
                    f"【A】\n{a}\n\n【B】\n{b}"
                ),
            },
        ]
        try:
            result = await call(messages, model)
        except Exception:  # noqa: BLE001 - 选择器故障按未解析计，不伪造胜场
            unparsed += 1
            continue
        choice = _parseChoice((result or {}).get("response")) if (result or {}).get("success") else ""
        if choice not in ("A", "B"):
            unparsed += 1
        elif (choice == "A") == candidate_is_a:
            candidate_wins += 1
        else:
            baseline_wins += 1

    parsed = candidate_wins + baseline_wins
    if parsed == 0:
        return {
            "state": "unavailable",
            "reason": "no_parsed_choice",
            "n": len(examples),
            "unparsed": unparsed,
        }
    preferred = (
        "candidate" if candidate_wins > baseline_wins
        else "baseline" if baseline_wins > candidate_wins
        else "tie"
    )
    return {
        "state": "measured",
        "n": parsed,
        "candidate_wins": candidate_wins,
        "baseline_wins": baseline_wins,
        "unparsed": unparsed,
        "preferred": preferred,
    }
