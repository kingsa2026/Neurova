"""
Agent Firewall - 三层防火墙系统

L0: 入口网关 + 输出脱敏 (Flask 中间件)
L1: 用户隔离 + Agent 隔离
L2: 文件访问保护

规则优先级: admin 全局默认 → 用户追加 (只能加严不能放松)
外部请求包含: 用户 API、Webhook、外部回调
外部请求排除: LLM 服务、模型推理服务（信任域内部流量）
"""

from dataclasses import dataclass, field
import functools
import json
import logging
import os
from pathlib import Path
import re
import threading
import time
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


@dataclass
class GlobalRuleSet:
    """全局规则集（admin 默认）"""
    rate_limit_per_minute: int = 60
    rate_limit_per_hour: int = 1000
    allowed_ips: List[str] = field(default_factory=list)
    blocked_ips: List[str] = field(default_factory=list)
    max_input_length: int = 10000
    max_file_size_mb: int = 50
    blocked_paths: List[str] = field(default_factory=lambda: [
        "/etc/passwd", "/etc/shadow", "/root", "/home",
        "C:\\Windows", "C:\\Users",
    ])
    sensitive_output_patterns: List[str] = field(default_factory=lambda: [
        r"api[_-]?key", r"password", r"secret", r"token",
        r"Bearer\s+\S+", r"sk-\w+",
    ])
    llm_trust_domains: List[str] = field(default_factory=lambda: [
        "api.openai.com", "api.anthropic.com", "generativelanguage.googleapis.com",
        "localhost", "127.0.0.1",
    ])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rate_limit_per_minute": self.rate_limit_per_minute,
            "rate_limit_per_hour": self.rate_limit_per_hour,
            "allowed_ips": self.allowed_ips,
            "blocked_ips": self.blocked_ips,
            "max_input_length": self.max_input_length,
            "max_file_size_mb": self.max_file_size_mb,
            "blocked_paths": self.blocked_paths,
            "sensitive_output_patterns": self.sensitive_output_patterns,
            "llm_trust_domains": self.llm_trust_domains,
        }


@dataclass
class UserRuleSet:
    """用户级规则集（只能加严不能放松）"""
    user_id: str = ""
    rate_limit_per_minute: Optional[int] = None
    rate_limit_per_hour: Optional[int] = None
    blocked_ips: List[str] = field(default_factory=list)
    extra_blocked_paths: List[str] = field(default_factory=list)
    agent_isolation: bool = True  # Agent 间隔离

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "rate_limit_per_minute": self.rate_limit_per_minute,
            "rate_limit_per_hour": self.rate_limit_per_hour,
            "blocked_ips": self.blocked_ips,
            "extra_blocked_paths": self.extra_blocked_paths,
            "agent_isolation": self.agent_isolation,
        }


class AgentFirewall:
    """
    Agent 三层防火墙

    L0: 入口网关 + 输出脱敏
    L1: 用户隔离 + Agent 隔离
    L2: 文件访问保护
    """

    def __init__(self, config_path: Optional[str] = None):
        self._config_path = config_path
        self._lock = threading.RLock()

        # 全局规则
        self._global_rules = GlobalRuleSet()

        # 用户规则: user_id -> UserRuleSet
        self._user_rules: Dict[str, UserRuleSet] = {}

        # 速率限制计数器: (user_id, window_start) -> count
        self._rate_counters: Dict[Tuple[str, str], int] = {}

        # 编译敏感输出正则
        self._sensitive_patterns = [
            re.compile(p, re.IGNORECASE)
            for p in self._global_rules.sensitive_output_patterns
        ]

        # 加载配置
        self._load()

    def _load(self) -> None:
        """加载配置文件"""
        if not self._config_path:
            return
        try:
            path = Path(self._config_path)
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if "global" in data:
                    for k, v in data["global"].items():
                        if hasattr(self._global_rules, k):
                            setattr(self._global_rules, k, v)
                if "users" in data:
                    for uid, udata in data["users"].items():
                        self._user_rules[uid] = UserRuleSet(user_id=uid, **udata)
        except Exception as e:
            logger.warning(f"Failed to load firewall config: {e}")

    def _save_global(self) -> None:
        """保存全局规则"""
        if not self._config_path:
            return
        try:
            Path(self._config_path).parent.mkdir(parents=True, exist_ok=True)
            data = {
                "global": self._global_rules.to_dict(),
                "users": {uid: rules.to_dict() for uid, rules in self._user_rules.items()},
            }
            with open(self._config_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save firewall config: {e}")

    def _save_user(self, user_id: str) -> None:
        """保存用户规则"""
        self._save_global()

    def get_global_rules(self) -> Dict[str, Any]:
        """获取全局规则"""
        return self._global_rules.to_dict()

    def update_global_rules(self, updates: Dict[str, Any]) -> None:
        """更新全局规则"""
        with self._lock:
            for k, v in updates.items():
                if hasattr(self._global_rules, k):
                    setattr(self._global_rules, k, v)
            self._save_global()
            logger.info("Global firewall rules updated")

    def get_user_rules(self, user_id: str) -> Dict[str, Any]:
        """获取用户规则"""
        rules = self._user_rules.get(user_id)
        return rules.to_dict() if rules else {}

    def update_user_rules(self, user_id: str, updates: Dict[str, Any]) -> None:
        """更新用户规则"""
        with self._lock:
            if user_id not in self._user_rules:
                self._user_rules[user_id] = UserRuleSet(user_id=user_id)
            rules = self._user_rules[user_id]
            for k, v in updates.items():
                if hasattr(rules, k):
                    setattr(rules, k, v)
            self._save_user(user_id)

    def get_effective_rules(self, user_id: str) -> Dict[str, Any]:
        """获取合并后的有效规则（全局 + 用户，取更严格值）"""
        global_rules = self._global_rules
        user_rules = self._user_rules.get(user_id)

        effective = global_rules.to_dict()
        if user_rules:
            # 速率限制取更小值
            if user_rules.rate_limit_per_minute is not None:
                effective["rate_limit_per_minute"] = min(
                    effective["rate_limit_per_minute"],
                    user_rules.rate_limit_per_minute,
                )
            if user_rules.rate_limit_per_hour is not None:
                effective["rate_limit_per_hour"] = min(
                    effective["rate_limit_per_hour"],
                    user_rules.rate_limit_per_hour,
                )
            # IP 黑名单合并
            effective["blocked_ips"] = list(set(
                effective["blocked_ips"] + user_rules.blocked_ips
            ))
            # 路径黑名单合并
            effective["blocked_paths"] = list(set(
                effective["blocked_paths"] + user_rules.extra_blocked_paths
            ))
            effective["agent_isolation"] = user_rules.agent_isolation

        return effective

    def is_agent_isolated(self, user_id: str) -> bool:
        """检查用户是否启用了 Agent 隔离"""
        rules = self._user_rules.get(user_id)
        return rules.agent_isolation if rules else True

    def check_rate_limit(self, user_id: str) -> Tuple[bool, str]:
        """
        检查速率限制

        Returns:
            (是否允许, 拒绝原因)
        """
        now = time.time()
        minute_key = (user_id, f"min_{int(now // 60)}")
        hour_key = (user_id, f"hour_{int(now // 3600)}")

        effective = self.get_effective_rules(user_id)

        with self._lock:
            # 清理旧计数器
            self._cleanup_counters(now)

            # 检查每分钟限制
            min_count = self._rate_counters.get(minute_key, 0)
            if min_count >= effective["rate_limit_per_minute"]:
                return False, "Rate limit exceeded (per minute)"

            # 检查每小时限制
            hour_count = self._rate_counters.get(hour_key, 0)
            if hour_count >= effective["rate_limit_per_hour"]:
                return False, "Rate limit exceeded (per hour)"

            # 增加计数
            self._rate_counters[minute_key] = min_count + 1
            self._rate_counters[hour_key] = hour_count + 1

        return True, ""

    def _cleanup_counters(self, now: float) -> None:
        """清理过期的速率计数器"""
        cutoff_min = f"min_{int(now // 60) - 2}"
        cutoff_hour = f"hour_{int(now // 3600) - 2}"
        to_delete = [
            key for key in self._rate_counters
            if key[1] < cutoff_min or key[1] < cutoff_hour
        ]
        for key in to_delete:
            del self._rate_counters[key]

    def check_ip_access(self, ip: str, user_id: str = "") -> Tuple[bool, str]:
        """检查 IP 访问权限"""
        effective = self.get_effective_rules(user_id) if user_id else self._global_rules.to_dict()

        if ip in effective.get("blocked_ips", []):
            return False, f"IP {ip} is blocked"

        allowed = effective.get("allowed_ips", [])
        if allowed and ip not in allowed:
            return False, f"IP {ip} not in allowed list"

        return True, ""

    def is_llm_internal(self, domain: str) -> bool:
        """检查是否为 LLM 内部信任域"""
        return any(
            trust in domain
            for trust in self._global_rules.llm_trust_domains
        )

    def validate_input(self, text: str, user_id: str = "") -> Tuple[bool, str]:
        """
        验证输入文本

        Returns:
            (是否有效, 拒绝原因)
        """
        effective = self.get_effective_rules(user_id) if user_id else self._global_rules.to_dict()

        max_len = effective.get("max_input_length", 10000)
        if len(text) > max_len:
            return False, f"Input exceeds max length ({max_len})"

        return True, ""

    def sanitize_output(self, text: str) -> str:
        """
        输出脱敏 - 替换敏感信息

        Args:
            text: 原始输出文本

        Returns:
            脱敏后的文本
        """
        result = text
        for pattern in self._sensitive_patterns:
            result = pattern.sub("[REDACTED]", result)
        return result

    def check_file_access(self, filepath: str, user_id: str = "") -> Tuple[bool, str]:
        """
        检查文件访问权限（L2）

        Returns:
            (是否允许, 拒绝原因)
        """
        effective = self.get_effective_rules(user_id) if user_id else self._global_rules.to_dict()
        blocked = effective.get("blocked_paths", [])

        resolved = str(Path(filepath).resolve())
        for blocked_path in blocked:
            if resolved.startswith(str(Path(blocked_path).resolve())):
                return False, f"Access to {blocked_path} is blocked"

        return True, ""

    def check_agent_access(
        self, source_agent: str, target_agent: str, user_id: str
    ) -> Tuple[bool, str]:
        """
        检查 Agent 间访问权限（L1）

        Returns:
            (是否允许, 拒绝原因)
        """
        if self.is_agent_isolated(user_id):
            if source_agent != target_agent:
                return False, "Agent isolation enabled: cross-agent access denied"
        return True, ""

    def check_cross_agent(
        self, agent_id: str, resource: str, user_id: str
    ) -> Tuple[bool, str]:
        """检查跨 Agent 资源访问"""
        return self.check_agent_access(agent_id, resource, user_id)


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------

_firewall: Optional[AgentFirewall] = None
_lock = threading.Lock()


def get_firewall(config_path: Optional[str] = None) -> AgentFirewall:
    """获取全局防火墙实例"""
    global _firewall
    if _firewall is None:
        with _lock:
            if _firewall is None:
                _firewall = AgentFirewall(config_path=config_path)
    return _firewall


def reset_firewall() -> None:
    """重置全局防火墙（用于测试）"""
    global _firewall
    with _lock:
        _firewall = None
