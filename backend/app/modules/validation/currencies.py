"""Currency data for validation and conversion: constants only, no logic.

ISO 4217 membership itself comes from ``pycountry``; this file adds what it lacks (minor
units) and the static, dated exchange-rate snapshot used by ``convert_currency``.
"""

from datetime import date
from decimal import Decimal

# Minor units (decimal places) per ISO 4217 code. pycountry does not carry them, so only the
# currencies that differ from the default of 2 are listed. Checked against the official
# ISO 4217 list one (SIX, published 2026-09-17), which also matched pycountry's codes
# exactly; recheck when a currency is added or redenominated.
ISO_4217_AS_OF = "ISO 4217 list one, published 2026-09-17"
DEFAULT_MINOR_UNITS = 2
MINOR_UNITS: dict[str, int] = {
    # 0 decimal places
    "BIF": 0,
    "CLP": 0,
    "DJF": 0,
    "GNF": 0,
    "ISK": 0,
    "JPY": 0,
    "KMF": 0,
    "KRW": 0,
    "PYG": 0,
    "RWF": 0,
    "UGX": 0,
    "UYI": 0,
    "VND": 0,
    "VUV": 0,
    "XAF": 0,
    "XOF": 0,
    "XPF": 0,
    # 3 decimal places
    "BHD": 3,
    "IQD": 3,
    "JOD": 3,
    "KWD": 3,
    "LYD": 3,
    "OMR": 3,
    "TND": 3,
    # 4 decimal places
    "CLF": 4,
    "UYW": 4,
}

# ISO 4217 codes that are not money an invoice can be priced in: precious metals, IMF /
# bond-market units, the testing code and "no currency". Real X currencies (XAF, XOF, XCD,
# XPF) are not listed and stay valid.
EXCLUDED_CODES = frozenset(
    {"XAU", "XAG", "XPT", "XPD", "XDR", "XSU", "XUA", "XBA", "XBB", "XBC", "XBD", "XTS", "XXX"}
)

# Static exchange-rate snapshot: units of each currency per 1 USD, copied exactly as
# published by GET https://open.er-api.com/v6/latest/USD (time_last_update_utc
# "Mon, 26 Oct 2026 00:02:31 +0000"). Indicative mid-market rates, not for settlement.
# The currencies are the ones 0003's prompt can produce from a symbol.
# To refresh: repeat the request, replace the literals and RATES_AS_OF, run the tests.
RATES_AS_OF = date(2026, 10, 26)
RATES_SOURCE = "ExchangeRate-API open access (https://www.exchangerate-api.com), USD base"
RATES_PER_USD: dict[str, Decimal] = {
    # Southeast Asia
    "MYR": Decimal("4.085277"),
    "SGD": Decimal("1.278569"),
    "IDR": Decimal("18090.294944"),
    "THB": Decimal("33.762188"),
    "PHP": Decimal("63.680824"),
    "VND": Decimal("25829.651426"),
    "BND": Decimal("1.278596"),
    "KHR": Decimal("4103.949618"),
    "LAK": Decimal("22334.490496"),
    "MMK": Decimal("2098.942204"),
    "USD": Decimal("1"),
    # Common world currencies
    "EUR": Decimal("0.89213"),
    "GBP": Decimal("0.747783"),
    "INR": Decimal("95.160836"),
    "KRW": Decimal("1323.904108"),
    "HKD": Decimal("7.842801"),
    "TWD": Decimal("32.596145"),
    "AUD": Decimal("1.422894"),
    "NZD": Decimal("1.754943"),
    "CAD": Decimal("1.401312"),
    "CNY": Decimal("6.677446"),
    "JPY": Decimal("156.872016"),
    "CHF": Decimal("0.824578"),
    "AED": Decimal("3.6725"),
    "SAR": Decimal("3.75"),
}
