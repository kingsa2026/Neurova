
"""
Pytest 配置和共享 fixtures

提供测试中可复用的模拟对象和通用工具。
"""
import pytest
import sys
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# 跑测期间不写字节码缓存——**仓库根顶层条目**里有 `__pycache__` 这一项的唯一来源。
#
# 本仓有过三处"局部关掉写盘"的补丁（`tests/unit/skills/conftest.py` 对 `start.py`、
# `tests/unit/desktop/test_install_supply_contract.py` 对 `install.py`、
# `tests/unit/test_cliFourOhOneSelfRescueHint.py` 对 `cli.py`），成因同一个：仓库根住着
# 若干**顶层脚本**（`cli.py` / `start.py` / `install.py`），而顶层脚本不是一个包，
# CPython 的常规 import 会把编译产物写在**源文件旁**——也就是仓库根的 `__pycache__/`，
# 由 `_guardRepoRootAgainstPollution` 逐条点名肇事用例（2026-10-12 CI 实测
# `tests/unit/test_cliFourOhOneSelfRescueHint.py` 报 `['__pycache__']`）。
#
# 三处补丁各管一个脚本，是同一件事的三份实现（教义第 6/7 条：口径只许一处）；
# 而且它们只护住自己那一个 import。根因是"跑测会往仓库根写盘"这件事本身，
# 就该在一处收口：判据与那批 `.pyc` 全无关系（没有任何用例断言缓存存在，
# 实测上表三处也只把它当副作用），关掉不影响任何断言；生产跑 `python cli.py`
# 是另一个进程，不受影响。
#
# 为什么必须在**导入期**：写盘发生在任何一个 `import cli` 的瞬间，
# per-test 的 monkeypatch 来得太晚（与上面 `NEUROVA_DATA_DIR` 同形）。
sys.dont_write_bytecode = True

# MoE 索引状态目录——会话级兜底。per-test fixture 用 monkeypatch 指向 tmp_path，
# 但那一刻之后仍有写盘：daemon 索引线程可能拖到 monkeypatch 撤销后才落盘，
# 起子进程的测试也不一定带上这个变量。实测（2026-09-19）全量 tests/unit 期间
# 4 个真实 workspace 键就被写回仓库 data/。这里在导入期把默认值钉进会话临时
# 目录，两种迟到写都落在临时区，且随子进程 env 继承下去。
MOE_STATE_SESSION_DIR = Path(tempfile.mkdtemp(prefix="neurovaMoeState-"))
os.environ.setdefault("NEUROVA_MOE_INDEX_STATE_DIR", str(MOE_STATE_SESSION_DIR))

# 数据根——**导入期**兜底（与上面 MoE 同形，且必须在任何 `neurova.*` 被 import 之前）。
#
# `core/data_root.get_data_root()` 的兜底是**仓库内** `data/`；而多个模块把它写在
# **模块级**（`library_service._BASE_DIR = get_data_root()`、`skill_service` 的默认落点
# 等），即 import 那一刻就把仓库根冻进常量，之后注入 env 一律看不见。
# 于是「构造一个默认落点的生产对象」在仓库根建塔写盘：受保护子集实跑 4 条
# ERROR（`data` / `.skill_scanner` / `.agents` / `__pycache__`）全此形态，
# 由 `_guardRepoRootAgainstPollution` 逐条点名。
#
# 为什么钉在这里而不是 per-test fixture：落点多数是**构造期/import 期**定死的，
# per-test 的 monkeypatch 来得太晚（那正是 `_isolate_agent_workspaces_root` 与
# `_isolateSessionsLanding` 对"构造期定死"无可奈何的同一形态）。收在导入期才覆盖
# 全量装配点，也随子进程 env 继承下去；生产默认仍是仓库 `data/`，本行不改任何默认值。
DATA_ROOT_SESSION_DIR = Path(tempfile.mkdtemp(prefix="neurovaDataRoot-"))
os.environ.setdefault("NEUROVA_DATA_DIR", str(DATA_ROOT_SESSION_DIR))

# 仓库根（污染守卫的快照对象）：conftest 在 tests/ 下，parents[1] 即根。
REPO_ROOT = Path(__file__).resolve().parents[1]

# 字节码落点——**导入期**兜底（与上面 MoE/数据根同形，且是同一族污染的剩余命中点）。
#
# 仓库根那六个顶层 `.py`（`cli.py` / `start.py` / …）是真模块：CPython 默认把字节码写在
# **源文件旁**，于是 `import cli` 会在仓库根建出 `__pycache__/cli.cpython-*.pyc`。
# 这正是 `_guardRepoRootAgainstPollution` 报的 `__pycache__`——它不是某条用例"写错路径"，
# 而是解释器的默认落点；判据本身没错（顶层条目不得新增），错的是让它有得可写。
#
# 为什么不收口到"点名的那个用例"：`cli.py` 住在仓库根是**既定事实**，任何 `import cli`
# 都会复现同一形态（`tests/unit/test_cli_repl.py`、`test_cli_repl_ui.py` 同样如此）。
# 在源头把字节码落点搬到会话临时区，才是根因处修复（教义第 1 条）；判据一个字不改。
# `sys.pycache_prefix` 必须在**首次 import 之前**设（`os.environ` 的同名变量在解释器
# 启动后再设无效——实测 `sys.pycache_prefix` 直接生效），故与本段其余兜底同处导入期。
BYTECODE_CACHE_SESSION_DIR = tempfile.mkdtemp(prefix="neurovaBytecodeCache-")
sys.pycache_prefix = BYTECODE_CACHE_SESSION_DIR

# 会话启动回收钩子——**注册点必须在本文件**。pytest 只从 conftest / 已注册插件的
# 模块命名空间收集钩子函数；同名函数写在普通模块（`tests/temp_reclaim.py`）里永远不会
# 被调用。2026-09-21 那版守卫就是这么带着"已落地"的标签零执行了三周——当时 18 条判据
# 全是把 stub session 手工喂给钩子，测得到"被调用时管用"，测不到"有没有人调用它"。
# 反证由 tests/unit/core/test_temp_reclaim.py::test_pytestInvokesTheHookWithoutAHandCall
# 承担：真起一个子会话，锁主确证死亡的残留目录若活过整轮会话即红。
# 位置在 `sys.pycache_prefix` 之后：那一项必须在首次 import 前生效，本行是一次 import。
from tests.temp_reclaim import pytest_sessionstart  # noqa: F401


@pytest.fixture(scope="session")
def moe_state_session_dir() -> Path:
    """会话级 MoE 状态目录（供断言兜底层生效）"""
    return MOE_STATE_SESSION_DIR


@pytest.fixture(autouse=True)
def _isolate_session_manager_singletons():
    """跨套件全局状态隔离（残留处理 2026-09-13 大合批泄漏治理）。

    SessionManager 为类级单例 + 类级解析/sidecar 缓存（进程级共享）；
    前序测试把 _instance 指向已删除的 tmp 目录或留下缓存条目时，后续
    会话面测试会在"全量批跑"里看到与单跑不一致的计数/解析断言。
    每测试后重置单例并清类级缓存；get_session_repository 同步复位。"""
    yield
    try:
        from neurova.session_manager import SessionManager
    except Exception:
        return
    SessionManager._instance = None
    for attr in ("_summary_cache", "_feedback_cache", "_sidecar_cache"):
        cache = getattr(SessionManager, attr, None)
        if isinstance(cache, dict):
            cache.clear()
    try:
        from neurova import session_repository as _sr
    except Exception:
        _sr = None
    if _sr is not None and hasattr(_sr, "reset_session_repository"):
        try:
            _sr.reset_session_repository()
        except Exception:
            pass


@pytest.fixture(autouse=True)
def _isolate_connection_pools():
    """跨测试释放连接池持有的 idle SQLite 连接。

    `connection_pool` 按路径持有连接且不随测试结束关闭；当测试把工作库建在
    TemporaryDirectory 内时，Windows 下临时目录清理会因残留池连接报 WinError 32
    （standalone 尤其明显）。每测试后 close_all_pools() 归还/关闭，池会在下次
    get_connection_pool 时惰性重建。
    """
    yield
    try:
        from neurova.core.connection_pool import close_all_pools

        close_all_pools()
    except Exception:  # pragma: no cover - 池模块不可用时跳过
        pass


@pytest.fixture(autouse=True)
def _isolate_execution_engine_singleton():
    """ExecutionEngine 单例跨测试隔离（Issue #65）。

    ExecutionEngine 是**类级单例**（``_instance`` 挂在类上），此前
    ``reset_execution_engine()`` 只清模块级缓存 → 重置后取回同一对象，
    依赖它做隔离的测试会拿到脏状态（实测 e2 is e1 → True），
    且该函数在全仓没有任何调用方——"重置"契约从未被验证。

    这里每测试后调用修复后的 ``reset_execution_engine()``（两层清：模块缓存
    + 类级 _instance），把契约钉在真实调用点上。原先的第三层"清执行记录
    ``_executions``"随那一面整体退役而消失——这把引擎今天只剩监控器一条来路。
    """
    yield
    try:
        from neurova.shared_core.execution_engine import reset_execution_engine
    except Exception:  # pragma: no cover - 模块不可用时跳过
        return
    try:
        reset_execution_engine()
    except Exception:  # pragma: no cover - 重置失败不得连带测试失败
        pass


@pytest.fixture(autouse=True)
def _isolate_skill_service_storage(tmp_path, monkeypatch):
    """Keep default skill-library writes out of user data during regressions.

    切的是**库根**，不是单条分支。旧写法只改写「不传 skills_dir」那一支（按 agent_id 取
    sha256 落 `tmp_path`），而 `library_service.get_library` 一直是**显式传目录**——生产把 23 处
    自建构造收进工厂之后，读侧的落点就不再受夹具摆布：它按 `_BASE_DIR`（import 期冻住的**会话级**
    数据根）解析，整个 pytest 进程内同一个根。于是夹具里写下的票据工厂读不到（露出来的那一角是
    6 格 `lookup=absent`），而用例之间开始共享同一本账。`_BASE_DIR` 正是 library_service 自带的
    测试注入点，把它指到 `tmp_path` 后，`resolve_library_dir` 与 `SkillService(agent_id=…)` 的
    默认落点同形同址：两条形状共用同一个库，隔离也不再依赖「谁恰好没传目录」。
    """
    from neurova.skills import library_service as lib
    from neurova.skills.skill_service import SkillService

    monkeypatch.setattr(lib, "_BASE_DIR", tmp_path)
    original = SkillService.__init__

    def isolated(self, agent_id, skills_dir=None):
        if skills_dir is not None:
            directory = skills_dir
        else:
            from neurova.core.agent_workspaces import get_agent_skills_dir

            directory = str(get_agent_skills_dir(agent_id))
        return original(self, agent_id, directory)

    monkeypatch.setattr(SkillService, "__init__", isolated)


@pytest.fixture(autouse=True)
def _isolate_library_singleton(tmp_path, monkeypatch):
    """每个用例清一次库实例表（收进单例的配套半区，不是可选的卫生工作）。

    生产侧把 23 处自建 `SkillService(agent_id=…)` 收进 `library_service.get_library` 的同进程
    单例之后，实例表就成了**跨用例共享态**。上面那夹具已把库根按用例切到 `tmp_path`，目录变了
    旧条目会自己失效——但那只是"不复用"，表里的条目仍然留着（上一个用例的实例连着它的锁与内存
    账，谁也不知道还有没有人握着引用）。逐用例复位才是把"收进单例"这件事做成可证伪的：判据
    `test_resetYieldsAFreshInstanceReadingFromDisk` 直接调这个函数，复位若做成空账它当场红。
    """
    from neurova.skills import library_service as lib

    lib.reset_libraries_for_tests()
    yield
    lib.reset_libraries_for_tests()


@pytest.fixture(autouse=True)
def _isolate_moe_index_state_dir(tmp_path, monkeypatch):
    """MoE 索引状态目录隔离（防仓库 data/ 泄漏）。

    状态文件名是 md5(agent_id:persist_db_path)，测试的 tmp_path 工作区每用例给
    一个新键、每次 pytest 运行再换一层基目录，落到仓库 data/ 就是不可回收的
    一次性文件。指向 tmp_path 后随测试临时目录一并清理。
    """
    monkeypatch.setenv("NEUROVA_MOE_INDEX_STATE_DIR", str(tmp_path / "moeIndexState"))


@pytest.fixture(autouse=True)
def _isolate_agent_workspaces_root(tmp_path, monkeypatch):
    """agent 工作区根隔离到 tmp_path（防污染真实记忆库）。

    app.py 用这个根建默认 Agent 并枚举已持久化 agent；测试里用 TestClient 起
    真 app 就会打开 agent_workspaces/<id>/memory/ 并往里写记忆行（实测某轮跑测
    期间 default 库从 301 行涨到 306 行）。生产默认仍是仓库 agent_workspaces/。
    """
    monkeypatch.setenv(
        "NEUROVA_AGENT_WORKSPACES_DIR", str(tmp_path / "agentWorkspaces")
    )


@pytest.fixture(autouse=True)
def _isolateSessionsLanding(_isolate_session_manager_singletons, tmp_path, monkeypatch):
    """会话落点默认隔离到本用例的 tmp 目录（根修，而非逐条用例补 env）。

    为什么必须收在默认值上：`SessionManager` 是类级单例，落点在**首次构造**时定死，
    而本文件的 `_isolate_session_manager_singletons` 每条用例后把 `_instance` 置 None
    ——于是任何起真 app 的用例（TestClient → startup → console 链路）都会在自己那一条里
    重新构造单例，落点取到 `dataLanding("sessions")`，即仓库真实会话库。实测被落点守卫
    点名 16 条、跨 7 个文件（console_run_ledger / mcp_session_shutdown / agent_*_persistence /
    load_saved_agents / home_stats / console_chat_ops）。逐条补 env 是 consumer-side 打补丁，
    默认值收口才是第 1 条要的上游修；同手法本仓已有先例 `_isolate_agent_workspaces_root`。

    收尾守卫 `_guardSessionLandingIsIsolated` 仍留着，兜住"显式把落点改回真实库"的写法。
    """
    from neurova.session_manager import SessionManager

    monkeypatch.setenv("NEUROVA_SESSIONS_DIR", str(tmp_path / "sessions"))
    SessionManager._instance = None
    yield
    SessionManager._instance = None


@pytest.fixture(autouse=True)
def _automationPrerequisitesHeldForEvidenceAxes(monkeypatch):
    """§8 自动化前置在测试里默认"齐备"，好让其它证据轴的判据仍然可达。

    为什么要有这一枚：晋升判据新增一道**结构性前置**（未满足即硬否决并点名），
    它在链首短路返回。不桩掉它，44 格在测"无回滚天数 / roi / 收敛结论 / 经验质量"
    的既有用例根本走不到自己那条轴——它们的断言与新前置无关，却被它一并挡在门外。

    这与 `tests/unit/evolution/conftest.py` 设计约束第 1 条（禁止私赋阶段、
    禁止伪造证据值"把缺陷洗成绿色"）**不冲突**：本夹具不伪造任何读数，
    它桩的是一条结构性能力读数，且：
      · 真值与桩的分工由 `tests/unit/evolution/rsi/test_automationPrerequisiteGate.py`
        反向钉住——该模块用**同名夹具**遮蔽本夹具，测的是未桩掉的真实否决；
      · 本夹具存在性有守卫（同文件 `test_scaffoldFixtureExistsAndIsOptOutable`），
        被静默摘掉时那里会红，不会变成一堵无主红墙。
    """
    from neurova.evolution.rsi import deployment_controller as controllerModule
    from neurova.evolution.rsi.gate_verdict import GateVerdict

    # `raising=False` 是实测逼出来的：接缝被改名/摘掉时，这里原本逐条抛
    # AttributeError —— 受保护子集实测**1553 条 error 全是同一句**，把真正的信号埋掉。
    # 夹具本身不响：控制器读不到桩就会走真实前置 ⇒ 依赖它的既有用例自己红。
    # **两条别重走的弯路**（都在摘掉接缝的工作树里实测过）：把"接缝还在吗"写成会话级
    # autouse 夹具 ⇒ 整场每条用例都 ERROR（228 条同句），只是换了报错文字；写成
    # `hasattr(controllerModule, …)` 的普通用例 ⇒ 恒真，因为 `raising=False` 的 setattr
    # 本来就会在模块上造出这个名字，检查者与被检查者同手。真正钉住"摘掉实装仍要红"的是
    # `tests/unit/evolution/rsi/test_automationPrerequisiteGate.py::TestControllerCarriesThePrerequisiteCell`
    # （同名夹具遮蔽后测未桩掉的否决），实测红 2 格、无错误墙。
    monkeypatch.setattr(
        controllerModule, "automationPrerequisiteVerdict",
        lambda *args, **kwargs: GateVerdict.passed("测试脚手架：前置按齐备处理"),
        raising=False)


@pytest.fixture(autouse=True)
def _guardRepoRootAgainstPollution():
    """单条用例执行前后，仓库根顶层条目不得新增——新增即红并点名该用例。

    为什么逐用例而不是整场：`MagicMock/…/.lifecycle_state.json` 这类泄漏在本仓复发过
    三次（`84260bb4`、`dd03d67c`"根目录二次清理 + gitignore 防再生"、2026-10-04 再现），
    每次都只能"清理 + 忽略"，因为整场快照给不出肇事用例；`.gitignore:380` 的
    `/MagicMock/` 更让它对 `git status` 彻底隐身。判据全文见
    `tests/unit/test_repo_root_pollution_guard.py` 与
    `audit-reports/simplification-audit-2026-10-05.md` §6-26/27。

    成本实测：单次 listdir 0.10ms，每条用例 2 次（3000 条约 0.6s）。
    不设例外名单——放行任何一个"会写根目录"的用例，就重演"用 ignore 当止痛"。
    """
    before = set(os.listdir(REPO_ROOT))
    yield
    added = sorted(set(os.listdir(REPO_ROOT)) - before)
    if added:
        raise AssertionError(
            "本条用例在仓库根新增了顶层条目 %s（进程 CWD=%s）——落盘路径必须由 "
            "core/data_root 的锚点或 tmp_path 推导，不得相对进程 CWD 写仓库根。"
            % (added, os.getcwd())
        )


@pytest.fixture(autouse=True)
def _guardSessionLandingIsIsolated(_isolateSessionsLanding):
    """用例结束时，`SessionManager` 单例不得指向仓库真实会话库。

    成因（§6-29）：`session_manager.py:205-207` 的落点第三档是 `dataLanding("sessions")`
    ——与进程 CWD 无关（`c2cb809c` 2026-09-22 收的口径）。于是历史上靠
    `monkeypatch.chdir(tmp_path)` 隔离会话目录的用例前提当场失效：它们读写的是仓库
    `data/sessions/`。`test_session_round_ops` 因此读到真实累计消息（6 passed/7 failed），
    `agent/test_p3_p4_refactor` 更是在全绿中往真实库建会话。

    为什么钉**装配点**而不是钉目录内容：目录内容判据要么每条用例取全树指纹（实测 99 文件
    4.71ms/次 → 每用例 9.4ms，全仓 2.1 万条 +200s），要么退化成 listdir 集合差——后者看不见
    原地改写与等量搬移（本条取证时就这么漏过一回：`test_session_archive` 报 added=0，
    实为搬动 15 个真实文件）。装配点判据 O(1)、逐用例归因，且**读写两侧都管**——读到真实
    数据同样是跨用例串味，不只是写脏用户库。

    分层职责：默认隔离（`_isolateSessionsLanding`）挡"没设"，本守卫挡"设错"——
    显式把落点改回仓库真实库的写法在这里红。只留默认值时一句 setenv 就能穿透，
    只留守卫时起真 app 的每条用例都得自己补 env。不设例外名单。

    形参 `_isolateSessionsLanding` 不是摆设：夹具按建立的逆序拆除，**不显式声明
    依赖时本守卫会在复位之后才跑，那时单例已被置 None，判据永远看不见肇事者**（实测就这么
    哑过一次）。声明依赖把顺序钉死。
    """
    yield
    module = sys.modules.get("neurova.session_manager")
    if module is None:
        return
    manager = getattr(module.SessionManager, "_instance", None)
    if manager is None:
        return
    landing = Path(str(manager._sessions_dir)).resolve()
    if landing == (REPO_ROOT / "data" / "sessions").resolve():
        raise AssertionError(
            "本条用例让 SessionManager 单例落在仓库真实会话库 %s——读会把真实累计数据当用例数据，"
            "写会写用户数据根。隔离只有一条通道：monkeypatch.setenv("
            "\"NEUROVA_SESSIONS_DIR\", str(tmp_path / \"sessions\")) 并把 "
            "SessionManager._instance 置 None（见 9495f1db）。" % landing
        )


@pytest.fixture(autouse=True)
def _isolateMobileDeviceRegistry(tmp_path, monkeypatch):
    """`/mobile/*` 的在册设备库与限流桶隔离（单点，各目录不自己抄）。

    在册设备自 §4.8 起是**持久**权威（SQLite），缺省落数据根——而本仓的数据根在跑测期
    是会话级共享目录（`neurovaDataRoot-*`，见本文件上方那条 `os.environ.setdefault`）。
    不隔离的后果实测过：两档用例共用一份库，前一档配的设备出现在后一档的列表里，
    读数长成"设备数 2 ≠ 1"，而肇事者与受害者不是同一条用例（逐档单跑恒绿）。
    构造处另有 `refuseSharedRootInTests()` 兜底：真漏了会点名用例红在那里，不往下传。

    `confirm`/`resolve`/`refresh` 的每 IP 滑窗桶（5 次/300s）同属模块级状态：跨文件不会
    自己过期，前一档配满次数就会让后一档把 429 读成业务失败。
    """
    import os

    from neurova.api.endpoints import mobile_pairing as mp

    dbPath = str(tmp_path / "mobile_devices.db")
    monkeypatch.setenv("NEUROVA_MOBILE_DEVICES_DB", dbPath)
    mp.resetDeviceRegistry()
    for suffix in ("", "-wal", "-shm"):
        stale = dbPath + suffix
        if os.path.exists(stale):
            os.remove(stale)
    mp._pairing_codes.clear()
    mp._confirm_attempts.clear()
    mp._ws_connections.clear()
    yield
    mp._confirm_attempts.clear()
    mp.resetDeviceRegistry()

@pytest.fixture
def mock_logger():
    """模拟日志记录器"""
    class MockLogger:
        def __init__(self):
            self.info_messages = []
            self.error_messages = []
            self.debug_messages = []
            self.warning_messages = []

        def info(self, msg):
            self.info_messages.append(msg)

        def error(self, msg):
            self.error_messages.append(msg)

        def debug(self, msg):
            self.debug_messages.append(msg)

        def warning(self, msg):
            self.warning_messages.append(msg)

    return MockLogger()


@pytest.fixture
def mock_event_bus():
    """模拟事件总线"""
    class MockEventBus:
        def __init__(self):
            self.events = []
            self.subscribers = {}

        def subscribe(self, event_type, callback):
            if event_type not in self.subscribers:
                self.subscribers[event_type] = []
            self.subscribers[event_type].append(callback)

        def emit(self, event_type, data=None):
            self.events.append((event_type, data))
            if event_type in self.subscribers:
                for callback in self.subscribers[event_type]:
                    callback(data)

    return MockEventBus()


@pytest.fixture
def temp_config(tmp_path):
    """临时配置目录"""
    return tmp_path / "config"


@pytest.fixture
def temp_workspace(tmp_path):
    """临时 Agent 工作目录

    用于 AgentConfig(workspace_path=...) 和 Agent(workspace_path=...) 测试。
    agent_core.py:215-220 强制要求 workspace_path 非空, 否则抛 ValueError。
    依赖此 fixture 的测试: test_agent.py 等。
    """
    workspace = tmp_path / "agent_workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


@pytest.fixture
def temp_db_path(tmp_path):
    """临时 SQLite DB 路径

    用于 Agent(db_path=...) 记忆模块测试。返回字符串形式路径。
    依赖此 fixture 的测试: test_agent.py 等。
    """
    db_dir = tmp_path / "memory"
    db_dir.mkdir(parents=True, exist_ok=True)
    return str(db_dir / "memory.db")


# ============================================================
# 语音引擎共享 fixtures
# ============================================================

@pytest.fixture
def mock_tts_manager():
    """模拟 TTSManager（向后兼容旧端点）"""
    manager = MagicMock()
    manager.is_initialized = True
    manager.get_engine_name.return_value = "mock-tts"
    manager.stats = {"initialized": True, "engine": "mock-tts"}
    manager.synthesize = AsyncMock(return_value=b"mock audio bytes")
    manager.synthesize_stream = AsyncMock()
    manager.shutdown = AsyncMock()
    return manager


@pytest.fixture
def mock_asr_manager():
    """模拟 ASRManager（向后兼容旧端点）"""
    manager = MagicMock()
    manager.is_initialized = True
    manager.get_engine_name.return_value = "mock-asr"
    manager.stats = {"initialized": True, "engine": "mock-asr"}
    manager.transcribe = AsyncMock(return_value={"text": "模拟识别结果", "language": "zh"})
    manager.understand = AsyncMock(return_value={"answer": "模拟理解结果"})
    manager.caption = AsyncMock(return_value={"caption": "模拟描述"})
    manager.shutdown = AsyncMock()
    return manager


@pytest.fixture
def mock_tts_voice_engine():
    """模拟 TTS VoiceEngine（新统一接口）"""
    from neurova.voice_engine import VoiceEngine, VoiceEngineType, VoiceResult

    engine = MagicMock(spec=VoiceEngine)
    engine.engine_type = VoiceEngineType.TTS
    engine.is_available.return_value = True
    engine.get_info.return_value = {
        "engine_type": "tts",
        "is_initialized": True,
        "engine_class": "MockTTS",
    }
    engine.process = AsyncMock(return_value=VoiceResult(
        audio_data=b"mock audio bytes",
        metadata={"operation": "synthesize", "engine": "mock-tts"},
    ))
    return engine


@pytest.fixture
def mock_asr_voice_engine():
    """模拟 ASR VoiceEngine（新统一接口）"""
    from neurova.voice_engine import VoiceEngine, VoiceEngineType, VoiceResult

    engine = MagicMock(spec=VoiceEngine)
    engine.engine_type = VoiceEngineType.ASR
    engine.is_available.return_value = True
    engine.get_info.return_value = {
        "engine_type": "asr",
        "is_initialized": True,
        "engine_class": "MockASR",
    }
    engine.process = AsyncMock(return_value=VoiceResult(
        text="识别结果",
        confidence=0.95,
        metadata={"operation": "transcribe", "engine": "mock-asr"},
    ))
    return engine


@pytest.fixture
def mock_failing_voice_engine():
    """模拟会失败的 VoiceEngine"""
    from neurova.voice_engine import VoiceEngine, VoiceEngineType, VoiceResult

    engine = MagicMock(spec=VoiceEngine)
    engine.engine_type = VoiceEngineType.TTS
    engine.is_available.return_value = True
    engine.process = AsyncMock(return_value=VoiceResult(error="引擎故障"))
    return engine


@pytest.fixture
def mock_agent():
    """模拟 Agent 实例（用于 pipeline/agent 相关测试）"""
    agent = MagicMock()
    agent._turn_count = 0
    agent._collect_tool_messages.return_value = []
    agent._save_to_session = MagicMock()
    agent.conversation_buffer = MagicMock()
    agent.memory_manager = MagicMock()
    agent.memory_manager.remember = AsyncMock()
    agent.memory_agent = MagicMock()
    agent.post_chat_pipeline = MagicMock()
    agent.post_chat_pipeline.execute = AsyncMock(return_value=None)
    return agent


# ============================================================
# AutoVoiceEngine 共享 fixtures
# ============================================================

@pytest.fixture
def available_engine():
    """可用的模拟引擎（用于 AutoVoiceEngine 测试）"""
    engine = MagicMock()
    engine.is_initialized = True
    engine.synthesize = AsyncMock(return_value=b"audio data")
    engine.transcribe = AsyncMock(return_value={"text": "识别结果"})
    return engine


@pytest.fixture
def failing_engine():
    """会失败的模拟引擎（用于 AutoVoiceEngine 测试）"""
    engine = MagicMock()
    engine.is_initialized = True
    engine.synthesize = AsyncMock(return_value=b"")
    engine.transcribe = AsyncMock(return_value={"text": "", "error": "引擎故障"})
    return engine


@pytest.fixture
def unavailable_engine():
    """不可用的模拟引擎（用于 AutoVoiceEngine 测试）"""
    engine = MagicMock()
    engine.is_initialized = False
    return engine


@pytest.fixture
def mock_auto_tts_engine(available_engine):
    """模拟自动 TTS 引擎（AutoVoiceEngine）"""
    from neurova.voice_engine import AutoVoiceEngine, VoiceEngineType
    return AutoVoiceEngine(
        engine_type=VoiceEngineType.TTS,
        engines=[available_engine],
    )


@pytest.fixture
def mock_auto_asr_engine(available_engine):
    """模拟自动 ASR 引擎（AutoVoiceEngine）"""
    from neurova.voice_engine import AutoVoiceEngine, VoiceEngineType
    return AutoVoiceEngine(
        engine_type=VoiceEngineType.ASR,
        engines=[available_engine],
    )



# ---------------------------------------------------------------------------
# 仓库文件防污染隔离
# ---------------------------------------------------------------------------
# 历史事故（2026-09，dee84dc）: settings API 的 CORS PUT 会写仓库 config/cors.json，
# 测试期写入的 evil.example.com 被误提交入库，随安装包分发后桌面端注册/登录全挂。
# 统一重定向：测试会话期间 CORS 配置只落临时目录，永不碰仓库真实文件。
#
# 接缝 2026-10-14 起单点在 `cors_policy.configFile`（此前中间件与管理端各算一遍落点，
# 因此要 patch 两处；收口后这一个接缝盖住读写两侧，patch 漏一处的静默失效面也随之消失）。

@pytest.fixture(autouse=True)
def _isolate_cors_config_file(tmp_path, monkeypatch):
    """所有测试的 CORS 配置读写都指向临时目录。"""
    try:
        from neurova.api import cors_policy as _cors_policy
    except Exception:  # pragma: no cover - settings 依赖缺失时跳过
        return
    monkeypatch.setattr(_cors_policy, "configFile", lambda: tmp_path / "cors.json")


# ---------------------------------------------------------------------------
# Token 用量历史库防污染隔离
# ---------------------------------------------------------------------------
# usage_history（神经va/core/usage_history.py）默认落 data/usage_history.db；
# multi_model_client 入账路径会写入它，测试期直接落盘会污染仓库 data/。
# 统一指向每测试临时目录（含单例重建），与 _isolate_cors_config_file 同模式。

@pytest.fixture(autouse=True)
def _isolate_usage_history(tmp_path, monkeypatch):
    """所有测试的 usage_history 落盘指向临时目录。"""
    monkeypatch.setenv("NEUROVA_USAGE_HISTORY_DB", str(tmp_path / "usage_history.db"))
    try:
        from neurova.core.usage_history import reset_usage_history
    except Exception:  # pragma: no cover - 模块未就绪时跳过
        return
    reset_usage_history()


# ---------------------------------------------------------------------------
# 元认知台账防污染隔离
# ---------------------------------------------------------------------------
# MetaLedger（neurova/cognitive_layers/meta_cognition_layer/ledger.py）默认落
# data/metacognition.db；B/C 写穿透与 API 测试都会写它，测试期直接落盘会污染
# 仓库 data/。统一指向每测试临时目录（含单例重建），与 _isolate_usage_history 同模式。

@pytest.fixture(autouse=True)
def _isolate_governance_settings(tmp_path, monkeypatch):
    """所有测试的治理设置（governance_settings.json）指向临时目录。

    data/governance_settings.json 是运行时管理面（RSI 部署阶段/对话规则提取
    门控），读写真实文件会（a）污染仓库 data/（b）让测试读到彼此的开关值。
    与 _isolate_usage_history 同模式。
    """
    monkeypatch.setenv("NEUROVA_GOVERNANCE_SETTINGS", str(tmp_path / "governance_settings.json"))


@pytest.fixture(autouse=True)
def _isolate_rsi_proposal_ledger(tmp_path, monkeypatch):
    """RSI 提案台账（SelfImprovementProposer 的 proposals 根目录）指向临时目录。

    工单 010 之前它硬编码仓库根同名目录，且构造即 mkdir —— 于是每个构造编排器的
    用例都在往工作树里写提案，实测一次八目录套件留下 873 个 JSON
    （`sleep` 429 / `emotion` 175 / `tool_memory` 157 / `experience` 112）。
    台账按 agent 分域之后，根路径仍可注入；这里统一注入到每测试临时目录。
    """
    monkeypatch.setenv("NEUROVA_PROPOSALS_ROOT", str(tmp_path / "rsi-proposal-ledger"))


@pytest.fixture(autouse=True)
def _isolate_evolution_state_paths(tmp_path, monkeypatch):
    """进化状态持久化各件统一指向每测试临时目录。

    `bootstrap_evolution_persistence` 按 env 解析默认路径；调用方只覆盖其中
    四件时，第五件（技能经验库）就写进仓库 `data/evolution/skill_experiences.json`
    —— 实测 `test_evolution_state_persistence.py` 单跑一次即改写该生产文件。
    工单 016 给 `AutoSkillImprover` 挂持久化，泄漏面会再多一处，故先在根 conftest
    收口（默认值也注入，测试自己不再需要逐个补 env）。
    """
    state_dir = tmp_path / "evolution"
    for key, name in (
        ("NEUROVA_EVOLUTION_WEIGHTS", "tool_weights.json"),
        ("NEUROVA_EVOLUTION_PATTERNS", "pattern_sequences.json"),
        ("NEUROVA_EVOLUTION_LIFECYCLE", "tool_lifecycle.json"),
        ("NEUROVA_EVOLUTION_EXPERIENCE", "experience_feedback.json"),
        ("NEUROVA_EVOLUTION_SKILL_EXPERIENCE", "skill_experiences.json"),
    ):
        monkeypatch.setenv(key, str(state_dir / name))


@pytest.fixture(autouse=True)
def _isolate_evolution_job_queue(tmp_path, monkeypatch):
    """所有测试的进化作业队列落盘指向临时目录（含单例重建）。

    EvolutionJobQueue（neurova/evolution/job_queue.py）默认落
    data/evolution/jobs.db；进化队列开关默认开（2026-09-15 SettingPage 收口）
    后，post_chat 每轮都会 enqueue/drain——不隔离即污染仓库 data/ 并让
    测试互相看到作业。
    """
    monkeypatch.setenv("NEUROVA_EVOLUTION_JOBS_DB", str(tmp_path / "evolution_jobs.db"))
    try:
        from neurova.evolution.job_queue import reset_evolution_job_queue

        reset_evolution_job_queue()
    except Exception:  # pragma: no cover - 模块未就绪时跳过
        pass


@pytest.fixture(autouse=True)
def _disable_skill_semantic_in_tests(monkeypatch):
    """语义档测试全局关：召回热路径的懒解析永不加载 ONNX 模型/不触下载器。

    专属测试（wave E/F）用显式注入的 fake engine 绕过 env（SkillVectorCache
    对显式 engine 不吃开关，见 _get_engine 注释）；生产默认行为不受影响。
    """
    monkeypatch.setenv("NEUROVA_SKILL_SEMANTIC", "0")


@pytest.fixture(autouse=True)
def _isolate_turn_context():
    """每测试清回合上下文（Wave H 测试卫生）。

    生产安全前提：asyncio 每请求 task 的 context 拷贝隔离，
    set_turn_skill_view 等不跨请求泄漏；但 pytest 同线程直调 chat_pipeline
    全链测试会把 view/funnel 残留到后续测试（task_name_params 等被视图门
    误拒的批跑失败根因，2026-09-15）。
    """
    try:
        from neurova.core import turn_context

        turn_context.clear_turn_state()
    except Exception:  # pragma: no cover - 模块未就绪时跳过
        pass
    yield
    try:
        from neurova.core import turn_context

        turn_context.clear_turn_state()
    except Exception:  # pragma: no cover
        pass


@pytest.fixture(autouse=True)
def _isolate_neurflow_storage(tmp_path, monkeypatch):
    """NeurflowStorage 默认路径隔离。

    NeurflowStorage(db_path="neurflow.db") 是 cwd 相对路径 → 测试从仓库根
    运行时读到开发者的真实 neurflow.db：其中"已发布"工作流经 workflow_as_tool
    （P1-3）注入 LLM 工具面，使所有经 _build_tools_for_llm 的测试随本机数据
    漂移（同 EKB 单例打真库事故根因）。默认构造重定向到每测试临时库；
    显式传 db_path 的专属测试不受影响。同时清 neurflow_api._get_storage 的
    函数属性缓存，防上一测试的临时库句柄泄漏到下一测试。
    """
    try:
        import neurova.collaboration.neurflow.storage as _nstor
    except Exception:  # pragma: no cover - 模块未就绪时跳过
        return
    real_cls = _nstor.NeurflowStorage
    tmp_db = str(tmp_path / "neurflow.db")

    class _IsolatedStorage(real_cls):
        def __init__(self, db_path: str = "neurflow.db"):
            super().__init__(tmp_db if db_path == "neurflow.db" else db_path)

    monkeypatch.setattr(_nstor, "NeurflowStorage", _IsolatedStorage)
    try:
        import neurova.api.endpoints.neurflow_api as _napi

        if hasattr(_napi._get_storage, "_instance"):
            del _napi._get_storage._instance
        # neurflow_api 模块顶层若已绑定旧类引用，一并替换
        monkeypatch.setattr(_napi, "NeurflowStorage", _IsolatedStorage, raising=False)
    except Exception:  # pragma: no cover
        pass


@pytest.fixture(autouse=True)
def _isolate_meta_ledger(tmp_path, monkeypatch):
    """所有测试的元认知台账落盘指向临时目录。

    （合并残留：本文件内曾定义两次，后者静默遮蔽前者——2026-09-06 收敛为一份。）
    MetaLedger（neurova/cognitive_layers/meta_cognition_layer/ledger.py）默认落
    data/metacognition.db；B/C 写穿透与 API 测试都会写它，测试期直接落盘会污染
    仓库 data/。统一指向每测试临时目录（含单例重建），与 _isolate_usage_history 同模式。
    """
    monkeypatch.setenv("NEUROVA_META_LEDGER_DB", str(tmp_path / "metacognition.db"))
    try:
        from neurova.cognitive_layers.meta_cognition_layer.ledger import reset_meta_ledger
    except Exception:  # pragma: no cover - 模块未就绪时跳过
        return
    reset_meta_ledger()


@pytest.fixture(autouse=True)
def _isolate_ekb(tmp_path, monkeypatch):
    """所有测试的经验知识库（EKB）落盘指向临时目录。

    根因（3920 条垃圾经验事故 2026-09-06）：管线级测试用 MagicMock
    evolution（hasattr 恒真）→ _step_record_experience 的 EKB 写入分支必执行，
    模块单例默认打生产库 data/experience_knowledge.db，测试对话
    （"Hello" ×1223 等）全部灌进真库。与 _isolate_meta_ledger 同模式：
    环境变量指向 tmp_path + 单例重建。
    """
    monkeypatch.setenv("NEUROVA_EKB_DB", str(tmp_path / "experience_knowledge.db"))
    try:
        from neurova.skills.experience_knowledge_base import (
            reset_experience_knowledge_base,
        )
    except Exception:  # pragma: no cover - 模块未就绪时跳过
        return
    reset_experience_knowledge_base()
    yield
    reset_experience_knowledge_base()


@pytest.fixture(autouse=True)
def _reset_memory_request_scope():
    """每个测试后归还未设置态：MemoryManager 的请求作用域是模块级 ContextVar。

    根因（2026-09-12 甄别）：set_request_scope 的"随请求上下文销毁"仅对
    异步任务成立——pytest 单线程同步执行下 ContextVar 值跨测试存活，
    任一测试 set_request_scope 后不归还，后续测试的记忆写入/读取全部落在
    被污染的作用域上（曾致 test_moe_router_reads_persist_db 顺序依赖失败：
    remember 写进 user_id='7' 的作用域，MoE 适配器按 n1/u1 过滤读空）。
    """
    yield
    try:
        from neurova.cognitive_layers.memory_layer.manager import (
            clear_memory_request_scope,
        )
    except Exception:  # pragma: cover - 模块未就绪时跳过
        return
    clear_memory_request_scope()


@pytest.fixture(autouse=True)
def _reclaimIdleMonitors():
    """每格结束回收本轮仍活跃的空闲监控线程（`idle-tracker-monitor`）。

    为什么按格而不是按会话：整场 `pytest tests/unit` 曾在 92% 处
    `STATUS_STACK_OVERFLOW` 崩机，dump 里数十条线程同名——`agent_core.py:1406` 逐 Agent
    起监控线程，而全仓**只有一个**地方会关它（`Agent.shutdown()` → `agent_core.py:2087`
    → `shutdown_agent`）⇒ 没被显式关闭的 Agent 一律留一条线程。生产那对手本批已配平
    （`agent_shutdown.py`），但"建完就丢"这件事本身只有测试侧收得掉（§6-407 批 O-2）。
    """
    yield
    try:
        from neurova.core.idle_tracker import stopAllIdleMonitors
    except Exception:  # pragma: cover - 模块未就绪时不拦跑测
        return
    stopAllIdleMonitors()


# ---------------------------------------------------------------------------
# 跑测层「真权重出网」门（§6-201 登记的跑测环境缺陷家族，批 44 立）
# ---------------------------------------------------------------------------
# 实状：`models/**/*.data`（moss 权重 670MB）是未跟踪件，而入 git 的 5 只 `.onnx`
# 让 `models/tts/moss-nano/` 在任何仓外 worktree 里都「看着存在」⇒ 用例里那句
# 「目录存在＝有权重」是假前置。走到 `ensure_model` 的用例于是发真 HTTPS 下载 +
# 退避 sleep：`test_ttl_release_switches_to_light_engine` 实测 HEAD 干净 worktree
# 单格 31s、本树 19.32s；全局 `timeout = 30` 的 thread 法一到点就把整场打死，
# A/B 因此拿不到汇总行（批 42、批 43 各烧掉一轮宽域自证）。
#
# 口径只在这里定义一次：登记表 = 仓内直接调外部权重下载的那几处
# （`snapshot_download` / `hf_hub_download` / `HubApi`），由
# `tests/unit/test_weightEgressGateRefusesBeforeBytes.py` 按 AST 反证覆盖面；
# 「本机有没有权重」一律走 `ModelDownloader.is_model_available`（它按
# `required_files` 逐件数，含那两份 .data），不另造第二份完整性谓词。
# 真权重用例改挂 `@pytest.mark.real_model(<模型名>)`——门对它们同样关着，
# 缺件只 skip，不许现场补下载。

_WEIGHT_EGRESS_SITES = (
    ("neurova.tts.model_downloader", "_download_via_modelscope"),
    ("neurova.tts.model_downloader", "_download_via_hf_mirror"),
    ("neurova.tts.model_downloader", "_download_via_huggingface"),
)


class _WeightEgressGate:
    """出网那一层的拒绝桩 + 「本机有权重」的单源判定。"""

    def __init__(self, sites):
        self.sites = tuple(sites)
        self.trips = []

    def refusalFor(self, moduleName, attr):
        trips = self.trips

        def _refuse(*_args, **_kwargs):
            trips.append(f"{moduleName}.{attr}")
            raise RuntimeError(
                f"跑测层禁止真出网取权重（被拦: {moduleName}.{attr}）。"
                "要读真权重：给该用例挂 @pytest.mark.real_model(<模型名>) 且本机件齐；"
                "要测下载逻辑：自己把这一处打桩（既有下载档都这么做）。")

        return _refuse

    def requireWeightsOrSkip(self, modelNames, baseDir=None):
        """缺件即 skip；判定与生产共用同一个下载器实例（baseDir 仅供判据造缺件场景）。"""
        if baseDir is None:
            from neurova.tts.model_downloader import get_model_downloader

            downloader = get_model_downloader()
        else:
            from neurova.tts.model_downloader import ModelDownloader

            downloader = ModelDownloader(base_dir=str(baseDir))
        missing = [name for name in modelNames if not downloader.is_model_available(name)]
        if missing:
            pytest.skip(
                f"真权重不齐（本机缺 {missing}）——real_model 用例的前提是本地齐件，"
                "不在此处补下载")


_weightEgressGate = _WeightEgressGate(_WEIGHT_EGRESS_SITES)


def pytest_configure(config):
    config.pluginmanager.register(_weightEgressGate, "weightEgressGate")


@pytest.fixture(autouse=True)
def _closeWeightEgressDuringTests(request, monkeypatch):
    """跑测期把三处权重下载点换成点名拒绝（在写出任何字节之前）。

    用例自己 setattr 的桩在本夹具之后生效、覆盖它——既有下载类档照旧可跑。
    """
    marker = request.node.get_closest_marker("real_model")
    if marker is not None:
        if not marker.args:
            pytest.fail(
                "real_model 标记必须点名它需要哪些权重，"
                "例如 @pytest.mark.real_model('moss-tts-nano')")
        _weightEgressGate.requireWeightsOrSkip(tuple(marker.args))
    import importlib

    for moduleName, attr in _WEIGHT_EGRESS_SITES:
        site = importlib.import_module(moduleName)
        monkeypatch.setattr(site, attr, _weightEgressGate.refusalFor(moduleName, attr))

# ── 锚文件的测试隔离（§6-388）──────────────────────────────────────────────
# 生产的锚落点是 `<数据根>/artifacts/artifact_anchors.json`（取法见
# `artifact_digest.anchorPath` 的注释）。跑测时任何一次"钉摘要/装技能/装插件"都会
# 去写那儿——默认按与数据根同形的思路改指临时目录，免得落进某个用例自己的隔离根。
# 注意这条夹具**不改变**落点语义：锚仍与账本同根（整库回滚的检测边界见台账）。
ANCHOR_SESSION_DIR = Path(tempfile.mkdtemp(prefix="neurovaAnchors-"))


@pytest.fixture(autouse=True)
def _isolateArtifactAnchors(monkeypatch):
    """按调用期改指（`anchorPath()` 是函数，不是模块级常量，所以 per-test 来得及）。"""
    from neurova.security import artifact_digest

    monkeypatch.setattr(artifact_digest, "anchorPath",
                        lambda: ANCHOR_SESSION_DIR / "artifact_anchors.json")
