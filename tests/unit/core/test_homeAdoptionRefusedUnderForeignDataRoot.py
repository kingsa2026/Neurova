# -*- coding: utf-8 -*-
"""主目录旧物只在「操作者自己的数据根」下才被收养（§6-204）。

起因不是推测而是实测：§6-203 把 `~/.neurova/` 那四族改成"空缺时收养进来"，收养用的是
`shutil.move`；而 `tests/conftest.py:58` 把整轮跑测的数据根注入到临时目录，**home 没有被
一起隔离**。于是本仓 2026-10-14 一次普通跑测（`Temp/neurovaDataRoot-8ur_l8p6/`）把开发者的
`providers.json`（18 家、13 份加密凭据）、`audit.db`（2361 行审计）、`governance_whitelist.json`
从主目录**搬进了那个临时根**。本会话按哈希比对把它复原回 `data/`。

为什么根修在收养端而不是"给跑测再补一份 home 隔离"：`~/.neurova` 不属于这个项目，
任何进程——跑测、取证探针、别人指定的落点——都不该把一个进程的一次运行当成用户的升级
意图。判据只看一件事：本进程的数据根是不是操作者自己的那一址。这一处判完，跑测面与
探针面同时被盖住，不必两处各立一份规矩。

不碰真实主目录：所有格子都在 `monkeypatch` 出来的假 home 与临时数据根上做。
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import pytest

from neurova.core import data_root
from neurova.core.data_root import DATA_ROOT_ENV

NEUROVA = Path(__file__).resolve().parents[3] / "neurova"
sys.path.insert(0, str(NEUROVA.parent))  # 仓根进 sys.path，`from tests import ast_scan` 才取得到

from tests import ast_scan  # noqa: E402

#: 四族落点的解析函数所在文件——形状格逐个问它走没走带闸的入口。
_FACE_FILES = (
    "llm/provider_manager.py",
    "security/audit_logger.py",
    "security/governance.py",
    "skills/hub_client.py",
)


@pytest.fixture()
def fakeHome(tmp_path, monkeypatch) -> Path:
    """把 `Path.home()` 指到临时目录——真主目录本轮一个字都不碰。"""
    fake = tmp_path / "fakeHome"
    fake.mkdir()
    monkeypatch.setattr("pathlib.Path.home", lambda: fake)
    return fake


def _useForeignRoot(monkeypatch, tmp_path) -> None:
    """把数据根显式注入到**不等于默认推导**的一址（跑测临时根就是这个形状）。"""
    monkeypatch.setattr(data_root, "_REPO_ROOT", tmp_path / "theOperatorsRepo")
    monkeypatch.setenv(DATA_ROOT_ENV, str(tmp_path / "elsewhereRoot"))


def _seedHomeConfig(home: Path, relpath: str, payload: str = "SENTINEL") -> Path:
    legacy = home / ".neurova" / relpath
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(payload, encoding="utf-8")
    return legacy


def _providerPayload() -> str:
    return json.dumps({"providers": [{"id": "glm", "name": "GLM"}],
                       "default_provider_id": "glm"}, ensure_ascii=False)


def _calledNames(relPath: str) -> set:
    """文件里被调用的名字（AST 形态，注释与 docstring 里的提法不算调用）。"""
    import ast

    tree = ast.parse((NEUROVA / relPath).read_text(encoding="utf-8", errors="replace"))
    names = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            names.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            names.add(node.func.attr)
    return names


class TestForeignRootMustNotTouchHome:
    """数据根被指到别处时，主目录那份一个字都不动、也不另搬一份出来。"""

    def test_providerCredentialsStayPut(self, fakeHome, monkeypatch, tmp_path):
        from neurova.llm.provider_manager import _default_config_dir

        _useForeignRoot(monkeypatch, tmp_path)
        legacy = _seedHomeConfig(fakeHome, "config/providers.json", _providerPayload())
        targetDir = _default_config_dir()

        assert legacy.exists(), "凭据被搬进了一个临时数据根（§6-203 实测形态）"
        assert not (targetDir / "providers.json").exists(), "旧物在别处根凭空复制了一份"

    def test_auditDbAndSidecarsStayPut(self, fakeHome, monkeypatch, tmp_path):
        from neurova.security.audit_logger import auditDbPath

        _useForeignRoot(monkeypatch, tmp_path)
        main = _seedHomeConfig(fakeHome, "audit.db", "AUDIT-MAIN")
        wal = _seedHomeConfig(fakeHome, "audit.db-wal", "AUDIT-WAL")
        path = auditDbPath()

        assert main.exists() and wal.exists(), "审计库或 -wal 被搬走（未 checkpoint 的帧就没了）"
        assert not Path(path).exists(), "新落点凭空出现一份审计库"

    def test_governanceWhitelistStaysPut(self, fakeHome, monkeypatch, tmp_path):
        from neurova.security.governance import _default_whitelist_path

        _useForeignRoot(monkeypatch, tmp_path)
        legacy = _seedHomeConfig(
            fakeHome, "config/governance_whitelist.json",
            json.dumps({"entries": [{"pattern": "git status"}], "updated_at": "x"}))
        target = _default_whitelist_path()

        assert legacy.exists(), "白名单被搬进临时根"
        assert not target.exists(), "别处根下凭空长出一份白名单"

    def test_skillHubInstalledDirStaysPut(self, fakeHome, monkeypatch, tmp_path):
        from neurova.skills.hub_client import SkillHubClient

        _useForeignRoot(monkeypatch, tmp_path)
        legacySkill = _seedHomeConfig(
            fakeHome, "skills/installed/pkg-a/skill.json", "{}")
        client = SkillHubClient()

        assert legacySkill.exists(), "技能包体被搬进临时根"
        # 构造自己会 mkdir(installed)，所以判"没搬进来"只能看**内容**——
        # 断空目录存在与否会绿得没道理。
        assert not (client._installed_dir / "pkg-a").exists(), "旧包体凭空出现在别处根下"


class TestSkipIsNamedNotSilent:
    """点名而不是静默跳过：桌面部署若把数据根长期指到别处，操作者得知道旧物还在原地。"""

    def test_skippedAdoptionLogsTheHomePathOnce(self, fakeHome, monkeypatch, tmp_path, caplog):
        from neurova.security.governance import _default_whitelist_path

        _useForeignRoot(monkeypatch, tmp_path)
        legacy = _seedHomeConfig(fakeHome, "config/governance_whitelist.json", "{}")
        with caplog.at_level(logging.WARNING, logger="neurova.core.data_root"):
            _default_whitelist_path()
            _default_whitelist_path()

        hits = [r for r in caplog.records if str(legacy) in r.getMessage()]
        assert hits, "静默跳过＝用户以为配置没生效，其实只是本进程没权利搬"
        assert len(hits) == 1, "落点解析在读写路径上反复被调用，逐次告警会刷屏"

    def test_noWarningWhenHomeHasNothing(self, fakeHome, monkeypatch, tmp_path, caplog):
        from neurova.security.governance import _default_whitelist_path

        _useForeignRoot(monkeypatch, tmp_path)
        with caplog.at_level(logging.WARNING, logger="neurova.core.data_root"):
            _default_whitelist_path()

        assert [r for r in caplog.records if ".neurova" in r.getMessage()] == [], (
            "反空转格：无旧物也要报警＝告警恒发，真信号被淹没"
        )


class TestOperatorsOwnRootStillAdopts:
    """闸不是总开关：操作者自己的那一址照常收养，升级路径不能被这条判据焊死。"""

    def test_defaultDerivationWithoutEnvStillMoves(self, fakeHome, monkeypatch, tmp_path):
        from neurova.llm.provider_manager import _default_config_dir

        monkeypatch.setattr(data_root, "_REPO_ROOT", tmp_path / "repo")
        monkeypatch.delenv(DATA_ROOT_ENV, raising=False)
        legacy = _seedHomeConfig(fakeHome, "config/providers.json", _providerPayload())

        targetDir = _default_config_dir()

        moved = targetDir / "providers.json"
        assert moved.exists() and moved.read_text(encoding="utf-8") == _providerPayload(), (
            "升级路径没把旧凭据收进来"
        )
        assert not legacy.exists(), "旧物留在原地＝同一份凭据两个落点"

    def test_envInjectedToTheSameRootStillMoves(self, fakeHome, monkeypatch, tmp_path):
        from neurova.llm.provider_manager import _default_config_dir

        repo = tmp_path / "repo"
        monkeypatch.setattr(data_root, "_REPO_ROOT", repo)
        monkeypatch.setenv(DATA_ROOT_ENV, str(repo / "data"))  # 与默认推导逐字相同
        legacy = _seedHomeConfig(fakeHome, "config/providers.json", _providerPayload())

        targetDir = _default_config_dir()

        assert (targetDir / "providers.json").exists(), (
            "注入的根就是默认那一址时也拒收养＝把救济做成了开关"
        )
        assert not legacy.exists()


class TestHomeAdoptionHasExactlyOneGate:
    """形状格：够得着主目录的只有那一个带闸的入口，防止第五处绕开它手拼。"""

    def test_legacyHomeLandingIsCalledOnlyInsideDataRoot(self):
        import ast

        callers = set()
        sources = list(ast_scan.filesUnder(NEUROVA))
        surface = len(sources)
        assert surface > 500, f"扫描面现读 {surface} 个 .py（根＝neurova/）——根被改窄时「零命中」不代表干净"
        # 枚举与解析都走 tests/ast_scan.py 的一次性入口（`filesUnder` 原地剪产物目录，
        # `transientTree` 不留常驻语法树）——共享枚举 + 自付 ast.parse 是门禁点名的免检通道
        for py in sources:
            try:
                tree = ast_scan.transientTree(py)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                name = func.id if isinstance(func, ast.Name) else (
                    func.attr if isinstance(func, ast.Attribute) else "")
                if name == "legacyHomeLanding":
                    callers.add(py.relative_to(NEUROVA).as_posix())
        assert callers == {"core/data_root.py"}, (
            "home 旧落点的取法出了一号仓库（各算一遍就是各判一次要不要搬）：\n%s"
            % sorted(callers)
        )

    def test_eachFaceGoesThroughTheGatedAdoption(self):
        for rel in _FACE_FILES:
            names = _calledNames(rel)
            assert any(n.startswith("adoptHomeLanding") for n in names), (
                "%s 没走带闸的收养入口" % rel
            )
            assert "adoptLandingFrom" not in names, (
                "%s 仍在直用无闸原语——闸就形同虚设" % rel
            )
