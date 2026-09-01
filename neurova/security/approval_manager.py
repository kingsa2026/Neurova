"""
Agent 执行危险命令审批机制

支持所有消息渠道的统一审批流程：
1. 危险命令检测
2. 审批请求发送（飞书卡片/企业微信模板/钉钉卡片/控制台）
3. 审批状态管理
4. 跨会话审批支持
"""

from __future__ import annotations

import datetime
import fnmatch
import json
from neurova.core.logger import get_logger
import re
import threading
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

logger = get_logger(__name__)


class ApprovalStatus(str, Enum):
    """审批状态"""

    PENDING = "pending"  # 等待审批
    APPROVED = "approved"  # 已批准
    REJECTED = "rejected"  # 已拒绝
    EXPIRED = "expired"  # 已过期
    AUTO_APPROVED = "auto_approved"  # 自动批准


class ApprovalLevel(str, Enum):
    """审批等级"""

    NONE = "none"  # 无需审批
    SMART = "smart"  # 智能模式（危险命令需要审批）
    ALWAYS = "always"  # 所有命令都需要审批


class DangerousCommandDetector:
    """危险命令检测器"""

    # 危险命令模式列表
    DANGEROUS_PATTERNS = [
        # 文件系统危险操作
        r"rm\s+(-[rf]+\s+|--recursive|--force)",
        r"rmdir\s+",
        r"mv\s+.*\s+/dev/null",
        r"dd\s+",
        r"mkfs\.",
        r"fdisk\s+",
        r"chmod\s+777",
        r"chown\s+root",
        # 网络危险操作
        r"curl\s+.*\|\s*(bash|sh)",
        r"wget\s+.*\|\s*(bash|sh)",
        r"nc\s+.*-e\s+",
        r"ncat\s+.*-e\s+",
        # 系统危险操作
        r"shutdown\s+",
        r"reboot\s+",
        r"halt\s+",
        r"poweroff",
        r"init\s+0",
        r"kill\s+-9\s+1",
        r"killall\s+",
        r"pkill\s+",
        # 权限提升
        r"sudo\s+",
        r"su\s+root",
        r"su\s+-",
        # 数据库危险操作
        r"DROP\s+DATABASE",
        r"DROP\s+TABLE",
        r"DELETE\s+FROM\s+.*\s+WHERE\s+1\s*=\s*1",
        r"TRUNCATE\s+TABLE",
        # 代码执行
        r"eval\s*\(",
        r"exec\s*\(",
        r"__import__\s*\(",
        r"subprocess\.call",
        r"os\.system\s*\(",
        # 危险的 Python 操作
        r"import\s+subprocess",
        r"import\s+os",
        r"from\s+os\s+import",
        r"from\s+subprocess\s+import",
    ]

    def __init__(self):
        self._compiled_patterns = [re.compile(pattern, re.IGNORECASE) for pattern in self.DANGEROUS_PATTERNS]

    def is_dangerous(self, command: str) -> bool:
        """检测命令是否危险"""
        if not command:
            return False

        for pattern in self._compiled_patterns:
            if pattern.search(command):
                return True

        return False

    def get_danger_reason(self, command: str) -> Optional[str]:
        """获取命令危险原因"""
        if not command:
            return None

        for pattern in self._compiled_patterns:
            match = pattern.search(command)
            if match:
                return f"匹配危险模式: {match.group()}"

        return None


@dataclass
class ApprovalRequest:
    """审批请求"""

    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    agent_id: str = ""
    user_id: str = ""
    command: str = ""
    description: str = ""
    danger_reason: str = ""
    status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))
    updated_at: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))
    expires_at: Optional[datetime.datetime] = None
    approved_by: Optional[str] = None
    approval_note: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "request_id": self.request_id,
            "agent_id": self.agent_id,
            "user_id": self.user_id,
            "command": self.command,
            "description": self.description,
            "danger_reason": self.danger_reason,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "approved_by": self.approved_by,
            "approval_note": self.approval_note,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ApprovalRequest:
        """从字典创建"""
        return cls(
            request_id=data.get("request_id", str(uuid.uuid4())),
            agent_id=data.get("agent_id", ""),
            user_id=data.get("user_id", ""),
            command=data.get("command", ""),
            description=data.get("description", ""),
            danger_reason=data.get("danger_reason", ""),
            status=ApprovalStatus(data.get("status", "pending")),
            created_at=(
                datetime.datetime.fromisoformat(data["created_at"])
                if data.get("created_at")
                else datetime.datetime.now(datetime.timezone.utc)
            ),
            updated_at=(
                datetime.datetime.fromisoformat(data["updated_at"])
                if data.get("updated_at")
                else datetime.datetime.now(datetime.timezone.utc)
            ),
            expires_at=datetime.datetime.fromisoformat(data["expires_at"]) if data.get("expires_at") else None,
            approved_by=data.get("approved_by"),
            approval_note=data.get("approval_note"),
            metadata=data.get("metadata", {}),
        )


class ApprovalManager:
    """审批管理器"""

    # 默认审批请求过期时间（秒）
    DEFAULT_EXPIRY_SECONDS = 300  # 5分钟

    def __init__(self, workspace_path: str, approval_level: ApprovalLevel = ApprovalLevel.SMART):
        self._workspace_path = Path(workspace_path)
        self._approval_level = approval_level
        self._lock = threading.Lock()

        # 审批请求存储
        self._requests: Dict[str, ApprovalRequest] = {}

        # 危险命令检测器
        self._detector = DangerousCommandDetector()

        # 白名单命令
        self._whitelist: Set[str] = set()

        # 历史批准记录（用于智能模式）
        self._approved_history: Dict[str, datetime.datetime] = {}

        # P1-c 审批记忆（EXACT/SIMILAR）：用户显式同意沉淀的持久规则
        self._approval_memory: List[Dict[str, Any]] = []
        self._APPROVAL_MEMORY_MAX = 200

        # 通知回调
        self._notification_callbacks: List[Callable] = []

        # 存储路径
        self._storage_path = self._workspace_path / ".approval" / "requests.json"
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)

        # 加载历史请求
        self._load_requests()

        logger.info("审批管理器初始化完成，等级: %s", approval_level.value)

    def register_notification_callback(self, callback: Callable):
        """注册通知回调"""
        self._notification_callbacks.append(callback)

    def check_command(self, command: str, agent_id: str = "", user_id: str = "") -> Dict[str, Any]:
        """
        检查命令是否需要审批

        返回:
            {
                "needs_approval": bool,
                "reason": str or None,
                "request_id": str or None
            }
        """
        # 如果审批等级为 NONE，直接通过
        if self._approval_level == ApprovalLevel.NONE:
            return {"needs_approval": False, "reason": None, "request_id": None}

        # 检查白名单
        if self._is_in_whitelist(command):
            return {"needs_approval": False, "reason": "命令在白名单中", "request_id": None}

        # P1-c 审批记忆：用户显式批准过的命令模式优先于危险检测
        mem_hit = self._match_approval_memory(command)
        if mem_hit is not None:
            return {
                "needs_approval": False,
                "reason": f"命中审批记忆({mem_hit['kind']})",
                "request_id": None,
            }

        # 检查历史批准
        if self._approval_level == ApprovalLevel.SMART:
            if self._check_historical_approval(command):
                return {"needs_approval": False, "reason": "命令已历史批准", "request_id": None}

        # 检测是否危险
        is_dangerous = self._detector.is_dangerous(command)
        danger_reason = self._detector.get_danger_reason(command)

        # 根据审批等级决定
        needs_approval = False
        reason = None

        if self._approval_level == ApprovalLevel.ALWAYS:
            needs_approval = True
            reason = "所有命令都需要审批"
        elif self._approval_level == ApprovalLevel.SMART and is_dangerous:
            needs_approval = True
            reason = danger_reason

        # 如果需要审批，创建审批请求
        request_id = None
        if needs_approval:
            request = self.create_approval_request(
                agent_id=agent_id,
                user_id=user_id,
                command=command,
                description=f"命令审批请求",
                danger_reason=danger_reason or "",
            )
            request_id = request.request_id

        return {
            "needs_approval": needs_approval,
            "reason": reason,
            "request_id": request_id,
        }

    def create_approval_request(
        self,
        agent_id: str,
        user_id: str,
        command: str,
        description: str = "",
        danger_reason: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ApprovalRequest:
        """创建审批请求"""
        with self._lock:
            request = ApprovalRequest(
                agent_id=agent_id,
                user_id=user_id,
                command=command,
                description=description,
                danger_reason=danger_reason,
                expires_at=datetime.datetime.now(datetime.timezone.utc)
                + datetime.timedelta(seconds=self.DEFAULT_EXPIRY_SECONDS),
                metadata=metadata or {},
            )

            self._requests[request.request_id] = request
            self._save_requests()

            # 发送通知
            self._send_approval_notification(request)

            logger.info("创建审批请求: %s, 命令: %s...", request.request_id, command[:50])

            return request

    def approve_request(
        self,
        request_id: str,
        approved_by: str,
        note: str = "",
        remember: Optional[str] = None,
    ) -> bool:
        """批准审批请求。

        remember: None（不记忆，走既有 24h 精确历史）/"exact"（整条命令
        持久记忆）/"similar"（结构泛化记忆——参数值通配，危险命令自动跳过泛化）。
        """
        """批准审批请求"""
        with self._lock:
            request = self._requests.get(request_id)
            if not request:
                logger.warning("审批请求不存在: %s", request_id)
                return False

            if request.status != ApprovalStatus.PENDING:
                logger.warning("审批请求状态不是待处理: %s, 状态: %s", request_id, request.status.value)
                return False

            # 检查是否过期
            if request.expires_at and datetime.datetime.now(datetime.timezone.utc) > request.expires_at:
                request.status = ApprovalStatus.EXPIRED
                self._save_requests()
                logger.warning("审批请求已过期: %s", request_id)
                return False

            # 更新状态
            request.status = ApprovalStatus.APPROVED
            request.approved_by = approved_by
            request.approval_note = note
            request.updated_at = datetime.datetime.now(datetime.timezone.utc)

            # 记录到历史（用于智能模式）
            self._approved_history[request.command] = datetime.datetime.now(datetime.timezone.utc)

            # P1-c：审批记忆沉淀
            self._remember_approval(request.command, approved_by, remember)

            self._save_requests()

            # 发送结果通知
            self._send_approval_result(request)

            logger.info("审批请求已批准: %s, 批准人: %s", request_id, approved_by)

            return True

    def reject_request(
        self,
        request_id: str,
        rejected_by: str,
        note: str = "",
    ) -> bool:
        """拒绝审批请求"""
        with self._lock:
            request = self._requests.get(request_id)
            if not request:
                logger.warning("审批请求不存在: %s", request_id)
                return False

            if request.status != ApprovalStatus.PENDING:
                logger.warning("审批请求状态不是待处理: %s, 状态: %s", request_id, request.status.value)
                return False

            # 更新状态
            request.status = ApprovalStatus.REJECTED
            request.approved_by = rejected_by
            request.approval_note = note
            request.updated_at = datetime.datetime.now(datetime.timezone.utc)

            self._save_requests()

            # 发送结果通知
            self._send_approval_result(request)

            logger.info("审批请求已拒绝: %s, 拒绝人: %s", request_id, rejected_by)

            return True

    def get_pending_requests(self, agent_id: Optional[str] = None) -> List[ApprovalRequest]:
        """获取待处理的审批请求"""
        with self._lock:
            self._cleanup_expired_requests()

            requests = [r for r in self._requests.values() if r.status == ApprovalStatus.PENDING]

            if agent_id:
                requests = [r for r in requests if r.agent_id == agent_id]

            return sorted(requests, key=lambda r: r.created_at, reverse=True)

    def get_request(self, request_id: str) -> Optional[ApprovalRequest]:
        """按 ID 获取审批请求（任意状态）"""
        with self._lock:
            return self._requests.get(request_id)

    # ── P1-c 审批记忆（EXACT/SIMILAR） ──

    @staticmethod
    def _generalize_command(command: str) -> str:
        """结构泛化：保留命令名与 flag，参数值通配为 *。

        git push origin feature-x → git push * *
        pytest -q tests/unit       → pytest -q *
        """
        tokens = (command or "").strip().split()
        if not tokens:
            return command
        out = [tokens[0]]
        for t in tokens[1:]:
            out.append(t if t.startswith("-") else "*")
        return " ".join(out)

    def _remember_approval(self, command: str, approved_by: str, remember: Optional[str]) -> None:
        """审批通过后沉淀持久记忆（EXACT/SIMILAR）；None 不记忆。"""
        if remember not in ("exact", "similar"):
            return
        try:
            if remember == "exact":
                pattern = (command or "").strip()
                kind = "exact"
            else:
                pattern = self._generalize_command(command)
                kind = "similar"

            # 同 pattern 同 kind 去重（刷新时间戳即可）
            for rule in self._approval_memory:
                if rule["pattern"] == pattern and rule["kind"] == kind:
                    rule["created_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
                    return

            self._approval_memory.append(
                {
                    "id": f"mem-{uuid.uuid4().hex[:8]}",
                    "pattern": pattern,
                    "kind": kind,
                    "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "approved_by": approved_by,
                    "hits": 0,
                }
            )
            # GC：超上限淘汰最旧
            if len(self._approval_memory) > self._APPROVAL_MEMORY_MAX:
                self._approval_memory.sort(key=lambda r: r["created_at"])
                self._approval_memory = self._approval_memory[-self._APPROVAL_MEMORY_MAX:]
            logger.info("审批记忆沉淀: kind=%s pattern=%r", kind, pattern)
        except Exception as e:
            logger.warning("审批记忆沉淀失败: %s", e)

    def _match_approval_memory(self, command: str) -> Optional[Dict[str, Any]]:
        """决策端匹配：EXACT 全等；SIMILAR 通配。

        危险命令豁免 SIMILAR——用户只泛化批准过一条结构，
        不代表所有同构危险命令（rm -rf *）都自动放行。
        """
        cmd = (command or "").strip()
        if not cmd:
            return None
        is_dangerous = self._detector.is_dangerous(cmd)
        hit = None
        for rule in self._approval_memory:
            if rule["kind"] == "exact":
                if rule["pattern"] == cmd:
                    hit = rule
                    break
            else:  # similar
                if is_dangerous:
                    continue
                try:
                    if fnmatch.fnmatch(cmd, rule["pattern"]):
                        hit = rule
                        break
                except Exception:
                    continue
        if hit is not None:
            hit["hits"] = hit.get("hits", 0) + 1
        return hit

    def list_approval_memory(self) -> List[Dict[str, Any]]:
        """审批记忆清单（只读副本）。"""
        with self._lock:
            return [dict(r) for r in self._approval_memory]

    def _is_in_whitelist(self, command: str) -> bool:
        """检查命令是否在白名单中"""
        command_lower = command.lower().strip()

        # 默认白名单
        default_whitelist = {
            "ls",
            "pwd",
            "echo",
            "cat",
            "head",
            "tail",
            "grep",
            "find",
            "which",
            "whoami",
            "date",
            "python --version",
            "node --version",
            "npm --version",
        }

        # 检查默认白名单
        if command_lower in default_whitelist:
            return True

        # 检查自定义白名单
        for pattern in self._whitelist:
            if re.match(pattern, command, re.IGNORECASE):
                return True

        return False

    def _check_historical_approval(self, command: str) -> bool:
        """检查命令是否已历史批准"""
        if command in self._approved_history:
            # 检查批准是否在24小时内
            approved_time = self._approved_history[command]
            if datetime.datetime.now(datetime.timezone.utc) - approved_time < datetime.timedelta(hours=24):
                return True
            else:
                # 过期，移除记录
                del self._approved_history[command]

        return False

    def _send_approval_notification(self, request: ApprovalRequest):
        """发送审批通知"""
        for callback in self._notification_callbacks:
            try:
                callback("approval_request", request.to_dict())
            except Exception as e:
                logger.error("发送审批通知失败: %s", e)

    def _send_approval_result(self, request: ApprovalRequest):
        """发送审批结果通知"""
        for callback in self._notification_callbacks:
            try:
                callback("approval_result", request.to_dict())
            except Exception as e:
                logger.error("发送审批结果通知失败: %s", e)

    def _cleanup_expired_requests(self):
        """清理过期请求"""
        now = datetime.datetime.now(datetime.timezone.utc)
        expired_ids = []

        for request_id, request in self._requests.items():
            if request.status == ApprovalStatus.PENDING and request.expires_at and now > request.expires_at:
                request.status = ApprovalStatus.EXPIRED
                expired_ids.append(request_id)

        if expired_ids:
            self._save_requests()
            logger.info("清理了 %s 个过期审批请求", len(expired_ids))

    def _load_requests(self):
        """加载审批请求"""
        try:
            if self._storage_path.exists():
                with open(self._storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for request_data in data.get("requests", []):
                        request = ApprovalRequest.from_dict(request_data)
                        self._requests[request.request_id] = request

                    # 加载白名单
                    self._whitelist = set(data.get("whitelist", []))

                    # 加载历史批准
                    for cmd, ts_str in data.get("approved_history", {}).items():
                        self._approved_history[cmd] = datetime.datetime.fromisoformat(ts_str)

                    # P1-c：加载审批记忆
                    mem = data.get("approval_memory", [])
                    if isinstance(mem, list):
                        self._approval_memory = [m for m in mem if isinstance(m, dict) and m.get("pattern")]

                logger.info("加载了 %s 个审批请求", len(self._requests))
        except Exception as e:
            logger.error("加载审批请求失败: %s", e)

    def _save_requests(self):
        """保存审批请求"""
        try:
            data = {
                "requests": [r.to_dict() for r in self._requests.values()],
                "whitelist": list(self._whitelist),
                "approved_history": {cmd: ts.isoformat() for cmd, ts in self._approved_history.items()},
                "approval_memory": list(self._approval_memory),
            }

            with open(self._storage_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

        except Exception as e:
            logger.error("保存审批请求失败: %s", e)


# ========================= 全局单例和便捷函数 =========================

_approval_manager: Optional[ApprovalManager] = None
_am_lock = threading.Lock()


def get_approval_manager(
    workspace_path: str = ".", approval_level: ApprovalLevel = ApprovalLevel.SMART
) -> ApprovalManager:
    """获取全局审批管理器"""
    global _approval_manager
    if _approval_manager is None:
        with _am_lock:
            if _approval_manager is None:
                _approval_manager = ApprovalManager(workspace_path, approval_level)
    return _approval_manager


def set_approval_level(level: ApprovalLevel):
    """设置审批等级"""
    manager = get_approval_manager()
    manager._approval_level = level
    logger.info("审批等级已设置为: %s", level.value)


def generate_approval_html(request_data: Dict[str, Any]) -> str:
    """
    生成控制台审批卡片 HTML 页面（支持跨会话审批）

    参数:
        request_data: 审批请求数据

    返回:
        HTML 字符串
    """
    request_id = request_data.get("request_id", "")
    command = request_data.get("command", "")
    danger_reason = request_data.get("danger_reason", "")
    agent_id = request_data.get("agent_id", "")
    created_at = request_data.get("created_at", "")

    html = f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Neurova 审批请求</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            margin: 0;
            padding: 20px;
        }}
        .card {{
            background: white;
            border-radius: 16px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            max-width: 600px;
            width: 100%;
            padding: 32px;
        }}
        .header {{
            text-align: center;
            margin-bottom: 24px;
        }}
        .header h1 {{
            color: #333;
            margin: 0 0 8px 0;
            font-size: 24px;
        }}
        .header p {{
            color: #666;
            margin: 0;
        }}
        .warning-box {{
            background: #fff3cd;
            border: 1px solid #ffc107;
            border-radius: 8px;
            padding: 16px;
            margin-bottom: 24px;
        }}
        .warning-box .icon {{
            font-size: 24px;
            margin-right: 8px;
        }}
        .command-box {{
            background: #f8f9fa;
            border: 1px solid #e9ecef;
            border-radius: 8px;
            padding: 16px;
            font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
            font-size: 14px;
            word-break: break-all;
            margin-bottom: 24px;
        }}
        .info-row {{
            display: flex;
            justify-content: space-between;
            margin-bottom: 12px;
            font-size: 14px;
        }}
        .info-label {{
            color: #666;
        }}
        .info-value {{
            color: #333;
            font-weight: 500;
        }}
        .buttons {{
            display: flex;
            gap: 16px;
            margin-top: 24px;
        }}
        .btn {{
            flex: 1;
            padding: 14px 24px;
            border: none;
            border-radius: 8px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }}
        .btn-approve {{
            background: #28a745;
            color: white;
        }}
        .btn-approve:hover {{
            background: #218838;
            transform: translateY(-2px);
        }}
        .btn-reject {{
            background: #dc3545;
            color: white;
        }}
        .btn-reject:hover {{
            background: #c82333;
            transform: translateY(-2px);
        }}
        .note-input {{
            width: 100%;
            padding: 12px;
            border: 1px solid #ddd;
            border-radius: 8px;
            font-size: 14px;
            margin-top: 16px;
            box-sizing: border-box;
        }}
    </style>
</head>
<body>
    <div class="card">
        <div class="header">
            <h1>⚠️ 命令审批请求</h1>
            <p>Agent 请求执行以下命令</p>
        </div>

        <div class="warning-box">
            <span class="icon">⚠️</span>
            <strong>危险原因:</strong> {danger_reason}
        </div>

        <div class="command-box">{command}</div>

        <div class="info-row">
            <span class="info-label">请求 ID:</span>
            <span class="info-value">{request_id[:8]}...</span>
        </div>
        <div class="info-row">
            <span class="info-label">Agent ID:</span>
            <span class="info-value">{agent_id}</span>
        </div>
        <div class="info-row">
            <span class="info-label">创建时间:</span>
            <span class="info-value">{created_at}</span>
        </div>

        <input type="text" class="note-input" id="note" placeholder="审批备注（可选）">

        <div class="buttons">
            <button class="btn btn-approve" onclick="approve()">
                ✅ 批准
            </button>
            <button class="btn btn-reject" onclick="reject()">
                ❌ 拒绝
            </button>
        </div>
    </div>

    <script>
        async function approve() {{
            const note = document.getElementById('note').value;
            const response = await fetch('/api/v1/approval/{request_id}/approve', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{note: note}})
            }});
            const result = await response.json();
            if (result.success) {{
                alert('已批准');
                window.location.reload();
            }} else {{
                alert('批准失败: ' + result.error);
            }}
        }}

        async function reject() {{
            const note = document.getElementById('note').value;
            const response = await fetch('/api/v1/approval/{request_id}/reject', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{note: note}})
            }});
            const result = await response.json();
            if (result.success) {{
                alert('已拒绝');
                window.location.reload();
            }} else {{
                alert('拒绝失败: ' + result.error);
            }}
        }}
    </script>
</body>
</html>
"""
    return html


def create_approval_api_endpoints(app, approval_manager: ApprovalManager):
    """
    创建审批 API 端点（用于控制台跨会话审批）

    参数:
        app: FastAPI 应用实例
        approval_manager: 审批管理器实例
    """
    from fastapi import HTTPException
    from pydantic import BaseModel

    class ApprovalAction(BaseModel):
        note: str = ""

    @app.get("/api/v1/approval/pending")
    async def get_pending_approvals():
        """获取待处理审批"""
        requests = approval_manager.get_pending_requests()
        return {
            "success": True,
            "data": [r.to_dict() for r in requests],
        }

    @app.get("/api/v1/approval/{request_id}")
    async def get_approval_detail(request_id: str):
        """获取审批详情"""
        request = approval_manager._requests.get(request_id)
        if not request:
            raise HTTPException(status_code=404, detail="审批请求不存在")

        return {
            "success": True,
            "data": request.to_dict(),
        }

    @app.get("/api/v1/approval/{request_id}/html")
    async def get_approval_html(request_id: str):
        """获取审批 HTML 页面"""
        request = approval_manager._requests.get(request_id)
        if not request:
            raise HTTPException(status_code=404, detail="审批请求不存在")

        from fastapi.responses import HTMLResponse

        html = generate_approval_html(request.to_dict())
        return HTMLResponse(content=html)

    @app.post("/api/v1/approval/{request_id}/approve")
    async def approve_request(request_id: str, action: ApprovalAction):
        """批准审批"""
        success = approval_manager.approve_request(
            request_id=request_id,
            approved_by="console_user",
            note=action.note,
        )

        if not success:
            raise HTTPException(status_code=400, detail="批准失败")

        return {"success": True, "message": "已批准"}

    @app.post("/api/v1/approval/{request_id}/reject")
    async def reject_request(request_id: str, action: ApprovalAction):
        """拒绝审批"""
        success = approval_manager.reject_request(
            request_id=request_id,
            rejected_by="console_user",
            note=action.note,
        )

        if not success:
            raise HTTPException(status_code=400, detail="拒绝失败")

        return {"success": True, "message": "已拒绝"}

    logger.info("审批 API 端点已创建")
