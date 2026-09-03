"""
tests/llm/test_model_route_config.py — core scenarios for model_route_config storage.
"""
import json
import pytest


class TestModelRouteConfig:
    def test_dataclass_to_from_dict_roundtrip(self):
        from neurova.llm.model_route_config import (
            ModelRouteConfig, RouteLevel, RequestType,
        )
        cfg = ModelRouteConfig(
            user_id="u1",
            level=RouteLevel.USER,
            request_type=RequestType.CHAT,
            model_id="gpt-4",
            provider_id="openai",
            priority=50,
        )
        data = cfg.to_dict()
        assert data["user_id"] == "u1"
        assert data["level"] == "user"
        assert data["request_type"] == "chat"
        assert data["model_id"] == "gpt-4"
        cfg2 = ModelRouteConfig.from_dict(data)
        assert cfg2.route_id == cfg.route_id
        assert cfg2.user_id == "u1"
        assert cfg2.level == RouteLevel.USER
        assert cfg2.request_type == RequestType.CHAT
        assert cfg2.model_id == "gpt-4"

    def test_matches_request_user_level_requires_user_id(self):
        from neurova.llm.model_route_config import (
            ModelRouteConfig, RouteLevel, RequestType,
        )
        cfg = ModelRouteConfig(
            user_id="alice",
            level=RouteLevel.USER,
            request_type=RequestType.CHAT,
            model_id="gpt-4",
            provider_id="openai",
        )
        assert cfg.matches_request(RequestType.CHAT, user_id="alice") is True
        assert cfg.matches_request(RequestType.CHAT, user_id="bob") is False

    def test_matches_request_general_type_accepts_all(self):
        from neurova.llm.model_route_config import (
            ModelRouteConfig, RouteLevel, RequestType,
        )
        cfg = ModelRouteConfig(
            level=RouteLevel.ADMIN,
            request_type=RequestType.GENERAL,
            model_id="claude-3",
            provider_id="anthropic",
        )
        assert cfg.matches_request(RequestType.CHAT) is True
        assert cfg.matches_request(RequestType.TOOL_CALL) is True

    def test_disabled_route_does_not_match(self):
        from neurova.llm.model_route_config import (
            ModelRouteConfig, RouteLevel, RequestType,
        )
        cfg = ModelRouteConfig(
            level=RouteLevel.SYSTEM,
            request_type=RequestType.CHAT,
            model_id="gpt-3.5",
            provider_id="openai",
            enabled=False,
        )
        assert cfg.matches_request(RequestType.CHAT) is False


class TestModelRouteConfigStorage:
    def test_create_and_get_route(self, tmp_path):
        from neurova.llm.model_route_config import (
            ModelRouteConfigStorage, ModelRouteConfig, RouteLevel, RequestType,
        )
        store = ModelRouteConfigStorage(str(tmp_path / "routes"))
        cfg = ModelRouteConfig(
            user_id="u1",
            level=RouteLevel.USER,
            request_type=RequestType.CHAT,
            model_id="gpt-4",
            provider_id="openai",
        )
        rid = store.create_route(cfg)
        assert isinstance(rid, str) and rid
        got = store.get_route(rid)
        assert got is not None
        assert got.model_id == "gpt-4"
        assert got.user_id == "u1"

    def test_update_and_delete_route(self, tmp_path):
        from neurova.llm.model_route_config import (
            ModelRouteConfigStorage, ModelRouteConfig, RouteLevel, RequestType,
        )
        store = ModelRouteConfigStorage(str(tmp_path / "routes"))
        cfg = ModelRouteConfig(
            level=RouteLevel.ADMIN,
            request_type=RequestType.TOOL_CALL,
            model_id="gpt-4",
            provider_id="openai",
        )
        rid = store.create_route(cfg)
        ok = store.update_route(rid, model_id="gpt-4-turbo", priority=99)
        assert ok is True
        got = store.get_route(rid)
        assert got.model_id == "gpt-4-turbo"
        assert got.priority == 99
        assert store.delete_route(rid) is True
        assert store.get_route(rid) is None

    def test_list_routes_by_level(self, tmp_path):
        from neurova.llm.model_route_config import (
            ModelRouteConfigStorage, ModelRouteConfig, RouteLevel, RequestType,
        )
        store = ModelRouteConfigStorage(str(tmp_path / "routes"))
        store.create_route(ModelRouteConfig(
            user_id="u1", level=RouteLevel.USER,
            request_type=RequestType.CHAT, model_id="m1", provider_id="p1",
        ))
        store.create_route(ModelRouteConfig(
            user_id="u2", level=RouteLevel.USER,
            request_type=RequestType.CHAT, model_id="m2", provider_id="p1",
        ))
        store.create_route(ModelRouteConfig(
            level=RouteLevel.ADMIN,
            request_type=RequestType.CHAT, model_id="m3", provider_id="p2",
        ))
        store.create_route(ModelRouteConfig(
            level=RouteLevel.SYSTEM,
            request_type=RequestType.CHAT, model_id="m4", provider_id="p2",
        ))
        users = store.list_routes(level=RouteLevel.USER)
        admins = store.list_routes(level=RouteLevel.ADMIN)
        system = store.list_routes(level=RouteLevel.SYSTEM)
        assert len(users) == 2
        assert len(admins) == 1
        assert len(system) == 1
        assert admins[0].model_id == "m3"

    def test_select_best_route_prefers_user_over_admin_over_system(self, tmp_path):
        from neurova.llm.model_route_config import (
            ModelRouteConfigStorage, ModelRouteConfig, RouteLevel, RequestType,
        )
        store = ModelRouteConfigStorage(str(tmp_path / "routes"))
        store.create_route(ModelRouteConfig(
            level=RouteLevel.SYSTEM,
            request_type=RequestType.CHAT, model_id="sys-model", provider_id="p1",
        ))
        store.create_route(ModelRouteConfig(
            level=RouteLevel.ADMIN,
            request_type=RequestType.CHAT, model_id="admin-model", provider_id="p2",
        ))
        store.create_route(ModelRouteConfig(
            user_id="alice", level=RouteLevel.USER,
            request_type=RequestType.CHAT, model_id="user-model", provider_id="p3",
        ))
        best = store.select_best_route(
            request_type=RequestType.CHAT, user_id="alice"
        )
        assert best is not None
        assert best.model_id == "user-model"
        best_anon = store.select_best_route(
            request_type=RequestType.CHAT, user_id=None
        )
        assert best_anon is not None
        assert best_anon.model_id == "admin-model"

    def test_persists_to_disk_and_reloads(self, tmp_path):
        from neurova.llm.model_route_config import (
            ModelRouteConfigStorage, ModelRouteConfig, RouteLevel, RequestType,
        )
        d = tmp_path / "persist"
        store = ModelRouteConfigStorage(str(d))
        cfg = ModelRouteConfig(
            level=RouteLevel.ADMIN,
            request_type=RequestType.CODE_GENERATION,
            model_id="gpt-4-turbo", provider_id="openai",
        )
        rid = store.create_route(cfg)
        json_file = d / "routes.json"
        assert json_file.exists()
        raw = json.loads(json_file.read_text(encoding="utf-8"))
        assert rid in raw
        store2 = ModelRouteConfigStorage(str(d))
        got = store2.get_route(rid)
        assert got is not None
        assert got.model_id == "gpt-4-turbo"
        assert got.level == RouteLevel.ADMIN


class TestGetModelRouteConfigStorage:
    def test_returns_singleton(self, tmp_path, monkeypatch):
        from neurova import llm
        from neurova.llm import model_route_config as mrc
        monkeypatch.setattr(mrc, "_DEFAULT_DIR", str(tmp_path / "global"))
        mrc._singleton = None
        a = mrc.get_model_route_config_storage()
        b = mrc.get_model_route_config_storage()
        assert a is b
