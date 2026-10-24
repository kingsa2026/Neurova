"""
记忆安全与隐私 - 敏感信息检测、加密存储、被遗忘权
"""

import datetime
import hashlib
from neurova.core.logger import get_logger
import os
import re
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Pattern, Tuple

from .models import Memory

# 可选依赖处理
try:
    from cryptography.fernet import Fernet

    HAS_CRYPTOGRAPHY = True
except ImportError:
    HAS_CRYPTOGRAPHY = False

logger = get_logger(__name__)

_ENCRYPTION_KEY_FILENAME = ".neurova_memory_encryption_key"


def _load_or_create_encryption_key() -> str:
    """读取或创建持久化记忆加密密钥，保证重启 / 多 worker 之间密钥一致（BUG AUDIT M-12）。

    旧实现当 encryption_key 未配置时每次进程生成新随机密钥 → 重启后已加密记忆
    无法解密（解密静默返回空串，记忆"消失"）。现改为从持久化文件读取（不存在则
    生成符合 Fernet 规范的密钥并 0600 保存）。
    """
    if not HAS_CRYPTOGRAPHY:
        raise RuntimeError(
            "cryptography 库未安装，无法产出可持久的 Fernet 密钥 — run: pip install cryptography"
        )
    try:
        # 原实现读一个全仓不存在的 `config.DATA_DIR`，再兜底到裸相对名 `"data"`
        # ——换个启动目录就换一份加密密钥，旧记忆解密静默返回空串（"记忆消失"）。
        from neurova.core.data_root import dataLanding

        data_dir = str(dataLanding(_ENCRYPTION_KEY_FILENAME).parent)
        os.makedirs(data_dir, exist_ok=True)
        key_path = os.path.join(data_dir, _ENCRYPTION_KEY_FILENAME)
        if os.path.exists(key_path):
            with open(key_path, "r", encoding="utf-8") as _f:
                existing = _f.read().strip()
            if existing:
                return existing
        # 生成符合 Fernet 规范的密钥（32 url-safe base64 字节）
        new_key = Fernet.generate_key().decode()
        with open(key_path, "w", encoding="utf-8") as _f:
            _f.write(new_key)
        try:
            os.chmod(key_path, 0o600)
        except OSError:
            pass
        return new_key
    except Exception as e:
        # M-12 的另一半：发一把"重启即失效"的临时钥匙，等于亲手制造下一次"记忆消失"，
        # 只 warning 一句就继续跑是把故障挪到更远的地方。宁可当场不起。
        logger.error("记忆加密密钥无法持久化，拒绝使用一次性临时密钥: %s", e)
        raise RuntimeError(
            f"记忆加密密钥未能写入数据根（拒绝回退到重启即失效的临时密钥）: {e}"
        ) from e


# ────── Enums ──────


#: 敏感度尺度与规则形状都在 `neurova/security/sensitive_info.py`（§6-411 批 O-5 收口）。
#: 这里留**别名**而不是第二份定义：本模块历史上自带 `SensitivityLevel` 与 `SensitivePattern`，
#: 与 cognitive 那边的 `SafetyLevel`＋自己那张 8 条表、firewall 那边那张 6 条表，
#: 同一件事在仓内有四份口径——同一条规则可以有两个分级、脱敏有四套循环。
from neurova.security.sensitive_info import (  # noqa: E402  (别名再导出，保持既有 import 面)
    SENSITIVE_RULES,
    SensitiveRule as SensitivePattern,
    SensitivityLevel,
    detectSensitive,
    highestSeverity,
    maskPreservingFormat,
    sanitizeSensitive,
)


class EncryptionMethod(Enum):
    """加密方法"""

    NONE = "none"  # 不加密
    FERNET = "fernet"  # Fernet 对称加密
    HASH = "hash"  # 哈希（不可逆）
    MASK = "mask"  # 掩码（部分隐藏）


class AuditAction(Enum):
    """审计动作"""

    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    ENCRYPT = "encrypt"
    DECRYPT = "decrypt"
    ANONYMIZE = "anonymize"
    FORGET = "forget"


# ────── Data Models ──────


# 敏感信息规则的形状就是共享那一份 `SensitiveRule`（本文件顶部以 `SensitivePattern` 之名再导出）。
# 这里原先另有一个同名 `@dataclass`——它把上面那个 import 盖掉了（守卫
# `test_packageInitBindsNoUnusedGenericNames` 抓的正是这一形：import 从未生效），
# 于是 `import_patterns()` 造出来的是**另一种**形状：字段叫 `sensitivity`、没有 `maskText()`，
# 交给共享引擎用就会 `AttributeError`。收口不留第二种形状。




@dataclass
class SecurityConfig:
    """安全配置"""

    default_encryption: EncryptionMethod = EncryptionMethod.FERNET
    auto_detect_sensitive: bool = True
    anonymize_on_export: bool = False
    retention_days: int = 365
    max_access_logs: int = 10000
    encryption_key: Optional[str] = None
    salt: Optional[str] = None


@dataclass
class AccessLog:
    """访问日志"""

    timestamp: datetime.datetime
    memory_id: str
    action: AuditAction
    user_id: str = ""
    ip_address: str = ""
    details: str = ""
    success: bool = True


@dataclass
class SecurityAuditResult:
    """安全审计结果"""

    memory_id: str
    sensitivity_level: SensitivityLevel
    has_sensitive_data: bool
    detected_patterns: List[str]
    recommendations: List[str]
    timestamp: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))


# ────── 内置敏感模式 ──────



# ────── 加密工具 ──────


class _FernetCipher:
    """Fernet 加密器"""

    def __init__(self, key: Optional[str] = None):
        if not HAS_CRYPTOGRAPHY:
            raise ImportError("cryptography 库未安装")

        if key:
            # 使用提供的密钥
            self._key = key.encode() if isinstance(key, str) else key
        else:
            # 生成新密钥
            self._key = Fernet.generate_key()

        self._fernet = Fernet(self._key)

    def encrypt(self, data: str) -> str:
        """Fernet 加密——失败即抛出，不返回空串。

        返回空串等于落一条"加密成功的空记忆"：写侧看不出坏，读侧再也取不回来。
        """
        if not data:
            return ""

        return self._fernet.encrypt(data.encode("utf-8")).decode("ascii")

    def decrypt(self, encrypted_data: str) -> str:
        """Fernet 解密——失败点名，不把"解不开"改写成"这条记忆没内容"。"""
        if not encrypted_data:
            return ""

        try:
            return self._fernet.decrypt(encrypted_data.encode("ascii")).decode("utf-8")
        except Exception as exc:
            raise ValueError(f"Fernet 解密失败（令牌或密钥不匹配）: {exc}") from exc


# ────── 主类 ──────


class MemorySecurity:
    """
    记忆安全与隐私管理器

    功能：
    1. 敏感信息检测（手机号、身份证、邮箱等）
    2. 加密存储（Fernet对称加密）
    3. 匿名化处理（替换敏感信息）
    4. 被遗忘权（安全删除）
    5. 访问日志审计
    """

    def __init__(
        self,
        config: Optional[SecurityConfig] = None,
        memory_manager: Optional[Any] = None,
    ):
        self._config = config or SecurityConfig()
        # 内置规则就是共享表本身（§6-411 批 O-5）——这里不再留 `_BUILTIN_PATTERNS`
        # 这个名字：收口前它是本模块自带的一张 8 条小抄（`bank_card` 与 `credit_card`
        # 还是同一条正则登记两次），留名就等于留第二张表的入口。
        self._patterns: List[SensitivePattern] = list(SENSITIVE_RULES)
        self._access_logs: List[AccessLog] = []
        self._lock = threading.RLock()
        # BUG AUDIT M-02: 被遗忘权需要真实的删除后端。此前 forget_memory()
        # 是空实现却返回 success=True，合规删除流程被静默欺骗。
        self._memory_manager = memory_manager

        # 初始化加密器
        self._cipher = self._init_cipher()

        # 名称→正则的缓存（按名字增删模式时用）。这 4 行必须留在 `__init__`：批 O-5 删本地
        # 数据类时曾把它们错接进 `set_memory_manager()`，于是没设记忆管理器的实例调
        # `import_patterns()` 直接 AttributeError（现场复算抓到，随本批归位）。
        self._compiled_patterns: Dict[str, Pattern] = {}
        for pattern in self._patterns:
            self._compiled_patterns[pattern.name] = pattern.pattern

    def set_memory_manager(self, memory_manager: Any) -> None:
        """延迟注入记忆管理器（被遗忘权的真实删除后端）"""
        with self._lock:
            self._memory_manager = memory_manager

    def _init_cipher(self):
        """初始化加密器"""
        method = self._config.default_encryption

        if method == EncryptionMethod.FERNET:
            if not HAS_CRYPTOGRAPHY:
                # 与 `llm/providers/secret_store.py` 同口径：依赖缺失就点名拒绝，
                # 不换新一把弱钥匙继续写"看起来加密了"的内容。
                raise RuntimeError(
                    "cryptography 库未安装，无法初始化记忆加密 "
                    "(EncryptionMethod.FERNET) — run: pip install cryptography"
                )
            # BUG AUDIT M-12: 未配置密钥时不再每次随机生成（重启后旧密文无法解密
            # → 记忆"消失"），改从持久化文件读取稳定密钥。
            key = self._config.encryption_key or _load_or_create_encryption_key()
            return _FernetCipher(key)
        elif method == EncryptionMethod.HASH:
            # 哈希不需要加密器
            return None
        elif method == EncryptionMethod.MASK:
            # 掩码不需要加密器
            return None
        else:
            return None

    def _log_access(
        self,
        memory_id: str,
        action: AuditAction,
        user_id: str = "",
        ip_address: str = "",
        details: str = "",
        success: bool = True,
    ):
        """记录访问日志"""
        with self._lock:
            log = AccessLog(
                timestamp=datetime.datetime.now(datetime.timezone.utc),
                memory_id=memory_id,
                action=action,
                user_id=user_id,
                ip_address=ip_address,
                details=details,
                success=success,
            )

            self._access_logs.append(log)

            # 限制日志数量
            if len(self._access_logs) > self._config.max_access_logs:
                # 保留最近的日志
                self._access_logs = self._access_logs[-self._config.max_access_logs :]

    def add_custom_pattern(self, pattern: SensitivePattern):
        """添加自定义敏感模式"""
        with self._lock:
            self._patterns.append(pattern)
            self._compiled_patterns[pattern.name] = pattern.pattern

    def remove_pattern(self, pattern_name: str) -> bool:
        """移除敏感模式"""
        with self._lock:
            for i, pattern in enumerate(self._patterns):
                if pattern.name == pattern_name:
                    self._patterns.pop(i)
                    self._compiled_patterns.pop(pattern_name, None)
                    return True
            return False

    def detect_sensitive_info(self, content: str) -> List[Dict[str, Any]]:
        """
        检测敏感信息

        返回:
            List[Dict]: 检测到的敏感信息列表
        """
        if not content:
            return []

        with self._lock:
            hits = detectSensitive(content, rules=self._patterns)

        grouped: Dict[str, Dict[str, Any]] = {}
        for hit in hits:
            entry = grouped.setdefault(hit.rule.name, {
                "pattern_name": hit.rule.name,
                "description": hit.rule.description,
                "sensitivity": hit.rule.severity.value,
                "count": 0,
                "samples": [],
            })
            entry["count"] += 1
            if len(entry["samples"]) < 3:
                # 样本给的是**打码后**的形状：检测面把原文抄进报告，等于换一个出口再泄露一次
                entry["samples"].append(hit.evidence)
        return list(grouped.values())

    def get_sensitivity_level(self, content: str) -> SensitivityLevel:
        """获取内容的敏感度级别"""
        with self._lock:
            top = highestSeverity(detectSensitive(content, rules=self._patterns))
        # 没命中才落 LOW；序由共享尺度给（本函数原先是 `max(levels, key=lambda x: x.value)`——
        # 按字符串比大小，"medium" 会赢过 "critical"，"最高敏感度"其实是个错读数）
        return top or SensitivityLevel.LOW

    def encrypt_sensitive_content(self, content: str, method: Optional[EncryptionMethod] = None) -> Tuple[str, str]:
        """
        加密敏感内容

        参数:
            content: 原始内容
            method: 加密方法（可选）

        返回:
            Tuple[str, str]: (加密后的内容, 使用的加密方法)
        """
        if not content:
            return ("", EncryptionMethod.NONE.value)

        use_method = method or self._config.default_encryption

        if use_method == EncryptionMethod.NONE:
            return (content, EncryptionMethod.NONE.value)

        if use_method == EncryptionMethod.HASH:
            # 哈希加密
            hashed = hashlib.sha256(content.encode("utf-8")).hexdigest()
            return (hashed, EncryptionMethod.HASH.value)

        if use_method == EncryptionMethod.MASK:
            # 掩码处理
            masked = self._mask_content(content)
            return (masked, EncryptionMethod.MASK.value)

        # Fernet 加密（失败即抛出，见 _FernetCipher）
        if self._cipher:
            encrypted = self._cipher.encrypt(content)
            return (encrypted, use_method.value)

        # 无加密器，返回原内容
        logger.warning("无可用加密器")
        return (content, EncryptionMethod.NONE.value)

    def decrypt_sensitive_content(self, encrypted_content: str, method: str) -> str:
        """
        解密敏感内容

        参数:
            encrypted_content: 加密内容
            method: 加密方法

        返回:
            str: 解密后的内容
        """
        if not encrypted_content:
            return ""

        if method == EncryptionMethod.NONE.value:
            return encrypted_content

        if method == EncryptionMethod.HASH.value:
            # 哈希无法解密
            logger.warning("哈希加密无法解密")
            return encrypted_content

        if method == EncryptionMethod.MASK.value:
            # 掩码无法完全还原
            logger.warning("掩码处理无法完全还原")
            return encrypted_content

        # Fernet 解密（失败即点名，不再返回空串）
        if self._cipher:
            return self._cipher.decrypt(encrypted_content)

        logger.warning("无可用解密器")
        return encrypted_content

    def _mask_content(self, content: str) -> str:
        """掩码处理内容"""
        with self._lock:
            return sanitizeSensitive(content, rules=self._patterns)

    def anonymize_content(self, content: str, preserve_format: bool = True) -> str:
        """
        匿名化内容

        参数:
            content: 原始内容
            preserve_format: 是否保留格式（如长度）

        返回:
            str: 匿名化后的内容
        """
        if not content:
            return ""

        with self._lock:
            if preserve_format:
                # 保留长度的匿名化那一档语义也收进同一个引擎（形状不同，实现不再分家）
                return maskPreservingFormat(content, rules=self._patterns)
            return sanitizeSensitive(content, rules=self._patterns)

    def forget_memory(self, memory_id: str, permanent: bool = False) -> Dict[str, Any]:
        """
        被遗忘权处理

        参数:
            memory_id: 记忆ID
            permanent: 是否永久删除

        返回:
            Dict: 处理结果
        """
        result = {
            "memory_id": memory_id,
            "action": "forget",
            "permanent": permanent,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "success": False,
        }

        manager = self._memory_manager
        if manager is None or not hasattr(manager, "forget"):
            # 没有删除后端时必须显式失败。禁止像此前那样"一行没删却返回
            # success=True"——那会让合规/删除流程静默误判成功。
            result["error"] = (
                "未注入可用的 memory_manager（需提供 forget(memory_id, soft) 接口），"
                "无法执行被遗忘权删除"
            )
            logger.error("被遗忘权执行失败: %s", result["error"])
            self._log_access(
                memory_id=memory_id,
                action=AuditAction.FORGET,
                details=f"失败：未注入 memory_manager（永久删除: {permanent}）",
            )
            return result

        try:
            # soft=True 为软删除（保留审计痕迹），permanent=True 走物理删除
            deleted = manager.forget(memory_id, soft=not permanent)

            result["success"] = bool(deleted)
            result["deleted"] = bool(deleted)
            result["message"] = "记忆已删除" if deleted else "记忆不存在或删除失败"

            self._log_access(
                memory_id=memory_id,
                action=AuditAction.FORGET,
                details=f"{'永久' if permanent else '软'}删除: {permanent}｜结果: {deleted}",
            )
        except Exception as e:
            result["error"] = str(e)
            logger.error("遗忘记忆失败: %s", e)

        return result

    def get_access_log(
        self, memory_id: Optional[str] = None, action: Optional[AuditAction] = None, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        获取访问日志

        参数:
            memory_id: 过滤记忆ID
            action: 过滤动作类型
            limit: 返回数量限制

        返回:
            List[Dict]: 访问日志列表
        """
        with self._lock:
            logs = self._access_logs.copy()

        # 过滤
        if memory_id:
            logs = [log for log in logs if log.memory_id == memory_id]

        if action:
            logs = [log for log in logs if log.action == action]

        # 排序（最新的在前）
        logs.sort(key=lambda x: x.timestamp, reverse=True)

        # 限制数量
        logs = logs[:limit]

        # 转换为字典
        return [
            {
                "timestamp": log.timestamp.isoformat(),
                "memory_id": log.memory_id,
                "action": log.action.value,
                "user_id": log.user_id,
                "ip_address": log.ip_address,
                "details": log.details,
                "success": log.success,
            }
            for log in logs
        ]

    def audit_memories(self, memories: List[Memory]) -> List[SecurityAuditResult]:
        """
        审计记忆列表

        参数:
            memories: 记忆列表

        返回:
            List[SecurityAuditResult]: 审计结果列表
        """
        results = []

        for memory in memories:
            # 检测敏感信息
            detections = self.detect_sensitive_info(memory.content)

            # 确定敏感度级别
            sensitivity = self.get_sensitivity_level(memory.content)

            # 生成建议
            recommendations = self._generate_recommendations(memory, detections, sensitivity)

            result = SecurityAuditResult(
                memory_id=memory.id,
                sensitivity_level=sensitivity,
                has_sensitive_data=len(detections) > 0,
                detected_patterns=[d["pattern_name"] for d in detections],
                recommendations=recommendations,
            )

            results.append(result)

        return results

    def _generate_recommendations(
        self, memory: Memory, detections: List[Dict[str, Any]], sensitivity: SensitivityLevel
    ) -> List[str]:
        """生成安全建议"""
        recommendations = []

        if not detections:
            recommendations.append("内容安全，无需特殊处理")
            return recommendations

        # 根据敏感度级别给出建议
        if sensitivity == SensitivityLevel.CRITICAL:
            recommendations.append("检测到关键敏感信息，建议加密存储")
            recommendations.append("考虑匿名化处理后分享")

            # 检查具体内容
            pattern_names = [d["pattern_name"] for d in detections]

            if "chinese_id" in pattern_names:
                recommendations.append("包含身份证号码，符合个人信息保护法要求")

            if "bank_card" in pattern_names or "credit_card" in pattern_names:
                recommendations.append("包含金融信息，需要额外安全措施")

            if "password_pattern" in pattern_names or "api_key" in pattern_names:
                recommendations.append("包含凭据信息，建议立即轮换")

        elif sensitivity == SensitivityLevel.HIGH:
            recommendations.append("检测到高敏感信息，建议加密存储")
            recommendations.append("分享前考虑匿名化处理")

        elif sensitivity == SensitivityLevel.MEDIUM:
            recommendations.append("检测到中敏感信息，注意访问控制")

        # 通用建议
        if memory.access_count > 100:
            recommendations.append("高频访问记忆，考虑缓存加密")

        return recommendations

    def _get_severity(self, sensitivity: SensitivityLevel) -> str:
        """获取严重程度描述"""
        severity_map = {
            SensitivityLevel.LOW: "低",
            SensitivityLevel.MEDIUM: "中",
            SensitivityLevel.HIGH: "高",
            SensitivityLevel.CRITICAL: "严重",
        }
        return severity_map.get(sensitivity, "未知")

    def get_statistics(self) -> Dict[str, Any]:
        """获取安全统计信息"""
        with self._lock:
            total_patterns = len(self._patterns)
            enabled_patterns = sum(1 for p in self._patterns if p.enabled)

            total_logs = len(self._access_logs)

            # 按动作统计
            action_stats = {}
            for log in self._access_logs:
                action = log.action.value
                action_stats[action] = action_stats.get(action, 0) + 1

            # 按敏感度统计模式
            sensitivity_stats = {}
            for pattern in self._patterns:
                level = pattern.severity.value
                sensitivity_stats[level] = sensitivity_stats.get(level, 0) + 1

            return {
                "patterns": {"total": total_patterns, "enabled": enabled_patterns, "by_sensitivity": sensitivity_stats},
                "access_logs": {"total": total_logs, "by_action": action_stats},
                "encryption": {"method": self._config.default_encryption.value, "has_cipher": self._cipher is not None},
            }

    def export_patterns(self) -> List[Dict[str, Any]]:
        """导出模式配置"""
        with self._lock:
            return [
                {
                    "name": p.name,
                    "pattern": p.pattern.pattern,
                    "sensitivity": p.severity.value,        # 外部配置键名不变（既有契约）
                    "description": p.description,
                    "enabled": p.enabled,
                    # 自定义 replacement 与内置的打码形状都无损带出去：
                    # 只发 `replacement` 会把内置规则的"留首3末4"这种形状降级成整段替换。
                    "replacement": p.literalReplacement,
                    "maskStrategy": p.maskStrategy,
                    "keepLeading": p.keepLeading,
                    "keepTrailing": p.keepTrailing,
                }
                for p in self._patterns
            ]

    def import_patterns(self, patterns_config: List[Dict[str, Any]]):
        """导入模式配置"""
        with self._lock:
            for config in patterns_config:
                try:
                    # 形状只有一份：这里造的必须是共享 `SensitiveRule`（`SensitivePattern`
                    # 现在是它的别名）。`replacement` 给了就走字面替换，没给就用
                    # `maskStrategy` 那三种形状之一——两边都不许被静默忽略。
                    pattern = SensitivePattern(
                        name=config["name"],
                        pattern=re.compile(config["pattern"]),
                        severity=SensitivityLevel(config["sensitivity"]),
                        description=config.get("description", ""),
                        maskStrategy=config.get("maskStrategy", "whole"),
                        keepLeading=int(config.get("keepLeading") or 0),
                        keepTrailing=int(config.get("keepTrailing") or 0),
                        literalReplacement=config.get("replacement"),
                        enabled=config.get("enabled", True),
                    )
                    self._patterns.append(pattern)
                    self._compiled_patterns[pattern.name] = pattern.pattern
                except Exception as e:
                    logger.error("导入模式失败: %s", e)


# ────── 单例管理 ──────

_security_instance: Optional[MemorySecurity] = None
_instance_lock = threading.Lock()


def get_memory_security(config: Optional[SecurityConfig] = None) -> MemorySecurity:
    """获取记忆安全实例（单例）"""
    global _security_instance

    if _security_instance is None:
        with _instance_lock:
            if _security_instance is None:
                _security_instance = MemorySecurity(config)

    return _security_instance


def reset_memory_security():
    """重置记忆安全实例"""
    global _security_instance

    with _instance_lock:
        _security_instance = None
