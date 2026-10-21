# Changelog

## 1.1.0 — October 21, 2026

- Refreshed all model schemas against the public console and authenticated
  `GET /models?include_schema=true` inventory: 87 inference endpoints plus the
  separate SOUL ID training workflow.
- Added SOUL 2 Image to Image, AI Influencer, Ads Studio, Genjutsu Light Motion
  Transfer/Object Swap, and Genjutsu Restyle, with native media inputs and
  model-specific limits and controls.
- Added live named Restyle presets, SOUL ID character controls, and a tier-aware
  AI Influencer appearance picker. Identity and clothing/object images have
  separate roles and limits; connected prompt text maps to `brief`.
- Added a safe-by-default SOUL ID node for local validation, explicit training,
  and checking existing character IDs. Training submissions are never retried.
- Restored automatic catalog discovery: startup background refresh, authenticated
  schema API first, reviewed catalog fallback, next-restart activation, and
  downgrade protection. Daily credential-free public checks open reviewed PRs.
- Replaced the broken framework-dependent discovery path with public JSON
  inventory/schema endpoints and documentation fallbacks. Partial inventories
  fail closed and unchanged contracts do not churn catalog revisions.
- Hide provider-computed duration fields and preserve named preset UUIDs in
  saved workflows. Expanded backend/frontend contract and price-guard tests.
- Clarified unknown numeric prices, estimate failures, and the fact that
  `max_usd` limits an estimate, not final provider billing. Reject non-finite
  budgets and prices. No paid generation or training was used for verification.

## 1.0.4

- Limited file-backed VIDEO inputs to ComfyUI's input, output, and temp
  directories. Paths outside those directories, including symlinks that point
  outside them, are rejected before upload.

## 1.0.3

- Added the API-documented `1080p` option to all five Seedance 2.5 video modes
  and both Genjutsu modes. The resolution default remains `720p`.
- Corrected the Genjutsu API paths to `higgsfield/genjutsu/...` and updated
  their model IDs. Existing workflows that selected the old IDs must reselect
  the matching Genjutsu model.
- Refreshed the public model catalog against the September 27, 2026 API schemas.

## 1.0.2

- Restored model-specific controls and direct connected media inputs across the
  generator nodes.
- Clarified reference handling and model availability in the documentation.

## 1.0.0 - Unreleased

- Added the PRYX ComfyUI Higgsfield loader and Registry metadata.
- Added a validated bundled catalog for the documented image and video endpoints.
- Added local credential storage, environment-variable priority, and settings routes.
- Added estimate-first generation with a pre-submission USD estimate limit.
- Added presigned media uploads, streaming downloads, local output persistence,
  status polling, cancel handling, and progress events.
- Added image, video, reference, catalog, and advanced request nodes.
- Added Genjutsu Motion Transfer and Genjutsu Object Swap as separate Video Edit
  model choices, and kept model-specific numeric controls interactive when
  their widget type changes.
- Prepared ComfyUI Registry metadata and package artwork for the first listing.
- Added mock tests and a documentation-driven catalog sync tool.
- Expanded the public README with installation, credentials, node guides,
  reference ordering, estimate safety, outputs, catalog coverage, and
  troubleshooting.
