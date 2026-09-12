"""历史图片保留策略（CUA 升级方案 R2-4）

Neurova 的图片 base64 只挂当轮请求（请求级 vision parts，2026-09-09 串台
事故后历史只留中性标记）。本模块在请求装配最终出口做**防线式收口**：
强制只保留最近 keep_last 条含图片消息的图片部件，更早的置为占位文本。

设计取舍（相对 Cua ImageRetention 的适配）：
- Neurova 历史无 computer_call/tool 配对结构 → "成对删除"适配为
  "图片部件置空占位"，消息骨架与文本说明保留（轮次语义不丢）
- 不就地修改调用方列表（返回新列表，内部的 content 列表按需浅拷贝）

参考：trycua/cua `callbacks/image_retention.py`（最近 N 张 + 相邻项成对删除）。
"""

from typing import Any, Dict, List, Tuple

IMAGE_OMITTED_PLACEHOLDER = "[图片已省略——早于最近保留窗口，图片随当轮请求附上过]"


def _is_image_part(part: Dict[str, Any]) -> bool:
    return isinstance(part, dict) and part.get("type") == "image_url"


def count_images(messages: List[Dict[str, Any]]) -> int:
    """统计消息列表中的图片部件总数"""
    total = 0
    for msg in messages:
        content = msg.get("content") if isinstance(msg, dict) else None
        if isinstance(content, list):
            total += sum(1 for part in content if _is_image_part(part))
    return total


def apply_image_retention(
    messages: List[Dict[str, Any]], keep_last: int = 4
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """只保留最近 keep_last 条含图消息的图片部件，更早的置空占位。

    返回 (新消息列表, stats)。stats:
    - images_kept: 保留的图片部件数
    - images_removed: 置空的图片部件数
    - messages_touched: 被改写的消息数
    """
    stats = {"images_kept": 0, "images_removed": 0, "messages_touched": 0}

    # 自后向前找含图消息的索引，前 keep_last 条保留、其余置空
    image_message_indexes: List[int] = []
    for i, msg in enumerate(messages):
        content = msg.get("content") if isinstance(msg, dict) else None
        if isinstance(content, list) and any(_is_image_part(part) for part in content):
            image_message_indexes.append(i)

    keep_from = image_message_indexes[len(image_message_indexes) - max(int(keep_last), 0):] if image_message_indexes else []
    keep_set = set(keep_from)

    cleaned: List[Dict[str, Any]] = []
    for i, msg in enumerate(messages):
        content = msg.get("content") if isinstance(msg, dict) else None
        if not isinstance(content, list) or not any(_is_image_part(part) for part in content):
            # 纯文本消息 / 字符串 content：永不触碰
            cleaned.append(msg)
            continue
        # 含图消息：在保留窗口内原样保留，否则只摘除图片部件、文本保留
        new_content: List[Any] = []
        touched = False
        for part in content:
            if _is_image_part(part):
                if i in keep_set:
                    stats["images_kept"] += 1
                    new_content.append(part)
                    continue
                new_content.append({"type": "text", "text": IMAGE_OMITTED_PLACEHOLDER})
                stats["images_removed"] += 1
                touched = True
            else:
                new_content.append(part)
        if touched:
            stats["messages_touched"] += 1
        new_msg = dict(msg)
        new_msg["content"] = new_content
        cleaned.append(new_msg)
    return cleaned, stats
