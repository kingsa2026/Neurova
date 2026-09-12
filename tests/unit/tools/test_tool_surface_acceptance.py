"""T6 工具面冻结验收集 — docs/Neurova_工具调用链升级计划_2026-09-13.md。

借 Needle environments"冻结验收套件"概念：把"用户话术→期望工具调用"沉淀为
JSON 夹具，每条记录钉三契约：
1. 工具名在 _BUILTIN_SCHEMAS 存在（dispatch/schema 对账，T1）；
2. 期望参数过 T2 validate_tool_args（宽容归一+校验零错误，等于 T2 上线自证）；
3. 期望参数本身是合法 JSON Schema 实例（Draft 2020-12）。

新工具上线带夹具条目即纳入回归；夹具是活契约，红=工具面或夹具漂移。
"""
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from neurova.builtin_tools import _BUILTIN_SCHEMAS
from neurova.security.tool_arg_validator import validate_tool_args

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "tool_surfaces"
_FIXTURES = sorted(_FIXTURE_DIR.glob("*.json"))


def test_fixtures_exist():
    assert _FIXTURES, "至少一份工具面验收夹具"


@pytest.mark.parametrize("path", _FIXTURES, ids=lambda p: p.name)
def test_surface_records_contract(path):
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc.get("records"), f"{path.name}: 夹具须有 records"
    for rec in doc["records"]:
        assert rec.get("query"), f"{path.name}: 记录缺 query"
        for call in rec.get("answers", []):
            name = call["name"]
            args = call.get("arguments", {})
            assert name in _BUILTIN_SCHEMAS, f"{path.name}: 工具 {name} 不在 schema 单源"
            entry = _BUILTIN_SCHEMAS[name]
            # 契约 2+3：先过 T2（宽容归一+校验），归一后参数必须是合法
            # schema 实例——端到端钉"校验器输出可直接进执行体"
            norm, errors = validate_tool_args(name, args)
            assert not errors, f"{path.name}/{name}: {errors}"
            Draft202012Validator(entry["parameters"]).validate(norm)
