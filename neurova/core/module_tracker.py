from __future__ import annotations

"""
模块有效性追踪器 - 闭环保证系统

功能:
- 追踪模块使用情况（写入/读取次数）
- 检测无效模块（写入多但读取少）
- 生成效果报告
- 警告低效模块

实现闭环检查清单:
1. 模块是否被正确初始化
2. 模块是否被使用
3. 模块是否有效果
4. 模块是否需要优化
"""

import asyncio
from dataclasses import dataclass, field
import datetime
import enum
import logging
import threading
import time
import typing

from enum import Enum

logger = logging.getLogger(__name__)


# ────── 数据模型 ──────

class LoopStatus(Enum):
    """闭环状态"""
    NOT_STARTED = "not_started"    # 未开始
    IN_PROGRESS = "in_progress"    # 进行中
    COMPLETED = "completed"        # 已完成
    FAILED = "failed"              # 失败
    INEFFECTIVE = "ineffective"    # 无效


class EffectivenessLevel(Enum):
    """有效性级别"""
    HIGH = "high"          # 高效
    MEDIUM = "medium"      # 中等
    LOW = "low"            # 低效
    INEFFECTIVE = "ineffective"  # 无效
    UNKNOWN = "unknown"    # 未知


@dataclass
class ModuleAccessRecord:
    """模块访问记录"""
    module_id: str = ""
    access_type: str = "read"  # read/write
    timestamp: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))
    details: typing.Dict[str, typing.Any] = field(default_factory=dict)

    def to_dict(self) -> typing.Dict[str, typing.Any]:
        """转换为字典"""
        return {
            "module_id": self.module_id,
            "access_type": self.access_type,
            "timestamp": self.timestamp.isoformat(),
            "details": self.details,
        }


@dataclass
class ModuleLoopChecklist:
    """模块闭环检查清单"""
    module_id: str = ""
    initialized: bool = False
    started: bool = False
    used: bool = False
    effective: bool = False
    optimized: bool = False
    last_check: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))
    issues: typing.List[str] = field(default_factory=list)

    def to_dict(self) -> typing.Dict[str, typing.Any]:
        """转换为字典"""
        return {
            "module_id": self.module_id,
            "initialized": self.initialized,
            "started": self.started,
            "used": self.used,
            "effective": self.effective,
            "optimized": self.optimized,
            "last_check": self.last_check.isoformat(),
            "issues": self.issues,
        }


@dataclass
class EffectivenessReport:
    """有效性报告"""
    module_id: str = ""
    effectiveness_level: EffectivenessLevel = EffectivenessLevel.UNKNOWN
    write_count: int = 0
    read_count: int = 0
    read_write_ratio: float = 0.0
    last_activity: typing.Optional[datetime.datetime] = None
    recommendations: typing.List[str] = field(default_factory=list)
    generated_at: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))

    def to_dict(self) -> typing.Dict[str, typing.Any]:
        """转换为字典"""
        return {
            "module_id": self.module_id,
            "effectiveness_level": self.effectiveness_level.value,
            "write_count": self.write_count,
            "read_count": self.read_count,
            "read_write_ratio": self.read_write_ratio,
            "last_activity": self.last_activity.isoformat() if self.last_activity else None,
            "recommendations": self.recommendations,
            "generated_at": self.generated_at.isoformat(),
        }


# ────── 主类 ──────

class ModuleEffectivenessTracker:
    """
    模块有效性追踪器

    追踪模块使用情况，检测无效模块，生成效果报告。
    """

    def __init__(self, check_interval: int = 300, ineffective_threshold: float = 0.1):
        """
        初始化模块有效性追踪器

        参数:
            check_interval: 检查间隔（秒）
            ineffective_threshold: 无效阈值（读写比）
        """
        self._check_interval = check_interval
        self._ineffective_threshold = ineffective_threshold
        self._lock = threading.RLock()

        # 模块注册表
        self._modules: typing.Dict[str, typing.Any] = {}

        # 访问记录
        self._access_records: typing.Dict[str, typing.List[ModuleAccessRecord]] = {}

        # 闭环检查清单
        self._checklists: typing.Dict[str, ModuleLoopChecklist] = {}

        # 统计信息
        self._write_counts: typing.Dict[str, int] = {}
        self._read_counts: typing.Dict[str, int] = {}

        # 定时检查线程
        self._running = True
        self._check_thread: typing.Optional[threading.Thread] = None

        self._start_periodic_check()

        logger.info("ModuleEffectivenessTracker initialized")

    def _start_periodic_check(self):
        """启动定时检查"""
        def check_loop():
            while self._running:
                try:
                    time.sleep(self._check_interval)
                    if self._running:
                        self._periodic_check()
                except Exception as e:
                    logger.error(f"Periodic check error: {e}")

        self._check_thread = threading.Thread(target=check_loop, daemon=True)
        self._check_thread.start()

    def on_initialize(self, module_id: str) -> None:
        """模块初始化回调"""
        with self._lock:
            checklist = self._ensure_checklist(module_id)
            checklist.initialized = True
            logger.debug(f"Module {module_id} initialized")

    def on_start(self, module_id: str) -> None:
        """模块启动回调"""
        with self._lock:
            checklist = self._ensure_checklist(module_id)
            checklist.started = True
            logger.debug(f"Module {module_id} started")

    def on_stop(self, module_id: str) -> None:
        """模块停止回调"""
        with self._lock:
            checklist = self._ensure_checklist(module_id)
            checklist.started = False
            logger.debug(f"Module {module_id} stopped")

    def _initialize_all_modules(self) -> None:
        """初始化所有模块"""
        with self._lock:
            for module_id in self._modules:
                self.on_initialize(module_id)

    def _ensure_checklist(self, module_id: str) -> ModuleLoopChecklist:
        """确保检查清单存在"""
        if module_id not in self._checklists:
            self._checklists[module_id] = ModuleLoopChecklist(module_id=module_id)
        return self._checklists[module_id]

    def _on_module_write(self, module_id: str, details: typing.Dict[str, typing.Any] = None) -> None:
        """模块写入回调"""
        self.record_access(module_id, "write", details)

    def _on_module_read(self, module_id: str, details: typing.Dict[str, typing.Any] = None) -> None:
        """模块读取回调"""
        self.record_access(module_id, "read", details)

    def _on_module_initialized(self, module_id: str) -> None:
        """模块已初始化回调"""
        self.on_initialize(module_id)

    def _on_check_request(self, module_id: str) -> None:
        """检查请求回调"""
        self._check_module(module_id)

    def record_access(self, module_id: str, access_type: str,
                     details: typing.Optional[typing.Dict[str, typing.Any]] = None) -> None:
        """
        记录访问

        参数:
            module_id: 模块 ID
            access_type: 访问类型 (read/write)
            details: 详情
        """
        with self._lock:
            # 创建记录
            record = ModuleAccessRecord(
                module_id=module_id,
                access_type=access_type,
                details=details or {},
            )

            # 存储记录
            if module_id not in self._access_records:
                self._access_records[module_id] = []
            self._access_records[module_id].append(record)

            # 限制记录数量
            if len(self._access_records[module_id]) > 1000:
                self._access_records[module_id] = self._access_records[module_id][-1000:]

            # 更新统计
            if access_type == "write":
                self._write_counts[module_id] = self._write_counts.get(module_id, 0) + 1
            else:
                self._read_counts[module_id] = self._read_counts.get(module_id, 0) + 1

            # 更新闭环状态
            self._update_loop_status(module_id)

    def _update_loop_status(self, module_id: str) -> None:
        """更新闭环状态"""
        checklist = self._ensure_checklist(module_id)

        # 检查是否被使用
        write_count = self._write_counts.get(module_id, 0)
        read_count = self._read_counts.get(module_id, 0)

        if write_count > 0 or read_count > 0:
            checklist.used = True

        # 检查是否有效
        if write_count > 0:
            ratio = read_count / write_count
            checklist.effective = ratio > self._ineffective_threshold

        checklist.last_check = datetime.datetime.now(datetime.timezone.utc)

    def get_effectiveness_level(self, module_id: str) -> EffectivenessLevel:
        """
        获取有效性级别

        参数:
            module_id: 模块 ID

        返回:
            EffectivenessLevel: 有效性级别
        """
        with self._lock:
            write_count = self._write_counts.get(module_id, 0)
            read_count = self._read_counts.get(module_id, 0)

            if write_count == 0 and read_count == 0:
                return EffectivenessLevel.UNKNOWN

            if write_count == 0:
                return EffectivenessLevel.HIGH

            ratio = read_count / write_count

            if ratio >= 1.0:
                return EffectivenessLevel.HIGH
            elif ratio >= 0.5:
                return EffectivenessLevel.MEDIUM
            elif ratio >= self._ineffective_threshold:
                return EffectivenessLevel.LOW
            else:
                return EffectivenessLevel.INEFFECTIVE

    def generate_report(self, module_id: str) -> EffectivenessReport:
        """
        生成报告

        参数:
            module_id: 模块 ID

        返回:
            EffectivenessReport: 有效性报告
        """
        with self._lock:
            return self._create_report(module_id)

    def _create_report(self, module_id: str) -> EffectivenessReport:
        """创建报告"""
        write_count = self._write_counts.get(module_id, 0)
        read_count = self._read_counts.get(module_id, 0)

        # 计算读写比
        ratio = read_count / max(1, write_count)

        # 获取最后活动时间
        last_activity = None
        if module_id in self._access_records and self._access_records[module_id]:
            last_activity = self._access_records[module_id][-1].timestamp

        # 获取有效性级别
        effectiveness_level = self.get_effectiveness_level(module_id)

        # 生成建议
        recommendations = self._generate_recommendations(module_id, effectiveness_level, ratio)

        return EffectivenessReport(
            module_id=module_id,
            effectiveness_level=effectiveness_level,
            write_count=write_count,
            read_count=read_count,
            read_write_ratio=ratio,
            last_activity=last_activity,
            recommendations=recommendations,
        )

    def _generate_recommendations(self, module_id: str, level: EffectivenessLevel,
                                ratio: float) -> typing.List[str]:
        """生成建议"""
        recommendations = []

        if level == EffectivenessLevel.INEFFECTIVE:
            recommendations.append(f"模块 {module_id} 读写比过低 ({ratio:.2f})，建议检查是否被正确使用")
            recommendations.append("考虑移除或重构该模块")

        elif level == EffectivenessLevel.LOW:
            recommendations.append(f"模块 {module_id} 读写比较低 ({ratio:.2f})，建议优化使用方式")

        elif level == EffectivenessLevel.UNKNOWN:
            recommendations.append(f"模块 {module_id} 未被使用，建议检查是否需要")

        return recommendations

    def get_inefficient_modules(self) -> typing.List[typing.Dict[str, typing.Any]]:
        """
        获取低效模块

        返回:
            List[Dict]: 低效模块列表
        """
        with self._lock:
            inefficient = []

            for module_id in self._modules:
                level = self.get_effectiveness_level(module_id)
                if level in (EffectivenessLevel.INEFFECTIVE, EffectivenessLevel.LOW):
                    report = self._create_report(module_id)
                    inefficient.append(report.to_dict())

            return inefficient

    def get_loop_status_summary(self) -> typing.Dict[str, typing.Any]:
        """
        获取闭环状态摘要

        返回:
            Dict: 状态摘要
        """
        with self._lock:
            total_modules = len(self._modules)
            initialized = sum(1 for c in self._checklists.values() if c.initialized)
            started = sum(1 for c in self._checklists.values() if c.started)
            used = sum(1 for c in self._checklists.values() if c.used)
            effective = sum(1 for c in self._checklists.values() if c.effective)

            return {
                "total_modules": total_modules,
                "initialized": initialized,
                "started": started,
                "used": used,
                "effective": effective,
                "checklists": {mid: c.to_dict() for mid, c in self._checklists.items()},
            }

    def _periodic_check(self) -> None:
        """定时检查"""
        logger.debug("Running periodic effectiveness check")
        self._check_all_modules()

    def _check_all_modules(self) -> None:
        """检查所有模块"""
        with self._lock:
            for module_id in list(self._modules.keys()):
                self._check_module(module_id)

    def _check_module(self, module_id: str) -> None:
        """检查单个模块"""
        checklist = self._ensure_checklist(module_id)

        # 检查是否被使用
        write_count = self._write_counts.get(module_id, 0)
        read_count = self._read_counts.get(module_id, 0)

        if write_count == 0 and read_count == 0:
            checklist.issues.append("Module not used")
        elif write_count > 0 and read_count == 0:
            checklist.issues.append("Module write-only")

        # 更新检查时间
        checklist.last_check = datetime.datetime.now(datetime.timezone.utc)

    def get_module_access_history(self, module_id: str, limit: int = 100) -> typing.List[typing.Dict[str, typing.Any]]:
        """
        获取模块访问历史

        参数:
            module_id: 模块 ID
            limit: 限制数量

        返回:
            List[Dict]: 访问历史
        """
        with self._lock:
            records = self._access_records.get(module_id, [])
            return [record.to_dict() for record in records[-limit:]]

    def register_module(self, module_id: str, module: typing.Any = None) -> None:
        """
        注册模块

        参数:
            module_id: 模块 ID
            module: 模块实例
        """
        with self._lock:
            self._modules[module_id] = module
            self._ensure_checklist(module_id)
            logger.debug(f"Registered module: {module_id}")

    def unregister_module(self, module_id: str) -> None:
        """
        注销模块

        参数:
            module_id: 模块 ID
        """
        with self._lock:
            if module_id in self._modules:
                del self._modules[module_id]

            if module_id in self._access_records:
                del self._access_records[module_id]

            if module_id in self._checklists:
                del self._checklists[module_id]

            if module_id in self._write_counts:
                del self._write_counts[module_id]

            if module_id in self._read_counts:
                del self._read_counts[module_id]

            logger.debug(f"Unregistered module: {module_id}")

    def reset_stats(self, module_id: typing.Optional[str] = None) -> None:
        """
        重置统计

        参数:
            module_id: 模块 ID（可选，None 表示全部）
        """
        with self._lock:
            if module_id:
                self._write_counts[module_id] = 0
                self._read_counts[module_id] = 0
                self._access_records[module_id] = []
                self._checklists[module_id] = ModuleLoopChecklist(module_id=module_id)
            else:
                self._write_counts.clear()
                self._read_counts.clear()
                self._access_records.clear()
                self._checklists.clear()

            logger.debug(f"Reset stats for: {module_id or 'all modules'}")

    def shutdown(self) -> None:
        """关闭追踪器"""
        self._running = False
        if self._check_thread and self._check_thread.is_alive():
            self._check_thread.join(timeout=5)


# ────── 单例管理 ──────

_tracker_instance: typing.Optional[ModuleEffectivenessTracker] = None
_instance_lock = threading.Lock()


def get_module_effectiveness_tracker(**kwargs) -> ModuleEffectivenessTracker:
    """获取全局模块有效性追踪器实例"""
    global _tracker_instance
    if _tracker_instance is None:
        with _instance_lock:
            if _tracker_instance is None:
                _tracker_instance = ModuleEffectivenessTracker(**kwargs)
    return _tracker_instance


def reset_module_effectiveness_tracker():
    """重置全局模块有效性追踪器实例"""
    global _tracker_instance
    with _instance_lock:
        if _tracker_instance:
            _tracker_instance.shutdown()
        _tracker_instance = None