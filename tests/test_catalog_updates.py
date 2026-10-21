"""October API discovery, new model controls and non-billable training checks."""

import copy
import json
from types import SimpleNamespace

import httpx
import pytest

from pryx_comfyui_higgsfield.catalog import load_bundled_catalog
from pryx_comfyui_higgsfield.catalog import discovery
from pryx_comfyui_higgsfield.catalog.catalog import CatalogManager, catalog_from_payload
from pryx_comfyui_higgsfield.client import HiggsfieldClient
from pryx_comfyui_higgsfield.credentials import Credentials
from pryx_comfyui_higgsfield.errors import APIError, CatalogError, ValidationError
from pryx_comfyui_higgsfield.model_options import validate_appearance
from pryx_comfyui_higgsfield.nodes import generation
from pryx_comfyui_higgsfield.nodes.soul_id import SoulIDNode
from pryx_comfyui_higgsfield.nodes.references import Reference, ReferenceCollection
from pryx_comfyui_higgsfield.styles import StyleManager
from pryx_comfyui_higgsfield.validation import normalize_arguments, references_to_arguments


CATALOG = load_bundled_catalog()


def test_public_inventory_paginates_without_login_or_following_remote_next(monkeypatch):
    calls = []
    def fetch(url):
        calls.append(url)
        return json.dumps({"count": 2, "next": "https://evil.invalid/" if len(calls) == 1 else None,
                           "results": [{"slug": "a/model" if len(calls) == 1 else "soul-id"}]})
    monkeypatch.setattr(discovery, "fetch_public", fetch)
    assert discovery.public_model_inventory() == {"a/model"}
    assert calls == [discovery.APP_MODELS + "?page=1&page_size=100", discovery.APP_MODELS + "?page=2&page_size=100"]


@pytest.mark.parametrize("payload", [
    {"count": 2, "results": [{"slug": "a/model"}], "next": None},
    {"count": 2, "results": [{"slug": "a/model"}, {"slug": "a/model"}], "next": None},
    {"count": 1, "results": [{"slug": "../bad"}], "next": None},
    {"count": 0, "results": [], "next": None},
])
def test_public_inventory_rejects_partial_duplicate_and_unsafe_data(monkeypatch, payload):
    monkeypatch.setattr(discovery, "fetch_public", lambda url: json.dumps(payload))
    with pytest.raises(ValueError):
        discovery.public_model_inventory()


def test_public_json_supplies_schema_and_all_family_modes(monkeypatch):
    schema = {"type": "object", "properties": {"prompt": {"type": "string"}}}
    monkeypatch.setattr(discovery, "fetch_public", lambda url: json.dumps({
        "slug": "a/model", "title": "A", "input_schema": schema,
        "operation_type": ["text2image"], "family": {"models": [{"slug": "a/model"}, {"slug": "a/edit"}]},
    }))
    family, record = discovery.inspect_family("a/model")
    assert family == {"a/model", "a/edit"}
    assert record["schema"] == schema
    with pytest.raises(ValueError, match="identity mismatch"):
        discovery.inspect_family("wrong/model")


def test_authenticated_discovery_explicitly_requests_schemas(monkeypatch):
    monkeypatch.setattr(discovery, "MIN_DISCOVERED_ENDPOINTS", 1)
    calls = []
    client = SimpleNamespace(get_json=lambda path: calls.append(path) or {
        "total": 2, "items": [{"slug": "a/model", "input_schema": {"type": "object", "properties": {}}}, {"slug": "soul-id"}],
    })
    assert set(discovery.authenticated_snapshot(client)) == {"a/model"}
    assert calls == ["/models?include_schema=true"]


def test_catalog_sync_is_idempotent_across_dates_and_model_order(monkeypatch):
    payload = CATALOG.as_payload()
    snapshot = {m.endpoint: {"slug": m.endpoint, "schema": m.input_schema, "source": m.docs_source,
                            "title": m.family, "variant_title": "", "operation_type": []}
                for m in reversed(CATALOG.models)}
    monkeypatch.setattr(discovery, "dt", SimpleNamespace(date=SimpleNamespace(today=lambda: SimpleNamespace(isoformat=lambda: "2030-01-01"))))
    assert discovery.build_catalog(snapshot, payload) is payload


def test_nullable_and_local_reference_types_keep_complete_validation():
    model = CATALOG.get("higgsfield-ai-influencer")
    assert model.parameter_map["seed"].type == "integer"
    assert model.parameter_map["seed"].nullable
    assert model.parameter_map["trait_variants"].type == "object"
    normalize_arguments(model, {"tier": "cats", "body_color": "#12aBcD"})
    with pytest.raises(ValidationError):
        normalize_arguments(model, {"trait_variants": {"version": "bad", "choices": {}}})
    with pytest.raises(ValidationError):
        normalize_arguments(model, {"tier": "normal", "body_color": "#112233"})
    with pytest.raises(ValidationError):
        normalize_arguments(model, {"tier": "cats", "pinned_species": "invalid"})


def test_remote_schema_reference_is_rejected_before_validation():
    payload = CATALOG.as_payload()
    model = next(m for m in payload["models"] if m["id"] == "higgsfield-ai-influencer")
    model["input_schema"]["$defs"]["TraitVariants"]["properties"]["bad"] = {"$ref": "https://evil.invalid/schema"}
    with pytest.raises(CatalogError, match="Remote schema"):
        catalog_from_payload(payload, source="test")


@pytest.mark.parametrize("reference", ["#/$defs/does-not-exist", "#/$defs/TraitVariants"])
def test_dangling_and_cyclic_nested_references_are_rejected(reference):
    payload = CATALOG.as_payload()
    model = next(m for m in payload["models"] if m["id"] == "higgsfield-ai-influencer")
    model["input_schema"]["$defs"]["TraitVariants"]["properties"]["bad"] = {"$ref": reference}
    with pytest.raises(CatalogError, match="Invalid local schema"):
        catalog_from_payload(payload, source="test")


@pytest.mark.parametrize("mode", ["motion-transfer", "object-swap"])
def test_genjutsu_light_ignores_stale_ui_duration_and_rejects_advanced_override(mode):
    model = CATALOG.get(f"higgsfield-genjutsu-light-{mode}-v1-0")
    assert model.parameter_map["duration"].read_only
    assert generation._arguments_for_model(model.id, {"duration": 10}) == {}
    arguments = {"video_url": "https://cdn.example/video.mp4", "image_urls": ["https://cdn.example/image.png"]}
    assert "duration" not in normalize_arguments(model, arguments)
    with pytest.raises(ValidationError, match="computed"):
        normalize_arguments(model, {**arguments, "duration": 10})
    with pytest.raises(ValidationError):
        normalize_arguments(model, {**arguments, "image_urls": ["https://cdn.example/image.png"] * 9})


def test_influencer_has_separate_identity_and_item_media_and_connected_brief():
    model = CATALOG.get("higgsfield-ai-influencer")
    inputs = generation.ImageGenerateEditNode.INPUT_TYPES()["optional"]
    assert inputs["item_images"][0] == "IMAGE"
    refs = generation._with_reference_inputs(None, image=[[1]], item_images=[[2], [3]], model_id=model.id)
    mapped = references_to_arguments(model, [{"kind": r.kind, "field": r.field, "url": f"https://cdn.example/{i}"} for i, r in enumerate(refs)])
    assert mapped == {"image_url": "https://cdn.example/0", "item_image_urls": ["https://cdn.example/1", "https://cdn.example/2"]}
    assert generation._arguments_for_model(model.id, {"prompt": "Character direction"}) == {"brief": "Character direction"}
    with pytest.raises(ValidationError):
        normalize_arguments(model, {"brief": "a" * 4001})


def test_named_style_dropdown_submits_uuid_not_display_label():
    uid = "c2143317-f28d-4c3c-a0b8-39bd547e08a7"
    assert generation._arguments_for_model("higgsfield-genjutsu-restyle-v1-0", {"preset_id": f"Anime [{uid}]"}) == {"preset_id": uid}


def test_restyle_preset_catalog_uses_authenticated_model_endpoint(tmp_path):
    calls = []
    client = SimpleNamespace(get_json=lambda path: calls.append(path) or {"items": [{"id": "uuid", "name": "Anime"}]})
    manager = StyleManager(cache_path=tmp_path / "styles.json")
    assert manager.load(client, "genjutsu-restyle") == [{"style_id": "uuid", "name": "Anime"}]
    assert manager.load(client, "genjutsu-restyle") == [{"style_id": "uuid", "name": "Anime"}]
    assert calls == ["/models/higgsfield/genjutsu/restyle/v1.0/presets"]


APPEARANCE = {"categories": [{"key": "face", "tiers": ["normal"], "max": 2, "options": [
    {"key": "a", "tiers": None, "slot": "eyes"}, {"key": "b", "tiers": None, "slot": "eyes"},
    {"key": "c", "tiers": None, "exclusive": True}, {"key": "d", "tiers": ["cats"]},
]}]}


@pytest.mark.parametrize("selection", [{"bad": ["a"]}, {"face": ["bad"]}, {"face": ["a", "b"]},
                                       {"face": ["a", "c"]}, {"face": ["d"]}, {"face": ["a", "a"]}])
def test_incompatible_appearance_is_rejected(selection):
    with pytest.raises(ValidationError):
        validate_appearance(APPEARANCE, "normal", selection)


def test_valid_appearance_and_empty_selection_are_allowed():
    validate_appearance(APPEARANCE, "normal", {"face": ["a"]})
    validate_appearance(APPEARANCE, "cats", {})


def test_soul_id_validation_makes_no_request_or_upload(monkeypatch):
    monkeypatch.setattr(HiggsfieldClient, "from_environment", lambda **kw: pytest.fail("No client for validate_only"))
    result = SoulIDNode().run("validate_only", "Character", "v2", images=[[1], [2]])
    payload = json.loads(result["result"][1])
    assert payload["status"] == "validated" and payload["image_count"] == 2
    assert result["result"][0] == ""


@pytest.mark.parametrize("refs", [[], [Reference("image")] * 101, [Reference("video")]])
def test_soul_id_invalid_training_media_stop_before_network(refs):
    with pytest.raises(ValidationError):
        SoulIDNode().run("validate_only", "Character", "v2", references=refs)


def test_soul_id_check_uses_existing_id_and_never_trains(monkeypatch):
    uid = "c2143317-f28d-4c3c-a0b8-39bd547e08a7"
    calls = []
    client = SimpleNamespace(get_json=lambda path: calls.append(path) or {"id": uid, "status": "completed"}, close=lambda: None)
    monkeypatch.setattr(HiggsfieldClient, "from_environment", lambda **kw: client)
    assert SoulIDNode().run("check", "Unused", "v2", reference_id=uid)["result"][0] == uid
    assert calls == ["/v1/custom-references/" + uid]
    with pytest.raises(ValidationError):
        SoulIDNode().run("check", "Unused", "v2", reference_id="../../bad")


def test_soul_id_train_uploads_images_in_order_and_posts_once(monkeypatch):
    from pryx_comfyui_higgsfield.nodes import soul_id
    calls = []
    client = SimpleNamespace(create_custom_reference=lambda args: calls.append(args) or {
        "id": "c2143317-f28d-4c3c-a0b8-39bd547e08a7", "status": "queued"}, close=lambda: None)
    monkeypatch.setattr(HiggsfieldClient, "from_environment", lambda **kw: client)
    monkeypatch.setattr(soul_id, "upload_reference", lambda client, ref: f"https://cdn.example/{ref.value[0]}.png")
    result = SoulIDNode().run("train", " Character ", "v2", images=[[1], [2]])
    assert json.loads(result["result"][1])["status"] == "queued"
    assert calls == [{"name": "Character", "model_version": "v2", "input_images": [
        {"type": "image_url", "image_url": "https://cdn.example/1.png"},
        {"type": "image_url", "image_url": "https://cdn.example/2.png"}]}]


def test_reference_preview_preserves_distinct_identity_and_item_roles():
    result = generation.ReferencePreviewNode().preview("higgsfield-ai-influencer", image=[[1]], item_images=[[2], [3]])
    refs = result["result"][1]
    assert [ref.field for ref in refs] == ["image_url", "item_image_urls", "item_image_urls"]


def test_training_timeout_is_ambiguous_and_not_retried():
    calls = []
    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("timeout", request=request)
    client = HiggsfieldClient(Credentials("test", "test", "test"), http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    try:
        with pytest.raises(APIError) as captured:
            client.create_custom_reference({"name": "Character"})
        assert captured.value.ambiguous_submission and not captured.value.retryable
        assert len(calls) == 1
    finally:
        client.close()


def test_provider_refresh_caches_valid_schemas_without_activating_mid_workflow(monkeypatch, tmp_path):
    from pryx_comfyui_higgsfield import credentials
    from pryx_comfyui_higgsfield.catalog import runtime_catalog
    pinned = runtime_catalog()
    monkeypatch.setattr(credentials, "resolve_credentials", lambda **kw: Credentials("test", "test", "test"))
    monkeypatch.setattr(HiggsfieldClient, "close", lambda self: None)
    snapshot = {m.endpoint: {"slug": m.endpoint, "schema": copy.deepcopy(m.input_schema), "source": m.docs_source,
                           "title": m.family, "variant_title": "", "operation_type": []} for m in CATALOG.models}
    snapshot["higgsfield-ai/soul/v2/standard"]["schema"]["properties"]["custom_reference_strength"]["default"] = 0.75
    monkeypatch.setattr(discovery, "authenticated_snapshot", lambda client: snapshot)
    manager = CatalogManager(cache_path=tmp_path / "catalog.json")
    updated = manager.refresh_available()
    assert updated.get("soul-2").parameter_map["custom_reference_strength"].default == 0.75
    assert runtime_catalog() is pinned
    assert json.loads(manager.cache_path.read_text())["models"]


def test_invalid_authenticated_inventory_falls_back_to_reviewed_catalog(monkeypatch, tmp_path):
    from pryx_comfyui_higgsfield import credentials
    monkeypatch.setattr(credentials, "resolve_credentials", lambda **kw: Credentials("test", "test", "test"))
    monkeypatch.setattr(HiggsfieldClient, "close", lambda self: None)
    def invalid(client):
        raise ValueError("Provider returned a partial inventory")
    monkeypatch.setattr(discovery, "authenticated_snapshot", invalid)
    manager = CatalogManager(cache_path=tmp_path / "catalog.json")
    calls = []
    monkeypatch.setattr(manager, "refresh", lambda: calls.append(True) or CATALOG)
    assert manager.refresh_available() is CATALOG
    assert calls == [True]
    assert not manager.cache_path.exists()


def test_older_cached_revision_does_not_override_bundled_or_metadata(tmp_path):
    manager = CatalogManager(cache_path=tmp_path / "catalog.json", auto_refresh=False)
    payload = CATALOG.as_payload()
    payload["catalog_version"] = "2020-01-01.1"
    manager._write_cache(payload)
    assert manager.load().catalog_version == CATALOG.catalog_version
    assert manager.metadata()["catalog_version"] == CATALOG.catalog_version
