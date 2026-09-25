"""预算账本的金额/百分比边界契约（Issue #197 §7 台账 N4）

两处同一边界缺陷，都在"记账域（float/0~100 制）→ 预算账本（Decimal/0~100 制）"
这条跨域交界上：

1. **金额类型未归一**：`BudgetManager.record_usage(amount: Decimal)` 是
   `Decimal += amount` 的唯一执行点，而上游 LLM 成本域按设计产出 float
   （价格表、`cost_store` 的 `REAL` 列都是 float）。float 进 Decimal 账本即
   `TypeError: unsupported operand type(s) for +=: 'Decimal' and 'float'`，
   被 `_record_budget_and_check_alerts` 的 fail-open 兜住 ⇒ **预算记账整体失效**：
   用量恒为 0.00，`is_over_budget` 恒 False，超支闸永不闭合。
2. **阈值尺度不一致**：`get_usage_percentage()` 返回 0~100 制
   （与 `is_over_budget` 的 `>= 100.00`、API 响应字段、前端 `>= 75` 一致），
   而 `AlertConfig.percentage` 的默认阈值写的是 0~1 制（`0.50`/`0.75`/…）
   ⇒ 首次记账即把 INFO/WARNING/CRITICAL/EXCEEDED 全部触发。

判据（教义第 1 条）：把 float 传给账本 ⇒ 用量必为 0；把阈值放回 0~1 制 ⇒
1% 用量即触发全档告警。两条断言分别钉住这两处。
"""
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from neurova.models.cost_budget import (
    AlertLevel,
    BudgetConfig,
    BudgetManager,
    BudgetScope,
    get_budget_service,
    reset_budget_service,
)
from neurova.models.cost_tracking import (
    LLMProvider,
    record_llm_cost,
    reset_cost_tracker,
)


@pytest.fixture
def budget_service():
    """未注册任何预算的干净账本（记账域写入的真实落点）。"""
    reset_budget_service()
    reset_cost_tracker()
    yield get_budget_service()
    reset_budget_service()
    reset_cost_tracker()


def _register_hourly(manager: BudgetManager, identifier: str, amount: str) -> None:
    now = datetime.now()
    manager.register_budget(
        BudgetConfig(
            scope=BudgetScope.HOURLY,
            identifier=identifier,
            amount=Decimal(amount),
            period_start=now - timedelta(hours=1),
            period_end=now + timedelta(hours=1),
        )
    )


# ── 缺陷一：金额类型边界（float 进 Decimal 账本）──────────────────────

class TestLedgerAcceptsTheCostDomainValue:
    def test_realCostChain_isRecordedAgainstBudget(self, budget_service):
        """真链路：`record_llm_cost` 算出的成本必须记进用量。

        走生产入口（`record_llm_cost`）而非手工构造，因为本缺陷正是
        "上游产出 float、下游声明 Decimal"这条边界的产物。
        gpt-4o：$0.0025/1K 输入、$0.01/1K 输出 ⇒ 100K + 100K tokens = 1.25 USD。
        """
        _register_hourly(budget_service.manager, "kai", "10")

        record_llm_cost(
            provider=LLMProvider.OPENAI,
            model="gpt-4o",
            usage={"prompt_tokens": 100_000, "completion_tokens": 100_000},
            agent_id="kai",
        )

        usage = budget_service.manager.get_usage(BudgetScope.HOURLY, "kai")
        assert usage == Decimal("1.25"), f"真链路成本未记进账本：usage={usage}"

    def test_realCostChain_doesNotRaiseTypeError(self, budget_service, caplog):
        """记账不得以异常收场（此前被 fail-open 兜住，故障因此静默）。"""
        _register_hourly(budget_service.manager, "kai", "10")

        with caplog.at_level("WARNING"):
            record_llm_cost(
                provider=LLMProvider.OPENAI,
                model="gpt-4o",
                usage={"prompt_tokens": 100_000, "completion_tokens": 100_000},
                agent_id="kai",
            )

        swallowed = [r for r in caplog.records if "record budget" in r.getMessage()]
        assert not swallowed, f"记账仍以异常收场：{[r.getMessage() for r in swallowed]}"

    def test_registerThenRecord_pathUsesOneNormalization(self, budget_service):
        """`register_budget` 预置的 0.00 与真实记账必须同源（都是 Decimal）。"""
        _register_hourly(budget_service.manager, "kai", "10")
        assert budget_service.manager.get_usage(BudgetScope.HOURLY, "kai") == Decimal("0.00")

        record_llm_cost(
            provider=LLMProvider.OPENAI,
            model="gpt-4o",
            usage={"prompt_tokens": 1000, "completion_tokens": 0},
            agent_id="kai",
        )
        assert budget_service.manager.get_usage(BudgetScope.HOURLY, "kai") == Decimal("0.0025")


class TestOverBudgetGateCloses:
    def test_costOverBudget_opensTheGate(self, budget_service):
        """超支闸读的是同一账本：记账失效时它恒 False，等于没有闸。"""
        _register_hourly(budget_service.manager, "kai", "0.001")

        record_llm_cost(
            provider=LLMProvider.OPENAI,
            model="gpt-4o",
            usage={"prompt_tokens": 100_000, "completion_tokens": 100_000},
            agent_id="kai",
        )

        assert budget_service.manager.is_over_budget(BudgetScope.HOURLY, "kai") is True

    def test_costWithinBudget_keepsTheGateOpen(self, budget_service):
        """反向不扩面：未超支不得误判。"""
        _register_hourly(budget_service.manager, "kai", "100")

        record_llm_cost(
            provider=LLMProvider.OPENAI,
            model="gpt-4o",
            usage={"prompt_tokens": 1000, "completion_tokens": 1000},
            agent_id="kai",
        )

        assert budget_service.manager.is_over_budget(BudgetScope.HOURLY, "kai") is False



class TestLedgerEntryIsTheNormalizationPoint:
    """金额归一必须在 `record_usage` —— 它是 `+=` 的真实发生处。

    `record_llm_call_cost` 只是众多调用方之一；只在那里归一，任何直接调
    `record_usage` 的路径（含将来的新调用方）仍然会撞同一个 TypeError。
    判据：账本的公开记账 API 本身必须接受成本域的值。
    """

    def test_recordUsage_acceptsFloatFromCostDomain(self):
        manager = BudgetManager()
        _register_hourly(manager, "kai", "10")

        manager.record_usage(BudgetScope.HOURLY, "kai", 0.25)

        assert manager.get_usage(BudgetScope.HOURLY, "kai") == Decimal("0.25")

    def test_recordUsage_normalizesOnceAndIsIdempotent(self):
        """Decimal 入参照旧走同一条路（归一幂等，不产生第二套算术）。"""
        manager = BudgetManager()
        _register_hourly(manager, "kai", "10")

        manager.record_usage(BudgetScope.HOURLY, "kai", Decimal("0.25"))
        manager.record_usage(BudgetScope.HOURLY, "kai", 0.25)

        assert manager.get_usage(BudgetScope.HOURLY, "kai") == Decimal("0.50")

# ── 缺陷二：阈值尺度（0~1 制配置 × 0~100 制用量）──────────────────────

class TestAlertThresholdsShareTheUsageScale:
    def test_thresholdsMatchUsagePercentageScale(self):
        """阈值与用量必须同一尺度：0~100 制（`get_usage_percentage` 的输出口径）。"""
        for config in BudgetManager()._alert_configs:
            assert config.percentage <= Decimal("100"), (
                f"{config.level.name} 阈值 {config.percentage} 与用量尺度（0~100）不一致"
            )
        exceeded = next(c for c in BudgetManager()._alert_configs if c.level == AlertLevel.EXCEEDED)
        assert exceeded.percentage == Decimal("100")

    def test_negligibleUsage_triggersNoAlert(self):
        """1% 用量：一档告警都不该触发。"""
        manager = BudgetManager()
        _register_hourly(manager, "kai", "100")

        manager.record_usage(BudgetScope.HOURLY, "kai", Decimal("1"))

        assert manager.get_usage_percentage(BudgetScope.HOURLY, "kai") == Decimal("1.00")
        assert manager._last_alerted.get("hourly:kai", {}) == {}

    def test_usageAtFiftyPercent_triggersInfoOnly(self):
        """50% 用量：INFO 触发，WARNING 及以上不得触发（阈值逐个咬合）。"""
        manager = BudgetManager()
        _register_hourly(manager, "kai", "100")

        manager.record_usage(BudgetScope.HOURLY, "kai", Decimal("50"))

        fired = set(manager._last_alerted.get("hourly:kai", {}))
        assert AlertLevel.INFO in fired
        assert AlertLevel.WARNING not in fired
        assert AlertLevel.CRITICAL not in fired
        assert AlertLevel.EXCEEDED not in fired

    def test_usageAtHundredPercent_triggersExceeded(self):
        """100% 用量：EXCEEDED 档必须触发（与 `is_over_budget` 同一读数）。"""
        manager = BudgetManager()
        _register_hourly(manager, "kai", "100")

        manager.record_usage(BudgetScope.HOURLY, "kai", Decimal("100"))

        fired = set(manager._last_alerted.get("hourly:kai", {}))
        assert AlertLevel.EXCEEDED in fired
        assert manager.is_over_budget(BudgetScope.HOURLY, "kai") is True

    def test_alertMessageReportsPercentNotRatio(self):
        """告警正文里的百分数取自同一读数（此前 0~1 制阈值会把 1% 报成超支）。"""
        manager = BudgetManager()
        _register_hourly(manager, "kai", "100")
        seen: list = []
        manager._log_alert = lambda level, message: seen.append((level, message))

        manager.record_usage(BudgetScope.HOURLY, "kai", Decimal("1"))

        assert seen == [], f"1% 用量不该发告警：{seen}"


# ── 缺陷三：恢复档被当成"越线触发"档（同一函数内的反向语义）──────────

class TestRecoveredAlertOnlyFiresOnRecovery:
    def test_exceededUsage_doesNotReportRecovered(self):
        """超支时不得报"已恢复"——RECOVERED 是回落语义，不是越线语义。

        此前它和其余档位一起走 `should_trigger(percentage >= 阈值)`，
        于是任何高于回退线的用量都会发一条"已恢复"：
        超支 125000% 时报的是 `Budget recovered to 125000.00%`。
        """
        manager = BudgetManager()
        _register_hourly(manager, "kai", "100")
        seen: list = []
        manager._log_alert = lambda level, message: seen.append((level, message))

        manager.record_usage(BudgetScope.HOURLY, "kai", Decimal("200"))

        assert AlertLevel.EXCEEDED in manager._last_alerted.get("hourly:kai", {})
        recovered = [m for lvl, m in seen if lvl == AlertLevel.RECOVERED]
        assert recovered == [], f"超支时不该报已恢复：{recovered}"

    def test_belowThresholdAfterExceeded_reportsRecoveredOnce(self):
        """真回落：超支后百分比回到回退线以下，报一条已恢复并清掉 EXCEEDED。

        走 `register_budget` 的既有语义构造回落（重新登记即重置该键的用量缓存，
        等同新预算周期开始后的实际百分比），不改用量、不碰私有字段。
        """
        manager = BudgetManager()
        _register_hourly(manager, "kai", "100")
        manager.record_usage(BudgetScope.HOURLY, "kai", Decimal("150"))
        assert AlertLevel.EXCEEDED in manager._last_alerted["hourly:kai"]

        seen: list = []
        manager._log_alert = lambda level, message: seen.append((level, message))
        _register_hourly(manager, "kai", "100000")
        manager.record_usage(BudgetScope.HOURLY, "kai", Decimal("1"))

        assert manager.get_usage_percentage(BudgetScope.HOURLY, "kai") < Decimal("80.00")
        recovered = [m for lvl, m in seen if lvl == AlertLevel.RECOVERED]
        assert len(recovered) == 1, f"回落应报一条已恢复：{seen}"
        assert AlertLevel.EXCEEDED not in manager._last_alerted["hourly:kai"], (
            "已恢复后必须清掉 EXCEEDED 状态，否则恢复只报一次是假象"
        )
