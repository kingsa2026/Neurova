# -*- coding: utf-8 -*-
"""`runText` / `decodeChild`：子进程文本解码的单源入口判据（工单集 §15 / T-15 生产码半）。

## 判据怎么才有判别性（本轮踩过的两个坑，写死在这里）

1. **monkeypatch `locale.getpreferredencoding` 是无效的**——`text=True` 的默认编码在
   `io.TextIOWrapper` 的 C 层取，不读 Python 层那个函数。实测：把函数换成 `"ascii"` 后，
   `Popen(text=True)` 仍按 cp936 解开了 GBK 字节。所以判据不能建立在"毒码页"上。
2. 有效的平台无关夹具是**喂一个在所有相关码页下都非法的字节**：`0xFF` 在 utf-8、
   cp936/GBK、ascii 下都是非法起始字节（latin-1 例外，本机与 CI 都不是它）。
   实测本机：`b"\\xff\\xfe"` → `UnicodeDecodeError: 'gbk' codec can't decode byte 0xff`
   且 `stdout` 变 `None`；UTF-8 中文在这台 GBK 机器上同样 `stdout is None`。

## 判据取向

用**真子进程真字节**（`sys.executable` 起 Python 往 stdout 写原始字节），不 mock：
mock 出来的"解码正确"是同义反复。
"""

from __future__ import annotations

import pathlib
import subprocess
import sys
import textwrap

import pytest

from neurova.core.proc_text import DEFAULT_CHILD_ENCODING, decodeChild, runText


def _script(tmp_path: pathlib.Path, body: str) -> str:
    p = tmp_path / "child.py"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return str(p)


class TestRunText:
    def test_utf8ChildOutputDecodesExactly(self, tmp_path):
        script = _script(
            tmp_path,
            """
            import sys
            sys.stdout.buffer.write("订单·提交".encode("utf-8"))
            """,
        )
        r = runText([sys.executable, script], timeout=30)
        assert r.stdout == "订单·提交", r.stdout

    def test_undecodableBytesReturnTextNotNone(self, tmp_path):
        """0xFF 在 utf-8/gbk/ascii 下均非法 ⇒ 任何机器上都真跑到降级分支。"""
        script = _script(
            tmp_path,
            """
            import sys
            sys.stdout.buffer.write(b"\\xff\\xfeok")
            """,
        )
        r = runText([sys.executable, script], timeout=30)
        assert isinstance(r.stdout, str), "None 就是本缺陷的可见形态"
        assert "ok" in r.stdout, f"降级只该损失解不开的那几个字节，不该丢整条：{r.stdout!r}"

    def test_defaultEncodingIsDeclaredNotMachineChosen(self, tmp_path):
        """反证"看机器脸色"：默认口径必须是 utf-8，与本机码页无关。"""
        assert DEFAULT_CHILD_ENCODING == "utf-8"
        script = _script(
            tmp_path,
            """
            import sys
            sys.stdout.buffer.write("镜像标签:latest".encode("utf-8"))
            """,
        )
        r = runText([sys.executable, script], timeout=30)
        # text=True 交给机器码页时，这条在 cp936 机器上会变 None/乱码；这里必须逐字保住
        assert r.stdout == "镜像标签:latest", r.stdout

    def test_returncodeAndStderrAreFaithful(self, tmp_path):
        script = _script(
            tmp_path,
            """
            import sys
            sys.stderr.write("boom")
            sys.exit(7)
            """,
        )
        r = runText([sys.executable, script], timeout=30)
        assert r.returncode == 7
        assert r.stderr == "boom"

    def test_timeoutStillPropagates(self, tmp_path):
        """超时语义不得被入口吃掉：调用方靠 TimeoutExpired 杀进程树（C-22）。"""
        script = _script(
            tmp_path,
            """
            import time
            time.sleep(5)
            """,
        )
        with pytest.raises(subprocess.TimeoutExpired):
            runText([sys.executable, script], timeout=1)

    def test_silentChildGivesEmptyString(self, tmp_path):
        """子进程什么都没写 → 空串，不是 None。"""
        r = runText([sys.executable, _script(tmp_path, "pass\n")], timeout=30)
        assert r.stdout == "" and r.stderr == ""

    def test_strictErrorsIsHonouredWhenCallerAsks(self, tmp_path):
        """调用方要"解不开就算失败"时入口不替它决定——但默认绝不走这条路。"""
        script = _script(
            tmp_path,
            """
            import sys
            sys.stdout.buffer.write(b"\\xff")
            """,
        )
        with pytest.raises(UnicodeDecodeError):
            runText([sys.executable, script], timeout=30, errors="strict")


class TestDecodeChild:
    def test_bytesDecodeUnderUtf8(self):
        assert decodeChild("签名".encode("utf-8")) == "签名"

    def test_noneAndEmptyBothGiveEmptyString(self):
        assert decodeChild(None) == ""
        assert decodeChild(b"") == ""

    def test_alreadyTextPassesThrough(self):
        assert decodeChild("已经是文本") == "已经是文本"
