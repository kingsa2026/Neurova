"""
MCP Bootstrap — 启动时按共享配置自动连接 MCP 服务器

流程: SharedConfigManager 读取 mcp_servers → 严格校验 → 逐个连接（enabled 才连）
→ 客户端注册进进程级表 → agent init_tools 时同步挂载到各自 ToolRouter。

设计约束:
- 单个 server 失败只记录、不阻断整体启动
- 连接失败也注册客户端（状态/失败原因可经 API 查询）
- 同一 client 实例可挂载到多个 agent 的 router（连接全局只建一次）
"""

import asyncio
from neurova.core.logger import get_logger
import typing

from neurova.tool_layers.mcp_client import MCPToolClient, peek_mcp_client
from neurova.tool_layers.mcp_config import validate_mcp_server_config

logger = get_logger(__name__)

_clients: typing.Dict[str, MCPToolClient] = {}
_bootstrapped: bool = False
_lock = asyncio.Lock()


async def bootstrap_mcp(config_manager: typing.Optional[typing.Any] = None) -> typing.Dict[str, bool]:
    """按共享配置连接所有 enabled 的 MCP 服务器。

    Args:
        config_manager: 可选的 SharedConfigManager，缺省用全局单例

    Returns:
        {server_id: 是否连接成功}（仅包含实际尝试连接的服务器）
    """
    global _bootstrapped

    async with _lock:
        if _bootstrapped:
            # 活会话只有一份：重复 bootstrap 会为同一 server 再建客户端并顶掉注册表里
            # 的那一条，被顶掉的会话既不重连也不关闭，是一次纯泄漏（且 _bootstrapped
            # 此前只写不读）。返回 {} 与 docstring 口径一致：只含实际尝试连接的服务器。
            logger.debug("MCP bootstrap 已完成，跳过重复连接")
            return {}

        if config_manager is None:
            from neurova.shared_config import get_shared_config_manager

            config_manager = get_shared_config_manager()

        results: typing.Dict[str, bool] = {}

        try:
            servers = config_manager.list_mcp_servers() or []
        except Exception as e:
            logger.warning("MCP bootstrap: 读取共享配置失败，跳过: %s", e)
            return results

        for server in servers:
            if not isinstance(server, dict):
                continue
            server_id = server.get("id")
            if not server_id or not server.get("enabled", True):
                continue

            try:
                cfg = validate_mcp_server_config(server)
            except ValueError as e:
                logger.warning("MCP bootstrap: %s 配置非法，跳过: %s", server_id, e)
                results[server_id] = False
                continue

            client = MCPToolClient()
            try:
                ok = await client.connect_server(server_id, cfg)
            except Exception as e:
                logger.warning("MCP bootstrap: %s 连接异常: %s", server_id, e)
                ok = False

            # 失败也注册：状态与失败原因保持可查询
            _clients[server_id] = client
            results[server_id] = ok
            if ok:
                logger.info("MCP bootstrap: %s 已连接", server_id)
            else:
                logger.warning(
                    "MCP bootstrap: %s 连接失败: %s", server_id, client.get_server_status(server_id)["last_error"]
                )

        _bootstrapped = True
        logger.info("MCP bootstrap 完成: %s", results)
        return results


def get_bootstrapped_clients() -> typing.Dict[str, MCPToolClient]:
    """返回已 bootstrap 的客户端表（只读副本）"""
    return dict(_clients)


def attach_bootstrapped_clients(router: typing.Any) -> int:
    """把已 bootstrap 的客户端挂载到 ToolRouter（同步、幂等），返回挂载数量"""
    count = 0
    for server_id, client in _clients.items():
        router.register_mcp_client(server_id, client)
        count += 1
    return count


def reset_bootstrap() -> None:
    """清空 bootstrap 状态（测试用）"""
    global _bootstrapped
    _clients.clear()
    _bootstrapped = False


async def shutdown_mcp() -> None:
    """关停所有 MCP 会话：bootstrap 注册表与进程单例两个发现口都要收。

    必须显式关，不能留给 anyio 取消兜底——stdio reader 阻塞在子进程管道上，取消不
    收敛，承载它的线程就永不退出（TestClient 退出 lifespan 时表现为 `thread.join()`
    卡死，生产侧表现为子进程与会话泄漏）。注册表逐条先摘后关：关停期间不再有
    消费者拿到一个已断开的客户端；复位 `_bootstrapped` 使同进程重启能重新连接。
    """
    global _bootstrapped

    for server_id in list(_clients.keys()):
        client = _clients.pop(server_id, None)
        if client is None:
            continue
        try:
            await client.disconnect_all()
        except Exception as e:  # noqa: BLE001 - 单个会话关停失败不阻断其余关停
            logger.warning("MCP 会话关停失败 %s: %s", server_id, e)

    _bootstrapped = False

    singleton = peek_mcp_client()
    if singleton is not None:
        try:
            await singleton.disconnect_all()
        except Exception as e:  # noqa: BLE001 - 同上
            logger.warning("MCP 进程单例会话关停失败: %s", e)
