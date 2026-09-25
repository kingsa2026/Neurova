from __future__ import annotations

"""
上下文池数据模型 - Context Pool Models

ContextSource 和 ContextInput 是 context_pool 模块的核心数据类型，
提取到独立模块以避免循环导入。
"""

import hashlib
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional


class ContextSource(Enum):
    """上下文来源枚举"""

    SYSTEM_INSTRUCTION = "system_instruction"  # 系统指令
    DEVELOPER_INSTRUCTION = "developer_instruction"  # 开发者指令
    MEMORY = "memory"  # 记忆
    CONVERSATION = "conversation"  # 对话历史
    EXPERIENCE = "experience"  # 经验知识
    EMOTION = "emotion"  # 情感状态
    REFLECTION = "reflection"  # 反思日志
    TOOL_CALL = "tool_call"  # 工具调用
    MULTIMODAL = "multimodal"  # 多模态内容
    USER_INPUT = "user_input"  # 用户输入
    SUMMARY = "summary"  # 溢出折叠摘要（P1-1③：压缩视图而非丢内容）


#: 上下文来源 → 优先级阶梯（**唯一事实源**）。
#:
#: 为什么必须收在一处：`draw` 按 `priority` 打分排序，于是"同一来源在不同写入点
#: 拿到不同的分"会让同一来源的内容按写入方不同而争位。改前正是这个形态——
#: 编排器声明一套阶梯、端点 `/context/build` 另写 `10`（注释还写"高优先级"）、
#: `voice_context_module` 又给 EMOTION 写 `60` 而编排器写 `50`。三份口径各自
#: 都"看着合理"，合起来却是同一契约的多份定义（`AGENTS.md` 修复教义第 6 条）。
#:
#: 显式传入的 `priority` 仍然生效：经验档位由采纳证据决定（见
#: `dedupe_experience_sources`），那是**政策**而非阶梯的第二份副本。
SOURCE_PRIORITY = {
    ContextSource.SYSTEM_INSTRUCTION: 100,
    ContextSource.SUMMARY: 90,
    ContextSource.DEVELOPER_INSTRUCTION: 90,
    ContextSource.USER_INPUT: 90,
    ContextSource.MEMORY: 70,
    ContextSource.MULTIMODAL: 70,
    ContextSource.EXPERIENCE: 70,
    ContextSource.CONVERSATION: 60,
    ContextSource.TOOL_CALL: 60,
    ContextSource.REFLECTION: 60,
    ContextSource.EMOTION: 50,
}


def priorityForSource(source: ContextSource) -> int:
    """来源 → 优先级（阶梯的唯一入口，见 `SOURCE_PRIORITY`）。"""
    return SOURCE_PRIORITY[source]


@dataclass
class ContextInput:
    """上下文输入数据类 - 活水上下文池的基础单元"""

    source: ContextSource
    content: str
    #: 显式取值优先（证据驱动的档位）；缺省由来源经 `priorityForSource` 派生——
    #: 不再是一个与阶梯无关的独立常数（那就是第二份定义）。
    priority: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    tokens: int = 0
    tags: List[str] = field(default_factory=list)  # 标签列表
    hash: str = None  # 内容哈希（用于精确去重）
    #: 归档时刻——读侧排序与 freshness 打分的**唯一**时间事实源（B6-7）。
    #: 改前还有一个 `updated_at`（构造时与它同值、全仓零写入方），召回老归档时
    #: 该字段是"本次构造时刻"，会让越老的归档越新鲜（打分读到的不是归档时刻）。
    created_at: datetime = None
    seen_confirmed: bool = False  # P1-1④ ack 集：已被成功模型请求读过

    # created_at 单调化守卫（残留处理 2026-09-13 真 bug 根治）：
    # Windows 时钟分辨率粗（datetime.now() 同 tick 打平），而 drawer/query
    # 的排序只用 created_at 单键——打平后 sort 退化为"保留传入顺序"，
    # 同一批条目跨请求相对位置漂移，破坏 [缓存稳定] 前缀缓存契约
    # （semantic_drawer.py 注释自述目标）。守卫令同 tick 的 created_at
    # 严格 +1μs 递增，单键排序即稳定插入序。
    _created_at_lock = threading.Lock()
    _last_created_at = None

    def __post_init__(self):
        """初始化后处理"""
        # 优先级缺省由来源派生（阶梯单源，见 priorityForSource）
        if self.priority is None:
            self.priority = priorityForSource(self.source)

        # 自动生成哈希
        if self.hash is None:
            self.hash = self.compute_hash(self.source, self.content)

        # 自动设置时间（同 tick 单调化，见类注释）
        with ContextInput._created_at_lock:
            now = datetime.now()
            last = ContextInput._last_created_at
            if last is not None and now <= last:
                now = last + timedelta(microseconds=1)
            ContextInput._last_created_at = now
        if self.created_at is None:
            self.created_at = now

    @classmethod
    def compute_hash(cls, source: "ContextSource", content: str) -> str:
        """统一的内容指纹入口（source 域限定去重指纹，非安全用途）。

        任何需要在池外判断"内容是否已归档"的场景（如对话窗口排除重复调取）
        都必须经由本方法计算，保证与 __post_init__ 的去重哈希同源。
        """
        raw = f"{source.value}:{content}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "source": self.source.value,
            "content": self.content,
            "priority": self.priority,
            "metadata": self.metadata,
            "tokens": self.tokens,
            "tags": self.tags,
            "hash": self.hash,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
