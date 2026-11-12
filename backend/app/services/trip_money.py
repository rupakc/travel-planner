"""Trip expenses: exact decimal amounts and honest USD estimates."""

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

EXPENSE_CATEGORIES = (
    "flights",
    "lodging",
    "food",
    "transport",
    "activities",
    "shopping",
    "fees",
    "other",
)
MAX_AMOUNT = Decimal(1_000_000)
_ZERO_EXP = frozenset("JPY KRW VND CLP ISK UGX XAF XOF".split())
_THREE_EXP = frozenset("BHD KWD OMR JOD TND".split())
_AMOUNT_RE = re.compile(r"^\d+(\.\d+)?$")


def currency_exponent(code: str) -> int:
    if code in _ZERO_EXP:
        return 0
    if code in _THREE_EXP:
        return 3
    return 2


def parse_amount(amount: str, currency: str) -> int:
    """Decimal string -> integer minor units; ``ValueError`` when invalid."""
    if not isinstance(amount, str) or not _AMOUNT_RE.match(amount.strip()):
        raise ValueError("amount must be a plain decimal number")
    text = amount.strip()
    exp = currency_exponent(currency)
    decimals = len(text.split(".")[1]) if "." in text else 0
    if decimals > exp:
        raise ValueError(f"{currency} allows at most {exp} decimals")
    try:
        value = Decimal(text)
    except InvalidOperation as e:
        raise ValueError("amount must be a plain decimal number") from e
    if value <= 0 or value > MAX_AMOUNT:
        raise ValueError("amount must be above 0 and at most 1,000,000")
    return int(value.scaleb(exp))


def format_amount(minor: int, currency: str) -> str:
    exp = currency_exponent(currency)
    return f"{Decimal(minor).scaleb(-exp):.{exp}f}"


def _usd_str(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}"


def usd_rate(snapshot: dict | None) -> dict | None:
    """The snapshot's USD -> local rate: ``{"local", "usd_to_local", "as_of"}``."""
    forex = (snapshot or {}).get("forex")
    if not isinstance(forex, dict):
        return None
    for entry in forex.get("exchange_rates") or []:
        if not isinstance(entry, dict) or entry.get("from_currency") != "USD":
            continue
        local = entry.get("to_currency")
        rate = entry.get("rate")
        if (
            isinstance(local, str)
            and local
            and isinstance(rate, (int, float))
            and not isinstance(rate, bool)
            and rate > 0
        ):
            return {
                "local": local,
                "usd_to_local": rate,
                "as_of": (snapshot or {}).get("as_of"),
            }
    return None


def totals(expenses: list[dict], rate: dict | None) -> dict:
    """Per-currency totals plus a USD estimate from USD rows and rows in the
    rate's local currency; every other currency is listed unconverted."""
    by_minor: dict[str, int] = {}
    for e in expenses:
        by_minor[e["currency"]] = by_minor.get(e["currency"], 0) + e["amount_minor"]
    by_currency = {c: format_amount(m, c) for c, m in sorted(by_minor.items())}

    to_local = Decimal(str(rate["usd_to_local"])) if rate else None
    local = rate["local"] if rate else None
    usd_total = Decimal(0)
    by_cat: dict[str, Decimal] = {}
    converted = 0
    unconverted: set[str] = set()
    for e in expenses:
        cur = e["currency"]
        value = Decimal(e["amount_minor"]).scaleb(-currency_exponent(cur))
        if cur == "USD":
            usd = value
        elif to_local is not None and cur == local:
            usd = value / to_local
        else:
            unconverted.add(cur)
            continue
        converted += 1
        usd_total += usd
        by_cat[e["category"]] = by_cat.get(e["category"], Decimal(0)) + usd
    return {
        "by_currency": by_currency,
        "usd_estimate": _usd_str(usd_total) if converted else None,
        "by_category_usd": {k: _usd_str(v) for k, v in sorted(by_cat.items())},
        "unconverted": sorted(unconverted),
    }


def spend_summary(plan: dict) -> dict:
    from ..db import trip_expenses_db, trip_snapshot_db

    plan_id = plan.get("id")
    if plan_id is None:
        t = totals([], None)
    else:
        rate = usd_rate(trip_snapshot_db.get_snapshot(plan_id))
        t = totals(trip_expenses_db.list_for(plan_id), rate)
    return {
        "spent_usd": t["usd_estimate"],
        "by_category_usd": t["by_category_usd"],
        "unconverted": t["unconverted"],
        "by_currency": t["by_currency"],
    }
