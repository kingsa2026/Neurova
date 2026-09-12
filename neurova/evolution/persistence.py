"""进化状态持久化基础设施。

AdaptiveToolWeights（closed_loop.py）是首个落盘组件；本模块把同款
"attach（幂等）+ 节流落盘"协议抽成可复用 mixin，供 PatternMiner /
ToolLifecycleManager / ExperienceFeedback 等纯内存进化状态复用。

与 weights 存量实现的两点差异：
- 统一原子写（tmp + os.replace）——规避 providers 配置丢失事故同款
  "非原子写、异常截断覆盖"根因；
- 未挂载（_persist_path=None）时零 IO 副作用，纯内存/测试语义零变化。
"""

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional, Union

from neurova.core.logger import get_logger

logger = get_logger(__name__)


class PersistedStateMixin:
    """JSON 状态文件持久化 mixin。

    子类实现 _snapshot_payload()（锁内快照由子类自行负责）与
    _restore_payload(data)（覆盖语义）。save/load 失败一律 warning
    不抛——落盘故障不阻断进化主链。
    """

    def _init_state_persistence(self, save_interval: float = 10.0) -> None:
        self._persist_path: Optional[Path] = None
        self._save_interval: float = save_interval
        self._last_save_at: float = 0.0

    def attach_persistence(self, path: Union[str, Path], save_interval: float = 10.0) -> None:
        """挂载持久化（仅首次生效；save_interval 为落盘节流秒数）。"""
        if getattr(self, "_persist_path", None) is not None:
            return
        self._persist_path = Path(path)
        self._save_interval = save_interval if save_interval > 0 else 0.0
        logger.info(
            "%s 持久化挂载: %s (interval=%ss)",
            type(self).__name__,
            self._persist_path,
            self._save_interval,
        )

    def _maybe_persist(self) -> None:
        """节流落盘（变更路径自动保存；未挂载时 no-op）。"""
        if self._persist_path is None:
            return
        now = time.time()
        if self._save_interval <= 0 or (now - self._last_save_at) >= self._save_interval:
            self.save()

    def save(self, path: Optional[Union[str, Path]] = None) -> bool:
        """落盘全部状态（快照取自子类钩子；原子写；失败 warning 不抛）。"""
        target = Path(path) if path is not None else self._persist_path
        if target is None:
            return False
        tmp = target.with_suffix(target.suffix + ".tmp")
        try:
            payload = self._snapshot_payload()
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(target)
            self._last_save_at = time.time()
            return True
        except Exception:  # noqa: BLE001 - 落盘失败不阻断状态更新
            logger.warning("%s 持久化保存失败: %s", type(self).__name__, target, exc_info=True)
            try:
                tmp.unlink(missing_ok=True)
            except Exception:  # noqa: BLE001
                pass
            return False

    def load(self, path: Union[str, Path]) -> bool:
        """从文件恢复状态（覆盖语义；缺失 → False；损坏 → 回退空态）。"""
        target = Path(path)
        try:
            if not target.exists():
                logger.debug("%s 持久化文件不存在（首次启动）: %s", type(self).__name__, target)
                return False
            data = json.loads(target.read_text(encoding="utf-8"))
            self._restore_payload(data)
            logger.info("%s 状态已从 %s 恢复", type(self).__name__, target)
            return True
        except Exception:  # noqa: BLE001 - 损坏文件回退空态，不阻断启动
            logger.warning(
                "%s 持久化加载失败（回退空态）: %s", type(self).__name__, target, exc_info=True
            )
            return False

    # ---- 子类钩子 ----

    def _snapshot_payload(self) -> Dict[str, Any]:
        raise NotImplementedError

    def _restore_payload(self, data: Dict[str, Any]) -> None:
        raise NotImplementedError
