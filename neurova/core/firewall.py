"""
Agent Firewall - 三层防火墙系统

L0: 入口网关 + 输出脱敏 (Flask 中间件)
L1: 用户隔离 + Agent 隔离
L2: 文件访问保护

规则优先级: admin 全局默认 → 用户追加 (只能加严不能放松)
外部请求包含: 用户 API、Webhook、外部回调
外部请求排除: LLM 服务、模型推理服务（信任域内部流量）
"""

import json
import os
from neurova.core.logger import get_logger
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from neurova.core.data_root import dataPath

logger = get_logger(__name__)

#: 速率限制的渠道维度。internal 沿用既有额度档；externalAgent 是外部 Agent 接入
#: （API Key / 握手 / 消息投递）专用档——其批量同步量级远高于人用交互，不能同人用额度。
CHANNEL_INTERNAL = "internal"
CHANNEL_EXTERNAL_AGENT = "externalAgent"

#: 被限流后回给客户端的重试等待秒数，与分钟窗口对齐；执行点与额度同源，故写在这里。
RATE_LIMIT_RETRY_AFTER_SECONDS = 60


@dataclass
class GlobalRuleSet:
    """全局规则集（admin 默认）"""

    # internal 档不是"文档里的默认值"，而是全站唯一限流执行点当前在跑的额度：
    # RateLimitMiddleware 此前把 120/分 硬编码在 add_middleware 调用里，firewall 里
    # 那个 60 从来没有调用方。收口到本文件时若沿用 60，等于把人用流量当场收紧一半。
    # 小时档取 120×60，使小时闸在今天不会先于分钟闸生效（中间件从无小时上限）。
    rate_limit_per_minute: int = 120
    rate_limit_per_hour: int = 7200
    external_rate_limit_per_minute: int = 300
    external_rate_limit_per_hour: int = 20000
    allowed_ips: List[str] = field(default_factory=list)
    blocked_ips: List[str] = field(default_factory=list)
    max_input_length: int = 10000
    max_file_size_mb: int = 50
    blocked_paths: List[str] = field(
        default_factory=lambda: [
            "/etc/passwd",
            "/etc/shadow",
            "/root",
            "/home",
            "C:\\Windows",
            "C:\\Users",
        ]
    )
    sensitive_output_patterns: List[str] = field(
        default_factory=lambda: [
            r"api[_-]?key",
            r"password",
            r"secret",
            r"token",
            r"Bearer\s+\S+",
            r"sk-\w+",
        ]
    )
    llm_trust_domains: List[str] = field(
        default_factory=lambda: [
            "api.openai.com",
            "api.anthropic.com",
            "generativelanguage.googleapis.com",
            "localhost",
            "127.0.0.1",
        ]
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rate_limit_per_minute": self.rate_limit_per_minute,
            "rate_limit_per_hour": self.rate_limit_per_hour,
            "external_rate_limit_per_minute": self.external_rate_limit_per_minute,
            "external_rate_limit_per_hour": self.external_rate_limit_per_hour,
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

        # 组档位 resolver（由 API 层装配注入；core 不 import auth，避免成环）
        self._rateQuotaResolver = None
        self._rateQuotaTtlSeconds = 60.0
        self._rateQuotaCache: Dict[str, Tuple[Optional[int], float]] = {}

        # 编译敏感输出正则
        self._sensitive_patterns = [re.compile(p, re.IGNORECASE) for p in self._global_rules.sensitive_output_patterns]

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
                        # 合法键单源取 dataclass 字段：hasattr 会把方法与属性一并算作
                        # 合法，且未知键过去被无声丢弃（改动静默 no-op 却报成功）。
                        if k in GlobalRuleSet.__dataclass_fields__:
                            setattr(self._global_rules, k, v)
                        else:
                            logger.warning("防火墙配置含未知全局键，已忽略: %s", k)
                if "users" in data:
                    for uid, udata in data["users"].items():
                        self._user_rules[uid] = UserRuleSet(user_id=uid, **udata)
        except Exception as e:
            logger.warning("Failed to load firewall config: %s", e)

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
            logger.error("Failed to save firewall config: %s", e)

    def _save_user(self, user_id: str) -> None:
        """保存用户规则"""
        self._save_global()

    def get_global_rules(self) -> Dict[str, Any]:
        """获取全局规则"""
        return self._global_rules.to_dict()

    def update_global_rules(self, updates: Dict[str, Any]) -> None:
        """更新全局规则

        先验后写：`updates` 里只要有一个未知键就整条拒绝（ValueError），不出现
        "半生效 + 报成功"。此前这里是 `if hasattr` 逐个筛——未知键被无声丢弃，
        函数照样落盘返回，REST 层紧接着记 "Global firewall rules updated"。
        我接外部渠道额度时给的正是一个当时不存在的键名，低额度注入就这样 no-op 了。

        合法键名单源 = `GlobalRuleSet` 的 dataclass 字段，不另立第二份清单。
        """
        unknown = sorted(k for k in updates if k not in GlobalRuleSet.__dataclass_fields__)
        if unknown:
            raise ValueError(
                f"未知的全局规则键: {unknown}；合法键名取自 GlobalRuleSet 字段"
            )

        with self._lock:
            for k, v in updates.items():
                setattr(self._global_rules, k, v)
            self._save_global()
            logger.info("Global firewall rules updated")

    def get_user_rules(self, user_id: str) -> Dict[str, Any]:
        """获取用户规则"""
        rules = self._user_rules.get(user_id)
        return rules.to_dict() if rules else {}

    def update_user_rules(self, user_id: str, updates: Dict[str, Any]) -> None:
        """更新用户规则（与 `update_global_rules` 同规则：先验后写，未知键点名拒绝）"""
        unknown = sorted(k for k in updates if k not in UserRuleSet.__dataclass_fields__)
        if unknown:
            raise ValueError(
                f"未知的用户规则键: {unknown}；合法键名取自 UserRuleSet 字段"
            )

        with self._lock:
            if user_id not in self._user_rules:
                self._user_rules[user_id] = UserRuleSet(user_id=user_id)
            rules = self._user_rules[user_id]
            for k, v in updates.items():
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
            effective["blocked_ips"] = list(set(effective["blocked_ips"] + user_rules.blocked_ips))
            # 路径黑名单合并
            effective["blocked_paths"] = list(set(effective["blocked_paths"] + user_rules.extra_blocked_paths))
            effective["agent_isolation"] = user_rules.agent_isolation

        return effective

    def is_agent_isolated(self, user_id: str) -> bool:
        """检查用户是否启用了 Agent 隔离"""
        rules = self._user_rules.get(user_id)
        return rules.agent_isolation if rules else True

    def setRateQuotaResolver(self, resolver, ttlSeconds: float = 60.0) -> None:
        """注入"用户 → 每分钟额度"的解析器（组档位由 API 层提供）。

        core 不 import auth（会成环），故只接受注入。结果带 TTL 缓存——限流在每请求
        路径上，不能每次都查库。
        """
        self._rateQuotaResolver = resolver
        self._rateQuotaTtlSeconds = ttlSeconds

    def _groupRateFor(self, user_id: str) -> Optional[int]:
        resolver = self._rateQuotaResolver
        if resolver is None or not user_id:
            return None

        now = time.time()
        with self._lock:
            hit = self._rateQuotaCache.get(user_id)
            if hit and hit[1] > now:
                return hit[0]

        try:
            rate = resolver(user_id)
        except Exception as e:  # 解析器炸了不得拒请求
            logger.warning("额度解析器异常，回落默认档: %s", e)
            rate = None

        with self._lock:
            if len(self._rateQuotaCache) > 4096:
                self._rateQuotaCache = {
                    key: value for key, value in self._rateQuotaCache.items() if value[1] > now
                }
            self._rateQuotaCache[user_id] = (rate, now + self._rateQuotaTtlSeconds)

        return rate

    def check_rate_limit(self, user_id: str, channel: str = CHANNEL_INTERNAL) -> Tuple[bool, str]:
        """
        检查速率限制

        计数键带渠道前缀，使外部 Agent 流量与人用流量互不扣额；键域仍是 user_id
        （同一用户下的多个外部 Agent 共享一份额度，这是有意语义）。

        internal 渠道优先用组档位（取最宽）；解析不到才回落全局默认。externalAgent
        渠道不受用户组影响——那是接入面容量决策，不是用户权益。

        Returns:
            (是否允许, 拒绝原因)
        """
        now = time.time()
        minute_key = (user_id, f"{channel}:min_{int(now // 60)}")
        hour_key = (user_id, f"{channel}:hour_{int(now // 3600)}")

        effective = self.get_effective_rules(user_id)
        if channel == CHANNEL_EXTERNAL_AGENT:
            per_minute = effective["external_rate_limit_per_minute"]
            per_hour = effective["external_rate_limit_per_hour"]
        else:
            per_minute = effective["rate_limit_per_minute"]
            per_hour = effective["rate_limit_per_hour"]
            groupRate = self._groupRateFor(user_id)
            if groupRate:
                per_minute = groupRate
                # 组档只定义分钟值；小时闸按 60 倍折算，使其不会先于分钟闸生效。
                per_hour = groupRate * 60

        with self._lock:
            # 清理旧计数器
            self._cleanup_counters(now)

            # 检查每分钟限制
            min_count = self._rate_counters.get(minute_key, 0)
            if min_count >= per_minute:
                return False, f"Rate limit exceeded (per minute, channel={channel})"

            # 检查每小时限制
            hour_count = self._rate_counters.get(hour_key, 0)
            if hour_count >= per_hour:
                return False, f"Rate limit exceeded (per hour, channel={channel})"

            # 增加计数
            self._rate_counters[minute_key] = min_count + 1
            self._rate_counters[hour_key] = hour_count + 1

        return True, ""

    def _cleanup_counters(self, now: float) -> None:
        """清理过期的速率计数器（只保留当前与上一个窗口）"""
        minute_index = int(now // 60)
        hour_index = int(now // 3600)
        stale = []
        for key in self._rate_counters:
            window = key[1]
            kind, _, raw_index = window.rpartition("_")
            if not raw_index.isdigit():
                stale.append(key)
                continue
            index = int(raw_index)
            if kind.endswith(":min") and index < minute_index - 1:
                stale.append(key)
            elif kind.endswith(":hour") and index < hour_index - 1:
                stale.append(key)
        for key in stale:
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
        return any(trust in domain for trust in self._global_rules.llm_trust_domains)

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

    def check_agent_access(self, source_agent: str, target_agent: str, user_id: str) -> Tuple[bool, str]:
        """
        检查 Agent 间访问权限（L1）

        Returns:
            (是否允许, 拒绝原因)
        """
        if self.is_agent_isolated(user_id):
            if source_agent != target_agent:
                return False, "Agent isolation enabled: cross-agent access denied"
        return True, ""

    def check_cross_agent(self, agent_id: str, resource: str, user_id: str) -> Tuple[bool, str]:
        """检查跨 Agent 资源访问"""
        return self.check_agent_access(agent_id, resource, user_id)


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------

_firewall: Optional[AgentFirewall] = None
_lock = threading.Lock()


def get_firewall(config_path: Optional[str] = None) -> AgentFirewall:
    """获取全局防火墙实例

    2026-09-12 P3：此前生产调用方从不传 config_path → AgentFirewall._load/
    _save_global 早退，经 API 增删的规则只活在内存重启即丢。现默认落盘
    NEUROVA_FIREWALL_PATH 或 data/firewall.json。
    """
    global _firewall
    if _firewall is None:
        with _lock:
            if _firewall is None:
                _firewall = AgentFirewall(
                    config_path=config_path
                    or os.environ.get("NEUROVA_FIREWALL_PATH")
                    or dataPath("firewall.json")
                )
    return _firewall


def reset_firewall() -> None:
    """重置全局防火墙（用于测试）"""
    global _firewall
    with _lock:
        _firewall = None
