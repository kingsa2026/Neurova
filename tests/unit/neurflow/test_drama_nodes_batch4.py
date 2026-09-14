# -*- coding: utf-8 -*-
"""批次4：drama 节点从"半实现"升级成真节点。

锁定（放大视角根因——这些节点此前对画布"能用"，但三处名不副实）：
1. storyboard：正则按句拆分 → LLM 真分镜（坏 JSON / 无凭据回退既有规则，增强不替换）；
   风格+画幅项目锁注入每镜 visual_prompt（火宝式）；
2. voice-over：只整理台词未接 TTS → 真调 TTS 合成并落盘产物（不可用时诚实标注，
   不再装作只有文本是设计如此）；
3. scene-gen / video-compose：
   - scene-gen 非 comfyui 服务商改走 llm/generators 实测协议矩阵（批次0 单源），
     kling/jimeng 等未验协议诚实降级并给 reason；
   - video-compose **禁假文件名**（原降级返回 composed_<ts>.mp4 并不存在该文件，
     违反修复教义"禁止表面抹除"）：有 FFmpeg 真拼接；无 FFmpeg 输出连播清单
     manifest（诚实产物），前端连播播放器消费；
4. external_api VideoGenClient.generate comfyui 分支缺 await（async 方法直接
   return → 调用方拿到协程对象，.get 抛错被吞成降级路径——顺带根治）。
"""
from __future__ import annotations

import json

import pytest

from neurova.collaboration.neurflow import drama_nodes as dn

pytestmark = pytest.mark.timeout(60)


# ── 1. storyboard LLM 分镜 ─────────────────────────────────────────────────


class TestStoryboardLLM:
    @pytest.mark.asyncio
    async def test_llm_shots_with_style_injection(self, monkeypatch):
        shots = [
            {"description": "主角推门", "visual_prompt": "man pushes door",
             "narration": "他回来了", "duration": 3, "camera": "中景",
             "move": "推", "transition": "cut"},
            {"description": "众人惊愕", "visual_prompt": "crowd shocked",
             "narration": "全场寂静", "duration": 2.5, "camera": "全景",
             "move": "固定", "transition": "fade"},
        ]

        async def fake_agent(prompt, system_prompt=""):
            return "分析如下：\n" + json.dumps(shots, ensure_ascii=False) + "\n完毕"

        monkeypatch.setattr(dn, "_call_agent", fake_agent)
        result = await dn.exec_storyboard(
            {"script": "主角推门而入，众人惊愕。", "style": "国风水墨", "aspect_ratio": "9:16"}, {})

        out = result["output"]
        assert out["count"] == 2
        assert out.get("fallback") is None or out.get("fallback") is False
        assert out["shots"][0]["narration"] == "他回来了"
        # 火宝式：风格注入画面提示词
        assert "国风水墨" in out["shots"][0]["visual_prompt"]

    @pytest.mark.asyncio
    async def test_broken_json_falls_back_to_rules(self, monkeypatch):
        async def fake_agent(prompt, system_prompt=""):
            return "这里没有可用的 JSON 只有描述文字"

        monkeypatch.setattr(dn, "_call_agent", fake_agent)
        result = await dn.exec_storyboard({"script": "第一幕开始。第二幕高潮。"}, {})
        out = result["output"]
        assert out["fallback"] is True
        assert out["count"] == 2

    @pytest.mark.asyncio
    async def test_agent_failure_falls_back(self, monkeypatch):
        async def boom(prompt, system_prompt=""):
            raise RuntimeError("模型不可用")

        monkeypatch.setattr(dn, "_call_agent", boom)
        result = await dn.exec_storyboard({"script": "只有一句。"}, {})
        assert result["output"]["fallback"] is True
        assert result["status"] == "success"  # 回退规则拆分仍属成功产出


# ── 2. voice-over 接真 TTS ─────────────────────────────────────────────────


class TestVoiceOverTTS:
    @pytest.mark.asyncio
    async def test_synth_audio_files(self, monkeypatch, tmp_path):
        class FakeTTS:
            async def synthesize(self, text, voice="", language="", rate=1.0):
                return b"RIFFfake"

        monkeypatch.setattr(dn, "_get_tts_manager", lambda: FakeTTS())
        from neurova.llm.generators import runtime as gen_runtime

        async def fake_persist_bytes(data, ext, task_id, index, out_dir=None):
            p = tmp_path / f"vo_{index}.{ext}"
            p.write_bytes(data)
            return str(p)

        monkeypatch.setattr(gen_runtime, "persist_bytes", fake_persist_bytes)

        result = await dn.exec_voice_over({"lines": "你好世界\n第二句台词"}, {})
        out = result["output"]
        assert len(out["audio_paths"]) == 2
        assert out["audio_paths"][0]["url"].startswith("/api/v1/generation/files/")
        assert out["voiceover_error"] == ""

    @pytest.mark.asyncio
    async def test_batch_shots_uses_narration(self, monkeypatch, tmp_path):
        class FakeTTS:
            async def synthesize(self, text, voice="", language="", rate=1.0):
                return b"RIFF"

        monkeypatch.setattr(dn, "_get_tts_manager", lambda: FakeTTS())
        from neurova.llm.generators import runtime as gen_runtime

        async def fake_persist_bytes(data, ext, task_id, index, out_dir=None):
            p = tmp_path / f"vo_{index}.wav"
            p.write_bytes(data)
            return str(p)

        monkeypatch.setattr(gen_runtime, "persist_bytes", fake_persist_bytes)
        shots = [{"narration": "旁白一", "description": "d1"},
                 {"narration": "旁白二", "description": "d2"}]
        result = await dn.exec_voice_over({"shots": shots}, {})
        out = result["output"]
        assert [a["line"] for a in out["audio_paths"]] == ["旁白一", "旁白二"]
        assert len(out["audio_paths"]) == 2

    @pytest.mark.asyncio
    async def test_tts_unavailable_honest_flag(self, monkeypatch):
        monkeypatch.setattr(dn, "_get_tts_manager", lambda: None)
        result = await dn.exec_voice_over({"lines": "台词"}, {})
        out = result["output"]
        assert out["audio_paths"] == []
        assert "TTS" in out["voiceover_error"]
        assert out["lines"] == ["台词"]  # 台词整理输出保持向后兼容


# ── 3. scene-gen 实测协议单源 ──────────────────────────────────────────────


class TestSceneGenProtocols:
    @pytest.mark.asyncio
    async def test_batch_shots_fanout(self, monkeypatch, tmp_path):
        """逐镜扇出：shots 数组 → 每镜一张图（PRINTFILM 批量生成语义）。"""
        from neurova.llm.generators import protocols as proto_mod
        from neurova.llm.generators import runtime as gen_runtime
        from neurova.llm.generators.protocols import ProtocolCredentials

        monkeypatch.setattr(
            gen_runtime, "resolve_generation_creds",
            lambda hint, model, pid, ak, bu, db: ProtocolCredentials(
                api_key="k", base_url="https://x", model="m", protocol=hint))

        async def fake_gen(creds, prompt, **kw):
            return {"images": [f"http://cdn/{abs(hash(prompt)) % 999}.png"], "task_id": None, "raw": {}}

        async def fake_persist(url, kind, task_id, index, out_dir=None):
            p = tmp_path / f"b_{index}.png"
            p.write_bytes(b"P")
            return str(p)

        monkeypatch.setattr(proto_mod, "generate_image", fake_gen)
        monkeypatch.setattr(gen_runtime, "persist_media", fake_persist)

        shots = [
            {"shot": 1, "visual_prompt": "vp one", "description": "镜一"},
            {"shot": 2, "visual_prompt": "vp two", "description": "镜二"},
        ]
        result = await dn.exec_scene_gen({"shots": shots, "provider": "wanx"}, {})
        out = result["output"]
        assert out["batch"] is True
        assert len(out["images"]) == 2
        assert out["images"][0]["url"].startswith("/api/v1/generation/files/")
        assert out["images"][0]["shot"] == 1

    @pytest.mark.asyncio
    async def test_wanx_routes_to_dashscope_protocol(self, monkeypatch, tmp_path):
        from neurova.llm.generators import protocols as proto_mod
        from neurova.llm.generators import runtime as gen_runtime
        from neurova.llm.generators.protocols import ProtocolCredentials

        monkeypatch.setattr(
            gen_runtime, "resolve_generation_creds",
            lambda hint, model, pid, ak, bu, db: ProtocolCredentials(
                api_key="k", base_url="https://dashscope", model="wan2.2-t2i", protocol=hint))

        async def fake_gen(creds, prompt, **kw):
            return {"images": ["http://cdn/x.png"], "task_id": None, "raw": {}}

        async def fake_persist(url, kind, task_id, index, out_dir=None):
            p = tmp_path / "s_0.png"
            p.write_bytes(b"P")
            return str(p)

        monkeypatch.setattr(proto_mod, "generate_image", fake_gen)
        monkeypatch.setattr(gen_runtime, "persist_media", fake_persist)

        result = await dn.exec_scene_gen({"scene": "雨夜街头", "provider": "wanx"}, {})
        out = result["output"]
        assert out["image_url"].startswith("/api/v1/generation/files/")
        assert out.get("fallback") is None or out.get("fallback") is False

    @pytest.mark.asyncio
    async def test_unverified_provider_honest_degrade(self, monkeypatch):
        # kling 无实测协议：不得静默走外部假端点，须给 reason 降级
        result = await dn.exec_scene_gen({"scene": "s", "provider": "kling"}, {})
        out = result["output"]
        assert out["fallback"] is True
        assert "kling" in out.get("degrade_reason", "")

    @pytest.mark.asyncio
    async def test_model_selector_keys_flow_to_creds(self, monkeypatch, tmp_path):
        """画布 model-selector 契约：model_name/model_provider（属性面板写入）
        须流到凭据解析（键名劈叉曾致节点选择静默无效）。"""
        from neurova.llm.generators import protocols as proto_mod
        from neurova.llm.generators import runtime as gen_runtime
        from neurova.llm.generators.protocols import ProtocolCredentials

        seen = {}

        def fake_resolve(hint, model, pid, ak, bu, db):
            seen["args"] = (hint, model, pid)
            return ProtocolCredentials(api_key="k", base_url="https://x",
                                       model="m", protocol=hint)

        async def fake_gen(creds, prompt, **kw):
            return {"images": ["http://cdn/x.png"], "task_id": None, "raw": {}}

        async def fake_persist(url, kind, task_id, index, out_dir=None):
            fp = tmp_path / "m_0.png"
            fp.write_bytes(b"P")
            return str(fp)

        monkeypatch.setattr(gen_runtime, "resolve_generation_creds", fake_resolve)
        monkeypatch.setattr(proto_mod, "generate_image", fake_gen)
        monkeypatch.setattr(gen_runtime, "persist_media", fake_persist)
        await dn.exec_scene_gen({"scene": "s", "provider": "openai",
                                 "model_name": "flux.1", "model_provider": "prov-x"}, {})
        assert seen["args"][1] == "flux.1"
        assert seen["args"][2] == "prov-x"

    def test_scene_gen_schema_exposes_capability_model_selector(self):
        """schema：scene-gen 有 model-selector 字段且声明 image_generation
        能力过滤（前端按 provider_capability 筛下拉）。"""
        defn = next(d for d in dn.DRAMA_NODES
                    if d["type"] == "builtin:scene-gen")
        field = next(f for f in defn["sub_blocks"] if f.get("type") == "model-selector")
        assert field["id"] == "model_name"
        assert field["provider_capability"] == "image_generation"

    def test_scene_gen_serialization_keeps_capability(self):
        """序列化链根因修复：_sub_block_to_dict 白名单曾丢 provider_capability
        （后端声明到不了前端 → 能力过滤失效）。两分支都要透传。"""
        from neurova.api.endpoints.neurflow_api import _sub_block_to_dict

        d = _sub_block_to_dict({"id": "model_name", "label": "生成模型",
                                "type": "model-selector",
                                "provider_capability": "image_generation"})
        assert d["provider_capability"] == "image_generation"

        from neurova.collaboration.neurflow.models import SubBlockConfig

        o = _sub_block_to_dict(SubBlockConfig(id="model_name", title="生成模型",
                                              type="model-selector",
                                              provider_capability="video_generation"))
        assert o["provider_capability"] == "video_generation"


# ── 4. video-compose 禁假文件名 ────────────────────────────────────────────


class TestVideoComposeHonest:
    @pytest.mark.asyncio
    async def test_no_ffmpeg_outputs_manifest_not_fake_file(self, monkeypatch):
        import shutil as _shutil

        monkeypatch.setattr(_shutil, "which", lambda x: None)
        result = await dn.exec_video_compose(
            {"clips": ["/tmp/a.mp4", "/tmp/b.mp4"]}, {})
        out = result["output"]
        # 不得出现并不存在的 composed_*.mp4 假文件名
        video = out.get("video", "")
        assert not str(video).startswith("composed_"), f"假文件名回归: {video}"
        assert out["mode"] == "slideshow_manifest"
        assert out["composed"] is False
        assert len(out["items"]) == 2

    @pytest.mark.asyncio
    async def test_ffmpeg_compose_real_output(self, monkeypatch, tmp_path):
        import shutil as _shutil

        monkeypatch.setattr(_shutil, "which", lambda x: "/usr/bin/ffmpeg")
        called = {}

        class FakeProc:
            returncode = 0

        def fake_run(cmd, **kw):
            called["cmd"] = cmd
            # 模拟 ffmpeg 产出文件
            out_path = cmd[-1]
            open(out_path, "wb").write(b"MP4")
            return FakeProc()

        import subprocess as _sp

        monkeypatch.setattr(_sp, "run", fake_run)
        clips = [str(tmp_path / "a.mp4"), str(tmp_path / "b.mp4")]
        for c in clips:
            open(c, "wb").write(b"x")

        result = await dn.exec_video_compose({"clips": clips}, {})
        out = result["output"]
        assert out["composed"] is True
        assert out["video_url"].startswith("/api/v1/generation/files/")
        assert "ffmpeg" in str(called["cmd"][0])

    def test_videogenclient_comfyui_returns_dict_not_coroutine(self):
        """external_api await 缺陷：async 方法漏 await → 调用方拿到协程对象。"""
        import asyncio
        import inspect

        from neurova.collaboration.neurflow.external_api import VideoGenClient

        client = VideoGenClient()
        result = asyncio.run(client.generate("comfyui", "p"))
        assert isinstance(result, dict), f"应为 dict，实得 {type(result)}"
        assert result.get("status") != "success"


# ── 5. 节点定义面更新 ──────────────────────────────────────────────────────


class TestNodeDefinitions:
    def test_storyboard_has_llm_toggle_and_style(self):
        sb = next(n for n in dn.DRAMA_NODES if n["type"] == "builtin:storyboard")
        ids = {b["id"] for b in sb.get("sub_blocks", [])}
        assert "style" in ids

    def test_video_compose_declares_slideshow_degrade(self):
        vc = next(n for n in dn.DRAMA_NODES if n["type"] == "builtin:video-compose")
        assert "连播清单" in vc["description"] or "slideshow" in vc["description"].lower()
