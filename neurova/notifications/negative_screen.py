"""
负一屏推送模块 - Negative Screen Push Module

功能：
1. 用户级 authCode 配置管理
2. 负一屏推送执行
3. 推送结果追踪

架构：
- NegativeScreenConfig: 配置数据结构
- NegativeScreenConfigManager: 配置管理器（用户隔离）
- NegativeScreenPusher: 推送执行器
- PushResult: 推送结果
"""

from __future__ import annotations

import json
from neurova.core.logger import get_logger
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = get_logger(__name__)


# ─── 数据结构 ─────────────────────────────────────────────────────────────────


@dataclass
class PushResult:
    """推送结果"""

    success: bool
    task_id: Optional[str] = None
    response_code: Optional[str] = None
    error: Optional[str] = None
    push_time: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class NegativeScreenConfig:
    """负一屏配置（用户级）"""

    user_id: str
    auth_code: Optional[str] = None
    enabled: bool = False
    push_url: str = "https://hiboard-claw-drcn.ai.dbankcloud.cn/distribution/message/cloud/claw/msg/upload"
    timeout: int = 30
    max_content_length: int = 5000

    @property
    def masked_auth_code(self) -> Optional[str]:
        """获取脱敏的 authCode"""
        if not self.auth_code:
            return None
        if len(self.auth_code) <= 4:
            return self.auth_code + "***"
        return self.auth_code[:4] + "***"

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            "user_id": self.user_id,
            "auth_code": self.auth_code,
            "enabled": self.enabled,
            "push_url": self.push_url,
            "timeout": self.timeout,
            "max_content_length": self.max_content_length,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> NegativeScreenConfig:
        """从字典反序列化"""
        return cls(
            user_id=data.get("user_id", ""),
            auth_code=data.get("auth_code"),
            enabled=data.get("enabled", False),
            push_url=data.get("push_url", cls.push_url),
            timeout=data.get("timeout", 30),
            max_content_length=data.get("max_content_length", 5000),
        )


# ─── 配置管理器 ──────────────────────────────────────────────────────────────


class NegativeScreenConfigManager:
    """
    负一屏配置管理器（用户隔离）

    每个用户独立的 authCode 配置，存储在独立的 JSON 文件中。
    """

    def __init__(self, data_dir: str = None):
        """
        初始化配置管理器

        Args:
            data_dir: 数据存储目录
        """
        self._data_dir = Path(data_dir or "data/negative_screen")
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

        # 缓存
        self._cache: Dict[str, NegativeScreenConfig] = {}

        self._migrate_legacy_default_user()

        logger.info("NegativeScreenConfigManager 初始化完成: %s", self._data_dir)

    def _migrate_legacy_default_user(self) -> None:
        """一次性口径迁移（2026-09-12）：设置端点旧实现读从未注入的
        request.state.user_id，配置恒存 "default_user"；与通知/统计侧认证
        口径 "default" 分裂，自动推送链 get_config 永不命中。存量文件迁到
        default.json（仅当目标不存在，防覆盖新数据）。"""
        legacy = self._data_dir / "default_user.json"
        target = self._data_dir / "default.json"
        if not legacy.exists() or target.exists():
            return
        try:
            data = json.loads(legacy.read_text(encoding="utf-8"))
            data["user_id"] = "default"
            target.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            legacy.unlink()
            logger.info("负一屏配置口径迁移: default_user.json → default.json")
        except Exception as e:
            logger.error("负一屏配置口径迁移失败: %s", e)

    def _get_config_path(self, user_id: str) -> Path:
        """获取用户配置文件路径"""
        # 使用 user_id 作为文件名（需要清理特殊字符）
        safe_user_id = user_id.replace("/", "_").replace("\\", "_").replace(":", "_")
        return self._data_dir / f"{safe_user_id}.json"

    def get_config(self, user_id: str) -> Optional[NegativeScreenConfig]:
        """
        获取用户配置

        Args:
            user_id: 用户ID

        Returns:
            配置对象，不存在返回 None
        """
        with self._lock:
            # 先检查缓存
            if user_id in self._cache:
                return self._cache[user_id]

            # 从文件加载
            config_path = self._get_config_path(user_id)
            if not config_path.exists():
                return None

            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                config = NegativeScreenConfig.from_dict(data)
                self._cache[user_id] = config

                logger.debug("加载用户配置: %s", user_id)
                return config

            except Exception as e:
                logger.error("加载用户配置失败: %s, error=%s", user_id, e)
                return None

    def save_config(self, config: NegativeScreenConfig) -> bool:
        """
        保存用户配置

        Args:
            config: 配置对象

        Returns:
            是否保存成功
        """
        with self._lock:
            try:
                config_path = self._get_config_path(config.user_id)

                with open(config_path, "w", encoding="utf-8") as f:
                    json.dump(config.to_dict(), f, ensure_ascii=False, indent=2)

                # 更新缓存
                self._cache[config.user_id] = config

                logger.info("保存用户配置: %s", config.user_id)
                return True

            except Exception as e:
                logger.error("保存用户配置失败: %s, error=%s", config.user_id, e)
                return False

    def delete_config(self, user_id: str) -> bool:
        """
        删除用户配置

        Args:
            user_id: 用户ID

        Returns:
            是否删除成功
        """
        with self._lock:
            try:
                config_path = self._get_config_path(user_id)

                if config_path.exists():
                    config_path.unlink()

                # 从缓存中移除
                self._cache.pop(user_id, None)

                logger.info("删除用户配置: %s", user_id)
                return True

            except Exception as e:
                logger.error("删除用户配置失败: %s, error=%s", user_id, e)
                return False

    def list_configs(self) -> List[NegativeScreenConfig]:
        """
        列出所有配置

        Returns:
            配置列表
        """
        with self._lock:
            configs = []

            for config_file in self._data_dir.glob("*.json"):
                try:
                    with open(config_file, "r", encoding="utf-8") as f:
                        data = json.load(f)

                    config = NegativeScreenConfig.from_dict(data)
                    configs.append(config)

                except Exception as e:
                    logger.warning("读取配置文件失败: %s, error=%s", config_file, e)

            return configs

    def clear_cache(self) -> None:
        """清除缓存"""
        with self._lock:
            self._cache.clear()


# ─── 推送执行器 ──────────────────────────────────────────────────────────────


class NegativeScreenPusher:
    """
    负一屏推送执行器

    负责将任务结果推送到华为负一屏服务。
    """

    def __init__(self, timeout: int = 30, max_content_length: int = 5000):
        """
        初始化推送器

        Args:
            timeout: 超时时间（秒）
            max_content_length: 最大内容长度
        """
        self._timeout = timeout
        self._max_content_length = max_content_length

    async def push_task(
        self,
        config: NegativeScreenConfig,
        task_name: str,
        task_content: str,
        task_result: str = "任务已完成",
        task_id: str = None,
    ) -> PushResult:
        """
        推送任务到负一屏

        Args:
            config: 用户配置
            task_name: 任务名称
            task_content: 任务内容（Markdown）
            task_result: 任务结果
            task_id: 任务ID（可选，自动生成）

        Returns:
            推送结果
        """
        # 验证配置
        if not config.enabled:
            return PushResult(
                success=False,
                error="负一屏推送功能已禁用",
            )

        if not config.auth_code:
            return PushResult(
                success=False,
                error="auth_code 未设置，请在设置页面配置",
            )

        # 验证内容长度
        if len(task_content) > self._max_content_length:
            task_content = task_content[: self._max_content_length] + "\n\n... (内容已截断)"

        # 生成任务ID
        if not task_id:
            task_id = f"{task_name}_{uuid.uuid4().hex[:8]}"

        # 构建推送数据
        push_data = self._build_push_data(
            config=config,
            task_name=task_name,
            task_content=task_content,
            task_result=task_result,
            task_id=task_id,
        )

        # 执行推送
        return await self._execute_push(config.push_url, push_data, task_id)

    async def push_rsi_result(
        self,
        config: NegativeScreenConfig,
        rsi_result: Dict[str, Any],
    ) -> PushResult:
        """
        推送 RSI 摘要到负一屏

        入参口径 = ``neurova.evolution.rsi.result_summary.summarize_rsi_result``
        的输出（即对话响应里的 ``ctx.result["rsi"]``）：
        ``{status, applied_count, gain, phase_advanced, measure_state,
        evidenced_cases, placeholder_systems, turn?, stale?}``。

        历史实现读 ``iteration/improvements/convergence_score/status`` —— 与
        RSIOrchestrator.run_iteration 的真实输出（convergence/applied_count/
        gain/phase_advanced）名字全不匹配，且 ``convergence`` 是 dict，
        ``convergence_score * 100`` 一旦拿到真实结果就 TypeError。真接线前
        这里只会静默显示全默认值，接线后直接报错，故同一并收口。

        两个输入形态都接受（摘要 / 原始 run_iteration 返回值），字段名一律
        按真实契约取——由摘要模块统一裁剪，避免第二套字段解释。

        Args:
            config: 用户配置
            rsi_result: RSI 摘要（或原始迭代结果 dict）

        Returns:
            推送结果
        """
        from neurova.evolution.rsi.result_summary import summarize_rsi_result

        raw = rsi_result if isinstance(rsi_result, dict) else {}
        # 摘要口径统一由 result_summary 决定；形态不符时按"全默认值"渲染，
        # 但不再自带一份字段清单（那是第二套字段解释，会与摘要契约漂移）
        summary = summarize_rsi_result(raw) or {}

        status = str(summary.get("status") or "unknown")
        applied_count = summary.get("applied_count") or 0
        gain = summary.get("gain") or 0.0
        phase_advanced = bool(summary.get("phase_advanced"))
        # 增益为 0 有两种相反的成因：确实没有改善空间，或根本量不出来（工单 008）。
        # 前者降频巡检即可，后者要去修测量——所以停滞原因必须上推送面。
        measure_state = str(summary.get("measure_state") or "unknown")
        evidenced_cases = summary.get("evidenced_cases")
        evidence_label = (
            f"有证据用例 {evidenced_cases} 例"
            if isinstance(evidenced_cases, int)
            else "本轮未做前后测量"
        )
        # 缺席名单要成行展示，不能只躺在末尾的 raw JSON 里：
        # "应用优化数 0"有两种相反的成因（没改善空间 / 根本没装配系统）
        absent = summary.get("placeholder_systems")
        absent_line = f"- **缺席闭环系统**: {', '.join(absent)}\n" if absent else ""
        turn = raw.get("turn")

        iteration_label = f"#{turn}" if turn is not None else ""
        task_name = f"RSI 迭代{iteration_label}".rstrip()
        task_content = f"""## RSI 自我优化报告

### 迭代信息
- **收敛状态**: {status}
- **应用优化数**: {applied_count}
- **实测增益**: {gain:+.4f}
{absent_line}- **度量证据**: {measure_state}（{evidence_label}）
- **部署阶段推进**: {"是" if phase_advanced else "否"}

### 迭代结果
```json
{json.dumps(raw, indent=2, ensure_ascii=False, default=str)}
```
"""
        task_result = f"RSI 迭代{iteration_label} 完成，状态 {status}，应用 {applied_count} 项优化，增益 {gain:+.4f}"

        return await self.push_task(
            config=config,
            task_name=task_name,
            task_content=task_content,
            task_result=task_result,
            task_id=f"rsi_{turn if turn is not None else 'latest'}_{uuid.uuid4().hex[:8]}",
        )

    def _build_push_data(
        self,
        config: NegativeScreenConfig,
        task_name: str,
        task_content: str,
        task_result: str,
        task_id: str,
    ) -> Dict[str, Any]:
        """构建推送数据（对齐官方 today-task skill 标准数据格式，字段必填性见 SKILL.md）"""
        return {
            "data": {
                "authCode": config.auth_code,
                "msgContent": [
                    {
                        "msgId": task_id,
                        "scheduleTaskId": task_id,
                        "scheduleTaskName": task_name,
                        "summary": task_name,
                        "result": task_result,
                        "content": task_content,
                        "source": "Neurova",
                        "taskFinishTime": int(time.time()),
                    }
                ],
            }
        }

    async def _execute_push(
        self,
        push_url: str,
        push_data: Dict[str, Any],
        task_id: str,
    ) -> PushResult:
        """执行推送请求"""
        try:
            import aiohttp

            # 华为 HiBoard 网关校验请求头：x-trace-id 缺失/为空直接拒绝
            # （"Parameter x-trace-id is empty"），契约对齐官方 today-task skill
            trace_id = f"neurova-task-push-{int(time.time())}-{uuid.uuid4().hex[:8]}"
            headers = {
                "Content-Type": "application/json; charset=utf-8",
                "User-Agent": "Neurova-TaskPusher/1.0",
                "x-trace-id": trace_id,
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    push_url,
                    json=push_data,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=self._timeout),
                ) as response:
                    response_data = await response.json()

                    response_code = response_data.get("code", "")
                    success = response_code == "0000000000"

                    if success:
                        logger.info("负一屏推送成功: %s", task_id)
                        return PushResult(
                            success=True,
                            task_id=task_id,
                            response_code=response_code,
                            push_time=str(uuid.uuid4()),  # 使用 UUID 作为时间戳
                            metadata=response_data,
                        )
                    else:
                        error_msg = response_data.get("desc", "未知错误")
                        logger.warning("负一屏推送失败: %s, code=%s, desc=%s", task_id, response_code, error_msg)
                        return PushResult(
                            success=False,
                            task_id=task_id,
                            response_code=response_code,
                            error=error_msg,
                        )

        except ImportError:
            logger.error("aiohttp 未安装，无法执行推送")
            return PushResult(
                success=False,
                error="aiohttp 未安装，请安装: pip install aiohttp",
            )
        except Exception as e:
            logger.error("负一屏推送异常: %s, error=%s", task_id, e)
            return PushResult(
                success=False,
                task_id=task_id,
                error=str(e),
            )


# ─── 工厂函数 ────────────────────────────────────────────────────────────────


def create_negative_screen_config_manager(
    data_dir: str = None,
) -> NegativeScreenConfigManager:
    """创建配置管理器实例"""
    return NegativeScreenConfigManager(data_dir=data_dir)


def create_negative_screen_pusher(
    timeout: int = 30,
    max_content_length: int = 5000,
) -> NegativeScreenPusher:
    """创建推送器实例"""
    return NegativeScreenPusher(
        timeout=timeout,
        max_content_length=max_content_length,
    )
