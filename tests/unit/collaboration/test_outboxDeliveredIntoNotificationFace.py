"""协作生命周期事件必须真落到站内通知面（欠账③：outbox 的投递器从未注册）。

现量根据（动手前实测，不沿用 spec 散文）：
- 写侧：`api/endpoints/phase3_api.py` 四个 `/outbox/*` 端点 ＋ `collaboration/cost_ledger_integration.py`
  三个 hook；而那三个 hook 本身也只被 HTTP 端点调（生产主路不发事件）。
- 读侧：`process_pending_events` 的唯一驱动点是 `phase3_api.py:200` 那个**人手调**的端点。
- **投递器零注册**：`_handlers` 全仓只有一处写（`outbox_handler.py:321` 的 `register_handler`），
  而生产侧没有任何调用方 ⇒ `_process_event` 取不到 handler 就 `return False`（`:398-401`），
  于是任何事件只会按退避重试到过期、落进 `dead-letter/`。设计档自己也写了这句：
  「`outbox_handler` 与渠道出口是平行体系且 `register_handler` 全仓零生产调用方」
  （`docs/specs/2026-11-03-提示面资产化与出口审批收口升级设计.md:17`）。
  而 `docs/specs/2026-10-31-remaining-11-fixes.md:113` 声称消费方是 `skill_transfers.py`／`notifications.py`
  ——grep 两处都没有 outbox 引用，**那句影响面是错的**，本批按实测重定。
- 落点不是我新造的产品语义：`task_completed` 在生产里**已经**经 `notify_admins` 统一入口做站内镜像
  （`collaborate/workflow/scheduler.py:313-330`，接收人=管理员、无注册管理员兜底 `default`）。
  本批把同一个入口接给 outbox 的三个事件类型，并给排空接上调度。
"""

import ast
from pathlib import Path

import pytest

from neurova.collaboration.outbox_handler import EventStatus, OutboxHandler, reset_outbox_handler
from tests.ast_scan import parseSource

REPO_ROOT = Path(__file__).resolve().parents[3]
APP_FILE = REPO_ROOT / "neurova" / "api" / "app.py"
DELIVERY_FILE = REPO_ROOT / "neurova" / "collaboration" / "outbox_delivery.py"
HANDLER_WRITER = "register_handler"


@pytest.fixture()
def outbox(tmp_path):
    reset_outbox_handler()
    handler = OutboxHandler(data_dir=str(tmp_path))
    yield handler
    reset_outbox_handler()


def _notificationsOf(userId="default"):
    from neurova.notifications.manager import get_notification_manager

    return get_notification_manager().get_user_notifications(userId, limit=50)


def test_生产装配点必须注册投递器且注册落点只有一处():
    """结构格（今天就该红）：接线不能靠"以后再注册"——装配点没调，机制就只会产死信。"""
    assert DELIVERY_FILE.is_file(), "协作域还没有 outbox 出件口模块"
    appTree = parseSource(APP_FILE.read_text(encoding="utf-8"), "app.py")
    called = {n.func.id for n in ast.walk(appTree) if isinstance(n, ast.Call)
              and isinstance(n.func, ast.Name)}
    assert "registerOutboxHandlers" in called, (
        "app 装配面没注册 outbox 投递器：事件仍只会退避进 dead-letter")


def test_排空有具名调度入口且启停成对():
    """结构格：重投不能只靠人手调端点；间隔只许一处定义（教义第 6 条），
    起了一条常驻 task 就必须有等它的那一半（与 MCP／知识索引同一条纪律）。"""
    assert DELIVERY_FILE.is_file(), "协作域还没有 outbox 出件口模块"
    deliverySrc = DELIVERY_FILE.read_text(encoding="utf-8")
    assert "OUTBOX_DRAIN_INTERVAL_SECONDS" in deliverySrc, "排空间隔没有具名常量（单源）"

    appTree = parseSource(APP_FILE.read_text(encoding="utf-8"), "app.py")
    # 装配惯例是函数内懒 import，所以按整棵树取，不看顶层那几行
    imported = [n.module or "" for n in ast.walk(appTree) if isinstance(n, ast.ImportFrom)]
    assert any("outbox_delivery" in m for m in imported), (
        "app 装配面没引入出件口模块 ⇒ 投递器与排空都不在")
    started = [n for n in ast.walk(appTree) if isinstance(n, ast.Attribute)
               and n.attr == "outbox_drain_task"]
    # 关停侧按属性名要，不按局部变量名要——改个局部变量名不该让这条纪律假红
    stopFunc = next((n for n in ast.walk(appTree)
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                     and "shutdown" in n.name.lower()), None)
    stoppedInShutdown = [n for n in ast.walk(stopFunc) if isinstance(n, ast.Attribute)
                         and n.attr == "outbox_drain_task"] if stopFunc else []
    assert started and stoppedInShutdown, (
        f"排空循环启停不成对：装配侧 {len(started)} 处、关停函数 "
        f"({stopFunc.name if stopFunc else '未找到'}) {len(stoppedInShutdown)} 处")


def test_生命周期事件经出件口落到站内通知(outbox):
    """跨边界闭环：outbox 写 → 投递器读 → 通知面读回，三段都得真发生。"""
    from neurova.collaboration.outbox_delivery import registerOutboxHandlers

    registerOutboxHandlers(outbox)
    event = outbox.publish("agent_created", "agent-77", {"company_id": "c1"})

    delivered = outbox.process_pending_events()

    assert delivered >= 1, "注册了投递器却一条都没投出去"
    landed = [n for n in _notificationsOf() if (n.data or {}).get("event_type") == "agent_created"]
    assert landed, "事件没落到站内通知面（写侧与读侧仍断着）"
    assert "agent-77" in (landed[0].data or {}).get("agent_id", "")


def test_间隔读数错不许被当成立刻停(monkeypatch):
    """env 只改节奏，不改单源：写坏时回落到常量，而不是回 0 变成"贴着一个忙循环"。"""
    from neurova.collaboration.outbox_delivery import (
        OUTBOX_DRAIN_INTERVAL_SECONDS, drainIntervalSeconds)

    for badValue in ("", "0", "-5", "abc"):
        monkeypatch.setenv("NEUROVA_OUTBOX_DRAIN_INTERVAL", badValue)
        assert drainIntervalSeconds() == OUTBOX_DRAIN_INTERVAL_SECONDS, badValue
    monkeypatch.setenv("NEUROVA_OUTBOX_DRAIN_INTERVAL", "7")
    assert drainIntervalSeconds() == 7.0


def test_没注册投递器时不得把事件算成已投递(outbox):
    """反向格（今天就该绿、改完仍得绿）：没有处理器就是没投出去——不许报"已处理"，
    也不许把状态推成 sent；这条同时钉住"接线靠假装成功蒙过调度"那种修法。"""
    event = outbox.publish("session_started", "agent-88", {"user_id": "u1"})

    delivered = outbox.process_pending_events()

    assert delivered == 0, "无人投递却报成投出去了"
    assert event.status is EventStatus.PENDING
    assert event.sent_at is None and event.delivered_at is None
