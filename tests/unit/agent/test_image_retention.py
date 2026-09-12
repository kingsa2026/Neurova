"""R2-4 历史图片保留策略（CUA 升级方案 Phase 2，Cua ImageRetention 思想）

背景：Neurova 的图片 base64 只挂当轮请求（2026-09-09 串台事故后历史只留
中性标记），本模块是**防线式收口**——在请求装配的最终出口强制"只保留最近
N 条含图片的消息"，任何上游变化（截图进上下文、RS 远程会话平面）都不会
悄悄撑爆 LLM 上下文。

与 Cua 原版的适配差异：Neurova 历史无 computer_call 配对结构，故"成对删除"
适配为"图片部件置空占位"（文本说明保留，图省略）。

验收：
- 只保留最近 keep_last 条含图消息的图片部件，更早的置为占位文本
- 纯文本消息永不触碰
- 混合 content（text+image）只摘除图片部件、保留文本
- stats 如实上报（kept/removed/touched）
"""

import pytest

from neurova.agent.image_retention import apply_image_retention, count_images


def img_msg(content="看看图"):
    return {
        "role": "user",
        "content": [
            {"type": "text", "text": content},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
        ],
    }


def text_msg(content="hello"):
    return {"role": "user", "content": content}


class TestImageRetention:
    def test_keeps_last_n_image_rounds(self):
        messages = [img_msg("旧1"), img_msg("旧2"), img_msg("新"), text_msg("中间的纯文本")]
        cleaned, stats = apply_image_retention(messages, keep_last=1)
        # 最新的图片轮保留完整
        assert cleaned[2]["content"][1]["type"] == "image_url"
        # 更早的图片轮图片部件被置空
        assert cleaned[0]["content"][1]["type"] == "text"
        assert "已省略" in cleaned[0]["content"][1]["text"]
        # 文本部分原样保留
        assert cleaned[0]["content"][0]["text"] == "旧1"
        # 纯文本消息不受影响
        assert cleaned[3]["content"] == "中间的纯文本"
        assert stats["images_kept"] == 1
        assert stats["images_removed"] == 2
        assert stats["messages_touched"] == 2

    def test_no_images_untouched(self):
        messages = [text_msg("a"), {"role": "assistant", "content": "b"}]
        cleaned, stats = apply_image_retention(messages, keep_last=4)
        assert cleaned == messages
        assert stats["images_removed"] == 0

    def test_within_budget_untouched(self):
        messages = [img_msg("a"), img_msg("b")]
        cleaned, stats = apply_image_retention(messages, keep_last=4)
        assert all(
            any(p.get("type") == "image_url" for p in m["content"])
            for m in cleaned
            if isinstance(m["content"], list)
        )
        assert stats["images_removed"] == 0

    def test_string_content_message_with_image_format(self):
        """content 为字符串的消息永不触碰（防御非预期格式）"""
        messages = [{"role": "user", "content": "data:image/png;base64,xxx"}]
        cleaned, _ = apply_image_retention(messages, keep_last=0)
        assert cleaned[0]["content"] == "data:image/png;base64,xxx"

    def test_keep_last_zero_strips_all(self):
        messages = [img_msg("a"), img_msg("b")]
        _, stats = apply_image_retention(messages, keep_last=0)
        assert stats["images_removed"] == 2 and stats["images_kept"] == 0

    def test_original_list_not_mutated_shallow(self):
        """调用方传入的消息列表不被就地重排（返回新列表）"""
        messages = [img_msg("a"), text_msg("b")]
        cleaned, _ = apply_image_retention(messages, keep_last=0)
        assert cleaned is not messages


class TestCountImages:
    def test_count(self):
        messages = [img_msg("a"), img_msg("b"), text_msg("c"), img_msg("d")]
        assert count_images(messages) == 3
