# -*- coding: utf-8 -*-
"""Computer 属主门、一次性配对票据与凭据持久化回归。"""

import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

import neurova.collaboration.computer_manager as computerManagerModule
from neurova.collaboration.computer_manager import ComputerManager
from neurova.models.computer import ComputerEngine, ComputerKind, ComputerStatus


@pytest.fixture()
def manager(tmp_path):
    return ComputerManager(data_dir=str(tmp_path / "computers"))


def _create(manager, owner="owner-1", *, name="device", kind=ComputerKind.LOCAL, company_id=""):
    computer = manager.create_computer(
        name=name,
        owner_user_id=owner,
        kind=kind,
        engine=ComputerEngine.CLAUDE_CODE,
        company_id=company_id,
    )
    assert computer is not None
    return computer


def _pair(manager, computer_id, token, *, user_id="owner-1"):
    return manager.pair_byoa_computer(
        computer_id=computer_id,
        user_id=user_id,
        pair_token=token,
        host_name="host.local",
        available_engines=["claude"],
        daemon_version="1.0.0",
        supervised=False,
    )


def test_emptyIdentityIsNotInternalReadChannel(manager):
    computer = _create(manager)

    assert manager.get_computer(computer.computer_id, user_id=None) is computer
    assert manager.get_computer(computer.computer_id, user_id="") is None


def test_ownerlessListFailsClosed(manager):
    _create(manager, owner="")

    assert manager.list_user_computers("") == []


def test_ticketIssuanceRequiresOwner(manager):
    computer = _create(manager)

    assert manager.issue_pair_token(computer.computer_id, user_id="intruder") is None
    assert manager.issue_pair_token(computer.computer_id, user_id="") is None
    ticket = manager.issue_pair_token(computer.computer_id, user_id="owner-1")
    assert isinstance(ticket, str)
    assert len(ticket) >= 32


def test_pairTicketIsShortLivedAndSingleUse(manager, monkeypatch):
    computer = _create(manager)
    clock = {"now": 1_000.0}
    monkeypatch.setattr(computerManagerModule.time, "time", lambda: clock["now"])

    ticket = manager.issue_pair_token(computer.computer_id, user_id="owner-1", ttl_seconds=5)
    paired = _pair(manager, computer.computer_id, ticket)

    assert paired is not None
    assert paired.computer is computer
    assert paired.daemon_token != ticket
    assert computer.daemon_token == hashlib.sha256(paired.daemon_token.encode("utf-8")).hexdigest()
    assert _pair(manager, computer.computer_id, ticket) is None

    expiredComputer = _create(manager, name="expired")
    expiredTicket = manager.issue_pair_token(
        expiredComputer.computer_id, user_id="owner-1", ttl_seconds=5
    )
    clock["now"] += 5
    assert _pair(manager, expiredComputer.computer_id, expiredTicket) is None
    assert expiredComputer.daemon_token is None
    assert expiredComputer.paired_at is None


def test_pairTicketIsBoundToComputerAndOwner(manager):
    first = _create(manager, name="first")
    second = _create(manager, owner="owner-2", name="second")
    ticket = manager.issue_pair_token(first.computer_id, user_id="owner-1")

    assert _pair(manager, second.computer_id, ticket, user_id="owner-2") is None
    assert second.daemon_token is None
    assert second.paired_at is None


def test_rejectedOwnerDoesNotConsumeTicket(manager):
    computer = _create(manager)
    ticket = manager.issue_pair_token(computer.computer_id, user_id="owner-1")

    assert _pair(manager, computer.computer_id, ticket, user_id="intruder") is None
    assert _pair(manager, computer.computer_id, ticket, user_id="owner-1") is not None


def test_reissuedTicketInvalidatesPreviousTicket(manager):
    computer = _create(manager)
    first = manager.issue_pair_token(computer.computer_id, user_id="owner-1")
    second = manager.issue_pair_token(computer.computer_id, user_id="owner-1")

    assert first != second
    assert _pair(manager, computer.computer_id, first) is None
    assert _pair(manager, computer.computer_id, second) is not None


def test_concurrentPairingHasExactlyOneWinner(manager):
    computer = _create(manager)
    ticket = manager.issue_pair_token(computer.computer_id, user_id="owner-1")
    barrier = threading.Barrier(8)

    def consume(_):
        barrier.wait(timeout=5)
        return _pair(manager, computer.computer_id, ticket)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(consume, range(8)))

    winners = [result for result in results if result is not None]
    assert len(winners) == 1
    assert computer.daemon_token == hashlib.sha256(winners[0].daemon_token.encode("utf-8")).hexdigest()


def test_revokeRequiresOwnerAndInvalidatesCredentialAndTicket(manager):
    computer = _create(manager)
    ticket = manager.issue_pair_token(computer.computer_id, user_id="owner-1")
    paired = _pair(manager, computer.computer_id, ticket)
    assert paired is not None
    nextTicket = manager.issue_pair_token(computer.computer_id, user_id="owner-1")

    assert manager.revoke_computer(computer.computer_id, user_id="intruder") is False
    assert computer.daemon_token is not None
    assert computer.revoked_at is None

    assert manager.revoke_computer(computer.computer_id, user_id="owner-1") is True
    assert computer.daemon_token is None
    assert computer.status == ComputerStatus.OFFLINE
    assert _pair(manager, computer.computer_id, nextTicket) is None


def test_softDeleteRequiresOwnerAndPersistsDeletedState(manager):
    computer = _create(manager)
    ticket = manager.issue_pair_token(computer.computer_id, user_id="owner-1")
    assert _pair(manager, computer.computer_id, ticket) is not None

    assert manager.delete_computer(computer.computer_id, user_id="intruder") is False
    assert manager.get_computer(computer.computer_id, user_id="owner-1") is computer

    assert manager.delete_computer(computer.computer_id, user_id="owner-1") is True
    assert computer.status == ComputerStatus.DELETED
    assert computer.deleted_at is not None
    assert computer.daemon_token is None

    reloaded = ComputerManager(data_dir=manager.data_dir)
    stored = reloaded.get_computer(computer.computer_id, user_id="owner-1")
    assert stored is not None
    assert stored.status == ComputerStatus.DELETED
    assert stored.deleted_at is not None


def test_hardDeleteRequiresOwnerAndCleansCompanyIndex(manager, tmp_path):
    computer = _create(manager, company_id="company-1")
    deviceFile = tmp_path / "computers" / "devices" / f"{computer.computer_id}.json"

    assert manager.delete_computer(computer.computer_id, hard=True, user_id="intruder") is False
    assert deviceFile.exists()
    assert manager.get_computer(computer.computer_id, user_id="owner-1") is computer

    assert manager.delete_computer(computer.computer_id, hard=True, user_id="owner-1") is True
    assert not deviceFile.exists()
    assert manager.get_computer(computer.computer_id, user_id="owner-1") is None
    assert manager._company_computers.get("company-1", set()) == set()


def test_persistedCredentialIsDigestOnly(manager):
    computer = _create(manager)
    ticket = manager.issue_pair_token(computer.computer_id, user_id="owner-1")
    paired = _pair(manager, computer.computer_id, ticket)
    assert paired is not None

    deviceFile = manager.data_dir / "devices" / f"{computer.computer_id}.json"
    raw = deviceFile.read_text(encoding="utf-8")
    persisted = json.loads(raw)
    digest = hashlib.sha256(paired.daemon_token.encode("utf-8")).hexdigest()

    assert paired.daemon_token not in raw
    assert ticket not in raw
    assert persisted["daemon_token"] == digest
    assert "credential_hash" not in persisted
    assert not hasattr(computer, "credential_hash")

    reloaded = ComputerManager(data_dir=manager.data_dir)
    stored = reloaded.get_computer(computer.computer_id, user_id="owner-1")
    assert stored is not None
    assert stored.daemon_token == digest
