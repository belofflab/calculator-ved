"""Default FX snapshot.

Reference mid-market rates.  Production deployments should inject a live
:class:`~ved_calculator.domain.models.FxRateTable` (NBKR/CBR/ECB feeds) into the
engine instead of relying on this snapshot.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from ved_calculator.domain.models import Currency, FxRateTable

DEFAULT_FX_TABLE = FxRateTable(
    as_of=date(2026, 9, 28),
    per_usd={
        Currency.USD: Decimal("1"),
        Currency.KGS: Decimal("87.40"),  # NBKR reference band
        Currency.RUB: Decimal("83.50"),  # CBR reference band
        Currency.CNY: Decimal("7.15"),
        Currency.EUR: Decimal("0.9174"),  # EUR/USD ≈ 1.09
        Currency.TRY: Decimal("43.20"),
        Currency.AED: Decimal("3.6725"),  # hard peg
    },
)

__all__ = ["DEFAULT_FX_TABLE"]
