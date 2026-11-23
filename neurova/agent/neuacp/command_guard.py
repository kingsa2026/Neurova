# -*- coding: utf-8 -*-
"""外部代理命令行守卫（CodeQL py/command-line-injection 处置）。

外部编码代理的启动命令是管理员配置的 argv（名册本地直配层，设计文档
§4.7），经 subprocess.Popen（无 shell）拉起。argv 形态下真正的注入面是
「命令头选谁」：shell 解释器作头（bash -c / cmd /c / powershell -Command）
等价于把任意 shell 交到配置面手上。本守卫在拉起前拒绝该形态——本地直配
能力保留：直接指向目标 CLI 可执行文件（含自定义路径）照常放行。
"""
import os
from typing import List, Sequence

#: shell 解释器基名（头名归一——剥可执行后缀、小写——后比对）
_SHELL_BASENAMES = frozenset({
    "sh", "bash", "zsh", "dash", "ksh", "csh", "tcsh", "fish",
    "cmd", "powershell", "pwsh", "wsl",
})

#: Windows 可执行后缀（归一时剥掉再比基名）
_EXEC_SUFFIXES = (".exe", ".cmd", ".bat", ".com")


def refuseCommandArgv(command: Sequence[str]) -> List[str]:
    """返回违规原因清单（空列表 = 放行）。判据：

    - argv 非空且首词非空白；
    - 命令头（取基名、剥可执行后缀、小写）不是 shell 解释器——
      bash -c / cmd /c 形态等价于任意命令执行，守卫拒绝；
    - 任何一段不含 NUL 字节（Popen 遇 NUL 直接 ValueError，提前给诚实原因）。
    """
    reasons: List[str] = []
    argv = [str(part) for part in (command or [])]
    if not argv or not argv[0].strip():
        return ["command 不能为空"]
    head = os.path.basename(argv[0].strip()).lower()
    for suffix in _EXEC_SUFFIXES:
        if head.endswith(suffix):
            head = head[: -len(suffix)]
            break
    if head in _SHELL_BASENAMES:
        reasons.append(
            f"命令头不允许 shell 解释器: {argv[0]!r}——请直接指向目标 CLI "
            "可执行文件（bash -c / cmd /c 形态等价于任意命令执行，守卫拒绝）"
        )
    for part in argv:
        if "\x00" in part:
            reasons.append("command 含 NUL 字节")
            break
    return reasons
