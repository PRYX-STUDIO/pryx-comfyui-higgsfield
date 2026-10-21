# PRYX ComfyUI Higgsfield

[![Tests](https://github.com/PRYX-STUDIO/pryx-comfyui-higgsfield/actions/workflows/tests.yml/badge.svg)](https://github.com/PRYX-STUDIO/pryx-comfyui-higgsfield/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![ComfyUI](https://img.shields.io/badge/ComfyUI-%E2%89%A50.35.0-4f46e5)](https://github.com/comfyanonymous/ComfyUI)

Generate and edit images and videos with Higgsfield from ComfyUI, using
model-specific controls, connected media references, and estimate-first cost
checks.

PRYX ComfyUI Higgsfield lets you call the documented Higgsfield image and video
endpoints from normal ComfyUI workflows. Model-specific controls, choices,
limits, and tooltips come from the bundled catalog, so a node only exposes the
parameters supported by its selected model.

The ComfyUI backend sends requests directly to `api.higgsfield.ai`. PRYX does
not operate a proxy and does not receive your API credentials or generated
media.

> **Important:** This node pack accesses paid API services. New generator nodes
> start in `estimate_only` mode so you can inspect the provider's estimate
> before allowing a generation request.

## Contents

- [Requirements](#requirements)
- [Installation](#installation)
- [Credentials](#credentials)
- [Quick start](#quick-start)
- [Nodes](#nodes)
- [Working with references](#working-with-references)
- [Estimate Only, pricing, and generation safety](#estimate-only-pricing-and-generation-safety)
- [Model catalog](#model-catalog)
- [Outputs](#outputs)
- [Troubleshooting](#troubleshooting)
- [Development](#development)
- [Privacy, security, and license](#privacy-security-and-license)

## Requirements

- ComfyUI `0.35.0` or newer
- ComfyUI frontend `1.53.6` or newer
- Python `3.10` through `3.13`
- A Higgsfield API account with an API key ID and secret

The package includes the official `higgsfield-client` dependency and uses its
own `httpx` request wrapper for estimates, uploads, polling, and downloads.
ComfyUI normally already provides the media libraries needed by its
native `IMAGE`, `VIDEO`, and `AUDIO` types.

## Installation

### ComfyUI Manager

After the package is available in the ComfyUI Registry, search for
**PRYX ComfyUI Higgsfield** in ComfyUI Manager, install it, and restart ComfyUI.

### Git installation

Clone the repository into `ComfyUI/custom_nodes` and install its Python
dependencies with the same Python environment that runs ComfyUI:

```powershell
cd ComfyUI/custom_nodes
git clone https://github.com/PRYX-STUDIO/pryx-comfyui-higgsfield.git pryx-comfyui-higgsfield
python -m pip install -r .\pryx-comfyui-higgsfield\requirements.txt
```

For the Windows portable ComfyUI distribution, use its bundled interpreter
instead:

```powershell
..\python_embeded\python.exe -m pip install -r .\pryx-comfyui-higgsfield\requirements.txt
```

Restart ComfyUI after installation. When updating an existing checkout, pull
the changes and restart ComfyUI; reload the browser with `Ctrl+F5` so the
frontend extension is reloaded as well.

## Credentials

Open **ComfyUI Settings → PRYX ComfyUI Higgsfield → Credentials** and enter:

- **Higgsfield API key** — paste the complete value Higgsfield shows when you
  create the key, in `key-id:key-secret` format. ComfyUI splits it at the first
  colon before storing the two parts separately.

The key name shown in the Higgsfield console is only a label; it is not part of
the credential. If you no longer have the secret, create a new key and copy its
complete value. Never put the key in a workflow or issue report.

The **Validate estimate** button checks the credentials with an estimate
request. It does not submit a paid generation. **Save locally** stores the
credentials in the active ComfyUI user directory. The secret is cleared from
the form after saving and never becomes a workflow input or browser-storage
value.

For headless installations, use one of these supported configurations:

```text
HF_KEY=key-id:key-secret
```

or:

```text
HF_API_KEY=key-id
HF_API_SECRET=key-secret
```

Environment variables take precedence over the local ComfyUI credential file.
See [SECURITY.md](SECURITY.md) for the credential and request-safety details.

## Quick start

1. Install the node pack and configure the credentials.
2. Add a generator from **PRYX → Higgsfield**.
3. Choose a model from the model dropdown. The available controls update to
   match that model.
4. Connect a prompt. The prompt input accepts a normal text connection, so a
   Config UI Prompt node can be used for long prompts.
5. Leave **request_mode** at `estimate_only` and queue the workflow.
6. Read the `credits`, `usd`, and `status` outputs.
7. If the estimate is acceptable, switch **request_mode** to `generate`, optionally set
   a positive **max_usd** limit, and queue the workflow again.
8. Connect `video` or `images` to the corresponding native ComfyUI output/save
   node. Video results can be connected to a compatible Save Video node.

For an image-to-video workflow, connect a native `IMAGE` output such as
`Load Image` to the generator's `image` input. For a multimodal workflow, use
one Reference Collector and connect its `references` output to the generator.
Reference Preview can be placed between the inputs and generator while
building the workflow.

## Nodes

All nodes are available under **PRYX/ComfyUI/Higgsfield**. Generator nodes have a
model dropdown, a collapsed model-information panel, and dynamic controls.
Expand the information panel to see the selected model's supported media,
limits, output settings, and reference guidance.

### PRYX ComfyUI Higgsfield Model Catalog

Use this node when you want to choose a model once and reuse it in one or more
generator nodes.

**Inputs**

- `model_id` — catalog model dropdown
- `provider` — filter the catalog by provider
- `capability` — filter by task, such as `image_to_video`
- `status` — show active, deprecated, unavailable, or all entries

**Outputs**

- `model_id` — connect this `STRING` output to a generator's `model` input
- `model_info` — JSON with the selected model, supported media, limits, and
  catalog metadata

The catalog node is optional. Every generator also has its own validated model
dropdown. The catalog is useful for central selection, filtering, or sharing a
model choice between nodes.

### PRYX ComfyUI Higgsfield Reference Collector

Collect several local images, videos, or audio inputs into one ordered
`references` value. One Collector is enough; chaining multiple Collectors is
not required.

**Inputs**

- `image`, `image_2`, … — up to 30 image slots; image batches keep their order
- `video`, `video_2`, … — up to 10 video slots
- `audio`, `audio_2`, … — up to 10 audio slots
- `references` — merge an existing collection when needed
- `names` — optional labels, one per line, for example:
  `image_1=person` and `image_2=outfit`
- `external_url` — an already public HTTPS URL for a document or web page
- `external_type` — `url` or `file`

The frontend adds additional media sockets as they are connected. Sockets are
collected in numeric order, not by the order in which wires were drawn. Model
limits are checked later by the selected generator.

Connected local media does not need to be hosted manually. The backend
converts it to a supported format and uploads it through Higgsfield's
presigned upload flow. `external_url` is different: it remains an external
URL and must already be publicly reachable by the provider.

### PRYX ComfyUI Higgsfield Reference Preview

Inspect the final reference order and prompt mapping before running a
generator. This node performs no media upload and makes no Higgsfield API
request.

**Outputs**

- `prompt` — the prompt passed through the preview
- `references` — the ordered collection passed through the preview
- `model` — the selected model ID
- `reference_info` — readable mapping and resolved prompt text

Run the preview after changing media, labels, or the model. Its text output
shows which media item becomes `Image 1`, `Video 1`, and so on.

### PRYX ComfyUI Higgsfield Image Generate & Edit

Generate images or edit images with the catalog's image endpoints. The model
dropdown covers SOUL, Recraft, Marketing Studio, Ads Studio, AI Influencer,
and the other catalog image endpoints. Connect an `IMAGE` input when the
selected edit model supports source images. The visible parameter widgets
change with the selected model.

**AI Influencer:** connect the identity photo to `image`. Clothing/object
references go to `item_images` (an image batch) or the Reference Collector,
with a separate limit of three item images. Connected `prompt` text is sent
as `brief`, with a 4000-character limit. The collapsed appearance picker loads
the current category and option names from Higgsfield; its choices depend on
`tier`. Counts, exclusive choices, and facial slots are checked before upload.
Human tiers hide animal-only controls. `pinned_species` and `trait_variants`
are advanced overrides: normally leave them blank, because the appearance
catalog does not expose all valid identifiers for those fields.

**Ads Studio:** accepts up to ten product/reference images and generates one
to eight images. Its token-based bill is reconciled after completion, so the
estimate is not a guaranteed final charge.

**Outputs:** `images`, `image_urls`, `request_id`, `credits`, `usd`, `status`

### PRYX ComfyUI Higgsfield SOUL ID

Create a reusable SOUL character from one to 100 connected images. This is a
training workflow, not an image-generation endpoint.

- `validate_only` is the default. It checks the name, model version and image
  count locally, without uploads or API requests.
- `train` uploads the images and submits one training request. Training may
  cost money; the inference `estimate_only` and `max_usd` controls do not apply.
  The node returns immediately with the character ID and current status.
- `check` reads the status of an existing `reference_id`. Queue this action
  again to check progress; do not start another training to poll.

Choose `v1`, `v2`, or `cinema` to match the SOUL model that will use the character.
Once training is `completed`, connect `custom_reference_id` to that model's
input with the same name. Where supported, `custom_reference_strength` adjusts
its influence. Keep the ID after training: a fresh execution of `train` can
create another paid training, for example after restarting ComfyUI.

**Outputs:** `custom_reference_id`, `status` (JSON text)

### PRYX ComfyUI Higgsfield Text to Video

Generate a video from a text prompt. The node exposes the controls supported by
the selected text-to-video model, such as resolution, aspect ratio, duration,
audio, sound, multi-shot settings, or a seed. If the selected model accepts an
audio reference, the node also shows direct `AUDIO` and ordered `references`
inputs.

**Outputs:** `video`, `local_file`, `remote_url`, `request_id`, `credits`, `usd`,
`status`

### PRYX ComfyUI Higgsfield Image to Video

Animate a starting image. Connect one native `IMAGE` to `image`; models that
support an ending frame expose the optional `end_image` input. Models that
accept audio or additional references show the matching direct socket and the
ordered `references` input. The node only lists catalog models documented for
the Higgsfield image-to-video capability.

**Outputs:** `video`, `local_file`, `remote_url`, `request_id`, `credits`, `usd`,
`status`

### PRYX ComfyUI Higgsfield Reference to Video

Generate a video from ordered multimodal references. Depending on the selected
model, references may include images, videos, audio, documents, or web links.
Connect direct media inputs for simple workflows, or use a Reference Collector
for several inputs.

**Outputs:** `video`, `local_file`, `remote_url`, `request_id`, `credits`, `usd`,
`status`

### PRYX ComfyUI Higgsfield Video Edit

Edit an existing video with a prompt and the controls supported by the active
catalog model. The model dropdown includes Genjutsu Motion Transfer and
Object Swap, their Light variants, and Genjutsu Restyle as separate modes,
alongside the other documented video edit models. Connect the source video to
`video`; optional model-supported
image or audio inputs appear when supported, and additional references can be
supplied through `references`.

**Genjutsu Light:** one source video and one to eight images. Duration is
computed by Higgsfield from the source, rounded up and capped at 15 seconds;
there is no editable duration control. The model info panel explains this.

**Genjutsu Restyle:** choose a named preset from the live preset dropdown and
connect a source video. The source must be at least four seconds; longer clips
are trimmed to the first 30 seconds. Up to five optional character images are
supported. Motion and source audio are retained. The API exposes no duration,
FPS, or generated-audio control for this mode.

**Outputs:** `video`, `local_file`, `remote_url`, `request_id`, `credits`, `usd`,
`status`

### PRYX ComfyUI Higgsfield Video Extend

Extend an existing video. Connect the source clip to `video` and set the
model-supported duration and output options. Additional direct image/audio
inputs and the ordered `references` input appear when the selected model accepts
them.

**Outputs:** `video`, `local_file`, `remote_url`, `request_id`, `credits`, `usd`,
`status`

### PRYX ComfyUI Higgsfield Advanced Request

Send catalog-controlled JSON arguments when a specialized workflow needs more
direct control. The model is still selected from the validated catalog; this
node cannot override the API host or endpoint.

Use this node when you understand the selected model's documented request
schema. Normal generator nodes are easier to use because they create the
model-specific widgets and validate their values individually.

**Inputs**

- `model` — catalog model ID
- `arguments_json` — JSON object containing the model's request fields
- `request_mode`, `max_usd`, `auto_save`, `timeout` — common safety controls
- `image`, `video`, `audio`, `end_image`, `references` — optional native media
  inputs; the node shows only inputs supported by the selected model

**Outputs:** `image`, `video`, `remote_urls`, `request_id`, `credits`, `usd`,
`status`

## Working with references

### Direct inputs versus `references`

Use a direct input when the role is unambiguous:

- `image` is the source/start image for image-to-video or an image-edit node
- `end_image` is the explicit ending frame where the selected model supports it
- `video` is the source video for edit/extend nodes
- `audio` is an audio reference for models that accept one
- `item_images` is the AI Influencer clothing/object image batch, separate
  from its identity photo
- `references` is an ordered collection of additional media

The frontend hides inputs that the selected model cannot use. The backend
validates the final request again before uploading anything.

### Order and numbering

The order is deterministic:

1. Direct media inputs are mapped first.
2. Reference Collector slots follow in numeric socket order.
3. Image, video, audio, document, and web references are numbered separately
   when the provider uses numbered fields.
4. Image batches keep their internal order.

For example, two connected Collector images become `Image 1` and `Image 2`.
The socket `image_2` is always after `image`, even if its wire was added first.
Use Reference Preview to verify the actual mapping instead of guessing.

### Prompt references

Prompt syntax is endpoint-specific. The plugin does not invent `@` mentions or
angle-bracket tokens for endpoints that do not document them.

For **Wan 3.0 Reference to Video**, the documented tokens are:

```text
Image 1, Image 2, Video 1, Audio 1
```

The Collector's `names` input can assign readable aliases:

```text
image_1=person
image_2=outfit
video_1=camera
```

Then use the plugin alias syntax in the prompt:

```text
Use {{ref:person}} as the main character, {{ref:outfit}} as the clothing,
and {{ref:camera}} as the camera reference.
```

The plugin resolves those aliases to the correct documented model tokens before
upload and generation. Labels must be unique. Unknown or duplicate aliases
stop the request before media upload.

For other endpoints, numbered entries in Reference Preview describe delivery
order only. The current documentation does not confirm a prompt-token syntax
for them, so named aliases are rejected and the prompt should use the syntax
documented for that specific provider endpoint.

## Estimate Only, pricing, and generation safety

### What `estimate_only` does

When a generator runs in `estimate_only` mode, it:

1. Resolves the selected model and normalizes its parameters.
2. Checks required inputs, reference types, counts, choices, and ranges.
3. Uploads connected local references when the provider needs public media URLs.
4. Calls Higgsfield's `POST /estimate/<endpoint>` route.
5. Returns the provider's `credits` and `usd` estimate plus a `status` JSON.

It does **not** send the paid generation `POST` request. A local reference can
still be uploaded during an estimate because the provider must see the final
request shape; no generated image or video is created.

`generate` follows the same estimate-first path and submits the paid request
only after the estimate succeeds.

### Cost limits

- `max_usd = 0` disables the local cost limit.
- A positive `max_usd` is an upper bound on the **pre-submission USD estimate**.
- If the provider returns no USD estimate, a positive limit blocks generation.
- If the estimate exceeds the limit, no generation request is submitted.

The estimate is the best request-specific price supplied by the provider for
the selected model, duration, resolution, and references. `credits` and `usd`
are estimates, not a final billing receipt or account balance.

Final provider charges can differ, especially for token-based services such
as Ads Studio. This local check cannot impose an account-level billing cap.

Some endpoints return only a pricing description, with no numeric USD or
credit estimate. Missing values stay unavailable: the numeric output is `-1`,
not zero, and `status` retains the provider response. A positive `max_usd`
blocks generation when USD is unknown. An estimate error also stops the
request; it never triggers an unquoted generation as a fallback.

### Common safety controls

- `auto_save` stores completed media in ComfyUI's output directory when enabled
  and in its temporary directory when disabled.
- `timeout` limits how long the local node waits for a remote generation.
- Generation submissions are never automatically repeated after an ambiguous
  network timeout.
- Status polling uses bounded retries and backoff.
- ComfyUI progress events report the current phase and elapsed time. The
  provider does not currently expose a reliable percentage or ETA through this
  integration.

## Model catalog

The bundled catalog is the single source for model IDs, endpoint paths,
supported inputs, choices, ranges, defaults, conditional requirements, and
documentation links. Revision `2026-10-21.2` contains **87 inference endpoints**:
86 from Higgsfield's model inventory plus the separately documented SOUL Cinema
endpoint. SOUL ID training has its own node and is not counted as inference.
Account access and media acceptance are still decided by Higgsfield.

The table below is a snapshot of this bundled revision, not a provider-wide
inventory. The live dropdown in each node is authoritative for the catalog
loaded by that ComfyUI installation.

Seedance 2.5 supports `480p`, `720p`, and `1080p` in all five bundled video
modes (text, image, and reference to video, video edit, and video extend).
Genjutsu Motion Transfer and Object Swap also offer `1080p`. Their corrected
API endpoint paths use `higgsfield/genjutsu/...`. `720p` remains the default;
choose `1080p` in the resolution dropdown when the selected model supports it.

### Bundled catalog snapshot

| Capability | Bundled examples |
| --- | --- |
| Image generation (10) | SOUL, Recraft, Ideogram, Z-Image |
| Image editing (8) | SOUL 2 Image to Image, AI Influencer, Ads Studio, Marketing Studio, Grok Image |
| Text to video (19) | MiniMax H3, Seedance, Kling, Wan, PixVerse |
| Image to video (22) | MiniMax H3, Seedance, Kling, Wan, PixVerse |
| Reference to video (15) | MiniMax H3, Seedance, Kling Omni, Wan |
| Video edit (6) | Genjutsu Motion Transfer, Object Swap, Restyle, Seedance, Kling |
| Motion/control (6) | Genjutsu Light and Kling motion-control models, also in Video Edit |
| Video extend (1) | Seedance |

Each public platform entry includes the API reference's JSON input schema.
The backend checks required fields, choices, nested JSON, conditions, and
per-input limits before uploading local media. The collapsed model-information
panel lists the selected endpoint's media counts and options; the widgets show
its choices and tooltips. For Kling variants, provider `mode` (such as `std`
or `pro`) is distinct from the node's `request_mode` (estimate or generate).

### Discovery and automatic updates

Higgsfield now exposes model modes and complete request schemas through
authenticated **`GET /models?include_schema=true`**. Without `include_schema`,
schemas are omitted. This integration uses that route with your locally
configured credentials; no generation request is needed for discovery.

At ComfyUI startup, a background check refreshes the catalog if its cache is
more than 24 hours old. **Refresh catalog** runs the same check immediately.
If authenticated discovery fails, the updater falls back to the published,
reviewed PRYX catalog. Offline installations keep the latest valid local or
bundled catalog. Updates activate **after restarting ComfyUI**, so a running
workflow never changes its model schema halfway through execution. Reload the
browser afterward. Older catalogs cannot replace newer ones.

The repository also checks the public inventory every day at 06:00 UTC.
Changes run through the Python and frontend tests and open a pull request for
review; they are not automatically merged. This check needs **no login,
cookies, or API key**: it uses the public console JSON catalog at
`dash.higgsfield.ai/api/v2/app-models/`, including per-mode schemas. Public
model documentation is a fallback. The old page scraper alone was no longer
reliable after Higgsfield changed its website framework.

Repository setup: automatic PR creation requires **Settings → Actions →
General → Workflow permissions → Allow GitHub Actions to create and approve
pull requests**. This repository setting is currently disabled; an owner must
approve enabling it. The workflow never approves or merges PRs. ComfyUI's
local API refresh does not depend on this GitHub permission.

Partial inventories, unsafe references, incompatible schemas, and unknown
output/task mappings are rejected instead of replacing the working catalog.
New API task types may therefore need a code update as well as a catalog update.

**Upscalers:** no ByteDance/SeedVR or other standalone upscale endpoint was
listed in the authenticated model inventory, public console catalog, or API
references checked on October 21, 2026. Website tools are not necessarily API
products. No guessed upscale endpoint is included; a newly exposed compatible
API endpoint can be picked up by the discovery checks.

Model availability is capability-specific. A model can be available for one
Higgsfield task and still be absent from another node when the provider does
not document a compatible endpoint for that capability. The dropdowns therefore
filter by capability: an item missing from **Reference to Video** is not a
statement that the model is unavailable from Higgsfield in general.

To refresh manually, open **ComfyUI Settings → PRYX ComfyUI Higgsfield → Model
catalog**, click **Refresh catalog**, restart ComfyUI, and reload the browser.

## Outputs

### Generator outputs

| Output | Meaning |
| --- | --- |
| `images` | Native ComfyUI `IMAGE` result. Empty in estimate-only mode. |
| `video` | Native ComfyUI `VIDEO` result, or a local-file fallback when the installed ComfyUI version has no native video wrapper. Empty in estimate-only mode. |
| `image_urls` / `remote_url` / `remote_urls` | JSON text containing provider result URLs. These are not native media inputs. |
| `local_file` | Local path of a downloaded video result. It is empty until generation completes. |
| `request_id` | Provider request ID. Empty for estimate-only runs. |
| `credits` | Provider credit estimate for the normalized request. |
| `usd` | Provider USD estimate for the normalized request. |
| `status` | JSON diagnostics containing status, request ID, elapsed time, URLs, reference mapping, and provider status when available. |

Connect `images` or `video` to downstream ComfyUI nodes. Use URL outputs for
logging, diagnostics, or workflows that explicitly need the provider URL.
File-backed VIDEO inputs must be located inside ComfyUI's input, output, or
temp directory. Media passed directly as bytes or exported by a connected
VIDEO object does not need a file path in those directories.

## Troubleshooting

### A model is missing from a dropdown

The dropdown is filtered by node capability and active catalog status. Refresh
the catalog, restart ComfyUI, and hard-reload the browser. If the model is not
in the official Higgsfield endpoint documentation, it will not appear in this
node pack.

### The model-information panel is too large

Panels start collapsed. Click the panel heading to expand it. The expanded state
is remembered per node; use `Ctrl+F5` after updating the package if the old
frontend script is still cached.

### The video output is empty

This is expected in `estimate_only` mode. Switch to `generate` only after
checking the estimate and setting an appropriate `max_usd` limit.

### Connected media is rejected

Check the selected model's information panel and Reference Preview. The model
may accept a different media type, a smaller number of items, or a specific
source/end-frame field. Validation happens before generation and prevents an
invalid request from being sent.

### A long prompt is difficult to edit

Connect a Config UI Prompt node to the generator's `prompt` input. The prompt
field is designed to accept a connected `STRING` input.

### Credentials validate but generation fails

Run `estimate_only` with the exact model and inputs first. Then inspect the
`status` output and ComfyUI console. Provider-side model availability, account
credits, content policy, media duration, and retention rules can still affect a
real generation.

### A model's estimate returns HTTP 500

Do not switch off safety checks to bypass an estimate failure. On October 21,
2026, schema-valid live estimates succeeded for 81 of the 87 inference endpoints;
21 successful responses contained only a pricing description. The other six
returned HTTP 500: Kling O3/Omni Video Edit and Kling/V3 Motion Control in both
standard and pro modes. These observations do not verify paid generation or
prove that every valid source clip fails. The node stops before submission
when its estimate fails. Try again later or report the endpoint and sanitized
error to Higgsfield.

## Development

Run the local unit and mock integration tests:

```powershell
python -m pytest -q
node --test
```

Validate the Python import path:

```powershell
python -m compileall -q pryx_comfyui_higgsfield tools __init__.py
```

Validate the catalog against the official documentation pages:

```powershell
python tools/sync_platform_catalog.py --catalog pryx_comfyui_higgsfield/catalog/models.json --check --summary
```

To check the authenticated inventory instead, add `--authenticated`. It uses
the configured credentials without printing them. For an offline contract
review, save a public audit with `--snapshot <path>` and reuse it with
`--from-snapshot <path>`. Unchanged schemas do not create daily revision churn.

The test suite uses mocks and does not send paid generation requests. A live
credential smoke test should use an estimate only. A real generation requires
separate cost approval and an explicit positive `max_usd` value.

## Privacy, security, and license

- API credentials stay in the local ComfyUI installation or supported
  environment variables.
- PRYX does not proxy requests or collect credentials, prompts, references, or
  generated media.
- API authorization headers are not sent to the presigned storage upload host.
- See [SECURITY.md](SECURITY.md) for security reporting and request-safety
  details.
- The project is released under the [MIT License](LICENSE).
- See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for dependency notices.

## Links

- [Higgsfield API documentation](https://docs.higgsfield.ai/docs/models)
- [Higgsfield video model documentation](https://docs.higgsfield.ai/docs/models/video-generation)
- [ComfyUI](https://github.com/comfyanonymous/ComfyUI)
- [Issue tracker](https://github.com/PRYX-STUDIO/pryx-comfyui-higgsfield/issues)
