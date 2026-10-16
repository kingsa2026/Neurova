# -*- coding: utf-8 -*-
r"""live-verify（批 62）：三份"什么名字算路径"的名单收成一份之后，真接缝上的答案必须还是一个。

走的是生产装配点，不在测试里重实现：
  治理预检 `governance.extract_adjudicable_params` → 参数归一 `ParamGuard.guard` →
  守卫 `ToolGuardEngine.guard`（命令扫描面 vs 路径扫描面就在这里分家）。

三条要说清的：
① 清单内的两个名字（file_path/path）值不进命令面（§6-266 第①刀裁的口径，本批不许动）；
② 别名表归一（filepath → file_path）**接在守卫之前**能让同一个值也不进命令面——两张表首尾相接
   才是"一份事实源"在真链上的意义，各自为政时这一步是断的；
③ 没收进清单的名字（output_path）今天照命令面扫，这一侧保守，本批不放宽（那是下一拍的票）。

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

ROOT = isolatedDataRoot(prefix="neurovaPathKeysB62")
DATA = REPO / "data"


def fingerprint():
    h = hashlib.md5()
    for p in sorted(DATA.rglob("*")):
        if p.is_file():
            h.update(p.relative_to(DATA).as_posix().encode("utf-8"))
            h.update(str(p.stat().st_size).encode("ascii"))
    return h.hexdigest()


DATA_BEFORE = fingerprint()

from neurova.security import governance, tool_guard  # noqa: E402
from neurova.security.tool_guard import GuardThreatCategory, ToolGuardEngine  # noqa: E402
from neurova.security import tool_param_guard as tpg  # noqa: E402
from neurova.security.tool_param_guard import ParamGuard  # noqa: E402

EVASION = GuardThreatCategory.SHELL_EVASION
# 触发值把 `\xHH` 形状写进档名，不向操作者的用户名借（家目录形状随机器变，第 1/4 腿的读数会跟着翻）。
SAFE = r"/var/tmp/neurova_b62/readme\x41.txt"
failures = []


def read(what, probe):
    """三件式：谓词结论 / 现场读数 / 缺陷读法。

    读数与"为什么不健康"分开打印——早先 PASS 行也把解释文案一起刷出来，
    `[PASS] … 仍被当命令扫` 这种自相矛盾的行会让人把绿读成红。
    """
    try:
        ok, detail, hint = probe()
    except Exception as exc:  # noqa: BLE001
        ok, detail, hint = False, "探针异常 %r" % (exc,), ""
    print("[%s] %s — %s%s" % ("PASS" if ok else "FAIL", what, detail,
                              "" if ok else ("；缺陷读法：" + hint)))
    if not ok:
        failures.append(what[:6])
    return ok


def evasionRules(params):
    return [f.rule_id for f in ToolGuardEngine().guard("file_read", params).findings
            if f.category == EVASION]


# ① 清单那一族：两个名字的值不进命令面
read("1 清单内键不进命令面",
     lambda: (all(not evasionRules({k: SAFE}) for k in tool_guard.PATH_PARAM_KEYS),
              f"PATH_PARAM_KEYS={tool_guard.PATH_PARAM_KEYS} 的命令面读数逐条为空",
              "任一键报出读数即清单那一族的换向（§6-266 第①刀）被改判了"))


# ② 治理预检与守卫读的是同一份清单（不再各抄一份）
def governanceAgreesWithGuard():
    """真契约是 `(command 文本, file_paths)` 二元组——预检取的键名也来自同一份清单。"""
    command, paths = governance.extract_adjudicable_params({"file_path": SAFE, "command": "ls -l"})
    return (paths == SAFE and command == "ls -l",
            f"预检分出 command={command!r} / path={str(paths)[:60]!r}",
            "路径值混进命令文本，就是它另抄了一份清单")


read("2 治理预检不再自带第二份清单", governanceAgreesWithGuard)


# ③ 两张表在真链上首尾相接：别名先归一，守卫就按路径语义处理同一个值
def aliasThenGuard():
    """别名归一（`filepath` → 规范名）接在守卫之前，同一个值就该按路径语义处理。"""
    guarded, rejection = ParamGuard().guard("file_read", {"filepath": SAFE})
    rules = evasionRules(guarded)
    return (rejection is None and "file_path" in guarded and not rules,
            f"归一后参数={str(guarded)[:120]}，rejection={rejection}，命令面读数={rules}",
            "命令面非空即别名表与守卫没接上——那张表在真链上不起作用")


read("3 filepath 经归一后不进命令面", aliasThenGuard)


# ④ 保守那一侧不许被"收名单"顺手放宽：没登记的键今天照命令面扫
read("4 未登记键仍照命令面扫（本批不放宽）",
     lambda: (evasionRules({"output_path": SAFE}) == ["shell_十六进制编码"],
              f"output_path 的命令面读数={evasionRules({'output_path': SAFE})}",
              "读数为空即收名单时顺手改了裁决，那属于下一拍的票"))


# ⑤ 派生关系：三个视图都是一处声明的投影
def viewsDerivedFromTable():
    keys = tool_guard.PATH_PARAM_KEYS == tool_guard.pathNamesWithRole("scanned")
    aliases = tuple(tpg.UNAMBIGUOUS_ALIASES) == tool_guard.pathNamesWithRole("alias_plain")
    gatedNames = [k for k, v in tpg.SCHEMA_REQUIRED_ALIASES.items()
                  if v == tool_guard.PATH_CANONICAL_NAME]
    gated = gatedNames == list(tool_guard.pathNamesWithRole("alias_gated"))
    return (keys and aliases and gated,
            f"清单={tool_guard.PATH_PARAM_KEYS} 无歧义别名={tuple(tpg.UNAMBIGUOUS_ALIASES)} "
            f"需背书别名(路径族)={tuple(gatedNames)}",
            "任一分派生不成立即那张表又长回了字面量")


read("5 三份视图由单源表派生", viewsDerivedFromTable)

print("    OBSERVE 隔离根=%s" % ROOT)
read("6 仓库 data/ 未被写入",
     lambda: (fingerprint() == DATA_BEFORE,
              f"跑前 {DATA_BEFORE[:12]} ↔ 跑后 {fingerprint()[:12]}",
              "两个指纹不同即本轮活体写进了仓内真数据根（本卷 §6-41 那一族）"))

print("\n== 得数：%s ==" % ("全部通过（6 腿）" if not failures else f"FAIL {failures}"))
sys.exit(1 if failures else 0)
