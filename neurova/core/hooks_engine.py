# -*- coding: utf-8 -*-
"""Hooks 最小引擎。

- 事件：PreToolUse / PostToolUse / Stop（12 事件全集的子集，按需扩展）
- 声明：data/hooks.json {"hooks": {"PreToolUse": [{"matcher": "computer_shell|run_code",
  "command": "...", "timeout": 60}]}}；matcher 为工具名正则，缺省匹配全部
- wire：payload JSON 写 stdin（含 event/tool_name/params/result/session_id），
生态脚本零迁移
- 决策语义：PreToolUse {"decision":"block","reason"} → 拦截；PostToolUse/
  Stop 的 {"additionalContext"} 回灌；其余仅副作用
- 开关：NEUROVA_HOOKS=0 全局关闭；配置文件缺失/损坏 = 无 hooks（fail-open）
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

KNOWN_EVENTS = ("PreToolUse", "PostToolUse", "Stop")
_DEFAULT_HOOKS_FILE = "data/hooks.json"
_DEFAULT_TIMEOUT = 60
_MAX_TIMEOUT = 600
_MAX_CONTEXT_CHARS = 4000


class HookOutcome(Dict[str, Any]):
    """单个 hook 的执行结果：{hook, blocked, reason, additional_context, error}"""


class HookEngine:
    """配置驱动的 hooks 执行器（无配置时零开销）。"""

    def __init__(self, config_file: Optional[str] = None):
        self.config_file = config_file or os.environ.get(
            "NEUROVA_HOOKS_CONFIG", _DEFAULT_HOOKS_FILE
        )
        self._lock = threading.Lock()
        self._hooks: Dict[str, List[Dict[str, Any]]] = {}
        self._loaded = False

    # ── 配置 ──────────────────────────────────────────────────────

    def _load_locked(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if os.environ.get("NEUROVA_HOOKS", "1") == "0":
            return
        path = self.config_file
        if not path or not os.path.isfile(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            hooks = data.get("hooks") if isinstance(data, dict) else None
            if isinstance(hooks, dict):
                for event, entries in hooks.items():
                    if event in KNOWN_EVENTS and isinstance(entries, list):
                        self._hooks[event] = [e for e in entries if isinstance(e, dict) and e.get("command")]
        except Exception as e:  # noqa: BLE001 - 配置损坏 fail-open
            logger.warning("hooks 配置加载失败(忽略): %s: %s", path, e)

    def reload(self) -> None:
        with self._lock:
            self._hooks.clear()
            self._loaded = False
            self._load_locked()

    def hooks_for(self, event: str) -> List[Dict[str, Any]]:
        with self._lock:
            self._load_locked()
            return list(self._hooks.get(event, []))

    # ── 执行 ──────────────────────────────────────────────────────

    def run(self, event: str, payload: Dict[str, Any]) -> List[HookOutcome]:
        """执行某事件的全部匹配 hooks；单个失败不影响其余（fail-open）。"""
        if event not in KNOWN_EVENTS:
            return []
        tool_name = str(payload.get("tool_name", "") or "")
        outcomes: List[HookOutcome] = []
        for hook in self.hooks_for(event):
            matcher = hook.get("matcher")
            if matcher and tool_name:
                try:
                    if not re.search(str(matcher), tool_name):
                        continue
                except re.error:
                    continue
            outcome = self._run_one(hook, event, payload)
            if outcome is not None:
                outcomes.append(outcome)
        return outcomes

    def _run_one(self, hook: Dict[str, Any], event: str, payload: Dict[str, Any]) -> Optional[HookOutcome]:
        try:
            timeout = min(max(int(hook.get("timeout", _DEFAULT_TIMEOUT)), 1), _MAX_TIMEOUT)
            # shell=True 必须传字符串：列表形态会被整体加引号，cmd.exe 报
            # "系统找不到指定的路径"（Windows 实测）
            proc = subprocess.run(
                str(hook["command"]),
                shell=True,
                input=json.dumps(payload, ensure_ascii=False, default=str),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            logger.warning("hook 超时(%ss): event=%s cmd=%s", hook.get("timeout"), event, hook.get("command"))
            return HookOutcome(hook=hook.get("command", ""), blocked=False, reason="timeout", error="timeout")
        except Exception as e:  # noqa: BLE001
            logger.warning("hook 执行失败(忽略): %s", e)
            return HookOutcome(hook=str(hook.get("command", "")), blocked=False, error=str(e))

        decision = {}
        try:
            parsed = json.loads(proc.stdout or "{}")
            if isinstance(parsed, dict):
                decision = parsed
        except json.JSONDecodeError:
            pass

        blocked = bool(decision.get("decision") == "block" and event == "PreToolUse")
        additional = str(decision.get("additionalContext", "") or "")[:_MAX_CONTEXT_CHARS]
        return HookOutcome(
            hook=str(hook.get("command", "")),
            blocked=blocked,
            reason=str(decision.get("reason", "") or ""),
            additional_context=additional,
            exit_code=proc.returncode,
        )


_ENGINE: Optional[HookEngine] = None
_ENGINE_LOCK = threading.Lock()


def get_hook_engine() -> HookEngine:
    global _ENGINE
    with _ENGINE_LOCK:
        if _ENGINE is None:
            _ENGINE = HookEngine()
        return _ENGINE


def reset_hook_engine() -> None:
    global _ENGINE
    with _ENGINE_LOCK:
        _ENGINE = None
