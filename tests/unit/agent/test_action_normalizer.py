"""R1-3 执行前归一化层（CUA 升级方案 Phase 1，Cua OperatorNormalizer 思想）

病根（修复前）：LLM 产出的 computer/browser 工具参数直接分发到执行体——
词表外的 button 值、字符串坐标、幻觉的未知键全部直通底层。

验收（HTTP 侧 extra="forbid" 精神推广到 agent 侧）：
- button 别名归一（"right-click"/"secondary"→"right"），词表外拒绝
- 坐标/整数参数强转（字符串数字 → 数值）
- 未知键拒绝（幻觉参数在执行前拦截）
- 已知键之外的非法值（如 max_nodes="abc"）拒绝
- 非 computer/browser 工具原样放行（归一化层不越权）
"""

import pytest

from neurova.tool_executor import normalize_computer_params


class TestButtonNormalization:
    def test_canonical_passthrough(self):
        cleaned = normalize_computer_params("computer_click", {"x": 1, "y": 2, "button": "left"})
        assert cleaned["button"] == "left"

    def test_aliases_normalized(self):
        for raw, expected in (
            ("right-click", "right"),
            ("middle-click", "middle"),
            ("secondary", "right"),
            ("primary", "left"),
            ("RIGHT", "right"),
        ):
            cleaned = normalize_computer_params("computer_click", {"x": 1, "y": 2, "button": raw})
            assert cleaned["button"] == expected

    def test_unknown_button_rejected(self):
        with pytest.raises(ValueError, match="button"):
            normalize_computer_params("computer_click", {"x": 1, "y": 2, "button": "laser"})


class TestNumericCoercion:
    def test_string_coordinates_coerced(self):
        cleaned = normalize_computer_params("computer_click", {"x": "100", "y": "200"})
        assert cleaned["x"] == 100.0 and cleaned["y"] == 200.0

    def test_generation_coerced_to_int(self):
        cleaned = normalize_computer_params("browser_click_role", {"role": "button", "generation": "3"})
        assert cleaned["generation"] == 3

    def test_index_coerced_to_int(self):
        cleaned = normalize_computer_params("computer_click_element", {"index": "5"})
        assert cleaned["index"] == 5

    def test_non_numeric_coordinate_rejected(self):
        with pytest.raises(ValueError, match="x"):
            normalize_computer_params("computer_click", {"x": "center", "y": 2})


class TestUnknownKeys:
    def test_hallucinated_key_rejected(self):
        with pytest.raises(ValueError, match="未知参数"):
            normalize_computer_params("computer_click", {"x": 1, "y": 2, "selector": "#btn"})

    def test_known_keys_pass(self):
        cleaned = normalize_computer_params(
            "computer_set_value", {"value": "hi", "index": 1, "window_title": "记事本"}
        )
        assert cleaned == {"value": "hi", "index": 1, "window_title": "记事本"}


class TestScope:
    def test_non_computer_tool_passthrough(self):
        params = {"query": "x", "anything": True}
        assert normalize_computer_params("web_search", params) is params

    def test_none_params(self):
        assert normalize_computer_params("computer_screenshot", None) == {}
        assert normalize_computer_params("computer_screenshot", {}) == {}
