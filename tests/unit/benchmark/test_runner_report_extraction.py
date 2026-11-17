# -*- coding: utf-8 -*-
"""runner._extractText 的判据输入卫生（真模型基线实测抓到的假通过根因）。

dict 无正文键时不得回退 str(result)——那会把 reasoning/内部字段的 repr 当
"报告"喂给判据（实测：DCF 任务正文为空，标记却匹配在 reasoning 的 repr 里，
判了假通过）。没有正文就如实给空，让判据按失败计。
"""

import pytest

from neurova.benchmark.multi_agent.runner import _extractText


class TestExtractTextHygiene:
    def test_dict_without_text_keys_returns_empty_not_repr(self):
        result = {
            "text": "",
            "audio_path": None,
            "cognitive_score": 0.728,
            "reasoning": "【自由现金流预测】【折现率 WACC】（标记只出现在推理里）",
        }
        assert _extractText(result) == "", "不得把响应对象 repr 当报告喂给判据"

    def test_dict_with_text_key_returns_it(self):
        assert _extractText({"text": "正文"}) == "正文"
        assert _extractText({"report": "报告"}) == "报告"

    def test_object_content_still_extracted(self):
        class _R:
            content = "对象正文"

        assert _extractText(_R()) == "对象正文"

    def test_none_and_plain_string(self):
        assert _extractText(None) == ""
        assert _extractText("裸字符串") == "裸字符串"
