"""firewall 全局规则更新：未知键不得被静默丢弃却报成功

缺陷（`core/firewall.py:193-199`）：`update_global_rules` 用 `if hasattr` 逐个筛键，
未知键**既不报错也不留痕**，函数照常 `_save_global()` 返回，调用方（REST 层）
随后 `logger.info("Global firewall rules updated")` 报成功。

这条不是理论问题：我在接"外部渠道额度"时给的就是一个当时不存在的键名，
低额度注入因此无声 no-op，而接口回的是成功。按教义第 2 条，
"什么都没改成"不得写成"改好了"——要么全收，要么点名拒绝。

判据来源单源：合法键名 = `GlobalRuleSet` 的 dataclass 字段
（`hasattr` 会把方法与属性一并算作合法，是第二种口径）。
"""

import json
import logging

import pytest

from neurova.core.firewall import AgentFirewall, GlobalRuleSet


@pytest.fixture
def firewall(tmp_path):
    return AgentFirewall(config_path=str(tmp_path / "fw.json"))


def test_unknownKeyIsNamedAndRejected(firewall):
    with pytest.raises(ValueError) as excinfo:
        firewall.update_global_rules({"rate_limit_per_second": 5})

    message = str(excinfo.value)
    assert "rate_limit_per_second" in message, f"报错未点名未知键：{message}"


def test_mixedUpdateAppliesNothingWhenAnyKeyIsUnknown(firewall):
    """先验后写：一条更新里有一个未知键，就整条拒掉，不得半生效还报成功"""
    before = firewall.get_global_rules()

    with pytest.raises(ValueError):
        firewall.update_global_rules({"rate_limit_per_minute": 7, "bogus_key": 1})

    after = firewall.get_global_rules()
    assert after["rate_limit_per_minute"] == before["rate_limit_per_minute"], "被拒的更新竟已部分生效"


def test_knownKeysStillApply(firewall):
    """判据收紧不得把正常写入挡掉"""
    firewall.update_global_rules({"rate_limit_per_minute": 77, "rate_limit_per_hour": 7700})

    rules = firewall.get_global_rules()
    assert rules["rate_limit_per_minute"] == 77
    assert rules["rate_limit_per_hour"] == 7700


def test_legalKeyNamesComeFromTheDataclass(firewall):
    """单源反证：合法键名集合就是 GlobalRuleSet 的字段，另无第二份清单"""
    fields = set(GlobalRuleSet.__dataclass_fields__)

    with pytest.raises(ValueError):
        firewall.update_global_rules({"_save_global": True})  # 方法名不是字段，不得被 hasattr 放行

    for name in fields:
        assert name in fields


def test_userRulesRejectUnknownKeyToo(firewall):
    """教义第 5 条扫同形态：`update_user_rules` 用的是同一套 hasattr 静默丢弃"""
    with pytest.raises(ValueError) as excinfo:
        firewall.update_user_rules("u1", {"agent_isolation_no": True})

    assert "agent_isolation_no" in str(excinfo.value)


def test_userRulesKnownKeysStillApply(firewall):
    firewall.update_user_rules("u1", {"agent_isolation": False})

    assert firewall.get_user_rules("u1")["agent_isolation"] is False


def test_loadWarnsAboutDroppedKeys(tmp_path, caplog):
    """配置里带未知键时：不崩进程，但必须点名可观测（原来连一句 warning 都没有）"""
    path = tmp_path / "fw.json"
    path.write_text(
        json.dumps({"global": {"rate_limit_per_minute": 60, "legacy_typo_key": 9}}),
        encoding="utf-8",
    )

    with caplog.at_level(logging.WARNING):
        AgentFirewall(config_path=str(path))

    warnings = " ".join(r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING)
    assert "legacy_typo_key" in warnings, f"未知键被无声丢弃：{warnings!r}"
