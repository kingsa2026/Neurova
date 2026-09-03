"""Tests for media/manager.py - core scenarios only (file_flow pattern)."""
import json
import pytest


class TestMediaManagerInit:
    def test_init_creates_storage_dir(self, tmp_path):
        from neurova.media.manager import MediaManager
        target = tmp_path / "media"
        mgr = MediaManager(str(target))
        assert mgr is not None
        assert target.exists()
        assert target.is_dir()

    def test_init_persists_empty_index(self, tmp_path):
        from neurova.media.manager import MediaManager
        mgr = MediaManager(str(tmp_path / "media"))
        mgr._save()
        assert (tmp_path / "media" / "media.json").exists()


class TestSaveAndGetMedia:
    def test_save_media_returns_id(self, tmp_path):
        from neurova.media.manager import MediaManager
        mgr = MediaManager(str(tmp_path / "media"))
        mid = mgr.save_media(filename="hello.png", content=b"binary-bytes",
                             agent_id="a1", user_id="u1")
        assert isinstance(mid, str) and mid

    def test_get_media_returns_record(self, tmp_path):
        from neurova.media.manager import MediaManager
        mgr = MediaManager(str(tmp_path / "media"))
        mid = mgr.save_media(filename="hello.png", content=b"x", agent_id="a1")
        rec = mgr.get_media(mid)
        assert rec is not None
        assert rec.get("filename") == "hello.png"
        assert rec.get("agent_id") == "a1"
        assert rec.get("media_id") == mid

    def test_get_media_missing_returns_none(self, tmp_path):
        from neurova.media.manager import MediaManager
        mgr = MediaManager(str(tmp_path / "media"))
        assert mgr.get_media("nonexistent") is None


class TestListMedia:
    def test_list_filters_by_agent(self, tmp_path):
        from neurova.media.manager import MediaManager
        mgr = MediaManager(str(tmp_path / "media"))
        mgr.save_media(filename="a.png", content=b"1", agent_id="a1")
        mgr.save_media(filename="b.png", content=b"2", agent_id="a2")
        result = mgr.list_media(agent_id="a1")
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["filename"] == "a.png"

    def test_list_filters_by_media_type(self, tmp_path):
        from neurova.media.manager import MediaManager
        mgr = MediaManager(str(tmp_path / "media"))
        mgr.save_media(filename="pic.png", content=b"1", agent_id="a1")
        mgr.save_media(filename="audio.mp3", content=b"2", agent_id="a1")
        result = mgr.list_media(media_type="image")
        assert all(r.get("media_type") == "image" for r in result)
        assert len(result) >= 1


class TestUpdateAndDelete:
    def test_update_media_fields(self, tmp_path):
        from neurova.media.manager import MediaManager
        mgr = MediaManager(str(tmp_path / "media"))
        mid = mgr.save_media(filename="x.png", content=b"1", agent_id="a1")
        ok = mgr.update_media(mid, description="new desc")
        assert ok is True
        rec = mgr.get_media(mid)
        assert rec.get("description") == "new desc"

    def test_delete_media_soft(self, tmp_path):
        from neurova.media.manager import MediaManager
        mgr = MediaManager(str(tmp_path / "media"))
        mid = mgr.save_media(filename="x.png", content=b"1", agent_id="a1")
        assert mgr.delete_media(mid) is True
        rec = mgr.get_media(mid)
        assert rec is not None
        assert rec.get("is_deleted") is True

    def test_delete_media_permanent(self, tmp_path):
        from neurova.media.manager import MediaManager
        mgr = MediaManager(str(tmp_path / "media"))
        mid = mgr.save_media(filename="x.png", content=b"1", agent_id="a1")
        assert mgr.delete_media(mid, permanent=True) is True
        assert mgr.get_media(mid) is None


class TestPersistence:
    def test_data_persists_across_instances(self, tmp_path):
        from neurova.media.manager import MediaManager
        storage = str(tmp_path / "media")
        mgr1 = MediaManager(storage)
        mid = mgr1.save_media(filename="x.png", content=b"1", agent_id="a1")
        mgr2 = MediaManager(storage)
        rec = mgr2.get_media(mid)
        assert rec is not None
        assert rec.get("filename") == "x.png"


class TestStats:
    def test_get_stats_returns_dict(self, tmp_path):
        from neurova.media.manager import MediaManager
        mgr = MediaManager(str(tmp_path / "media"))
        mgr.save_media(filename="x.png", content=b"hello", agent_id="a1")
        stats = mgr.get_stats()
        assert isinstance(stats, dict)
        assert "total_files" in stats
        assert stats["total_files"] >= 1


class TestDetectMediaType:
    def test_detect_image_extension(self, tmp_path):
        from neurova.media.manager import MediaManager
        mgr = MediaManager(str(tmp_path / "media"))
        assert mgr._detect_media_type("photo.png") == "image"

    def test_detect_audio_extension(self, tmp_path):
        from neurova.media.manager import MediaManager
        mgr = MediaManager(str(tmp_path / "media"))
        assert mgr._detect_media_type("song.mp3") == "audio"


class TestGetMediaManager:
    def test_returns_singleton(self):
        from neurova.media.manager import get_media_manager
        a = get_media_manager()
        b = get_media_manager()
        assert a is b
