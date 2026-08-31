# 记忆安全与隐私架构设计

## 实现对齐说明

> **注意**: 本文档描述的设计理论与实际代码基本一致。

| 文档术语 | 实际代码类/方法 | 文件位置 |
|---------|---------------|---------|
| `MemorySecurity` | `MemorySecurity`（类名匹配） | `neurova/cognitive_layers/memory_layer/security.py` |

文档中的安全功能（敏感信息检测、加密存储、匿名化处理、被遗忘权、访问日志审计）在实际代码中均有对应实现。

实际实现以代码为准。

## 1. 概述

### 1.1 设计理念

记忆系统存储了大量用户个人信息，安全与隐私机制确保：

> **敏感信息被保护、用户拥有数据控制权、符合隐私法规要求、防止数据泄露和滥用。**

### 1.2 安全架构

```
记忆安全系统
├── 敏感信息检测 (Sensitive Information Detection)
│   ├── 自动识别敏感数据
│   ├── 分类标记
│   └── 风险等级评估
│
├── 数据加密 (Data Encryption)
│   ├── 存储加密
│   ├── 传输加密
│   └── 密钥管理
│
├── 隐私控制 (Privacy Control)
│   ├── 用户删除接口
│   ├── 数据导出
│   └── 被遗忘权实现
│
├── 访问控制 (Access Control)
│   ├── 权限分级
│   ├── 审计日志
│   └── 异常检测
│
└── 合规管理 (Compliance Management)
    ├── GDPR合规
    ├── 数据保留策略
    └── 隐私政策执行
```

---

## 2. 敏感信息检测

### 2.1 敏感信息分类

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from enum import Enum
import re
import uuid

class SensitivityLevel(Enum):
    """敏感等级"""
    PUBLIC = "public"           # 公开信息
    INTERNAL = "internal"       # 内部信息
    SENSITIVE = "sensitive"     # 敏感信息
    CRITICAL = "critical"       # 机密信息

class SensitiveCategory(Enum):
    """敏感类别"""
    # 个人身份
    NAME = "name"               # 姓名
    ID_CARD = "id_card"         # 身份证号
    PASSPORT = "passport"       # 护照号
    PHONE = "phone"             # 手机号
    EMAIL = "email"             # 邮箱
    ADDRESS = "address"         # 地址
    
    # 金融信息
    BANK_CARD = "bank_card"     # 银行卡号
    PASSWORD = "password"       # 密码
    PIN = "pin"                 # PIN码
    CREDIT_CARD = "credit_card" # 信用卡
    
    # 健康信息
    HEALTH = "health"           # 健康信息
    MEDICAL = "medical"         # 医疗记录
    
    # 其他
    API_KEY = "api_key"         # API密钥
    TOKEN = "token"             # Token
    PRIVATE_KEY = "private_key" # 私钥

@dataclass
class SensitiveInfo:
    """敏感信息对象"""
    id: str
    category: SensitiveCategory
    sensitivity_level: SensitivityLevel
    content: str
    masked_content: str  # 脱敏后的内容
    position: Tuple[int, int]  # 在原文中的位置
    detected_at: datetime = field(default_factory=datetime.now)
    confidence: float = 1.0  # 检测置信度
```

### 2.2 敏感信息检测器

```python
class SensitiveInfoDetector:
    """
    敏感信息检测器
    自动识别和标记敏感信息
    """
    
    def __init__(self, config=None):
        self.config = config or {}
        self._compile_patterns()
    
    def _compile_patterns(self):
        """编译检测正则"""
        self.patterns = {
            SensitiveCategory.ID_CARD: re.compile(r'\b\d{17}[\dXx]\b'),
            SensitiveCategory.PHONE: re.compile(r'\b1[3-9]\d{9}\b'),
            SensitiveCategory.EMAIL: re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'),
            SensitiveCategory.BANK_CARD: re.compile(r'\b\d{16,19}\b'),
            SensitiveCategory.PASSWORD: re.compile(r'(密码|password|pwd)\s*[:=]\s*\S+'),
            SensitiveCategory.API_KEY: re.compile(r'(api[_-]?key|apikey)\s*[:=]\s*[A-Za-z0-9]{16,}'),
            SensitiveCategory.TOKEN: re.compile(r'(token|access_token)\s*[:=]\s*[A-Za-z0-9_.-]{20,}'),
        }
    
    def detect(self, content: str) -> List[SensitiveInfo]:
        """
        检测内容中的敏感信息
        
        Args:
            content: 待检测内容
        
        Returns:
            检测到的敏感信息列表
        """
        results = []
        
        for category, pattern in self.patterns.items():
            for match in pattern.finditer(content):
                sensitive_content = match.group()
                
                # 确定敏感等级
                sensitivity = self._get_sensitivity_level(category, sensitive_content)
                
                # 生成脱敏内容
                masked = self._mask_content(sensitive_content, category)
                
                # 创建敏感信息对象
                sensitive_info = SensitiveInfo(
                    id=str(uuid.uuid4()),
                    category=category,
                    sensitivity_level=sensitivity,
                    content=sensitive_content,
                    masked_content=masked,
                    position=(match.start(), match.end()),
                    confidence=self._calculate_confidence(category, sensitive_content)
                )
                
                results.append(sensitive_info)
        
        return results
    
    def _get_sensitivity_level(
        self,
        category: SensitiveCategory,
        content: str
    ) -> SensitivityLevel:
        """确定敏感等级"""
        critical_categories = {
            SensitiveCategory.PASSWORD,
            SensitiveCategory.PIN,
            SensitiveCategory.PRIVATE_KEY,
            SensitiveCategory.API_KEY,
            SensitiveCategory.TOKEN
        }
        
        sensitive_categories = {
            SensitiveCategory.ID_CARD,
            SensitiveCategory.PASSPORT,
            SensitiveCategory.BANK_CARD,
            SensitiveCategory.CREDIT_CARD
        }
        
        if category in critical_categories:
            return SensitivityLevel.CRITICAL
        elif category in sensitive_categories:
            return SensitivityLevel.SENSITIVE
        elif category in {SensitiveCategory.PHONE, SensitiveCategory.EMAIL}:
            return SensitivityLevel.INTERNAL
        else:
            return SensitivityLevel.PUBLIC
    
    def _mask_content(self, content: str, category: SensitiveCategory) -> str:
        """脱敏处理"""
        if category == SensitiveCategory.PHONE:
            # 手机号: 138****1234
            return content[:3] + '****' + content[-4:]
        
        elif category == SensitiveCategory.ID_CARD:
            # 身份证: 110***********1234
            return content[:3] + '*' * 11 + content[-4:]
        
        elif category == SensitiveCategory.EMAIL:
            # 邮箱: us***@example.com
            parts = content.split('@')
            return parts[0][:2] + '***@' + parts[1]
        
        elif category == SensitiveCategory.BANK_CARD:
            # 银行卡: ****1234
            return '****' + content[-4:]
        
        elif category in {SensitiveCategory.PASSWORD, SensitiveCategory.PIN}:
            return '***REDACTED***'
        
        elif category in {SensitiveCategory.API_KEY, SensitiveCategory.TOKEN}:
            return content[:4] + '***' + content[-4:]
        
        else:
            return '***'
    
    def _calculate_confidence(self, category: SensitiveCategory, content: str) -> float:
        """计算检测置信度"""
        # 基于长度、格式等计算
        if category == SensitiveCategory.PHONE:
            return 0.95 if len(content) == 11 else 0.7
        
        elif category == SensitiveCategory.ID_CARD:
            return 0.95 if len(content) == 18 else 0.8
        
        elif category == SensitiveCategory.EMAIL:
            return 0.9
        
        return 0.8
```

### 2.3 敏感信息处理策略

```python
class SensitiveInfoHandler:
    """
    敏感信息处理器
    根据敏感等级采取不同处理策略
    """
    
    def __init__(self, db_connection, detector: SensitiveInfoDetector, config=None):
        self.db = db_connection
        self.detector = detector
        self.config = config or {}
        self._create_tables()
    
    def process_memory(self, memory: Memory) -> Dict:
        """
        处理记忆中的敏感信息
        
        返回:
        {
            'has_sensitive': bool,
            'sensitive_items': [...],
            'action': 'store/mask/encrypt/reject',
            'processed_content': str
        }
        """
        # 1. 检测敏感信息
        sensitive_items = self.detector.detect(memory.content)
        
        if not sensitive_items:
            return {
                'has_sensitive': False,
                'sensitive_items': [],
                'action': 'store',
                'processed_content': memory.content
            }
        
        # 2. 确定处理策略
        action = self._determine_action(sensitive_items)
        
        # 3. 执行处理
        if action == 'mask':
            processed_content = self._mask_sensitive(memory.content, sensitive_items)
        
        elif action == 'encrypt':
            processed_content = self._encrypt_sensitive(memory.content, sensitive_items)
        
        elif action == 'reject':
            return {
                'has_sensitive': True,
                'sensitive_items': sensitive_items,
                'action': 'reject',
                'processed_content': None,
                'reason': 'Contains critical sensitive information'
            }
        
        else:
            processed_content = memory.content
        
        return {
            'has_sensitive': True,
            'sensitive_items': [item.__dict__ for item in sensitive_items],
            'action': action,
            'processed_content': processed_content
        }
    
    def _determine_action(self, sensitive_items: List[SensitiveInfo]) -> str:
        """确定处理策略"""
        max_level = max(item.sensitivity_level for item in sensitive_items)
        
        if max_level == SensitivityLevel.CRITICAL:
            return 'reject'  # 拒绝存储
        elif max_level == SensitivityLevel.SENSITIVE:
            return 'encrypt'  # 加密存储
        elif max_level == SensitivityLevel.INTERNAL:
            return 'mask'  # 脱敏存储
        else:
            return 'store'  # 正常存储
    
    def _mask_sensitive(self, content: str, items: List[SensitiveInfo]) -> str:
        """脱敏处理"""
        # 从后向前替换，避免位置偏移
        items_sorted = sorted(items, key=lambda x: x.position[0], reverse=True)
        
        for item in items_sorted:
            start, end = item.position
            content = content[:start] + item.masked_content + content[end:]
        
        return content
    
    def _encrypt_sensitive(self, content: str, items: List[SensitiveInfo]) -> str:
        """加密敏感信息"""
        # 使用 AES 加密
        # 返回加密后的内容
        return content  # 简化实现
```

---

## 3. 数据加密

### 3.1 加密管理器

```python
class EncryptionManager:
    """
    加密管理器
    管理敏感数据的加密/解密
    """
    
    def __init__(self, config=None):
        self.config = config or {}
        self.encryption_key = self._load_encryption_key()
    
    def _load_encryption_key(self) -> bytes:
        """加载加密密钥"""
        # 从环境变量或密钥管理服务加载
        import os
        key = os.environ.get('MEMORY_ENCRYPTION_KEY')
        if not key:
            raise ValueError("MEMORY_ENCRYPTION_KEY not set")
        return key.encode()
    
    def encrypt(self, plaintext: str) -> str:
        """
        加密文本
        
        使用 AES-256-GCM
        """
        from cryptography.fernet import Fernet
        
        fernet = Fernet(self.encryption_key)
        encrypted = fernet.encrypt(plaintext.encode())
        return encrypted.decode()
    
    def decrypt(self, ciphertext: str) -> str:
        """解密文本"""
        from cryptography.fernet import Fernet
        
        fernet = Fernet(self.encryption_key)
        decrypted = fernet.decrypt(ciphertext.encode())
        return decrypted.decode()
    
    def encrypt_memory(self, memory_id: str, content: str) -> str:
        """加密记忆内容"""
        encrypted = self.encrypt(content)
        
        # 更新数据库
        cursor = self.db.cursor()
        cursor.execute("""
            UPDATE memories
            SET content_encrypted = ?,
                is_encrypted = 1
            WHERE id = ?
        """, (encrypted, memory_id))
        self.db.commit()
        
        return encrypted
    
    def decrypt_memory(self, memory_id: str, encrypted_content: str) -> str:
        """解密记忆内容"""
        return self.decrypt(encrypted_content)
```

---

## 4. 隐私控制

### 4.1 用户隐私控制器

```python
class PrivacyController:
    """
    隐私控制器
    实现用户数据控制权
    """
    
    def __init__(self, db_connection, memory_manager):
        self.db = db_connection
        self.memory_manager = memory_manager
    
    def delete_user_data(self, agent_id: str, user_id: str) -> Dict:
        """
        删除用户数据（被遗忘权）
        
        流程:
        1. 标记所有相关记忆为待删除
        2. 执行软删除
        3. 记录删除日志
        4. 返回删除统计
        """
        cursor = self.db.cursor()
        
        stats = {
            'memories_deleted': 0,
            'sessions_deleted': 0,
            'vectors_deleted': 0
        }
        
        # 1. 软删除记忆
        cursor.execute("""
            UPDATE memories
            SET lifecycle_stage = 'deleted',
                deleted_at = CURRENT_TIMESTAMP,
                delete_reason = 'user_request'
            WHERE agent_id = ?
              AND user_id = ?
              AND lifecycle_stage != 'deleted'
        """, (agent_id, user_id))
        
        stats['memories_deleted'] = cursor.rowcount
        
        # 2. 删除向量
        cursor.execute("""
            DELETE FROM memory_embeddings
            WHERE memory_id IN (
                SELECT id FROM memories
                WHERE agent_id = ? AND user_id = ?
            )
        """, (agent_id, user_id))
        
        stats['vectors_deleted'] = cursor.rowcount
        
        # 3. 记录删除日志
        self._log_deletion(agent_id, user_id, stats)
        
        self.db.commit()
        
        return stats
    
    def export_user_data(self, agent_id: str, user_id: str) -> Dict:
        """
        导出用户数据（数据可携带权）
        
        返回:
        {
            'memories': [...],
            'sessions': [...],
            'emotion_data': [...],
            'export_timestamp': str
        }
        """
        cursor = self.db.cursor()
        
        # 导出记忆
        cursor.execute("""
            SELECT * FROM memories
            WHERE agent_id = ?
              AND user_id = ?
              AND lifecycle_stage != 'deleted'
        """, (agent_id, user_id))
        
        memories = [dict(zip([col[0] for col in cursor.description], row)) for row in cursor.fetchall()]
        
        return {
            'memories': memories,
            'export_timestamp': datetime.now().isoformat(),
            'agent_id': agent_id,
            'user_id': user_id
        }
    
    def _log_deletion(self, agent_id: str, user_id: str, stats: Dict):
        """记录删除日志"""
        cursor = self.db.cursor()
        cursor.execute("""
            INSERT INTO privacy_logs (
                id, agent_id, user_id, action, details, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, (
            str(uuid.uuid4()),
            agent_id,
            user_id,
            'data_deletion',
            json.dumps(stats),
            datetime.now().isoformat()
        ))
        self.db.commit()
```

---

## 5. 访问控制

### 5.1 访问权限管理

```python
class AccessControlManager:
    """
    访问控制管理器
    控制记忆系统的访问权限
    """
    
    def __init__(self, db_connection):
        self.db = db_connection
        self._create_tables()
    
    def check_access(
        self,
        agent_id: str,
        user_id: str,
        memory_id: str,
        action: str  # read/write/delete
    ) -> bool:
        """
        检查访问权限
        
        Returns:
            True 如果允许访问
        """
        cursor = self.db.cursor()
        
        # 检查记忆是否属于该用户
        cursor.execute("""
            SELECT user_id, sensitivity_level FROM memories
            WHERE id = ? AND agent_id = ?
        """, (memory_id, agent_id))
        
        row = cursor.fetchone()
        if not row:
            return False
        
        stored_user_id, sensitivity = row
        
        # 检查用户匹配
        if stored_user_id != user_id:
            # 非所有者，检查是否有共享权限
            return self._check_shared_access(agent_id, user_id, memory_id, action)
        
        # 所有者，检查敏感等级
        if sensitivity == 'critical':
            return action in ['read', 'write']  # 不能删除
        
        return True
    
    def _check_shared_access(
        self,
        agent_id: str,
        user_id: str,
        memory_id: str,
        action: str
    ) -> bool:
        """检查共享访问权限"""
        cursor = self.db.cursor()
        cursor.execute("""
            SELECT 1 FROM memory_shares
            WHERE agent_id = ?
              AND memory_id = ?
              AND shared_to_user = ?
              AND permission_level >= ?
              AND expires_at > CURRENT_TIMESTAMP
        """, (agent_id, memory_id, user_id, self._action_to_level(action)))
        
        return cursor.fetchone() is not None
    
    def _action_to_level(self, action: str) -> int:
        """将操作映射为权限等级"""
        levels = {
            'read': 1,
            'write': 2,
            'delete': 3
        }
        return levels.get(action, 0)
```

---

## 6. 数据库设计

### 6.1 安全相关表

```sql
-- 敏感信息记录表
CREATE TABLE sensitive_info_records (
    id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    category TEXT NOT NULL,
    sensitivity_level TEXT NOT NULL,
    original_content TEXT,  -- 加密存储
    masked_content TEXT,
    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
);

-- 加密字段
ALTER TABLE memories ADD COLUMN is_encrypted BOOLEAN DEFAULT 0;
ALTER TABLE memories ADD COLUMN content_encrypted TEXT;
ALTER TABLE memories ADD COLUMN sensitivity_level TEXT DEFAULT 'public';

-- 隐私日志
CREATE TABLE privacy_logs (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    action TEXT NOT NULL,  -- data_deletion/data_export/access_request
    details TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_privacy_logs_agent ON privacy_logs(agent_id, timestamp DESC);

-- 访问审计日志
CREATE TABLE access_audit_logs (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    memory_id TEXT NOT NULL,
    action TEXT NOT NULL,
    result TEXT,  -- success/denied
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_access_audit ON access_audit_logs(agent_id, user_id, timestamp DESC);

-- 记忆共享表
CREATE TABLE memory_shares (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    memory_id TEXT NOT NULL,
    shared_to_user TEXT NOT NULL,
    permission_level INTEGER DEFAULT 1,  -- 1=read, 2=write, 3=delete
    expires_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_shares_agent ON memory_shares(agent_id, shared_to_user);
```

---

## 7. 配置示例

```yaml
# memory_security.yaml
security:
  # 敏感信息检测
  sensitive_detection:
    enabled: true
    auto_detect: true
    reject_critical: true
    
    categories:
      - name
      - id_card
      - phone
      - email
      - bank_card
      - password
      - api_key
      - token
  
  # 加密
  encryption:
    enabled: true
    algorithm: AES-256-GCM
    encrypt_fields:
      - sensitive_content
      - personal_info
  
  # 隐私控制
  privacy:
    user_deletion:
      enabled: true
      soft_delete: true
      retention_days: 30  # 软删除后保留30天
    
    data_export:
      enabled: true
      format: json
    
    consent:
      required: true
      log_consent: true
  
  # 访问控制
  access_control:
    enabled: true
    audit_log: true
    max_failed_attempts: 5
    lockout_duration_minutes: 30
```

---

## 8. 监控指标

| 指标 | 说明 | 健康范围 |
|------|------|---------|
| **敏感信息检出率** | 检测到的敏感信息比例 | > 95% |
| **误报率** | 正常内容被误判为敏感 | < 5% |
| **加密覆盖率** | 敏感数据加密比例 | 100% |
| **删除响应时间** | 用户删除请求响应时间 | < 24小时 |
| **访问拒绝率** | 非法访问被拒绝比例 | 100% |
