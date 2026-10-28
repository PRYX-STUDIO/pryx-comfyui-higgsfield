"""API-first discovery lifecycle, without paid operations or GitHub access."""

import asyncio
import copy
import hashlib
import json
import sys
from types import SimpleNamespace

import pytest

from pryx_comfyui_higgsfield import credentials, server
from pryx_comfyui_higgsfield.catalog import discovery, load_bundled_catalog
from pryx_comfyui_higgsfield.catalog import catalog as catalog_module
from pryx_comfyui_higgsfield.catalog.catalog import CatalogManager
from pryx_comfyui_higgsfield.client import HiggsfieldClient
from pryx_comfyui_higgsfield.credentials import Credentials
from pryx_comfyui_higgsfield.nodes import generation


def snapshot():
    return {m.endpoint: {"slug": m.endpoint, "schema": copy.deepcopy(m.input_schema), "source": m.docs_source,
                         "title": m.family, "variant_title": "", "operation_type": [], "output_type": m.output.value}
            for m in load_bundled_catalog().models}


@pytest.fixture
def api_manager(monkeypatch, tmp_path):
    clock = [100_000.0]
    account = [Credentials("test-account-id", "do-not-store-this-secret", "test")]
    calls = []
    monkeypatch.setattr(credentials, "resolve_credentials", lambda **kw: account[0])
    monkeypatch.setattr(HiggsfieldClient, "close", lambda self: None)
    def discover(client):
        calls.append(True)
        return snapshot()
    monkeypatch.setattr(discovery, "authenticated_snapshot", discover)
    manager = CatalogManager(cache_path=tmp_path / "models.json", clock=lambda: clock[0])
    return manager, clock, account, calls


def test_cache_ttl_force_and_changed_key(api_manager):
    manager, clock, account, calls = api_manager
    manager.load()
    manager.load()
    assert len(calls) == 1
    assert manager.last_sync_status == "higgsfield-api:cached"
    clock[0] += 24 * 60 * 60
    manager.load()
    assert len(calls) == 2
    account[0] = Credentials("different-account", "other-secret", "test")
    manager.load()
    assert len(calls) == 3
    manager.refresh_available()
    assert len(calls) == 4
    content = manager.cache_path.read_text()
    assert "different-account" not in content and "other-secret" not in content
    assert "do-not-store-this-secret" not in content
    assert json.loads(content)["provider_sync"]["key_fingerprint"] == hashlib.sha256(b"different-account").hexdigest()


def test_no_key_uses_local_models_without_any_discovery(api_manager):
    manager, _, account, calls = api_manager
    account[0] = None
    assert manager.load().source == "bundled"
    assert manager.last_sync_status == "not-configured"
    assert not calls


def test_offline_discovery_retains_cache_and_does_not_mark_it_fresh(api_manager, monkeypatch):
    manager, clock, _, calls = api_manager
    original = manager.load().as_payload()
    old_bytes = manager.cache_path.read_bytes()
    clock[0] += 24 * 60 * 60
    def offline(client):
        calls.append(True)
        raise ValueError("Offline or incompatible schema")
    monkeypatch.setattr(discovery, "authenticated_snapshot", offline)
    assert manager.load().as_payload() == original
    assert manager.last_sync_status == "higgsfield-api:failed"
    assert manager.cache_path.read_bytes() == old_bytes
    manager.load()
    assert len(calls) == 3  # Failed discovery is retried, never cached as success.


def test_legacy_cache_without_api_confirmation_is_rechecked(api_manager):
    manager, _, _, calls = api_manager
    manager._write_cache(load_bundled_catalog().as_payload())
    manager.load()
    assert len(calls) == 1
    assert "provider_sync" in json.loads(manager.cache_path.read_text())


def test_deleted_credentials_stop_discovery_but_keep_working_definitions(api_manager):
    manager, clock, account, calls = api_manager
    expected = manager.load().as_payload()
    account[0] = None
    clock[0] += 24 * 60 * 60
    assert manager.load().as_payload() == expected
    assert manager.last_sync_status == "not-configured"
    assert len(calls) == 1


def test_periodic_checks_stop_on_shutdown_without_waiting_in_test(monkeypatch):
    checks = []
    waits = []
    def wait(seconds):
        waits.append(seconds)
        return len(waits) > 1
    monkeypatch.setattr(server, "refresh_models", lambda: checks.append(True))
    server._catalog_refresh_loop(SimpleNamespace(wait=wait))
    assert checks == [True] and waits == [3600, 3600]


def test_authenticated_discovery_does_not_retry_during_startup(monkeypatch):
    captured = []
    monkeypatch.setattr(discovery, "MIN_DISCOVERED_ENDPOINTS", 1)
    def get(path, **kwargs):
        captured.append((path, kwargs))
        return {"total": 1, "items": [{"slug": "provider/model", "input_schema": {"type": "object", "properties": {}}}]}
    discovery.authenticated_snapshot(SimpleNamespace(get_json=get))
    assert captured == [("/models?include_schema=true", {"attempts": 1})]


def test_startup_discovers_before_pinning_node_schema(api_manager, monkeypatch):
    manager, _, _, calls = api_manager
    monkeypatch.setattr(catalog_module, "default_catalog_manager", lambda: manager)
    current = catalog_module.runtime_catalog.__wrapped__()
    assert len(calls) == 1 and current.source == "higgsfield-api"


def test_new_model_and_new_controls_need_no_bundled_catalog_edit(api_manager, monkeypatch):
    manager, _, _, _ = api_manager
    data = snapshot()
    item = copy.deepcopy(data["minimax/h3/image-to-video"])
    item.update(slug="new-provider/new-animator", title="New Animator", operation_type=["image2video"])
    item["schema"]["properties"]["stabilization"] = {"type": "string", "enum": ["off", "on"], "default": "on"}
    data[item["slug"]] = item
    monkeypatch.setattr(discovery, "authenticated_snapshot", lambda client: data)
    updated = manager.load()
    monkeypatch.setattr(generation, "_CATALOG", updated)
    model = updated.get("new-provider-new-animator")
    assert model.capability.value == "image_to_video"
    definitions = generation.ImageToVideoNode.INPUT_TYPES()
    assert model.id in definitions["required"]["model"][1]["choices"]
    assert definitions["optional"]["stabilization"][0] == ["off", "on"]
    assert model.parameter_map["stabilization"].default == "on"


def test_retired_model_does_not_block_other_updates_and_can_reappear(api_manager, monkeypatch):
    manager, _, _, _ = api_manager
    data = snapshot()
    missing = data.pop("minimax/h3/image-to-video")
    data["higgsfield-ai/soul/v2/standard"]["schema"]["properties"]["custom_reference_strength"]["default"] = 0.75
    monkeypatch.setattr(discovery, "authenticated_snapshot", lambda client: data)
    updated = manager.refresh_available()
    assert updated.get("minimax-h3-image-to-video").status.value == "unavailable"
    assert updated.get("soul-2").parameter_map["custom_reference_strength"].default == 0.75
    assert updated.get("soul-cinema").status.value == "active"
    data["minimax/h3/image-to-video"] = missing
    assert manager.refresh_available().get("minimax-h3-image-to-video").status.value == "active"


@pytest.mark.parametrize("sync", [None, [], "invalid", {"checked_at": "invalid"}])
def test_malformed_sync_metadata_cannot_break_startup(api_manager, sync):
    manager, _, _, calls = api_manager
    payload = load_bundled_catalog().as_payload()
    payload["provider_sync"] = sync
    manager._write_cache(payload)
    assert manager.load().source == "higgsfield-api"
    assert len(calls) == 1


def test_background_update_marks_restart_without_replacing_runtime(api_manager, monkeypatch):
    manager, _, _, _ = api_manager
    pinned = load_bundled_catalog()
    data = snapshot()
    data["higgsfield-ai/soul/v2/standard"]["schema"]["properties"]["custom_reference_strength"]["default"] = 0.75
    monkeypatch.setattr(discovery, "authenticated_snapshot", lambda client: data)
    events = []
    monkeypatch.setattr(server, "catalog_manager", lambda: manager)
    monkeypatch.setattr(server, "runtime_catalog", lambda: pinned)
    monkeypatch.setattr(server, "_prompt_server", SimpleNamespace(send_sync=lambda name, payload: events.append((name, payload))))
    result = server.refresh_models(force=True)
    assert result["restart_required"] and result["active_catalog_version"] == pinned.catalog_version
    assert server.runtime_catalog() is pinned
    assert events[0][0] == "pryx_comfyui_higgsfield.catalog_status"


def test_saving_credentials_schedules_discovery_and_cleanup_stops_periodic_thread(monkeypatch):
    routes = {}
    threads = []
    class Routes:
        def __getattr__(self, verb):
            def register(path):
                def decorate(handler):
                    routes[verb, path] = handler
                    return handler
                return decorate
            return register
    class Thread:
        def __init__(self, **kw):
            self.kw = kw
            threads.append(self)
        def start(self):
            pass
    saved = []
    refreshed = []
    class Response(dict):
        headers = None
        def __init__(self, payload, **kw):
            super().__init__(payload)
            self.headers = {}
    prompt_server = SimpleNamespace(routes=Routes(), app=SimpleNamespace(on_cleanup=[]))
    monkeypatch.setitem(sys.modules, "aiohttp", SimpleNamespace(web=SimpleNamespace(json_response=Response)))
    monkeypatch.setitem(sys.modules, "server", SimpleNamespace(PromptServer=SimpleNamespace(instance=prompt_server)))
    monkeypatch.setattr(server, "_registered", False)
    monkeypatch.setattr(server, "_prompt_server", None)
    monkeypatch.setattr(server, "Thread", Thread)
    monkeypatch.setattr(server, "credential_store", lambda: SimpleNamespace(
        save=lambda *args: saved.append(args), metadata=lambda: {"configured": True}))
    monkeypatch.setattr(server, "refresh_models", lambda **kw: refreshed.append(kw))
    server.register_routes()
    async def payload():
        return {"key_id": "test-id", "secret": "test-secret"}
    session_request = SimpleNamespace(headers={"Sec-Fetch-Site": "same-origin"})
    token = asyncio.run(routes["post", "/pryx-comfyui-higgsfield/session"](session_request))["token"]
    response = asyncio.run(routes["put", "/pryx-comfyui-higgsfield/settings"](SimpleNamespace(
        json=payload, headers={"Sec-Fetch-Site": "same-origin", "X-PRYX-Higgsfield-Token": token})))
    assert response == {"configured": True, "catalog_refresh": "scheduled"}
    assert saved == [("test-id", "test-secret")]
    threads[-1].kw["target"]()
    assert refreshed == [{"force": True}]
    stop = threads[0].kw["args"][0]
    asyncio.run(prompt_server.app.on_cleanup[0](None))
    assert stop.is_set()
