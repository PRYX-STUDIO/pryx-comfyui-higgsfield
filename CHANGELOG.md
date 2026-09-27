# Changelog

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
- Added estimate-first generation with a hard USD limit.
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
