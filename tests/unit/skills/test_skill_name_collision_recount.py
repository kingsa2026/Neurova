"""006 残留 · 同名冲突计数必须**可复算**（把"我记得有 8 条"变成可查读数）。

票据 006 验收原文：「name 冲突告警在现网存量上可复算（预期计数 = 8，来自上面那份
manifest）；硬拒未引入、存量装配不炸。」

前一轮落了 `scripts/diagnostics/skill_name_collisions.py`，但**计数口径**没有任何用例
钉住——脚本与注册表两侧各有一套逻辑，谁改了口径都无人发现。本文件把口径钉死：

- **计数 = 同一 name 下身份不同的额外条目数**（先到者留得住，其余每个记 1 次覆盖）；
- 在**审计记载的存量形状**（8 条不同 `synth_*` 共用 name=`general_tool`）上复算 ⇒ 7；
- **注册表侧同口径**：逐条 register 同样 8 条，`registered_collision_count()` 必须是 7，
  与脚本读数一致（两侧同口径，不是两份各算各的）。
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "diagnostics" / "skill_name_collisions.py"
COLLIDING_NAME = "general_tool"
DUPLICATE_IDENTITIES = 8


def _load_script():
    spec = importlib.util.spec_from_file_location("_collisions_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    import sys

    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _legacy_manifest() -> dict:
    """审计记载的存量形状：8 条不同身份共用同一个 name。"""
    return {
        f"synth_{index:02d}": {
            "id": f"synth_{index:02d}",
            "name": COLLIDING_NAME,
            "description": f"历史生成器遗留 #{index}",
            "config": {"tool_sequence": [{"tool": "general_tool", "params": {}}]},
        }
        for index in range(DUPLICATE_IDENTITIES)
    }


def _synth_skill(index: int):
    from neurova.skill_system import Skill

    skill = Skill(name=COLLIDING_NAME, description=f"历史生成器遗留 #{index}")
    skill.skill_id = f"synth_{index:02d}"
    skill.config = {"skill_id": f"synth_{index:02d}"}
    return skill


class TestRecountScript:
    def test_counts_extra_identities_not_rows(self, tmp_path):
        manifest = tmp_path / "manifest.json"
        manifest.write_text(json.dumps(_legacy_manifest(), ensure_ascii=False),
                            encoding="utf-8")
        report = _load_script().recount_name_collisions(manifest)
        assert report["collision_count"] == DUPLICATE_IDENTITIES - 1, (
            f"计数口径不是「不同身份的额外条目数」：{report}"
        )
        assert report["collisions"][0]["name"] == COLLIDING_NAME

    def test_single_identity_under_one_name_is_not_a_collision(self, tmp_path):
        manifest = tmp_path / "manifest.json"
        manifest.write_text(json.dumps({"synth_00": {
            "id": "synth_00", "name": COLLIDING_NAME,
            "config": {"tool_sequence": []}}}, ensure_ascii=False), encoding="utf-8")
        assert _load_script().recount_name_collisions(manifest)["collision_count"] == 0


class TestRegistryAgreesWithTheScript:
    def test_registry_and_script_use_the_same_denominator(self):
        """两侧必须同口径：同样 8 条 ⇒ 脚本 7、注册表读数也是 7。"""
        from neurova.skill_system import SkillRegistry

        registry = SkillRegistry()
        registry._name_collision_count = 0
        for index in range(DUPLICATE_IDENTITIES):
            registry.register(_synth_skill(index))
        assert registry._name_collision_count == DUPLICATE_IDENTITIES - 1, (
            f"注册表侧口径与脚本不一致：{registry._name_collision_count}"
        )

    def test_recount_reads_the_registry_without_building_it(self):
        """观测面读数口只读已创建的注册表（抓指标不造对象）。"""
        from neurova import skill_system

        standalone = skill_system.__getattr__("registered_collision_count")
        module = __import__("sys").modules["neurova.skill_system_module_standalone"]
        original = module._skill_registry_singleton
        module._skill_registry_singleton = None
        try:
            assert standalone() == 0
        finally:
            module._skill_registry_singleton = original
