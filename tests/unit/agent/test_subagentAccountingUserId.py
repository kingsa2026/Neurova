# -*- coding: utf-8 -*-
"""子代理记账身份取法（fullrepo 审计 2026-11-18 B2/G3）。

§3 裁定：运行台账（agent_run_ledger）行 user_id 与续跑权威按 **agent
属主**，可见性同口径。旧形 `current_user_id`（发送者直读转发）优先，
会在 admin/他人代跑时把台账行记到点击者名下——属主反而看不见自己的
run（台账自家注释：跟着点击者走＝接线顺手造出来的越权面）。取法收口：
属主优先，缺省退发送者转发，再退空串（fail-soft 不臆造）。
"""
from neurova.agent.swarm import SwarmManager


class _Agent:
    def __init__(self, owner=None, sender=None):
        if owner is not None:
            self.owner_user_id = owner
        if sender is not None:
            self.current_user_id = sender


class TestSubagentAccountingUserId:
    def test_owner_takes_precedence_over_sender(self):
        assert SwarmManager._subagentAccountingUserId(
            _Agent(owner="owner-1", sender="sender-9")) == "owner-1"

    def test_falls_back_to_sender_forward_when_no_owner(self):
        assert SwarmManager._subagentAccountingUserId(
            _Agent(sender="sender-9")) == "sender-9"

    def test_empty_when_neither_present(self):
        assert SwarmManager._subagentAccountingUserId(_Agent()) == ""

    def test_none_values_do_not_become_the_string_none(self):
        assert SwarmManager._subagentAccountingUserId(
            _Agent(owner=None, sender=None)) == ""
