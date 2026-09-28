"""Shared fixtures.

The FX table uses round numbers (1 USD = 90 KGS = 90 RUB, 1 EUR = 100 KGS,
1 USD = 7.2 CNY) so that every expected figure in the tests can be checked by
hand against the specification formulas.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from ved_calculator import VEDCalculationRequest, VEDCalculatorEngine
from ved_calculator.domain.models import (
    CargoCategory,
    CargoSpec,
    Currency,
    FxRateTable,
    OriginCountry,
)
from ved_calculator.services.fx_service import FxService

ROUND_FX = FxRateTable(
    as_of=date(2026, 9, 28),
    per_usd={
        Currency.USD: Decimal("1"),
        Currency.KGS: Decimal("90"),
        Currency.RUB: Decimal("90"),
        Currency.CNY: Decimal("7.2"),
        Currency.EUR: Decimal("0.9"),
        Currency.TRY: Decimal("40"),
        Currency.AED: Decimal("3.6"),
    },
)


@pytest.fixture(scope="session")
def round_fx() -> FxRateTable:
    return ROUND_FX


@pytest.fixture(scope="session")
def engine() -> VEDCalculatorEngine:
    return VEDCalculatorEngine(fx_table=ROUND_FX)


@pytest.fixture
def fx() -> FxService:
    return FxService(ROUND_FX, risk_buffer_percent=Decimal("2.5"))


@pytest.fixture
def sneakers_cargo() -> CargoSpec:
    """500 kg / 2.5 m³ / 400 pairs of sneakers, USD 12 000 FOB Guangzhou."""
    return CargoSpec(
        category=CargoCategory.FOOTWEAR,
        hs_code="6404 11 000 0",
        total_weight_kg=Decimal("500"),
        total_volume_m3=Decimal("2.5"),
        declared_value_origin=Decimal("12000"),
        origin_currency=Currency.USD,
        quantity_units=400,
        description="Sneakers, 400 pairs",
    )


@pytest.fixture
def sneakers_request(sneakers_cargo: CargoSpec) -> VEDCalculationRequest:
    return VEDCalculationRequest(
        origin_country=OriginCountry.CHINA,
        destination_city_ru="Tyumen",
        cargo=sneakers_cargo,
    )
