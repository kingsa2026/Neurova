"""工单 015 · 裸 env 收进治理设置 — 开关事实源与优先级口径。

收口对象：
- `NEUROVA_CRYSTALLIZATION_LLM_GATE`（结晶 LLM 裁决闸，默认开）
- `NEUROVA_SKILL_AUTO_RETIRE`（技能自动淘汰，默认关）

两者此前只有裸 env，生产无写入方，等于"定义了没人能拨"的幻影旋钮。收口后
必须与 `metacog_gate_enabled` 同口径：**env 显式 0 强制关 > env 显式 1 强制开 >
治理设置 > 内置默认**，且三个方向都要可测（只断一个方向等于没锁住优先级）。

治理设置面（GET/PUT /v1/governance/settings）必须能读到、也能改到这两个键——
否则"收进治理"只是把 env 换了个名字读。
"""

import json
import re
from pathlib import Path

import pytest

from neurova.security.governance_settings import DEFAULTS, resolve_flag

NEW_SWITCHES = ("crystallization_llm_gate_enabled", "skill_auto_retire_enabled")


@pytest.fixture(autouse=True)
def _no_stale_switch_env(monkeypatch):
    """裸 env 残留会把"默认/治理"两个方向读成同一个值，先清场。"""
    for var in ("NEUROVA_CRYSTALLIZATION_LLM_GATE", "NEUROVA_SKILL_AUTO_RETIRE"):
        monkeypatch.delenv(var, raising=False)


def _write_settings(tmp_path: Path, payload: dict) -> Path:
    p = tmp_path / "governance_settings.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


class TestSwitchesDeclaredInDefaults:
    """两个开关必须进 DEFAULTS —— 不在 DEFAULTS 的键读不到也写不进（load/save 只认已声明键）。"""

    @pytest.mark.parametrize("key", NEW_SWITCHES)
    def test_key_is_declared(self, key):
        assert key in DEFAULTS, f"{key} 未登记进 governance_settings.DEFAULTS"

    def test_defaults_match_today_production_behavior(self):
        """反向锁：收口不得改变现网默认（结晶闸默认开、自动淘汰默认关）。"""
        assert DEFAULTS["crystallization_llm_gate_enabled"] is True
        assert DEFAULTS["skill_auto_retire_enabled"] is False


class TestResolveFlagPriority:
    """优先级三个方向各自一条断言 —— 少一个方向就是没锁。"""

    def test_env_zero_forces_off_over_governance_true(self, tmp_path, monkeypatch):
        _write_settings(tmp_path, {"crystallization_llm_gate_enabled": True})
        monkeypatch.setenv("NEUROVA_CRYSTALLIZATION_LLM_GATE", "0")
        assert resolve_flag("crystallization_llm_gate_enabled", "NEUROVA_CRYSTALLIZATION_LLM_GATE") is False

    def test_env_one_forces_on_over_governance_false(self, tmp_path, monkeypatch):
        _write_settings(tmp_path, {"crystallization_llm_gate_enabled": False})
        monkeypatch.setenv("NEUROVA_CRYSTALLIZATION_LLM_GATE", "1")
        assert resolve_flag("crystallization_llm_gate_enabled", "NEUROVA_CRYSTALLIZATION_LLM_GATE") is True

    def test_governance_wins_over_default_when_env_absent(self, tmp_path, monkeypatch):
        """治理设置 False 而内置默认 True ⇒ 读成 False（env 未显式设置时设置面说话）。"""
        _write_settings(tmp_path, {"crystallization_llm_gate_enabled": False})
        assert resolve_flag("crystallization_llm_gate_enabled", "NEUROVA_CRYSTALLIZATION_LLM_GATE") is False

    def test_builtin_default_when_nothing_configured(self, tmp_path):
        """文件不存在 ⇒ 落 DEFAULTS（运营从未拨过旋钮时的现网行为）。"""
        assert resolve_flag("crystallization_llm_gate_enabled", "NEUROVA_CRYSTALLIZATION_LLM_GATE") is True
        assert resolve_flag("skill_auto_retire_enabled", "NEUROVA_SKILL_AUTO_RETIRE") is False

    def test_env_value_other_than_zero_or_one_is_not_explicit(self, tmp_path, monkeypatch):
        """env 存在但不是 0/1 ⇒ 不算"显式设置"，仍由治理面说话。

        与 metacog_gate_enabled 同口径：NEUROVA_METACOG_GATE=banana 不会误开门。
        """
        _write_settings(tmp_path, {"crystallization_llm_gate_enabled": False})
        monkeypatch.setenv("NEUROVA_CRYSTALLIZATION_LLM_GATE", "banana")
        assert resolve_flag("crystallization_llm_gate_enabled", "NEUROVA_CRYSTALLIZATION_LLM_GATE") is False

    def test_undeclared_key_raises_instead_of_silently_off(self):
        """未声明的键必须炸，不能被 .get() 兜成 False —— 那正是"幻影旋钮"的成因。"""
        with pytest.raises(KeyError):
            resolve_flag("no_such_switch_enabled", "NEUROVA_NO_SUCH_SWITCH")


class TestGovernanceSwitchSurfaceIsReadableAndWritable:
    """管理面可读可写：GET 暴露默认、PUT 能落盘 —— 只有 env 能改的开关不算收口。"""

    def _client(self, tmp_path):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        import neurova.api.endpoints.governance as gov
        from neurova.api.endpoints.governance import router

        app = FastAPI()
        app.include_router(router, prefix="/api/v1/governance")
        app.dependency_overrides[gov._governance_admin_dep] = lambda: {"id": 1}
        return TestClient(app)

    def test_get_exposes_both_switches(self, tmp_path):
        client = self._client(tmp_path)
        data = client.get("/api/v1/governance/settings").json()["data"]
        assert data["crystallization_llm_gate_enabled"] is True
        assert data["skill_auto_retire_enabled"] is False

    @pytest.mark.parametrize("key", NEW_SWITCHES)
    def test_put_persists_switch(self, tmp_path, key):
        client = self._client(tmp_path)
        settings_file = tmp_path / "governance_settings.json"
        resp = client.put("/api/v1/governance/settings", json={key: True})
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"][key] is True
        assert json.loads(settings_file.read_text(encoding="utf-8"))[key] is True

    def test_unlisted_env_var_names_are_gone_from_consumers(self):
        """两个裸 env 只能出现在 resolver 的声明处，消费方不得再自行读环境。

        留一处裸读就是第二个幻影旋钮：治理面写了值，消费方看不到。
        只匹配**读取形态**（docstring/注释里提及变量名不算违规，也不该被删掉）。
        扫描限定顶层 neurova/ —— src-tauri 下是构建期旧副本，会给出假命中。
        """
        backend = Path(__file__).resolve().parents[3] / "neurova"
        read_form = re.compile(
            r"""os\s*\.\s*(?:environ\s*\[|environ\.get\(|getenv\()\s*["']"""
            r"""(NEUROVA_CRYSTALLIZATION_LLM_GATE|NEUROVA_SKILL_AUTO_RETIRE)"""
        )
        offenders = []
        for py in backend.rglob("*.py"):
            if "__pycache__" in py.parts:
                continue
            rel = py.relative_to(backend).as_posix()
            if rel == "security/governance_settings.py":
                continue
            for lineno, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
                hit = read_form.search(line)
                if hit:
                    offenders.append(f"{rel}:{lineno}: {hit.group(1)}")
        assert offenders == [], "消费方仍在裸读 env:\n" + "\n".join(offenders)
