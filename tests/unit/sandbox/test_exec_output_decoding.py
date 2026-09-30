# -*- coding: utf-8 -*-
"""沙箱执行任意命令时，输出解码不得决定这次执行的成败（T-15 生产码命中点）。

`ExecSandbox.execute` 跑的是**用户给的任意命令**（`cmd.exe /c` / `sh -c` 包一层），
原先用 `Popen(text=True)`：码页由机器定，解码动作在 subprocess 的 reader 子线程里，
那里的 `UnicodeDecodeError` 被线程吞掉，`communicate()` 回来的就是 `None`，
再被 `stdout or ""` 抹成**空串**——命令明明成功执行，调用方拿到的输出却是空的。
这比抛异常更难查：没有任何一处提到"编码"。

夹具按 `tests/unit/core/test_proc_text.py` 里记的口径来：喂 `0xFF`（utf-8/gbk/ascii
下都非法），别用"毒 locale 函数"那招——`text=True` 的默认编码在 C 层定，
monkeypatch Python 层的 `locale.getpreferredencoding` 实测无效。
"""

from __future__ import annotations

import pathlib
import sys
import textwrap

from neurova.sandbox.exec_sandbox import ExecSandbox


def _script(tmp_path: pathlib.Path, body: str) -> str:
    p = tmp_path / "child.py"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return str(p)


def _run(tmp_path: pathlib.Path, body: str) -> dict:
    script = _script(tmp_path, body)
    # 路径无空格：不加引号，避开 cmd.exe 对多层引号的剥离规则
    return ExecSandbox().execute(f"{sys.executable} {script}", timeout=30)


def test_undecodableBytesDoNotEraseSuccessfulOutput(tmp_path):
    """命令成功 + 输出含非法字节 ⇒ 结果必须还是有内容的 str，而不是空串。"""
    result = _run(
        tmp_path,
        """
        import sys
        sys.stdout.buffer.write(b"\\xff\\xfe" + "构建完成".encode("utf-8"))
        """,
    )
    assert result["return_code"] == 0, result
    assert isinstance(result["output"], str), (
        f"输出形态被解码失败改写（拿到 {type(result['output']).__name__}）——"
        "命令本身是成功的，故障不该由码页代报"
    )
    assert result["output"], "降级只该损失解不开的字节，不该把整条输出丢掉"


def test_utf8OutputIsNotCorrupted(tmp_path):
    """默认口径必须是 utf-8：数据类输出逐字保住（本机码页为 GBK 时，旧实现此条即红）。"""
    result = _run(
        tmp_path,
        """
        import sys
        sys.stdout.buffer.write("镜像标签 neurova:latest · 订单".encode("utf-8"))
        """,
    )
    assert "镜像标签 neurova:latest · 订单" in result["output"], result["output"]


def test_stderrKeepsSameShape(tmp_path):
    """失败侧同一条口径：stderr 恒为 str，且退出码忠实。"""
    result = _run(
        tmp_path,
        """
        import sys
        sys.stderr.buffer.write(b"\\xff\\xfe" + "出错".encode("utf-8"))
        sys.exit(3)
        """,
    )
    assert result["return_code"] == 3
    assert isinstance(result["error"], str)
    assert "出错" in result["error"], result["error"]
