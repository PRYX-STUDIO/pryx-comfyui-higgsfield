# Automatic model updates

Normal Higgsfield model updates do not require a PRYX release. The installed
pack queries the official API using the key configured in ComfyUI. GitHub is
used to distribute code, not to deliver users' day-to-day model definitions.

## User lifecycle

1. **Install and start.** Without a key, the validated bundled snapshot provides
   model definitions. No paid operation or discovery request is made.
2. **Save the key.** ComfyUI stores it locally and schedules a discovery check.
   The credentials dialog closes immediately; slow discovery does not prevent
   saving. Existing models can use the key immediately.
3. **Check for new definitions.** Discovery calls authenticated
   `GET /models?include_schema=true`. Complete input schemas are required.
   Some models also have dedicated metadata routes, such as Restyle presets
   and AI Influencer appearance options.
4. **Activate safely.** If discovery runs at startup, its definitions are used
   before the nodes' `INPUT_TYPES` are constructed. If a change arrives during
   a session, it is cached and the user is asked to restart ComfyUI and reload
   the browser. Existing node definitions are never replaced mid-execution.
5. **Keep checking.** Successful discovery is cached for 24 hours. An hourly
   background check refreshes stale data while ComfyUI remains open. Saving a
   key or selecting **Check models now** forces a check without waiting for TTL.

The Settings entry **PRYX ComfyUI Higgsfield → Automatic model updates** shows
discovery status and pending activation. Model checking does not estimate,
upload references, generate media, or train a SOUL ID.

## Fallback and safety

- API discovery uses one attempt with eight-second HTTP timeouts. It does not
  automatically retry multiple requests during startup.
- Every candidate is checked for a complete inventory, safe endpoint paths,
  supported tasks/outputs, and valid request schemas before atomic persistence.
- Failed checks leave the previous file unchanged. With no valid local cache,
  the bundled definitions remain available; later automatic checks retry.
- A model omitted from a complete API inventory becomes unavailable in the
  next session; its ID is retained for diagnostics and it can reappear later.
  This does not block updates to the remaining models. The separately
  documented SOUL Cinema exception is retained, not disabled by discovery alone.
- The cache contains no credential. A SHA-256 key-ID fingerprint identifies
  whether a successful check belongs to the currently configured key. A new
  key forces discovery. Deleting credentials stops authenticated discovery.
- A newer bundled snapshot cannot be replaced by an older cache.
- Runtime refresh never contacts GitHub or reads website HTML. It does not
  require GitHub Actions permissions or a maintainer to merge model updates.

## What still needs a plugin update?

Compatible new image/video models, new choices, limits, defaults, and ordinary
parameters can be represented dynamically. Entirely new task/output types,
new media roles, or API protocol changes still need implementation and tests.
Unsafe or incompatible inventories are rejected rather than partially activated.

The provider inventory is not assumed to be perfect: SOUL Cinema is a known,
separately documented inference endpoint absent from general discovery. Its
reviewed definition is retained. SOUL ID training is a separate lifecycle and
node; it is not sent through the inference endpoint/estimate flow.

## Maintainer audit

For a larger code update, a maintainer can refresh the bundled fallback:

```powershell
python tools/sync_platform_catalog.py --catalog pryx_comfyui_higgsfield/catalog/models.json --check --summary
```

Omit `--check` to write a candidate for review. Add `--authenticated` to query
the generation API using configured local credentials instead of the public
console inventory. The public console audit needs no login or cookies.

The **Catalog audit (manual)** GitHub Action runs only on manual dispatch. It
audits the public schemas, runs Python/frontend tests, and uploads a candidate
snapshot as an artifact. It has read-only repository permissions, creates no
commits or pull requests, and does not alter installed users' models.

After changing the updater, test first install, key saving/changing, TTL expiry,
offline fallback, a newly discovered model and parameter, and pending-restart
notifications. Use mocked requests or read-only discovery; paid generation and
training require separate explicit approval.
