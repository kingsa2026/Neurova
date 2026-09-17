"""Frozen pre-split API contracts and live facade patch seams (offline only)."""
import ast
import importlib
import inspect
import json
import pickle
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from neurova.collaboration.neurflow import external_api as api

SNAPSHOT = json.loads(Path(__file__).with_name("external_api_contract_snapshot.json").read_text(encoding="utf-8"))
LEAVES = {
    "image": ["ImageGenClient"], "video": ["VideoGenClient"],
    "amazon_sp": ["AmazonSPAPIClient"], "amazon_ads": ["AmazonAdsClient"],
    "taobao": ["TaobaoTopClient", "XianyuClient"], "jd": ["JdOpenClient"],
    "pdd": ["PddOpenClient"], "douyin": ["DouyinEcomClient"],
    "tiktok": ["TikTokShopClient"], "alibaba1688": ["Alibaba1688Client"],
    "xiaohongshu": ["XiaohongshuClient"],
}


def test_old_exports_signatures_and_inheritance():
    for name in SNAPSHOT["exports"]:
        assert hasattr(api, name), name
    for name, signature in SNAPSHOT["functions"].items():
        assert str(inspect.signature(getattr(api, name))) == signature
    for name, expected in SNAPSHOT["classes"].items():
        cls = getattr(api, name)
        assert [base.__name__ for base in cls.__bases__] == expected["bases"]
        assert cls.__module__ == api.__name__
        assert pickle.loads(pickle.dumps(cls)) is cls
        methods = {key: str(inspect.signature(value.__func__ if isinstance(value, (staticmethod, classmethod)) else value))
                   for key, value in vars(cls).items()
                   if inspect.isfunction(value) or isinstance(value, (staticmethod, classmethod))}
        assert methods == expected["methods"]
        for key in methods:
            assert getattr(cls, key).__module__ == api.__name__


@pytest.mark.parametrize("leaf,names", LEAVES.items())
def test_leaf_structure_identity_and_no_old_helper_bindings(leaf, names):
    directory = Path(api.__file__).with_name("external_clients")
    assert (directory / f"{leaf}.py").is_file()
    assert (directory / "__init__.py").read_text(encoding="utf-8") == ""
    module = importlib.import_module(f"{api.__package__}.external_clients.{leaf}")
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    assert [n.name for n in tree.body if isinstance(n, ast.ClassDef)] == names
    for name in names:
        cls = getattr(module, name)
        assert cls is getattr(api, name)
        assert pickle.loads(pickle.dumps(cls())) .__class__ is cls
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.module != "external_api"
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {"exec", "globals", "eval"}
    assert not any(name.startswith("get_") or name.startswith("reset_") or name.endswith("_instance") for name in vars(module))


@pytest.mark.parametrize("leaf,names", LEAVES.items())
def test_fresh_process_import_order(leaf, names):
    code = (
        "import importlib\n"
        f"leaf = importlib.import_module({api.__package__ + '.external_clients.' + leaf!r})\n"
        f"facade = importlib.import_module({api.__name__!r})\n"
        f"for name in {names!r}:\n"
        "    assert getattr(leaf, name) is getattr(facade, name)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[3],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.asyncio
async def test_patch_facade_after_import_hits_actual_leaf_http(monkeypatch):
    client = api.VideoGenClient()
    post = AsyncMock(return_value={"task_id": "offline-task"})
    get = AsyncMock(return_value={"status": "completed", "video_url": "https://offline.invalid/video"})
    monkeypatch.setattr(api, "_http_post", post)
    monkeypatch.setattr(api, "_http_get", get)
    monkeypatch.setattr(api, "get_secret_store", lambda: pytest.fail("must not read credentials"))
    result = await client.generate("kling", "test", api_key="offline", base_url="https://offline.invalid")
    assert result["status"] == "success"
    assert result["output"]["video_url"] == "https://offline.invalid/video"
    post.assert_awaited_once()
    get.assert_awaited_once()


@pytest.mark.parametrize("name,reset,state,key", [
    ("image_gen", "image_gen", "_image_gen_instance", None),
    ("video_gen", "video_gen", "_video_gen_instance", None),
    ("amazon_sp", "amazon_sp", "_amazon_sp_instance", None),
    ("amazon_ads", "amazon_ads", "_amazon_ads_instance", None),
    ("commerce_platform", "commerce_platform", "_commerce_instance", None),
    ("publish_platform", "publish_platform", "_publish_instance", None),
    *[(name, "cn_platforms", "_cn_client_instances", key) for name, key in [
        ("taobao_top", "taobao"), ("jd_open", "jd"), ("pdd_open", "pdd"),
        ("douyin_ecom", "douyin"), ("tiktok_shop", "tiktok"), ("alibaba1688", "ali1688"),
        ("xiaohongshu", "xiaohongshu"), ("xianyu", "xianyu")]],
])
def test_single_factory_state_and_reset(monkeypatch, name, reset, state, key):
    monkeypatch.setattr(api, state, {} if key else None)
    factory = getattr(api, f"get_{name}_client")
    resetter = api.reset_cn_platform_clients if key else getattr(api, f"reset_{reset}_client")
    first = factory()
    assert first is factory()
    assert first is (getattr(api, state)[key] if key else getattr(api, state))
    resetter()
    assert factory() is not first
