"""Reference data: default tariffs, rate cards, tax/fee schedules and FX snapshot."""

from ved_calculator.reference.cities import city_title, normalize_city
from ved_calculator.reference.corridors import (
    BISHKEK,
    DEFAULT_CORRIDORS,
    DEFAULT_DOMESTIC_LEGS,
    DEFAULT_FALLBACK_DOMESTIC,
    MOSCOW,
)
from ved_calculator.reference.fees import (
    DEFAULT_BANK_FEES,
    DEFAULT_SERVICE_FEES,
    DEFAULT_TAX_PROFILES,
    KG_TAX_PROFILE,
    RU_TAX_PROFILE,
)
from ved_calculator.reference.fx_rates import DEFAULT_FX_TABLE
from ved_calculator.reference.tariffs import DEFAULT_TARIFF_MATRIX, TARIFF_ENTRIES

__all__ = [
    "BISHKEK",
    "DEFAULT_BANK_FEES",
    "DEFAULT_CORRIDORS",
    "DEFAULT_DOMESTIC_LEGS",
    "DEFAULT_FALLBACK_DOMESTIC",
    "DEFAULT_FX_TABLE",
    "DEFAULT_SERVICE_FEES",
    "DEFAULT_TARIFF_MATRIX",
    "DEFAULT_TAX_PROFILES",
    "KG_TAX_PROFILE",
    "MOSCOW",
    "RU_TAX_PROFILE",
    "TARIFF_ENTRIES",
    "city_title",
    "normalize_city",
]
