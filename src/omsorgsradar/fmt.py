"""nb-NO number formatting helpers.

Produces Norwegian-locale output:
- Decimal separator: comma (,)
- Thousands separator: regular space ( )
- Percent: space before % sign («31,1 %»)
- Press index: two-decimal («1,00»)

These are purely presentational — never applied to raw numeric computations.
"""

from __future__ import annotations

import math


def nb(value: float, decimals: int = 1) -> str:
    """Format *value* with Norwegian decimal/thousands conventions.

    Examples:
        nb(31.1)       → «31,1»
        nb(288360.0)   → «288 360»
        nb(1234.5, 2)  → «1 234,50»
        nb(float("nan")) → «—»

    Args:
        value: Numeric value to format.
        decimals: Number of decimal places (0 for integers, 1+ for floats).

    Returns:
        Norwegian-formatted string.
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "—"
    if math.isnan(v) or math.isinf(v):
        return "—"

    # Format with the requested number of decimal places using English locale
    # then swap . → , for decimal and , →   (narrow no-break space) for thousands.
    # We use regular space as thousands sep (as commonly used in Norwegian typography).
    formatted = f"{v:,.{decimals}f}"  # e.g. "31,123.10" with English locale
    # Python's format uses ',' as thousands sep and '.' as decimal sep by default.
    # Swap: first replace ',' (thousands) with a placeholder, then '.' (decimal) → ','
    # then placeholder → ' '.
    formatted = formatted.replace(",", "\x00").replace(".", ",").replace("\x00", " ")
    # Use narrow no-break space (U+202F) as thousands separator — standard in Norwegian.
    # For plain-text contexts replace with regular space if needed:
    formatted = formatted.replace(" ", " ")  # non-breaking space
    # Actually the plan says «regular space» so let's use ordinary space.
    formatted = formatted.replace(" ", " ")
    return formatted


def nb_pct(value: float, decimals: int = 1) -> str:
    """Format *value* as a Norwegian percentage string.

    Example:
        nb_pct(31.1) → «31,1 %»
        nb_pct(float("nan")) → «—»

    Args:
        value: Numeric value (already in percent; e.g. 31.1 for 31.1%).
        decimals: Decimal places.

    Returns:
        Norwegian-formatted percentage string.
    """
    num_str = nb(value, decimals)
    if num_str == "—":
        return "—"
    return f"{num_str} %"


def nb_index(value: float) -> str:
    """Format a press-index value with two decimals (Norwegian style).

    Norwegian readers read «1.000» as one thousand; the index must be
    rendered «1,00» to avoid confusion.

    Example:
        nb_index(1.0)   → «1,00»
        nb_index(0.935) → «0,94»

    Args:
        value: Press-index value (typically in [0, 1]).

    Returns:
        Two-decimal Norwegian-formatted string.
    """
    return nb(value, decimals=2)
