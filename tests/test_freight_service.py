"""Module 2 — logistics router unit tests."""

from __future__ import annotations

from decimal import Decimal

import pytest

from ved_calculator import VEDCalculatorEngine
from ved_calculator.domain.models import (
    CargoCategory,
    CargoSpec,
    Currency,
    OriginCountry,
    ServiceKind,
    TransportMode,
)
from ved_calculator.reference.corridors import BISHKEK, DEFAULT_CORRIDORS, MOSCOW
from ved_calculator.services.freight_service import FreightService

D = Decimal


class TestChargeableWeight:
    def test_density_at_threshold_uses_actual_weight(self) -> None:
        assert FreightService.chargeable_weight(500, "2.5", 200) == D("500")

    def test_light_cargo_uses_volumetric_weight(self) -> None:
        assert FreightService.chargeable_weight(100, "2.0", 167) == D("334.0")

    def test_dense_cargo_uses_actual_weight(self) -> None:
        assert FreightService.chargeable_weight(1000, 1, 250) == D("1000")


class TestCorridorQuotes:
    def test_white_express_quote_uses_volumetric_weight(
        self, engine: VEDCalculatorEngine, sneakers_cargo: CargoSpec
    ) -> None:
        card = engine.freight.corridor("CN-FRU-AUTO-EXPRESS-WHITE")
        quote = engine.freight.quote_corridor(card, sneakers_cargo)
        assert quote.volumetric_weight_kg == D("625.0")  # 2.5 m³ × 250
        assert quote.chargeable_weight_kg == D("625.0")
        assert quote.freight_usd == D("1187.500")  # 625 × 1.90
        assert quote.handling_usd == D("130.000")  # 80 + 0.08 × 625
        assert quote.total_usd == D("1317.500")
        assert quote.min_charge_applied is False
        assert (quote.days_min, quote.days_max) == (10, 14)

    def test_minimum_charge_applies_to_small_parcels(self, engine: VEDCalculatorEngine) -> None:
        small = CargoSpec(
            category=CargoCategory.GENERAL,
            total_weight_kg=10,
            total_volume_m3="0.05",
            declared_value_origin=200,
            origin_currency=Currency.USD,
            quantity_units=20,
        )
        card = engine.freight.corridor("CN-FRU-AUTO-EXPRESS-WHITE")
        quote = engine.freight.quote_corridor(card, small)
        assert quote.base_freight_usd == D("23.750")
        assert quote.min_charge_applied is True
        assert quote.freight_usd == D("400")

    def test_category_multiplier_for_cargo_electronics(self, engine: VEDCalculatorEngine) -> None:
        gadgets = CargoSpec(
            category=CargoCategory.ELECTRONICS,
            total_weight_kg=100,
            total_volume_m3="0.4",
            declared_value_origin=5000,
            origin_currency=Currency.USD,
            quantity_units=100,
        )
        card = engine.freight.corridor("CN-FRU-AUTO-EXPRESS-CARGO")
        quote = engine.freight.quote_corridor(card, gadgets)
        assert quote.category_multiplier == D("1.35")
        assert quote.rate_per_kg_usd == D("4.5900")
        assert quote.freight_usd == D("459.0000")


class TestCatalogue:
    def test_corridors_for_filters_by_origin_service_and_hub(
        self, engine: VEDCalculatorEngine
    ) -> None:
        white_kg = engine.freight.corridors_for(
            OriginCountry.CHINA, ServiceKind.WHITE_FREIGHT, BISHKEK
        )
        cargo_kg = engine.freight.corridors_for(
            OriginCountry.CHINA, ServiceKind.CARGO_ALL_IN, BISHKEK
        )
        white_ru = engine.freight.corridors_for(
            OriginCountry.CHINA, ServiceKind.WHITE_FREIGHT, MOSCOW
        )
        assert {c.transport_mode for c in white_kg} == {
            TransportMode.AUTO_EXPRESS,
            TransportMode.AUTO_STANDARD,
            TransportMode.RAIL,
            TransportMode.AIR,
        }
        assert len(cargo_kg) == 3
        assert all(c.destination_hub == MOSCOW for c in white_ru) and len(white_ru) == 3
        assert engine.freight.corridors_for("turkey", "white_freight", BISHKEK)

    def test_every_origin_has_bishkek_white_and_cargo_corridors(
        self, engine: VEDCalculatorEngine
    ) -> None:
        for origin in OriginCountry:
            assert engine.freight.corridors_for(origin, ServiceKind.WHITE_FREIGHT, BISHKEK), origin
            assert engine.freight.corridors_for(origin, ServiceKind.CARGO_ALL_IN, BISHKEK), origin
            assert engine.freight.corridors_for(origin, ServiceKind.WHITE_FREIGHT, MOSCOW), origin

    def test_hubs_for_origin(self, engine: VEDCalculatorEngine) -> None:
        assert engine.freight.hubs_for(OriginCountry.CHINA) == [BISHKEK, MOSCOW]

    def test_unknown_corridor_raises(self, engine: VEDCalculatorEngine) -> None:
        with pytest.raises(KeyError):
            engine.freight.corridor("NOPE")

    def test_duplicate_corridor_ids_rejected(self) -> None:
        card = DEFAULT_CORRIDORS[0]
        with pytest.raises(ValueError, match="unique"):
            FreightService(corridors=[card, card])


class TestDomesticLegs:
    @pytest.mark.parametrize("spelling", ["Tyumen", "тюмень", " TYUMEN ", "Тюмень"])
    def test_city_aliases_resolve(self, engine: VEDCalculatorEngine, spelling: str) -> None:
        legs, is_fallback = engine.freight.domestic_legs_for(BISHKEK, spelling)
        assert is_fallback is False
        assert {leg.destination_city for leg in legs} == {"tyumen"}
        assert {leg.transport_mode for leg in legs} == {TransportMode.TRUCK}

    def test_moscow_offers_truck_and_air(self, engine: VEDCalculatorEngine) -> None:
        legs, _ = engine.freight.domestic_legs_for(BISHKEK, "Москва")
        assert {leg.transport_mode for leg in legs} == {TransportMode.TRUCK, TransportMode.AIR}

    def test_unknown_city_uses_flagged_fallback(self, engine: VEDCalculatorEngine) -> None:
        legs, is_fallback = engine.freight.domestic_legs_for(BISHKEK, "Nizhny Novgorod")
        assert is_fallback is True
        assert len(legs) == 1
        assert legs[0].destination_city == "nizhny_novgorod"
        assert legs[0].rate_per_kg_rub == D("48")

    def test_domestic_quote_tyumen(
        self, engine: VEDCalculatorEngine, sneakers_cargo: CargoSpec
    ) -> None:
        legs, _ = engine.freight.domestic_legs_for(BISHKEK, "Tyumen")
        quote = engine.freight.quote_domestic(legs[0], sneakers_cargo)
        assert quote.chargeable_weight_kg == D("625.0")
        assert quote.cost_rub == D("21875.0")  # 625 × 35 RUB
        assert quote.min_charge_applied is False

    def test_domestic_minimum_charge(self, engine: VEDCalculatorEngine) -> None:
        small = CargoSpec(
            category=CargoCategory.GENERAL,
            total_weight_kg=10,
            total_volume_m3="0.05",
            declared_value_origin=200,
            origin_currency=Currency.USD,
            quantity_units=20,
        )
        legs, _ = engine.freight.domestic_legs_for(BISHKEK, "Tyumen")
        quote = engine.freight.quote_domestic(legs[0], small)
        assert quote.min_charge_applied is True
        assert quote.cost_rub == D("10000")

    def test_both_hubs_serve_the_same_cities_by_truck(self, engine: VEDCalculatorEngine) -> None:
        def cities(hub: str) -> set[str]:
            return {
                leg.destination_city
                for leg in engine.freight.domestic_legs
                if leg.from_hub == hub and leg.transport_mode is TransportMode.TRUCK
            }

        assert cities(BISHKEK) == cities(MOSCOW)
        assert "tyumen" in cities(BISHKEK)
