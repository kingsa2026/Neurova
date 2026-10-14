"""CORS 口径单源 + 面板与中间件必须同值（§6-199，序 9 双源口径批）。

现读实状（动手前逐处自己命中，不抄台账）：
- 同一份 8 项 origins 白名单写了两遍：`api/middleware.py:194-203` 与
  `api/endpoints/settings.py:93-102`；
- `allow_methods` / `allow_headers` 那两条清单写了 **6 遍**：`middleware.py:258-259`、
  `settings.py:344-345`（模型缺省）、`:369-370`（读不到文件时的兜底 dict）、
  `:398-399`（GET 的 `config.get` 缺省）、`:447-448`（PUT 响应回显缺省）；
- 行为分叉一条：三级优先（env `NEUROVA_CORS_ORIGINS` > `config/cors.json` > 默认值）
  只有中间件实现（`middleware.py:206-240`），而管理端 `GET /api/v1/settings/cors` 走
  `settings.py:360-371` **不看 env**——设了 env 之后，面板显示的还是文件/默认值，
  实际生效的是 env。管理员照着面板改白名单，改的是一份**没在生效**的清单。

收口口径：唯一事实源 `neurova/api/cors_policy.py`（名单、方法、头、落点、三级优先各一处），
中间件与管理端都从它取；且**收口前后允许集合逐字等值**（本档第 5 格钉住，防"顺手放宽/收紧"）。
"""

from __future__ import annotations

import ast
import json
import pathlib
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests import ast_scan  # noqa: E402

NEUROVA = REPO_ROOT / "neurova"

POLICY = "neurova/api/cors_policy.py"
REPO_CORS_CONFIG = REPO_ROOT / "config" / "cors.json"

#: 桌面壳 origin 是这两条——把两者一起写进一个字面量，就是一份" origins 白名单副本"
TAURI_PAIR = {"http://tauri.localhost", "https://tauri.localhost"}
#: 六个 HTTP 方法凑齐，就是一份 methods 清单副本
METHOD_MARKERS = {"PATCH", "OPTIONS"}


def _literalGroups(source: str):
    """一份源码里所有"字面量集合"（list/set/tuple）的字符串成员集合。"""
    groups = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return groups
    for node in ast.walk(tree):
        if isinstance(node, (ast.List, ast.Set, ast.Tuple)):
            items = [e.value for e in node.elts
                     if isinstance(e, ast.Constant) and isinstance(e.value, str)]
            if items:
                groups.append(set(items))
    return groups


def _hostsDefining(required: set) -> set:
    """按 AST 找"把某组字面量整套写全"的文件——判的是副本存在，不钉变量名。

    取数走 `ast_scan.transientNodes`（一次性入口，不留常驻语法树）＋**文本预筛**：
    一份完整副本必然把这些字面量原样写在该文件里，所以连关键词都没出现的文件不可能命中
    ——预筛是充分条件，缩面不缩判据。
    """
    hosts = set()
    for path, node in ast_scan.transientNodes(NEUROVA, hints=tuple(sorted(required))):
        if not isinstance(node, (ast.List, ast.Set, ast.Tuple)):
            continue
        items = {e.value for e in node.elts
                 if isinstance(e, ast.Constant) and isinstance(e.value, str)}
        if items and required <= items:
            hosts.add(ast_scan.relativeToRepo(path))
    return hosts


def _policy():
    import importlib

    return importlib.import_module("neurova.api.cors_policy")


def _assembledCors(monkeypatch, config_file=None) -> dict:
    """按 `setup_middleware` **装配后的实参**读中间件那侧的生效值。

    读装配实参而不是读某个取数函数：面板要和"真正决定预检结果的那一份"比同不同，
    比两份都可能不在生效的读数，量不到这次的分叉。
    """
    from fastapi import FastAPI
    from starlette.middleware.cors import CORSMiddleware

    from neurova.api import cors_policy as CP
    from neurova.api import middleware as MW

    if config_file is not None:
        monkeypatch.setattr(CP, "configFile", lambda: pathlib.Path(config_file))
    app = FastAPI()
    MW.setup_middleware(app)
    entries = [m for m in app.user_middleware if m.cls is CORSMiddleware]
    assert len(entries) == 1, f"CORS 中间件应装配 1 处，读到 {len(entries)} 处"
    return entries[0].kwargs


class TestOriginsAreSingleSource:
    def testOriginAllowListHasExactlyOneHost(self):
        hosts = _hostsDefining(TAURI_PAIR)
        assert hosts == {POLICY}, (
            f"桌面壳 origin 那份 8 项白名单出现在 {sorted(hosts)}——两处名单就是两本账，"
            "改一处忘一处（middleware 与 settings 曾各持一份）")

    def testMethodAndHeaderListsHaveExactlyOneHost(self):
        hosts = _hostsDefining(METHOD_MARKERS)
        assert hosts == {POLICY}, (
            f"allow_methods/allow_headers 的字面量清单散在 {sorted(hosts)}——建档时实测 6 处，"
            "收口后只许 cors_policy 一处")

    def testDetectorNamesASecondCopy(self):
        """反空转格：探测器必须认得"另起一份清单"这个动作本身。

        不配这一格的话，一个恒返回空集的探测器与真守卫在绿灯下不可分辨。
        """
        sample = ('X = ["http://tauri.localhost", "https://tauri.localhost"]\n'
                  'Y = ["GET", "PATCH", "OPTIONS"]\n')
        groups = _literalGroups(sample)
        assert any(TAURI_PAIR <= g for g in groups), "漏认 origins 副本"
        assert any(METHOD_MARKERS <= g for g in groups), "漏认 methods 副本"


class TestPanelAndMiddlewareShowTheSameValue:
    def testEnvOverrideIsHonouredOnBothSides(self, monkeypatch, tmp_path):
        """设了 `NEUROVA_CORS_ORIGINS` 之后，装配进中间件的与管理面板显示的是同一份。

        这条就是收口要顺带修的行为分叉：三级优先只写在中间件里，而 `GET /settings/cors`
        只看文件与自带兜底 ⇒ 管理员照面板改的是一份**没在生效**的清单。
        """
        from neurova.api.endpoints import settings as ST

        monkeypatch.setenv("NEUROVA_CORS_ORIGINS", "http://env-one.test, http://env-two.test")
        monkeypatch.setattr(_policy(), "configFile",
                            lambda: tmp_path / "absent" / "cors.json")

        applied = _assembledCors(monkeypatch)["allow_origins"]
        shown = ST._load_cors_config()["origins"]
        assert set(shown) == set(applied) == {"http://env-one.test", "http://env-two.test"}, (
            f"面板显示 {shown} 与装配生效 {applied} 不一致——显示≠生效就是双源的老病")

    def testWithoutEnvBothSidesUseTheFileThenTheSameDefaults(self, monkeypatch, tmp_path):
        """无 env 时：先文件后兜底，且面板与装配**逐键**相等（四项口径一起比）。"""
        from neurova.api.endpoints import settings as ST

        policy = _policy()
        monkeypatch.delenv("NEUROVA_CORS_ORIGINS", raising=False)
        cfg = tmp_path / "cors.json"
        cfg.write_text(json.dumps({"origins": ["http://from-file.test"]}), encoding="utf-8")

        expectedFile = {"origins": ["http://from-file.test"], "allow_credentials": True,
                        "allow_methods": list(policy.ALLOW_METHODS),
                        "allow_headers": list(policy.ALLOW_HEADERS)}
        assembled = _assembledCors(monkeypatch, cfg)
        assert ST._load_cors_config(config_file=str(cfg)) == expectedFile
        assert {k: assembled[k] for k in ("allow_origins", "allow_credentials",
                                         "allow_methods", "allow_headers")} == {
            "allow_origins": expectedFile["origins"],
            "allow_credentials": True,
            "allow_methods": expectedFile["allow_methods"],
            "allow_headers": expectedFile["allow_headers"]}, (
            "装配实参与面板不同键值——两处还在各读各的")

        missing = tmp_path / "nope" / "cors.json"
        assert (_assembledCors(monkeypatch, missing)["allow_origins"]
                == ST._load_cors_config(config_file=str(missing))["origins"]
                == list(policy.DEFAULT_ORIGINS))

    def testCredentialsSwitchInTheFileReachesTheMiddleware(self, monkeypatch, tmp_path):
        """面板可编辑的 allow_credentials 必须真的进装配实参。

        建档时装配处把它写死 True，面板读的却是文件里那个键——管理员改成 False 存下来，
        生效值仍是 True：这就是 §2 说的"写出无人读的字段"。收口后开关与其余三项同出一条口径。
        """
        policy = _policy()
        monkeypatch.delenv("NEUROVA_CORS_ORIGINS", raising=False)
        cfg = tmp_path / "cors.json"
        cfg.write_text(json.dumps({"origins": ["http://cred.test"],
                                   "allow_credentials": False}), encoding="utf-8")

        assert _assembledCors(monkeypatch, cfg)["allow_credentials"] is False
        assert _assembledCors(monkeypatch, tmp_path / "absent.json")["allow_credentials"] is (
            policy.ALLOW_CREDENTIALS_DEFAULT), "缺省档不得翻转凭证开关——打包态一直是 True"

    def testEnvIsReadThroughTheConfigAccessor(self, monkeypatch, tmp_path):
        """env 走 `neurova.core.config.get` 这一个入口读，不直取 `os.environ`。

        本仓运行时配置的入口是 core.config（含 .env 装载与用户覆盖层）；咽喉若绕过它，
        写在 .env 里的 `NEUROVA_CORS_ORIGINS` 就不生效，而既有守卫 `test_cors_tauri_origins`
        patch 的正是这个入口——绕过它，那条守卫就白配了。
        """
        import neurova.core.config as core_config

        policy = _policy()
        monkeypatch.delenv("NEUROVA_CORS_ORIGINS", raising=False)
        monkeypatch.setattr(
            core_config, "get",
            lambda key, default="": ("http://via-accessor.test"
                                     if key == policy.ORIGINS_ENV_KEY else default))

        origins = policy.effectiveOrigins(str(tmp_path / "absent" / "cors.json"))
        assert origins == ["http://via-accessor.test"], (
            f"读到 {origins}——env 没经 config.get 入口，配置层的白名单进不来")

    def testEnvOutranksTheConfigFile(self, monkeypatch, tmp_path):
        """三级优先的**次序**也得钉住：env 压过配置文件。

        两侧同值（前两格）只保证"面板=中间件"，保证不了它们一起读错——把次序翻成
        "文件压过 env"，两侧照样一致，但部署方用 env 收紧白名单的手感当场失效
        （`config/cors.json` 是打进安装包的，谁在机器上设了 env 却说不上话）。
        """
        policy = _policy()
        cfg = tmp_path / "cors.json"
        cfg.write_text(json.dumps({"origins": ["http://from-file.test"]}), encoding="utf-8")
        monkeypatch.setenv("NEUROVA_CORS_ORIGINS", "http://env-wins.test")

        assert policy.effectiveOrigins(str(cfg)) == ["http://env-wins.test"]


class TestConsolidationChangesNothing:
    def testAllowSetsAreByteIdenticalToWhatTheRepoConfigShips(self):
        """收口不是重编一份：三项都必须与仓内 `config/cors.json` 现读的生效值逐字相等。

        这条防的是"顺手把某个端口/头去掉"——那种收紧会当场把桌面壳或前端打挂，
        而单源判据本身看不出来。
        """
        policy = _policy()
        shipped = json.loads(REPO_CORS_CONFIG.read_text(encoding="utf-8"))

        assert list(policy.ALLOW_METHODS) == shipped["allow_methods"], "methods 与仓内配置不等值"
        assert list(policy.ALLOW_HEADERS) == shipped["allow_headers"], "headers 与仓内配置不等值"
        assert set(policy.DEFAULT_ORIGINS) == set(shipped["origins"]), (
            "默认 origins 与仓内配置不逐字等值——桌面壳 origin 少一条就是打包产物打不通")
        assert pathlib.Path(policy.configFile()).name == "cors.json"

    def testMiddlewareAndEndpointReadTheSameObject(self):
        """装配点复核：中间件实参与管理端响应都得从单源取，不再各留一份字面量。"""
        import inspect

        from neurova.api import middleware as MW
        from neurova.api.endpoints import settings as ST

        src = inspect.getsource(MW.setup_middleware)
        assert "cors_policy" in src, (
            "setup_middleware 还在自带 methods/headers/credentials——单源没接上")
        assert not any(TAURI_PAIR <= g or METHOD_MARKERS <= g for g in _literalGroups(src)), (
            "setup_middleware 的实参里还写着一整套清单——装配处自己那份会盖住单源的改动")
        load_src = inspect.getsource(ST._load_cors_config)
        assert "cors_policy.effectiveConfig" in load_src, (
            "管理端没转发到单源，面板与实际生效仍会分叉")
        # GET 的响应构造里不许再出现任何整套清单（`config.get(k, [ ... ])` 那种自带兜底）
        for fn in (ST.get_cors_config, ST.update_cors_config):
            groups = _literalGroups(inspect.getsource(fn))
            assert not any(TAURI_PAIR <= g or METHOD_MARKERS <= g for g in groups), (
                f"{fn.__name__} 里还写着一整份兜底清单——它会盖住单源的值，"
                "且单源改了这里不改，就是第二本账")
