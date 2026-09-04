"""ProviderUsageCollector — provider 真账单采集器（P1-13，OpenClaw 启发）

OpenClaw `src/infra/provider-usage*.ts` 的核心思想：配额/余额/30 天趋势从
provider 后台 API 直拉，与 token 估值分离——这是"sensetime 网关不回传 usage"
困局的正解（流内抠不到的账，从后台拿）。

Neurova 落地纪律（增量实施约束）：
- **默认关**：install_provider_usage_collector() 显式装配才存在（对齐
  工具熔断器惯例）；未安装时零开销、零行为变化。
- **逐 provider 开**：register_provider(provider_id, fetch) 注册各后台
  适配函数；无注册 = 无采集。fetch 由调用方实现（各家 API/凭证差异大，
  框架只管调度、落盘、错误隔离）。
- 快照落 provider_usage SQLite 表（含 raw JSON），env
  NEUROVA_PROVIDER_USAGE_DB 可覆盖（测试隔离）；任何失败静默——统计
  副路径绝不阻断主流程。
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

DEFAULT_DB_PATH = Path("data") / "provider_usage.db"

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS provider_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    plan TEXT,
    quota_remaining REAL,
    currency TEXT,
    balance REAL,
    window_days INTEGER,
    raw TEXT DEFAULT '{}'
)
"""
_CREATE_INDEX = "CREATE INDEX IF NOT EXISTS idx_pu_provider_ts ON provider_usage (provider_id, ts)"


class ProviderUsageCollector:
    """provider 后台账单采集器（显式 install，逐 provider 注册）。"""

    _instance: Optional["ProviderUsageCollector"] = None
    _instance_lock = threading.Lock()

    def __init__(self, db_path: Optional[str] = None):
        self._db_path = (
            db_path
            or os.environ.get("NEUROVA_PROVIDER_USAGE_DB")
            or str(DEFAULT_DB_PATH)
        )
        self._lock = threading.RLock()
        # provider_id -> fetch 协程/普通函数（返回 Dict 快照）
        self._fetchers: Dict[str, Callable[[], Dict[str, Any]]] = {}
        self._errors: List[Dict[str, Any]] = []
        self._init_db()

    # ── install/uninstall（默认关门面） ──────────────────────────────────

    @classmethod
    def install(cls) -> "ProviderUsageCollector":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
        return cls._instance

    @classmethod
    def uninstall(cls) -> None:
        with cls._instance_lock:
            cls._instance = None

    @classmethod
    def get_installed(cls) -> Optional["ProviderUsageCollector"]:
        with cls._instance_lock:
            return cls._instance

    # ── 注册与采集 ────────────────────────────────────────────────────────

    def register_provider(self, provider_id: str, fetch: Callable[[], Dict[str, Any]]) -> None:
        """注册 provider 后台账单适配函数（幂等覆盖）。"""
        with self._lock:
            self._fetchers[provider_id] = fetch

    def collect_all(self) -> int:
        """拉取全部已注册 provider 的快照并落盘。返回成功数。

        单 provider 失败只记录到 errors，不影响其他 provider。
        """
        with self._lock:
            fetchers = dict(self._fetchers)
        ok = 0
        for provider_id, fetch in fetchers.items():
            try:
                snapshot = fetch()
                if not isinstance(snapshot, dict):
                    raise TypeError("fetch 必须返回 dict")
                self._persist(provider_id, snapshot)
                ok += 1
            except Exception as e:  # noqa: BLE001 - 单点失败隔离
                logger.debug("provider %s 账单拉取失败: %s", provider_id, e)
                with self._lock:
                    self._errors.append(
                        {
                            "provider_id": provider_id,
                            "error": str(e)[:200],
                            "ts": datetime.now().isoformat(timespec="seconds"),
                        }
                    )
        return ok

    def get_errors(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._errors)

    # ── 持久化与查询 ──────────────────────────────────────────────────────

    def _init_db(self) -> None:
        try:
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                with self._connect() as conn:
                    conn.execute(_CREATE_TABLE)
                    conn.execute(_CREATE_INDEX)
        except Exception as e:
            logger.debug("provider_usage DB 初始化失败（统计副路径降级）: %s", e)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _persist(self, provider_id: str, snapshot: Dict[str, Any]) -> None:
        try:
            with self._lock:
                with self._connect() as conn:
                    conn.execute(
                        """
                        INSERT INTO provider_usage
                            (ts, provider_id, plan, quota_remaining, currency, balance, window_days, raw)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            datetime.now().isoformat(timespec="seconds"),
                            provider_id,
                            snapshot.get("plan"),
                            snapshot.get("quota_remaining"),
                            snapshot.get("currency"),
                            snapshot.get("balance"),
                            snapshot.get("window_days"),
                            json.dumps(snapshot, ensure_ascii=False),
                        ),
                    )
        except Exception as e:
            logger.debug("provider_usage 落盘失败: %s", e)

    def get_collected_usage(self, provider_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """读取采集快照（最新在前）。异常回退空列表（诚实统计）。"""
        try:
            where, params = ("WHERE provider_id = ?", [provider_id]) if provider_id else ("", [])
            with self._lock:
                with self._connect() as conn:
                    rows = conn.execute(
                        f"SELECT * FROM provider_usage {where} ORDER BY ts DESC LIMIT 200",
                        params,
                    ).fetchall()
            return [
                {
                    "provider_id": r["provider_id"],
                    "ts": r["ts"],
                    "plan": r["plan"],
                    "quota_remaining": r["quota_remaining"],
                    "currency": r["currency"],
                    "balance": r["balance"],
                    "window_days": r["window_days"],
                    "raw": json.loads(r["raw"]) if r["raw"] else {},
                }
                for r in rows
            ]
        except Exception:
            return []


# ── 模块级门面（对齐工具熔断器 install 惯例） ────────────────────────────


def install_provider_usage_collector() -> ProviderUsageCollector:
    """显式装配采集器（幂等）。未装配时系统无采集行为（默认关）。"""
    return ProviderUsageCollector.install()


def uninstall_provider_usage_collector() -> None:
    ProviderUsageCollector.uninstall()


def reset_provider_usage_collector() -> None:
    """测试隔离用：等价 uninstall"""
    ProviderUsageCollector.uninstall()
