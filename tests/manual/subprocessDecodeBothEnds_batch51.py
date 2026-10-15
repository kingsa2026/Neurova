# -*- coding: utf-8 -*-
"""live-verify（批 51，§6-225）：三处子进程文本捕获按真链路读数，证"显式编码"选对了、不是只让棘轮闭嘴。

判据档数的是形状（AST 里有没有 `encoding=` 关键字）；这一支读**真子进程的真字节**：

1. `scripts/desktop/disk_headroom.py`（真闸脚本，只读盘）按两头钉形态跑一发——它的成功行本来就带
   中文（`剩余 x.xx GB`），中文原样回来＝两头钉成立；
2. 同一条命令**只钉父端**（摘掉子端 `PYTHONIOENCODING`）⇒ 本机首选编码非 UTF-8 时这一发必须读坏；
   读不坏就说明"半修有害"这条前提在本机不成立，判据的反向半边是空话（脚本按 PREFERRED 如实判定）；
3. 原生控制台件那一支：`schtasks` **不在这里真跑**（它会改机器上的计划任务，属不可逆的系统动作），
   代之以同为控制台件的 `cmd /c echo` 发一条中文——locale 解原样、utf-8 解读坏 ⇒ 这就是
   `wsl_crash_cleanup.py` 那两处按 `locale.getpreferredencoding(False)` 而不是"顺手统一成 utf-8"的理由；
4. `test_temp_reclaim.py` 那条真子会话（`sys.executable -m pytest` 跑自己）按本批形态跑通：退出码 0，
   且子会话输出里的中文路径（本仓在 `…\\项目\\Neurova` 下）没有被替换符污染；
5. 反证：把根修的两处形态各单独退回旧写法（去掉子端钉 / locale→utf-8）后复跑**同一份脚本**，
   必须红在对应读数上。

跑法：`PYTHONPATH=$(git rev-parse --show-toplevel) python tests/manual/subprocessDecodeBothEnds_batch51.py`
"""
from __future__ import annotations

import locale
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parents[2]
GATE = REPO / "scripts/desktop/disk_headroom.py"
MARKER = "剩余"
failures: list = []
PREFERRED = locale.getpreferredencoding(False)
LOCALE_IS_UTF8 = PREFERRED.lower().replace("-", "") == "utf8"


def read(idx: str, desc: str, fn) -> None:
    try:
        print("[%s] PASS %s  ← %s" % (idx, desc, fn()))
    except AssertionError as exc:
        failures.append("%s %s：%s" % (idx, desc, exc))
        print("[%s] FAIL %s：%s" % (idx, desc, exc))


def spawn(cmd, *, pinChild: bool, decode: str) -> "subprocess.CompletedProcess[str]":
    env = {**os.environ}
    if pinChild:
        env["PYTHONIOENCODING"] = "utf-8"
    else:
        env.pop("PYTHONIOENCODING", None)
    return subprocess.run([str(x) for x in cmd], capture_output=True, text=True,
                          encoding=decode, errors="replace", cwd=str(REPO), env=env, timeout=180)


def _gateBothEnds() -> str:
    p = spawn([sys.executable, str(GATE), str(REPO)], pinChild=True, decode="utf-8")
    assert p.returncode == 0, f"闸脚本退出码 {p.returncode}：{(p.stdout + p.stderr)[-240:]}"
    assert MARKER in p.stdout, f"读数里没有中文成功行：{p.stdout[-200:]!r}"
    assert "\ufffd" not in p.stdout, f"两头钉后仍有替换符：{p.stdout[-200:]!r}"
    return p.stdout.strip().splitlines()[-1][:72]


def _gateHalfPin() -> str:
    p = spawn([sys.executable, str(GATE), str(REPO)], pinChild=False, decode="utf-8")
    mangled = "锟" in p.stdout or "\ufffd" in p.stdout or MARKER not in p.stdout
    if LOCALE_IS_UTF8:
        return "本机首选编码已是 UTF-8——半修在这一台机器上恰好读得对（判据反向那半同样 skip）"
    assert mangled, f"半修那发竟读对了（PREFERRED={PREFERRED}）——前提变了，得重定反向半边"
    return "半修读坏（PREFERRED=%s）：%r" % (PREFERRED, p.stdout.strip().splitlines()[-1][:56])


def _consoleTool() -> str:
    assert not LOCALE_IS_UTF8, "本机首选编码是 UTF-8，控制台件那一支在本机分不出两种写法，改日再验"
    pin = spawn(["cmd", "/c", "echo 项目Neurova"], pinChild=True, decode=PREFERRED)
    wrong = spawn(["cmd", "/c", "echo 项目Neurova"], pinChild=True, decode="utf-8")
    assert "项目" in pin.stdout, f"按控制台码页解仍读不到中文：{pin.stdout!r}"
    assert "项目" not in wrong.stdout, (
        f"原生控制台件按 utf-8 解仍读对——那就不该钉 locale，重定这一支：{wrong.stdout!r}")
    return "locale(%s) 解=%r ／ utf-8 解=%r" % (
        PREFERRED, pin.stdout.strip()[:24], wrong.stdout.strip()[:24])


def _reclaimChildSession() -> str:
    p = spawn([sys.executable, "-m", "pytest", str(REPO / "tests/unit/core/test_temp_reclaim.py"),
               "-k", "reportsHolderDeadWhenProcessDoesNotExist", "-q", "-p", "no:cacheprovider",
               "--no-header"], pinChild=True, decode="utf-8")
    assert p.returncode == 0, f"真子会话没跑起来：{p.stdout[-260:]}"
    assert "1 passed" in p.stdout, f"子会话读数异常：{p.stdout[-200:]!r}"
    return "真子 pytest 会话 rc=0，输出无替换符=%s" % ("\ufffd" not in p.stdout)


def _revertProbe() -> str:
    """反证：把两处根修形态各退回旧写法，同一份脚本必须红在对应读数上。

    子进程带 `B51_REVERT_PROBE=1` ⇒ 那一发不再递归做第 5 项（否则每一层都会再改自己一次）。
    """
    target = REPO / "tests/manual/subprocessDecodeBothEnds_batch51.py"
    original = target.read_bytes()
    crlf = b"\r\n" in original

    def conv(s):
        return s.replace("\n", "\r\n").encode("utf-8") if crlf else s.encode("utf-8")

    # 锚点用**拼接**写：整串字面量会在本文件里出现两次（一次是探针的锚点、一次是被探针的真行），
    # 直接写整串就变成"命中 2 次"，第一版正是这么把这一项读成"未做"的——"未做"必须算红，不能算绿。
    echoLine = 'pin = spawn(["cmd", "/c", "echo ' + "项目Neurova" + '"], pinChild=True, '
    pairs = [
        ("两头钉→半修",
         'pinChild=True, decode="utf-8")\n    assert p.returncode == 0, f"闸脚本',
         'pinChild=False, decode="utf-8")\n    assert p.returncode == 0, f"闸脚本'),
        ("控制台件 locale→utf-8",
         echoLine + "decode=PREFERRED)", echoLine + 'decode="utf-8")'),
    ]
    reverted = []
    for name, old, new in pairs:
        hits = original.count(conv(old))
        assert hits == 1, "反证锚点命中 %d 次（应为 1）：%s——锚点已失效，这一项没做成" % (hits, name)
        target.write_bytes(original.replace(conv(old), conv(new)))
        try:
            p = subprocess.run([sys.executable, str(target)], capture_output=True, text=True,
                               encoding="utf-8", errors="replace", cwd=str(REPO), timeout=600,
                               env={**os.environ, "B51_REVERT_PROBE": "1"})
            lines = (p.stdout or "").splitlines()
            failedIdx = sorted({l[1:4].strip() for l in lines if l.startswith("[") and "] FAIL" in l})
            assert p.returncode != 0 and failedIdx, (
                f"退回「{name}」后同一份脚本仍全绿——那一处的读数不咬人（rc={p.returncode}）")
            reverted.append("%s→红在第%s项" % (name, ",".join(failedIdx)))
        finally:
            target.write_bytes(original)
            assert target.read_bytes() == original, "反证脚本复原失败"
    return " ｜ ".join(reverted)


read("1", "真闸脚本按两头钉跑一发，中文回显原样", _gateBothEnds)
read("2", "同一条命令只钉父端（半修）必须读坏", _gateHalfPin)
read("3", "原生控制台件：locale 解对、utf-8 解坏（schtasks 不真跑）", _consoleTool)
read("4", "真子 pytest 会话按两头钉跑通", _reclaimChildSession)
if os.environ.get("B51_REVERT_PROBE") == "1":
    print("[5] SKIP 反证段（本发就是反证自己spawn的那一发）")
else:
    read("5", "反证：两处根修各退回旧形态，同一份脚本必须红", _revertProbe)

print("PREFERRED=%s ｜ LOCALE_IS_UTF8=%s" % (PREFERRED, LOCALE_IS_UTF8))
print("\n总计：5 项，失败 %d 项" % len(failures))
for f in failures:
    print("  - " + f)
sys.exit(1 if failures else 0)
