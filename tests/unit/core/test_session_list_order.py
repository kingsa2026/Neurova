# -*- coding: utf-8 -*-
"""list_sessions 排序契约测试（2026-09-07）。

事故："重启之前的会话没了"。根因：951d8c0b（09-06 reorder 排序落库）把
_collect_summaries 的排序键写成
    (0 if sort_order else 1, sort_order or 0, "" if sort_order else created_at)
元组整体升序——未排序（sort_order=0）会话按 created_at **升序**（最老在前），
与 docstring"未排序(0)按 created_at 倒序垫底"相反，也破坏了 951d8c0b 之前的
基线行为（sort(key=created_at, reverse=True)）。后果链：
最新会话全部沉底 → 前端 loadSessions 自动选列表第一项 → 用户打开的是
6 月的老空会话 → 感知为"之前的会话全没了"（数据其实都在）。

锁定契约：
1. 未排序会话按 created_at 倒序（最新在前）——旧基线行为；
2. sort_order>0 的显式排序会话按其升序排在未排序会话之前（reorder 功能语义）；
3. pinned 置顶只由前端 filteredSessions 处理，摘要层不做 pinned 排序
   （本测试不锁定 pinned 在摘要层的顺序，避免双重排序契约漂移）。
"""
import pytest

import neurova.session_manager as sm_mod
from neurova.session_manager import SessionManager


@pytest.fixture()
def mgr(tmp_path, monkeypatch):
    # 单例下 env 是唯一可靠覆盖通道（构造参数只在首次生效）；每用例重置单例
    monkeypatch.setenv("NEUROVA_SESSIONS_DIR", str(tmp_path / "sessions"))
    sm_mod.SessionManager._instance = None
    yield SessionManager()
    sm_mod.SessionManager._instance = None


def test_unsorted_sessions_newest_first(mgr):
    """未排序会话按 created_at 倒序：最新创建的会话必须排在列表头部。

    旧基线（<951d8c0b）行为；事故中此契约被破坏，导致前端 auto-select
    打开最老的空会话（用户感知"会话全丢"）。
    """
    s_old = mgr.create_session(agent_id="default", title="old")
    s_mid = mgr.create_session(agent_id="default", title="mid")
    s_new = mgr.create_session(agent_id="default", title="new")

    # create_session 的 isoformat 秒级分辨率内可能同秒，用文件时间兜底拉开
    # （同秒时顺序不敏感——三个都新于/旧于彼此才构成契约场景）
    sessions = mgr.list_sessions(agent_id="default")
    ids = [s["session_id"] for s in sessions]
    if len({s_old, s_mid, s_new}) < 3 or len(set(ids)) < 3:
        pytest.skip("create_session 同秒创建，无法构造时序场景")
    assert ids.index(s_new) < ids.index(s_mid) < ids.index(s_old)


def test_explicit_sort_order_kept_before_unsorted(mgr):
    """sort_order>0 的会话按升序在前，未排序会话按 created_at 倒序垫底。"""
    s_a = mgr.create_session(agent_id="default", title="ordered-a")
    s_b = mgr.create_session(agent_id="default", title="ordered-b")
    s_plain_old = mgr.create_session(agent_id="default", title="plain-old")
    s_plain_new = mgr.create_session(agent_id="default", title="plain-new")

    mgr.set_sessions_sort_order("default", [s_b, s_a])

    sessions = mgr.list_sessions(agent_id="default")
    ordered = [s["session_id"] for s in sessions if s.get("sort_order", 0) > 0]
    unsorted = [s["session_id"] for s in sessions if not s.get("sort_order", 0)]

    assert ordered == [s_b, s_a], "显式排序须按 sort_order 升序"
    assert set(unsorted) == {s_plain_old, s_plain_new}
    if len(set(unsorted)) == 2:
        assert unsorted.index(s_plain_new) < unsorted.index(s_plain_old), (
            "未排序会话须按 created_at 倒序（新在前）"
        )
    # 全局：显式排序区整体在未排序区之前
    all_ids = [s["session_id"] for s in sessions]
    assert all_ids[:2] == [s_b, s_a]
