# -*- coding: utf-8 -*-
"""Shell 命令归一化（安全检查与执行共用）。

移植自 QwenPaw ``src/qwenpaw/utils/shell_normalization.py``（P0-1，#7472
同款漏洞修复）：POSIX shell 在分词前移除行尾 ``\\`` + 换行，安全检查若对
"移除前"的拼写做正则，与 shell 实际执行的命令存在解析差分——敏感路径
或逃逸特征被物理换行拆开后即可绕过。检查侧必须先归一化再看。

单引号内的 ``\\``+换行 是字面量必须保留；双引号内与引号外都是续行。
CRLF 同样接受（防止 Windows 来源的 JSON/文本制造同款差分）。
"""
from __future__ import annotations


def normalize_posix_line_continuations(command: str) -> str:
    r"""移除 *command* 中的 POSIX ``\\`` + 换行续行。

    引号感知：单引号字面量保留；反斜杠转义不改变引号状态。
    """
    if "\\\n" not in command and "\\\r\n" not in command:
        return command

    result: list = []
    quote: str | None = None
    index = 0
    length = len(command)

    while index < length:
        char = command[index]

        if quote == "'":
            result.append(char)
            if char == "'":
                quote = None
            index += 1
            continue

        if char == "\\":
            if index + 1 < length and command[index + 1] == "\n":
                index += 2
                continue
            if (
                index + 2 < length
                and command[index + 1] == "\r"
                and command[index + 2] == "\n"
            ):
                index += 3
                continue

            # 保留被转义的字符，并防止 \" 改变下方跟踪的引号状态
            result.append(char)
            if index + 1 < length:
                result.append(command[index + 1])
                index += 2
            else:
                index += 1
            continue

        result.append(char)
        if char == '"':
            quote = None if quote == '"' else '"'
        elif char == "'" and quote is None:
            quote = "'"
        index += 1

    return "".join(result)
