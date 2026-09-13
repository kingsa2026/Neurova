# -*- coding: utf-8 -*-
"""批次0：generators facade 修通回归（渠道 B 栈 AIGC 复活）。

根因：neurova.llm.generators 包 __init__ 零导出（渠道 import 恒 ImportError），
manager.generate 用不存在的 GenType/GenerationConfig 名字（NameError 被吞），
渠道按想象契约构造 GenerationConfig（model/style/num_outputs/image_url/…字段不存在）、
读不存在的 result.urls/error_message。六个 BaseGenerator 实现体打的是文档判定
虚构端点。本测试锁定修复后的单一 facade 契约：渠道 → GeneratorManager →
ProtocolGenerator → protocols 实测协议矩阵 → runtime 落盘/账本。
"""
from __future__ import annotations

from pathlib import Path

import pytest


# ── 1. 包级导出（渠道 import 链冒烟）──────────────────────────────────────


def test_package_exports_facade_symbols():
    from neurova.llm.generators import (  # noqa: F401  当前恒 ImportError → RED
        BaseGenerator,
        GenerationConfig,
        GenerationResult,
        GeneratorManager,
        GeneratorType,
        get_generator_manager,
        get_image_generator,
        get_video_generator,
        reset_generator_manager,
    )


def test_task_ledger_still_reachable_via_package():
    from neurova.llm.generators import task_ledger as mod

    assert hasattr(mod, "GenerationTaskLedger")


# ── 2. GenerationConfig 实传字段（渠道三 mixin 零改动前提）─────────────────


def test_generation_config_accepts_channel_fields():
    from neurova.llm.generators import GenerationConfig, GeneratorType

    cfg = GenerationConfig(
        type=GeneratorType.TEXT_TO_IMAGE,
        model="wanx-v1",
        prompt="p",
        width=1024,
        height=1024,
        num_outputs=2,
        negative_prompt="bad hands",
        style="anime",
    )
    assert cfg.model == "wanx-v1"
    assert cfg.num_outputs == 2
    assert cfg.style == "anime"

    cfg2 = GenerationConfig(
        type=GeneratorType.IMAGE_TO_IMAGE,
        image_url="https://x/ref.png",
        strength=0.7,
        guidance_scale=7.5,
    )
    assert cfg2.image_url == "https://x/ref.png"
    assert cfg2.strength == 0.7

    cfg3 = GenerationConfig(
        type=GeneratorType.TEXT_TO_VIDEO,
        duration=5,
        fps=30,
    )
    cfg4 = GenerationConfig(
        type=GeneratorType.KEYFRAME_TO_VIDEO,
        start_image_url="a.png",
        end_image_url="b.png",
    )
    cfg5 = GenerationConfig(
        type=GeneratorType.VIDEO_TO_VIDEO, video_url="v.mp4"
    )
    assert cfg3.fps == 30
    assert cfg4.start_image_url == "a.png"
    assert cfg5.video_url == "v.mp4"


def test_generation_result_urls_and_error_message():
    from neurova.llm.generators import GenerationResult

    res = GenerationResult(success=True, output_path="/tmp/a.png", urls=["/tmp/a.png"])
    assert res.urls == ["/tmp/a.png"]
    assert res.error_message == ""

    err = GenerationResult(success=False, error="boom")
    assert err.error_message == "boom"
    assert err.urls == []


# ── 3. manager facade：get_generator 二参兼容 + NameError 根治 ──────────────


def test_get_generator_two_arg_compat():
    from neurova.llm.generators import get_generator_manager, reset_generator_manager

    reset_generator_manager()
    manager = get_generator_manager()
    gen = manager.get_generator("text_to_image", "wanx-v1")
    assert gen is not None
    gen2 = manager.get_generator("text_to_image")
    assert gen2 is not None


def test_manager_generate_no_swallowed_nameerror(monkeypatch):
    from neurova.llm.generators import manager as mgr_mod
    from neurova.llm.generators import runtime
    from neurova.llm.generators.protocols import ProtocolCredentials

    monkeypatch.setattr(
        runtime,
        "resolve_generation_creds",
        lambda *a, **k: ProtocolCredentials(api_key="k", base_url="https://x", model="m", protocol="openai_compat"),
        raising=False,
    )

    async def fake_generate_image(creds, prompt, **kw):
        return {"images": ["http://cdn/img.png"], "task_id": None, "raw": {}}

    from neurova.llm.generators import protocols as proto_mod

    monkeypatch.setattr(proto_mod, "generate_image", fake_generate_image)

    async def fake_persist(url_or_data, kind, task_id, index, out_dir=None):
        return f"/tmp/{task_id}_{index}.png"

    monkeypatch.setattr(runtime, "persist_media", fake_persist)

    mgr = mgr_mod.GeneratorManager()
    result = __import__("asyncio").run(
        mgr.generate("text_to_image", "一只猫", model="flux")
    )
    assert result.success, f"manager.generate 失败: {result.error}"


# ── 4. ProtocolGenerator 分发（图像/视频/诚实 unsupported）─────────────────


@pytest.fixture()
def runtime_patched(monkeypatch, tmp_path):
    from neurova.llm.generators import runtime
    from neurova.llm.generators.protocols import ProtocolCredentials

    calls = {}

    monkeypatch.setattr(
        runtime,
        "resolve_generation_creds",
        lambda protocol_hint, model, provider_id, api_key, base_url, default_base: (
            ProtocolCredentials(api_key="k", base_url="https://gw.test/v1",
                               model=model or "m", protocol=protocol_hint or "")
        ),
    )

    async def fake_persist(url_or_data, kind, task_id, index, out_dir=None):
        p = tmp_path / f"{task_id}_{index}"
        p.write_bytes(b"BYTES")
        calls["persist"] = (url_or_data, kind)
        return str(p)

    monkeypatch.setattr(runtime, "persist_media", fake_persist)
    return runtime, calls


def _run(coro):
    import asyncio

    return asyncio.run(coro)


def test_facade_image_success_localizes(runtime_patched):
    runtime, calls = runtime_patched
    from neurova.llm.generators import GenerationConfig, GeneratorType
    from neurova.llm.generators import protocols as proto_mod

    captured = {}

    async def fake_generate_image(creds, prompt, **kw):
        captured["kwargs"] = kw
        captured["model"] = creds.model
        return {"images": ["http://cdn/img1.png", "http://cdn/img2.png"], "task_id": None, "raw": {}}

    monkey_ok = getattr(proto_mod, "generate_image", None)
    proto_mod.generate_image = fake_generate_image
    try:
        gen = runtime.ProtocolGenerator(GeneratorType.TEXT_TO_IMAGE)
        cfg = GenerationConfig(
            type=GeneratorType.TEXT_TO_IMAGE, model="flux", prompt="p",
            width=768, height=1024, num_outputs=2,
        )
        result = _run(gen.generate(cfg))
    finally:
        proto_mod.generate_image = monkey_ok

    assert result.success, result.error
    assert captured["kwargs"]["size"] == "768x1024"
    assert captured["kwargs"]["n"] == 2
    assert captured["model"] == "flux"
    # 产物本地化：urls 必须是服务端本地路径（渠道 _download_url 本地分支可取 bytes）
    assert len(result.urls) == 2
    assert all(Path(u).is_file() for u in result.urls)
    assert result.metadata.get("remote_urls") == ["http://cdn/img1.png", "http://cdn/img2.png"]


def test_facade_i2i_passes_ref_image(runtime_patched):
    runtime, calls = runtime_patched
    from neurova.llm.generators import GenerationConfig, GeneratorType
    from neurova.llm.generators import protocols as proto_mod

    captured = {}

    async def fake_generate_image(creds, prompt, **kw):
        captured["refs"] = kw.get("ref_images")
        return {"images": ["http://cdn/x.png"], "task_id": None, "raw": {}}

    orig = proto_mod.generate_image
    proto_mod.generate_image = fake_generate_image
    try:
        gen = runtime.ProtocolGenerator(GeneratorType.IMAGE_TO_IMAGE)
        cfg = GenerationConfig(
            type=GeneratorType.IMAGE_TO_IMAGE, model="seededit", prompt="p",
            image_url="http://cdn/ref.png",
        )
        result = _run(gen.generate(cfg))
    finally:
        proto_mod.generate_image = orig

    assert result.success, result.error
    assert captured["refs"] == ["http://cdn/ref.png"]


def test_facade_missing_creds_honest_error(monkeypatch):
    from neurova.llm.generators import GenerationConfig, GeneratorType, runtime

    def boom(*a, **k):
        raise runtime.GenerationCredsError("缺少生成凭据：请先配置服务商")

    monkeypatch.setattr(runtime, "resolve_generation_creds", boom)
    gen = runtime.ProtocolGenerator(GeneratorType.TEXT_TO_IMAGE)
    result = _run(gen.generate(GenerationConfig(type=GeneratorType.TEXT_TO_IMAGE, prompt="p")))
    assert not result.success
    assert "凭据" in result.error


def test_facade_video_success_and_failure_honest(runtime_patched):
    runtime, calls = runtime_patched
    from neurova.llm.generators import GenerationConfig, GeneratorType
    from neurova.llm.generators import protocols as proto_mod

    async def fake_wait(creds, prompt, **kw):
        return {"status": "succeeded", "video_url": "http://cdn/v.mp4", "raw": {}}

    async def fake_wait_fail(creds, prompt, **kw):
        return {"status": "failed", "error": "内容审核不通过", "raw": {}}

    orig = proto_mod.generate_video_wait
    proto_mod.generate_video_wait = fake_wait
    try:
        gen = runtime.ProtocolGenerator(GeneratorType.TEXT_TO_VIDEO)
        result = _run(gen.generate(GenerationConfig(
            type=GeneratorType.TEXT_TO_VIDEO, model="wan3.0-t2v-bundle",
            prompt="p", duration=5,
        )))
    finally:
        proto_mod.generate_video_wait = orig
    assert result.success, result.error
    assert Path(result.output_path).is_file()

    proto_mod.generate_video_wait = fake_wait_fail
    try:
        result2 = _run(gen.generate(GenerationConfig(
            type=GeneratorType.TEXT_TO_VIDEO, model="wan3.0-t2v-bundle", prompt="p",
        )))
    finally:
        proto_mod.generate_video_wait = orig
    # 失败必须诚实：不得假成功、不得吞错
    assert not result2.success
    assert "审核" in result2.error


def test_facade_keyframe_v2v_unsupported_not_fake(runtime_patched):
    runtime, calls = runtime_patched
    from neurova.llm.generators import GenerationConfig, GeneratorType

    gen = runtime.ProtocolGenerator(GeneratorType.KEYFRAME_TO_VIDEO)
    result = _run(gen.generate(GenerationConfig(
        type=GeneratorType.KEYFRAME_TO_VIDEO,
        start_image_url="a.png", end_image_url="b.png",
    )))
    assert not result.success
    assert "协议" in result.error  # 诚实说明原因，而非假成功或空 error


# ── 5. Legacy bytes 适配器（wechat_ai/feishu_ai 旧工厂契约）────────────────


def test_legacy_image_adapter_returns_bytes(runtime_patched):
    runtime, calls = runtime_patched
    from neurova.llm.generators import get_image_generator
    from neurova.llm.generators import protocols as proto_mod

    async def fake_generate_image(creds, prompt, **kw):
        return {"images": ["http://cdn/img.png"], "task_id": None, "raw": {}}

    orig = proto_mod.generate_image
    proto_mod.generate_image = fake_generate_image
    try:
        gen = get_image_generator()
        data = _run(gen.generate(
            prompt="p", negative_prompt="", width=512, height=512, num_images=1,
        ))
    finally:
        proto_mod.generate_image = orig
    assert data == b"BYTES"


def test_legacy_image_adapter_none_on_failure(monkeypatch):
    from neurova.llm.generators import GenerationCredsError, get_image_generator, runtime

    def boom(*a, **k):
        raise GenerationCredsError("no creds")

    monkeypatch.setattr(runtime, "resolve_generation_creds", boom)
    gen = get_image_generator()
    data = _run(gen.generate(prompt="p"))
    assert data is None


def test_legacy_video_adapter_maps_kwargs(runtime_patched):
    runtime, calls = runtime_patched
    from neurova.llm.generators import get_video_generator
    from neurova.llm.generators import protocols as proto_mod

    captured = {}

    async def fake_wait(creds, prompt, **kw):
        captured["kwargs"] = kw
        return {"status": "succeeded", "video_url": "http://cdn/v.mp4", "raw": {}}

    orig = proto_mod.generate_video_wait
    proto_mod.generate_video_wait = fake_wait
    try:
        gen = get_video_generator()
        data = _run(gen.generate(prompt="p", duration=8, fps=24))
    finally:
        proto_mod.generate_video_wait = orig
    assert data == b"BYTES"
    assert captured["kwargs"].get("duration") == 8


# ── 6. 端点侧搬移后兼容（安全测试 patch 面不变）────────────────────────────


def test_endpoint_persist_wrapper_honours_module_dir(monkeypatch, tmp_path):
    """generation 端点 _persist_media 仍按模块全局 _GENERATION_OUTPUT_DIR 落盘
    （tests/api/test_generation_security.py 的 monkeypatch 契约不回退）。"""
    from neurova.api.endpoints import generation as gen

    monkeypatch.setattr(gen, "_GENERATION_OUTPUT_DIR", str(tmp_path))
    seen = {}

    async def fake_runtime_persist(url_or_data, kind, task_id, index, out_dir=None):
        seen["out_dir"] = out_dir
        return str(tmp_path / "f.png")

    from neurova.llm.generators import runtime

    orig = runtime.persist_media
    runtime.persist_media = fake_runtime_persist
    try:
        _run(gen._persist_media("data:image/png;base64,AAAA", "image", "t1", 0))
    finally:
        runtime.persist_media = orig
    assert seen["out_dir"] == str(tmp_path)


# ── 7. 账本追溯字段（批次0：渠道/画布/REST 产物同池可追溯）──────────────────


def test_task_record_traceability_fields(tmp_path):
    from neurova.llm.generators.task_ledger import (
        GenerationTaskLedger, TaskRecord,
    )

    ledger = GenerationTaskLedger(path=str(tmp_path / "tasks.json"))
    rec = ledger.add(TaskRecord(
        kind="video", source="workflow", execution_id="exec-42",
        remote_task_id="r1", owner_user_id="u1",
    ))
    loaded = ledger.get(rec.task_id)
    assert loaded.source == "workflow"
    assert loaded.execution_id == "exec-42"

    # 存量旧账本（无新字段）加载不炸：默认值兜底
    legacy = tmp_path / "legacy.json"
    legacy.write_text(
        '{"old1": {"task_id": "old1", "kind": "video", "status": "running",'
        ' "remote_task_id": "r0"}}',
        encoding="utf-8",
    )
    old_ledger = GenerationTaskLedger(path=str(legacy))
    rec0 = old_ledger.get("old1")
    assert rec0.source == "rest"
    assert rec0.execution_id == ""
