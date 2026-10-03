# -*- coding: utf-8 -*-
"""#344 复核漏项：「每日」配额必须有跨自然日的结算点。

## 根因（不是形状）

上一轮给 `MultiModelLLMClient` 装上了配额闸口（`try_consume` 判定 + 记账），
但「每日」额度的**跨天结算**始终是死码：

- `ResourceUsage.check_daily_reset()` 生产零调用——判定自己算得出
  「已用 >= 上限」，却没人问它「这个数是不是今天的」；
- 它按「距今 86400 秒」的**滚动窗口**判定，与「每日配额」的自然日语义
  不符：昨天下午用满的用户，今天上午仍会被拒；
- 窗口锚点 `_last_reset` 不在 dataclass 字段里，`from_dict` 即丢；
- 归零发生在内存副本上，**写不回磁盘**——重启后计数原样复活。

后果从「无影响」升级为「永久拒绝」：装上闸口后，用户用满
`max_llm_calls_per_day` 即被永久拦下，重启也不解（计数持久化在
`usage.json`），只能手工删账本。

## 本套件钉住

1. 跨自然日 → 额度恢复，且归零**写回磁盘**；
2. 同一自然日内 → 用满仍拒绝（防「每次都归零」的过度修正）；
3. 判定路径（不经过 try_consume 的 check_llm_call_quota）同样触发结算；
4. 升级前落盘的老账本（无窗口标记）→ 视为新窗口，不得永久锁死。
"""

import json
from datetime import date, timedelta
from pathlib import Path


def _seedLedger(store: Path, payload: dict) -> None:
    """按落盘格式预置账本（直接写 `usage.json`，不经内存缓存）。"""
    store.mkdir(parents=True, exist_ok=True)
    (store / "usage.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _yesterday() -> str:
    return (date.today() - timedelta(days=1)).isoformat()


class TestDailyWindowRollover:
    def testQuotaRestoresOnNextDay(self, tmp_path):
        """昨天用满 → 今天首次消费放行，且归零已写回磁盘。"""
        from neurova.admin.resource_quota_manager import ResourceQuotaManager

        store = tmp_path / "quota"
        _seedLedger(store, {
            "u1": {
                "user_id": "u1",
                "group_type": "user",
                "llm_call_count": 2,
                "daily_window": _yesterday(),
            },
        })
        mgr = ResourceQuotaManager(str(store), custom_limits={"max_llm_calls_per_day": 2})

        assert mgr.try_consume("u1", "llm_call_count", "max_llm_calls_per_day") is True
        assert mgr.get_usage("u1").llm_call_count == 1

        onDisk = json.loads((store / "usage.json").read_text(encoding="utf-8"))
        assert onDisk["u1"]["llm_call_count"] == 1, "归零与记账必须写回磁盘，不能只发生在内存副本上"
        assert onDisk["u1"]["daily_window"] == date.today().isoformat()

    def testSameDayStillDenied(self, tmp_path):
        """负控制：同一自然日内用满 → 仍拒绝（不是「每次都归零」）。"""
        from neurova.admin.resource_quota_manager import ResourceQuotaManager

        mgr = ResourceQuotaManager(
            str(tmp_path / "quota"), custom_limits={"max_llm_calls_per_day": 1}
        )
        assert mgr.try_consume("u1", "llm_call_count", "max_llm_calls_per_day") is True
        assert mgr.try_consume("u1", "llm_call_count", "max_llm_calls_per_day") is False

    def testCheckPathSeesFreshWindow(self, tmp_path):
        """判定路径（check_llm_call_quota）同样触发结算，不必先消费一次。"""
        from neurova.admin.resource_quota_manager import ResourceQuotaManager

        store = tmp_path / "quota"
        _seedLedger(store, {
            "u1": {
                "user_id": "u1",
                "group_type": "user",
                "llm_call_count": 5,
                "daily_window": _yesterday(),
            },
        })
        mgr = ResourceQuotaManager(str(store), custom_limits={"max_llm_calls_per_day": 5})

        status = mgr.check_llm_call_quota("u1")
        assert status["allowed"] is True
        assert status["current"] == 0

    def testStatusReportShowsSettledCounters(self, tmp_path):
        """运维报表（get_quota_status）看到的是今天的计数，不是昨天的存量。"""
        from neurova.admin.resource_quota_manager import ResourceQuotaManager

        store = tmp_path / "quota"
        _seedLedger(store, {
            "u1": {
                "user_id": "u1",
                "group_type": "user",
                "llm_call_count": 2,
                "daily_window": _yesterday(),
            },
        })
        mgr = ResourceQuotaManager(str(store), custom_limits={"max_llm_calls_per_day": 2})

        status = mgr.get_quota_status("u1")
        assert status["usage"]["llm_call_count"] == 0
        assert status["usage"]["daily_window"] == date.today().isoformat()

    def testNearLimitReportIgnoresYesterday(self, tmp_path):
        """「近限名单」按当日计数判——昨天的满额不该今天继续告警。"""
        from neurova.admin.resource_quota_manager import ResourceQuotaManager

        store = tmp_path / "quota"
        _seedLedger(store, {
            "u1": {
                "user_id": "u1",
                "group_type": "user",
                "llm_call_count": 2,
                "daily_window": _yesterday(),
            },
        })
        mgr = ResourceQuotaManager(str(store), custom_limits={"max_llm_calls_per_day": 2})

        assert mgr.list_users_near_limits(threshold=0.8) == []

    def testAggregateReportsUseTodayCounters(self, tmp_path):
        """get_stats / get_all_usage 两个汇总口同样不得把昨天的存量算进今天。"""
        from neurova.admin.resource_quota_manager import ResourceQuotaManager

        store = tmp_path / "quota"
        _seedLedger(store, {
            "u1": {
                "user_id": "u1",
                "group_type": "user",
                "llm_call_count": 2,
                "daily_window": _yesterday(),
            },
        })
        mgr = ResourceQuotaManager(str(store), custom_limits={"max_llm_calls_per_day": 2})

        assert mgr.get_stats()["totals"]["llm_call_count"] == 0
        assert mgr.get_all_usage()["u1"]["llm_call_count"] == 0

    def testLegacyLedgerWithoutWindowDoesNotLockOut(self, tmp_path):
        """升级前落盘的老账本没有窗口标记 → 视为新窗口，不得永久锁死。"""
        from neurova.admin.resource_quota_manager import ResourceQuotaManager

        store = tmp_path / "quota"
        _seedLedger(store, {
            "u1": {"user_id": "u1", "group_type": "user", "llm_call_count": 100},
        })
        mgr = ResourceQuotaManager(str(store), custom_limits={"max_llm_calls_per_day": 100})

        assert mgr.check_llm_call_quota("u1")["allowed"] is True
        assert mgr.try_consume("u1", "llm_call_count", "max_llm_calls_per_day") is True
