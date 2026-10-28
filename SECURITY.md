# Security

## Credential handling

The node pack resolves credentials in this order:

1. HF_KEY
2. HF_API_KEY together with HF_API_SECRET
3. The local ComfyUI user credential file

The secret is not a workflow widget, is not returned by the settings API, and
is not stored in browser storage. The local file is written atomically. POSIX
systems receive owner-only permissions; Windows keeps the file in the active
user directory and applies restrictive file attributes where the platform
permits it.

## Local settings API

All plugin routes require a per-process session token, except the POST token
bootstrap route, which requires same-origin access. Foreign and opaque origins
are rejected, including when ComfyUI runs with permissive CORS. The bootstrap
requires matching Origin or same-origin browser fetch metadata. Token-protected
requests may omit both headers for HTTP LAN and older browser compatibility,
but conflicting origin metadata is always rejected. The token stays in browser
memory, is never part of a workflow or URL, and changes when the server
restarts. Token and settings responses use `Cache-Control: no-store`.

The frontend obtains the token automatically. A rejected stale token triggers
one renewal and retry, before the handler has performed any action. Network
failures and other write errors are not retried.

This protects against cross-site configuration changes; it is not user
authentication. ComfyUI deployments accessible over a network still need
appropriate authentication and transport security. Reverse proxies must
preserve the original scheme and host as seen by ComfyUI, or use a trusted
deployment configuration that provides them correctly.

## Request safety

Catalog endpoints are relative paths and are validated against
https://api.higgsfield.ai. Advanced Request accepts a catalog model ID and
JSON arguments but cannot override the API host. Storage uploads use only
headers returned by Higgsfield and never receive the API Authorization header.

Generation POST requests are not retried after a timeout. Status GET requests
may be retried with a bounded policy. Test suites do not send generation
requests.

Inference always estimates before submission. A positive `max_usd` rejects a
missing or excessive USD estimate; it is not a guarantee about final provider
billing. Non-finite and negative provider prices are treated as unavailable.
An estimate failure never falls back to submitting a paid generation.

SOUL ID training uses a separate API lifecycle. Its default `validate_only`
action is local; `train` explicitly submits a potentially paid training without
an inference estimate or USD guard. Training POSTs are never retried, and
ambiguous responses must be checked rather than blindly resubmitted.

Catalog schemas cannot reference remote documents. Automatic updates validate
the complete inventory and schemas before atomically replacing the cache;
running workflows keep their startup catalog until ComfyUI restarts.
Discovery uses the user's credentials only against the fixed Higgsfield API
host. Runtime updates never fetch a catalog from GitHub or scrape model pages.
The cache stores public model/schema data, the successful check time, and a
SHA-256 key-ID fingerprint for invalidation, never the raw key ID or secret.
Discovery failures do not replace the working cache or submit paid operations.

## Reporting

Please report a security issue privately to the project maintainer before
opening a public issue. Do not include API keys, secrets, cookies, signed
upload URLs, private media, or complete request payloads in a report.
