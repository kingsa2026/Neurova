"""Windows Sandbox 会话提供者（CUA Phase 3 扩展 RS-1，Windows 宿主一次性桌面）

生成 .wsb 配置（挂载 guest agent 启动命令 + 共享目录），经 WindowsSandbox.Client
拉起一次性隔离桌面，返回指向来宾 guest agent 的 DesktopSession。用完即毁（Sandbox
天然全重置）。

真机拉起依赖 Win Pro + 虚拟化，本模块把**可机械验证的部分**（wsb XML 生成、端口/
token 注入、生命周期状态机）做实；subprocess 启动器可注入，真实 sandbox.exe 拉起
留待人工真机验收（立项书 RS-1 验收判据）。
"""

from __future__ import annotations

import secrets
import subprocess
from typing import Any, Callable, Dict, Optional

from neurova.core.logger import get_logger
from neurova.computer_use.session_pool import DesktopSession, SessionProvider

logger = get_logger(__name__)

DEFAULT_GUEST_PORT = 8765

_WSB_TEMPLATE = """<Configuration>
  <VGpu>Disable</VGpu>
  <Networking>Enable</Networking>
  <MappedFolders>
    <MappedFolder>
      <HostFolder>{shared_dir}</HostFolder>
      <SandboxFolder>C:\\NeurovaGuest</SandboxFolder>
      <ReadOnly>true</ReadOnly>
    </MappedFolder>
  </MappedFolders>
  <LogonCommands>
    <SynchronousCommand LogonCommand="true">
      <CommandLine>cmd /c start /min python C:\\NeurovaGuest\\run_guest_agent.py --port {port} --token {token}</CommandLine>
    </SynchronousCommand>
  </LogonCommands>
</Configuration>
"""


class WindowsSandboxProvider(SessionProvider):
    """Windows Sandbox 一次性桌面提供者。"""

    def __init__(
        self,
        *,
        guest_port: int = DEFAULT_GUEST_PORT,
        shared_dir: str = "C:\\NeurovaGuest",
        sandbox_exe: str = "C:\\Windows\\System32\\WindowsSandbox.Client.exe",
        runner: Optional[Callable[..., Any]] = None,
    ):
        self._port = guest_port
        self._shared_dir = shared_dir
        self._exe = sandbox_exe
        # runner 注入：默认 subprocess.Popen，测试用假 runner
        self._runner = runner or subprocess.Popen
        self._procs: Dict[str, Any] = {}

    def build_wsb(self, token: str) -> str:
        """生成 .wsb 配置文本（确定性，供测试与落盘）。"""
        return _WSB_TEMPLATE.format(shared_dir=self._shared_dir, port=self._port, token=token)

    def create(self, user_id: str) -> DesktopSession:
        token = secrets.token_urlsafe(16)
        wsb = self.build_wsb(token)
        name = f"neurova-guest-{user_id}-{secrets.token_hex(3)}"
        # 真实环境：写 wsb 文件 + 拉起 sandbox；此处经注入 runner 执行
        try:
            proc = self._launch(name, wsb)
        except Exception as e:  # noqa: BLE001
            logger.warning("Windows Sandbox 拉起失败（user=%s）: %s", user_id, e)
            raise
        sid = name
        self._procs[sid] = proc
        return DesktopSession(
            session_id=sid,
            base_url=f"http://127.0.0.1:{self._port}",
            token=token,
            user_id=user_id,
        )

    def _launch(self, name: str, wsb: str) -> Any:
        # 落盘 wsb 并拉起（runner 可注入以便测试）
        import tempfile
        import os

        path = os.path.join(tempfile.gettempdir(), f"{name}.wsb")
        with open(path, "w", encoding="utf-8") as f:
            f.write(wsb)
        return self._runner([self._exe, path])

    def destroy(self, session: DesktopSession) -> None:
        proc = self._procs.pop(session.session_id, None)
        if proc is not None and hasattr(proc, "terminate"):
            try:
                proc.terminate()
            except Exception as e:  # noqa: BLE001
                logger.debug("sandbox 终止失败（忽略）: %s", e)
