"""Skill 声明式权限模型（P0-4 — Dify resource.permission 对标）。

设计（docs/Neurova_Dify代码级对比_2026-09-03.md §2.4 / §4 P0-4）：
Neurova 治理原本只管"调用时"（DENY/SANDBOX/ASK 内容裁决），缺
"安装时声明"层。本模块提供声明面（manifest permissions）+ 调用面
仲裁原语，让 tool_executor / ToolSequenceSkill 以声明为准。

能力键（对齐 Dify resource.permission 六类，Neurova 实际工具面裁剪）：
- tools:   显式工具白名单 {enabled, allow: [...]}（或直接列表）
- network: 网络面（web_search/web_fetch/browser_*/weather/rss/mcp.*）
- file:    文件面（file_read/write/create/delete/edit/list/search，
           支持 read_only 细粒度）
- model:   模型面（tts_synthesize/asr_transcribe 等）
- system:  系统面（computer_*/run_code/spawn_subagent 本机控制）
- node:    节点反调面（run_workflow_agent 等）
- storage: 存储配额声明 {enabled, size}（配额执行接 resource_quota_manager）

语义：
- 无声明（permissions 键缺省）= 存量技能，维持旧行为（治理预检仍兜底）
- 有声明 = fail-closed：六类能力未声明即拒绝；分类外平台工具
  （memory_search/planning 等纯平台能力）不受能力面约束
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set

# 工具分类注册表（与 builtin_tools.py 注册表保持同步；mcp.* 前缀恒网络）
_CATEGORY_TOOLS: Dict[str, Set[str]] = {
    "network": {
        "web_search", "web_fetch", "weather", "rss_read", "youtube_transcript",
        "bilibili_search", "social_search", "browser_read",
        "browser_navigate", "browser_click", "browser_type", "browser_screenshot",
        "browser_extract_text", "browser_dom_snapshot", "browser_dom_read",
        "browser_click_role", "browser_fill_role",
    },
    "file": {
        "file_read", "file_write", "file_create", "file_delete",
        "file_edit", "file_list", "file_search",
    },
    "system": {
        "computer_shell", "computer_screenshot", "computer_click",
        "computer_type", "computer_scroll", "run_code", "spawn_subagent",
    },
    "model": {"tts_synthesize", "asr_transcribe"},
    "node": {"run_workflow_agent"},
}

_TOOL_TO_CATEGORY: Dict[str, str] = {
    tool: cat for cat, tools in _CATEGORY_TOOLS.items() for tool in tools
}

# 文件面只读子集（file.read_only=True 时放行）
_FILE_READ_TOOLS = {"file_read", "file_list", "file_search"}

# 合法能力键（安装门据此报未知键；模型解析时未知键忽略）
KNOWN_CAPABILITY_KEYS = {"tools", "network", "file", "model", "system", "node", "storage"}


def tool_category(tool_name: str) -> Optional[str]:
    """工具 → 能力分类；未分类（平台能力）返回 None。"""
    if (tool_name or "").startswith("mcp."):
        return "network"
    return _TOOL_TO_CATEGORY.get(tool_name)


def tools_for_categories(*categories: str) -> Set[str]:
    """展开分类下的工具集合（安装门/文档用）。"""
    out: Set[str] = set()
    for c in categories:
        out |= _CATEGORY_TOOLS.get(c, set())
    return out


@dataclass
class SkillPermissions:
    """技能权限声明（manifest.permissions 的解析形态）"""

    tools: Optional[List[str]] = None  # 显式白名单；None=未列白名单
    network: bool = False
    file: bool = False
    file_read_only: bool = False
    model: bool = False
    system: bool = False
    node: bool = False
    storage: bool = False
    storage_size: int = 0

    # ── 解析 / 序列化 ────────────────────────────────────────

    @classmethod
    def from_dict(cls, raw: Any) -> "SkillPermissions":
        """宽松解析：嵌套 {enabled, allow} 与扁平 bool 两形态都接受；
        非法类型降级为默认（严格校验是安装门的职责，见
        skill_install_gate.validate_permissions_for_install）。"""
        p = cls()
        if not isinstance(raw, dict):
            return p

        tools_raw = raw.get("tools")
        if isinstance(tools_raw, dict):
            allow = tools_raw.get("allow")
            if isinstance(allow, (list, tuple)):
                p.tools = [str(t) for t in allow]
            if tools_raw.get("enabled") is False:
                p.tools = []
        elif isinstance(tools_raw, (list, tuple)):
            p.tools = [str(t) for t in tools_raw]

        p.network = cls._as_bool(raw.get("network"))

        file_raw = raw.get("file")
        if isinstance(file_raw, dict):
            p.file_read_only = cls._as_bool(file_raw.get("read_only"))
            # read_only=True 表示"仅读"：全量 file 能力不开，只有读子集放行
            p.file = cls._as_bool(file_raw.get("enabled")) and not p.file_read_only
        else:
            p.file = cls._as_bool(file_raw)

        for key, attr in (("model", "model"), ("system", "system"), ("node", "node")):
            setattr(p, attr, cls._as_bool(raw.get(key)))

        storage_raw = raw.get("storage")
        if isinstance(storage_raw, dict):
            p.storage = cls._as_bool(storage_raw.get("enabled"))
            size = storage_raw.get("size")
            if isinstance(size, (int, float)) and not isinstance(size, bool):
                p.storage_size = int(size)
        elif isinstance(storage_raw, (int, float)) and not isinstance(storage_raw, bool):
            p.storage_size = int(storage_raw)
            p.storage = True
        return p

    @staticmethod
    def _as_bool(v: Any) -> bool:
        if isinstance(v, dict):
            return bool(v.get("enabled", False))
        return bool(v)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "network": self.network,
            "file": {"enabled": self.file, "read_only": self.file_read_only},
            "model": self.model,
            "system": self.system,
            "node": self.node,
            "storage": {"enabled": self.storage, "size": self.storage_size},
        }
        if self.tools is not None:
            d["tools"] = {"enabled": True, "allow": list(self.tools)}
        return d

    # ── 仲裁 ─────────────────────────────────────────────────

    def allows_tool(self, tool_name: str) -> bool:
        """白名单优先；分类工具需对应能力声明；未分类平台工具不受约束。"""
        if self.tools is not None and tool_name in self.tools:
            return True
        cat = tool_category(tool_name)
        if cat is None:
            return True
        if cat == "network":
            return self.network
        if cat == "file":
            if self.file:
                return True
            return self.file_read_only and tool_name in _FILE_READ_TOOLS
        if cat == "model":
            return self.model
        if cat == "system":
            return self.system
        if cat == "node":
            return self.node
        return False

    @property
    def model_enabled(self) -> bool:
        return self.model

    @property
    def allows_file_read(self) -> bool:
        return self.file or self.file_read_only

    @property
    def allows_file_write(self) -> bool:
        return self.file


# 别名：与 Dify 六类模型命名对齐时的可读别名
SkillPermissionModel = SkillPermissions


def parse_permissions(raw: Any) -> Optional[SkillPermissions]:
    """manifest/config 中的 permissions → SkillPermissions。

    返回 None = 无声明（存量技能，运行时维持旧行为，由治理预检兜底）。
    """
    if raw is None:
        return None
    if isinstance(raw, SkillPermissions):
        return raw
    if not isinstance(raw, dict):
        return None
    return SkillPermissions.from_dict(raw)


def check_tool_permission(permissions_raw: Any, tool_name: str) -> Optional[str]:
    """声明仲裁原语：返回拒绝原因（str）或 None（放行）。

    - permissions_raw 为 None（无声明）→ None（存量语义不变）
    - 有声明且工具未授权 → 拒绝原因（fail-closed 有依据）
    """
    if permissions_raw is None:
        return None
    perms = permissions_raw if isinstance(permissions_raw, SkillPermissions) else SkillPermissions.from_dict(permissions_raw)
    if perms.allows_tool(tool_name):
        return None
    cat = tool_category(tool_name) or "platform"
    return f"工具 {tool_name} 未在技能权限声明中授权（分类={cat}）"


# ── 调用面作用域（治理预检的声明仲裁入口） ──────────────────

import threading  # noqa: E402
from contextvars import ContextVar  # noqa: E402

_current_skill_permissions: ContextVar[Optional[SkillPermissions]] = ContextVar(
    "skill_permissions", default=None
)


@contextmanager
def skill_permission_scope(perms: Optional[SkillPermissions]):
    """技能执行期间挂载声明作用域（execute_skill_tool 使用）。

    嵌套技能按最内层声明裁决（内层覆盖外层，与调用栈语义一致）。
    """
    token = _current_skill_permissions.set(perms)
    try:
        yield
    finally:
        _current_skill_permissions.reset(token)


def current_skill_permissions() -> Optional[SkillPermissions]:
    return _current_skill_permissions.get()
