#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""neuacp 真实 transcript 录制工具（G2 回放契约的事实源采集器）。

对指定家族用**真** :class:`NeuacpClient`（dogfood，不另写协议栈）拉起真实
CLI 子进程，按共享场景脚本执行；双向帧经真 frame_log 账本（写盘前内嵌
redaction 脱敏）按 direction/seq/载荷 留痕，读取后再过一遍 redactFrame 兜底，
落 JSON fixture 到 ``tests/unit/agent/neuacp/replay_fixtures/<family>/<scenario>.json``。

用法：
    python scripts/neuacp_record_fixture.py --list
    python scripts/neuacp_record_fixture.py --family opencode --scenario handshake
    python scripts/neuacp_record_fixture.py --family opencode --scenario all
    python scripts/neuacp_record_fixture.py --family claude-code --scenario handshake --out <path>.json

纪律：
- 真实 transcript 不得带密钥/令牌落库：帧账本写盘前必经 redactFrame
  （结构级字段名 + 值级单源），本工具落 fixture 前再脱敏一遍（幂等兜底）。
- 帧账本临时目录经 ``NEUROVA_DATA_DIR`` 注入（必须在 import neurova 之前），
  录制读取后即删，不污染数据根。
- 录制失败（CLI 未安装 / 鉴权墙 / 配额墙 / 协议错误）如实报告并给非零退出码，
  **绝不伪造 transcript**；回放契约测试只认这里真实录到的 fixture。
- 场景步骤解释器与回放侧共用 ``tests/unit/agent/neuacp/replay_harness.py``
  的 :func:`runScenarioSteps`（单一事实源），两侧语义一致才谈得上「回放一致」。
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# 帧账本落临时区：数据根可注入，必须在任何 neurova 模块被 import 之前注入。
os.environ.setdefault("NEUROVA_DATA_DIR", tempfile.mkdtemp(prefix="neuacpRecord-"))

sys.path.insert(0, str(REPO_ROOT))
_HARNESS_DIR = REPO_ROOT / "tests" / "unit" / "agent" / "neuacp"
if str(_HARNESS_DIR) not in sys.path:
    sys.path.insert(0, str(_HARNESS_DIR))

from neurova.agent.neuacp.acp_client import NeuacpClient  # noqa: E402
from neurova.agent.neuacp.catalog import defaultCommand  # noqa: E402
from neurova.agent.neuacp.frame_log import readFrames  # noqa: E402
from neurova.agent.neuacp.redaction import redactFrame  # noqa: E402
from replay_harness import runScenarioSteps  # noqa: E402

FIXTURE_ROOT = REPO_ROOT / "tests" / "unit" / "agent" / "neuacp" / "replay_fixtures"

#: 录制基线请求超时（秒）：握手/会话建立用；步骤可自带更长 timeout 覆盖。
RECORD_REQUEST_TIMEOUT_S = 20.0

#: prompt 类场景的统一问句（无凭据环境下大概率撞鉴权/配额墙，结果如实录）。
PROMPT_TEXT = "只回答数字本身：1+1=?"

#: 共享场景集（步骤脚本数据，解释器在 replay_harness.runScenarioSteps）。
SCENARIOS: dict = {
    # 必录：三家都要。验 initialize 握手与版本协商；留 1.5s 静默窗收
    # agent 握手后的主动通知（如各家 auth 状态推送），一并进 transcript。
    "handshake": [
        {"op": "start", "protocol_version": "1", "client_capabilities": {}},
        {"op": "sleep", "seconds": 1.5},
        {"op": "terminate"},
    ],
    # 故意错版本：看错误分类（协商失败 / -32602 / fail-closed，以真机为准）。
    "version_mismatch": [
        {"op": "start", "protocol_version": "99", "client_capabilities": {}},
        {"op": "terminate"},
    ],
    # 需要 agent 真正回答；无凭据时大概率超时——超时分类也是契约的一部分。
    "prompt_end_of_turn": [
        {"op": "start", "protocol_version": "1", "client_capabilities": {}},
        {"op": "request", "method": "session/new",
         "params": {"cwd": "$cwd", "mcpServers": []}, "timeout": 20},
        {"op": "request", "method": "session/prompt",
         "params": {"sessionId": "$session_id",
                    "prompt": [{"type": "text", "text": PROMPT_TEXT}]},
         "timeout": 15},
        {"op": "terminate"},
    ],
    # prompt 在飞时发 session/cancel，看中断行为（stopReason/通知序列）。
    "cancel_mid_prompt": [
        {"op": "start", "protocol_version": "1", "client_capabilities": {}},
        {"op": "request", "method": "session/new",
         "params": {"cwd": "$cwd", "mcpServers": []}, "timeout": 20},
        {"op": "cancel_soon", "after_s": 4.0, "method": "session/cancel",
         "params": {"sessionId": "$session_id"}},
        {"op": "request", "method": "session/prompt",
         "params": {"sessionId": "$session_id",
                    "prompt": [{"type": "text", "text": "从一数到一百，逐个输出"}]},
         "timeout": 25},
        {"op": "terminate"},
    ],
    # 权限申请：真 CLI 不触发则不落 fixture（登记缺失），不硬造。
    "permission_request": [
        {"op": "start", "protocol_version": "1", "client_capabilities": {}},
        {"op": "set_permission_handler", "choice": "allow"},
        {"op": "request", "method": "session/new",
         "params": {"cwd": "$cwd", "mcpServers": []}, "timeout": 20},
        {"op": "request", "method": "session/prompt",
         "params": {"sessionId": "$session_id",
                    "prompt": [{"type": "text",
                                "text": "在当前目录创建 neuacp_replay_probe.txt，内容写 replay-ok"}]},
         "timeout": 20},
        {"op": "terminate"},
    ],
}

#: 需要文件工具的 prompt 才可能触发权限申请；用于判断 permission 场景是否真触发。
_PERMISSION_METHOD = "session/request_permission"


def listScenarios() -> str:
    lines = ["可用家族: " + ", ".join(sorted({"opencode", "claude-code", "codex", "gemini-cli"})), "场景:"]
    for name, steps in SCENARIOS.items():
        ops = " -> ".join(str(s.get("op")) for s in steps)
        lines.append(f"  {name}: {ops}")
    return "\n".join(lines)


def _resolveCommand(family: str) -> list:
    """从目录取该家族的启动命令（单一事实源），并做本机安装探测。"""
    command = defaultCommand(family)
    if command is None:
        raise SystemExit(f"[record] 家族 {family!r} 未收录或已禁用，无法录制。可用见 --list")
    head = command[0]
    resolved = shutil.which(head)
    if resolved is None:
        raise SystemExit(
            f"[record] 本机未安装 {family}（命令首词 {head!r} 不在 PATH）——"
            f"如实登记缺失，不伪造录制。install: {head}"
        )
    if head == "npx" and shutil.which("node") is None:
        raise SystemExit("[record] npx 适配器需要 node 运行时，本机未找到 node")
    command = list(command)
    command[0] = resolved
    return command


def _dropLedgerFile(frame_key: str) -> None:
    """录制读取后即删临时帧账本（fail-open）。"""
    try:
        from neurova.core.data_root import dataPath

        safe = "".join(ch for ch in frame_key if ch.isalnum() or ch in "._-")
        path = dataPath("swarm_runs") / f"{safe}.frames.jsonl"
        if path.exists():
            path.unlink()
    except Exception:  # noqa: BLE001
        pass


def recordFixture(family: str, scenario: str, out_path: Path) -> dict:
    """录制一个 (family, scenario) fixture 并落盘，返回摘要 dict。"""
    command = _resolveCommand(family)
    steps = SCENARIOS[scenario]
    # 工作目录用一次性 scratch：真 agent 若真执行文件操作也不污染仓库。
    scratch = tempfile.mkdtemp(prefix="neuacpRecordCwd-")
    events: list = []
    crashes: list = []
    client = NeuacpClient(
        command,
        cwd=scratch,
        env_extra={},
        on_event=lambda method, params: events.append({"method": method, "params": params or {}}),
        on_crash=crashes.append,
        request_timeout=RECORD_REQUEST_TIMEOUT_S,
    )
    frame_key = f"rec-{family}-{scenario}-{int(time.time() * 1000)}"
    client.setFrameKey(frame_key)
    started = time.monotonic()
    try:
        step_outcomes = runScenarioSteps(client, steps, state={"cwd": scratch})
    finally:
        try:
            client.terminate()
        except Exception:  # noqa: BLE001
            pass
    elapsed = time.monotonic() - started

    raw_records = readFrames(frame_key)
    _dropLedgerFile(frame_key)
    # 落盘前再脱敏一遍（账本已脱敏，此处幂等兜底）：真实 transcript 不带凭据落库
    frames = [
        {"seq": record.get("seq"), "direction": record.get("direction"),
         "frame": redactFrame(record.get("frame") or {})}
        for record in raw_records
    ]
    expected = {
        "steps": [
            {key: (redactFrame(value) if key in ("handshake", "result") else value)
             for key, value in outcome.items()}
            for outcome in step_outcomes
        ],
        "events": [
            {"method": item["method"], "params": redactFrame(item["params"])}
            for item in events
        ],
    }
    fixture = {
        "fixture_version": 1,
        "family": family,
        "scenario": scenario,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "command": command,
        "cwd": scratch,
        "steps": steps,
        "frames": frames,
        "expected": expected,
    }

    # permission 场景真 CLI 未触发权限申请 → 不落 fixture（缺失登记，不硬造）
    if scenario == "permission_request":
        saw_permission = any(
            (frame.get("frame") or {}).get("method") == _PERMISSION_METHOD
            for frame in frames
            if frame.get("direction") == "in"
        )
        if not saw_permission:
            shutil.rmtree(scratch, ignore_errors=True)
            return {"family": family, "scenario": scenario, "written": False,
                    "reason": "真实 CLI 未触发 session/request_permission（权限场景缺失登记）",
                    "frames": len(frames), "elapsed_s": round(elapsed, 1)}

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(fixture, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    shutil.rmtree(scratch, ignore_errors=True)
    step_summary = "; ".join(
        f"{o.get('op')}({'ok' if o.get('ok') else 'FAIL:' + str(o.get('error_class'))})"
        for o in step_outcomes
    )
    return {"family": family, "scenario": scenario, "written": True, "path": str(out_path),
            "frames": len(frames), "elapsed_s": round(elapsed, 1), "steps": step_summary,
            "crashes": crashes}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="录制 neuacp 真实 transcript fixture")
    parser.add_argument("--family", choices=["opencode", "claude-code", "codex", "gemini-cli"],
                        help="外部代理家族（目录键）")
    parser.add_argument("--scenario", choices=list(SCENARIOS) + ["all"], help="场景名或 all")
    parser.add_argument("--out", default=None, help="fixture 输出路径（默认按 family/scenario 落位）")
    parser.add_argument("--list", action="store_true", help="列出家族与场景")
    args = parser.parse_args(argv)

    if args.list or (not args.family and not args.scenario):
        print(listScenarios())
        return 0
    if not args.family or not args.scenario:
        parser.error("--family 与 --scenario 必须成对提供（或使用 --list）")

    scenarios = list(SCENARIOS) if args.scenario == "all" else [args.scenario]
    failures = []
    for scenario in scenarios:
        out_path = (
            Path(args.out)
            if len(scenarios) == 1 and args.out
            else FIXTURE_ROOT / args.family / f"{scenario}.json"
        )
        print(f"[record] {args.family}/{scenario} -> {out_path}")
        try:
            summary = recordFixture(args.family, scenario, out_path)
        except SystemExit as exc:
            print(str(exc))
            failures.append(scenario)
            continue
        if summary.get("written"):
            print(f"[record] 已落盘 {summary['frames']} 帧 ({summary['elapsed_s']}s) 步骤: {summary['steps']}")
            if summary.get("crashes"):
                print(f"[record] on_crash: {summary['crashes']}")
        else:
            print(f"[record] 未落盘：{summary.get('reason')}（帧数 {summary.get('frames')}）")
            failures.append(scenario)
    if failures:
        print(f"[record] 未完成场景: {failures}（原因见上，如实登记）")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
