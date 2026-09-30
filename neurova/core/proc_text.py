"""子进程文本输出的解码单源入口。

## 为什么要有这个入口（工单集 §15 / T-15）

`subprocess.run(..., text=True)` 不声明编码时，解码码页由**机器**决定
（`io.TextIOWrapper` 的默认编码在 C 层取 `locale.getpreferredencoding()`，注意
Python 层 monkeypatch 那个函数是**无效**的——本仓实测过，判据不能建立在这上面）。
于是同一行代码在不同机器上有两种相反的结局：

- 生产者是 UTF-8（git、docker inspect）而机器码页是 cp936/GBK ⇒ 解码失败；
  更糟的是失败发生在 subprocess 的 **reader 子线程**里，异常被线程吞掉，
  主线程只看到 `stdout is None`，traceback 指向"这行在切字符串"，
  顺着它修就会去给 `.split` 加判空（修复教义第 1 条禁的 consumer-only guard）；
- 生产者是本地化消息（taskkill/powershell 在中文 Windows 上输出 GBK）⇒
  机械地给每处补 `encoding="utf-8"` 反而把原本解得动的东西变成解不动。

所以单源口径是：**按字节取回，在我们自己的线程里解码，解不开就降级为可读性损失**
（`errors="replace"`），既不抛出也不丢整条输出。UTF-8 作默认：数据类命令占多数，
且 ASCII 是 UTF-8 的子集，PID 表/退出码这类关键信息在任何码页下都逐字保住。

调用方需要更严格时传 `errors="strict"`——但请想清楚：strict 下解不开的结果就是
本模块要消灭的那个 `None`。
"""

from __future__ import annotations

import subprocess
from typing import Any, Dict, List, Optional

__all__ = ["DEFAULT_CHILD_ENCODING", "decodeChild", "runText"]

DEFAULT_CHILD_ENCODING = "utf-8"


def decodeChild(
    data: Any,
    *,
    encoding: str = DEFAULT_CHILD_ENCODING,
    errors: str = "replace",
) -> str:
    """把子进程的一条流稳定解成 str：`None`/空 → `""`，已是 str → 原样。"""
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    return data.decode(encoding, errors)


def runText(
    argv: List[str],
    *,
    timeout: Optional[float] = None,
    encoding: str = DEFAULT_CHILD_ENCODING,
    errors: str = "replace",
    **kwargs: Any,
) -> subprocess.CompletedProcess:
    """跑一条命令并返回 `stdout`/`stderr` **恒为 str** 的 CompletedProcess。

    与 `subprocess.run(text=True)` 的区别只有一件要紧的：解码发生在这里
    （调用方线程），所以码页由参数说了算、失败以异常形态落在调用栈上、
    永远不会把"取不到"伪装成 `None` 再让你去猜。
    超时语义原样透传：调用方靠 `TimeoutExpired` 杀进程树（C-22），入口不得吃掉它。
    """
    proc = subprocess.run(
        argv, capture_output=True, timeout=timeout, **kwargs
    )
    return subprocess.CompletedProcess(
        proc.args,
        proc.returncode,
        decodeChild(proc.stdout, encoding=encoding, errors=errors),
        decodeChild(proc.stderr, encoding=encoding, errors=errors),
    )
