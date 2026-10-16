"""管理面 PUT 的字段白名单不得落后于配置单源（同族病两枚命中点，一档收口）。

病形：`GET` 直接把生效值全量带出，`PUT` 却只认其中几个键；其余键的写入被
pydantic（不在模型里 ⇒ 丢）或被持久层的 `if key in DEFAULTS`（在模型里但不在单源 ⇒ 丢）
静默吃掉。管理员看到 200、文件照写别的键、读数照旧——**比报错更坏，因为没人知道没生效**。
本档不按"看起来合理"断言，而是两面都判：
① 覆盖性——单源里每个键，PUT 模型必须收得到；
② 可达性——真发一次 PUT，GET 必须读回那个值；
③ 边界同源性——面板的合法域必须等于 `get_effective_limits` 夹紧用的同一批常量，
   两边各写一份数字，改一处就悄悄漂移；
④ 未知键不得静默丢弃（与②同一根因的另一半）。

裁定出处：用户裁"补齐八键 + clamp + 同形守卫"（2026-10-16）。
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

import neurova.security.agent_limits_settings as limits_mod
from neurova.api.endpoints import governance as gov_module
from tests.auth_headers import overrideIdentity

BASE = "/api/v1/governance"

#: 键 → 夹紧用的常量对（**取模块对象本身，不在这里重打数字**——重打就是把第三份定义
#: 写进判据，单源改了这里不会红，而这正是本档要防的漂移）。
#: `goal_verification_enabled` 是布尔开关，无数值域，单独一格判可达。
#: `goal_round_budget` 的 `None` 是"跟随 max_loop_rounds"哨兵，合法域与 max_loop_rounds 同档。
BOUND_TABLE = {
    "token_budget": (limits_mod.MIN_TOKEN_BUDGET, limits_mod.MAX_TOKEN_BUDGET),
    "max_loop_rounds": (limits_mod.MIN_ROUNDS, limits_mod.MAX_ROUNDS),
    "goal_max_continuations": (
        limits_mod.MIN_GOAL_CONTINUATIONS, limits_mod.MAX_GOAL_CONTINUATIONS),
    "goal_round_budget": (
        limits_mod.MIN_GOAL_ROUND_BUDGET, limits_mod.MAX_GOAL_ROUND_BUDGET),
    "max_subagent_depth": (
        limits_mod.MIN_SUBAGENT_DEPTH, limits_mod.MAX_SUBAGENT_DEPTH_LIMIT),
    "max_parallel_tools": (
        limits_mod.MIN_PARALLEL_TOOLS, limits_mod.MAX_PARALLEL_TOOLS),
    "doom_loop_window_size": (
        limits_mod.MIN_DOOM_LOOP_WINDOW, limits_mod.MAX_DOOM_LOOP_WINDOW),
    "doom_loop_max_interrupts": (
        limits_mod.MIN_DOOM_LOOP_INTERRUPTS, limits_mod.MAX_DOOM_LOOP_INTERRUPTS),
    "doom_loop_similarity_threshold": (
        limits_mod.MIN_DOOM_LOOP_SIMILARITY, limits_mod.MAX_DOOM_LOOP_SIMILARITY),
}


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("NEUROVA_AGENT_LIMITS_SETTINGS", str(tmp_path / "limits.json"))
    monkeypatch.setenv("NEUROVA_EVOLUTION_SETTINGS", str(tmp_path / "evolution.json"))
    app = FastAPI()
    app.include_router(gov_module.router, prefix=BASE)
    overrideIdentity(app, {"user_id": "admin1", "role": "admin"})
    return TestClient(app)


def _fieldBounds(model, name) -> tuple:
    """从 pydantic 模型取某字段声明的 ge/le（取不到回 None，由断言判"该有却没有"）。

    边界在 pydantic v2 里以 `annotated_types.Ge/Le` 元数据挂在 `FieldInfo.metadata` 上，
    所以按属性扫而不是按类型名判——类型名是 pydantic 的实现细节，会随版本漂。
    """
    ge = le = None
    for meta in model.model_fields[name].metadata:
        ge = getattr(meta, "ge", ge)
        le = getattr(meta, "le", le)
    return ge, le


class TestPutWhitelistCoversTheSingleSource:
    def testAgentLimitsPutModelCoversEveryConfigKey(self):
        """`DEFAULTS` 是"这台 agent 有哪些可调旋钮"的唯一出处；PUT 模型少一键就是面板空转。"""
        missing = set(limits_mod.DEFAULTS) - set(gov_module.AgentLimitsUpdate.model_fields)
        assert not missing, (
            f"PUT 白名单落后于配置单源，这些键写了也不生效：{sorted(missing)}")

    def testEvolutionSettingsPutModelCoversEveryConfigField(self):
        """同一族病在进化侧的命中点（原在真臂判据档，按"一族一个家"移来此处）。"""
        from dataclasses import fields as dataclassFields

        from neurova.api.endpoints import text_evolution_api as text_api
        from neurova.evolution.evolution_settings import EvolutionSettings

        missing = ({f.name for f in dataclassFields(EvolutionSettings)}
                   - set(text_api.SettingsPatch.model_fields))
        assert not missing, f"PUT 白名单缺这些配置键：{sorted(missing)}"

    @pytest.mark.parametrize("key", sorted(BOUND_TABLE))
    def testNumericBoundsComeFromTheClampConstants(self, key):
        """面板合法域必须等于夹紧区间——两边各写一份数字，改一处就悄悄漂移。"""
        model = gov_module.AgentLimitsUpdate
        assert key in model.model_fields, f"{key} 不在 PUT 模型里，无从谈边界"
        assert _fieldBounds(model, key) == BOUND_TABLE[key], (
            f"{key} 的面板边界应为夹紧常量 {BOUND_TABLE[key]}，"
            f"现值 {_fieldBounds(model, key)}")

    def testUnknownKeyIsRejectedNotSilentlyDropped(self, client):
        """打错的键名不得"200 但没生效"：与落后白名单同一根因的另一半。

        混合一发（一个合法键 + 一个错键）才判得出这件事：只发错键时今天的空 payload
        也会回 422，那是"没有效字段"而不是"拒未知键"，两回事会被读成同一条绿。
        """
        resp = client.put(f"{BASE}/agent-limits",
                          json={"token_budget": 200000, "token_budget_": 1})
        assert resp.status_code == 422, resp.text


class TestEveryKeyIsActuallyWritable:
    def testPutWritesAllKeysAndGetReadsThemBack(self, client):
        # 取合法域中点：整型域用 `int()` 落回整（`//` 对浮点域会向下取到 0，
        # 相似度那一档的中点 0.75 会被它压成 0.0 而撞自己的下界——这不是配置坏，
        # 是我这份取值表达式坏）
        payload = {key: type(lo)((lo + hi) / 2) for key, (lo, hi) in BOUND_TABLE.items()}
        payload["goal_verification_enabled"] = True
        resp = client.put(f"{BASE}/agent-limits", json=payload)
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        for key, value in payload.items():
            assert data[key] == value, (key, data[key], value)

    def testGoalVerificationSwitchIsReachableFromTheAdminFace(self, client):
        """成本闸必须两头可达：只能开不能关，等于给运营留了一半假旋钮。"""
        assert client.put(f"{BASE}/agent-limits",
                          json={"goal_verification_enabled": False}).status_code == 200
        assert client.get(f"{BASE}/agent-limits").json()["data"][
            "goal_verification_enabled"] is False

    def testOutOfRangeValueIsRejectedByTheSameBound(self, client):
        _, hi = BOUND_TABLE["doom_loop_window_size"]
        resp = client.put(f"{BASE}/agent-limits",
                          json={"doom_loop_window_size": hi + 1})
        assert resp.status_code == 422, resp.text
        assert client.get(f"{BASE}/agent-limits").json()["data"][
            "doom_loop_window_size"] == limits_mod.DEFAULTS["doom_loop_window_size"]

    def testFollowSentinelIsNotUnpinnableFromThePanel(self, client):
        """如实钉一条边界：`goal_round_budget=None` 是"跟随 max_loop_rounds"的哨兵，
        而 PUT 的 None 过滤（`if v is not None`）让"钉住之后放回跟随"这条路不存在。
        要做这条路得改持久层的 None 语义（那会连带影响其余键），不属本批；
        这一格钉的是**现状**，将来谁把它改成可清，必须同时改判这一格。"""
        assert client.put(f"{BASE}/agent-limits",
                          json={"goal_round_budget": 8}).status_code == 200
        client.put(f"{BASE}/agent-limits", json={"max_loop_rounds": 30})
        data = client.get(f"{BASE}/agent-limits").json()["data"]
        assert data["goal_round_budget"] == 8, data
        assert data["max_loop_rounds"] == 30, data


class TestNoSecondDefinitionOfTheWhitelist:
    def testEveryPutFieldExistsInTheSingleSource(self):
        """反向半区：模型里有而单源没有的键同样坏——`save_agent_limits` 会把它丢掉，
        面板看起来能设，磁盘上永远不落（与少键同形，方向相反）。"""
        extra = set(gov_module.AgentLimitsUpdate.model_fields) - set(limits_mod.DEFAULTS)
        assert not extra, f"PUT 模型里有单源不认的键：{sorted(extra)}"

    def testSettingsPatchAndEvolutionSettingsHaveNoStrayFields(self):
        from dataclasses import fields as dataclassFields

        from neurova.api.endpoints import text_evolution_api as text_api
        from neurova.evolution.evolution_settings import EvolutionSettings

        names = {f.name for f in dataclassFields(EvolutionSettings)}
        extra = set(text_api.SettingsPatch.model_fields) - names
        assert not extra, f"进化设置 PUT 模型里有单源不认的键：{sorted(extra)}"
