"""P2-14：旧 AttachmentManager 退役后的行为边界。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from neurova.agent_shutdown import shutdown_agent
from neurova.mem_core import MemCore


def test_mem_core_no_longer_exposes_attachment_manager() -> None:
    agent = SimpleNamespace(config=SimpleNamespace(agent_id="ag1"))
    memCore = MemCore(agent)

    assert not hasattr(memCore, "attachment_manager")


def test_shutdown_does_not_close_retired_attachment_manager() -> None:
    class RetiredAttachmentSentinel:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    sentinel = RetiredAttachmentSentinel()
    agent = SimpleNamespace(
        config=SimpleNamespace(name="ag1"),
        attachment_manager=sentinel,
    )

    asyncio.run(shutdown_agent(agent))

    assert sentinel.closed is False
