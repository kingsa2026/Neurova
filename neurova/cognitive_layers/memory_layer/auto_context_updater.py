"""
自动上下文更新器 - Auto Context Updater

实现Neurova上下文机制的自动循环更新功能：
1. 定时压缩旧记忆（>30天）
2. 更新记忆温度（冷却机制）
3. 重建向量索引（保持搜索准确性）
4. 清理过期缓存

设计原则：
- 非阻塞后台运行
"""

import datetime
from neurova.core.logger import get_logger
import threading
import time
from typing import Any, Dict, Optional


logger = get_logger(__name__)


class AutoContextUpdater:
    """
    自动上下文更新器

    实现Neurova上下文机制的自动循环更新功能。
    """

    def __init__(
        self,
        memory_manager: Any = None,
        update_interval: int = 3600,  # 1小时
        compression_threshold_days: int = 30,
        temperature_decay_rate: float = 1.0,
    ):
        """
        初始化自动上下文更新器

        Args:
            memory_manager: 记忆管理器
            update_interval: 更新间隔（秒）
            compression_threshold_days: 压缩阈值（天）
            temperature_decay_rate: 温度衰减率
        """
        self.memory_manager = memory_manager
        self.update_interval = update_interval
        self.compression_threshold_days = compression_threshold_days
        self.temperature_decay_rate = temperature_decay_rate

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        # 审计 P1-E7：更新执行标志（trigger_update 与事件循环线程去重）
        self._update_in_progress_flag = threading.Lock()
        self._stats = {
            "total_updates": 0,
            "last_update": None,
            "compressed_memories": 0,
            "temperature_updates": 0,
            "index_rebuilds": 0,
            "cache_cleanups": 0,
        }

        logger.info("AutoContextUpdater 初始化完成")

    def start(self) -> None:
        """启动更新器"""
        if self._running:
            logger.warning("AutoContextUpdater 已经在运行")
            return

        self._running = True
        self._thread = threading.Thread(target=self._run_event_loop, daemon=True)
        self._thread.start()

        logger.info("AutoContextUpdater 启动")

    def stop(self) -> None:
        """停止更新器"""
        if not self._running:
            return

        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

        logger.info("AutoContextUpdater 停止")

    def _run_event_loop(self) -> None:
        """运行事件循环"""
        while self._running:
            try:
                self._perform_update()
                time.sleep(self.update_interval)
            except Exception as e:
                logger.error("AutoContextUpdater 更新失败: %s", e)
                time.sleep(60)  # 出错后等待1分钟

    def _perform_update(self) -> None:
        """执行更新"""
        with self._lock:
            start_time = time.time()

            try:
                # 1. 压缩旧记忆
                compressed = self._compress_old_memories()

                # 2. 更新记忆温度
                temperature_updates = self._update_temperature()

                # 3. 重建向量索引
                index_rebuilds = self._rebuild_vector_index()

                # 4. 清理过期缓存
                cache_cleanups = self._cleanup_cache()

                # 更新统计信息
                self._stats["total_updates"] += 1
                self._stats["last_update"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
                self._stats["compressed_memories"] += compressed
                self._stats["temperature_updates"] += temperature_updates
                self._stats["index_rebuilds"] += index_rebuilds
                self._stats["cache_cleanups"] += cache_cleanups

                duration = time.time() - start_time
                logger.info(
                    f"AutoContextUpdater 更新完成: 压缩 {compressed}, 温度更新 {temperature_updates}, "
                    f"索引重建 {index_rebuilds}, 缓存清理 {cache_cleanups} (耗时: {duration:.2f}s)"
                )

            except Exception as e:
                logger.error("AutoContextUpdater 更新失败: %s", e)

    def _compress_old_memories(self) -> int:
        """压缩旧记忆。

        M-14 遗留定性（2026-09-11）：现无"按年龄压缩"的真实后端。
        ``MemoryManager.compress_low_value_memories`` 是按低重要性候选+LLM 语义
        合并的破坏性操作，与本方法的">N 天"语义不同轴，且不允许由小时级后台
        循环静默触发；接入需产品决策（专用按龄压缩 API + 显式开关）。
        在此之前保持透明 no-op（计数如实为 0，不谎报成功）。
        """
        if not self.memory_manager:
            return 0

        try:
            # 获取旧记忆
            threshold = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
                days=self.compression_threshold_days
            )

            # 这里简化实现，实际应该调用记忆管理器的压缩方法
            logger.debug("压缩 %s 之前的记忆", threshold)

            return 0
        except Exception as e:
            logger.error("压缩旧记忆失败: %s", e)
            return 0

    def _update_temperature(self) -> int:
        """更新记忆温度（冷却衰减机制，真实生效）。

        BUG AUDIT M-14 修复：原实现为空 stub（仅 logger.debug + return 0），但
        ``_perform_update`` 仍上报"更新完成"并递增 ``total_updates`` → 冷却维护
        静默失效、记忆只升温不降温。现按空闲时长对每条记忆做温度衰减并落盘，
        使冷却机制真正运转（根因修复，非表面抹除）。
        """
        if not self.memory_manager:
            return 0

        get_all = getattr(self.memory_manager, "get_all_memories", None)
        update_one = getattr(self.memory_manager, "update_memory", None)
        if not callable(get_all) or not callable(update_one):
            return 0

        try:
            now = datetime.datetime.now(datetime.timezone.utc)
            base_decay = float(self.temperature_decay_rate)
            updated = 0

            for mem in get_all():
                mem_id = mem.get("id") if isinstance(mem, dict) else getattr(mem, "id", None)
                if not mem_id:
                    continue

                raw_temp = (
                    mem.get("temperature", 50.0) if isinstance(mem, dict)
                    else getattr(mem, "temperature", 50.0)
                )
                try:
                    temp = float(raw_temp)
                except (TypeError, ValueError):
                    temp = 50.0

                # 空闲越久降温越多；无访问时间则按基础衰减率冷却
                decay = base_decay
                if isinstance(mem, dict):
                    last_accessed = mem.get("last_accessed_at") or mem.get("updated_at")
                else:
                    last_accessed = getattr(mem, "last_accessed_at", None) or getattr(mem, "updated_at", None)
                if last_accessed:
                    try:
                        la = datetime.datetime.fromisoformat(str(last_accessed))
                        if la.tzinfo is None:
                            la = la.replace(tzinfo=datetime.timezone.utc)
                        idle_days = max(0.0, (now - la).total_seconds() / 86400.0)
                        decay = base_decay * (1.0 + idle_days)
                    except (ValueError, TypeError):
                        pass

                new_temp = max(0.0, min(100.0, temp - decay))
                if new_temp != temp:
                    update_one(mem_id, temperature=new_temp)
                    updated += 1

            logger.debug("记忆温度衰减更新 %d 条", updated)
            return updated
        except Exception as e:
            logger.error("更新记忆温度失败: %s", e)
            return 0

    def _rebuild_vector_index(self) -> int:
        """重建向量索引。

        M-14 遗留定性（2026-09-11）：``VectorIndexManager.sync_full`` 虽存在，
        但 VectorIndexManager 本身在 neurova/ 生产代码中从未被实例化（孤儿模块），
        MemoryManager 亦未持有索引管理器属性——无活后端可接，死接死属假进度。
        待记忆检索链路接入统一索引管理后再行对接；保持透明 no-op。
        """
        if not self.memory_manager:
            return 0

        try:
            # 重建向量索引
            logger.debug("重建向量索引")

            return 0
        except Exception as e:
            logger.error("重建向量索引失败: %s", e)
            return 0

    def _cleanup_cache(self) -> int:
        """清理过期缓存。

        M-14 遗留定性（2026-09-11）：memory_layer/cache.py 已废弃（shim 到
        neurova.core.cache），MemoryManager 未持有带 TTL 的可清缓存实例；
        现有缓存随请求生命周期存续，无跨周期积压。无真实清理目标，保持透明 no-op。
        """
        try:
            # 清理过期缓存
            logger.debug("清理过期缓存")

            return 0
        except Exception as e:
            logger.error("清理缓存失败: %s", e)
            return 0

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return self._stats.copy()

    def trigger_update(self) -> None:
        """手动触发更新"""
        if not self._running:
            logger.warning("AutoContextUpdater 未运行，无法触发更新")
            return

        # 审计 P1-E7：执行标志去重——事件循环线程可能正在 _perform_update，
        # 无条件开新线程会导致重叠并发更新（无互斥）
        if not self._update_in_progress_flag.acquire(blocking=False):
            logger.debug("手动触发更新跳过（已有更新在执行）")
            return
        threading.Thread(target=self._perform_update_with_flag, daemon=True).start()
        logger.info("手动触发更新")

    def _perform_update_with_flag(self) -> None:
        """持执行标志运行更新（配合 trigger_update 去重）"""
        try:
            self._perform_update()
        finally:
            self._update_in_progress_flag.release()


class ContextAutoUpdater:
    """
    上下文自动更新器（别名）

    AutoContextUpdater 的别名，提供相同的接口。
    """

    def __init__(self, *args, **kwargs):
        """初始化上下文自动更新器"""
        self._updater = AutoContextUpdater(*args, **kwargs)

    def __getattr__(self, name):
        """委托所有属性访问到内部更新器"""
        return getattr(self._updater, name)
