"""Cost guards must fail closed even for non-finite provider/input values."""

from types import SimpleNamespace

import pytest

from pryx_comfyui_higgsfield.errors import ValidationError
from pryx_comfyui_higgsfield.nodes.common import execute_generation
from pryx_comfyui_higgsfield.types import Estimate


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", -1])
def test_invalid_provider_price_is_unavailable_not_an_approved_budget(value):
    estimate = Estimate.from_payload({"usd": value, "credits": value})
    assert estimate.usd is None and estimate.credits is None
    client = SimpleNamespace(estimate=lambda *args: estimate,
                             submit=lambda *args: pytest.fail("Unknown price cannot pass a positive budget"))
    with pytest.raises(ValidationError, match="cannot be enforced"):
        execute_generation("soul-2", {"prompt": "test"}, mode="generate", max_usd=1,
                           auto_save=False, timeout=60, client=client)


@pytest.mark.parametrize("name,value", [("max_usd", float("nan")), ("max_usd", float("inf")),
                                       ("timeout", float("nan")), ("timeout", float("inf"))])
def test_invalid_safety_controls_stop_before_network(name, value):
    options = {"mode": "estimate_only", "max_usd": 0, "auto_save": False, "timeout": 60}
    options[name] = value
    with pytest.raises(ValidationError):
        execute_generation("soul-2", {"prompt": "test"}, **options)
