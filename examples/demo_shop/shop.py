"""A tiny shop whose behaviour depends on Flagsmith flags (read through OpenFeature)."""

from __future__ import annotations

from openfeature import api
from openfeature.evaluation_context import EvaluationContext

EXPRESS_COURIER_SLOTS: dict[str, int] = {"mumbai": 4, "pune": 2}  # no slots configured for other cities yet


def _ctx(user_id: str, plan: str) -> EvaluationContext:
    return EvaluationContext(targeting_key=user_id, attributes={"plan": plan})


def checkout(cart_total: int, user_id: str, city: str = "mumbai", plan: str = "free") -> dict:
    client = api.get_client()
    ctx = _ctx(user_id, plan)
    flow = client.get_string_value("checkout_flow", "classic", ctx)
    threshold = client.get_integer_value("free_shipping_threshold", 999, ctx)
    shipping = 0 if cart_total >= threshold else 49

    if flow == "one_page":
        steps = 1
        eta_days = 3
    elif flow == "express":
        steps = 1
        # Latent bug: cities without express slots divide by zero.
        eta_days = 4 // EXPRESS_COURIER_SLOTS.get(city, 0)
    elif flow == "invoice":
        steps = 2
        eta_days = 5
    else:
        steps = 3
        eta_days = 4
    return {"flow": flow, "steps": steps, "shipping": shipping, "eta_days": eta_days, "total": cart_total + shipping}


def homepage(user_id: str, plan: str = "free") -> dict:
    client = api.get_client()
    ctx = _ctx(user_id, plan)
    return {
        "theme": "dark" if client.get_boolean_value("dark_mode", False, ctx) else "light",
        "search": "v2" if client.get_boolean_value("new_search", False, ctx) else "v1",
        "recommendations": client.get_boolean_value("recommendation_v2", False, ctx),
    }
