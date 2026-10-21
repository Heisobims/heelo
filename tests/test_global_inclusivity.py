from __future__ import annotations

import pytest
from app.config import settings
from app.services.payment_service import select_provider


def test_select_provider_prioritizes_stripe_for_global_currencies(monkeypatch):
    monkeypatch.setattr(settings, "STRIPE_SECRET_KEY", "sk_test_123")
    monkeypatch.setattr(settings, "PAYSTACK_SECRET_KEY", "sk_test_paystack")
    monkeypatch.setattr(settings, "FLUTTERWAVE_SECRET_KEY", "flw_test_secret")

    # Global currencies MUST route to Stripe
    for curr in ("USD", "EUR", "GBP", "CAD", "AUD", "NZD", "CHF", "SGD", "JPY"):
        assert select_provider(curr) == "stripe", f"Failed for {curr}: expected stripe"


def test_select_provider_routes_african_currencies_to_paystack(monkeypatch):
    monkeypatch.setattr(settings, "STRIPE_SECRET_KEY", "sk_test_123")
    monkeypatch.setattr(settings, "PAYSTACK_SECRET_KEY", "sk_test_paystack")
    monkeypatch.setattr(settings, "FLUTTERWAVE_SECRET_KEY", "flw_test_secret")

    # African currencies with domestic rails route to Paystack
    for curr in ("NGN", "GHS", "ZAR", "KES", "EGP"):
        assert select_provider(curr) == "paystack", f"Failed for {curr}: expected paystack"


def test_select_provider_falls_back_cleanly(monkeypatch):
    # Only Flutterwave is configured
    monkeypatch.setattr(settings, "STRIPE_SECRET_KEY", None)
    monkeypatch.setattr(settings, "PAYSTACK_SECRET_KEY", None)
    monkeypatch.setattr(settings, "FLUTTERWAVE_SECRET_KEY", "flw_test_secret")

    assert select_provider("USD") == "flutterwave"
    assert select_provider("NGN") == "flutterwave"

    # Only Stripe is configured
    monkeypatch.setattr(settings, "STRIPE_SECRET_KEY", "sk_test_stripe")
    monkeypatch.setattr(settings, "FLUTTERWAVE_SECRET_KEY", None)

    assert select_provider("USD") == "stripe"
    assert select_provider("NGN") == "stripe"


def test_currency_symbol_and_country_helpers():
    from app.utils.currency import country_to_currency, currency_symbol

    assert currency_symbol("USD") == "$"
    assert currency_symbol("GBP") == "£"
    assert currency_symbol("EUR") == "€"
    assert currency_symbol("CAD") == "CA$"
    assert currency_symbol("AUD") == "A$"
    assert currency_symbol("NGN") == "₦"
    assert currency_symbol("GHS") == "GH₵"
    assert currency_symbol("KES") == "KSh"
    assert currency_symbol("ZAR") == "R"
    assert currency_symbol("UNKNOWN") == "UNKNOWN"
    assert currency_symbol(None) == "$"

    assert country_to_currency("GB") == "GBP"
    assert country_to_currency("US") == "USD"
    assert country_to_currency("CA") == "CAD"
    assert country_to_currency("AU") == "AUD"
    assert country_to_currency("DE") == "EUR"
    assert country_to_currency("FR") == "EUR"
    assert country_to_currency("NG") == "NGN"
    assert country_to_currency("GH") == "GHS"
    assert country_to_currency("KE") == "KES"
    assert country_to_currency("ZA") == "ZAR"
    assert country_to_currency("XX") == "USD"


def test_vendor_subscription_plans_by_currency():
    from app.services.vendor_service import (
        get_featured_pricing,
        get_lead_credit_price,
        get_vendor_subscription_plans,
    )

    # UK Rate Card
    gbp_plans = get_vendor_subscription_plans("GBP")
    assert gbp_plans["starter"]["price"] == 25.0
    assert gbp_plans["starter"]["currency"] == "GBP"
    assert gbp_plans["pro"]["price"] == 55.0
    assert gbp_plans["pro"]["currency"] == "GBP"
    assert gbp_plans["premium"]["price"] == 119.0
    assert gbp_plans["premium"]["currency"] == "GBP"

    # US Rate Card
    usd_plans = get_vendor_subscription_plans("USD")
    assert usd_plans["starter"]["price"] == 29.0
    assert usd_plans["starter"]["currency"] == "USD"
    assert usd_plans["pro"]["price"] == 69.0
    assert usd_plans["pro"]["currency"] == "USD"
    assert usd_plans["premium"]["price"] == 149.0
    assert usd_plans["premium"]["currency"] == "USD"

    # EUR Rate Card
    eur_plans = get_vendor_subscription_plans("EUR")
    assert eur_plans["starter"]["price"] == 27.0
    assert eur_plans["starter"]["currency"] == "EUR"
    assert eur_plans["pro"]["price"] == 59.0
    assert eur_plans["pro"]["currency"] == "EUR"

    # Nigeria Rate Card
    ngn_plans = get_vendor_subscription_plans("NGN")
    assert ngn_plans["starter"]["price"] == 15000.0
    assert ngn_plans["starter"]["currency"] == "NGN"
    assert ngn_plans["pro"]["price"] == 35000.0
    assert ngn_plans["pro"]["currency"] == "NGN"

    # Featured Campaign Pricing
    assert get_featured_pricing("marketplace_top", 30, "GBP")[0] == 59.0
    assert get_featured_pricing("marketplace_top", 30, "USD")[0] == 75.0
    assert get_featured_pricing("marketplace_top", 30, "EUR")[0] == 65.0
    assert get_featured_pricing("marketplace_top", 30, "NGN")[0] == 30000.0

    # Lead Credit Pricing
    assert get_lead_credit_price(5, "GBP")[0] == 8.0
    assert get_lead_credit_price(5, "USD")[0] == 10.0
    assert get_lead_credit_price(5, "EUR")[0] == 9.0
    assert get_lead_credit_price(5, "NGN")[0] == 5000.0


def test_organizer_plan_pricing_by_currency():
    from decimal import Decimal
    from app.services.billing_service import get_plan_price

    # UK Organizer Pricing
    assert get_plan_price("growth", "GBP") == Decimal("15")
    assert get_plan_price("pro", "GBP") == Decimal("39")

    # US Organizer Pricing
    assert get_plan_price("growth", "USD") == Decimal("19")
    assert get_plan_price("pro", "USD") == Decimal("49")

    # EUR Organizer Pricing
    assert get_plan_price("growth", "EUR") == Decimal("18")
    assert get_plan_price("pro", "EUR") == Decimal("45")

    # Nigeria Organizer Pricing
    assert get_plan_price("growth", "NGN") == Decimal("7500")
    assert get_plan_price("pro", "NGN") == Decimal("25000")


def test_jinja_currency_symbol_filter_registered():
    from app.routers.pages import templates as page_templates
    from app.routers.admin_pages import templates as admin_templates

    assert "currency_symbol" in page_templates.env.filters
    assert page_templates.env.filters["currency_symbol"]("GBP") == "£"
    assert page_templates.env.filters["currency_symbol"]("USD") == "$"
    assert page_templates.env.filters["currency_symbol"]("EUR") == "€"
    assert page_templates.env.filters["currency_symbol"]("NGN") == "₦"

    assert "currency_symbol" in admin_templates.env.filters
    assert admin_templates.env.filters["currency_symbol"]("CAD") == "CA$"


