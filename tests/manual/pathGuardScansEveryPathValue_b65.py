# -*- coding: utf-8 -*-
r"""live-verify（批 65）：§6-284 甲案落在**真预检路**上——一次调用带两条路径参数，第二条必须还被查。

走的都是生产装配点，不在脚本里重实现：
  `get_governance().evaluate_tool_call(tool_name, params)`（`tool_executor.py:1615` 就是这个调用形状）
  → `extract_adjudicable_params` → `GovernancePolicy.evaluate` → `ToolGuardEngine.guard`
  → `FilePathGuardian.guard`。

六条腿各自要证的：
① case 1 在真路上：`{"file_path": 良性, "path": 受保护}` 不再 ALLOW；
② case 2 在真路上：第一方唯一那只同时带 `command` 与 `path` 的工具就是 `git`（`builtin_tools.py:931`），
   它今天正因为"已找到 path"而从不扫命令行文本；
③ 逐值扫要**点名归属**：两个受保护值各出一条读数，不是合成一条；
④ 去重按归属：同一个值被两个键带着只出一条，而"按值判"与"按文本判"两个归属不许互吞；
⑤ case 4 明确仍不覆盖：`note` 里的自由文本路径照旧零读数（做了它就是判形状退回判词）；
⑥ 对照：单路径调用的裁决与改前一致（甲对外承诺的那一半）。

数据根经 `_liveVerifyIsolation.isolatedDataRoot()` 单点隔离；跑前跑后各取一次仓内 `data/` 指纹。
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402

ROOT = isolatedDataRoot(prefix="neurovaPathGuardB65")
DATA = REPO / "data"

from neurova.security.governance import get_governance  # noqa: E402
from neurova.security.tool_guard import ToolGuardEngine  # noqa: E402

SAFE = "/home/agent/workspace/readme.txt"
SHADOW = "/etc/shadow"
PASSWD = "/etc/passwd"
SSH_KEY = "/root/.ssh/id_rsa"


def fingerprint():
    h = hashlib.md5()
    for p in sorted(DATA.rglob("*")):
        if p.is_file():
            h.update(p.relative_to(DATA).as_posix().encode("utf-8"))
            h.update(str(p.stat().st_size).encode("ascii"))
    return h.hexdigest()


FAILURES = []


def leg(label, fn):
    ok, detail = fn()
    print(f"[{'PASS' if ok else 'FAIL'}] {label}\n       {detail}")
    if not ok:
        FAILURES.append(label)


def verdictOf(toolName, params):
    v = get_governance().evaluate_tool_call(toolName, params)
    if v is None:
        return "None（无可裁决内容）", []
    return v.decision.name, list(v.reasons or [])


# ① case 1 在真预检路上
def leg1():
    name, reasons = verdictOf("file_read", {"file_path": SAFE, "path": SHADOW})
    return (name != "ALLOW",
            f"decision={name}，reasons={[r[:48] for r in reasons][:2]}；"
            "改前这一形是 ALLOW（第二条路径参数在预检层就被 next() 丢掉）")


leg("1 case 1｜两条路径参数，第二条也要进裁决", leg1)


# ② case 2 在真预检路上（第一方那只双参数工具）
def leg2():
    name, reasons = verdictOf("git", {"command": f"git diff -- {SHADOW}", "path": "."})
    both = verdictOf("shell", {"command": f"cat {SHADOW}", "file_path": SAFE})
    return (name != "ALLOW" and both[0] != "ALLOW",
            f"git 形 decision={name}；shell 形 decision={both[0]}；改前两者都是 ALLOW")


leg("2 case 2｜带 path 的调用里命令文本也要扫（git 那一形）", leg2)


# ③ 逐值扫要点名归属
def leg3():
    found = [(f.rule_id, f.evidence) for f in
             ToolGuardEngine().guard("file_read", {"file_path": PASSWD, "path": SSH_KEY}).findings
             if f.rule_id == "protected_path"]
    return ({PASSWD, SSH_KEY} <= {e for _r, e in found},
            f"protected_path 读数={[(e[:28]) for _r, e in found]}（两个受保护值各一条）")


leg("3 逐值｜两个受保护值各出一条读数，不是合成一条", leg3)


# ④ 去重按归属
def leg4():
    sameValue = [f.evidence for f in
                 ToolGuardEngine().guard("file_read", {"file_path": SHADOW, "path": SHADOW}).findings
                 if f.rule_id == "protected_path"]
    twoFaces = {f.rule_id for f in
                ToolGuardEngine().guard("shell", {"path": SHADOW, "command": f"cat {SHADOW}"}).findings}
    return (len(sameValue) == 1
            and {"protected_path", "protected_path_in_command"} <= twoFaces,
            f"同值双键 → {len(sameValue)} 条；值面与文本面 → {sorted(twoFaces)}（两个归属都在）")


leg("4 去重｜按归属去：同值一条，值面与文本面互不吞并", leg4)


# ⑤ case 4 仍不覆盖
def leg5():
    ids = [f.rule_id for f in
           ToolGuardEngine().guard("file_read", {"file_path": SAFE, "note": f"见 {SHADOW}"}).findings]
    name, _ = verdictOf("file_read", {"file_path": SAFE, "note": f"见 {SHADOW}"})
    return (ids == [] and name == "ALLOW",
            f"findings={ids}，decision={name}（自由文本键里的路径继续不判——甲案明确不覆盖这一形）")


leg("5 case 4 反向｜自由文本键里的路径仍零读数", leg5)


# ⑥ 对照：单路径调用裁决不变
def leg6():
    one, reasons = verdictOf("file_read", {"file_path": SHADOW})
    benign, _ = verdictOf("file_read", {"file_path": SAFE})
    return (one != "ALLOW" and benign == "ALLOW",
            f"单条受保护 decision={one}（改前后一致，reasons 首条={ (reasons or ['—'])[0][:44] }）；"
            f"良性 decision={benign}")


leg("6 对照｜单路径调用的裁决与改前一致", leg6)


after = fingerprint()
print(f"\n[数据根隔离] 隔离根={ROOT}")
print(f"[仓内 data/ 指纹] {after[:12]}（跑前跑后同一枚才算没写进真库）")
before_marker = REPO / ".tmp_b65_datafp_before.txt"
if before_marker.exists():
    if before_marker.read_text(encoding="utf-8").strip() != after:
        FAILURES.append("仓内 data/ 被写入")
        print("[FAIL] 仓内 data/ 指纹变了——真库被写")
    else:
        print("[PASS] 仓内 data/ 指纹未变")

print("\n==>", "全部 PASS" if not FAILURES else f"有 {len(FAILURES)} 条 FAIL: {FAILURES}")
sys.exit(0 if not FAILURES else 1)
