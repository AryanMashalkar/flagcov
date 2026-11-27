"""The shop's existing test suite: green, decent line coverage, and blind to 10% of checkouts.

The team tested the two checkout variants they built. Later, someone added an
"express" variant in the Flagsmith dashboard and rolled it out to 10% of
users. No pull request, no code review, no new test. FlagCov catches that.
"""

from shop import checkout, homepage


def test_classic_checkout(flag_override):
    flag_override("checkout_flow", "classic")
    order = checkout(cart_total=650, user_id="user-1")
    assert order == {"flow": "classic", "steps": 3, "shipping": 0, "eta_days": 4, "total": 650}


def test_one_page_checkout(flag_override):
    flag_override("checkout_flow", "one_page")
    order = checkout(cart_total=650, user_id="user-2")
    assert order["steps"] == 1 and order["eta_days"] == 3


def test_small_cart_pays_shipping(flag_override):
    flag_override("checkout_flow", "classic")
    assert checkout(cart_total=200, user_id="user-3")["shipping"] == 49


def test_homepage_theme():
    assert homepage("user-1")["theme"] == "dark"
