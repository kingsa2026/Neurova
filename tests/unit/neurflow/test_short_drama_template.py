# -*- coding: utf-8 -*-
"""批次4：内置短剧一键成片模板（AIGC 创作 Tab 的数据源）。"""
from __future__ import annotations

import pytest

from neurova.collaboration.neurflow.dag import get_dag_validator
from neurova.collaboration.neurflow.templates.short_drama import (
    SHORT_DRAMA_TEMPLATE_ID,
    get_short_drama_template,
)

pytestmark = pytest.mark.timeout(60)


class TestShortDramaTemplate:
    def test_dag_valid_and_shape(self):
        tpl = get_short_drama_template()
        assert tpl.id == SHORT_DRAMA_TEMPLATE_ID
        assert tpl.template is True and tpl.public is True
        result = get_dag_validator().validate(tpl.nodes, tpl.edges)
        assert result.is_valid, str(result.errors)

    def test_start_declares_inputs_for_workflow_as_tool(self):
        tpl = get_short_drama_template()
        start = next(n for n in tpl.nodes if n.type == "builtin:start")
        schema = start.config["inputs_schema"]
        assert set(["theme", "genre", "style", "aspect_ratio", "image_provider"]) <= set(schema)
        assert schema["theme"]["required"] is True

    def test_pipeline_nodes_present(self):
        types = {n.type for n in get_short_drama_template().nodes}
        assert {
            "builtin:short-drama-script",
            "builtin:storyboard",
            "builtin:scene-gen",
            "builtin:voice-over",
            "builtin:video-compose",
        } <= types


class TestSeedIdempotent:
    def test_seed_creates_once_skips_twice(self, tmp_path):
        from neurova.collaboration.neurflow.storage import NeurflowStorage
        from neurova.collaboration.neurflow.templates import seed_short_drama_template

        storage = NeurflowStorage(db_path=str(tmp_path / "nf.db"))
        assert seed_short_drama_template(storage) is True
        assert seed_short_drama_template(storage) is False
        tpl = storage.get_workflow(SHORT_DRAMA_TEMPLATE_ID)
        assert tpl is not None and tpl.name == "AI 短剧一键成片"
