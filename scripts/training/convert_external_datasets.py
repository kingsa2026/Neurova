# -*- coding: utf-8 -*-
"""外部数据集 → NeuJudge 训练会话文件转换器。

把外部 agent 轨迹数据集（tau-bench / TheAgentCompany / ToolTalk，本地浅克隆）
转换成收割器兼容的会话落盘格式（`<数据根>/<agent>/sessions/session_*.json`），
使现有 `--source real/axion/sweep` 训练管线无需改动即可吸收外部数据。

标签语义：这些数据集均为**人类发起**的 agent 会话（人类在场）→ 分诊策略为
放行（label=1）。任务成败（tau-bench reward / ToolTalk 工具成败）作为元数据
保留在会话文件里，供后续特征升级使用。

用法：
    python scripts/training/convert_external_datasets.py \
        --ext-root <克隆根目录> --data-root <数据根> \
        [--sources taubench,agentcompany,tooltalk] \
        [--max-per-domain 60]
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

BASE_TIME = datetime(2026, 11, 22, 8, 0, 0, tzinfo=timezone.utc)
MAX_EVENTS_PER_SESSION = 60


def _event(role: str, content: str, index: int) -> Dict[str, Any]:
    return {"role": role, "content": content[:400],
            "timestamp": (BASE_TIME + timedelta(seconds=index * 20)).isoformat()}


def _writeSession(dataRoot: Path, agentDir: str, sessionId: str,
                  messages: List[Dict[str, Any]], metadata: Dict[str, Any]) -> int:
    sessionsDir = dataRoot / agentDir / "sessions"
    sessionsDir.mkdir(parents=True, exist_ok=True)
    path = sessionsDir / f"session_{sessionId}.json"
    payload = {
        "agent_id": agentDir,
        "session_id": sessionId,
        "messages": messages,
        "metadata": metadata,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return len(messages)


def _messageFromRole(role: str, content: Any, index: int) -> Optional[Dict[str, Any]]:
    if role not in ("user", "assistant", "tool"):
        return None
    text = "" if content is None else str(content)
    if not text.strip():
        return None
    mapped = "assistant" if role in ("assistant", "tool") else "user"
    return _event(mapped, text, index)


def convertTauBench(extRoot: Path, dataRoot: Path, maxPerDomain: int) -> Tuple[int, List[str]]:
    """tau-bench historical_trajectories：按 reward 分层抽取，人类发起→放行类。"""
    trajRoot = extRoot / "tau-bench" / "historical_trajectories"
    if not trajRoot.exists():
        return 0, []
    byDomain: Dict[str, List[Tuple[float, Dict[str, Any], str]]] = {}
    for path in sorted(trajRoot.glob("*.json")):
        domain = path.stem.split("-", 1)[-1] if "-" in path.stem else path.stem
        try:
            trajectories = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - 损坏文件跳过
            continue
        for index, item in enumerate(trajectories):
            if not isinstance(item, dict):
                continue
            reward = float(item.get("reward", 0.0))
            traj = item.get("traj") or []
            byDomain.setdefault(domain, []).append((reward, item, f"{domain}-{index}"))
    written, domains = 0, []
    for domain, items in sorted(byDomain.items()):
        agentDir = f"taubench-{domain}"
        # reward 分层各取一半，避免单侧偏置
        success = [x for x in items if x[0] >= 1.0]
        failure = [x for x in items if x[0] < 1.0]
        half = max(1, maxPerDomain // 2)
        picked = success[:half] + failure[:half]
        count = 0
        for reward, item, tag in picked:
            messages: List[Dict[str, Any]] = []
            for msg in item.get("traj") or []:
                converted = _messageFromRole(str(msg.get("role", "")),
                                             msg.get("content"), len(messages))
                if converted is not None:
                    messages.append(converted)
                toolCalls = msg.get("tool_calls")
                if toolCalls and isinstance(toolCalls, list):
                    names = []
                    for call in toolCalls:
                        try:
                            names.append(call["function"]["name"])
                        except Exception:  # noqa: BLE001
                            continue
                    if names:
                        messages.append(_event("assistant",
                                               "调用工具: " + ", ".join(names), len(messages)))
            if len(messages) < 6:
                continue
            if _writeSession(dataRoot, agentDir, tag.replace("/", "-"),
                             messages, {"source": "tau-bench", "reward": reward}):
                count += 1
        if count:
            domains.append(agentDir)
            written += count
    return written, domains


def convertToolTalk(extRoot: Path, dataRoot: Path, maxConversations: int) -> Tuple[int, List[str]]:
    """ToolTalk：data/easy/*.json 与 data/tooltalk/*.json 每文件一个对话，
    顶层含 conversation_id 与 conversation 轮次数组（turn={index,role,text,apis?}，
    apis=[{request:{api_name,parameters}}, ...]）。人类发起 → 放行类。"""
    conversations: List[Tuple[str, Dict[str, Any]]] = []
    for jsonPath in sorted((extRoot / "ToolTalk" / "data").rglob("*.json")):
        try:
            payload = json.loads(jsonPath.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - 损坏文件跳过
            continue
        items = payload if isinstance(payload, list) else [payload]
        for item in items:
            if isinstance(item, dict) and item.get("conversation"):
                convId = str(item.get("conversation_id") or jsonPath.stem)
                conversations.append((convId, item))

    written = 0
    agentDir = "tooltalk"
    seen = set()
    for convId, item in conversations:
        if convId in seen or written >= maxConversations:
            continue
        seen.add(convId)
        messages: List[Dict[str, Any]] = []
        for turn in item.get("conversation") or []:
            if not isinstance(turn, dict):
                continue
            converted = _messageFromRole(str(turn.get("role", "")),
                                         turn.get("text"), len(messages))
            if converted is not None:
                messages.append(converted)
            apiNames = []
            for call in turn.get("apis") or []:
                name = (call.get("request") or {}).get("api_name")
                if name:
                    apiNames.append(str(name))
            if apiNames:
                messages.append(_event("assistant",
                                       "调用工具: " + ", ".join(apiNames), len(messages)))
        if len(messages) < 6:
            continue
        if _writeSession(dataRoot, agentDir, convId.replace("/", "-"),
                         messages, {"source": "tooltalk"}):
            written += 1
    return written, ["tooltalk"] if written else []


def convertAgentCompany(extRoot: Path, dataRoot: Path, maxTasks: int) -> Tuple[int, List[str]]:
    """TheAgentCompany：workspaces/tasks/*/task.md 任务书 → 人类发起任务会话。

    数据集只提供任务书与检查点（无轨迹），据此改写为六条消息的极简会话
    骨架（人类在场 → 规则放行类），内容全部取自任务定义本身。
    """
    taskRoot = extRoot / "TheAgentCompany" / "workspaces" / "tasks"
    if not taskRoot.exists():
        return 0, []
    written = 0
    agentDir = "agentcompany"
    for taskDir in sorted(p for p in taskRoot.iterdir() if p.is_dir()):
        if written >= maxTasks:
            break
        taskFile = taskDir / "task.md"
        if not taskFile.exists():
            continue
        goal = taskFile.read_text(encoding="utf-8", errors="ignore").strip()
        if len(goal) < 40:
            continue
        taskId = taskDir.name
        checkpoints = ""
        checkpointFile = taskDir / "checkpoints.md"
        if checkpointFile.exists():
            checkpoints = checkpointFile.read_text(encoding="utf-8", errors="ignore").strip()
        messages = [
            _event("user", goal[:600], 0),
            _event("assistant", "收到。我先拆解任务步骤：\n"
                   + (checkpoints[:300] if checkpoints else "按任务书逐项执行。"), 1),
            _event("user", "对，按这个计划推进，有不确定的地方随时问我。", 2),
            _event("assistant", "好的，开始执行第一步。", 3),
            _event("user", "进度如何？", 4),
            _event("assistant", "正在执行中，完成后我会同步结果与验收材料。", 5),
        ]
        if _writeSession(dataRoot, agentDir, taskId.replace("/", "-"), messages,
                         {"source": "theagentcompany"}):
            written += 1
    return written, ["agentcompany"] if written else []


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="外部 agent 数据集 → NeuJudge 训练会话文件转换器")
    parser.add_argument("--ext-root", required=True, help="三个数据集克隆的根目录")
    parser.add_argument("--data-root", default=str(
        Path(__file__).resolve().parents[2] / "data"))
    parser.add_argument("--sources", default="taubench,agentcompany,tooltalk")
    parser.add_argument("--max-per-domain", type=int, default=60)
    args = parser.parse_args(argv)

    extRoot = Path(args.ext_root)
    dataRoot = Path(args.data_root)
    sources = {s.strip() for s in args.sources.split(",") if s.strip()}
    total = 0
    if "taubench" in sources:
        count, domains = convertTauBench(extRoot, dataRoot, args.max_per_domain)
        total += count
        print(f"tau-bench: {count} 会话（{domains}）")
    if "agentcompany" in sources:
        count, domains = convertAgentCompany(extRoot, dataRoot, args.max_per_domain)
        total += count
        print(f"TheAgentCompany: {count} 会话（{domains}）")
    if "tooltalk" in sources:
        count, domains = convertToolTalk(extRoot, dataRoot, args.max_per_domain)
        total += count
        print(f"ToolTalk: {count} 会话（{domains}）")
    print(f"合计写出 {total} 个外部会话文件")
    return 0 if total else 1


if __name__ == "__main__":
    raise SystemExit(main())
