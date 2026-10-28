# -*- coding: utf-8 -*-
r"""logger.\* 的占位符与参数必须逐位对上——否则日志那一句自己先炸。

为什么这条判据必须存在（实测取证）：
`neurova/tool_executor.py` 的治理预检里，SANDBOX 分支「文件类操作无沙箱后端 →
降级为阻止」那条 logger.warning 曾经写的是 `%s %s` 配 `tool_name, "; ".join(f"{k}={v}" …)`，
参数两两错位一撕。那一句是**这条降级路径唯一**的解释通道：它炸了，用户只拿到
「已阻止」而读不到为什么。更坏的是它与阻断结果绑在同一个 try 里，日志异常会把
「已阻止」一起吞掉——报错说错了对象。

判据口径：AST 现读全仓（`neurova/` + `scripts/` + `tests/`），对每个
`logger.<方法>(fmt, *args)` 取 fmt 里的转换符个数与实参个数**一对一对账**：

* 数是 `%` 格式规格（`%s` `%d` `%(name)s` `%r` `%%`），`%%` 是字面量不计、`%(name)s`
  只占一位；
* fmt 不是字面量常量（拼接、变量、动态串）时跳过——那是另一类账，凭猜判红只会制造假红；
* **fmt 里没有占位符却传了实参**是这一格抓到过的真形态：`logging` 只在有 args 时才做
  `%` 格式化，多出来的实参是**静默丢掉**的（不抛错、不告警）——那句"要说明情况"的
  日志于是印出一句没有情况的话。`neurova/channels/xiaoyi.py` 的
  `logger.warning("[小艺模拟] 发送消息: ", message)` 实测输出就是
  `[小艺模拟] 发送消息: `，消息体整个消失；
* 少传则当场 `%` 格式化报 `not enough arguments`，那是显式 500 级故障，同样算红。

覆盖边界（别把这格读成「日志不会再炸」）：本档管的是**同一处调用内**的个数对账。
`extra` / `exc_info` 走关键字参数，不在计数面内；`%` 之外的格式化风格本仓不用。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from tests.ast_scan import parseSource

REPO = Path(__file__).resolve().parents[3]

#: 扫描面：生产代码、CI 脚本、测试——三处都会在真链路里打日志。
SCAN_ROOTS = ("neurova", "scripts", "tests")

#: `logging` 模块上会走 % 格式化的方法。只认 `logging.` / `self.logger` 这类
#: **logging 受体**上的同名方法：`warnings.warn` 与仓内 `log_manager.warning(module, msg)`
#: 用的是别的签名（它们不吃 % 实参），混进来就是假红——判据先认受体，再对账。
LOGGER_METHODS = frozenset(
    {"debug", "info", "warning", "warn", "error", "exception", "critical", "log"}
)

#: 受体名恰好是这些（或形如 `self.<其中之一>`），才认为它是个 logging 受体。
#: 用等号格而不是子串格：`get_logger()` 返回的那个名字不总叫 `logger`，但子串格会把
#: `log_manager.warning(module, msg)` 这种**不同签名**的受体一起算进来——判据先认
#: 受体，再对账，假红和漏判都出自这一步。
LOGGER_RECEIVER_NAMES = frozenset({"logger", "LOGGER", "_logger", "_LOGGER", "log", "_log"})

_CONVERSION = re.compile(r"%(?:\([^)]*\))?[-#0 +]*(?:\d+|\*)?(?:\.(?:\d+|\*))?[hlL]?[diouxXeEfFgGcrsa%]")


def conversionCount(fmt: str) -> int:
    """fmt 里的转换符个数（`%%` 不计、`%(name)s` 只占一位）。"""
    return sum(1 for token in _CONVERSION.findall(fmt) if not token.endswith("%"))


def _isLoggingReceiver(name: str, node: ast.AST, moduleUsesLogging: bool = False) -> bool:
    """受体是不是 logging 受体（`logging.<x>` / `logger` / `self.logger` / `_logger`）。"""
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
            and node.value.id == "logging":
        return True
    # 本模块显式导入了 logging.getLogger ⇒ 模块内叫 `logger` 的受体就是它的实例。
    if moduleUsesLogging and (name or "") in LOGGER_RECEIVER_NAMES:
        return True
    return (name or "") in LOGGER_RECEIVER_NAMES


_LOGGER_MODULE_NAMES = frozenset({"logger", "logging", "_logger", "log"})


def _isPreFormattedCall(node: ast.Call) -> bool:
    """该实参是不是「在调用处已经算好的串」（`"..." % x` / `f"..."` / `.format(...)`）。

    这类写法把格式化提前到调用方，日志器收下的已是一个串——本格判的是
    「日志器自己那次 % 格式化」对不对得上，故不把它算进来（也能逼出 `f"..."` 里
    把日志器名字插错位的形态，那是另一类账）。
    """
    if len(node.args) < 2:
        return False
    arg = node.args[1]
    if isinstance(arg, ast.JoinedStr):
        return True
    if isinstance(arg, ast.BinOp) and isinstance(arg.op, ast.Mod):
        left = arg.left
        if isinstance(left, ast.Constant) and isinstance(left.value, str):
            return True
    return False


def _literalFormat(node: ast.Call) -> str | None:
    if not node.args:
        return None
    first = node.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value
    return None


def halfMatchedLoggerSites(source: str, relPath: str = "") -> list:
    """返回 `(行号, 方法名, 转换符数, 实参数)` 的问题站点。"""
    try:
        tree = parseSource(source)
    except SyntaxError:
        return []
    # 本模块是不是把 `logger` 这个名字绑给了 logging（`logging.getLogger(...)`）——
    # `log_manager` 那族用的是 `warning(module, msg)` 签名，同名叫法不同义。
    moduleUsesLogging = any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "getLogger"
        and isinstance(n.func.value, ast.Name)
        and n.func.value.id == "logging"
        for n in ast.walk(tree)
    )
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr in LOGGER_METHODS):
            continue
        receiver = func.value
        receiverName = receiver.attr if isinstance(receiver, ast.Attribute) else getattr(
            receiver, "id", ""
        )
        if not _isLoggingReceiver(
            getattr(receiver, "id", "") or receiverName, func.value, moduleUsesLogging
        ):
            continue
        # `logging.Logger.info(logger, fmt, *args)` 形态不算——只认 <receiver>.<method>。
        fmt = _literalFormat(node)
        if fmt is None:
            continue
        # `logger.exception` 等位置参就是实参；`log(level, fmt, ...)` 的首参是级别。
        args = node.args[1:]
        if func.attr == "log":
            args = node.args[2:]
        expected = conversionCount(fmt)
        # 已经把值算好并单独传进来的调用（`logger.info("...%(k)d", {**stats})`）
        # 走映射形，与占位符个数不是一对一对账的关系——那一类不归本格判。
        if expected and args and isinstance(args[0], (ast.Dict, ast.JoinedStr)):
            continue
        if expected == 0 and _isPreFormattedCall(node):
            # 已经自己格式化好的串（日志器直接收下），不是本格的账。
            continue
        if len(args) != expected:
            out.append((node.lineno, func.attr, expected, len(args)))
    return out


def scannedFiles() -> list:
    files = []
    for root in SCAN_ROOTS:
        base = REPO / root
        if not base.is_dir():
            continue
        files.extend(sorted(p for p in base.rglob("*.py") if "__pycache__" not in p.parts))
    return files


def test_loggerPlaceholdersMatchArgumentCount():
    """主格：全仓 logger 调用逐处对账，一处不对即红。"""
    files = scannedFiles()
    assert len(files) > 500, f"扫描面现读 {len(files)} 个 .py——根被改窄时「零命中」不代表干净"
    offenders = []
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, attr, expected, got in halfMatchedLoggerSites(text):
            offenders.append(
                f"{path.relative_to(REPO).as_posix()}:{lineno} logger.{attr} "
                f"占位符 {expected} 个 / 实参 {got} 个"
            )
    assert not offenders, (
        "日志占位符与实参个数不符——那一句日志会在打印时自己抛 TypeError，"
        "把「这条路径为什么被挡」唯一的一条解释通道吞掉：\n" + "\n".join(offenders)
    )


def test_detectorSeesBothShapes():
    """负样本反向钉住识别器：只有形如 `logger.x(fmt, *args)` 且数目不符的才该红。"""
    source = (
        "import logging\n"
        "logger = logging.getLogger(__name__)\n"
        "def f(tool, pathValues):\n"
        '    logger.warning("a %s b %s", tool)\n'          # 少传 → 红
        '    logger.info("ok %s", tool)\n'                # 对上 → 绿
        '    logger.debug("literal %% and %s", tool)\n'   # %% 是字面量 → 绿
        '    logger.error("n=%d" % 1)\n'                  # 已格式化，无实参 → 绿
        '    logger.warning(f"dyn {tool}", tool)\n'       # 非 % 常量 → 跳过
    )
    hits = halfMatchedLoggerSites(source)
    assert hits == [(4, "warning", 2, 1)], hits
