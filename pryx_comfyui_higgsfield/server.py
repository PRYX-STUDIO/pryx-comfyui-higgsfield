"""Local ComfyUI routes for credentials, catalog management, and progress."""

from __future__ import annotations

from functools import lru_cache
import asyncio
from threading import Event, Thread
from typing import Any

from .catalog import CatalogManager, runtime_catalog
from .catalog.catalog import default_catalog_manager
from .credentials import CredentialStore, Credentials, default_user_directory, mask_key_id, resolve_credentials
from .errors import HiggsfieldError, redact_secrets
from .request_guard import RequestGuard
from .styles import StyleManager
from .types import ProgressEvent


_registered = False
_prompt_server: Any = None


@lru_cache(maxsize=1)
def catalog_manager() -> CatalogManager:
    return default_catalog_manager()


def catalog_status() -> dict[str, Any]:
    current = runtime_catalog()
    metadata = catalog_manager().metadata()
    return {**metadata, "active_catalog_version": current.catalog_version,
            "restart_required": metadata["catalog_version"] != current.catalog_version}


def refresh_models(*, force: bool = False) -> dict[str, Any]:
    """Refresh only the cache; never mutate schemas used by running nodes."""
    manager = catalog_manager()
    manager.refresh_available() if force else manager.load()
    status = catalog_status()
    if _prompt_server is not None:
        try:
            _prompt_server.send_sync("pryx_comfyui_higgsfield.catalog_status", status)
        except Exception:
            pass
    return status


def _catalog_refresh_loop(stop: Event) -> None:
    while not stop.wait(60 * 60):
        refresh_models()


@lru_cache(maxsize=1)
def credential_store() -> CredentialStore:
    return CredentialStore(default_user_directory() / ".pryx_comfyui_higgsfield_credentials.json")


@lru_cache(maxsize=1)
def style_manager() -> StyleManager:
    return StyleManager(cache_path=default_user_directory() / ".pryx_comfyui_higgsfield_soul_styles.json")


def register_routes() -> None:
    global _registered, _prompt_server
    if _registered:
        return
    try:
        from aiohttp import web
        from server import PromptServer
    except ImportError:
        return

    _prompt_server = getattr(PromptServer, "instance", None)
    if _prompt_server is None:
        # Offline imports may precede ComfyUI server construction. Normal node
        # loading occurs after the server instance has been initialized.
        return
    routes = _prompt_server.routes

    async def get_settings(request):
        return web.json_response(credential_store().metadata())

    async def put_settings(request):
        try:
            data = await request.json()
            key_id = data.get("key_id")
            secret = data.get("secret")
            credential_store().save(key_id, secret)
            # Saving a key is fast even if discovery is offline. A websocket
            # event updates the persistent model status when discovery ends.
            Thread(target=lambda: refresh_models(force=True), name="higgsfield-key-discovery", daemon=True).start()
            return web.json_response({**credential_store().metadata(), "catalog_refresh": "scheduled"})
        except (HiggsfieldError, AttributeError, TypeError, ValueError) as error:
            return web.json_response({"error": redact_secrets(str(error))}, status=400)

    async def delete_settings(request):
        try:
            credential_store().delete()
            return web.json_response({"configured": False, "source": "none", "key_id": None})
        except HiggsfieldError as error:
            return web.json_response({"error": redact_secrets(str(error))}, status=400)

    async def validate_settings(request):
        try:
            data = await request.json()
        except Exception:
            data = {}
        try:
            credentials = _credentials_from_request(data)
            from .catalog import load_bundled_catalog
            from .client import HiggsfieldClient

            model = load_bundled_catalog().get("soul-2")
            client = HiggsfieldClient(credentials, timeout=60)
            try:
                estimate = client.validate_credentials(model)
            finally:
                client.close()
            return web.json_response(
                {
                    "valid": True,
                    "key_id": mask_key_id(credentials.key_id),
                    "credits": estimate.credits,
                    "usd": estimate.usd,
                }
            )
        except HiggsfieldError as error:
            return web.json_response({"valid": False, "error": redact_secrets(str(error))}, status=400)

    async def get_catalog(request):
        try:
            catalog = runtime_catalog()
            return web.json_response(
                {
                    "schema_version": 1,
                    "catalog_version": catalog.catalog_version,
                    "source_date": catalog.source_date,
                    "source": catalog.source,
                    "last_sync_status": catalog_manager().last_sync_status,
                    "models": catalog.as_payload()["models"],
                    "available_catalog_version": catalog_manager().metadata()["catalog_version"],
                    "update_status": catalog_status(),
                }
            )
        except HiggsfieldError as error:
            return web.json_response({"error": redact_secrets(str(error))}, status=503)

    async def refresh_catalog(request):
        try:
            return web.json_response(await asyncio.to_thread(refresh_models, force=True))
        except HiggsfieldError as error:
            return web.json_response({"error": redact_secrets(str(error))}, status=502)

    async def get_styles(request):
        variant = request.query.get("variant", "soul-2")
        refresh = request.query.get("refresh", "false").lower() == "true"
        try:
            credentials = resolve_credentials(credential_store())
            from .client import HiggsfieldClient

            client = HiggsfieldClient(credentials, timeout=60)
            try:
                styles = await asyncio.to_thread(style_manager().load, client, variant, refresh=refresh)
            finally:
                client.close()
            return web.json_response({"variant": variant, "styles": styles})
        except HiggsfieldError as error:
            return web.json_response({"error": redact_secrets(str(error))}, status=400)

    async def get_appearance_options(request):
        try:
            from .client import HiggsfieldClient
            from .model_options import INFLUENCER_OPTIONS
            client = HiggsfieldClient(resolve_credentials(credential_store()), timeout=30)
            try:
                payload = await asyncio.to_thread(client.get_json, INFLUENCER_OPTIONS)
            finally:
                client.close()
            return web.json_response(dict(payload))
        except HiggsfieldError as error:
            return web.json_response({"error": redact_secrets(str(error))}, status=400)

    guard = RequestGuard()
    routes.post("/pryx-comfyui-higgsfield/session")(guard.session)
    routes.get("/pryx-comfyui-higgsfield/settings")(guard.protect(get_settings))
    routes.put("/pryx-comfyui-higgsfield/settings")(guard.protect(put_settings))
    routes.delete("/pryx-comfyui-higgsfield/settings")(guard.protect(delete_settings))
    routes.post("/pryx-comfyui-higgsfield/settings/validate")(guard.protect(validate_settings))
    routes.get("/pryx-comfyui-higgsfield/catalog")(guard.protect(get_catalog))
    routes.post("/pryx-comfyui-higgsfield/catalog/refresh")(guard.protect(refresh_catalog))
    routes.get("/pryx-comfyui-higgsfield/styles")(guard.protect(get_styles))
    routes.get("/pryx-comfyui-higgsfield/appearance-options")(guard.protect(get_appearance_options))
    _registered = True
    # Startup discovery already ran before INPUT_TYPES were constructed.
    # Long-lived servers also check hourly; successful API responses have a
    # 24-hour TTL. A later update remains pending until a safe restart.
    stop = Event()
    Thread(target=_catalog_refresh_loop, args=(stop,), name="higgsfield-model-updates", daemon=True).start()
    async def stop_catalog_updates(app):
        stop.set()
    if getattr(_prompt_server, "app", None) is not None:
        _prompt_server.app.on_cleanup.append(stop_catalog_updates)


def _credentials_from_request(data: Any) -> Credentials:
    if isinstance(data, dict) and data.get("key_id") and data.get("secret"):
        return Credentials(str(data["key_id"]), str(data["secret"]), "settings:validation")
    return resolve_credentials(credential_store())


def emit_progress(event: ProgressEvent | dict[str, Any]) -> None:
    """Send a non-secret progress event to the active ComfyUI websocket."""

    if _prompt_server is None:
        return
    payload = event.as_dict() if isinstance(event, ProgressEvent) else dict(event)
    try:
        _prompt_server.send_sync("pryx_comfyui_higgsfield.progress", payload)
    except Exception:
        # Progress is auxiliary. A websocket incompatibility must not fail a
        # generation that is otherwise running correctly.
        return
