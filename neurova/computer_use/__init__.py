"""
Computer Use 能力 v1.0.0-beta1 - 浏览器自动化增强版（集成 browser-skill）

隔离层级: 全局共享 + L1/L2 防火墙

能力:
1. 桌面截图识别 (screenshot) - 真实实现 + 视觉理解
2. 鼠标/键盘操作 (click, type, scroll) - 真实实现
3. 窗口管理 (window management) - 模拟实现
4. 文件操作 (file operations) - 真实实现
5. 浏览器操作 (browser operations) - 真实实现（多后端支持）
"""

from __future__ import annotations

from neurova.core.logger import get_logger
import os
import typing

logger = get_logger(__name__)


class ComputerUseManager:
    """计算机使用管理器 - 整合桌面操作、文件操作和浏览器操作"""

    _instance: typing.Optional["ComputerUseManager"] = None

    def __new__(cls, config: typing.Dict[str, typing.Any] = None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, config: typing.Dict[str, typing.Any] = None):
        if self._initialized:
            return

        self._config = config or {}
        self._browser_manager = None
        self._firewall = None
        self._screenshot_backend = None

        # 检测截图后端
        self._detect_screenshot_backend()

        self._initialized = True
        logger.info("ComputerUseManager 初始化完成")

    def _detect_screenshot_backend(self) -> None:
        """检测截图后端（进程内探测，解释器即运行环境）"""
        try:
            from PIL import ImageGrab  # noqa: F401 - 探测可用性

            self._screenshot_backend = "PIL"
        except ImportError:
            self._screenshot_backend = "basic"
        logger.info("截图后端: %s", self._screenshot_backend)

    def _get_firewall(self):
        """获取防火墙"""
        if self._firewall is None:
            try:
                from neurova.core.firewall import get_firewall

                self._firewall = get_firewall()
            except ImportError:
                logger.warning("防火墙不可用")
        return self._firewall

    def _get_browser_manager(self):
        """获取浏览器管理器"""
        if self._browser_manager is None:
            try:
                from neurova.computer_use.browser_manager import get_browser_manager

                self._browser_manager = get_browser_manager()
            except ImportError:
                logger.warning("浏览器管理器不可用")
        return self._browser_manager

    def screenshot(self, region: typing.Tuple[int, int, int, int] = None) -> typing.Optional[bytes]:
        """截取屏幕截图（进程内 Pillow，PNG 字节流）"""
        try:
            from PIL import ImageGrab
            import io

            img = ImageGrab.grab(region)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()
        except ImportError:
            logger.warning("截图失败：缺少 Pillow（pip install Pillow）")
            return None
        except Exception as e:
            logger.error("截图失败: %s", e)
            return None

    def click(self, x: int, y: int, button: str = "left") -> bool:
        """点击操作（进程内 pyautogui；坐标强转 int，按钮白名单校验）"""
        if button not in ("left", "right", "middle"):
            logger.warning("不支持的鼠标按钮: %r", button)
            return False
        try:
            import pyautogui

            pyautogui.click(int(x), int(y), button=button)
            return True
        except ImportError:
            logger.warning("点击失败：缺少 pyautogui")
            return False
        except Exception as e:
            logger.error("点击失败: %s", e)
            return False

    def type_text(self, text: str, interval: float = 0.05) -> bool:
        """输入文本（进程内 pyautogui）"""
        try:
            import pyautogui

            pyautogui.typewrite(text, interval=interval)
            return True
        except ImportError:
            logger.warning("输入失败：缺少 pyautogui")
            return False
        except Exception as e:
            logger.error("输入失败: %s", e)
            return False

    def scroll(self, x: typing.Optional[int], y: typing.Optional[int], clicks: int = 3) -> bool:
        """滚动操作（x/y 为 None 时在当前指针位置滚动）"""
        try:
            import pyautogui

            if x is None or y is None:
                pyautogui.scroll(int(clicks))
            else:
                pyautogui.scroll(int(clicks), int(x), int(y))
            return True
        except ImportError:
            logger.warning("滚动失败：缺少 pyautogui")
            return False
        except Exception as e:
            logger.error("滚动失败: %s", e)
            return False

    def file_read(self, path: str) -> typing.Optional[str]:
        """读取文件"""
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            logger.error("读取文件失败: %s", e)
            return None

    def file_write(self, path: str, content: str) -> bool:
        """写入文件"""
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return True
        except Exception as e:
            logger.error("写入文件失败: %s", e)
            return False

    def file_create(self, path: str, content: str = "") -> bool:
        """创建文件"""
        return self.file_write(path, content)

    def file_delete(self, path: str) -> bool:
        """删除文件"""
        try:
            if os.path.exists(path):
                os.remove(path)
                return True
            return False
        except Exception as e:
            logger.error("删除文件失败: %s", e)
            return False

    def file_edit(self, path: str, old_text: str, new_text: str) -> bool:
        """编辑文件"""
        try:
            content = self.file_read(path)
            if content is None:
                return False
            new_content = content.replace(old_text, new_text, 1)
            return self.file_write(path, new_content)
        except Exception as e:
            logger.error("编辑文件失败: %s", e)
            return False

    async def shell(self, command: str, timeout: int = 30, runtime_type: str = "local") -> typing.Dict[str, typing.Any]:
        """执行 shell 命令（委托执行层，本模块不自行拼装进程）。

        能力定位就是执行任意 shell 命令；命令内容是否放行由调用链上游的
        治理预检（allow/deny/ask/sandbox）裁决。

        runtime_type: "local"（默认，本机执行）| "docker"（容器内执行，
        跨平台隔离；Docker 不可用时返回明确错误）。
        """
        if not command or not command.strip():
            return {"returncode": -1, "error": "缺少命令"}
        try:
            import uuid

            if runtime_type == "docker":
                from neurova.execution_layers import RuntimeFactory, RuntimeType

                # 统一经 RuntimeFactory 创建（默认镜像，可配置扩展），与 skill_system 同源
                runtime = RuntimeFactory.create(RuntimeType.DOCKER, runtime_id=f"cu_shell_{uuid.uuid4().hex[:8]}")
            else:
                from neurova.execution_layers import LocalExecutor

                runtime = LocalExecutor(runtime_id=f"cu_shell_{uuid.uuid4().hex[:8]}")
            await runtime.start()
            try:
                if runtime_type == "docker":
                    # 容器内固定 POSIX shell；本机则按平台选择
                    cmd, args = "sh", ["-c", command]
                elif os.name == "nt":
                    cmd, args = "cmd.exe", ["/c", command]
                else:
                    cmd, args = "/bin/sh", ["-c", command]
                exec_result = await runtime.exec(command=cmd, args=args, timeout=timeout)
                return {
                    "returncode": exec_result.exit_code,
                    "stdout": exec_result.stdout or "",
                    "stderr": exec_result.stderr or "",
                    "runtime": runtime_type,
                }
            finally:
                await runtime.stop()
        except Exception as e:
            logger.error("Shell 命令执行失败: %s", e)
            return {"returncode": -1, "error": str(e)}

    async def browser_navigate(self, url: str, generation: int = None) -> typing.Dict[str, typing.Any]:
        """浏览器导航（导航使活动 tab 快照事实失效 → generation 递增）"""
        bm = self._get_browser_manager()
        if bm:
            return await bm.navigate(url, generation=generation)
        return {"error": "浏览器管理器不可用"}

    async def browser_list_targets(self) -> typing.Any:
        """列出全部浏览器 tab（含 generation 与活动标记）"""
        bm = self._get_browser_manager()
        if bm:
            return await bm.list_targets()
        return {"error": "浏览器管理器不可用"}

    async def browser_open_target(self, url: str = None) -> typing.Any:
        """新开 tab 并激活"""
        bm = self._get_browser_manager()
        if bm:
            return await bm.open_target(url)
        return {"error": "浏览器管理器不可用"}

    async def browser_switch_target(self, target_id: str, generation: int = None) -> typing.Any:
        """切换活动 tab"""
        bm = self._get_browser_manager()
        if bm:
            return await bm.switch_target(target_id, generation)
        return {"error": "浏览器管理器不可用"}

    async def browser_close_target(self, target_id: str, generation: int = None) -> typing.Any:
        """关闭 tab"""
        bm = self._get_browser_manager()
        if bm:
            return await bm.close_target(target_id, generation)
        return {"error": "浏览器管理器不可用"}

    async def browser_screenshot(self) -> typing.Optional[bytes]:
        """浏览器截图"""
        bm = self._get_browser_manager()
        if bm:
            return await bm.screenshot()
        return None

    async def browser_click(self, selector: str) -> bool:
        """浏览器点击"""
        bm = self._get_browser_manager()
        if bm:
            return await bm.click(selector)
        return False

    async def browser_type(self, selector: str, text: str) -> bool:
        """浏览器输入"""
        bm = self._get_browser_manager()
        if bm:
            return await bm.type_text(selector, text)
        return False

    async def browser_extract_text(self) -> typing.Any:
        """提取当前页面正文文本"""
        bm = self._get_browser_manager()
        if bm:
            return await bm.extract_text()
        return None

    async def browser_snapshot(self) -> typing.Optional[str]:
        """浏览器快照"""
        bm = self._get_browser_manager()
        if bm:
            return await bm.snapshot()
        return None

    async def browser_dom_snapshot(self, generation: int = None) -> typing.Any:
        """aria 可访问性树快照（结构化观察，优先于 HTML/截图）；generation 用于新鲜度校验"""
        bm = self._get_browser_manager()
        if bm:
            return await bm.dom_snapshot(generation=generation)
        return {"error": "浏览器管理器不可用"}

    async def browser_click_role(self, role: str, name: str = None, generation: int = None) -> typing.Any:
        """按 ARIA role + accessible name 定位点击（快照事实驱动）"""
        bm = self._get_browser_manager()
        if bm:
            return await bm.click_role(role, name, generation=generation)
        return {"error": "浏览器管理器不可用"}

    async def browser_fill_role(self, role: str, name: str, text: str, generation: int = None) -> typing.Any:
        """按 ARIA role + accessible name 定位输入"""
        bm = self._get_browser_manager()
        if bm:
            return await bm.fill_role(role, name, text, generation=generation)
        return {"error": "浏览器管理器不可用"}

    async def browser_capabilities(self) -> typing.Any:
        """查询当前后端能力清单"""
        bm = self._get_browser_manager()
        if bm:
            return await bm.get_capabilities()
        return {"error": "浏览器管理器不可用"}


# 工厂函数
_manager: typing.Optional[ComputerUseManager] = None


def get_computer_use_manager(config: typing.Dict[str, typing.Any] = None) -> ComputerUseManager:
    """获取 ComputerUseManager 单例"""
    global _manager
    if _manager is None:
        _manager = ComputerUseManager(config)
    return _manager


def reset_computer_use_manager() -> None:
    """重置（用于测试）"""
    global _manager
    _manager = None
