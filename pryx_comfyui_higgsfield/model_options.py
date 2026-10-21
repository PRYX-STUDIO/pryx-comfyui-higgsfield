"""Model-specific metadata and validation; never submit generation here."""

from collections.abc import Mapping

from .errors import ValidationError


INFLUENCER_OPTIONS = "/models/higgsfield/ai-influencer/options"


def validate_appearance(options: Mapping, tier: str, selection: Mapping) -> None:
    categories = options.get("categories")
    if not isinstance(categories, list):
        raise ValidationError("AI Influencer returned an invalid appearance catalog.")
    available = {item["key"]: item for item in categories if tier in item.get("tiers", [])}
    for key, values in selection.items():
        category = available.get(key)
        if category is None:
            raise ValidationError(f"Appearance category {key} is not available for tier {tier}.")
        allowed = {item["key"]: item for item in category.get("options", [])
                   if item.get("tiers") is None or tier in item["tiers"]}
        if not isinstance(values, list) or len(values) != len(set(values)) or len(values) > category["max"]:
            raise ValidationError(f"Appearance {key} accepts at most {category['max']} different option(s).")
        if any(value not in allowed for value in values):
            raise ValidationError(f"Appearance {key} contains an unavailable option for {tier}.")
        selected = [allowed[value] for value in values]
        if len(selected) > 1 and any(item.get("exclusive") for item in selected):
            raise ValidationError(f"An exclusive {key} option must be selected alone.")
        slots = [item["slot"] for item in selected if item.get("slot") is not None]
        if len(slots) != len(set(slots)):
            raise ValidationError(f"Appearance {key} accepts only one option per facial slot.")
