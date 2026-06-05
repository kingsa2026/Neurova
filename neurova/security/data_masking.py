from __future__ import annotations

"""
Neurova 数据脱敏模块

功能:
1. 日志脱敏规则配置
2. 敏感字段识别（手机号、邮箱、身份证等）
3. 导出数据自动脱敏
4. 脱敏策略管理
"""

from dataclasses import dataclass, field
import enum
import hashlib
import logging
import re
import threading
from enum import Enum
from typing import Dict, Any, List, Optional, Pattern, Callable, Union

logger = logging.getLogger(__name__)


class MaskingStrategy(str, Enum):
    """脱敏策略"""
    FULL_MASK = "full"
    PARTIAL_MASK = "partial"
    KEEP_PREFIX = "keep_prefix"
    KEEP_SUFFIX = "keep_suffix"
    HASH = "hash"
    CUSTOM = "custom"


@dataclass
class MaskingRule:
    """脱敏规则"""
    name: str
    field_name: str
    strategy: MaskingStrategy
    pattern: Optional[Pattern] = None
    replacement: Optional[str] = None
    custom_func: Optional[Callable[[str], str]] = None
    enabled: bool = True
    priority: int = 0

    def __post_init__(self):
        if self.pattern is None and self.field_name:
            try:
                self.pattern = re.compile(self.field_name)
            except re.error:
                self.pattern = re.compile(re.escape(self.field_name))


@dataclass
class SensitiveField:
    """敏感字段定义"""
    field_name: str
    field_type: str
    example: str = ""


PREDEFINED_SENSITIVE_FIELDS = [
    SensitiveField("password", "密码", "my_secret_123"),
    SensitiveField("phone", "手机号", "13812345678"),
    SensitiveField("email", "邮箱", "user@example.com"),
    SensitiveField("id_card", "身份证", "110101199001011234"),
    SensitiveField("bank_card", "银行卡", "6222021234567890123"),
    SensitiveField("address", "地址", "北京市朝阳区xxx"),
    SensitiveField("ip_address", "IP地址", "192.168.1.1"),
    SensitiveField("name", "姓名", "张三"),
]


# 手机号、邮箱、身份证、IP 的正则（用于文本中的日志脱敏）
_PHONE_RE = re.compile(r'\b(1[3-9]\d{9})\b')
_EMAIL_RE = re.compile(r'\b([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})\b')
_ID_CARD_RE = re.compile(r'\b(\d{17}[\dXx])\b')
_IP_RE = re.compile(r'\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b')


class DataMasking:
    """数据脱敏引擎"""

    def __init__(self):
        self._rules: Dict[str, MaskingRule] = {}
        self._load_default_rules()

    def _load_default_rules(self):
        """加载默认脱敏规则"""
        defaults = [
            MaskingRule("手机号", "phone", MaskingStrategy.KEEP_PREFIX, priority=10),
            MaskingRule("邮箱", "email", MaskingStrategy.HASH, priority=9),
            MaskingRule("身份证", "id_card", MaskingStrategy.KEEP_PREFIX, priority=10),
            MaskingRule("IP地址", "ip", MaskingStrategy.FULL_MASK, priority=8),
            MaskingRule("密码", "password", MaskingStrategy.FULL_MASK, priority=100),
            MaskingRule("姓名", "name", MaskingStrategy.PARTIAL_MASK, priority=7),
            MaskingRule("地址", "address", MaskingStrategy.FULL_MASK, priority=6),
            MaskingRule("银行卡", "bank_card", MaskingStrategy.KEEP_SUFFIX, priority=9),
        ]
        for rule in defaults:
            self._rules[rule.name] = rule

    def add_rule(self, rule: MaskingRule):
        """添加脱敏规则"""
        if rule.pattern is None and rule.field_name:
            try:
                rule.pattern = re.compile(rule.field_name)
            except re.error:
                rule.pattern = re.compile(re.escape(rule.field_name))
        self._rules[rule.name] = rule

    def remove_rule(self, name: str) -> bool:
        """移除脱敏规则"""
        if name in self._rules:
            del self._rules[name]
            return True
        return False

    def get_rule(self, name: str) -> Optional[MaskingRule]:
        """获取脱敏规则"""
        return self._rules.get(name)

    def list_rules(self) -> List[MaskingRule]:
        """列出所有规则（按优先级降序）"""
        return sorted(self._rules.values(), key=lambda r: r.priority, reverse=True)

    def enable_rule(self, name: str, enabled: bool):
        """启用/禁用规则"""
        if name in self._rules:
            self._rules[name].enabled = enabled

    # ========================= 静态脱敏方法 =========================

    @staticmethod
    def _full_mask(value: str) -> str:
        return "****"

    @staticmethod
    def _partial_mask(value: str) -> str:
        if len(value) <= 1:
            return "*"
        if len(value) == 2:
            return value[0] + "*"
        return value[0] + "*" * (len(value) - 2) + value[-1]

    @staticmethod
    def _keep_prefix_mask(value: str, prefix_len: int = 3, suffix_len: int = 4) -> str:
        if not value:
            return ""
        if len(value) <= prefix_len + suffix_len:
            return "*" * len(value)
        return value[:prefix_len] + "*" * (len(value) - prefix_len - suffix_len) + value[-suffix_len:]

    @staticmethod
    def _keep_suffix_mask(value: str, suffix_len: int = 4) -> str:
        if not value:
            return ""
        if len(value) <= suffix_len:
            return "*" * len(value)
        return "****" + value[-suffix_len:]

    @staticmethod
    def _hash_mask(value: str) -> str:
        return hashlib.md5(value.encode()).hexdigest()[:12]

    def _apply_mask(self, value: str, rule: MaskingRule) -> str:
        """应用脱敏规则"""
        if rule.strategy == MaskingStrategy.FULL_MASK:
            return self._full_mask(value)
        elif rule.strategy == MaskingStrategy.PARTIAL_MASK:
            return self._partial_mask(value)
        elif rule.strategy == MaskingStrategy.KEEP_PREFIX:
            return self._keep_prefix_mask(value)
        elif rule.strategy == MaskingStrategy.KEEP_SUFFIX:
            return self._keep_suffix_mask(value)
        elif rule.strategy == MaskingStrategy.HASH:
            return self._hash_mask(value)
        elif rule.strategy == MaskingStrategy.CUSTOM:
            if rule.custom_func:
                return rule.custom_func(value)
            return self._full_mask(value)
        return value

    def _find_rule_for_field(self, field_name: str) -> Optional[MaskingRule]:
        """根据字段名查找匹配的规则"""
        for rule in self._rules.values():
            if not rule.enabled:
                continue
            if rule.pattern and rule.pattern.match(field_name):
                return rule
        return None

    # ========================= 公共接口 =========================

    def mask_value(self, value: Any, field_name: str) -> Any:
        """对单个值进行脱敏"""
        if value is None:
            return None
        if not field_name:
            return value

        rule = self._find_rule_for_field(field_name)
        if rule:
            return self._apply_mask(str(value), rule)
        return value

    def mask_dict(self, data: Optional[Dict], exclude_fields: List[str] = None) -> Dict:
        """对字典进行脱敏"""
        if data is None:
            return {}
        exclude = set(exclude_fields or [])
        return self._mask_dict_recursive(data, exclude)

    def _mask_dict_recursive(self, data: Any, exclude: set) -> Any:
        if isinstance(data, dict):
            result = {}
            for key, value in data.items():
                if key in exclude:
                    result[key] = value
                elif isinstance(value, (dict, list)):
                    result[key] = self._mask_dict_recursive(value, exclude)
                else:
                    result[key] = self.mask_value(value, key)
            return result
        elif isinstance(data, list):
            return [self._mask_dict_recursive(item, exclude) for item in data]
        return data

    def mask_log_message(self, message: Optional[str],
                         extra_patterns: List[tuple] = None) -> Optional[str]:
        """对日志消息中的敏感信息进行脱敏"""
        if message is None:
            return None
        if not message:
            return message

        result = message
        # 手机号
        result = _PHONE_RE.sub(lambda m: m.group(1)[0] + "*" * (len(m.group(1)) - 1), result)
        # 邮箱
        result = _EMAIL_RE.sub(lambda m: self._hash_mask(m.group(1)), result)
        # 身份证
        result = _ID_CARD_RE.sub(lambda m: self._keep_prefix_mask(m.group(1), 3, 4), result)
        # IP
        result = _IP_RE.sub("***.***.***.***", result)

        # 额外模式
        if extra_patterns:
            for pattern, replacement in extra_patterns:
                result = re.sub(pattern, replacement, result)

        return result

    def mask_export_data(self, data: List[Dict], columns: List[str],
                         masking_config: Optional[Dict[str, str]] = None) -> List[Dict]:
        """对导出数据进行脱敏"""
        if not data:
            return []

        config = masking_config or {}
        result = []

        strategy_map = {
            "full": MaskingStrategy.FULL_MASK,
            "partial": MaskingStrategy.PARTIAL_MASK,
            "keep_prefix": MaskingStrategy.KEEP_PREFIX,
            "keep_suffix": MaskingStrategy.KEEP_SUFFIX,
            "hash": MaskingStrategy.HASH,
        }

        for row in data:
            masked_row = {}
            for col, value in row.items():
                if col in config:
                    strategy = strategy_map.get(config[col])
                    if strategy:
                        rule = MaskingRule("_export", col, strategy)
                        masked_row[col] = self._apply_mask(str(value), rule)
                    else:
                        masked_row[col] = value
                else:
                    masked_row[col] = self.mask_value(value, col)
            result.append(masked_row)

        return result


# ========================= 全局单例和便捷函数 =========================

_data_masking: Optional[DataMasking] = None
_dm_lock = threading.Lock()


def get_data_masking() -> DataMasking:
    global _data_masking
    if _data_masking is None:
        with _dm_lock:
            if _data_masking is None:
                _data_masking = DataMasking()
    return _data_masking


def mask_sensitive_data(value: Any, field_name: str) -> Any:
    return get_data_masking().mask_value(value, field_name)


def mask_log_message(message: Optional[str], extra_patterns: List[tuple] = None) -> Optional[str]:
    return get_data_masking().mask_log_message(message, extra_patterns)
