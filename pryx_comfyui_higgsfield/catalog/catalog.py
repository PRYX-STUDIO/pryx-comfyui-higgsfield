"""Catalog loading, validation, filtering, and offline-safe refresh."""

from __future__ import annotations

import json
import hashlib
import os
import tempfile
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping
from threading import RLock
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from urllib.parse import urlsplit

from ..credentials import default_user_directory
from ..errors import CatalogError
from ..types import API_BASE_URL, CATALOG_SCHEMA_VERSION, Capability, ModelSpec, ModelStatus


REFRESH_INTERVAL_SECONDS = 24 * 60 * 60
DISCOVERY_TIMEOUT_SECONDS = 8


class Catalog:
    def __init__(
        self,
        models: Iterable[ModelSpec],
        *,
        catalog_version: str,
        source_date: str,
        source: str = "bundled",
    ) -> None:
        self.models = tuple(models)
        self.catalog_version = catalog_version
        self.source_date = source_date
        self.source = source
        self._by_id = {model.id: model for model in self.models}

    def get(self, model_id: str) -> ModelSpec:
        try:
            return self._by_id[model_id]
        except KeyError as error:
            raise CatalogError(f"Unknown Higgsfield model ID: {model_id}") from error

    def filter(
        self,
        *,
        provider: str | None = None,
        capability: Capability | str | None = None,
        status: ModelStatus | str | None = ModelStatus.ACTIVE,
    ) -> tuple[ModelSpec, ...]:
        capability_value = capability.value if isinstance(capability, Capability) else capability
        status_value = status.value if isinstance(status, ModelStatus) else status
        return tuple(
            model
            for model in self.models
            if (not provider or provider == "all" or model.provider == provider)
            and (
                not capability_value
                or capability_value == "all"
                or model.capability.value == capability_value
            )
            and (
                not status_value
                or status_value == "all"
                or model.status.value == status_value
            )
        )

    def as_payload(self) -> dict[str, Any]:
        return {
            "schema_version": CATALOG_SCHEMA_VERSION,
            "catalog_version": self.catalog_version,
            "source_date": self.source_date,
            "models": [model.as_dict() for model in self.models],
        }


def load_bundled_catalog() -> Catalog:
    path = Path(__file__).with_name("models.json")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise CatalogError("The bundled Higgsfield catalog could not be read.") from error
    return catalog_from_payload(payload, source="bundled")


def catalog_from_payload(payload: Mapping[str, Any], *, source: str) -> Catalog:
    validate_catalog_payload(payload)
    return Catalog(
        [ModelSpec.from_dict(item) for item in payload["models"]],
        catalog_version=str(payload["catalog_version"]),
        source_date=str(payload["source_date"]),
        source=source,
    )


def catalog_version(catalog: Catalog) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in catalog.catalog_version.replace("-", ".").split("."))
    except ValueError:
        return (0,)


@lru_cache(maxsize=1)
def runtime_catalog() -> Catalog:
    """One immutable schema for frontend, node definitions, and requests per process."""
    # Discover before ComfyUI builds INPUT_TYPES, not one restart after that.
    return default_catalog_manager().load()


@lru_cache(maxsize=1)
def default_catalog_manager() -> CatalogManager:
    return CatalogManager()


def validate_catalog_payload(payload: Mapping[str, Any]) -> None:
    if not isinstance(payload, Mapping):
        raise CatalogError("The Higgsfield catalog must be a JSON object.")
    if payload.get("schema_version") != CATALOG_SCHEMA_VERSION:
        raise CatalogError(
            f"Unsupported catalog schema version: {payload.get('schema_version')}"
        )
    for key in ("catalog_version", "source_date", "models"):
        if key not in payload:
            raise CatalogError(f"Catalog field is missing: {key}")
    if not isinstance(payload["models"], list) or not payload["models"]:
        raise CatalogError("The Higgsfield catalog contains no models.")

    ids: set[str] = set()
    for model in payload["models"]:
        if not isinstance(model, Mapping):
            raise CatalogError("Every catalog model must be an object.")
        required = (
            "id",
            "display_name",
            "provider",
            "family",
            "endpoint",
            "capability",
            "output",
            "parameters",
            "docs_source",
            "docs_checked",
            "status",
        )
        missing = [key for key in required if key not in model]
        if missing:
            raise CatalogError(f"Catalog model is missing fields: {', '.join(missing)}")
        model_id = model["id"]
        if not isinstance(model_id, str) or not model_id or model_id in ids:
            raise CatalogError(f"Catalog model IDs must be unique: {model_id}")
        ids.add(model_id)
        _validate_endpoint(model["endpoint"])
        try:
            Capability(str(model["capability"]))
            ModelStatus(str(model["status"]))
            output = str(model["output"])
            if output not in {"image", "video"}:
                raise ValueError(output)
            expected_output = "image" if model["capability"] in {"image_generate", "image_edit"} else "video"
            if output != expected_output:
                raise ValueError(f"{model['capability']} cannot produce {output}")
        except ValueError as error:
            raise CatalogError(f"Unsupported catalog enum in {model_id}.") from error
        parameters = model["parameters"]
        if not isinstance(parameters, list):
            raise CatalogError(f"Parameters must be a list: {model_id}")
        parameter_names: set[str] = set()
        for parameter in parameters:
            if not isinstance(parameter, Mapping) or not parameter.get("name") or not parameter.get("type"):
                raise CatalogError(f"Invalid parameter in catalog model: {model_id}")
            name = str(parameter["name"])
            if name in parameter_names:
                raise CatalogError(f"Duplicate parameter {name} in {model_id}.")
            parameter_names.add(name)
            for key in ("minimum", "maximum", "min_items", "max_items", "min_length", "max_length", "multiple_of"):
                if key in parameter and not isinstance(parameter[key], (int, float)):
                    raise CatalogError(f"Invalid {key} in {model_id}.{name}.")
        docs_source = str(model["docs_source"])
        if not docs_source.startswith(("https://docs.higgsfield.ai/", "https://open.higgsfield.ai/models/")):
            raise CatalogError(f"Catalog docs source is not official: {model_id}")
        input_schema = model.get("input_schema")
        if input_schema is not None:
            if not isinstance(input_schema, Mapping) or input_schema.get("type") != "object":
                raise CatalogError(f"Invalid input schema: {model_id}")
            if set(input_schema.get("properties", {})) != parameter_names:
                raise CatalogError(f"Input schema and parameters disagree: {model_id}")
            def reject_remote_refs(value):
                if isinstance(value, Mapping):
                    if "$dynamicRef" in value or "$id" in value or (
                        "$ref" in value and (not isinstance(value["$ref"], str) or not value["$ref"].startswith("#/"))
                    ):
                        raise CatalogError(f"Remote schema references are forbidden: {model_id}")
                    for child in value.values():
                        reject_remote_refs(child)
                elif isinstance(value, list):
                    for child in value:
                        reject_remote_refs(child)
            reject_remote_refs(input_schema)
            from ..schema import resolve_property, validate_local_references
            try:
                validate_local_references(input_schema)
                for prop in input_schema.get("properties", {}).values():
                    resolve_property(prop, input_schema)
            except (ValueError, KeyError, TypeError, IndexError, RecursionError) as error:
                raise CatalogError(f"Invalid local schema reference in {model_id}.") from error
            try:
                Draft202012Validator.check_schema(input_schema)
            except SchemaError as error:
                raise CatalogError(f"Invalid JSON Schema in {model_id}.") from error


def _validate_endpoint(endpoint: Any) -> None:
    if not isinstance(endpoint, str) or not endpoint:
        raise CatalogError("Catalog endpoints must be non-empty strings.")
    if "://" in endpoint or any(value in endpoint for value in ("?", "#", "..")) or chr(92) in endpoint:
        raise CatalogError(f"Catalog endpoint is not a relative API path: {endpoint}")
    if not endpoint.startswith("/") and endpoint.startswith("http"):
        raise CatalogError(f"Catalog endpoint is not allowed: {endpoint}")
    url = urlsplit(f"{API_BASE_URL}/{endpoint.lstrip('/')}")
    if url.scheme != "https" or url.netloc != urlsplit(API_BASE_URL).netloc:
        raise CatalogError(f"Catalog endpoint host is not allowed: {endpoint}")
    if not all(part and all(char.isalnum() or char in "-._~" for char in part) for part in endpoint.split("/")):
        raise CatalogError(f"Catalog endpoint contains unsafe characters: {endpoint}")


class CatalogManager:
    def __init__(
        self,
        *,
        cache_path: str | os.PathLike[str] | None = None,
        auto_refresh: bool = True,
        clock: callable = time.time,
    ) -> None:
        self.cache_path = Path(cache_path) if cache_path else default_user_directory() / ".pryx_comfyui_higgsfield_catalog.json"
        self.auto_refresh = auto_refresh
        self._clock = clock
        self._lock = RLock()
        self.last_sync_status = "bundled"
        self.last_sync_message = "Using the bundled models until API discovery is configured."

    def load(self) -> Catalog:
        return self._refresh(force=False) if self.auto_refresh else self._best_local()

    def refresh_available(self) -> Catalog:
        """Fetch official schemas; failures retain local data without any GitHub request."""
        return self._refresh(force=True)

    def _best_local(self) -> Catalog:
        bundled = load_bundled_catalog()
        cached = self._read_cache()
        return cached if cached and catalog_version(cached) >= catalog_version(bundled) else bundled

    def _refresh(self, *, force: bool) -> Catalog:
        from ..client import HiggsfieldClient
        from ..credentials import resolve_credentials
        from ..errors import HiggsfieldError
        from .discovery import authenticated_snapshot, build_catalog
        with self._lock:
            base = self._best_local()
            try:
                credentials = resolve_credentials(allow_missing=True)
                if credentials is None:
                    self.last_sync_status = "not-configured"
                    self.last_sync_message = "Save a Higgsfield API key to load current models automatically."
                    return base
                # The hash identifies the account/key without storing a key ID
                # or secret in the model cache. A changed key forces discovery.
                fingerprint = hashlib.sha256(credentials.key_id.encode("utf-8")).hexdigest()
                if not force and self._cache_is_fresh(fingerprint):
                    self.last_sync_status = "higgsfield-api:cached"
                    self.last_sync_message = "Official API models checked within the last 24 hours."
                    return base
                client = HiggsfieldClient(credentials, timeout=DISCOVERY_TIMEOUT_SECONDS)
                try:
                    snapshot = authenticated_snapshot(client)
                finally:
                    client.close()
                payload = build_catalog(snapshot, base.as_payload(), allow_missing=True)
                catalog = catalog_from_payload(payload, source="higgsfield-api")
                payload = {**payload, "provider_sync": {"key_fingerprint": fingerprint, "checked_at": self._clock()}}
                self._write_cache(payload)
                self.last_sync_status = "higgsfield-api:updated"
                self.last_sync_message = "Current models loaded directly from the Higgsfield API."
                return catalog
            except (HiggsfieldError, ValueError, KeyError, TypeError, AttributeError, IndexError, RecursionError, OSError):
                self.last_sync_status = "higgsfield-api:failed"
                self.last_sync_message = "API discovery failed or returned incompatible data. Keeping the last working models; automatic checks will retry."
                return base

    def metadata(self) -> dict[str, Any]:
        catalog = self._read_cache()
        bundled = load_bundled_catalog()
        if catalog and catalog_version(catalog) < catalog_version(bundled):
            catalog = None
        return {
            "catalog_version": catalog.catalog_version if catalog else bundled.catalog_version,
            "source_date": catalog.source_date if catalog else bundled.source_date,
            "source": catalog.source if catalog else "bundled",
            "last_sync_status": self.last_sync_status,
            "message": self.last_sync_message,
            "cache_path": str(self.cache_path),
        }

    def _read_cache(self) -> Catalog | None:
        if not self.cache_path.exists():
            return None
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
            return catalog_from_payload(payload, source="cache")
        except (OSError, ValueError, TypeError, KeyError, AttributeError, CatalogError):
            return None

    def _cache_is_fresh(self, fingerprint: str) -> bool:
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
            sync = payload.get("provider_sync", {})
            return (sync.get("key_fingerprint") == fingerprint
                    and 0 <= self._clock() - float(sync["checked_at"]) < REFRESH_INTERVAL_SECONDS
                    and catalog_version(catalog_from_payload(payload, source="cache")) >= catalog_version(load_bundled_catalog()))
        except (OSError, ValueError, KeyError, TypeError, AttributeError, CatalogError):
            return False

    def _write_cache(self, payload: Mapping[str, Any]) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=f"{self.cache_path.name}.",
                suffix=".tmp",
                dir=self.cache_path.parent,
                delete=False,
            ) as handle:
                temporary = handle.name
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.cache_path)
        except OSError as error:
            if temporary:
                try:
                    Path(temporary).unlink(missing_ok=True)
                except OSError:
                    pass
            raise CatalogError("The validated catalog could not be cached.") from error
