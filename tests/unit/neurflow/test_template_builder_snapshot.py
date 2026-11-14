# -*- coding: utf-8 -*-
"""模板重构快照对照测试（审计 P2-28：模板构建器抽取的行为保持证明）。

fixture（``template_builder_snapshot.json``）是重构前从 8 个模板的
``_create_nodes`` / ``_create_edges`` / ``_create_variables`` 抓取的原始输出。
本测试把当前模板产出与 fixture 全量对照：dataclass → dict 后按 JSON 文本
严格比较，列表顺序与嵌套字典键序都参与判定——改走公共构建器后必须逐字节一致。
"""
import dataclasses
import json
from pathlib import Path

import pytest

from neurova.collaboration.neurflow.templates import (
    data_analysis,
    document,
    ecommerce,
    media,
    programming,
    short_drama,
    web_maintenance,
    writing,
)

FIXTURE_PATH = Path(__file__).parent / "template_builder_snapshot.json"

MODULES = {
    "data_analysis": data_analysis,
    "document": document,
    "ecommerce": ecommerce,
    "media": media,
    "programming": programming,
    "short_drama": short_drama,
    "web_maintenance": web_maintenance,
    "writing": writing,
}


def _serialize(objs) -> str:
    """dataclass 列表 → 紧凑 JSON 文本（保留列表顺序与字典键插入序）"""
    return json.dumps([dataclasses.asdict(o) for o in objs], ensure_ascii=False)


@pytest.fixture(scope="module")
def snapshot():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize("key", sorted(MODULES))
class TestTemplateSnapshot:
    def test_fixture_covers_template(self, snapshot, key):
        """fixture 必须覆盖全部 8 个模板"""
        assert key in snapshot

    def test_nodes_match_pre_refactor_output(self, snapshot, key):
        tpl = getattr(MODULES[key], f"get_{key}_template")()
        assert _serialize(tpl.nodes) == json.dumps(
            snapshot[key]["nodes"], ensure_ascii=False
        ), f"{key} 节点与重构前快照不一致"

    def test_edges_match_pre_refactor_output(self, snapshot, key):
        tpl = getattr(MODULES[key], f"get_{key}_template")()
        assert _serialize(tpl.edges) == json.dumps(
            snapshot[key]["edges"], ensure_ascii=False
        ), f"{key} 边与重构前快照不一致"

    def test_variables_match_pre_refactor_output(self, snapshot, key):
        tpl = getattr(MODULES[key], f"get_{key}_template")()
        expected = snapshot[key].get("variables")
        if expected is None:
            # 无变量模板（short_drama）：保持空列表
            assert tpl.variables == []
            return
        assert _serialize(tpl.variables) == json.dumps(
            expected, ensure_ascii=False
        ), f"{key} 变量与重构前快照不一致"
