"""Global multi-currency utilities and symbol formatters."""

from __future__ import annotations

CURRENCY_SYMBOLS: dict[str, str] = {
    "USD": "$",
    "GBP": "£",
    "EUR": "€",
    "CAD": "CA$",
    "AUD": "A$",
    "NZD": "NZ$",
    "CHF": "CHF",
    "SGD": "S$",
    "JPY": "¥",
    "BRL": "R$",
    "INR": "₹",
    "NGN": "₦",
    "GHS": "GH₵",
    "KES": "KSh",
    "ZAR": "R",
    "EGP": "E£",
}

COUNTRY_TO_CURRENCY: dict[str, str] = {
    # Americas
    "US": "USD",
    "CA": "CAD",
    "BR": "BRL",
    # UK & Europe
    "GB": "GBP",
    "DE": "EUR",
    "FR": "EUR",
    "IT": "EUR",
    "ES": "EUR",
    "NL": "EUR",
    "IE": "EUR",
    "BE": "EUR",
    "AT": "EUR",
    "PT": "EUR",
    "FI": "EUR",
    "CH": "CHF",
    # Asia-Pacific
    "AU": "AUD",
    "NZ": "NZD",
    "SG": "SGD",
    "JP": "JPY",
    "IN": "INR",
    # Africa
    "NG": "NGN",
    "GH": "GHS",
    "KE": "KES",
    "ZA": "ZAR",
    "EG": "EGP",
}


def currency_symbol(code: str | None) -> str:
    """Return the symbol for a 3-letter currency code, defaulting to '$'."""
    if not code:
        return "$"
    return CURRENCY_SYMBOLS.get(code.upper(), code.upper())


def country_to_currency(country: str | None, default: str = "USD") -> str:
    """Return the default currency code for an ISO 3166-1 alpha-2 country code."""
    if not country:
        return default
    return COUNTRY_TO_CURRENCY.get(country.upper(), default)

