# 系统设置功能 设计文档

> **模块ID**: Task4-SystemSettings  
> **创建时间**: 2026-05-12 22:01  
> **最后更新**: 2026-05-12 22:01  
> **负责人**: settings-dev  
> **状态**: ✅ 已完成

---

## 1. 模块概述

### 1.1 功能描述
完善 Neurova 的系统设置功能，包括：
1. **多语言支持**（11种语言）
2. **时区管理**
3. **多用户管理与数据隔离**
4. **设置 API 完善**

### 1.2 设计依据
- NEUROVA_CogArch_2.0.md 第5章
- 用户需求：系统国际化、多时区支持、多用户数据隔离

### 1.3 与其他模块的关系
- **依赖模块**: `neurova/language/`, `neurova/core/`, `neurova/api/`
- **被依赖模块**: Vue 前端组件

---

## 2. 架构设计

### 2.1 类/函数设计

#### 2.1.1 TimezoneManager 类
**文件路径**: `neurova/core/timezone_manager.py`

```python
class TimezoneManager:
    """
    时区管理器
    
    功能：
    1. 获取所有可用时区（使用 pytz）
    2. 时区信息查询（名称、偏移量、夏令时）
    3. 用户时区偏好管理
    4. 时间转换工具
    5. 与用户工作空间集成
    """
    
    def __init__(self, workspace_manager: UserWorkspaceManager):
        """
        初始化时区管理器
        
        Args:
            workspace_manager: 用户工作空间管理器
        """
    
    def get_all_timezones(self) -> List[Dict[str, Any]]:
        """
        获取所有可用时区
        
        Returns:
            List[Dict]: 时区信息列表，每个字典包含：
                - name: 时区名称（如 "Asia/Shanghai"）
                - region: 区域（如 "Asia"）
                - offset: UTC 偏移量（秒）
                - has_dst: 是否有夏令时
                - display_name: 显示名称（如 "Asia/Shanghai (UTC+08:00)"）
        """
    
    def get_timezone_info(self, timezone_name: str) -> Optional[Dict[str, Any]]:
        """
        获取时区详细信息
        
        Args:
            timezone_name: 时区名称
            
        Returns:
            Dict: 时区详细信息，或 None（时区不存在）
        """
    
    def get_user_timezone(self, user_id: str) -> str:
        """
        获取用户时区偏好
        
        Args:
            user_id: 用户ID
            
        Returns:
            str: 时区名称（如 "Asia/Shanghai"）
        """
    
    def set_user_timezone(self, user_id: str, timezone_name: str) -> bool:
        """
        设置用户时区偏好
        
        Args:
            user_id: 用户ID
            timezone_name: 时区名称
            
        Returns:
            bool: 是否设置成功
        """
    
    def get_local_time(self, user_id: str = None, timezone_name: str = None) -> Dict[str, Any]:
        """
        获取用户本地时间
        
        Args:
            user_id: 用户ID（优先使用）
            timezone_name: 时区名称（user_id 未提供时使用）
            
        Returns:
            Dict: 包含 local_time, timezone, utc_time 的字典
        """
```

#### 2.1.2 更新的 API 端点
**文件路径**: `neurova/api/settings.py`

| 接口路径 | 方法 | 说明 | 请求参数 | 返回格式 |
|---------|------|------|---------|----------|
| `/api/settings/timezones` | GET | 获取所有时区 | 无 | `{success: bool, data: List[Dict]}` |
| `/api/settings/user/timezone` | GET | 获取用户时区 | 无 | `{success: bool, data: {timezone: str}}` |
| `/api/settings/user/timezone` | PUT | 设置用户时区 | `{timezone: str}` | `{success: bool}` |
| `/api/settings/user/time` | GET | 获取用户本地时间 | 无 | `{success: bool, data: {local_time: str, timezone: str, utc_time: str}}` |
| `/api/settings/system/info` | GET | 获取系统信息 | 无 | `{success: bool, data: {supported_languages: int, supported_timezones: int}}` |

### 2.2 数据流图
```
[用户请求]
    ↓
[Vue 前端] → 调用 API
    ↓
[settings.py] → API 端点
    ↓
[TimezoneManager] → 时区管理逻辑
    ↓
[UserWorkspaceManager] → 用户偏好存储
    ↓
[返回结果] → JSON 响应
```

### 2.3 多语言支持架构
```
[Vue 前端]
    ↓ $language.t()
[language.js] → 前端语言管理
    ↓ API 调用
[settings.py] → 后端语言 API
    ↓
[manager.py] → 后端语言管理器
    ↓
[models.py] → 语言枚举（11种语言）
```

---

## 3. 实现细节

### 3.1 已完成的子任务
- [x] 3.1 完善多语言支持（11种语言）
- [x] 3.2 确保 Vue 前端正确集成（已替换 $i18n 为 $language）
- [x] 3.3 实现 `TimezoneManager`（时区管理器）
- [x] 3.4 完善时区管理 API
- [x] 3.5 完善多用户管理与数据隔离
- [x] 3.6 完善设置 API
- [x] 3.7 编写集成测试
- [x] 3.8 更新模块设计文档（本文档）
- [x] 3.9 提交代码审查

### 3.2 关键代码片段

#### 3.2.1 时区管理器初始化
```python
# neurova/core/timezone_manager.py

from typing import Dict, List, Optional, Any
import pytz
from datetime import datetime
from neurova.core.user_workspace import UserWorkspaceManager

class TimezoneManager:
    """时区管理器"""
    
    def __init__(self, workspace_manager: UserWorkspaceManager):
        """初始化时区管理器"""
        self.workspace_manager = workspace_manager
        self.all_timezones = pytz.all_timezones
```

#### 3.2.2 获取所有时区 API
```python
# neurova/api/settings.py

@settings_bp.route('/api/settings/timezones', methods=['GET'])
@login_required
def get_timezones():
    """获取所有时区"""
    try:
        timezones = timezone_manager.get_all_timezones()
        return jsonify({
            'success': True,
            'data': timezones
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500
```

#### 3.2.3 前端语言列表（已更新）
```javascript
// neurova/vue/js/language.js

export const languages = {
  'en_US': { code: 'en_US', name: 'English', native: 'English', flag: '🇺🇸' },
  'zh_CN': { code: 'zh_CN', name: 'Chinese (Simplified)', native: '简体中文', flag: '🇨🇳' },
  'zh_TW': { code: 'zh_TW', name: 'Chinese (Traditional)', native: '繁體中文', flag: '🇹🇼' },
  'ja_JP': { code: 'ja_JP', name: 'Japanese', native: '日本語', flag: '🇯🇵' },
  'ko_KR': { code: 'ko_KR', name: 'Korean', native: '한국어', flag: '🇰🇷' },
  'fr_FR': { code: 'fr_FR', name: 'French', native: 'Français', flag: '🇫🇷' },
  'de_DE': { code: 'de_DE', name: 'German', native: 'Deutsch', flag: '🇩🇪' },
  'es_ES': { code: 'es_ES', name: 'Spanish', native: 'Español', flag: '🇪🇸' },
  'ru_RU': { code: 'ru_RU', name: 'Russian', native: 'Русский', flag: '🇷🇺' },
  'pt_PT': { code: 'pt_PT', name: 'Portuguese', native: 'Português', flag: '🇵🇹' },
  'ar_SA': { code: 'ar_SA', name: 'Arabic', native: 'العربية', flag: '🇸🇦' },
};
```

---

## 4. 测试计划

### 4.1 单元测试
| 测试用例 | 测试内容 | 状态 | 通过率 |
|---------|---------|------|--------|
| test_get_all_timezones | 测试获取所有时区 | ✅ 通过 | 100% |
| test_get_timezone_info | 测试获取时区信息 | ✅ 通过 | 100% |
| test_get_user_timezone | 测试获取用户时区 | ✅ 通过 | 100% |
| test_set_user_timezone | 测试设置用户时区 | ✅ 通过 | 100% |
| test_get_local_time | 测试获取本地时间 | ✅ 通过 | 100% |

### 4.2 集成测试
- [x] 测试多语言切换功能
- [x] 测试时区设置功能
- [x] 测试用户数据隔离

---

## 5. 已知问题

| 问题描述 | 严重程度 | 发现时间 | 解决方案 | 状态 |
|---------|---------|----------|--------|------|
| 无 | - | - | - | - |

---

## 6. 变更记录

| 时间 | 变更内容 | 变更原因 | 影响范围 |
|------|---------|---------|---------|
| 2026-05-12 21:53 | 任务启动 | 用户要求 | 全部 |
| 2026-05-12 22:00 | 完成多语言支持（11种语言） | 设计文档要求 | `language/` |
| 2026-05-12 22:00 | 创建 `timezone_manager.py` | 设计文档要求 | `core/` |
| 2026-05-12 22:00 | 更新 `settings.py` API | 设计文档要求 | `api/` |
| 2026-05-12 22:01 | 完成任务，更新文档 | 任务完成 | `docs/` |

---

## 7. 附录

### 7.1 参考资料
- NEUROVA_CogArch_2.0.md 第5章
- Python pytz 文档: http://pytz.sourceforge.net/
- Vue I18n 文档: https://vue-i18n.intlify.dev/

### 7.2 相关文件
- `neurova/language/__init__.py`
- `neurova/language/models.py`
- `neurova/language/manager.py`
- `neurova/vue/js/language.js`
- `neurova/core/timezone_manager.py` (新建)
- `neurova/core/user_workspace.py`
- `neurova/api/settings.py`
- `neurova/vue/js/components/Settings.js`

---

**最后更新**: 2026-05-12 22:01 | **更新人**: settings-dev
