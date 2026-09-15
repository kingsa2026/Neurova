# -*- coding: utf-8 -*-
"""三库路由（Wave H-W1，三层技能库存储地基）

词汇沿用退役孤岛 SkillPoolType（吸收清单见 docs §7.5）：
- ``agent``：agent 私库 = ``data/agents/{agent_id}/skills``（现状，零迁移）；
- ``user``：用户私库 = ``data/users/{ukey}/skills``；
- ``public``：公共库 = ``data/public/skills``。

存储引擎**单源 SkillService**（原子写/RLock/漏斗/trust/修订链全复用），
本模块只做路由 + 同进程单例化。单例化是并发正确性设计：SkillService 锁是
实例级，多 agent 并发 flush 同一 user/public 库时跨实例 last-writer-wins
丢更新——同键同实例后实例锁即足够（桌面单进程部署成立；多进程 worker
场景需文件锁升级，已在台账 §7.2 备注）。

用户键命名空间（防孤岛教训：user_id 裸拼目录的路径注入面）：
``u:{jwt_sub}`` 内部账号、``ch:{channel}:{sender_id}`` 渠道外部身份；
严格白名单校验，非法即抛 ValueError。
"""
from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from neurova.core.logger import get_logger

logger = get_logger(__name__)

__all__ = [
    "POOL_AGENT",
    "POOL_USER",
    "POOL_PUBLIC",
    "normalize_user_key",
    "resolve_library_dir",
    "from_dir_token",
    "get_library",
    "reset_libraries_for_tests",
]

POOL_AGENT = "agent"
POOL_USER = "user"
POOL_PUBLIC = "public"
_VALID_POOLS = (POOL_AGENT, POOL_USER, POOL_PUBLIC)

# 测试注入点：monkeypatch 此值即整体切换库根
_BASE_DIR = Path("data")

# 键白名单：u:<alnum_-+ .> / ch:<alnum_-+ .>:<alnum_-+ .>
# 禁 "/" ".." 空格 冒号嵌套——目录名安全 = 路径注入第一道闸
_KEY_RE = re.compile(r"^(?:u:[A-Za-z0-9_.\-]+|ch:[A-Za-z0-9_.\-]+:[A-Za-z0-9_.\-]+)$")

_libraries: Dict[Tuple[str, str], Tuple[str, object]] = {}
_libraries_lock = threading.RLock()


def normalize_user_key(key: Optional[str]) -> Optional[str]:
    """用户键校验/归一：None/"" → None（无用户库视图）；非法抛 ValueError。"""
    if key is None:
        return None
    s = str(key).strip()
    if not s:
        return None
    if not _KEY_RE.match(s):
        raise ValueError(f"非法用户库键: {key!r}（需 u:… / ch:…:… 命名空间且不含路径字符）")
    # 纯点号体（u:.. / u:.）过字符类但构成路径语义——要求至少含一个字母数字
    for seg in s.split(":")[1:]:
        if not re.search(r"[A-Za-z0-9]", seg):
            raise ValueError(f"非法用户库键段: {key!r}")
    return s


def _dir_token(key: str) -> str:
    """键转目录名：':' → '%3A'（: 在 Windows 文件名非法；键白名单不含 %，
    故 from_dir_token 严格互逆——旧 :→_ 编码对 ch: 双冒号键反解不闭环，
    公共升级广播会产出非法 dst_owner）。"""
    return key.replace(":", "%3A")


def from_dir_token(token: str) -> str:
    """目录名转回用户键（_dir_token 的逆，广播扫描用）。"""
    return token.replace("%3A", ":")


def resolve_library_dir(pool: str, owner_key: str = "") -> Path:
    """三库目录布局的唯一权威。agent 的 owner_key=agent_id。"""
    if pool not in _VALID_POOLS:
        raise ValueError(f"未知技能库类型: {pool!r}")
    if pool == POOL_PUBLIC:
        return _BASE_DIR / "public" / "skills"
    if pool == POOL_USER:
        key = normalize_user_key(owner_key)
        if not key:
            raise ValueError("user 库必须携带合法 owner_key")
        return _BASE_DIR / "users" / _dir_token(key) / "skills"
    token = str(owner_key or "").strip()
    if not token or not re.match(r"^[A-Za-z0-9_\-]+$", token):
        raise ValueError(f"非法 agent id（agent 库路由）: {owner_key!r}")
    return _BASE_DIR / "agents" / token / "skills"


def get_library(pool: str, owner_key: str = ""):
    """获取库的 SkillService 实例（同进程单例，目录感知缓存）。

    缓存键 (pool, dir_token)；条目记录构造时的目录——_BASE_DIR 被测试
    切换后旧实例自动失效重建（防跨测试单例污染）。
    """
    from neurova.skills import skill_service as _ss_mod

    directory = resolve_library_dir(pool, owner_key)
    cache_key = (pool, str(directory))
    with _libraries_lock:
        cached = _libraries.get(cache_key)
        if cached is not None and str(getattr(cached[1], "skills_dir", "")) == str(directory):
            return cached[1]
        kwargs: Dict[str, object] = {"skills_dir": str(directory)}
        if pool == POOL_AGENT:
            kwargs = {"agent_id": owner_key, "skills_dir": str(directory)}
        elif pool == POOL_USER:
            kwargs = {"agent_id": f"ulib:{_dir_token(owner_key)}", "skills_dir": str(directory)}
        else:
            kwargs = {"agent_id": "public", "skills_dir": str(directory)}
        service = _ss_mod.SkillService(**kwargs)
        _libraries[cache_key] = (str(directory), service)
        return service


def reset_libraries_for_tests() -> None:
    """测试隔离：清空单例表（不关实例——SkillService 无连接句柄）。"""
    with _libraries_lock:
        _libraries.clear()


# ── Wave H-W4 技能流转（副本 + 血缘，吸收孤岛 push 词汇）────


def apply_transfer(
    dst_pool: str,
    dst_owner: str,
    src_pool: str,
    src_owner: str,
    skill_id: str,
    actor: str = "",
    override_version: str = "",
) -> Dict[str, Any]:
    """把源库技能流转（复制）到目标库；目标已有同源副本则原地升级。

    语义定案（对比文档 §7.5 孤岛吸收）：**副本+血缘**，非引用——
    - 首流转：目标库新条（pool_type/owner 落款、config 带 transferred_from
      血缘）；出生 trust=provisional（register_auto_skill 既有语义），须目标
      库独立攒成功观测晋升；
    - 再流转（同 transferred_from 源）：update_auto_skill 原地 bump——
      修订链追加 + usage/trust 账本保留（绝不走 install 重建，force 清零坑）；
    - 异源同名或本地同名（无血缘）：一律拒绝（防串库顶替/静默覆盖本地实现）。

    override_version：确认卡签发时刻的版本快照优先于源当前版本（防卡片在途、
    源侧回滚导致把旧版当升级落给目标）。
    返回 {"ok", "action": created|upgraded|rejected, "error"?}
    """
    try:
        src = get_library(src_pool, src_owner)
    except ValueError as bad:
        return {"ok": False, "action": "rejected", "error": str(bad)}
    src_entry = src.get_skill_info(skill_id)
    if src_entry is None:
        return {"ok": False, "action": "rejected", "error": f"源技能不存在: {src_pool}/{skill_id}"}
    eff_version = str(override_version or "").strip() or str(src_entry.get("version") or "1.0.0")

    dst = get_library(dst_pool, dst_owner)
    manifest = src_entry.get("manifest") or {}
    src_cfg = dict(manifest.get("config") or {})
    lineage = {
        "transferred_from": {"pool": src_pool, "owner": src_owner, "skill_id": str(skill_id)},
        "transferred_by": str(actor or ""),
    }
    out_cfg = {**src_cfg, **lineage}

    existing = dst.get_skill_info(skill_id)
    if existing is None:
        ok = dst.register_auto_skill(
            skill_id,
            name=str(src_entry.get("name") or skill_id),
            description=str(src_entry.get("description") or ""),
            version=eff_version,
            config=out_cfg,
            manifest_source=str(manifest.get("source") or "auto"),
            pool_type=dst_pool,
            owner_user_id=dst_owner or "",
        )
        return {"ok": bool(ok), "action": "created" if ok else "rejected"}

    ex_cfg = (existing.get("manifest") or {}).get("config") or {}
    ex_from = ex_cfg.get("transferred_from") or {}
    if not ex_from:
        return {
            "ok": False,
            "action": "rejected",
            "error": "目标库已存在同名本地技能（无流转血缘），拒绝顶替",
        }
    if ex_from.get("pool") != src_pool or str(ex_from.get("owner") or "") != str(src_owner or ""):
        return {
            "ok": False,
            "action": "rejected",
            "error": f"目标同名技能来自其他源（{ex_from.get('pool')}），拒绝顶替",
        }
    ok = dst.update_auto_skill(
        skill_id,
        version=eff_version,
        config={**ex_cfg, **out_cfg},
        name=str(src_entry.get("name") or skill_id),
        description=str(src_entry.get("description") or ""),
    )
    return {"ok": bool(ok), "action": "upgraded" if ok else "rejected"}
