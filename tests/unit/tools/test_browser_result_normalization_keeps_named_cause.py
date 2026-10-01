# -*- coding: utf-8 -*-
"""`_normalize_browser_result` 不得把产出侧的具名原因抹成"格式未知"。

## 为什么这条值得常驻

函数开头有一段专门处理 dict 形态的分支，但它落到最后会被 `else` 分支覆盖：
dict 没有 `to_dict()`，于是**任何** dict 输入最终都变成
`{"success": False, "error": "浏览器返回格式未知"}`。实测（改前）：

    _normalize_browser_result({"error": "浏览器管理器不可用"})
      → {'success': False, 'error': '浏览器返回格式未知'}
    _normalize_browser_result({"success": True, "data": "x", "image_base64": "AAA"})
      → {'success': False, 'error': '浏览器返回格式未知'}

两个后果都命中本工单集的教义：

1. 与 T-13 同源的诚实缺陷——`ComputerUseManager` 在浏览器管理器缺席时返回的正是
   `{"error": "浏览器管理器不可用"}` 这种 dict，模型拿到的是"格式未知"，
   真实原因在这最后一跳被吃掉；
2. 成功读数被翻成失败——`{"success": True, ...}` 同输入同结果，任何走 dict 形态的
   后端（含 `execute()` 的 dict 返回）都会被误判为失败。

T-09（截图进模型上下文）要用的正是这条函数所在的那一跳，所以先把"原因被吞、成功被翻"
这两处修掉：**修的是遮蔽，不是那层有意丢大对象的保护**——后者由反向锁钉住，
接 T-09 必须走请求级旁路而不是取消 pop。
"""

from neurova.tool_executor import ToolExecutor as _ToolExecutor


def test_dictErrorKeepsTheProducerReason():
    got = _ToolExecutor._normalize_browser_result({"error": "浏览器管理器不可用"})
    assert got["success"] is False, got
    assert "浏览器管理器不可用" in str(got.get("error")), (
        f"产出侧的具名原因被抹掉了，模型只能瞎猜：{got}")
    assert "格式未知" not in str(got.get("error")), got


def test_dictSuccessIsNotFlippedIntoFailure():
    got = _ToolExecutor._normalize_browser_result({"success": True, "data": "页面正文"})
    assert got["success"] is True, f"成功读数被 normalize 这一跳翻成失败：{got}"
    assert got.get("data") == "页面正文", got


def test_dictImageIsStillKeptOutOfTheLlmFacingDict():
    """反向锁：丢 base64 是这条函数**有意**的防膨胀契约，不是缺陷。

    截图进模型上下文走的是请求级旁路（`chat_pipeline` 那条：base64 只挂当轮请求、
    绝不入历史），不是把大对象塞回工具结果 dict。谁哪天想靠"取消 pop"来接 T-09，
    这一条会先红——那正是 2026-09-09 图片串台事故的形状。
    """
    got = _ToolExecutor._normalize_browser_result(
        {"success": True, "data": "x", "image_base64": "AAAA"})
    assert "image_base64" not in got, f"大对象又回到模型可见面：{sorted(got)}"
    assert got.get("has_image") is True, (
        "图被摘掉后必须留下可判定的痕迹，否则感知门连『要不要给图』都无从决定")
