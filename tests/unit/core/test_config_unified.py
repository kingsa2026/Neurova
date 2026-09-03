"""
统一配置库模块级函数测试

验证 neurova.core.config 提供的模块级便捷函数:
- get(key, default): 读取环境变量字符串
- get_int(key, default): 读取整数
- get_bool(key, default): 读取布尔值
- get_list(key, default, sep): 读取列表

测试策略: 通过公开接口验证行为，使用 monkeypatch 隔离环境变量，
确保测试不依赖全局状态、可重复运行。
"""

import pytest

from neurova.core import config


# ---------------------------------------------------------------------------
# get()
# ---------------------------------------------------------------------------


class TestConfigGet:
    """config.get 行为测试"""

    def test_get_returns_env_value_when_set(self, monkeypatch):
        """环境变量已设置时返回其值"""
        monkeypatch.setenv("TEST_CFG_GET_KEY", "hello-world")
        assert config.get("TEST_CFG_GET_KEY") == "hello-world"

    def test_get_returns_default_when_unset(self, monkeypatch):
        """环境变量未设置时返回 default"""
        monkeypatch.delenv("TEST_CFG_GET_MISSING", raising=False)
        assert config.get("TEST_CFG_GET_MISSING", "fallback") == "fallback"

    def test_get_returns_none_when_unset_and_no_default(self, monkeypatch):
        """环境变量未设置且无 default 时返回 None"""
        monkeypatch.delenv("TEST_CFG_GET_NONE", raising=False)
        assert config.get("TEST_CFG_GET_NONE") is None

    def test_get_returns_empty_string_when_env_empty(self, monkeypatch):
        """环境变量为空字符串时返回空字符串（而非 default）"""
        monkeypatch.setenv("TEST_CFG_GET_EMPTY", "")
        assert config.get("TEST_CFG_GET_EMPTY", "fallback") == ""


# ---------------------------------------------------------------------------
# get_int()
# ---------------------------------------------------------------------------


class TestConfigGetInt:
    """config.get_int 行为测试"""

    def test_get_int_returns_int_type(self, monkeypatch):
        """返回整数类型"""
        monkeypatch.setenv("TEST_CFG_INT", "9527")
        result = config.get_int("TEST_CFG_INT")
        assert result == 9527
        assert isinstance(result, int)

    def test_get_int_returns_default_when_unset(self, monkeypatch):
        """未设置时返回 default"""
        monkeypatch.delenv("TEST_CFG_INT_MISSING", raising=False)
        assert config.get_int("TEST_CFG_INT_MISSING", 42) == 42

    def test_get_int_default_zero_when_unset_no_default(self, monkeypatch):
        """未设置且无 default 时返回 0"""
        monkeypatch.delenv("TEST_CFG_INT_ZERO", raising=False)
        assert config.get_int("TEST_CFG_INT_ZERO") == 0

    def test_get_int_returns_default_on_invalid_value(self, monkeypatch):
        """非数字值时返回 default（不抛异常）"""
        monkeypatch.setenv("TEST_CFG_INT_BAD", "not-a-number")
        assert config.get_int("TEST_CFG_INT_BAD", 99) == 99


# ---------------------------------------------------------------------------
# get_bool()
# ---------------------------------------------------------------------------


class TestConfigGetBool:
    """config.get_bool 行为测试"""

    @pytest.mark.parametrize("truthy", ["true", "True", "TRUE", "1", "yes", "on", "YES", "ON"])
    def test_get_bool_truthy_values(self, monkeypatch, truthy):
        """true/1/yes/on 等字符串返回 True"""
        monkeypatch.setenv("TEST_CFG_BOOL", truthy)
        assert config.get_bool("TEST_CFG_BOOL") is True

    @pytest.mark.parametrize("falsy", ["false", "False", "FALSE", "0", "no", "off", "No", "OFF"])
    def test_get_bool_falsy_values(self, monkeypatch, falsy):
        """false/0/no/off 等字符串返回 False"""
        monkeypatch.setenv("TEST_CFG_BOOL", falsy)
        assert config.get_bool("TEST_CFG_BOOL") is False

    def test_get_bool_returns_default_when_unset(self, monkeypatch):
        """未设置时返回 default"""
        monkeypatch.delenv("TEST_CFG_BOOL_MISSING", raising=False)
        assert config.get_bool("TEST_CFG_BOOL_MISSING", True) is True
        assert config.get_bool("TEST_CFG_BOOL_MISSING", False) is False

    def test_get_bool_default_false_when_unset_no_default(self, monkeypatch):
        """未设置且无 default 时返回 False"""
        monkeypatch.delenv("TEST_CFG_BOOL_DEFAULT", raising=False)
        assert config.get_bool("TEST_CFG_BOOL_DEFAULT") is False

    def test_get_bool_returns_bool_type(self, monkeypatch):
        """返回值是 bool 类型而非字符串"""
        monkeypatch.setenv("TEST_CFG_BOOL_TYPE", "true")
        result = config.get_bool("TEST_CFG_BOOL_TYPE")
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# get_list()
# ---------------------------------------------------------------------------


class TestConfigGetList:
    """config.get_list 行为测试"""

    def test_get_list_returns_list_type(self, monkeypatch):
        """返回列表类型"""
        monkeypatch.setenv("TEST_CFG_LIST", "a,b,c")
        result = config.get_list("TEST_CFG_LIST")
        assert result == ["a", "b", "c"]
        assert isinstance(result, list)

    def test_get_list_strips_whitespace(self, monkeypatch):
        """去除每项首尾空白"""
        monkeypatch.setenv("TEST_CFG_LIST", " a , b , c ")
        assert config.get_list("TEST_CFG_LIST") == ["a", "b", "c"]

    def test_get_list_filters_empty_items(self, monkeypatch):
        """过滤空项"""
        monkeypatch.setenv("TEST_CFG_LIST", "a,,b,")
        assert config.get_list("TEST_CFG_LIST") == ["a", "b"]

    def test_get_list_custom_separator(self, monkeypatch):
        """支持自定义分隔符"""
        monkeypatch.setenv("TEST_CFG_LIST", "a|b|c")
        assert config.get_list("TEST_CFG_LIST", sep="|") == ["a", "b", "c"]

    def test_get_list_returns_default_when_unset(self, monkeypatch):
        """未设置时返回 default"""
        monkeypatch.delenv("TEST_CFG_LIST_MISSING", raising=False)
        default = ["x", "y"]
        assert config.get_list("TEST_CFG_LIST_MISSING", default) == ["x", "y"]

    def test_get_list_returns_empty_list_when_unset_no_default(self, monkeypatch):
        """未设置且无 default 时返回空列表"""
        monkeypatch.delenv("TEST_CFG_LIST_EMPTY", raising=False)
        assert config.get_list("TEST_CFG_LIST_EMPTY") == []

    def test_get_list_empty_env_returns_empty_list(self, monkeypatch):
        """环境变量为空字符串时返回空列表"""
        monkeypatch.setenv("TEST_CFG_LIST_BLANK", "")
        assert config.get_list("TEST_CFG_LIST_BLANK") == []
