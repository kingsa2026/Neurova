"""SSH 远程命令执行器（Linux/macOS 远程 = SSH 命令，无 GUI）

paramiko 惰性导入（未装不影响模块 import；client_factory 注入便于无依赖单测）。
key 与 password 两种认证都支持：优先 key_text（粘贴私钥），其次 key_path，再次 password，
都无则走系统 agent/默认密钥。

安全（U1，弃 AutoAddPolicy 的 TOFU）：host key 一律严格校验（无旁路）——首连由
UnknownHostKeyPolicy 抛 HostKeyConfirmationNeeded（携带公钥 SHA256
指纹），上层弹主机确认卡征求用户；用户确认后经 SshHostStore 落库
（data/<agent_id>/ssh_known_hosts.json）并重连。已确认主机：指纹一致放行；指纹变化抛
HostKeyMismatchError（fail-closed + 审计 HIGH）。

失败相位（U3）：连接失败/认证失败/超时且零输出 → RemoteNotExecutedError
（executed=False、retryable=True、phase=connect|auth|timeout）；已获部分输出后中断 →
executed="unknown"、retryable=False（不可盲目重试）。上层据此映射结构化错误载荷。
"""

from __future__ import annotations

import io
import os
import socket
from typing import Any, Callable, Dict, Optional, Tuple

from neurova.core.logger import get_logger

logger = get_logger(__name__)

class HostKeyConfirmationNeeded(Exception):
    """首连主机的公钥尚未经用户确认（fail-closed 的控制流中断，非故障）。

    上层（tool_executor ssh 分支）捕获后弹主机确认卡；用户确认 →
    SshHostStore.mark_confirmed 落库 → 原地重连。fingerprint 为
    OpenSSH 风格 SHA256 指纹（publicKeyFingerprint 口径）。
    """

    def __init__(self, fingerprint: str, *, host: str, port: int, key_type: str = ""):
        self.fingerprint = fingerprint
        self.host = host
        self.port = int(port)
        self.key_type = key_type
        super().__init__(
            f"主机 {host}:{port} 的公钥（{key_type or '未知类型'}，指纹 {fingerprint}）"
            f"尚未确认，已按 fail-closed 拒绝连接")


class HostKeyMismatchError(Exception):
    """服务端公钥与已确认记录不一致：疑似中间人/主机重装，fail-closed 拒连。"""

    def __init__(self, fingerprint: str, *, stored_fingerprint: str,
                 host: str, port: int):
        self.fingerprint = fingerprint
        self.stored_fingerprint = stored_fingerprint
        self.host = host
        self.port = int(port)
        super().__init__(
            f"主机 {host}:{port} 的公钥与已确认记录不一致"
            f"（现 {fingerprint}，原 {stored_fingerprint}），已拒绝连接")


class RemoteNotExecutedError(Exception):
    """命令未在远端执行（或执行状态未知）的结构化失败（U3 相位追踪）。

    phase: connect | auth | timeout | exec；
    executed: False（确认未执行）| "unknown"（已获部分输出后中断）；
    retryable: 是否可安全重试（executed="unknown" 时恒为 False）。
    """

    def __init__(self, message: str, *, phase: str, retryable: bool = True,
                 executed: Any = False):
        self.phase = phase
        self.retryable = retryable
        self.executed = executed
        super().__init__(message)


def _load_pkey(key_text: str):
    """从私钥文本构造 paramiko PKey（依次尝试常见类型）。"""
    import paramiko

    for factory in (
        paramiko.RSAKey,
        paramiko.Ed25519Key,
        paramiko.ECDSAKey,
        paramiko.DSSKey,
    ):
        try:
            return factory.from_private_key(io.StringIO(key_text))
        except Exception:  # noqa: BLE001 - 类型不符，试下一种
            continue
    raise ValueError("无法解析私钥（不支持的类型或已加密需 passphrase）")


class UnknownHostKeyPolicy:
    """主机密钥裁决策略（替代 AutoAddPolicy 的 TOFU）。

    本仓不从系统 known_hosts 预载，paramiko 对每台主机都会回调 missing_host_key，
    故"未确认 / 已确认匹配 / 指纹变化"三种裁决都收在这一个钩子里：
    - 库中无记录 → 暂存新指纹（不写库），抛 HostKeyConfirmationNeeded 待用户确认；
    - 有记录且指纹一致 → 放行（接受该 key，连接继续）；
    - 有记录但指纹变化 → HostKeyMismatchError（fail-closed）+ 审计 HIGH。
    """

    def __init__(self, store: Any, agent_id: str, host: str, port: int):
        self._store = store
        self._agent_id = agent_id or ""
        self._host = host
        self._port = int(port)
        # 待确认指纹（抛 HostKeyConfirmationNeeded 前暂存，供上层展示/确认后写库）
        self.pendingFingerprint: Optional[str] = None
        self.pendingKeyType: Optional[str] = None

    def missing_host_key(self, client: Any, hostname: str, key: Any) -> None:
        from neurova.security.ssh_host_store import publicKeyFingerprint

        fingerprint = publicKeyFingerprint(key)
        entry = None
        if self._store is not None:
            entry = self._store.lookup(self._agent_id, self._host, self._port)
        if entry is None:
            self.pendingFingerprint = fingerprint
            self.pendingKeyType = key.get_name()
            raise HostKeyConfirmationNeeded(
                fingerprint, host=self._host, port=self._port, key_type=key.get_name())
        if self._store.is_mismatch(self._agent_id, self._host, self._port, fingerprint):
            self._auditMismatch(fingerprint, entry)
            raise HostKeyMismatchError(
                fingerprint, stored_fingerprint=entry.get("key_fingerprint") or "",
                host=self._host, port=self._port)
        # 指纹一致：放行（不写库——库只收用户确认的记录）

    def _auditMismatch(self, fingerprint: str, entry: Dict[str, Any]) -> None:
        """指纹变化 = 疑似中间人/重装，审计 HIGH 留痕（失败不掩盖 mismatch 本身）。"""
        try:
            from neurova.security.audit_logger import AuditEventType, AuditSeverity, log_audit

            log_audit(
                AuditEventType.CONFIG_CHANGE, AuditSeverity.HIGH,
                user_id=self._agent_id,
                action=(f"SSH 主机公钥变化（fail-closed 拒连）：{self._host}:{self._port} "
                        f"原指纹 {entry.get('key_fingerprint')}，现指纹 {fingerprint}"),
            )
        except Exception as e:  # noqa: BLE001
            logger.error("SSH 主机公钥变化审计记录失败: %s", e)


def _buildClient(*, store: Any, agent_id: str, host: str, port: int,
                 client_factory: Optional[Callable[[], Any]] = None) -> Tuple[Any, Any]:
    """建 SSH 客户端并装配主机密钥策略。返回 (client, policy)。

    client_factory 注入（测试/部署桩）时跳过策略装配。主机密钥一律走
    UnknownHostKeyPolicy（TOFU + 指纹确认 + 变更 fail-closed）——CodeQL
    py/paramiko-missing-host-key-validation：AutoAddPolicy 的兼容旁路已退役，
    不再存在「接受任意主机密钥」的代码路径。
    """
    if client_factory is not None:
        return client_factory(), None
    import paramiko

    client = paramiko.SSHClient()
    policy = UnknownHostKeyPolicy(store, agent_id, host, port)
    client.set_missing_host_key_policy(policy)
    return client, policy


def _classifyConnectFailure(e: Exception, user: Optional[str], host: str) -> RemoteNotExecutedError:
    """连接期失败 → 相位化 RemoteNotExecutedError（executed=False、retryable=True）。"""
    import paramiko

    if isinstance(e, paramiko.AuthenticationException):
        return RemoteNotExecutedError(
            f"SSH 认证失败（{user or '?'}@{host}）: {e}", phase="auth")
    if isinstance(e, (socket.timeout, TimeoutError)):
        return RemoteNotExecutedError(f"SSH 连接超时: {e}", phase="timeout")
    if isinstance(e, paramiko.SSHException) and "timeout" in str(e).lower():
        return RemoteNotExecutedError(f"SSH 连接超时: {e}", phase="timeout")
    return RemoteNotExecutedError(f"SSH 连接失败: {e}", phase="connect")


def _classifyExecFailure(e: Exception, outBytes: bytes, errBytes: bytes) -> RemoteNotExecutedError:
    """执行期失败：已获部分输出 → executed="unknown" 不可盲目重试；零输出 → 判未执行。"""
    if outBytes or errBytes:
        return RemoteNotExecutedError(
            f"SSH 命令执行中断（已获部分输出，不可盲目重试）: {e}",
            phase="exec", retryable=False, executed="unknown")
    if isinstance(e, (socket.timeout, TimeoutError)):
        return RemoteNotExecutedError(f"SSH 命令执行超时（零输出）: {e}", phase="timeout")
    return RemoteNotExecutedError(
        f"SSH 命令执行失败（零输出，判定未执行）: {e}", phase="exec")


def run_ssh_command(
    host: str,
    command: str,
    *,
    user: Optional[str] = None,
    port: int = 22,
    key_path: Optional[str] = None,
    key_text: Optional[str] = None,
    password: Optional[str] = None,
    timeout: float = 60.0,
    client_factory: Optional[Callable[[], Any]] = None,
    agent_id: str = "",
    host_key_store: Any = None,
) -> Dict[str, Any]:
    """在 host 上经 SSH 执行 command，返回 {returncode, stdout, stderr}。

    认证优先级：key_text（粘贴私钥）> key_path（服务端私钥文件）> password > 系统 agent。
    client_factory 注入 paramiko-like 客户端（测试用）；默认惰性建 paramiko.SSHClient。

    主机密钥（U1）：一律严格校验（AutoAddPolicy 兼容旁路已退役）。显式传
    host_key_store 可强制指定信任锚（优先于单例）；未传时经 get_ssh_host_store()
    单例落库。连接/执行失败抛 RemoteNotExecutedError（相位化），主机密钥两类
    异常原样上抛给上层弹卡/拒连。
    """
    if not host:
        return {"returncode": -1, "stdout": "", "stderr": "缺少 host"}
    if not command:
        return {"returncode": -1, "stdout": "", "stderr": "缺少 command"}

    if host_key_store is not None:
        store = host_key_store
    else:
        from neurova.security.ssh_host_store import get_ssh_host_store

        store = get_ssh_host_store()

    try:
        client, _policy = _buildClient(store=store, agent_id=agent_id,
                                       host=host, port=port, client_factory=client_factory)
    except Exception as e:  # noqa: BLE001
        return {"returncode": -1, "stdout": "", "stderr": f"SSH 客户端构建失败: {e}"}

    connect_kwargs: Dict[str, Any] = {"hostname": host, "port": port, "timeout": timeout}
    if user:
        connect_kwargs["username"] = user
    try:
        if key_text:
            connect_kwargs["pkey"] = _load_pkey(key_text)
        elif key_path:
            connect_kwargs["key_filename"] = key_path
        elif password:
            connect_kwargs["password"] = password
    except Exception as e:  # noqa: BLE001 - 私钥解析失败结构化返回
        return {"returncode": -1, "stdout": "", "stderr": f"私钥解析失败: {e}"}

    try:
        client.connect(**connect_kwargs)
    except (HostKeyConfirmationNeeded, HostKeyMismatchError):
        raise  # 主机密钥裁决结果原样上抛（上层弹确认卡 / fail-closed 拒连）
    except Exception as e:  # noqa: BLE001 - 相位化（connect/auth/timeout）
        raise _classifyConnectFailure(e, user, host) from e

    outBytes = b""
    errBytes = b""
    try:
        _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
        outBytes = stdout.read()
        errBytes = stderr.read()
        rc = stdout.channel.recv_exit_status()
        return {"returncode": rc,
                "stdout": outBytes.decode("utf-8", "replace"),
                "stderr": errBytes.decode("utf-8", "replace")}
    except (HostKeyConfirmationNeeded, HostKeyMismatchError):
        raise
    except Exception as e:  # noqa: BLE001 - 相位化（部分输出=不可盲重试 / 零输出=未执行）
        raise _classifyExecFailure(e, outBytes, errBytes) from e
    finally:
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass


def resolve_ssh_credentials(user_id: str, host: str) -> Dict[str, Any]:
    """从凭据分桶取该用户对该 host 的 SSH 连接参数（多主机按 host 分键）。缺省返回空 dict。"""
    try:
        from neurova.web_reach.credentials import get_credential_store

        cfg = get_credential_store().get_ssh_host(user_id, host) or {}
        return {
            "user": cfg.get("user") or None,
            "port": int(cfg.get("port") or 22),
            "key_text": cfg.get("key_text") or None,
            "password": cfg.get("password") or None,
        }
    except Exception:  # noqa: BLE001
        return {}
