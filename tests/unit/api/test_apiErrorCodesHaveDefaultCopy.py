# -*- coding: utf-8 -*-
"""批 G2：APIError 已声明码的「码 → 默认文案」登记表。

立项理由（docs/specs/2026-11-03-提示面资产化与出口审批收口升级设计.md 批 G）：
错误码唯一守卫此前只钉码→HTTP 状态（error_handlers._CODE_TO_HTTP_STATUS），
不钉码→文案——前端把 `detail` 原样显示给用户，抛出点漏写 message 时信封里
就是空字符串。本批给每个已声明码登记默认文案，并把消费点接进信封装配：
抛出点给了话用原话，空话回落默认文案，连默认都没有就点名码本身——
绝不发空串。
"""
from neurova.api.error_handlers import resolveErrorMessage
from neurova.interfaces.api_standard import DEFAULT_ERROR_MESSAGES, ErrorCodes


class TestRegistryCompleteness:
    def test_everyDeclaredCodeHasADefaultCopy(self):
        """登记表必须覆盖 ErrorCodes 全体成员——缺一枚即红（缺文案的码会漏出空信封）。"""
        members = set(ErrorCodes)
        registered = set(DEFAULT_ERROR_MESSAGES)
        missing = members - registered
        assert not missing, (
            f"这些已声明错误码没有默认文案: {sorted(missing)}——"
            "补进 DEFAULT_ERROR_MESSAGES（码表单源在 api_standard.ErrorCodes）"
        )

    def test_registryHasNoOrphanEntries(self):
        """登记表不许有码表之外的孤儿条目——孤儿即第二份码表（教义第 6 条）。"""
        orphans = set(DEFAULT_ERROR_MESSAGES) - set(ErrorCodes)
        assert not orphans, f"DEFAULT_ERROR_MESSAGES 里出现了未声明码: {sorted(orphans)}"

    def test_everyCopyIsNonTrivialChinese(self):
        """默认文案必须非空且能单独示人——裸码、空串、单字符都算没交待。"""
        for code, copy in sorted(DEFAULT_ERROR_MESSAGES.items()):
            assert isinstance(copy, str) and len(copy.strip()) >= 4, (
                f"{code.name} 的默认文案太敷衍: {copy!r}"
            )


class TestResolveBehavior:
    def test_givenMessageWins(self):
        """抛出点给了话 → 原话直通（默认文案不覆盖具体原因）。"""
        assert resolveErrorMessage(ErrorCodes.NOT_FOUND, "工作流不存在") == "工作流不存在"

    def test_blankMessageFallsBackToDefault(self):
        """空话/空白话 → 回落该码默认文案（信封里不许出现空 message）。"""
        assert resolveErrorMessage(ErrorCodes.NOT_FOUND, "") != ""
        assert resolveErrorMessage(ErrorCodes.NOT_FOUND, "   ") == \
            DEFAULT_ERROR_MESSAGES[ErrorCodes.NOT_FOUND]

    def test_unregisteredCodeNamesItself(self):
        """连默认都没有的码（未来新增漏登记）→ 点名码本身，仍不发空串。"""
        assert resolveErrorMessage(9999, "") == "错误码 9999"
