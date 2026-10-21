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

## Reporting

Please report a security issue privately to the project maintainer before
opening a public issue. Do not include API keys, secrets, cookies, signed
upload URLs, private media, or complete request payloads in a report.
