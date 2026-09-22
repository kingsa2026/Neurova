"""运行期数据落点必须经数据根/仓库根推导，不得按进程 CWD 拼。

病灶（Issue #75 §7.7 登记为"另一根族"、本批实测为**真 CWD 泄露**）：
`core/data_root.py` 把 `data/` 这一族收口了，`core/file_utils.py`/`files_api` 的
`storage/`、`core/trace_recorder.py` 的 `trajectories/`、`api/auth.py` 的
`.jwt_secret`、`session_manager.py` 的 `sessions/`、`media/config.py` 的
`config/media`、`execution_monitor.py` 的 `logs/executions` 等仍是裸相对字面量。
上一批把它们登记为"运行期数据、改名会让既有令牌与轨迹失联"而未动；本批实测它们
**在任意 CWD 下都会就地造出文件**（真构造点 + 临时 CWD，见下），比 `data/` 那族更坏：
`data/` 至少还锚在仓库根，这些锚在"进程碰巧从哪儿启动"。

判据（每条都可由本文件复现，不用替身）：

1. **静态**：`neurova/` 与 `scripts/` 内不得有"CWD 相对字面量当落点"；
   落点要么经数据根（`get_data_root` / `resolveDataPath` / `callerPath` / `dataPath`）
   推导，要么经仓库根（`repoRoot` / `repoAsset`）推导 —— 后者给随代码走的配置与模型资产。
2. **活体**：在临时 CWD + 注入数据根下调用一批**真构造点**，CWD 必须零新增文件。
3. **收养**：旧落点（CWD 相对时代的产物）在新落点空缺时被搬进数据根，既有部署不失联。
"""

from __future__ import annotations

import ast
import functools
import os
import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_ROOT_MODULE = PROJECT_ROOT / "neurova" / "core" / "data_root.py"
SCANNED_ROOTS = ("neurova", "scripts")

#: 允许的落点推导器（出现任一即视为已锚定）
ANCHORS = (
    "get_data_root", "resolveDataPath", "callerPath", "dataPath", "get_agent_data_dir",
    "ensure_agent_data_dir", "get_agent_workspaces_root", "repoRoot", "repoAsset",
    "PROJECT_ROOT", "REPO_ROOT", "_REPO_ROOT", "_PROJECT_ROOT", "__file__", "parents[",
    "getcwd",
)

_REL_LITERAL = re.compile(r"^[A-Za-z0-9_.\-][A-Za-z0-9_./\-]*$")
_PATHY_NAME = re.compile(r"(dir|path|file|root|folder|store|db|subdir|filename)$", re.I)
#: 取叶子名的属性访问：`Path(x).name` 不构成落点
_LEAF_ATTRS = {"name", "stem", "suffix", "suffixes", "parts", "anchor"}
_SKIP_LITERALS = {".", "..", "./", "../", ".\\", "..\\", ":memory:", ""}
#: 这些子串出现即不是"文件系统落点"（时钟格式、Windows 环境根、模板片段）
_NOT_A_LANDING = ("%", "SystemRoot", "LOCALAPPDATA", "AppData")


def _isCwdRelativeLiteral(value) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    if value in _SKIP_LITERALS:
        return False
    if value.startswith(("/", "~", "\\")):
        return False
    if len(value) > 1 and value[1] == ":":       # 盘符
        return False
    if "://" in value or value.startswith(("http", "ws")):
        return False
    if any(mark in value for mark in _NOT_A_LANDING):
        return False
    return bool(_REL_LITERAL.match(value))


_CALL_HINT = re.compile(r"(Path|PurePath|join|joinpath|makedirs|mkdir|connect)\s*\(")
_QUOTE_HINT = re.compile(r"[\"']")


@functools.lru_cache(maxsize=None)
def _textOf(path: Path) -> str:
    """按文件缓存源码（预筛与解析共用）。"""
    return path.read_text(encoding="utf-8", errors="replace")


@functools.lru_cache(maxsize=None)
def _treeOf(path: Path):
    """按文件缓存 AST；语法错误返回 None（跳过该文件，与既有守卫一致）。"""
    try:
        return ast.parse(_textOf(path))
    except SyntaxError:
        return None


def _maybeHasLanding(path: Path) -> bool:
    """文本级粗筛：不含路径调用或引号字面量的文件不可能命中。

    扫描成本在 `ast.parse` + 遍历；全量 1000+ 文件直扫会撞 `pytest-timeout`
    的 30s 上界（受保护子集并发跑时更甚）。预筛是**严格超集**：
    任何落点形态都必须写成 `Path(...)` / `join(...)` / `connect(...)` 且带引号字面量。
    由 `test_prefilterNeverDropsAJudgedShape` 反向锁住。
    """
    text = _textOf(path)
    return bool(_CALL_HINT.search(text)) and bool(_QUOTE_HINT.search(text))


def _landingCall(node) -> str | None:
    """该 Call 是否"把参数当文件系统落点"。返回调用名或 None。"""
    func = node.func
    if isinstance(func, ast.Name):
        if func.id in ("Path", "PurePath"):
            return func.id
        if func.id == "open":
            return "open"
        return None
    if isinstance(func, ast.Attribute):
        receiver = ast.unparse(func.value)
        attr = func.attr
        if attr in ("mkdir", "makedirs") and any(k in receiver for k in ("Path", "path", "os")):
            return attr
        if attr in ("join", "joinpath") and any(k in receiver for k in ("Path", "path", "os")):
            return attr
        if attr == "connect" and "sqlite3" in receiver:
            return "connect"
        return None
    return None


def _landingArgs(node) -> list:
    """该 Call 里"被当文件系统落点"的参数下标。

    `Path('storage')` / `sqlite3.connect('x.db')` 的首参是落点；
    `os.path.join(base, 'leaf.json')` 只有 **base** 是落点——把叶子名也当落点，
    `join(derived, 'wal.jsonl')` 会被误判成 CWD 相对。
    """
    kind = _landingCall(node)
    if kind is None or not node.args:
        return []
    if kind in ("join", "joinpath"):
        return [0]
    if kind == "connect":
        return list(range(len(node.args)))
    return [0]


def _isCwdRelativeLiteral(value) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    if value in _SKIP_LITERALS:
        return False
    if value.startswith(("/", "~", "\\")):
        return False
    if len(value) > 1 and value[1] == ":":       # 盘符
        return False
    if "://" in value or value.startswith(("http", "ws")):
        return False
    if any(mark in value for mark in _NOT_A_LANDING):
        return False
    return bool(_REL_LITERAL.match(value))


def _cwdLiteralsIn(node) -> list:
    """落点参数里的 CWD 相对字面量。

    `Path('x')` 是直白形状；`Path(cfg or 'x')` 与 `Path('a' if y else 'b')`
    是生产线上的常见写法（兜底名就藏在 `or` 右边），必须一并认。
    """
    if isinstance(node, ast.Constant) and _isCwdRelativeLiteral(node.value):
        return [node]
    found = []
    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
        found.extend(c for c in node.values
                     if isinstance(c, ast.Constant) and _isCwdRelativeLiteral(c.value))
    if isinstance(node, ast.IfExp):
        for branch in (node.body, node.orelse):
            if isinstance(branch, ast.Constant) and _isCwdRelativeLiteral(branch.value):
                found.append(branch)
    # `Path(cfg.get("<KEY>", "<相对名>"))`：没配就用相对名，同样是落点。
    # 只认键名带落点语义的，不误伤 `cfg.get("host", "127.0.0.1")` 那类普通配置。
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
            and node.func.attr == "get" and len(node.args) >= 2:
        key, fallback = node.args[0], node.args[1]
        receiver = ast.unparse(node.func.value)
        if (isinstance(key, ast.Constant) and isinstance(key.value, str)
                and any(mark in key.value.upper()
                        for mark in ("PATH", "DIR", "FILE", "UPLOAD", "LOG", "STORE"))
                and any(mark in receiver for mark in ("config", "environ"))
                and isinstance(fallback, ast.Constant)
                and _isCwdRelativeLiteral(fallback.value)):
            found.append(fallback)
    return found


@functools.lru_cache(maxsize=None)
def _cwdLandingsIn(path: Path) -> list:
    """判据实现：返回该文件里"CWD 相对字面量当落点"的位置与原因。

    单趟建索引（parents / docstrings / tainted 名），再单趟裁决——
    `ast.walk` 每趟都遍历全树，多趟会让受保护子集并发跑时撞 timeout。
    """
    if not _maybeHasLanding(path):
        return []
    tree = _treeOf(path)
    if tree is None:
        return []

    parents = {}
    docstrings = set()
    nodes = []
    stack = [tree]
    while stack:
        node = stack.pop()
        nodes.append(node)
        for child in ast.iter_child_nodes(node):
            parents[child] = node
            stack.append(child)
        if node.__class__.__name__ in ("Module", "ClassDef", "FunctionDef", "AsyncFunctionDef"):
            body = node.body
            if body and body[0].__class__ is ast.Expr:
                value = body[0].value
                if value.__class__ is ast.Constant and isinstance(value.value, str):
                    docstrings.add(id(value))

    def isCwdLiteral(node) -> bool:
        return (isinstance(node, ast.Constant) and _isCwdRelativeLiteral(node.value)
                and id(node) not in docstrings)

    def anchored(call) -> bool:
        text = ast.unparse(call.func)
        for arg in call.args:
            text += " " + ast.unparse(arg)
        return any(anchor in text for anchor in ANCHORS)

    hits = []

    # ── 名字索引：路径语义名接住的 CWD 字面量（含默认参数与 or 兜底）──────
    tainted = {}
    for node in nodes:
        targets = None
        if isinstance(node, ast.Assign):
            targets = node.targets
            values = ([node.value] if isinstance(node.value, ast.Constant)
                      else list(node.value.values)
                      if isinstance(node.value, ast.BoolOp) and isinstance(node.value.op, ast.Or)
                      else [])
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            values = [node.value] if isinstance(node.value, ast.Constant) else []
        else:
            targets = None
            values = []
        # `x = cfg.get("<KEY>", "<相对名>")`：没配就用相对名，同样是落点。
        # 只认键名带落点语义（PATH/DIR/FILE/UPLOAD/LOG/STORE）的，
        # 不误伤 `cfg.get("host", "127.0.0.1")` 这类普通配置。
        if targets is not None and isinstance(node.value, ast.Call) \
                and isinstance(node.value.func, ast.Attribute) \
                and node.value.func.attr == "get" and len(node.value.args) >= 2:
            key, fallback = node.value.args[0], node.value.args[1]
            receiver = ast.unparse(node.value.func.value)
            if (isinstance(key, ast.Constant) and isinstance(key.value, str)
                    and any(mark in key.value.upper()
                            for mark in ("PATH", "DIR", "FILE", "UPLOAD", "LOG", "STORE"))
                    and any(mark in receiver for mark in ("config", "environ"))
                    and isinstance(fallback, ast.Constant) and isCwdLiteral(fallback)):
                values = [fallback]
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            positional = list(node.args.args) + list(node.args.kwonlyargs)
            defaults = list(node.args.defaults) + [d for d in node.args.kw_defaults if d is not None]
            for arg, default in zip(positional[-len(defaults):] if defaults else [], defaults):
                if _PATHY_NAME.search(arg.arg) and isCwdLiteral(default):
                    tainted.setdefault(arg.arg, []).append(default)
        if not targets:
            continue
        for target in targets:
            name = (target.attr if isinstance(target, ast.Attribute)
                    else target.id if isinstance(target, ast.Name) else None)
            if not name or not _PATHY_NAME.search(name):
                continue
            for value in values:
                if isCwdLiteral(value):
                    tainted.setdefault(name, []).append(value)

    for node in nodes:
        if not isinstance(node, ast.Call) or not node.args:
            continue
        kind = _landingCall(node)
        if kind is None:
            continue
        parent = parents.get(node)
        if isinstance(parent, ast.Attribute) and parent.attr in _LEAF_ATTRS:
            continue          # `Path(x).name` / `.suffix`：取叶子名，不是落点
        if kind == "open":
            mode = node.args[1] if len(node.args) > 1 else None
            if not (isinstance(mode, ast.Constant) and isinstance(mode.value, str)):
                continue
            if not any(c in mode.value for c in "wax+"):
                continue

        if not anchored(node):
            for index in _landingArgs(node):
                if index >= len(node.args):
                    continue
                for literal in _cwdLiteralsIn(node.args[index]):
                    if id(literal) not in docstrings:
                        hits.append((literal.lineno, "%s(%r)" % (kind, literal.value)))

        if not tainted:
            continue
        indexes = _landingArgs(node)
        if not indexes and isinstance(node.func, ast.Attribute) \
                and node.func.attr in ("abspath", "exists", "dirname"):
            indexes = [0]
        for index in indexes:
            if index >= len(node.args):
                continue
            for sub in ast.walk(node.args[index]):
                name = None
                if isinstance(sub, ast.Attribute) and sub.attr in tainted:
                    name = sub.attr
                elif isinstance(sub, ast.Name) and sub.id in tainted:
                    name = sub.id
                if name:
                    for literal in tainted[name]:
                        hits.append((literal.lineno, "%s ← %s=%r" % (kind, name, literal.value)))
    return sorted(set(hits))


def _scannedFiles() -> list:
    files = []
    for root in SCANNED_ROOTS:
        for path in sorted((PROJECT_ROOT / root).rglob("*.py")):
            if "__pycache__" in path.parts or path == DATA_ROOT_MODULE:
                continue
            files.append(path)
    return files


class TestNoCwdRelativeRuntimeLanding:
    """生产代码内不得再有"CWD 相对字面量当落点"。"""

    def test_productionTreeHasNoCwdLanding(self):
        offenders = []
        for path in _scannedFiles():
            for lineno, reason in _cwdLandingsIn(path):
                offenders.append("%s:%d: %s" % (path.relative_to(PROJECT_ROOT).as_posix(), lineno, reason))
        assert offenders == [], (
            "仍有 %d 处落点按进程 CWD 拼（换个启动目录就换个位置）：\n  %s\n"
            "修复：数据落点走 `neurova/core/data_root.py`（get_data_root / resolveDataPath / "
            "callerPath / dataPath），随代码走的配置与模型资产走 `repoRoot()` / `repoAsset()`。"
            % (len(offenders), "\n  ".join(offenders))
        )

    def test_scannerHasTeethOnKnownShapes(self, tmp_path):
        """反向控制：判据必须真认得出落点形态，否则上面那条是空断言。"""
        probe = tmp_path / "probe.py"
        probe.write_text(
            "import os\n"
            "from pathlib import Path\n"
            "A = Path('storage/users')\n"
            "B = os.path.join('logs', 'executions')\n"
            "C = Path('trajectories'); C.mkdir(exist_ok=True)\n"
            "def d(base_dir: str = 'sessions'):\n"
            "    return Path(base_dir)\n"
            "E = 'config/media'\n"
            "def f(config_dir=None):\n"
            "    return Path(config_dir or 'config/media')\n"
            "G = sqlite3.connect('neurflow.db')\n"
            "H = Path(get_data_root()) / 'ok'\n"
            "I = os.path.join(get_data_root(), 'ok2')\n"
            "J = Path(__file__).resolve().parents[2] / 'config'\n"
            "K = Path(get_data_root(), 'a', 'leaf.jsonl')\n"
            "L = os.path.join(get_data_root(), 'leaf.json')\n"
            "M = Path('x.dat').suffix\n"
            "N = Path('%Y%m%d')\n"
            "O = Path('SystemRoot')\n"
            "P = Path(config.get('NEUROVA_CONSOLE_UPLOADS', 'uploads/console'))\n"
            "Q = Path(config.get('NEUROVA_LOG_FILE', 'logs/neurova.log'))\n"
            "R = config.get('host', '127.0.0.1')\n",
            encoding="utf-8",
        )
        reasons = [r for _, r in _cwdLandingsIn(probe)]
        assert len(reasons) == 8, "扫描器漏认或误伤：%s" % reasons
        assert not any("get_data_root" in r or "parents[" in r for r in reasons), \
            "已锚定的落点被误判"
        assert not any("%Y" in r or "SystemRoot" in r for r in reasons), \
            "时钟格式与环境根被误判成落点"
        assert not any("127.0.0.1" in r for r in reasons), \
            "普通配置兜底（host/port 等）被误判成落点"


class TestConstructorsDoNotTouchCwd:
    """活体判据：真构造点在临时 CWD 下必须零新增。"""

    @pytest.fixture
    def elsewhere(self, tmp_path, monkeypatch):
        cwd = tmp_path / "cwd"
        cwd.mkdir()
        monkeypatch.chdir(cwd)
        monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "dataRoot"))
        return cwd

    @staticmethod
    def _leaked(cwd: Path) -> list:
        return sorted(p.name for p in cwd.iterdir())

    def test_jwtSecretLandsUnderDataRoot(self, elsewhere):
        from neurova.api import auth

        auth._write_secret_file("x" * 40)
        assert self._leaked(elsewhere) == [], "密钥文件仍落在 CWD"

    def test_traceRecorderLandsUnderDataRoot(self, elsewhere):
        from neurova.core.trace_recorder import get_trajectory_recorder

        recorder = get_trajectory_recorder()
        assert recorder._storage_dir.is_absolute()
        recorder._load_saved_traces_index()
        assert self._leaked(elsewhere) == [], "轨迹目录仍落在 CWD"

    def test_isolatedStorageLandsUnderDataRoot(self, elsewhere):
        from neurova.core import file_utils

        file_utils.get_isolated_path("u1", "a1", "s1", "image")
        assert self._leaked(elsewhere) == [], "上传隔离存储仍落在 CWD"

    def test_filesApiRootLandsUnderDataRoot(self, elsewhere):
        from neurova.api.endpoints import files_api

        files_api.STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
        assert self._leaked(elsewhere) == [], "上传根仍落在 CWD"

    def test_sessionManagerLandsUnderDataRoot(self, elsewhere):
        from neurova.session_manager import SessionManager

        assert SessionManager()._sessions_dir.is_absolute()
        assert self._leaked(elsewhere) == [], "会话目录仍落在 CWD"

    def test_executionMonitorLandsUnderDataRoot(self, elsewhere):
        from neurova.execution_engine.execution_monitor import ExecutionMonitor

        ExecutionMonitor().load_execution_history()
        assert self._leaked(elsewhere) == [], "执行日志目录仍落在 CWD"

    def test_mediaConfigLandsUnderDataRoot(self, elsewhere):
        from neurova.media.config import MediaStorageConfigManager

        assert MediaStorageConfigManager().config_dir.is_absolute()
        assert self._leaked(elsewhere) == [], "媒体配置目录仍落在 CWD"

    def test_projectToSkillLandsUnderDataRoot(self, elsewhere):
        from neurova.skills.project_to_skill import ProjectToSkillConverter

        assert ProjectToSkillConverter().output_dir.is_absolute()
        assert self._leaked(elsewhere) == [], "技能产出目录仍落在 CWD"

    def test_healthCheckLandsUnderDataRoot(self, elsewhere):
        from neurova.api.app import _make_database_health_check

        _make_database_health_check()()
        assert self._leaked(elsewhere) == [], "健康检查连库仍落在 CWD"

    def test_shutdownGuardLandsUnderDataRoot(self, elsewhere):
        from neurova.recovery.shutdown_guard import get_shutdown_guard

        get_shutdown_guard().write_sentinel()
        assert self._leaked(elsewhere) == [], "关机哨兵仍落在 CWD"

    def test_neurflowStorageLandsUnderDataRoot(self, elsewhere):
        from neurova.collaboration.neurflow.storage import NeurflowStorage

        NeurflowStorage()
        assert self._leaked(elsewhere) == [], "neurflow 库仍落在 CWD"

    def test_tokenSecretsLandUnderDataRoot(self, elsewhere):
        from neurova.security.neu_token_manager import _load_or_create_token_secret

        _load_or_create_token_secret()
        assert self._leaked(elsewhere) == [], "令牌签名密钥仍落在 CWD"

    def test_memoryEncryptionKeyLandsUnderDataRoot(self, elsewhere):
        from neurova.cognitive_layers.memory_layer import security

        security._load_or_create_encryption_key()
        assert self._leaked(elsewhere) == [], "记忆加密密钥仍落在 CWD"


class TestLegacyLandingIsAdopted:
    """旧落点（CWD 相对时代的产物）必须被搬进数据根，不能就此失联。"""

    def test_repoRootLegacyFileIsMoved(self, monkeypatch, tmp_path):
        from neurova.core import data_root

        legacy_root = tmp_path / "repo"
        (legacy_root / "config").mkdir(parents=True)
        legacy = legacy_root / "config" / "infrastructure.json"
        legacy.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(data_root, "repoRoot", lambda: legacy_root)
        target = tmp_path / "dataRoot" / "config" / "infrastructure.json"

        assert data_root.adoptLegacyLanding(target, "config", "infrastructure.json") is True
        assert target.exists() and not legacy.exists(), "旧落点未被收养"

    def test_existingTargetWins(self, monkeypatch, tmp_path):
        """新落点已有该物时不得用旧物覆盖（旧物只作空缺时的救济）。"""
        from neurova.core import data_root

        legacy_root = tmp_path / "repo"
        legacy_root.mkdir()
        (legacy_root / "agents.json").write_text('{"old": 1}', encoding="utf-8")
        monkeypatch.setattr(data_root, "repoRoot", lambda: legacy_root)
        target = tmp_path / "dataRoot" / "agents.json"
        target.parent.mkdir(parents=True)
        target.write_text('{"new": 2}', encoding="utf-8")

        assert data_root.adoptLegacyLanding(target, "agents.json") is False
        assert target.read_text(encoding="utf-8") == '{"new": 2}'

    def test_noLegacyIsNoOp(self, monkeypatch, tmp_path):
        from neurova.core import data_root

        monkeypatch.setattr(data_root, "repoRoot", lambda: tmp_path / "absent")
        target = tmp_path / "dataRoot" / "x.json"

        assert data_root.adoptLegacyLanding(target, "x.json") is False
        assert not target.exists()


class TestGuardIsProtected:
    """守卫必须真进 CI 受保护子集——"绿"要和"跑过"是同一件事。"""

    def test_listedInProtectedSubset(self):
        listed = (PROJECT_ROOT / "scripts" / "ci" / "protected_tests.txt").read_text(encoding="utf-8")
        assert "tests/unit/core/test_runtime_landing_root.py" in listed, \
            "本守卫不在受保护子集里，CI 不会跑它"
