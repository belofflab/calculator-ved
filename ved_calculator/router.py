"""Module 2 — Multi-Country Logistics Router (public façade).

Implementation lives in :mod:`ved_calculator.services.freight_service`; the
reference rate cards in :mod:`ved_calculator.reference.corridors`.
"""

from ved_calculator.domain.models import (
    CorridorRateCard,
    DomesticLegRate,
    DomesticQuote,
    FreightQuote,
    ServiceKind,
    TransportMode,
)
from ved_calculator.reference.cities import city_title, normalize_city
from ved_calculator.reference.corridors import (
    BISHKEK,
    DEFAULT_CORRIDORS,
    DEFAULT_DOMESTIC_LEGS,
    DEFAULT_FALLBACK_DOMESTIC,
    MOSCOW,
)
from ved_calculator.services.freight_service import FreightService

__all__ = [
    "BISHKEK",
    "DEFAULT_CORRIDORS",
    "DEFAULT_DOMESTIC_LEGS",
    "DEFAULT_FALLBACK_DOMESTIC",
    "MOSCOW",
    "CorridorRateCard",
    "DomesticLegRate",
    "DomesticQuote",
    "FreightQuote",
    "FreightService",
    "ServiceKind",
    "TransportMode",
    "city_title",
    "normalize_city",
]
