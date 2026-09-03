"""Tests for neurova.language.models — TDD RED phase."""
import enum
import inspect
import typing
from dataclasses import is_dataclass
from datetime import datetime, timezone

import pytest


class TestLanguage:
    def test_is_enum_subclass(self):
        from neurova.language.models import Language
        assert issubclass(Language, enum.Enum)

    def test_has_zh(self):
        from neurova.language.models import Language
        assert hasattr(Language, "ZH") or hasattr(Language, "CHINESE") or hasattr(Language, "zh")

    def test_has_en(self):
        from neurova.language.models import Language
        assert hasattr(Language, "EN") or hasattr(Language, "ENGLISH") or hasattr(Language, "en")

    def test_at_least_3_languages(self):
        from neurova.language.models import Language
        assert len(list(Language)) >= 3


class TestTranslationKey:
    def test_is_dataclass(self):
        from neurova.language.models import TranslationKey
        assert is_dataclass(TranslationKey)

    def test_can_instantiate(self):
        from neurova.language.models import TranslationKey
        tk = TranslationKey(key="hello", namespace="ui")
        assert tk.key == "hello"
        assert tk.namespace == "ui"


class TestTranslation:
    def test_is_dataclass(self):
        from neurova.language.models import Translation
        assert is_dataclass(Translation)

    def test_can_instantiate(self):
        from neurova.language.models import Translation
        t = Translation(key="hello", language="zh", value="你好")
        assert t.value == "你好"
        assert t.language == "zh"


class TestUserLanguagePreference:
    def test_is_dataclass(self):
        from neurova.language.models import UserLanguagePreference
        assert is_dataclass(UserLanguagePreference)

    def test_can_instantiate(self):
        from neurova.language.models import UserLanguagePreference
        pref = UserLanguagePreference(user_id="u1", language="en")
        assert pref.user_id == "u1"
        assert pref.language == "en"
