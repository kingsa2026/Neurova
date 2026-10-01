"""Windows 安全的 git 子进程单源封装——三个实测坑的根因级防线。

仓内所有经 subprocess 发起 git 命令的调用方（skill_journal /
checkpoints / github_push 等）一律经本模块，不得各自裸调
subprocess.run / create_subprocess_exec（防坑复发）。

三个实测坑（2026-10-02，RRSI 对齐 P2-11 实施中逐个踩中）：

坑 1 · 文本模式 CRLF 翻译
    subprocess text=True 在 Windows 把 stdin 的 '\\n' 翻译成 '\\r\\n'——
    实测把 mktree 的路径条目污染成 "s1.txt\\r"。本模块用二进制
    transport，str stdin 统一 utf-8/LF 编码。
坑 2 · '-m' 参数内嵌换行被空格化
    Windows 命令行传参（CreateProcess）无法保真换行——多行 message
    经 '-m' 后 subject/body 合并成一行。多行 message 一律走 stdin
    （commit-tree 无 -m 时读 stdin；commit 用 '-F -'）。
坑 3 · %s 折叠 subject
    git 的 %s 把 commit message 首个空行前的所有行折叠成一行——
    subject 与 body 之间必须空行分隔（commit_message 负责规范）。
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Optional, Union

Stdin = Union[str, bytes]


def run_git(
    *args,
    git_dir: Optional[str] = None,
    cwd: Optional[str] = None,
    stdin: Optional[Stdin] = None,
    timeout: int = 30,
    env_extra: Optional[dict] = None,
) -> subprocess.CompletedProcess:
    """执行 git 子进程（坑 1 根因防线：二进制 transport）。

    - stdin: str → utf-8/LF 编码；bytes 原样。
    - stdout/stderr 以 bytes 返回——调用方按需 decode（blob 可能是
      二进制内容，禁止在 transport 层强转 str）。
    """
    if isinstance(stdin, str):
        stdin = stdin.encode("utf-8")
    cmd = ["git"]
    if git_dir is not None:
        cmd += ["--git-dir", str(git_dir)]
    cmd += [str(a) for a in args]
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        cmd, input=stdin, capture_output=True, timeout=timeout, cwd=cwd, env=env,
    )


def commit_message(subject: str, body: str = "") -> str:
    """坑 3 防线：subject 与 body 之间强制空行（无 body 时不留尾随空行）。"""
    subject = subject.rstrip("\n")
    if not body:
        return subject
    return f"{subject}\n\n{body.lstrip(chr(10))}"


class GitRunner:
    """面向 bare 仓 plumbing 的薄封装。

    只统一 transport 与消息规范；错误语义由调用方定义（审计链失败可
    降级、检查点失败上抛），本类不吞错。
    """

    def __init__(self, git_dir, *, timeout: int = 30):
        self.git_dir = str(git_dir)
        self.timeout = timeout

    def run(self, *args, stdin: Optional[Stdin] = None, check: bool = False):
        proc = run_git(*args, git_dir=self.git_dir, stdin=stdin, timeout=self.timeout)
        if check and proc.returncode != 0:
            raise RuntimeError(f"git {args[0]} 失败: {proc.stderr[:300]}")
        return proc

    def ensure_bare(self) -> bool:
        """按需初始化 bare 仓（幂等）；返回是否已存在。"""
        existed = (Path(self.git_dir) / "HEAD").exists()
        if not existed:
            self.run("init", "--bare", "--quiet", self.git_dir, check=True)
        return existed

    def commit_tree(self, tree_sha: str, message: str,
                    parent: Optional[str] = None) -> str:
        """坑 2 防线：message 走 stdin（不经 '-m' 命令行参数）。message
        若已按 commit_message 组装则坑 3 同时被规避。"""
        args = ["commit-tree", tree_sha]
        if parent:
            args += ["-p", parent]
        proc = self.run(*args, stdin=message, check=True)
        return proc.stdout.strip()
