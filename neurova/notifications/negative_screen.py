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
import logging
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


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

        logger.info("NegativeScreenConfigManager 初始化完成: %s", self._data_dir)

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
        推送 RSI 结果到负一屏

        Args:
            config: 用户配置
            rsi_result: RSI 迭代结果

        Returns:
            推送结果
        """
        # 格式化 RSI 结果
        iteration = rsi_result.get("iteration", 0)
        improvements = rsi_result.get("improvements", 0)
        convergence_score = rsi_result.get("convergence_score", 0.0)
        status = rsi_result.get("status", "unknown")

        task_name = f"RSI 迭代 #{iteration}"
        task_content = f"""## RSI 自我优化报告

### 迭代信息
- **迭代次数**: {iteration}
- **优化数量**: {improvements}
- **收敛分数**: {convergence_score * 100:.2f}%%
- **状态**: {status}

### 详细结果
```json
{json.dumps(rsi_result, indent=2, ensure_ascii=False)}
```
"""
        task_result = f"RSI 迭代 {iteration} 完成，{improvements} 项优化，收敛分数 {convergence_score * 100:.2f}%%"

        return await self.push_task(
            config=config,
            task_name=task_name,
            task_content=task_content,
            task_result=task_result,
            task_id=f"rsi_{iteration}_{uuid.uuid4().hex[:8]}",
        )

    def _build_push_data(
        self,
        config: NegativeScreenConfig,
        task_name: str,
        task_content: str,
        task_result: str,
        task_id: str,
    ) -> Dict[str, Any]:
        """构建推送数据"""
        return {
            "data": {
                "authCode": config.auth_code,
                "msgContent": [
                    {
                        "msgId": task_id,
                        "scheduleTaskId": task_id,
                        "summary": task_name,
                        "result": task_result,
                        "content": task_content,
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

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    push_url,
                    json=push_data,
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
