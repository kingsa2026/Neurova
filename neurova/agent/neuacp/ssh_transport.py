# -*- coding: utf-8 -*-
"""SSH 远程传输（设计文档 §4.8，P2 卡 C1，transport=ssh）。

把名册的 ``transport="ssh"`` + ``remote={"host","port","user","key_ref"}``
落成 ``ssh -o BatchMode=yes -p <port> -i <key> <user>@<host> -- <原命令...>``
前缀命令：本机只拉起 ssh 客户端，ACP/插件进程在远端主机运行，stdio 经
SSH 隧道透传。

纪律：
- ``BatchMode=yes`` 固定带上（禁交互提示，缺凭据即失败，不卡会话）；
- ``key_ref`` 只透**引用名**（不落明文私钥/路径进名册）；实际私钥路径在
  spawn 时经 ``key_resolver`` 解析（默认读 os.environ），解析不到一律
  fail-closed 抛 :class:`NeuacpError`；
- ``--`` 之后的参数经 shlex.quote：OpenSSH 会把参数用空格拼接后交给远端
  shell 重新解析，不带引号的带空格参数（如插件形态的 ``--prompt <任务>``
  任务文本）会在远端被切碎。
"""
import os
import shlex
from typing import Callable, List, Optional

from neurova.agent.neuacp.acp_client import NeuacpError

#: 当前支持的传输形态（transport=http 待 ACP 远程 Streamable HTTP RFD 定稿后另立卡）。
SUPPORTED_TRANSPORTS = ("stdio", "ssh")

#: 固定批处理选项：禁交互提示（host key / 口令），凭据不齐直接失败。
BATCH_MODE_OPTION = "BatchMode=yes"

#: key_resolver 契约：key_ref（引用名）→ 私钥路径；无则返回 None。
KeyResolver = Callable[[str], Optional[str]]


def defaultSshKeyResolver(key_ref: str) -> Optional[str]:
    """默认凭据解析：os.environ 里 key_ref 指向的私钥路径（缺/空 → None）。"""
    value = os.environ.get(key_ref)
    if value is None:
        return None
    value = value.strip()
    return value or None


def resolveRemoteCommand(command, remote, key_resolver: Optional[KeyResolver] = None) -> List[str]:
    """把原命令包装成 ssh 前缀命令（fail-closed：缺 host/user/key 即抛错）。

    产出形态（顺序固定）：``["ssh", "-o", "BatchMode=yes", "-p", <port>,
    "-i", <key>, "<user>@<host>", "--", *原命令]``；port/key_ref 缺省时
    对应项省略。
    """
    parts = [str(part) for part in (command or [])]
    if not parts:
        raise NeuacpError("SSH 远程命令缺少原命令（command 为空，fail-closed）")
    if not isinstance(remote, dict):
        raise NeuacpError("transport=ssh 需要 remote 配置（host/user 等），fail-closed")
    host = str(remote.get("host") or "").strip()
    user = str(remote.get("user") or "").strip()
    if not host:
        raise NeuacpError("SSH remote 缺少 host（fail-closed）")
    if not user:
        raise NeuacpError("SSH remote 缺少 user（fail-closed）")

    prefix: List[str] = ["ssh", "-o", BATCH_MODE_OPTION]

    port = remote.get("port")
    if port is not None and str(port).strip() != "":
        try:
            port_value = int(str(port).strip())
        except ValueError:
            raise NeuacpError(f"SSH remote port 非法: {port!r}（fail-closed）") from None
        if port_value <= 0:
            raise NeuacpError(f"SSH remote port 必须为正整数: {port!r}（fail-closed）")
        prefix += ["-p", str(port_value)]

    key_ref = str(remote.get("key_ref") or "").strip()
    if key_ref:
        resolver = key_resolver if key_resolver is not None else defaultSshKeyResolver
        try:
            key_path = resolver(key_ref)
        except Exception as exc:
            raise NeuacpError(
                f"SSH 私钥解析失败（key_ref={key_ref!r}）: {exc}") from exc
        if not key_path or not str(key_path).strip():
            raise NeuacpError(
                f"SSH 私钥解析失败：key_ref={key_ref!r} 未解析到私钥路径（fail-closed，"
                "不带 -i 会退回非预期凭据）")
        prefix += ["-i", str(key_path)]

    prefix.append(f"{user}@{host}")
    prefix.append("--")
    # OpenSSH 把参数原样用空格拼接交给远端 shell：带空格/特殊字符的参数
    # 必须 quote，否则远端重新切分（插件形态 --prompt 任务文本首当其冲）。
    prefix.extend(shlex.quote(part) for part in parts)
    return prefix


#: 任务书（C1）对同一实现的称呼；单一事实源，不另写第二份包装逻辑。
wrapRemoteCommand = resolveRemoteCommand


def resolveSpawnCommand(command, transport: str = "stdio", remote=None,
                        key_resolver: Optional[KeyResolver] = None) -> List[str]:
    """spawn 期统一漏斗：按 transport 产出实际拉起命令。

    stdio 原样返回（既有行为零变化）；ssh 走 resolveRemoteCommand 包装；
    其余 transport fail-closed（本卡只落地 stdio/ssh）。
    """
    transport_value = str(transport or "stdio")
    if transport_value == "stdio":
        return [str(part) for part in (command or [])]
    if transport_value == "ssh":
        return resolveRemoteCommand(command, remote, key_resolver)
    raise NeuacpError(
        f"不支持的 transport: {transport_value!r}（当前支持 stdio/ssh，fail-closed）")


def applyRemoteTransport(executor, transport, remote) -> None:
    """把名册 transport/remote 落到已构造执行体（swarm 透传入口）。

    NeuacpStdioExecutor 的构造参数面不收 transport/remote（acp_executor.py
    本卡禁改），且其 ``_ensureClient``/池 factory 会在 start 期重建底层
    ``NeuacpClient``——只改现成 ``_client`` 会被丢弃。故包一层实例的
    ``_newClient`` 工厂：此后**每一个**新建客户端（直启与池路径）都带上
    传输形态，ssh 包装仍在各客户端 spawn 时发生（私钥 spawn 期解析）。
    插件执行体（NeuacpPluginExecutor）直接走构造参数，不经此 helper。
    stdio 是缺省形态，直接返回（零行为变化）。
    """
    transport_value = str(transport or "stdio")
    if transport_value not in SUPPORTED_TRANSPORTS:
        raise NeuacpError(
            f"不支持的 transport: {transport_value!r}（当前支持 stdio/ssh，fail-closed）")
    if transport_value == "stdio":
        return
    newClient = getattr(executor, "_newClient", None)
    if not callable(newClient):
        raise NeuacpError(
            f"执行体不支持 transport={transport_value!r}（缺少底层客户端工厂，fail-closed）")
    remoteValue = remote if isinstance(remote, dict) else None
    if remoteValue is None:
        raise NeuacpError("transport=ssh 需要 remote 配置（host/user 等，fail-closed）")

    def newClientWithTransport():
        client = newClient()
        client.setTransport(transport_value, remoteValue)
        return client

    executor._newClient = newClientWithTransport
    # 现成客户端同步补设（装配期必为未启动件，可安全变更；start 期会被
    # 包装工厂新建的客户端替换，两处状态保持一致便于观测）。
    currentClient = getattr(executor, "_client", None)
    if currentClient is not None:
        currentClient.setTransport(transport_value, remoteValue)
