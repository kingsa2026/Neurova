# -*- coding: utf-8 -*-
"""一次性接入票据必须按绝对到期时间拒绝，且不能重放。"""

from neurova.api.endpoints import mobile_pairing as pairing
from neurova.tunnel import protocol


def setup_function():
    pairing._outstanding_tickets.clear()
    pairing._spent_tickets.clear()


def teardown_function():
    pairing._outstanding_tickets.clear()
    pairing._spent_tickets.clear()


def test_ticket_expires_at_stored_deadline(monkeypatch):
    clock = {"now": 1_800_000_000.0}
    monkeypatch.setattr(pairing.time, "time", lambda: clock["now"])
    ticket = pairing._issueConnectTicket("u1", "pair-1", 3)

    clock["now"] += protocol.CONNECT_TICKET_TTL_SECONDS + 1

    assert pairing._consumeConnectTicket(ticket) is None
    assert ticket not in pairing._outstanding_tickets


def test_same_second_renewal_issues_distinct_single_use_tickets(monkeypatch):
    monkeypatch.setattr(pairing.time, "time", lambda: 1_800_000_000.0)
    first_ticket = pairing._issueConnectTicket("u1", "pair-1", 3)
    second_ticket = pairing._issueConnectTicket("u1", "pair-1", 3)

    assert first_ticket != second_ticket
    assert pairing._consumeConnectTicket(first_ticket) is not None
    assert pairing._consumeConnectTicket(second_ticket) is not None


def test_ticket_is_single_use(monkeypatch):
    monkeypatch.setattr(pairing.time, "time", lambda: 1_800_000_000.0)
    ticket = pairing._issueConnectTicket("u1", "pair-1", 3)

    first = pairing._consumeConnectTicket(ticket)
    second = pairing._consumeConnectTicket(ticket)

    assert first == {"user_id": "u1", "pairing_id": "pair-1", "token_epoch": "3"}
    assert second is None
