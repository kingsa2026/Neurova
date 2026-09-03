"""s9 TDD: 批量修复 20 处 model_dump bug (pydantic v1.10 兼容)

背景:
- 项目 pydantic 实际版本 1.10.26 (v1), 没有 model_dump() 方法, 只有 dict()
- 但代码库 20 处调用 body.model_dump(...) / r.model_dump() → 全部 AttributeError
- 这些是预存 bug, 端点从未被调用过所以未暴露
- s6 已修 1 处 (skill_pool_api.py:190); s9 批量修剩余 19 处

修复策略:
1. 创建 helper 函数 neurova.api.endpoints._pydantic_compat.safe_model_dump(obj, **kwargs)
   - v1: obj.dict(**kwargs)
   - v2: obj.model_dump(**kwargs)
2. 所有 19 处 .model_dump(...) 改为 safe_model_dump(obj, ...)
3. types.py 的 2 处 self.model_dump() 改为 self.dict() (因在 llm 包, 不依赖 api)

契约:
1. helper 函数存在且双兼容
2. 12 个端点文件中无 .model_dump 直接调用 (除 helper 内部)
3. types.py 的 to_dict 在 v1 下能工作
"""

import inspect

import pytest


# ─── 契约 1: helper 存在且双兼容 ───


def test_safe_model_dump_helper_exists():
    """s9.1: neurova.api.endpoints._pydantic_compat.safe_model_dump 存在"""
    from neurova.api.endpoints._pydantic_compat import safe_model_dump

    assert callable(safe_model_dump), "safe_model_dump 必须可调用"


def test_safe_model_dump_works_with_pydantic_v1():
    """s9.2: 在 pydantic v1.10 下, safe_model_dump 应走 .dict()"""
    from neurova.api.endpoints._pydantic_compat import safe_model_dump
    from pydantic import BaseModel

    class Foo(BaseModel):
        a: int = 1
        b: str = "x"

    # v1: dict() 存在
    result = safe_model_dump(Foo())
    assert result == {"a": 1, "b": "x"}, f"safe_model_dump v1 路径失败, result={result}"


def test_safe_model_dump_passes_kwargs():
    """s9.3: safe_model_dump 透传 exclude_none 等 kwargs"""
    from neurova.api.endpoints._pydantic_compat import safe_model_dump
    from pydantic import BaseModel

    class Foo(BaseModel):
        a: int = 1
        b: str = None  # type: ignore

    result = safe_model_dump(Foo(), exclude_none=True)
    assert "b" not in result, f"exclude_none=True 应排除 None 字段, result={result}"


def test_safe_model_dump_v2_compatible():
    """s9.4: 模拟 v2 环境 (model_dump 存在), 应优先用 model_dump"""
    from neurova.api.endpoints._pydantic_compat import safe_model_dump

    class FakeV2Model:
        """模拟 pydantic v2 BaseModel"""

        def model_dump(self, **kwargs):
            return {"_v2_path": True, "kwargs": kwargs}

        def dict(self, **kwargs):
            return {"_v1_path": True}

    obj = FakeV2Model()
    result = safe_model_dump(obj)
    assert result.get("_v2_path") is True, (
        f"v2 环境下应优先 model_dump, 实际走 v1: {result}"
    )


# ─── 契约 2: 12 个端点文件无 .model_dump 直接调用 (除 helper) ───


@pytest.mark.parametrize(
    "endpoint_module",
    [
        "neurova.api.endpoints.channel_config",
        "neurova.api.endpoints.enhanced_users_api",
        "neurova.api.endpoints.rules_api",
        "neurova.api.endpoints.shared_config",
        "neurova.api.endpoints.skill_market",
        "neurova.api.endpoints.skill_pool_api",
        "neurova.api.endpoints.skill_version_api",
        "neurova.api.endpoints.tasks_api",
        "neurova.api.endpoints.user_group_api",
        "neurova.api.endpoints.webhooks",
    ],
)
def test_endpoint_module_does_not_call_model_dump_directly(endpoint_module):
    """s9.5: 端点模块源码不应再含 .model_dump( 调用 (应改用 safe_model_dump)"""
    import importlib

    mod = importlib.import_module(endpoint_module)
    src = inspect.getsource(mod)
    # 允许 helper 内部用 .model_dump, 但不允许业务端点直接用
    # 排除: import 行 / 注释 / 字符串
    forbidden = ".model_dump("
    lines = [
        line
        for line in src.split("\n")
        if forbidden in line
        and not line.strip().startswith("#")
        and not line.strip().startswith('"')
        and not "def safe_model_dump" in line
        and "import" not in line
    ]
    assert not lines, (
        f"{endpoint_module} 仍直接调用 .model_dump(): {lines}. "
        "应改用 from neurova.api.endpoints._pydantic_compat import safe_model_dump"
    )


# ─── 契约 3: types.py 的 to_dict 在 v1 下能工作 ───


def test_model_info_to_dict_works_in_pydantic_v1():
    """s9.6: ModelInfo.to_dict() 在 v1 下应工作 (返回 dict)"""
    from neurova.llm.providers.types import ModelInfo

    m = ModelInfo(id="gpt-4", name="GPT-4")
    result = m.to_dict()
    assert isinstance(result, dict), f"to_dict 应返回 dict, 实际 {type(result)}"
    assert result["id"] == "gpt-4"


def test_provider_info_to_dict_works_in_pydantic_v1():
    """s9.7: ProviderInfo.to_dict() 在 v1 下应工作"""
    from neurova.llm.providers.types import ProviderInfo

    p = ProviderInfo(id="openai", name="OpenAI")
    result = p.to_dict()
    assert isinstance(result, dict)
    assert result["id"] == "openai"
