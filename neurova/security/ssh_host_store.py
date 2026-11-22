"""SSH 主机密钥确认库（known_hosts，按 agent 分桶落盘）。

U1（弃 AutoAddPolicy 的 TOFU）的信任锚：首连主机的公钥必须经用户确认
（主机确认卡），确认记录落 `data/<agent_id>/ssh_known_hosts.json`；后续连接
校验服务端公钥的 SHA256 指纹——一致放行，变化即 fail-closed（疑似中间人/主机重装，
由 ssh_runner 侧抛 HostKeyMismatchError 并落审计 HIGH）。

设计：
- 键 = (agent_id, host, port)；每 agent 一个 JSON 文件，写走 RLock + 临时文件原子替换
- 只存"已确认"记录与指纹，不存公钥本体（裁决只需指纹，落盘面最小）
- 指纹算法单点：publicKeyFingerprint（OpenSSH 风格 SHA256:base64，去 padding）
- 坏文件按空库处理（裁决宁可回到"待确认"，绝不把坏数据当成"已确认"放行）
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Union

from neurova.core.logger import get_logger

logger = get_logger(__name__)

_STORE_FILENAME = "ssh_known_hosts.json"


def publicKeyFingerprint(key: Any) -> str:
    """paramiko 公钥对象 → OpenSSH 风格 SHA256 指纹（"SHA256:" + 去 padding base64）。

    只依赖 key.asbytes()（SSH wire 格式公钥字节），不 import paramiko，
    供 ssh_runner / remote_deploy 共用同一口径（单一事实源）。
    """
    digest = hashlib.sha256(key.asbytes()).digest()
    return "SHA256:" + base64.b64encode(digest).decode("ascii").rstrip("=")


def _nowIso() -> str:
    return datetime.now().isoformat(timespec="seconds")


class SshHostStore:
    """按 (agent_id, host, port) 记录已确认的主机公钥指纹。"""

    def __init__(self, root_dir: Union[str, Path] = ""):
        # root_dir = agent 根目录的父目录（生产=数据根；测试注入临时目录隔离）。
        self._root = Path(root_dir).expanduser() if root_dir else None
        self._lock = threading.RLock()

    def _bucketDir(self, agent_id: str) -> Path:
        if self._root is not None:
            return self._root / (agent_id or "default")
        from neurova.core.data_root import get_agent_data_dir

        return get_agent_data_dir(agent_id)

    def _pathFor(self, agent_id: str) -> Path:
        return self._bucketDir(agent_id) / _STORE_FILENAME

    def _read(self, agent_id: str) -> Dict[str, Any]:
        path = self._pathFor(agent_id)
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {"version": 1, "hosts": {}}
        except OSError as e:
            logger.warning("ssh_known_hosts 读取失败（按空库处理）%s: %s", path, e)
            return {"version": 1, "hosts": {}}
        try:
            data = json.loads(raw)
            if not isinstance(data, dict) or not isinstance(data.get("hosts"), dict):
                raise ValueError("JSON 形状不符")
            return data
        except Exception as e:  # noqa: BLE001 - 坏文件按空库处理，裁决回"待确认"而非误放行
            logger.warning("ssh_known_hosts 解析失败（按空库处理）%s: %s", path, e)
            return {"version": 1, "hosts": {}}

    def _write(self, agent_id: str, data: Dict[str, Any]) -> None:
        path = self._pathFor(agent_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)

    @staticmethod
    def _entryKey(host: str, port: int) -> str:
        return f"{(host or '').strip()}:{int(port)}"

    def lookup(self, agent_id: str, host: str, port: int) -> Optional[Dict[str, Any]]:
        """取该 (agent, host, port) 的已确认记录；无记录返回 None。"""
        with self._lock:
            entry = self._read(agent_id)["hosts"].get(self._entryKey(host, port))
        return dict(entry) if isinstance(entry, dict) else None

    def mark_confirmed(self, agent_id: str, host: str, port: int, key_fingerprint: str,
                       confirmed_via: str = "user_card", key_type: str = "") -> bool:
        """记录/更新一条已确认主机公钥（复确认覆盖旧指纹，first_seen 保留首见）。

        写入方：主机确认卡的确认动作（API/前端）与运维脚本；ssh_runner 只读。
        """
        host = (host or "").strip()
        key_fingerprint = (key_fingerprint or "").strip()
        if not host or not key_fingerprint:
            return False
        with self._lock:
            data = self._read(agent_id)
            hosts = data.setdefault("hosts", {})
            entryKey = self._entryKey(host, port)
            old = hosts.get(entryKey) if isinstance(hosts.get(entryKey), dict) else {}
            hosts[entryKey] = {
                "host": host,
                "port": int(port),
                "key_fingerprint": key_fingerprint,
                "key_type": key_type or old.get("key_type", ""),
                "first_seen": old.get("first_seen") or _nowIso(),
                "confirmed_via": confirmed_via or "user_card",
            }
            self._write(agent_id, data)
        return True

    def is_mismatch(self, agent_id: str, host: str, port: int, key_fingerprint: str) -> bool:
        """已确认记录存在且指纹不一致 → True（fail-closed 信号）。

        无记录 → False（那是"待确认"，不是"不匹配"——两态由调用方分流）。
        """
        entry = self.lookup(agent_id, host, port)
        if entry is None:
            return False
        return entry.get("key_fingerprint") != (key_fingerprint or "").strip()


# 模块级单例（DCL + RLock，代码规约口径）
_store_instance: Optional[SshHostStore] = None
_store_lock = threading.RLock()


def get_ssh_host_store() -> SshHostStore:
    global _store_instance
    if _store_instance is None:
        with _store_lock:
            if _store_instance is None:
                _store_instance = SshHostStore()
    return _store_instance


def reset_ssh_host_store() -> None:
    """仅测试/重装配用：清空单例，使下一次 get 重建。"""
    global _store_instance
    with _store_lock:
        _store_instance = None
