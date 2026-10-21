"""Inspect the public Higgsfield model pages without account credentials.

Use the public console JSON API for discovery, modes and schemas. Public model
documentation is the fallback; no login, cookies or API keys are required.
A failed extraction is an error, never a reason to publish a partial catalog.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


HOST = "https://open.higgsfield.ai"
DATA_HOST = "https://dash.higgsfield.ai"
APP_MODELS = f"{DATA_HOST}/api/v2/app-models/"
TRAINING_ENDPOINTS = {"soul-id"}  # Separate lifecycle, implemented by Soul ID nodes.
MIN_DISCOVERED_ENDPOINTS = 80  # A shrinking inventory needs manual review.
LEGACY_DOCUMENTED_ENDPOINTS = {"higgsfield-ai/soul/cinema"}
RENAMED_ENDPOINTS = {
    "higgsfield/genjutsu/motion-transfer/v1.0": "higgsfiled/genjutsu/motion-transfer/v1.0",
    "higgsfield/genjutsu/object-swap/v1.0": "higgsfiled/genjutsu/object-swap/v1.0",
}
from .catalog import validate_catalog_payload
MAX_BYTES = 3 * 1024 * 1024
MODEL_LINK = re.compile(r'/models/([a-zA-Z0-9._~/-]+)/playground')
API_ENDPOINT = re.compile(r'https://api\.higgsfield\.ai/([a-zA-Z0-9._~/-]+)')
SCHEMA_BLOCK = re.compile(r'### Input JSON Schema\s+```json\s*(\{.*?\})\s*```', re.DOTALL)


class _FlightScripts(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_script = False
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.in_script = tag == "script"

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self.in_script = False

    def handle_data(self, data: str) -> None:
        if self.in_script and "self.__next_f.push" in data:
            for match in re.finditer(r'self\.__next_f\.push\(\[1,("(?:\\.|[^"\\])*")\]\)', data):
                self.parts.append(json.loads(match.group(1)))


def fetch_public(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc not in {"open.higgsfield.ai", "dash.higgsfield.ai", "docs.higgsfield.ai"}:
        raise ValueError("Only public Higgsfield catalog/documentation hosts may be fetched")
    request = Request(url, headers={"User-Agent": "PRYX-ComfyUI-Higgsfield-Catalog-Audit/1.0"})
    with urlopen(request, timeout=30) as response:
        if urlparse(response.geturl()).netloc != parsed.netloc:
            raise ValueError("Public catalog redirected to another host")
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError(f"Public page exceeds maximum size: {url}")
    return data.decode("utf-8")


def flight_text(page: str) -> str:
    parser = _FlightScripts()
    parser.feed(page)
    if not parser.parts:
        raise ValueError("Higgsfield server-rendered model data is missing")
    return "\n".join(parser.parts)


def discover_models(page: str) -> set[str]:
    return {
        match.group(1)
        for match in MODEL_LINK.finditer(html.unescape(page))
        if not match.group(1).startswith("workflows/")
    }


def _schema_reference(schema: dict) -> dict:
    """Resolve local references for widgets; keep the original schema for validation."""
    from pryx_comfyui_higgsfield.schema import resolve_property
    return {name: resolve_property(value, schema) for name, value in schema["properties"].items()}


def _model_record(slug: str, model: dict) -> tuple[set[str], dict]:
    if model.get("slug") != slug:
        raise ValueError(f"Model identity mismatch: {slug}")
    schema = model.get("input_schema")
    if not isinstance(schema, dict) or schema.get("type") != "object" or not isinstance(schema.get("properties"), dict):
        raise ValueError(f"Invalid model input schema: {slug}")
    family = model.get("family") or {}
    variants = family.get("models", []) if isinstance(family, dict) else family
    if not isinstance(variants, list):
        raise ValueError(f"Invalid model family: {slug}")
    return {slug, *(item["slug"] for item in variants)}, {
        "slug": slug, "schema": schema,
        "source": f"{HOST}/models/{slug}/api-reference",
        "title": model.get("title") or slug,
        "variant_title": model.get("variant_title") or "",
        "operation_type": model.get("operation_type") or [],
        "output_type": model.get("output_type"),
        "provider": (model.get("company") or {}).get("name"),
        "description": model.get("description") or "",
        "availability": model.get("availability_state", "available"),
    }


def inspect_family(slug: str) -> tuple[set[str], dict]:
    try:
        model = json.loads(fetch_public(f"{APP_MODELS}{slug}/"))
    except (HTTPError, URLError, TimeoutError, OSError):
        return inspect_documentation(slug)
    return _model_record(slug, model)


def inspect_documentation(slug: str) -> tuple[set[str], dict]:
    """Plain model documentation survives frontend framework migrations."""
    try:
        text = fetch_public(f"{DATA_HOST}/models/{slug}/llms.txt")
        match = SCHEMA_BLOCK.search(text)
        if f"https://api.higgsfield.ai/{slug}`" not in text or not match:
            raise ValueError(f"Missing matching API reference or input schema: {slug}")
        schema = json.loads(match.group(1))
        title = re.search(r"^# (.+)$", text, re.MULTILINE)
        category = re.search(r"\*\*Category\*\*: (.+)", text)
        return _model_record(slug, {
            "slug": slug, "input_schema": schema, "title": title.group(1) if title else slug,
            "operation_type": category.group(1).split(", ") if category else [],
        })
    except (HTTPError, URLError, TimeoutError, OSError):
        return inspect_legacy_page(slug)


def inspect_legacy_page(slug: str) -> tuple[set[str], dict]:
    page = fetch_public(f"{HOST}/models/{slug}/api-reference")
    data = flight_text(page)
    endpoints = {match.group(1) for match in API_ENDPOINT.finditer(data)}
    schema = SCHEMA_BLOCK.search(data)
    if slug not in endpoints or not schema:
        raise ValueError(f"Missing matching API reference or input schema: {slug}")
    input_schema = json.loads(schema.group(1))
    if not isinstance(input_schema.get("properties"), dict):
        raise ValueError(f"Invalid model input schema: {slug}")
    family_start = data.find('"family":[')
    if family_start == -1:
        raise ValueError(f"Model family variants are missing: {slug}")
    variants_data, _ = json.JSONDecoder().raw_decode(data[family_start + len('"family":'):])
    variants = {item["slug"] for item in variants_data if isinstance(item, dict) and item.get("slug")}
    variants.add(slug)
    current = next((item for item in variants_data if item.get("slug") == slug), {})
    return variants, {"slug": slug, "schema": input_schema,
                      "source": f"{HOST}/models/{slug}/api-reference",
                      "title": current.get("title") or slug,
                      "variant_title": current.get("variant_title") or "",
                      "operation_type": current.get("type") or ""}


def public_model_inventory() -> set[str]:
    """Read every page, rejecting truncation and cross-host pagination."""
    slugs: set[str] = set()
    expected = None
    for page in range(1, 101):
        payload = json.loads(fetch_public(f"{APP_MODELS}?page={page}&page_size=100"))
        if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
            raise ValueError("Invalid public model inventory")
        count = payload.get("count")
        if type(count) is not int or count < 1 or (expected is not None and expected != count):
            raise ValueError("Public model inventory changed during pagination")
        expected = count
        for item in payload["results"]:
            slug = item.get("slug")
            if not isinstance(slug, str) or not re.fullmatch(r"[a-zA-Z0-9._~-]+(?:/[a-zA-Z0-9._~-]+)*", slug) or any(part in {".", ".."} for part in slug.split("/")):
                raise ValueError("Invalid public model slug")
            if slug in slugs:
                raise ValueError("Duplicate model in public inventory")
            slugs.add(slug)
        if not payload.get("next"):
            if len(slugs) != expected:
                raise ValueError("Incomplete public model inventory")
            return slugs - TRAINING_ENDPOINTS
    raise ValueError("Public model inventory exceeds page limit")


def authenticated_snapshot(client) -> dict[str, dict]:
    """The generation API can now return model modes AND their input schemas."""
    payload = client.get_json("/models?include_schema=true")
    items = payload.get("items")
    if not isinstance(items, list) or type(payload.get("total")) is not int or len(items) != payload["total"]:
        raise ValueError("Incomplete authenticated model inventory")
    result = {}
    for model in items:
        slug = model.get("slug")
        if slug in TRAINING_ENDPOINTS:
            continue
        if not isinstance(slug, str) or slug in result:
            raise ValueError("Invalid or duplicate authenticated model ID")
        _, result[slug] = _model_record(slug, model)
    if len(result) < MIN_DISCOVERED_ENDPOINTS:
        raise ValueError("Refusing a partial authenticated model inventory")
    return dict(sorted(result.items()))


def audit() -> dict[str, dict]:
    try:
        seeds = public_model_inventory()
    except (HTTPError, URLError, TimeoutError, OSError):
        with ThreadPoolExecutor(max_workers=2) as pool:
            index_pages = list(pool.map(fetch_public, (f"{HOST}/explore/image", f"{HOST}/explore/video")))
        seeds = set().union(*(discover_models(page) for page in index_pages))
        if seeds:
            # This workflow has a documented inference endpoint but no normal
            # model-card link in Explore. Do not drop it in website fallback.
            seeds.add("higgsfield/ads-studio/v1.0")
    if not seeds:
        raise ValueError("No model links found in Higgsfield explore pages")
    result: dict[str, dict] = {}
    pending = seeds
    for _ in range(3):
        pending -= result.keys()
        if not pending:
            break
        with ThreadPoolExecutor(max_workers=6) as pool:
            inspected = pool.map(inspect_family, sorted(pending))
            next_pending: set[str] = set()
            for variants, model in inspected:
                result[model["slug"]] = model
                next_pending.update(variants)
        pending = next_pending
    if pending - result.keys():
        raise ValueError(f"Variant discovery did not converge: {sorted(pending - result.keys())}")
    if len(result) < MIN_DISCOVERED_ENDPOINTS:
        raise ValueError(f"Only {len(result)} endpoints found; refusing a partial platform catalog")
    # SOUL Cinema is explicitly documented as callable despite its absence
    # from discovery. Recheck its real schema, never mark it removed on a 404.
    for slug in LEGACY_DOCUMENTED_ENDPOINTS - result.keys():
        text = fetch_public("https://docs.higgsfield.ai/docs/models/soul-cinema/generate.md")
        text = re.sub(r"^> ?", "", text, flags=re.MULTILINE)
        if f"https://api.higgsfield.ai/{slug}`" not in text:
            raise ValueError("SOUL Cinema documentation no longer confirms its endpoint")
        match = re.search(r"```json[^\n]*\n(\{.*?\})\s*```", text, re.DOTALL)
        if not match:
            raise ValueError("SOUL Cinema schema missing")
        _, result[slug] = _model_record(slug, {"slug": slug, "title": "SOUL Cinema", "operation_type": ["text2image"], "input_schema": json.loads(match.group(1))})
        result[slug]["source"] = "https://docs.higgsfield.ai/docs/models/soul-cinema/generate"
    return dict(sorted(result.items()))


def _capability(slug: str, operation: str | list[str]) -> str:
    operations = {operation} if isinstance(operation, str) else set(operation)
    if slug.endswith("/text-to-video") or "/text-to-video/" in slug:
        return "text_to_video"
    if slug.endswith("/video-extend"):
        return "video_extend"
    if slug.endswith("/reference-to-video") or slug.endswith(("/image-reference", "/video-reference")):
        return "reference_to_video"
    if "motion-control" in slug or "motion-transfer" in slug or "object-swap" in slug:
        return "video_motion"
    if slug.endswith("/image-to-video") or "/image-to-video/" in slug or slug.endswith("/first-last-frame"):
        return "image_to_video"
    if slug.startswith("higgsfield/cinema-studio/"):
        return "reference_to_video"
    if slug.endswith("/video-edit") or "video2video" in operations:
        return "video_edit"
    if operations.intersection({"text2image", "image_edit"}) or slug.startswith(("recraft/", "ideogram/", "z-image/", "marketing-studio/", "higgsfield-ai/", "alibaba/qwen-image-", "xai/grok-imagine-image-")):
        return "image_edit" if "image_edit" in operations or any(name in slug for name in ("/edit", "/image-to-image", "marketing-studio/", "grok-imagine-image")) else "image_generate"
    raise ValueError(f"No safe node capability mapping for {slug}: {operation}")


def _parameter(name: str, item: dict, required: set[str]) -> dict:
    from pryx_comfyui_higgsfield.schema import parameter_type
    parameter: dict = {"name": name, "type": parameter_type(item), "required": name in required}
    if item.get("readOnly"):
        parameter["read_only"] = True
    if isinstance(item.get("type"), list) and "null" in item["type"] or any(branch.get("type") == "null" for branch in item.get("anyOf", [])):
        parameter["nullable"] = True
    for source, target in (("default", "default"), ("enum", "choices"),
                           ("minimum", "minimum"), ("maximum", "maximum"),
                           ("minItems", "min_items"), ("maxItems", "max_items"),
                           ("minLength", "min_length"), ("maxLength", "max_length"),
                           ("multipleOf", "multiple_of")):
        if source in item and not (source == "default" and item[source] is None):
            parameter[target] = item[source]
    parameter["description"] = item.get("description") or item.get("title") or name
    if item.get("format") == "uri" or item.get("items", {}).get("format") == "uri" or name in {"image_urls", "item_image_urls", "video_urls", "audio_urls"}:
        media = next((kind for kind in ("image", "video", "audio", "file") if kind in name), "url")
        if name in {"first_frame_url", "last_frame_url"}:
            media = "image"
        parameter["media_types"] = [media]
    return parameter


def build_catalog(snapshot: dict[str, dict], bundled: dict) -> dict:
    existing = {model["endpoint"]: model for model in bundled["models"]}
    models = []
    for slug, item in snapshot.items():
        schema = item["schema"]
        properties = _schema_reference(schema)
        required = set(schema.get("required", ()))
        parameters = [_parameter(name, prop, required) for name, prop in properties.items()]
        previous = existing.pop(slug, None)
        if previous is None and slug in RENAMED_ENDPOINTS:
            previous = existing.pop(RENAMED_ENDPOINTS[slug], None)
        capability = previous["capability"] if previous else _capability(slug, item["operation_type"])
        image_output = capability in {"image_generate", "image_edit"}
        if item.get("output_type") and item["output_type"] != ("image" if image_output else "video"):
            raise ValueError(f"Model output type changed or has no supported node mapping: {slug}")
        title = schema.get("title", "").removesuffix(" Playground") or item["title"]
        display = previous["display_name"] if previous else item["title"] or title
        if not previous and item["variant_title"] and item["variant_title"].lower() not in display.lower():
            display += " · " + item["variant_title"]
        if previous and item.get("variant_title"):
            display = item["title"]
            if item["variant_title"].lower() not in display.lower():
                display += " · " + item["variant_title"]
        media = sorted({kind for parameter in parameters for kind in parameter.get("media_types", ())})
        models.append({
            "id": (previous["id"] if previous and slug not in RENAMED_ENDPOINTS
                   else re.sub(r"[^a-z0-9]+", "-", slug.lower()).strip("-")),
            "display_name": display,
            "provider": previous["provider"] if previous else item.get("provider") or slug.split("/")[0].replace("-", " ").title(),
            "family": previous["family"] if previous else item["title"],
            "endpoint": slug,
            "capability": capability,
            "output": "image" if image_output else "video",
            "parameters": parameters,
            "input_media": media,
            "max_references": None,
            "result_field": "images" if image_output else "video",
            "docs_source": item["source"],
            "docs_checked": dt.date.today().isoformat(),
            "status": "active" if item.get("availability", "available") == "available" else "unavailable",
            "notes": _notes(slug, previous),
            "input_schema": schema,
        })
    unknown_missing = set(existing) - LEGACY_DOCUMENTED_ENDPOINTS
    if unknown_missing:
        raise ValueError(f"Previously cataloged endpoints missing from platform inventory: {sorted(unknown_missing)}")
    # This endpoint remains documented separately, outside public discovery.
    models.extend(existing.values())
    def contract(model):
        return {key: value for key, value in model.items() if key != "docs_checked"}
    if {model["endpoint"]: contract(model) for model in models} == {model["endpoint"]: contract(model) for model in bundled["models"]}:
        return bundled
    today = dt.date.today().isoformat()
    old_version = bundled["catalog_version"]
    suffix = int(old_version.rsplit(".", 1)[1]) + 1 if old_version.startswith(today + ".") else 1
    payload = {"schema_version": 1, "catalog_version": f"{today}.{suffix}",
               "source_date": dt.date.today().isoformat(), "models": models}
    validate_catalog_payload(payload)
    return payload


def _notes(slug: str, previous: dict | None) -> list[str]:
    notes = list(previous.get("notes", [])) if previous else []
    additions = []
    if "/genjutsu-light/" in slug:
        additions = ["Connect one source video and 1–8 reference images. Source audio is preserved. Duration is derived from the source, rounded up to whole seconds, capped at 15 seconds; it is not an editable input."]
    elif "/genjutsu/restyle/" in slug:
        additions = ["Choose one current style preset. Source video: minimum 4 seconds, maximum download 200 MiB; longer clips are trimmed to the first 30 seconds. Optional character images: 0–5, maximum 64 MiB each. Motion and source audio are retained; framing and cadence are derived from the source/preset. No duration, FPS or audio-generation control is exposed."]
    elif slug == "higgsfield/ai-influencer":
        additions = ["Connect one identity photo to image. Connect up to three clothing/object references to item_images (batch) or References. These are separate roles; the identity photo does not count toward the three-item limit. Connected prompt text maps to brief (maximum 4000 characters).",
                     "Human tiers: normal, freak, total. Animal tiers: insects, frogs, cats, dogs, capybaras, birds. Human tiers require variation_index=0 and no body_color/pinned_species. pinned_species is only valid for insects. Appearance selection uses current category/option keys from the model options API; advanced trait overrides require valid provider identifiers."]
    elif slug == "higgsfield/ads-studio/v1.0":
        additions = ["Generate 1–8 advertising images from a brief, with up to 10 product/reference images. Optional language, niche and target audience. Token-based billing is reconciled after completion; an estimate is not a final price."]
    for note in additions:
        if note not in notes:
            notes.append(note)
    return notes


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--snapshot", type=Path, help="Write a generated audit snapshot for local validation")
    parser.add_argument("--from-snapshot", type=Path, help="Use a previously audited local snapshot")
    parser.add_argument("--catalog", type=Path, help="Generate the validated bundled catalog")
    parser.add_argument("--check", action="store_true", help="Fail if the bundled catalog has drifted")
    parser.add_argument("--authenticated", action="store_true", help="Use GET /models?include_schema=true with locally configured credentials")
    args = parser.parse_args()
    if args.from_snapshot and args.authenticated:
        parser.error("--from-snapshot and --authenticated are mutually exclusive")
    if args.authenticated:
        from ..client import HiggsfieldClient
        client = HiggsfieldClient.from_environment(timeout=30)
        try:
            result = authenticated_snapshot(client)
        finally:
            client.close()
    else:
        result = json.loads(args.from_snapshot.read_text(encoding="utf-8")) if args.from_snapshot else audit()
    if args.snapshot:
        args.snapshot.parent.mkdir(parents=True, exist_ok=True)
        args.snapshot.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if args.catalog:
        bundled = json.loads(args.catalog.read_text(encoding="utf-8"))
        payload = build_catalog(result, bundled)
        if args.check and payload != bundled:
            raise SystemExit("Catalog drift detected; regenerate and review the contract")
        if not args.check and payload != bundled:
            args.catalog.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Validated {len(payload['models'])} catalog endpoints")
    if args.summary:
        counts: dict[str, int] = {}
        for slug in result:
            counts[slug.split("/")[0]] = counts.get(slug.split("/")[0], 0) + 1
        print(json.dumps({"total": len(result), "by_provider": counts}, indent=2))
    else:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
