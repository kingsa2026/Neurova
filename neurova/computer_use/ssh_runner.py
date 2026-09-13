"""SSH 远程命令执行器（Linux/macOS 远程 = SSH 命令，无 GUI）

paramiko 惰性导入（未装不影响模块 import；client_factory 注入便于无依赖单测）。
key 与 password 两种认证都支持：优先 key_path，其次 password，都无则走系统 agent/默认密钥。

安全：exec_command 直接传命令串给远端 shell（远端本就该有该用户的执行权）；本机侧
零 shell 注入面（不拼本地命令行）。host key 策略默认 AutoAdd（自动化友好），可经
policy 参数收紧为 RejectPolicy + known_hosts。
"""

from __future__ import annotations

import io
from typing import Any, Callable, Dict, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)


def _load_pkey(key_text: str):
    """从私钥文本构造 paramiko PKey（依次尝试常见类型）。"""
    import paramiko

    for factory in (
        paramiko.RSAKey,
        paramiko.Ed255519Key,
        paramiko.ECDSAKey,
        paramiko.DSSKey,
    ):
        try:
            return factory.from_private_key(io.StringIO(key_text))
        except Exception:  # noqa: BLE001 - 类型不符，试下一种
            continue
    raise ValueError("无法解析私钥（不支持的类型或已加密需 passphrase）")


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
) -> Dict[str, Any]:
    """在 host 上经 SSH 执行 command，返回 {returncode, stdout, stderr}。

    认证优先级：key_text（粘贴私钥）> key_path（服务端私钥文件）> password > 系统 agent。
    client_factory 注入 paramiko-like 客户端（测试用）；默认惰性建 paramiko.SSHClient。
    """
    if not host:
        return {"returncode": -1, "stdout": "", "stderr": "缺少 host"}
    if not command:
        return {"returncode": -1, "stdout": "", "stderr": "缺少 command"}

    if client_factory is None:
        import paramiko  # 惰性：无 paramiko 时仅在实际调用才报错

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    else:
        client = client_factory()

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
        _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        rc = stdout.channel.recv_exit_status()
        return {"returncode": rc, "stdout": out, "stderr": err}
    except Exception as e:  # noqa: BLE001 — SSH 失败回结构化，不抛给上层
        logger.warning("SSH 执行失败 %s@%s: %s", user, host, e)
        return {"returncode": -1, "stdout": "", "stderr": f"SSH 连接/执行失败: {e}"}
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
