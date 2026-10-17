# -*- coding: utf-8 -*-
r"""live-verify（批 66·丁）：路径语义由 schema 声明决定——真预检路上 `exec_command.workdir` 必须被查。

装配点全部走生产：`get_governance().evaluate_tool_call(tool_name, params)`（`tool_executor.py:1615`
就是这个调用形状）→ `extract_adjudicable_params(tool_name, params)` → `pathValuesForTool`
→ `GovernancePolicy.evaluate` → `ToolGuardEngine.guard` → `FilePathGuardian`。

改前实状（探针即用即删）：`{"workdir":"/etc/shadow","file_path":良性,"command":"ls"}` 这一形经真预检
是 **ALLOW**——`workdir` 不在名字表里，而回落正则靠 `workdir=` 里的子串 `dir=` 偶然咬到它；
清单内键一出现，偶然就消失。
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402

ROOT = isolatedDataRoot(prefix="neurovaPathDeclB66")
DATA = REPO / "data"

from neurova.security.governance import get_governance  # noqa: E402
from neurova.security.tool_guard import ToolGuardEngine  # noqa: E402

SAFE = "/home/agent/workspace/readme.txt"
SHADOW = "/etc/shadow"
PROGRAM_FILES = r"C:\Program Files\Foo"
FAILURES = []


def fingerprint():
    h = hashlib.md5()
    for p in sorted(DATA.rglob("*")):
        if p.is_file():
            h.update(p.relative_to(DATA).as_posix().encode("utf-8"))
            h.update(str(p.stat().st_size).encode("ascii"))
    return h.hexdigest()


BEFORE = fingerprint()


def leg(label, fn):
    ok, detail = fn()
    print(f"[{'PASS' if ok else 'FAIL'}] {label}\n       {detail}")
    if not ok:
        FAILURES.append(label)


def findings(toolName, params):
    return [(f.rule_id, str(f.evidence)) for f in ToolGuardEngine().guard(toolName, params).findings]


def brief(items):
    return [(rule, ev[:26]) for rule, ev in items]


def decisionOf(toolName, params):
    v = get_governance().evaluate_tool_call(toolName, params)
    return (v.decision.name if v is not None else "None"), list(v.reasons or []) if v else []


def leg1():
    name, reasons = decisionOf("exec_command",
                               {"workdir": SHADOW, "file_path": SAFE, "command": "ls"})
    return (name != "ALLOW",
            f"decision={name}（改前这一形是 ALLOW）；reasons={(reasons or ['—'])[0][:64]}")


def leg2():
    items = findings("exec_command", {"workdir": SHADOW, "file_path": SAFE})
    return (any(ev == SHADOW for rule, ev in items if rule == "protected_path"),
            f"读数={brief(items)}——声明为路径的 workdir 要与清单内键一起被逐值判")


def leg3():
    items = findings("exec_command", {"workdir": PROGRAM_FILES})
    viaListed = findings("file_list", {"path": PROGRAM_FILES})
    return ("windows_system_path" in [r for r, _e in items]
            and "windows_system_path" in [r for r, _e in viaListed],
            f"workdir 形={brief(items)}；对照 path 形={brief(viaListed)}（同一份字节必须同判）")


def leg4():
    items = findings("mcp.demo.tool", {"path": SHADOW})
    return ("protected_path" in [r for r, _e in items],
            f"没有 schema 可问的远端工具名仍按名字表兜底：{brief(items)}")


def leg5():
    items = findings("file_read", {"file_path": SAFE, "note": "见 " + SHADOW})
    return (items == [], f"case 4（自由文本键里的路径）应仍是零读数：{brief(items)}")


def leg6():
    items = findings("exec_command", {"command": "ls -l", "workdir": SHADOW})
    rules = sorted({r for r, _e in items})
    return (rules == ["protected_path"],
            f"命令扫描面已按声明剔除 workdir 的值，不该双报：{brief(items)}")


leg("1 声明即生效｜真预检路上 workdir 与清单内键同给也要被查", leg1)
leg("2 点名归属｜读数里带的就是那个受保护值", leg2)
leg("3 整值不被空格切短｜带空格的系统目录按声明取到整串", leg3)
leg("4 兜底没被删｜没有 schema 的远端工具名仍按名字表判", leg4)
leg("5 case 4 反向钉｜自由文本键里的路径仍零读数", leg5)
leg("6 归属唯一｜声明参数的值不再同时进命令面", leg6)

after = fingerprint()
print(f"\n[数据根隔离] 隔离根={ROOT}")
print(f"[仓内 data/ 指纹] 跑前={BEFORE[:12]} 跑后={after[:12]}")
if BEFORE != after:
    FAILURES.append("仓内 data/ 被写入")
    print("[FAIL] 仓内 data/ 指纹变了——真库被写")
else:
    print("[PASS] 仓内 data/ 指纹未变")

print("\n==>", "全部 PASS" if not FAILURES else f"有 {len(FAILURES)} 条 FAIL: {FAILURES}")
sys.exit(0 if not FAILURES else 1)
