"""Tests for neurova.llm.providers.multimodal_prober — heuristic prober."""
import json
import pytest


class TestMultimodalProberInit:
    def test_init_with_storage_path(self, tmp_path):
        from neurova.llm.providers.multimodal_prober import MultimodalProber
        prober = MultimodalProber(str(tmp_path / "probe"))
        assert prober is not None

    def test_init_persists_empty_file(self, tmp_path):
        from neurova.llm.providers.multimodal_prober import MultimodalProber
        storage = tmp_path / "probe"
        MultimodalProber(str(storage))
        target = storage / "probes.json"
        assert target.exists()
        data = json.loads(target.read_text(encoding="utf-8"))
        assert isinstance(data, dict)


class TestProbeRecord:
    def test_record_fields(self):
        from neurova.llm.providers.multimodal_prober import ProbeRecord
        rec = ProbeRecord(
            model_id="gpt-4-vision",
            filename="cat.png",
            mime_type="image/png",
            capabilities=["vision"],
            confidence=0.8,
            method="extension+mime",
        )
        assert rec.model_id == "gpt-4-vision"
        assert rec.filename == "cat.png"
        assert rec.mime_type == "image/png"
        assert "vision" in rec.capabilities
        assert rec.confidence == 0.8
        assert rec.method == "extension+mime"

    def test_record_to_dict_round_trip(self):
        from neurova.llm.providers.multimodal_prober import ProbeRecord
        rec = ProbeRecord(model_id="m1", capabilities=["vision"], confidence=0.5)
        data = rec.to_dict()
        assert isinstance(data, dict)
        rec2 = ProbeRecord.from_dict(data)
        assert rec2.model_id == rec.model_id
        assert rec2.capabilities == rec.capabilities


class TestDetectCapabilities:
    def test_detect_vision_from_png_extension(self, tmp_path):
        from neurova.llm.providers.multimodal_prober import MultimodalProber
        prober = MultimodalProber(str(tmp_path / "probe"))
        rec = prober.detect_capabilities(filename="photo.png")
        assert "vision" in rec.capabilities

    def test_detect_audio_from_mp3_extension(self, tmp_path):
        from neurova.llm.providers.multimodal_prober import MultimodalProber
        prober = MultimodalProber(str(tmp_path / "probe"))
        rec = prober.detect_capabilities(filename="song.mp3")
        assert "audio" in rec.capabilities

    def test_detect_video_from_mp4_extension(self, tmp_path):
        from neurova.llm.providers.multimodal_prober import MultimodalProber
        prober = MultimodalProber(str(tmp_path / "probe"))
        rec = prober.detect_capabilities(filename="clip.mp4")
        assert "video" in rec.capabilities

    def test_detect_vision_from_mime(self, tmp_path):
        from neurova.llm.providers.multimodal_prober import MultimodalProber
        prober = MultimodalProber(str(tmp_path / "probe"))
        rec = prober.detect_capabilities(mime_type="image/jpeg")
        assert "vision" in rec.capabilities

    def test_detect_from_model_name(self, tmp_path):
        from neurova.llm.providers.multimodal_prober import MultimodalProber
        prober = MultimodalProber(str(tmp_path / "probe"))
        rec = prober.detect_capabilities(model_id="gpt-4-vision-preview")
        assert "vision" in rec.capabilities

    def test_detect_audio_from_model_name(self, tmp_path):
        from neurova.llm.providers.multimodal_prober import MultimodalProber
        prober = MultimodalProber(str(tmp_path / "probe"))
        rec = prober.detect_capabilities(model_id="whisper-large-v3")
        assert "audio" in rec.capabilities

    def test_detect_unknown_returns_empty(self, tmp_path):
        from neurova.llm.providers.multimodal_prober import MultimodalProber
        prober = MultimodalProber(str(tmp_path / "probe"))
        rec = prober.detect_capabilities(filename="data.xyz", model_id="unknown-model")
        assert rec.capabilities == [] or rec.capabilities == ["text"]


class TestConvenienceDetectors:
    def test_is_vision_returns_true_for_image(self, tmp_path):
        from neurova.llm.providers.multimodal_prober import MultimodalProber
        prober = MultimodalProber(str(tmp_path / "probe"))
        assert prober.is_vision(filename="cat.png") is True

    def test_is_audio_returns_false_for_text(self, tmp_path):
        from neurova.llm.providers.multimodal_prober import MultimodalProber
        prober = MultimodalProber(str(tmp_path / "probe"))
        assert prober.is_audio(filename="readme.md") is False

    def test_is_video_returns_true_for_mp4(self, tmp_path):
        from neurova.llm.providers.multimodal_prober import MultimodalProber
        prober = MultimodalProber(str(tmp_path / "probe"))
        assert prober.is_video(filename="movie.mp4") is True


class TestRecordsManagement:
    def test_record_persisted_to_json(self, tmp_path):
        from neurova.llm.providers.multimodal_prober import MultimodalProber
        storage = tmp_path / "probe"
        prober = MultimodalProber(str(storage))
        rec = prober.detect_capabilities(filename="cat.png")
        prober2 = MultimodalProber(str(storage))
        loaded = prober2.get_record(rec.id)
        assert loaded is not None
        assert loaded.id == rec.id

    def test_list_records_filters_by_model(self, tmp_path):
        from neurova.llm.providers.multimodal_prober import MultimodalProber
        prober = MultimodalProber(str(tmp_path / "probe"))
        prober.detect_capabilities(model_id="gpt-4-vision", filename="a.png")
        prober.detect_capabilities(model_id="whisper", filename="b.mp3")
        gpt_records = prober.list_records(model_id="gpt-4-vision")
        assert all(r.model_id == "gpt-4-vision" for r in gpt_records)

    def test_clear_removes_all(self, tmp_path):
        from neurova.llm.providers.multimodal_prober import MultimodalProber
        prober = MultimodalProber(str(tmp_path / "probe"))
        prober.detect_capabilities(filename="a.png")
        prober.clear()
        assert prober.list_records() == []

    def test_get_stats_returns_dict(self, tmp_path):
        from neurova.llm.providers.multimodal_prober import MultimodalProber
        prober = MultimodalProber(str(tmp_path / "probe"))
        prober.detect_capabilities(filename="a.png")
        prober.detect_capabilities(filename="b.mp3")
        stats = prober.get_stats()
        assert isinstance(stats, dict)
        assert stats.get("total", 0) >= 2


class TestSingleton:
    def test_singleton_returns_same_instance(self, tmp_path, monkeypatch):
        from neurova.llm.providers import multimodal_prober as mod
        monkeypatch.setattr(mod, "_singleton", None)
        monkeypatch.setattr(mod, "_DEFAULT_DIR", str(tmp_path / "singleton_probe"))
        a = mod.get_multimodal_prober()
        b = mod.get_multimodal_prober()
        assert a is b
