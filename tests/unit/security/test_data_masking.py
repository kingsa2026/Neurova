"""
测试：数据脱敏模块 (neurova/security/data_masking.py)
"""

import re
import hashlib
import pytest
from neurova.security.data_masking import (
    DataMasking,
    MaskingRule,
    MaskingStrategy,
    SensitiveField,
    PREDEFINED_SENSITIVE_FIELDS,
    get_data_masking,
    mask_sensitive_data,
    mask_log_message,
)


# ============================================================
# 测试 MaskingStrategy 枚举
# ============================================================

class TestMaskingStrategy:
    """MaskingStrategy 枚举"""

    def test_members(self):
        assert MaskingStrategy.FULL_MASK.value == "full"
        assert MaskingStrategy.PARTIAL_MASK.value == "partial"
        assert MaskingStrategy.KEEP_PREFIX.value == "keep_prefix"
        assert MaskingStrategy.KEEP_SUFFIX.value == "keep_suffix"
        assert MaskingStrategy.HASH.value == "hash"
        assert MaskingStrategy.CUSTOM.value == "custom"

    def test_unique_values(self):
        values = [m.value for m in MaskingStrategy]
        assert len(values) == len(set(values))


# ============================================================
# 测试 MaskingRule 和 SensitiveField 数据类
# ============================================================

class TestMaskingRule:
    """MaskingRule 数据类"""

    def test_default_values(self):
        rule = MaskingRule(name="测试", field_name="test", strategy=MaskingStrategy.FULL_MASK)
        assert rule.name == "测试"
        assert rule.field_name == "test"
        assert rule.strategy == MaskingStrategy.FULL_MASK
        # __post_init__ 会自动将 field_name 编译为 pattern
        assert rule.pattern is not None
        assert rule.pattern.match("test")
        assert rule.replacement is None
        assert rule.custom_func is None
        assert rule.enabled is True
        assert rule.priority == 0

    def test_all_fields(self):
        p = re.compile(r"^\d{3}$")
        fn = lambda v: "***"
        rule = MaskingRule(
            name="Test", field_name="code", strategy=MaskingStrategy.CUSTOM,
            pattern=p, replacement="***", custom_func=fn,
            enabled=False, priority=5,
        )
        assert rule.name == "Test"
        assert rule.pattern is p
        assert rule.replacement == "***"
        assert rule.custom_func is fn
        assert rule.enabled is False
        assert rule.priority == 5


class TestSensitiveField:
    """SensitiveField 数据类"""

    def test_fields(self):
        sf = SensitiveField("phone", "手机号", "13812345678")
        assert sf.field_name == "phone"
        assert sf.field_type == "手机号"
        assert sf.example == "13812345678"


# ============================================================
# 测试 PREDEFINED_SENSITIVE_FIELDS
# ============================================================

class TestPredefinedSensitiveFields:
    """预定义敏感字段列表"""

    def test_contains_key_fields(self):
        names = [f.field_name for f in PREDEFINED_SENSITIVE_FIELDS]
        assert "password" in names
        assert "phone" in names
        assert "email" in names
        assert "id_card" in names
        assert "bank_card" in names
        assert "address" in names
        assert "ip_address" in names

    def test_no_duplicates(self):
        names = [f.field_name for f in PREDEFINED_SENSITIVE_FIELDS]
        assert len(names) == len(set(names))


# ============================================================
# 测试 DataMasking 类
# ============================================================

class TestDataMaskingInit:
    """初始化"""

    def test_default_rules_loaded(self):
        dm = DataMasking()
        rules = dm.list_rules()
        names = [r.name for r in rules]
        assert "手机号" in names
        assert "邮箱" in names
        assert "身份证" in names
        assert "IP地址" in names
        assert "密码" in names
        assert "姓名" in names
        assert "地址" in names
        assert "银行卡" in names

    def test_default_rules_have_correct_strategies(self):
        dm = DataMasking()
        assert dm.get_rule("手机号").strategy == MaskingStrategy.KEEP_PREFIX
        assert dm.get_rule("密码").strategy == MaskingStrategy.FULL_MASK
        assert dm.get_rule("姓名").strategy == MaskingStrategy.PARTIAL_MASK
        assert dm.get_rule("银行卡").strategy == MaskingStrategy.KEEP_SUFFIX


class TestDataMaskingRules:
    """规则管理"""

    def test_add_rule(self):
        dm = DataMasking()
        rule = MaskingRule("新规则", "my_field", MaskingStrategy.FULL_MASK)
        dm.add_rule(rule)
        assert dm.get_rule("新规则") is rule

    def test_add_rule_compiles_field_name_as_pattern(self):
        dm = DataMasking()
        rule = MaskingRule("custom", "my_field|another", MaskingStrategy.FULL_MASK)
        dm.add_rule(rule)
        stored = dm.get_rule("custom")
        assert stored.pattern.match("my_field")
        assert stored.pattern.match("another")
        assert not stored.pattern.match("no_match")

    def test_remove_rule_exists(self):
        dm = DataMasking()
        assert dm.remove_rule("手机号") is True
        assert dm.get_rule("手机号") is None

    def test_remove_rule_not_exists(self):
        dm = DataMasking()
        assert dm.remove_rule("不存在的规则") is False

    def test_get_rule_not_exists(self):
        dm = DataMasking()
        assert dm.get_rule("xxx") is None

    def test_list_rules_sorted_by_priority(self):
        dm = DataMasking()
        dm.add_rule(MaskingRule("A", "a", MaskingStrategy.FULL_MASK, priority=10))
        dm.add_rule(MaskingRule("B", "b", MaskingStrategy.FULL_MASK, priority=1))
        listed = dm.list_rules()
        # 高优先级在前
        idx_a = next(i for i, r in enumerate(listed) if r.name == "A")
        idx_b = next(i for i, r in enumerate(listed) if r.name == "B")
        assert idx_a < idx_b

    def test_enable_rule_toggle(self):
        dm = DataMasking()
        dm.enable_rule("手机号", False)
        assert dm.get_rule("手机号").enabled is False
        dm.enable_rule("手机号", True)
        assert dm.get_rule("手机号").enabled is True

    def test_enable_rule_unknown(self):
        """禁用不存在的规则不应报错"""
        dm = DataMasking()
        dm.enable_rule("xxx", False)  # 不应抛出异常


# ============================================================
# 测试内部脱敏方法
# ============================================================

class TestMaskingInternals:
    """_full_mask, _partial_mask, _keep_prefix_mask 等静态方法"""

    def test_full_mask(self):
        assert DataMasking._full_mask("anything") == "****"

    def test_full_mask_empty(self):
        assert DataMasking._full_mask("") == "****"

    def test_partial_mask_short(self):
        assert DataMasking._partial_mask("a") == "*"
        assert DataMasking._partial_mask("ab") == "a*"

    def test_partial_mask_normal(self):
        result = DataMasking._partial_mask("12345")
        assert result == "1***5"

    def test_partial_mask_single_char(self):
        assert DataMasking._partial_mask("x") == "*"

    def test_keep_prefix_mask_short(self):
        assert DataMasking._keep_prefix_mask("12") == "**"

    def test_keep_prefix_mask_long(self):
        result = DataMasking._keep_prefix_mask("13812345678")
        # 前3位可见，中间****，后4位可见
        assert result.startswith("138")
        assert result.endswith("5678")

    def test_keep_prefix_mask_empty(self):
        assert DataMasking._keep_prefix_mask("") == ""

    def test_keep_suffix_mask_short(self):
        assert DataMasking._keep_suffix_mask("12") == "**"

    def test_keep_suffix_mask_normal(self):
        result = DataMasking._keep_suffix_mask("6222021234567890123")
        assert result == "****0123"

    def test_keep_suffix_mask_empty(self):
        assert DataMasking._keep_suffix_mask("") == ""

    def test_hash_mask(self):
        result = DataMasking._hash_mask("test")
        expected = hashlib.md5(b"test").hexdigest()[:12]
        assert result == expected

    def test_hash_mask_deterministic(self):
        assert DataMasking._hash_mask("hello") == DataMasking._hash_mask("hello")


# ============================================================
# 测试 mask_value / _apply_mask
# ============================================================

class TestMaskValue:
    """mask_value 方法"""

    def test_none_returns_none(self):
        dm = DataMasking()
        assert dm.mask_value(None, "phone") is None

    def test_no_field_name_returns_original(self):
        dm = DataMasking()
        assert dm.mask_value("13812345678", "") == "13812345678"

    def test_phone_masked(self):
        dm = DataMasking()
        result = dm.mask_value("13812345678", "phone")
        # phone 默认策略是 KEEP_PREFIX: 前3位 + **** + 后4位
        assert result.startswith("138")
        assert result.endswith("5678")
        assert "****" in result

    def test_password_masked(self):
        dm = DataMasking()
        result = dm.mask_value("my_secret", "password")
        assert result == "****"

    def test_email_masked(self):
        dm = DataMasking()
        result = dm.mask_value("user@example.com", "email")
        # email 默认策略是 HASH: md5 哈希前12位
        expected = hashlib.md5(b"user@example.com").hexdigest()[:12]
        assert result == expected

    def test_id_card_masked(self):
        dm = DataMasking()
        result = dm.mask_value("110101199001011234", "id_card")
        assert len(result) == 18
        assert result != "110101199001011234"

    def test_ip_masked(self):
        dm = DataMasking()
        result = dm.mask_value("192.168.1.1", "ip")
        assert result == "****"  # IP: FULL_MASK

    def test_name_masked(self):
        dm = DataMasking()
        result = dm.mask_value("张三丰", "name")
        assert result == "张*丰"

    def test_unknown_field_returns_original(self):
        dm = DataMasking()
        assert dm.mask_value("hello", "unknown_field") == "hello"


# ============================================================
# 测试 mask_dict
# ============================================================

class TestMaskDict:
    """mask_dict 方法"""

    def test_none_returns_empty_dict(self):
        dm = DataMasking()
        assert dm.mask_dict(None) == {}

    def test_mask_simple_dict(self):
        dm = DataMasking()
        data = {"phone": "13812345678", "name": "张三"}
        result = dm.mask_dict(data)
        assert result["phone"] != "13812345678"
        assert result["name"] != "张三"
        assert "****" in result["phone"] or len(result["phone"]) > 0

    def test_exclude_fields_skipped(self):
        dm = DataMasking()
        data = {"phone": "13812345678", "log": "debug"}
        result = dm.mask_dict(data, exclude_fields=["log"])
        assert result["log"] == "debug"

    def test_nested_dict(self):
        dm = DataMasking()
        data = {"user": {"phone": "13812345678", "name": "李四"}}
        result = dm.mask_dict(data)
        assert result["user"]["phone"] != "13812345678"

    def test_list_of_dicts(self):
        dm = DataMasking()
        data = {"users": [{"phone": "13800000001"}, {"phone": "13900000002"}]}
        result = dm.mask_dict(data)
        assert result["users"][0]["phone"] != "13800000001"
        assert result["users"][1]["phone"] != "13900000002"


# ============================================================
# 测试 mask_log_message
# ============================================================

class TestMaskLogMessage:
    """mask_log_message 方法"""

    def test_empty_message(self):
        dm = DataMasking()
        assert dm.mask_log_message("") == ""
        assert dm.mask_log_message(None) is None

    def test_mask_phone_in_text(self):
        dm = DataMasking()
        msg = "用户手机号: 13812345678"
        result = dm.mask_log_message(msg)
        assert "1**********" in result
        assert "13812345678" not in result

    def test_mask_email_in_text(self):
        dm = DataMasking()
        msg = "邮箱: user@example.com"
        result = dm.mask_log_message(msg)
        assert "user@example.com" not in result

    def test_mask_id_card_in_text(self):
        dm = DataMasking()
        msg = "身份证: 110101199001011234"
        result = dm.mask_log_message(msg)
        assert "110101199001011234" not in result

    def test_mask_ip_in_text(self):
        dm = DataMasking()
        msg = "IP: 192.168.1.100"
        result = dm.mask_log_message(msg)
        assert "192.168.1.100" not in result
        assert "***.***.***.***" in result

    def test_extra_patterns(self):
        dm = DataMasking()
        msg = "token=abc123"
        result = dm.mask_log_message(msg, extra_patterns=[(r"token=\w+", "token=***")])
        assert "token=***" in result

    def test_no_sensitive_info(self):
        """无敏感信息的日志消息保持不变"""
        dm = DataMasking()
        msg = "Hello, this is a normal log message"
        result = dm.mask_log_message(msg)
        assert result == msg


# ============================================================
# 测试 mask_export_data
# ============================================================

class TestMaskExportData:
    """mask_export_data 方法"""

    def test_empty_data(self):
        dm = DataMasking()
        assert dm.mask_export_data([], ["col1"]) == []

    def test_auto_masking_by_column_name(self):
        dm = DataMasking()
        data = [{"phone": "13812345678", "name": "张三"}]
        result = dm.mask_export_data(data, ["phone", "name"])
        row = result[0]
        assert row["phone"] != "13812345678"
        assert row["name"] != "张三"

    def test_custom_masking_config(self):
        dm = DataMasking()
        data = [{"col": "hello"}]
        result = dm.mask_export_data(data, ["col"], masking_config={"col": "full"})
        assert result[0]["col"] == "****"

    def test_custom_config_keep_prefix(self):
        dm = DataMasking()
        data = [{"col": "hello_world"}]
        result = dm.mask_export_data(data, ["col"], masking_config={"col": "keep_prefix"})
        assert result[0]["col"] != "hello_world"

    def test_custom_config_keep_suffix(self):
        dm = DataMasking()
        data = [{"col": "hello_world"}]
        result = dm.mask_export_data(data, ["col"], masking_config={"col": "keep_suffix"})
        assert result[0]["col"] != "hello_world"

    def test_custom_config_unknown_strategy(self):
        dm = DataMasking()
        data = [{"col": "hello"}]
        result = dm.mask_export_data(data, ["col"], masking_config={"col": "unknown"})
        assert result[0]["col"] == "hello"


# ============================================================
# 测试全局便利函数
# ============================================================

class TestGlobalFunctions:
    """get_data_masking, mask_sensitive_data, mask_log_message"""

    def test_get_data_masking_singleton(self):
        dm1 = get_data_masking()
        dm2 = get_data_masking()
        assert dm1 is dm2

    def test_mask_sensitive_data(self):
        result = mask_sensitive_data("13812345678", "phone")
        assert result != "13812345678"

    def test_mask_sensitive_data_no_field(self):
        assert mask_sensitive_data("hello", "") == "hello"

    def test_mask_log_message_top_level(self):
        result = mask_log_message("手机: 13812345678")
        assert "13812345678" not in result
