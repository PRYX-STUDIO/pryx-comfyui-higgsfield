"""SOUL ID training has a separate lifecycle from image/video inference."""

import json
from uuid import UUID

from ..client import HiggsfieldClient
from ..errors import ValidationError
from ..media import upload_reference
from .references import Reference, ReferenceCollection, _split_batch


class SoulIDNode:
    CATEGORY = "PRYX/ComfyUI/Higgsfield"
    FUNCTION = "run"
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("custom_reference_id", "status")
    OUTPUT_NODE = True
    DESCRIPTION = (
        "Train a reusable SOUL character from 1–100 connected images, or check an existing training. "
        "validate_only never uploads or trains. Training may cost money and has no inference estimate/max_usd guard. "
        "train submits once and returns the ID immediately; use check with that ID to poll safely. "
        "After status=completed, connect the ID to the matching SOUL model's custom_reference_id input."
    )

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "action": (["validate_only", "train", "check"], {"default": "validate_only", "tooltip": cls.DESCRIPTION}),
            "name": ("STRING", {"default": "My character", "tooltip": "Character reference name, 1–100 characters."}),
            "model_version": (["v1", "v2", "cinema"], {"default": "v1", "tooltip": "Must match the SOUL generation family that will use the completed character ID."}),
        }, "optional": {
            "images": ("IMAGE", {"tooltip": "Training image or batch. Images from references follow the batch. Total: 1–100."}),
            "references": (ReferenceCollection.TYPE, {"tooltip": "Additional ordered training images. Video/audio references are not accepted."}),
            "reference_id": ("STRING", {"default": "", "tooltip": "Existing SOUL ID UUID. Required for check. Returned after train; do not start another training to check progress."}),
        }}

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        # A status check must reach the server, but an unchanged train node must
        # remain cacheable so queuing a downstream generator cannot retrain it.
        return float("nan") if kwargs.get("action") == "check" else json.dumps(
            {k: v for k, v in kwargs.items() if k not in {"images", "references"}}, sort_keys=True
        )

    def run(self, action, name, model_version, images=None, references=None, reference_id=""):
        if action not in {"validate_only", "train", "check"}:
            raise ValidationError("Unknown SOUL ID action.")
        if action == "check":
            try:
                reference_id = str(UUID(reference_id))
            except (ValueError, TypeError, AttributeError) as error:
                raise ValidationError("reference_id must be an existing SOUL ID UUID.") from error
            client = HiggsfieldClient.from_environment(timeout=60)
            try:
                payload = client.get_json(f"/v1/custom-references/{reference_id}")
            finally:
                client.close()
        else:
            if model_version not in {"v1", "v2", "cinema"} or not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
                raise ValidationError("SOUL ID needs a name of 1–100 characters and model_version v1, v2 or cinema.")
            refs = ReferenceCollection(Reference("image", item) for item in _split_batch(images))
            refs.extend(ReferenceCollection(references or ()))
            if not 1 <= len(refs) <= 100 or any(ref.kind != "image" for ref in refs):
                raise ValidationError("SOUL ID requires 1–100 images; videos and audio are not accepted.")
            if action == "validate_only":
                payload = {"status": "validated", "name": name.strip(), "model_version": model_version,
                           "image_count": len(refs), "message": "No upload or training submitted. Training has no inference price quote; select train explicitly."}
            else:
                if reference_id.strip():
                    raise ValidationError("Clear reference_id to start a NEW training, or select check for the existing training.")
                client = HiggsfieldClient.from_environment(timeout=60)
                try:
                    args = {"name": name.strip(), "model_version": model_version, "input_images": [
                        {"type": "image_url", "image_url": upload_reference(client, ref)} for ref in refs
                    ]}
                    payload = client.create_custom_reference(args)
                finally:
                    client.close()
        text = json.dumps(dict(payload), ensure_ascii=False)
        return {"ui": {"text": [text]}, "result": (str(payload.get("id", "")), text)}
