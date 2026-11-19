# -*- coding: utf-8 -*-
"""checkpoints 域跑测隔离。

快照走真 git plumbing（commit-tree），而 git 的作者/提交者身份取自
环境变量或 git config——tmp_path 下的裸仓库不继承本仓 config，宿主/CI
未配全局身份时 commit-tree 必然报 "Author identity unknown"。
本域统一在夹具里自备身份（与 test_auto_checkpoint_content.py 同一口径），
不要求用户配全局 git 身份；断言落在快照/恢复/GC 语义本身。
"""
import pytest


@pytest.fixture(autouse=True)
def _gitIdentityForCheckpoints(monkeypatch):
    monkeypatch.setenv("GIT_AUTHOR_NAME", "neurova-test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "neurova-test@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "neurova-test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "neurova-test@example.com")
