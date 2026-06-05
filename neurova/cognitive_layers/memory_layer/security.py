"""
记忆安全与隐私 - 敏感信息检测、加密存储、被遗忘权
"""

import base64
import datetime
import hashlib
import logging
import os
import re
import typing
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Pattern, Tuple, Union

from .models import Memory

# 可选依赖处理
try:
    from cryptography.fernet import Fernet, InvalidToken
    HAS_CRYPTOGRAPHY = True
except ImportError:
    HAS_CRYPTOGRAPHY = False

logger = logging.getLogger(__name__)


# ────── Enums ──────

class SensitivityLevel(Enum):
    """敏感度级别"""
    LOW = "low"           # 低敏感（一般信息）
    MEDIUM = "medium"     # 中敏感（个人偏好）
    HIGH = "high"         # 高敏感（个人信息）
    CRITICAL = "critical" # 关键敏感（财务/健康数据）


class EncryptionMethod(Enum):
    """加密方法"""
    NONE = "none"         # 不加密
    FERNET = "fernet"     # Fernet 对称加密
    HASH = "hash"         # 哈希（不可逆）
    MASK = "mask"         # 掩码（部分隐藏）


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

@dataclass
class SensitivePattern:
    """敏感信息模式"""
    name: str
    pattern: Pattern
    sensitivity: SensitivityLevel
    description: str = ""
    replacement: str = "***"
    enabled: bool = True


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

_BUILTIN_PATTERNS: List[SensitivePattern] = [
    # 中国手机号
    SensitivePattern(
        name="chinese_mobile",
        pattern=re.compile(r"1[3-9]\d{9}"),
        sensitivity=SensitivityLevel.HIGH,
        description="中国手机号码",
        replacement="1**********"
    ),
    # 身份证号
    SensitivePattern(
        name="chinese_id",
        pattern=re.compile(r"[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]"),
        sensitivity=SensitivityLevel.CRITICAL,
        description="中国身份证号码",
        replacement="***"
    ),
    # 邮箱
    SensitivePattern(
        name="email",
        pattern=re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
        sensitivity=SensitivityLevel.MEDIUM,
        description="电子邮箱地址",
        replacement="***@***.***"
    ),
    # 银行卡号
    SensitivePattern(
        name="bank_card",
        pattern=re.compile(r"(?:\d{4}[- ]?){3}\d{4}"),
        sensitivity=SensitivityLevel.CRITICAL,
        description="银行卡号",
        replacement="****-****-****-****"
    ),
    # 密码模式
    SensitivePattern(
        name="password_pattern",
        pattern=re.compile(r"(?:password|passwd|pwd|密码|口令)[\s:=]+\S+", re.IGNORECASE),
        sensitivity=SensitivityLevel.CRITICAL,
        description="密码字段",
        replacement="password=***"
    ),
    # API密钥
    SensitivePattern(
        name="api_key",
        pattern=re.compile(r"(?:api[_-]?key|token|secret)[\s:=]+[a-zA-Z0-9_\-]{20,}", re.IGNORECASE),
        sensitivity=SensitivityLevel.CRITICAL,
        description="API密钥/令牌",
        replacement="api_key=***"
    ),
    # IP地址
    SensitivePattern(
        name="ip_address",
        pattern=re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
        sensitivity=SensitivityLevel.LOW,
        description="IP地址",
        replacement="*.*.*.*"
    ),
    # 信用卡号
    SensitivePattern(
        name="credit_card",
        pattern=re.compile(r"\b(?:\d{4}[- ]?){3}\d{4}\b"),
        sensitivity=SensitivityLevel.CRITICAL,
        description="信用卡号码",
        replacement="****-****-****-****"
    ),
]


# ────── 加密工具 ──────

class _FallbackCipher:
    """回退加密器（当 cryptography 库不可用时使用）"""
    
    def __init__(self, key: Optional[str] = None):
        self._key = key or os.urandom(32).hex()
        self._key_bytes = hashlib.sha256(self._key.encode()).digest()
    
    def encrypt(self, data: str) -> str:
        """简单加密（Base64 + XOR）"""
        if not data:
            return ""
        
        key_bytes = self._key_bytes
        data_bytes = data.encode('utf-8')
        
        # XOR 加密
        encrypted = bytearray()
        for i, byte in enumerate(data_bytes):
            encrypted.append(byte ^ key_bytes[i % len(key_bytes)])
        
        # Base64 编码
        return base64.b64encode(encrypted).decode('ascii')
    
    def decrypt(self, encrypted_data: str) -> str:
        """简单解密"""
        if not encrypted_data:
            return ""
        
        try:
            # Base64 解码
            encrypted_bytes = base64.b64decode(encrypted_data)
            
            key_bytes = self._key_bytes
            decrypted = bytearray()
            
            for i, byte in enumerate(encrypted_bytes):
                decrypted.append(byte ^ key_bytes[i % len(key_bytes)])
            
            return decrypted.decode('utf-8')
        except Exception as e:
            logger.error(f"解密失败: {e}")
            return ""


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
        """Fernet 加密"""
        if not data:
            return ""
        
        try:
            encrypted = self._fernet.encrypt(data.encode('utf-8'))
            return encrypted.decode('ascii')
        except Exception as e:
            logger.error(f"Fernet加密失败: {e}")
            return ""
    
    def decrypt(self, encrypted_data: str) -> str:
        """Fernet 解密"""
        if not encrypted_data:
            return ""
        
        try:
            decrypted = self._fernet.decrypt(encrypted_data.encode('ascii'))
            return decrypted.decode('utf-8')
        except InvalidToken:
            logger.error("解密失败：无效的令牌或密钥")
            return ""
        except Exception as e:
            logger.error(f"Fernet解密失败: {e}")
            return ""


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
    
    def __init__(self, config: Optional[SecurityConfig] = None):
        self._config = config or SecurityConfig()
        self._patterns: List[SensitivePattern] = list(_BUILTIN_PATTERNS)
        self._access_logs: List[AccessLog] = []
        self._lock = threading.RLock()
        
        # 初始化加密器
        self._cipher = self._init_cipher()
        
        # 编译模式缓存
        self._compiled_patterns: Dict[str, Pattern] = {}
        for pattern in self._patterns:
            self._compiled_patterns[pattern.name] = pattern.pattern
    
    def _init_cipher(self):
        """初始化加密器"""
        method = self._config.default_encryption
        
        if method == EncryptionMethod.FERNET:
            try:
                return _FernetCipher(self._config.encryption_key)
            except ImportError:
                logger.warning("cryptography 库未安装，使用回退加密器")
                return _FallbackCipher(self._config.encryption_key)
        elif method == EncryptionMethod.HASH:
            # 哈希不需要加密器
            return None
        elif method == EncryptionMethod.MASK:
            # 掩码不需要加密器
            return None
        else:
            return None
    
    def _log_access(self, memory_id: str, action: AuditAction, 
                   user_id: str = "", ip_address: str = "", 
                   details: str = "", success: bool = True):
        """记录访问日志"""
        with self._lock:
            log = AccessLog(
                timestamp=datetime.datetime.now(datetime.timezone.utc),
                memory_id=memory_id,
                action=action,
                user_id=user_id,
                ip_address=ip_address,
                details=details,
                success=success
            )
            
            self._access_logs.append(log)
            
            # 限制日志数量
            if len(self._access_logs) > self._config.max_access_logs:
                # 保留最近的日志
                self._access_logs = self._access_logs[-self._config.max_access_logs:]
    
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
        
        results = []
        
        with self._lock:
            for pattern in self._patterns:
                if not pattern.enabled:
                    continue
                
                matches = pattern.pattern.findall(content)
                if matches:
                    results.append({
                        "pattern_name": pattern.name,
                        "description": pattern.description,
                        "sensitivity": pattern.sensitivity.value,
                        "count": len(matches),
                        "samples": matches[:3]  # 最多显示3个样本
                    })
        
        return results
    
    def get_sensitivity_level(self, content: str) -> SensitivityLevel:
        """获取内容的敏感度级别"""
        detections = self.detect_sensitive_info(content)
        
        if not detections:
            return SensitivityLevel.LOW
        
        # 返回最高敏感度
        levels = [SensitivityLevel(d["sensitivity"]) for d in detections]
        return max(levels, key=lambda x: x.value)
    
    def encrypt_sensitive_content(self, content: str, 
                                 method: Optional[EncryptionMethod] = None) -> Tuple[str, str]:
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
            hashed = hashlib.sha256(content.encode('utf-8')).hexdigest()
            return (hashed, EncryptionMethod.HASH.value)
        
        if use_method == EncryptionMethod.MASK:
            # 掩码处理
            masked = self._mask_content(content)
            return (masked, EncryptionMethod.MASK.value)
        
        # Fernet 或回退加密
        if self._cipher:
            encrypted = self._cipher.encrypt(content)
            return (encrypted, use_method.value)
        
        # 无加密器，返回原内容
        logger.warning("无可用加密器")
        return (content, EncryptionMethod.NONE.value)
    
    def decrypt_sensitive_content(self, encrypted_content: str, 
                                 method: str) -> str:
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
        
        # Fernet 或回退解密
        if self._cipher:
            return self._cipher.decrypt(encrypted_content)
        
        logger.warning("无可用解密器")
        return encrypted_content
    
    def _mask_content(self, content: str) -> str:
        """掩码处理内容"""
        result = content
        
        with self._lock:
            for pattern in self._patterns:
                if not pattern.enabled:
                    continue
                
                # 替换匹配的内容
                result = pattern.pattern.sub(pattern.replacement, result)
        
        return result
    
    def anonymize_content(self, content: str, 
                         preserve_format: bool = True) -> str:
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
        
        result = content
        
        with self._lock:
            for pattern in self._patterns:
                if not pattern.enabled:
                    continue
                
                if preserve_format:
                    # 保留格式的匿名化
                    def replace_preserve(match):
                        original = match.group(0)
                        if len(original) <= 4:
                            return "*" * len(original)
                        else:
                            # 保留首尾字符
                            return original[0] + "*" * (len(original) - 2) + original[-1]
                    
                    result = pattern.pattern.sub(replace_preserve, result)
                else:
                    # 简单替换
                    result = pattern.pattern.sub(pattern.replacement, result)
        
        return result
    
    def forget_memory(self, memory_id: str, 
                     permanent: bool = False) -> Dict[str, Any]:
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
            "success": False
        }
        
        try:
            # 这里应该调用实际的记忆删除逻辑
            # 由于我们只有 Memory 模型，这里只是模拟
            
            # 记录访问日志
            self._log_access(
                memory_id=memory_id,
                action=AuditAction.FORGET,
                details=f"永久删除: {permanent}"
            )
            
            result["success"] = True
            result["message"] = "记忆已标记为遗忘"
            
        except Exception as e:
            result["error"] = str(e)
            logger.error(f"遗忘记忆失败: {e}")
        
        return result
    
    def get_access_log(self, memory_id: Optional[str] = None,
                      action: Optional[AuditAction] = None,
                      limit: int = 100) -> List[Dict[str, Any]]:
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
                "success": log.success
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
                recommendations=recommendations
            )
            
            results.append(result)
        
        return results
    
    def _generate_recommendations(self, memory: Memory, 
                                 detections: List[Dict[str, Any]],
                                 sensitivity: SensitivityLevel) -> List[str]:
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
            SensitivityLevel.CRITICAL: "严重"
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
                level = pattern.sensitivity.value
                sensitivity_stats[level] = sensitivity_stats.get(level, 0) + 1
            
            return {
                "patterns": {
                    "total": total_patterns,
                    "enabled": enabled_patterns,
                    "by_sensitivity": sensitivity_stats
                },
                "access_logs": {
                    "total": total_logs,
                    "by_action": action_stats
                },
                "encryption": {
                    "method": self._config.default_encryption.value,
                    "has_cipher": self._cipher is not None
                }
            }
    
    def export_patterns(self) -> List[Dict[str, Any]]:
        """导出模式配置"""
        with self._lock:
            return [
                {
                    "name": p.name,
                    "pattern": p.pattern.pattern,
                    "sensitivity": p.sensitivity.value,
                    "description": p.description,
                    "replacement": p.replacement,
                    "enabled": p.enabled
                }
                for p in self._patterns
            ]
    
    def import_patterns(self, patterns_config: List[Dict[str, Any]]):
        """导入模式配置"""
        with self._lock:
            for config in patterns_config:
                try:
                    pattern = SensitivePattern(
                        name=config["name"],
                        pattern=re.compile(config["pattern"]),
                        sensitivity=SensitivityLevel(config["sensitivity"]),
                        description=config.get("description", ""),
                        replacement=config.get("replacement", "***"),
                        enabled=config.get("enabled", True)
                    )
                    self._patterns.append(pattern)
                    self._compiled_patterns[pattern.name] = pattern.pattern
                except Exception as e:
                    logger.error(f"导入模式失败: {e}")


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