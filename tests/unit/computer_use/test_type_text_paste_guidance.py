# -*- coding: utf-8 -*-
"""C5 长文本 paste 优先引导（OSWorld 失败驱动改进卡）红灯测试。

M4 教训（f918266a 75 步逐字符敲代码、c288e301 15 步 typewrite 长命令）：
type_text 被用于长文本输入，又慢又易错。本卡两面收敛：

- 行为面：type_text 对超过阈值（200 字符）的输入在结果附 ``suggest_paste``
  （不拒绝执行——语义仍成功，只加引导）；
- 描述面：computer_type 工具描述注明"适合短文本；长文本改用 computer_paste"
  （模型可见文本，eval case 先行——见 tests/unit/evals/test_computer_use_cases.py）。
"""

from unittest.mock import MagicMock

from neurova.computer_use.actions import type_text


def _manager(ok=True):
    manager = MagicMock()
    manager.type_text = MagicMock(return_value=ok)
    return manager


class TestTypeTextPasteGuidance:
    def test_longTextGetsSuggestPaste(self):
        result = type_text(_manager(), "x" * 201)
        assert result.get("success") is True, "长文本仍执行（引导不拒绝）"
        assert result.get("suggest_paste") is True, ">200 字符必须附 paste 引导"
        assert result.get("suggest_paste_hint"), "引导须带提示文本（点名 computer_paste）"
        assert "computer_paste" in result["suggest_paste_hint"]

    def test_shortTextNoSuggestKey(self):
        result = type_text(_manager(), "x" * 50)
        assert result.get("success") is True
        assert "suggest_paste" not in result, "短文本不加引导（阈值 200）"

    def test_boundaryAt200NoSuggest(self):
        result = type_text(_manager(), "x" * 200)
        assert "suggest_paste" not in result, "恰好 200 字符属短文本侧（>200 才引导）"

    def test_failurePathNoSuggestNoise(self):
        result = type_text(_manager(ok=False), "x" * 300)
        assert result.get("success") is not True
        assert "suggest_paste" not in result, "失败路径不加引导噪声"