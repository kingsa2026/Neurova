"""档三：agent 代部署自建中继（SSH 上机执行，2026-11-19 拍板立项）。

用户在配对面板填「服务器地址 + SSH 凭据」，后端代为完成档二的手工部署：
建专用账号 → 上传中继最小文件集 → 装 venv 依赖 → 生成/复用准入令牌 →
写 systemd 单元并启动 → 自检。成功后**自动**把连接方式切到 relay
（relay_url/准入令牌一并回填），用户无需再手填。

安全边界（核心原则第 9 条「涉及用户资产必须显式确认」的落地）：
- 仅 admin 可触发；触发即确认（面板明示 agent 将以所给凭据登录服务器执行安装）；
- 凭据经 web_reach 凭据库加密落盘（只写不读），任务视图与日志不落全文；
- 部署步骤幂等（重复执行=更新；服务器上已有准入令牌则复用，不换令牌）；
- 全程审计留痕（CONFIG_CHANGE/HIGH）；提供 remote-undeploy 撤销；
- 主机密钥严格校验与 computer_ssh_exec 同源（U1：弃 AutoAddPolicy，部署目标
  首连同样须经 known_hosts 确认，指纹变化 fail-closed 拒连）；
- 部署包源（systemd 单元模板 + 最小文件集清单）以 `deploy/relay-systemd/`
  为唯一出处，本模块就地读取，不另抄第二份。
"""
from __future__ import annotations

import asyncio
import base64
import re
import secrets
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from neurova.computer_use.ssh_runner import _load_pkey
from neurova.core.logger import get_logger
from neurova.security.audit_logger import AuditEventType, AuditSeverity, log_audit

logger = get_logger(__name__)

#: 部署任务注册表（admin 低频操作，不设上限；凭据不入内）。
_TASKS: Dict[str, Dict[str, Any]] = {}
_TASKS_LOCK = threading.RLock()

#: SSH 客户端工厂（测试注入假客户端；默认 None = 用真 paramiko）。
_sshClientFactory: Optional[Callable[[], Any]] = None

#: 部署用的远端固定路径（与 deploy/relay-systemd/install.sh 同一口径）。
REMOTE_LIB_DIR = "/opt/neurova-relay/lib"
REMOTE_VENV_DIR = "/opt/neurova-relay/venv"
REMOTE_CONFIG_DIR = "/etc/neurova-relay"
REMOTE_SERVICE_USER = "neurova-relay"
REMOTE_SERVICE_NAME = "neurova-relay"


def setSshClientFactory(factory: Optional[Callable[[], Any]]) -> None:
    """注入 SSH 客户端工厂（测试用）；None = 回到真 paramiko。"""
    global _sshClientFactory
    _sshClientFactory = factory


def _repoRoot() -> Path:
    return Path(__file__).resolve().parents[2]


def _relayFiles() -> List[str]:
    """中继运行的最小文件集——**唯一出处**是 install.sh 的 RELAY_FILES 清单，
    这里就地解析，不另抄一份（教义第 6 条）。"""
    text = (_repoRoot() / "deploy" / "relay-systemd" / "install.sh").read_text(encoding="utf-8")
    block = re.search(r"RELAY_FILES=\(([^)]*)\)", text, re.S)
    if not block:
        raise ValueError("install.sh 里找不到 RELAY_FILES 清单——部署包结构变了，请同步本模块")
    return [item.strip('"') for item in re.findall(r'"([^"]+)"', block.group(1))]


def _unitTemplate() -> str:
    return (_repoRoot() / "deploy" / "relay-systemd" / "neurova-relay.service").read_text(
        encoding="utf-8")


class _SshSession:
    """一条 SSH 连接：跑命令 + base64 写文件（免 SFTP，走同一条代码路径）。"""

    def __init__(self, *, host: str, port: int, username: str,
                 password: Optional[str], key_text: Optional[str]):
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._key_text = key_text
        self._client = None
        self._hostKeyPolicy = None

    def connect(self) -> None:
        if _sshClientFactory is not None:
            self._client = _sshClientFactory()
            return
        from neurova.computer_use.ssh_runner import _buildClient, strictHostKeyEnabled
        from neurova.security.ssh_host_store import get_ssh_host_store

        # U1：部署目标也是主机——与 computer_ssh_exec 共用同一 known_hosts 信任锚
        # （NEUROVA_SSH_STRICT_HOSTKEY 同源开关；部署是 admin 全局操作，记 default 桶）。
        # 首连未确认 → HostKeyConfirmationNeeded 上抛（任务失败并提示指纹）；
        # 指纹变化 → HostKeyMismatchError fail-closed（审计 HIGH 已在策略内落）。
        strict = strictHostKeyEnabled()
        store = get_ssh_host_store() if strict else None
        self._client, self._hostKeyPolicy = _buildClient(
            strict=strict, store=store, agent_id="", host=self._host, port=self._port)
        kwargs: Dict[str, Any] = {"hostname": self._host, "port": self._port,
                                  "timeout": 30.0, "username": self._username}
        if self._key_text:
            kwargs["pkey"] = _load_pkey(self._key_text)
        elif self._password:
            kwargs["password"] = self._password
        self._client.connect(**kwargs)

    def run(self, command: str, timeout: float = 900.0) -> Dict[str, Any]:
        _stdin, stdout, stderr = self._client.exec_command(command, timeout=timeout)
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        rc = stdout.channel.recv_exit_status()
        return {"returncode": rc, "stdout": out, "stderr": err}

    def writeText(self, remotePath: str, text: str) -> None:
        """远端写文本文件：内容走 base64（免引号/转义问题），服务器端 base64 -d 落盘。"""
        payload = base64.b64encode(text.encode("utf-8")).decode("ascii")
        result = self.run(f"echo '{payload}' | base64 -d > '{remotePath}'")
        if result["returncode"] != 0:
            raise RuntimeError(f"写入 {remotePath} 失败: {result['stderr'][:200]}")

    def close(self) -> None:
        try:
            if self._client is not None:
                self._client.close()
        except Exception:  # noqa: BLE001 - 收尾不外泄
            pass


def _validateParams(params: Dict[str, Any]) -> None:
    host = str(params.get("host") or "").strip()
    username = str(params.get("username") or "").strip()
    password = str(params.get("password") or "").strip()
    keyText = str(params.get("key_text") or "").strip()
    # 0 是合法端点值的边界（0 端口必须报错，不能被 `or 默认值` 吞掉）
    sshPortRaw = params.get("ssh_port")
    relayPortRaw = params.get("relay_port")
    sshPort = int(sshPortRaw) if sshPortRaw is not None else 22
    relayPort = int(relayPortRaw) if relayPortRaw is not None else 8443
    if not host:
        raise ValueError("host 不能为空（服务器 IP/域名）")
    if not username:
        raise ValueError("username 不能为空")
    if not password and not keyText:
        raise ValueError("必须提供 SSH 凭据（password 或 key_text 之一）")
    if not (1 <= sshPort <= 65535) or not (1 <= relayPort <= 65535):
        raise ValueError("ssh_port / relay_port 必须在 1-65535")
    tlsCert = str(params.get("tls_cert") or "").strip()
    tlsKey = str(params.get("tls_key") or "").strip()
    if bool(tlsCert) != bool(tlsKey):
        raise ValueError("tls_cert 与 tls_key 必须成对提供")


def startRemoteDeploy(userId: str, params: Dict[str, Any],
                      loop: Optional[asyncio.AbstractEventLoop] = None) -> Dict[str, Any]:
    """校验 → 凭据加密落盘 → 起后台部署线程。返回 {"task_id": ...}。

    `loop` 是 API 侧的运行中事件循环：部署线程完成后经它把连接方式切到 relay
    并重建出站 agent（跨线程调度）。直接调用（测试/无循环）时只落配置，
    agent 重建交给下一次配置读写。
    """
    _validateParams(params)
    host = str(params["host"]).strip()
    userId = str(userId or "")

    # 凭据加密落盘（只写；之后 undeploy 可按 host 复用，不必重输）
    from neurova.web_reach import credentials as _credentials

    _credentials.get_credential_store().set_ssh_host(
        userId, host,
        user=str(params.get("username") or "root"),
        port=int(params.get("ssh_port") or 22),
        key_text=str(params.get("key_text") or ""),
        password=str(params.get("password") or ""),
    )

    taskId = "deploy-" + uuid.uuid4().hex[:12]
    with _TASKS_LOCK:
        _TASKS[taskId] = {
            "task_id": taskId,
            "state": "running",
            "steps": [],
            "relay_url": "",
            "enrollment_token_masked": "",
            "error": "",
            "started_at": time.time(),
            "finished_at": None,
        }
    log_audit(AuditEventType.CONFIG_CHANGE, AuditSeverity.HIGH, user_id=userId,
              action=f"发起自建中继远程部署（host={host}）")

    thread = threading.Thread(target=_executeDeploy,
                              args=(taskId, userId, dict(params), loop),
                              daemon=True, name=f"relay-deploy-{taskId}")
    thread.start()
    return {"task_id": taskId}


def getDeployTask(taskId: str) -> Optional[Dict[str, Any]]:
    with _TASKS_LOCK:
        task = _TASKS.get(str(taskId or ""))
    if task is None:
        return None
    return {k: v for k, v in task.items()}


def _record(taskId: str, name: str, ok: bool, detail: str = "") -> None:
    with _TASKS_LOCK:
        task = _TASKS.get(taskId)
        if task is not None:
            task["steps"].append({"name": name, "ok": ok, "detail": detail[:400]})


def _fail(taskId: str, message: str) -> None:
    with _TASKS_LOCK:
        task = _TASKS.get(taskId)
        if task is not None:
            task["state"] = "failed"
            task["error"] = message
            task["finished_at"] = time.time()


def _applyOnLoop(loop: Optional[asyncio.AbstractEventLoop]) -> None:
    """把「重建出站 agent」调度回 API 的事件循环（部署线程里没有 loop）。"""
    from neurova.tunnel import connection_config as CC

    if loop is not None and loop.is_running():
        future = asyncio.run_coroutine_threadsafe(CC.applyConnectionConfig(), loop)
        future.result(timeout=60)
    else:
        # 无运行中循环（如单元测试直调）：只落配置，agent 重建交给下次配置读写
        CC.setConnectionConfig(mode=CC.getConnectionConfig()["mode"])


def _executeDeploy(taskId: str, userId: str, params: Dict[str, Any],
                   loop: Optional[asyncio.AbstractEventLoop]) -> None:
    host = str(params["host"]).strip()
    relayPort = int(params.get("relay_port") or 8443)
    domain = str(params.get("domain") or "").strip()
    tlsCert = str(params.get("tls_cert") or "").strip()
    tlsKey = str(params.get("tls_key") or "").strip()
    session = _SshSession(
        host=host, port=int(params.get("ssh_port") or 22),
        username=str(params.get("username") or "root"),
        password=str(params.get("password") or "") or None,
        key_text=str(params.get("key_text") or "") or None,
    )

    def fail(message: str) -> None:
        _fail(taskId, message)
        log_audit(AuditEventType.CONFIG_CHANGE, AuditSeverity.HIGH, user_id=userId,
                  action=f"远程部署失败（{host}）：{message[:120]}")

    def step(name: str, action: Callable[[], str]) -> bool:
        """跑一步：成功记 True 并返回 True；失败记 False、置任务失败并返回 False。"""
        try:
            _record(taskId, name, True, action())
            return True
        except Exception as e:  # noqa: BLE001 - 单步失败=整次部署诚实失败
            _record(taskId, name, False, str(e))
            fail(str(e))
            return False

    def checkConnection() -> str:
        uid = require(session.run("id -u"), "id -u")
        if uid != "0":
            raise RuntimeError(f"需要 root 权限部署（当前 uid={uid}）")
        require(session.run("command -v systemctl"), "systemd 检查")
        return "root + systemd 就绪"

    def makeUserAndDirs() -> str:
        require(session.run(f"id -u {REMOTE_SERVICE_USER} >/dev/null 2>&1 || "
                            f"useradd --system --no-create-home --shell /usr/sbin/nologin "
                            f"{REMOTE_SERVICE_USER}"), "建账号")
        require(session.run(f"mkdir -p {REMOTE_LIB_DIR}/lib {REMOTE_VENV_DIR} "
                            f"{REMOTE_CONFIG_DIR}"), "建目录")
        return ""

    def uploadFiles() -> str:
        files = _relayFiles()
        dirs = sorted({f"{REMOTE_LIB_DIR}/" + str(Path(rel).parent) for rel in files})
        require(session.run("mkdir -p " + " ".join(dirs)), "建文件目录")
        for rel in files:
            payload = base64.b64encode((_repoRoot() / rel).read_bytes()).decode("ascii")
            require(session.run(f"echo '{payload}' | base64 -d > '{REMOTE_LIB_DIR}/{rel}'"),
                    f"上传 {rel}")
        return f"{len(files)} 个文件"

    def installDeps() -> str:
        return require(session.run(
            f"python3 -m venv {REMOTE_VENV_DIR} && "
            f"{REMOTE_VENV_DIR}/bin/pip install --quiet --upgrade pip && "
            f"{REMOTE_VENV_DIR}/bin/pip install --quiet fastapi 'uvicorn[standard]'",
            timeout=1200.0), "安装依赖") or "依赖安装完成"

    token = ""

    def writeToken() -> str:
        nonlocal token
        existing = require(session.run(
            f"cat {REMOTE_CONFIG_DIR}/enrollment_token 2>/dev/null || true"), "读令牌")
        if existing:
            token = existing
            return "复用服务器上已有令牌"
        token = secrets.token_urlsafe(32)
        session.writeText(f"{REMOTE_CONFIG_DIR}/enrollment_token", token)
        require(session.run(f"chmod 600 {REMOTE_CONFIG_DIR}/enrollment_token"), "令牌权限")
        return "新生成"

    def writeConfigAndUnit() -> str:
        lines = [f"NEUROVA_RELAY_ENROLLMENT_TOKEN={token}",
                 f"NEUROVA_RELAY_PORT={relayPort}"]
        if tlsCert and tlsKey:
            lines += [f"NEUROVA_RELAY_TLS_CERT={tlsCert}", f"NEUROVA_RELAY_TLS_KEY={tlsKey}"]
        session.writeText(f"{REMOTE_CONFIG_DIR}/config.env", "\n".join(lines) + "\n")
        session.writeText("/etc/systemd/system/neurova-relay.service", _unitTemplate())
        return require(session.run(f"systemctl daemon-reload && "
                                   f"systemctl enable {REMOTE_SERVICE_NAME}"), "装单元")

    def startAndSelfCheck() -> str:
        out = require(session.run(
            f"systemctl restart {REMOTE_SERVICE_NAME} && sleep 1 && "
            f"curl -s -o /dev/null -w '%{{http_code}}' "
            f"http://127.0.0.1:{relayPort}/healthz"), "启动自检")
        if out != "200":
            raise RuntimeError(f"中继自检未通过（/healthz → {out or '无响应'}）")
        return "自检 200"

    try:
        session.connect()
    except Exception as e:  # noqa: BLE001
        fail(f"SSH 连接失败：{e}")
        return

    def require(result: Dict[str, Any], stepName: str) -> str:
        if result["returncode"] != 0:
            raise RuntimeError(
                f"{stepName} 失败：{(result['stderr'] or result['stdout'] or '无输出')[:300]}")
        return result["stdout"].strip()

    for name, action in (
        ("SSH 连接与 root 权限检查", checkConnection),
        ("创建专用账号与目录", makeUserAndDirs),
        ("上传中继文件集", uploadFiles),
        ("安装运行依赖", installDeps),
        ("写入准入令牌", writeToken),
        ("写配置与 systemd 单元", writeConfigAndUnit),
        ("启动与自检", startAndSelfCheck),
    ):
        if not step(name, action):
            session.close()
            return

    scheme = "https" if (tlsCert and tlsKey) else "http"
    relayUrl = f"{scheme}://{domain or host}:{relayPort}"
    from neurova.tunnel import connection_config as CC

    CC.setConnectionConfig(mode="relay", relayUrl=relayUrl, relayEnrollmentToken=token)
    _applyOnLoop(loop)
    with _TASKS_LOCK:
        task = _TASKS.get(taskId)
        if task is not None:
            task["state"] = "success"
            task["relay_url"] = relayUrl
            task["enrollment_token_masked"] = ("••••" + token[-4:]) if token else ""
            task["finished_at"] = time.time()
    log_audit(AuditEventType.CONFIG_CHANGE, AuditSeverity.HIGH, user_id=userId,
              action=f"远程部署成功（{relayUrl}），连接方式已切到自建中继")
    session.close()


def runRemoteUndeploy(userId: str, params: Dict[str, Any],
                      loop: Optional[asyncio.AbstractEventLoop] = None) -> Dict[str, Any]:
    """撤销远程部署：停服务 → 删文件与账号 → 连接方式退回 auto。同步执行（秒级）。"""
    _validateParams(params)
    host = str(params["host"]).strip()
    session = _SshSession(
        host=host, port=int(params.get("ssh_port") or 22),
        username=str(params.get("username") or "root"),
        password=str(params.get("password") or "") or None,
        key_text=str(params.get("key_text") or "") or None,
    )
    steps: List[Dict[str, Any]] = []

    def runStep(name: str, command: str) -> None:
        try:
            result = session.run(command, timeout=120.0)
            ok = result["returncode"] == 0
            detail = result["stderr"][:200] or result["stdout"][:200]
        except Exception as e:  # noqa: BLE001 - 单步失败也要进报告
            ok, detail = False, str(e)
        steps.append({"name": name, "ok": ok, "detail": detail})

    try:
        session.connect()
    except Exception as e:  # noqa: BLE001
        return {"state": "failed", "steps": [{"name": "SSH 连接", "ok": False,
                                              "detail": str(e)}], "error": str(e)}

    runStep("停止并禁用服务",
            f"systemctl stop {REMOTE_SERVICE_NAME}; "
            f"systemctl disable {REMOTE_SERVICE_NAME}")
    runStep("删除文件与单元",
            f"rm -rf {REMOTE_VENV_DIR} {REMOTE_LIB_DIR} {REMOTE_CONFIG_DIR} "
            f"/etc/systemd/system/{REMOTE_SERVICE_NAME}.service && systemctl daemon-reload")
    runStep("移除专用账号",
            f"id -u {REMOTE_SERVICE_USER} >/dev/null 2>&1 && userdel {REMOTE_SERVICE_USER}")
    session.close()

    failed = [s for s in steps if not s["ok"]]
    # 连接方式退回 auto（若当前不是 relay 则保持原样）；agent 重建回事件循环
    from neurova.tunnel import connection_config as CC

    if CC.getConnectionConfig()["mode"] == "relay":
        CC.setConnectionConfig(mode="auto", relayUrl="", relayEnrollmentToken="")
        if loop is not None and loop.is_running():
            asyncio.run_coroutine_threadsafe(CC.applyConnectionConfig(), loop)
    log_audit(AuditEventType.CONFIG_CHANGE, AuditSeverity.HIGH, user_id=userId,
              action=f"远程中继已卸载（{host}）")
    return {"state": "failed" if failed else "success", "steps": steps,
            "error": "; ".join(s["detail"] for s in failed)}
