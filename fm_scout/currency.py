"""Currency helpers for FM money values.

FM stores contract and value-related money fields in a GBP-like base unit.
The UI in this project displays EUR, so we convert on readout/export.
"""

DEFAULT_GBP_TO_EUR_RATE: float = 1.17
_gbp_to_eur_rate: float = DEFAULT_GBP_TO_EUR_RATE


def set_gbp_to_eur_rate(rate: float) -> None:
    """Set conversion rate used for display/export."""
    global _gbp_to_eur_rate
    try:
        value = float(rate)
    except (TypeError, ValueError):
        value = DEFAULT_GBP_TO_EUR_RATE
    if value <= 0:
        value = DEFAULT_GBP_TO_EUR_RATE
    _gbp_to_eur_rate = value


def get_gbp_to_eur_rate() -> float:
    return _gbp_to_eur_rate


def gbp_to_eur(value: int | float | None) -> int:
    if value is None:
        return 0
    try:
        raw = float(value)
    except (TypeError, ValueError):
        return 0
    if raw <= 0:
        return 0
    return int(round(raw * _gbp_to_eur_rate))


def format_eur_from_gbp(value: int | float | None) -> str:
    eur = gbp_to_eur(value)
    if eur <= 0:
        return ""
    if eur >= 1_000_000:
        return f"\u20ac{eur / 1_000_000:.1f}M"
    if eur >= 1_000:
        return f"\u20ac{eur / 1_000:.0f}k"
    return f"\u20ac{eur:,}"
