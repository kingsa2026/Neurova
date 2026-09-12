"""CUA simulated 评测台 harness（CUA 升级方案 R2-2，cua-bench 简化版）。

任务契约（cua-bench 四装饰器的简化翻译）：
- setup: 注入假桌面 HTML（fake_desktop.html 单页 + task 参数路由）
- solve: 走生产 PlaywrightBackend 的观察后行动协议（dom_snapshot → click_role/fill_role）
- evaluate: 读页面真实状态（window.* 标记）→ reward 0..1

零 VM 零 Docker，headless chromium 直跑进 CI——这是桌面/浏览器链路的
**行为级**回归护栏（断言 reward==1.0，不是"不崩"）。
"""

from pathlib import Path
from typing import Any, Callable, Dict, List

import pytest

from neurova.computer_use.browser_manager import PlaywrightBackend

_HTML_PATH = Path(__file__).parent / "fake_desktop.html"

PlaywrightBackend = pytest.importorskip(
    "neurova.computer_use.browser_manager", reason="browser_manager 不可用"
) and PlaywrightBackend


async def _read_html() -> str:
    import asyncio

    return await asyncio.to_thread(_HTML_PATH.read_text, "utf-8")


class FakeDesktop:
    """simulated 会话：一个 headless chromium 页面 + 按 task 注入的假桌面"""

    def __init__(self):
        self.backend: Any = None
        self.page: Any = None

    async def start(self) -> None:
        self.backend = PlaywrightBackend({"headless": True})
        if not await self.backend.initialize():
            pytest.skip("chromium 初始化失败（playwright install chromium）")
        self.page = self.backend._page
        await self.page.goto("about:blank")
        await self.page.set_content(await _read_html())

    async def load_task(self, task: str) -> None:
        """按 task 名重新注入页面（等价 cua-bench 的 setup_task）"""
        await self.page.goto(f"about:blank?task={task}")
        await self.page.set_content((await _read_html()).replace(
            'new URLSearchParams(location.search).get("task")',
            f'"{task}"',
        ))
        assert await self.page.evaluate("window.__ready === true")

    async def evaluate(self, expression: str) -> Any:
        return await self.page.evaluate(expression)

    async def stop(self) -> None:
        if self.backend:
            try:
                await self.backend.close()
            except Exception:
                pass


async def _solve_click_button(backend: PlaywrightBackend) -> None:
    """生产协议：先快照拿事实，再 role 定位点击"""
    snap = await backend.dom_snapshot()
    assert snap.success, f"快照失败: {snap.error}"
    result = await backend.click_role("button", "确认订单", generation=snap.generation)
    assert result.success, f"点击失败: {result.error}"


async def _evaluate_click_button(desktop: FakeDesktop) -> float:
    confirmed = await desktop.evaluate("window.__confirmed === true")
    return 1.0 if confirmed else 0.0


async def _solve_form_fill(backend: PlaywrightBackend) -> None:
    snap = await backend.dom_snapshot()
    assert snap.success
    fill = await backend.fill_role("textbox", "用户名", "neurova", generation=snap.generation)
    assert fill.success, f"填写失败: {fill.error}"
    click = await backend.click_role("button", "提交", generation=fill.generation)
    assert click.success, f"提交失败: {click.error}"


async def _evaluate_form_fill(desktop: FakeDesktop) -> float:
    submitted = await desktop.evaluate("window.__submitted === true")
    username = await desktop.evaluate("window.__username")
    reward = 0.0
    if submitted:
        reward += 0.5
    if username == "neurova":
        reward += 0.5
    return reward


async def _solve_snapshot_budget(backend: PlaywrightBackend) -> Dict[str, Any]:
    """R1-5 观察预算：显式调大才放大，默认硬顶"""
    full = await backend.dom_snapshot()
    assert full.success
    budgeted = await backend.dom_snapshot(max_nodes=8)
    assert budgeted.success
    return {"full_lines": len(str(full.data).splitlines()), "budgeted": budgeted}


async def _evaluate_snapshot_budget(desktop: FakeDesktop, solve_result: Dict[str, Any]) -> float:
    budgeted_lines = len(str(solve_result["budgeted"].data).splitlines())
    # 30 个按钮的树裁到 8 行以内，且确实比全量少
    if budgeted_lines <= 8 and budgeted_lines < solve_result["full_lines"]:
        return 1.0
    return 0.0


TASKS: List[Dict[str, Any]] = [
    {
        "name": "click-button",
        "solve": _solve_click_button,
        "evaluate": _evaluate_click_button,
        "solve_result": False,
    },
    {
        "name": "form-fill",
        "solve": _solve_form_fill,
        "evaluate": _evaluate_form_fill,
        "solve_result": False,
    },
    {
        "name": "snapshot-budget",
        "solve": _solve_snapshot_budget,
        "evaluate": _evaluate_snapshot_budget,
        "solve_result": True,
    },
]
