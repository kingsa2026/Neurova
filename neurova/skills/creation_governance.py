"""Server-owned execution evidence and conservative structural skill identity.

No model-supplied counters are accepted. SQLite serializes creation across service
instances/processes; manifests remain in place, including all historical entries.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import copy
import hashlib
import json
import sqlite3
import threading
import uuid
from typing import Dict

from neurova.core.logger import get_logger

logger = get_logger(__name__)

MIN_SUCCESSES = 3
_locks = {}
_locks_guard = threading.RLock()
_execution = ContextVar("skill_creation_execution", default=None)


def normalize_steps(steps):
    if not isinstance(steps, list) or not steps:
        return []
    normalized = []
    for step in steps:
        if isinstance(step, str):
            tool, params = step, {}
        elif isinstance(step, dict):
            tool = step.get("tool") or step.get("name") or step.get("tool_name")
            params = step.get("params", step.get("parameters", {}))
        else:
            raise ValueError("Invalid skill step")
        if not isinstance(tool, str) or not tool.strip() or not isinstance(params, dict):
            raise ValueError("Invalid skill tool/params")
        # Do not trim parameter values, sort steps, or discard repeated tools.
        normalized.append({"tool": tool.strip(), "params": copy.deepcopy(params)})
    return normalized


def normalize_purpose(purpose=""):
    """业务意图归一：大小写折叠 + 空白折叠。三种工具序列命名方案共用。"""
    return " ".join(str(purpose or "").casefold().split())


def fingerprint(steps, purpose=""):
    """结构身份 = 工具序列 + 参数 + 业务意图，三者全吸收。

    历史缺陷（P1 统一指纹）：旧实现只在**所有**步骤 params 为空时才吸收
    purpose，于是同一业务意图的两种真实形态（带参步 / 裸工具名）产出两个
    身份——"同一技能被封装成两条"。修复后 purpose 恒为身份的一部分：
      - 带参步：identity = {steps(含参), purpose}
      - 裸工具名：identity = {steps(裸名), purpose}
    purpose 为空时（旧 API 的缺省调用）退回纯结构身份，向后兼容。
    """
    steps = normalize_steps(steps)
    if not steps:
        return None
    identity = {"steps": steps}
    # purpose 恒为身份的一部分（空串也占位）：否则**同一批任务**里有的证据带
    # 意图、有的不带就会落到两个身份——计量分叉（任务计数/成功数各算一半）。
    # 空意图 = "未标注意图"这一等价类，不是"任意意图"。
    identity["purpose"] = normalize_purpose(purpose)
    return hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def structure_key(steps):
    """**只看结构**的身份键（工具序列 + 参数，不含业务意图）。

    为什么需要两个键：
      - `fingerprint` 是**业务身份**（结构 + 意图）——"同一序列做不同业务"
        必须是两条技能，否则 pdf 转换和发票汇总会被合并；
      - `structure_key` 是**结构身份**——证据计量/重复判定的口径。

    历史缺陷（本轮修复）：`record(steps, purpose)` 按业务身份写入，而
    `task_results(steps)`（调用方不传 purpose）按纯结构身份查询——**同一个
    任务永远查不回来**，"三次独立成功"闸门因此恒不可达。二键分离后，
    record 同时落业务身份与结构身份（一行一列），查询按结构身份聚合，
    两个问题各自有正确答案。
    """
    steps = normalize_steps(steps)
    if not steps:
        return None
    identity = {"steps": steps}
    return hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def canonical_skill_id(steps, purpose="", prefix="skill"):
    """统一技能 ID 命名方案——三条写入臂（封装/遗传/NL 合成）共用。

    旧实现各臂自造命名（skill_<md5> / genetic_<工具名> / synth_*），
    同序列不同名 → 服务端的重复判定（按 ID）永远不命中。统一为
    ``{prefix}_{fingerprint[:16]}``：ID 即身份，重复序列天然同 ID。
    """
    key = fingerprint(steps, purpose)
    if not key:
        return ""
    return f"{str(prefix or 'skill').strip() or 'skill'}_{key[:16]}"


def shared_lock(directory):
    key = str(directory.resolve()).casefold()
    with _locks_guard:
        return _locks.setdefault(key, threading.RLock())


class EvidenceStore:
    def __init__(self, directory, agent_id):
        self.directory, self.agent_id = directory, agent_id
        self.lock = shared_lock(directory)

    _SCHEMA = ("CREATE TABLE IF NOT EXISTS evidence (agent TEXT, fingerprint TEXT, structure TEXT, "
               "task TEXT, success INTEGER NOT NULL, PRIMARY KEY(agent, fingerprint, task))")

    @contextmanager
    def transaction(self):
        with self.lock:
            db = sqlite3.connect(str(self.directory / ".creation.sqlite3"), timeout=30)
            try:
                db.execute(self._SCHEMA)
                # 旧库迁移：structure 列缺席则补列并按结构回填（不回填 = 存量
                # 证据在结构查询下全部"消失"，闸门对老库恒不可达）。
                columns = {row[1] for row in db.execute("PRAGMA table_info(evidence)")}
                if "structure" not in columns:
                    db.execute("ALTER TABLE evidence ADD COLUMN structure TEXT")
                    db.execute("UPDATE evidence SET structure=? WHERE structure IS NULL",
                               (self._legacy_structure_fill(),))
                db.execute("BEGIN IMMEDIATE")
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise
            finally:
                db.close()

    @staticmethod
    def _legacy_structure_fill():
        """旧库回填哨兵：无法反推旧行意图，回填 'legacy' 保证列非空可查。"""
        return "legacy"

    def record(self, task_id, steps, purpose, success):
        key = fingerprint(steps, purpose)
        structure = structure_key(steps)
        if not isinstance(task_id, str) or not task_id or not key or not structure:
            return False
        with self.transaction() as db:
            # Failure is sticky: replay/retry cannot convert a failed task into a vote.
            db.execute(
                "INSERT INTO evidence (agent, fingerprint, structure, task, success) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(agent,fingerprint,task) DO UPDATE SET success=MIN(success,excluded.success)",
                (self.agent_id, key, structure, task_id, int(success is True)))
        return True

    def task_results(self, steps, purpose="", db=None):
        """按**结构身份**聚合该工具序列的全部任务结果（业务身份聚合视图）。

        purpose 仍参与写入侧的**业务身份**（同一序列不同业务是两条技能），
        但"这条序列成功过几次"是结构问题——否则未标注意图的调用方永远
        查不到任何证据（历史断点：三次独立成功闸门恒不可达）。
        """
        if db is None:
            with self.transaction() as connection:
                return self.task_results(steps, purpose, connection)
        key = structure_key(steps)
        if not key:
            return {}
        rows = db.execute(
            "SELECT task, success FROM evidence WHERE agent=? AND structure=?",
            (self.agent_id, key)).fetchall()
        results: Dict[str, int] = {}
        for task, success in rows:
            # 同一任务可能因意图不同存在多行：失败具有粘性（任一失败即失败）。
            results[task] = min(results.get(task, 1), int(success))
        return results

    def success_tasks(self, steps, purpose="", db=None):
        return [task for task, success in self.task_results(steps, purpose, db).items() if success]

    def eligible(self, steps, purpose="", db=None):
        return len(self.success_tasks(steps, purpose, db)) >= MIN_SUCCESSES

    def business_identities(self, steps, db=None):
        """该结构下已出现过的业务身份集（供合并/跨意图观测）。"""
        if db is None:
            with self.transaction() as connection:
                return self.business_identities(steps, connection)
        key = structure_key(steps)
        if not key:
            return set()
        return {row[0] for row in db.execute(
            "SELECT DISTINCT fingerprint FROM evidence WHERE agent=? AND structure=?",
            (self.agent_id, key))}


def begin_task():
    # Server allocated, request-local, unaffected by global session turn counters.
    _execution.set({"id": uuid.uuid4().hex, "steps": [], "success": True,
                    "closed": False, "lock": threading.RLock()})


_missing_context_counter = 0
_missing_context_lock = threading.Lock()


def missing_context_count() -> int:
    """票据上下文缺失的累计次数（观测面读数，进程级）。

    "这个 agent 从没调过工具"与"它的工具调用没被采到"是两件事：`begin_task()`
    只由 `reset_turn_tool_messages()` 触发（chat 主链轮首），子代理 / swarm /
    neurflow / API 直调等入口全在此静默丢票。没有这个读数，005 迁移期出现的
    漏采在观测面完全不可见。
    """
    return _missing_context_counter


def record_tool_execution(tool_name, params, success, result):
    task = _execution.get()
    if task is None:
        global _missing_context_counter
        with _missing_context_lock:
            _missing_context_counter += 1
        logger.warning(
            "票据上下文缺失，本次工具执行未进证据账本（入口/工具=%s）——"
            "该入口未经 reset_turn_tool_messages 建任务上下文，属漏采",
            tool_name,
        )
        return
    if tool_name == "create_skill":
        return
    from neurova.security.governance import is_policy_denial
    ok = (success is True and result is not None and not is_policy_denial(result)
          and not (isinstance(result, dict) and
                   (result.get("error") or result.get("success") is False)))
    with task["lock"]:
        if not task["closed"]:
            task["steps"].append({"tool": tool_name, "params": copy.deepcopy(params)})
            task["success"] = task["success"] and ok


def finish_task(agent, purpose, completed):
    task = _execution.get()
    if task is None:
        return
    with task["lock"]:
        if task["closed"] or not task["steps"]:
            flush_task(None, purpose, completed)
            return
    from neurova.skills.skill_service import SkillService

    service = SkillService(agent_id=agent.config.agent_id)
    record = flush_task(service, purpose, completed)
    builder = getattr(agent, "skill_packer", None)
    if builder is not None and record:
        builder.evidence_store = service.creation_evidence
        builder.observe(record["steps"], context=purpose, success=record["success"],
                        metadata={"source_key": record["source_key"]})
        builder.register_to_skill_registry(getattr(agent, "_skill_registry", None), service)


def flush_task(service, purpose, completed):
    task = _execution.get()
    if task is None:
        return None
    with task["lock"]:
        _execution.set(None)
        if task["closed"]:
            return None
        task["closed"] = True
        if not task["steps"]:
            return None
        success = completed is True and task["success"]
        service.creation_evidence.record(task["id"], task["steps"], purpose, success)
        return {"source_key": task["id"], "steps": copy.deepcopy(task["steps"]),
                "purpose": purpose, "success": success}


def _manifest_config(manifest):
    """manifest 可能是 dict / SimpleNamespace / Skill（三条臂各用一种）。

    历史只按 dict 取值——`publish_automatic` 的调用方却传对象，于是
    "统一命名"用对象 manifest 调进来会 AttributeError（本次一并修）。
    """
    if isinstance(manifest, dict):
        config = manifest.get("config")
    else:
        config = getattr(manifest, "config", None)
    return config if isinstance(config, dict) else {}


def manifest_purpose(manifest):
    """manifest 的业务意图来源（显式声明优先，描述兜底）。"""
    config = _manifest_config(manifest)
    description = manifest.get("description", "") if isinstance(manifest, dict) \
        else getattr(manifest, "description", "")
    return (config.get("task_purpose") or config.get("context_template")
            or description or "")


def manifest_fingerprint(manifest):
    """业务身份：结构 + 意图（"同序列不同业务"必须是两条技能）。"""
    return fingerprint(_manifest_config(manifest).get("tool_sequence"), manifest_purpose(manifest))


def manifest_structure(manifest):
    """结构身份：只看工具序列（"同序列不可能被封装两次"的判重口径）。"""
    return structure_key(_manifest_config(manifest).get("tool_sequence"))


def publish_automatic(service, registry, manifest, *, alias_id="", human_approved=False):
    """Disk first; restore the canonical identity without bypassing evidence.

    **统一命名（P0 收口）**：本函数是三条写入臂（AutoSkillBuilder /
    ToolGeneticEngine / NL 合成）唯一共用的落盘闸口，故 ID 归一化在这里做，
    而不是在三个调用点各写一遍——各写一遍等于没统一（历史缺陷：三臂各自
    `genetic_*` / `synth_*` / `skill_<md5>`，服务端按 ID 判重永不命中）。

    归一规则：
      - 有可推导的身份（工具序列非空）→ 落盘 ID = ``canonical_skill_id(...)``；
        调用方原 ID **登记为别名**，既有 manifest / 账本 / 前端引用照旧可解析。
      - 无身份（无工具序列的手工/用户技能）→ 保持调用方 ID 原样，
        统一命名只约束「工具序列身份」这一类产物。

    alias_id：调用方沿用的旧 ID（保持既有 manifest/账本/前端引用不搬迁）。
    """
    config = dict(manifest.config or {})
    original_id = str(manifest.id or "")
    canonical = canonical_skill_id(
        config.get("tool_sequence"), manifest_purpose(manifest),
        prefix=_canonical_prefix(original_id),
    )
    aliases = {str(alias_id)} if alias_id and str(alias_id) != original_id else set()
    if canonical and original_id and original_id != canonical:
        # 原 ID 收敛为别名：库里只有规范 ID，调用方照旧能用原 ID 找到它。
        aliases.add(original_id)
    aliases.discard(canonical)
    aliases.discard("")
    if canonical:
        manifest = _renamed(manifest, canonical)
    return _publish_automatic(service, registry, manifest, config, sorted(aliases),
                              human_approved=human_approved)


def _canonical_prefix(original_id):
    """按写入臂归属选前缀，使规范 ID 可读地标明产物来源（skill/genetic/synth）。

    前缀**不参与身份**（身份是 fingerprint），只影响可读性与运维排查；
    未知来源一律 ``skill``。
    """
    raw = str(original_id or "").strip().casefold()
    for prefix in ("genetic", "synth"):
        if raw.startswith(prefix + "_"):
            return prefix
    return "skill"


def _renamed(manifest, new_id):
    """产出一份 ID 已归一的 manifest（保持原类型：SimpleNamespace / Skill / dict）。"""
    if isinstance(manifest, dict):
        return {**manifest, "id": new_id}
    from types import SimpleNamespace

    fields = {"id": new_id, "name": getattr(manifest, "name", new_id),
              "description": getattr(manifest, "description", ""),
              "config": getattr(manifest, "config", {}) or {}}
    for extra in ("version", "author", "source", "enabled"):
        if hasattr(manifest, extra):
            fields[extra] = getattr(manifest, extra)
    return SimpleNamespace(**fields)


def _publish_automatic(service, registry, manifest, config, aliases, human_approved=False):
    result = service.create_automatic_skill(
        manifest.id, manifest.name, manifest.description, config,
        version=getattr(manifest, "version", "1.0.0"), alias_ids=aliases,
        human_approved=human_approved)
    if not result.get("success"):
        return result
    # 别名登记：调用方沿用的 ID（含被归一掉的原 ID）都解析到落盘条目。
    # 必须在**新建成功**时也登记——只在 duplicate 分支登记会让第一个写入臂
    # 的原 ID 解析不到（"统一命名"后又制造了一个新的孤儿入口）。
    for alias in aliases:
        service.register_skill_alias(result["skill_id"], alias)
    if result.get("duplicate"):
        # 身份已存在：登记本臂 ID（后续同序列任一命名方案都收敛到同一技能），
        # 并**同步运行态**到已落盘条目的当前状态——内部平台（runspace）可能与
        # 磁盘不同步（重启后新实例才读到"已批准=enabled"），不同步会让运行态
        # 停在旧的待审/停用态（登记"批准过却仍不可用"）。
        service.register_skill_alias(result["skill_id"], manifest.id)
    from types import SimpleNamespace
    info = service.get_skill_info(result["skill_id"])
    stored = info.get("manifest") or {}
    runtime = SimpleNamespace(id=info["id"], name=info["name"],
                              description=info.get("description", ""), config=stored.get("config", {}))
    if registry is None or not registry.register_skill(runtime, None):
        return {**result, "success": False, "persisted": True,
                "error": "Skill persisted but runtime registration failed; retry restores it"}
    if hasattr(registry, "set_skill_enabled"):
        registry.set_skill_enabled(runtime.name, info.get("enabled", True))
    return {**result, "skill_name": runtime.name}
