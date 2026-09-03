# -*- coding: utf-8 -*-
"""
单元测试：系统设置功能

测试内容:
1. Language 枚举
2. LanguageManager
3. TimezoneManager
4. UserWorkspace

对齐说明：生产代码已重构（language 枚举名从 zh_CN/en_US 改为 zh/en；
Translation/UserLanguagePreference 为 dataclass；TimezoneInfo 构造为
name/offset/utc_offset；UserWorkspace 使用 Path 路径）。本文件对齐当前实现。
"""

import shutil
import sys
import unittest
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from neurova.language.models import Language, Translation, UserLanguagePreference
from neurova.language.manager import LanguageManager
from neurova.core.timezone_manager import TimezoneManager, TimezoneInfo
from neurova.core.user_workspace import UserWorkspace, UserWorkspaceManager


class TestLanguageEnum(unittest.TestCase):
    """测试 Language 枚举"""

    def test_language_values(self):
        """测试语言枚举值"""
        self.assertEqual(Language.CHINESE.value, "zh")
        self.assertEqual(Language.ENGLISH.value, "en")
        self.assertEqual(Language.SPANISH.value, "es")
        self.assertEqual(Language.PORTUGUESE.value, "pt")

    def test_language_get_name(self):
        """测试语言名称"""
        self.assertEqual(Language.ENGLISH.get_name(), "English")
        self.assertEqual(Language.CHINESE.get_name(), "中文")
        self.assertEqual(Language.SPANISH.get_name(), "Español")

    def test_language_from_str(self):
        """测试字符串转换"""
        self.assertEqual(Language.from_str("en"), Language.ENGLISH)
        self.assertEqual(Language.from_str("zh"), Language.CHINESE)
        # 未知语言回退到 AUTO
        self.assertEqual(Language.from_str("invalid"), Language.AUTO)

    def test_language_auto(self):
        """测试 AUTO 语言"""
        self.assertEqual(Language.AUTO.value, "auto")


class TestTranslation(unittest.TestCase):
    """测试 Translation 类"""

    def test_translation_create(self):
        """测试创建翻译"""
        trans = Translation(key="test", language=Language.ENGLISH, value="Hello")
        self.assertEqual(trans.key, "test")
        self.assertEqual(trans.language, Language.ENGLISH)
        self.assertEqual(trans.value, "Hello")

    def test_translation_to_dict(self):
        """测试转换为字典"""
        trans = Translation(key="test", language=Language.CHINESE, value="你好")
        result = trans.to_dict()
        self.assertEqual(result["key"], "test")
        self.assertEqual(result["language"], "zh")
        self.assertEqual(result["value"], "你好")

    def test_translation_get_full_key(self):
        """测试完整键名"""
        trans = Translation(key="test", language=Language.ENGLISH, value="Hello")
        self.assertEqual(trans.get_full_key(), "test")

        trans_ns = Translation(key="test", language=Language.ENGLISH, value="Hello", namespace="ui")
        self.assertEqual(trans_ns.get_full_key(), "ui.test")


class TestUserLanguagePreference(unittest.TestCase):
    """测试 UserLanguagePreference 类"""

    def test_default_values(self):
        """测试默认值"""
        pref = UserLanguagePreference(user_id="test_user")
        self.assertEqual(pref.user_id, "test_user")
        self.assertEqual(pref.primary_language, Language.CHINESE)
        self.assertEqual(pref.fallback_language, Language.ENGLISH)
        self.assertTrue(pref.auto_detect)

    def test_get_preferred_languages(self):
        """测试首选语言列表（仅 primary + secondary）"""
        pref = UserLanguagePreference(
            user_id="test_user",
            primary_language=Language.ENGLISH,
            secondary_languages=[Language.JAPANESE],
        )
        languages = pref.get_preferred_languages()
        self.assertIn(Language.ENGLISH, languages)
        self.assertIn(Language.JAPANESE, languages)
        self.assertNotIn(Language.CHINESE, languages)


class TestLanguageManager(unittest.TestCase):
    """测试 LanguageManager 类"""

    def setUp(self):
        """测试前准备"""
        self.manager = LanguageManager(data_dir="test_language_data")

    def tearDown(self):
        """测试后清理"""
        shutil.rmtree("test_language_data", ignore_errors=True)

    def test_get_available_languages(self):
        """测试获取可用语言列表（内置 zh/en/ja/ko）"""
        languages = self.manager.get_available_languages()
        self.assertGreaterEqual(len(languages), 4)
        self.assertIn(Language.CHINESE, languages)
        self.assertIn(Language.ENGLISH, languages)

    def test_get_translation(self):
        """测试获取翻译"""
        # 内置键
        self.assertEqual(self.manager.get_translation("greeting", Language.ENGLISH), "Hello")
        self.assertEqual(self.manager.get_translation("greeting", Language.CHINESE), "你好")
        # 不存在的键返回键本身
        self.assertEqual(self.manager.get_translation("nonexistent.key"), "nonexistent.key")

    def test_set_and_get_user_preference(self):
        """测试设置和获取用户偏好"""
        pref = UserLanguagePreference(
            user_id="user1",
            primary_language=Language.ENGLISH,
            fallback_language=Language.CHINESE,
            auto_detect=True,
        )
        self.assertTrue(self.manager.set_user_preference("user1", pref))

        retrieved = self.manager.get_user_preference("user1")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.primary_language, Language.ENGLISH)
        self.assertEqual(retrieved.fallback_language, Language.CHINESE)

    def test_detect_browser_language(self):
        """测试检测浏览器语言"""
        # 英语
        lang = self.manager.detect_browser_language("en-US,en;q=0.9")
        self.assertEqual(lang, Language.ENGLISH)

        # 简体中文
        lang = self.manager.detect_browser_language("zh-CN,zh;q=0.9")
        self.assertEqual(lang, Language.CHINESE)

        # 无效语言回退到默认（中文）
        lang = self.manager.detect_browser_language("invalid")
        self.assertEqual(lang, Language.CHINESE)

    def test_get_statistics(self):
        """测试统计信息"""
        stats = self.manager.get_statistics()
        self.assertIn("total_translations", stats)
        self.assertGreater(stats["total_translations"], 0)
        self.assertIn("available_languages", stats)


class TestTimezoneInfo(unittest.TestCase):
    """测试 TimezoneInfo 类"""

    def test_timezone_info_creation(self):
        """测试创建时区信息"""
        info = TimezoneInfo(name="Asia/Shanghai", offset="+0800", utc_offset=8.0)
        self.assertEqual(info.name, "Asia/Shanghai")
        self.assertEqual(info.offset, "+0800")
        self.assertEqual(info.utc_offset, 8.0)

    def test_timezone_info_to_dict(self):
        """测试转换为字典"""
        info = TimezoneInfo(name="America/New_York", offset="-0500", utc_offset=-5.0)
        result = info.to_dict()
        self.assertEqual(result["name"], "America/New_York")
        self.assertEqual(result["offset"], "-0500")
        self.assertEqual(result["utc_offset"], -5.0)


class TestTimezoneManager(unittest.TestCase):
    """测试 TimezoneManager 类"""

    def setUp(self):
        """测试前准备"""
        self.manager = TimezoneManager()

    def test_get_all_timezones(self):
        """测试获取所有时区"""
        timezones = self.manager.get_all_timezones()
        self.assertGreater(len(timezones), 0)
        self.assertIn("Asia/Shanghai", timezones)
        self.assertIn("America/New_York", timezones)

    def test_is_valid_timezone(self):
        """测试验证时区"""
        self.assertTrue(self.manager.is_valid_timezone("Asia/Shanghai"))
        self.assertTrue(self.manager.is_valid_timezone("America/New_York"))
        self.assertFalse(self.manager.is_valid_timezone("Invalid/Timezone"))

    def test_get_timezone_info(self):
        """测试获取时区信息"""
        info = self.manager.get_timezone_info("Asia/Shanghai")
        self.assertIsNotNone(info)
        self.assertEqual(info.name, "Asia/Shanghai")
        self.assertEqual(info.utc_offset, 8.0)

    def test_get_common_timezones(self):
        """测试获取常用时区"""
        common = self.manager.get_common_timezones()
        self.assertIn("Asia/Shanghai", common)
        self.assertIn("Europe/London", common)
        self.assertIn("America/New_York", common)

    def test_get_all_timezone_info(self):
        """测试获取所有时区详细信息"""
        info_list = self.manager.get_all_timezone_info()
        self.assertGreater(len(info_list), 0)

        # 检查第一个元素的结构
        first = info_list[0]
        self.assertIsInstance(first, TimezoneInfo)
        self.assertTrue(first.name)
        self.assertIsInstance(first.utc_offset, float)

    def test_user_timezone(self):
        """测试用户时区设置"""
        self.manager.set_user_timezone("Asia/Tokyo", user_id="tz_user")
        self.assertEqual(self.manager.get_user_timezone("tz_user"), "Asia/Tokyo")

    def test_timezone_offset(self):
        """测试时区偏移量"""
        offset = self.manager.get_timezone_offset("Asia/Shanghai")
        self.assertEqual(offset, 8.0)


class TestUserWorkspace(unittest.TestCase):
    """测试 UserWorkspace 类"""

    def setUp(self):
        """测试前准备"""
        self.test_user_id = "test_user_123"
        self.workspace = UserWorkspace(self.test_user_id, Path("test_workspaces"))

    def tearDown(self):
        """测试后清理"""
        shutil.rmtree("test_workspaces", ignore_errors=True)

    def test_workspace_creation(self):
        """测试工作空间创建"""
        self.assertTrue(self.workspace.root_path.exists())

        # 检查子目录
        self.assertTrue(self.workspace.database_path.exists())
        self.assertTrue(self.workspace.memory_path.exists())
        self.assertTrue(self.workspace.projects_path.exists())

    def test_get_set_config(self):
        """测试获取和设置配置"""
        # 设置配置
        self.workspace.set_config("language", "en")
        self.workspace.set_config("timezone", "America/New_York")

        # 获取配置
        self.assertEqual(self.workspace.get_config("language"), "en")
        self.assertEqual(self.workspace.get_config("timezone"), "America/New_York")

        # 不存在的配置返回默认值
        self.assertIsNone(self.workspace.get_config("nonexistent"))
        self.assertEqual(self.workspace.get_config("nonexistent", "default"), "default")

    def test_workspace_properties(self):
        """测试工作空间属性"""
        self.assertEqual(self.workspace.user_id, self.test_user_id)
        self.assertTrue(str(self.workspace.database_path).endswith("database"))
        self.assertTrue(str(self.workspace.memory_path).endswith("memory"))


class TestUserWorkspaceManager(unittest.TestCase):
    """测试 UserWorkspaceManager 类"""

    def setUp(self):
        """测试前准备"""
        self.manager = UserWorkspaceManager(Path("test_workspaces_2"))

    def tearDown(self):
        """测试后清理"""
        shutil.rmtree("test_workspaces_2", ignore_errors=True)

    def test_create_workspace(self):
        """测试创建工作空间"""
        workspace = self.manager.create_workspace("user1")
        self.assertEqual(workspace.user_id, "user1")
        self.assertTrue(workspace.root_path.exists())

    def test_get_workspace(self):
        """测试获取工作空间"""
        # 第一次获取会创建
        workspace = self.manager.get_workspace("user2")
        self.assertEqual(workspace.user_id, "user2")

        # 第二次获取应该返回同一个实例
        workspace2 = self.manager.get_workspace("user2")
        self.assertIs(workspace, workspace2)

    def test_list_workspaces(self):
        """测试列出工作空间"""
        self.manager.create_workspace("user3")
        self.manager.create_workspace("user4")

        user_ids = self.manager.list_workspaces()
        self.assertIn("user3", user_ids)
        self.assertIn("user4", user_ids)

    def test_delete_workspace(self):
        """测试删除工作空间"""
        self.manager.create_workspace("user5")
        self.assertTrue(self.manager.workspace_exists("user5"))

        result = self.manager.delete_workspace("user5")
        self.assertTrue(result)
        self.assertFalse(self.manager.workspace_exists("user5"))


if __name__ == '__main__':
    unittest.main()
