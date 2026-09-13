"""neurova-guest-agent 包（CUA Phase 3 扩展 RS-2）

来宾桌面动作守护进程：server（FastAPI，复用 actions.py/desktop_uia）+ client
（宿主 remote 后端调用）。控制面走 HTTP，与显示协议无关（立项书 §3 要点 1）。
"""

from neurova.guest_agent.client import GuestAgentClient
from neurova.guest_agent.server import DEFAULT_PORT, create_app

__all__ = ["GuestAgentClient", "create_app", "DEFAULT_PORT"]
