"""End-to-end tests against real-world sample shipments and the service contracts.

The expected figures are recomputed here by hand from the specification
formulas (sections 2.A–2.D) with the round FX table from ``conftest.py``.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from ved_calculator import VEDCalculationRequest, VEDCalculatorEngine, calculate
from ved_calculator.__main__ import EXAMPLE_REQUEST
from ved_calculator.domain.models import (
    CargoCategory,
    CargoSpec,
    ClearanceType,
    Currency,
    OriginCountry,
    RiskLevel,
    RouteComparisonResult,
    TransportMode,
)

D = Decimal
CENT = D("0.01")


def q2(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


class TestSneakersChinaBishkekTyumen:
    """500 kg / 2.5 m³ / 400 pairs of sneakers, USD 12 000, Guangzhou → Bishkek → Tyumen."""

    ROUTE_ID = "china-bishkek-official-eaeu-kg-auto-express-truck-tyumen"

    def test_white_customs_auto_express_matches_specification_formulas(
        self, engine: VEDCalculatorEngine, sneakers_request: VEDCalculationRequest
    ) -> None:
        route = engine.calculate(sneakers_request).route(self.ROUTE_ID)
        assert route is not None

        usd_kgs, usd_rub, kgs_rub, eur_kgs = D(90), D(90), D(1), D(100)
        delta = D("0.025")  # δ_fx
        value_usd = D(12000)

        # 2.A volumetric & freight: chargeable = max(500, 2.5 m³ × 250) = 625 kg
        chargeable = D(625)
        freight_usd = chargeable * D("1.90")  # 1 187.50
        handling_usd = D(80) + D("0.08") * chargeable  # 130
        insurance_usd = value_usd * D("0.004")  # 48
        bank1_usd = max(value_usd * D("0.002"), D(30)) + value_usd * D("0.006")  # 30 + 72

        # 2.B official EAEU clearance in Bishkek (official rates, no buffer)
        invoice_kgs = value_usd * usd_kgs  # 1 080 000
        freight_kgs = freight_usd * usd_kgs  # 106 875
        duty_kgs = D("0.47") * 400 * eur_kgs  # 18 800
        vat_kgs = (invoice_kgs + duty_kgs + freight_kgs) * D("0.12")  # 144 681
        proc_kgs = min(max(invoice_kgs * D("0.004"), D(500)), D(250000))  # 4 320
        broker_kgs = D(20000)

        # RUB at mid rate + one δ_fx premium per foreign-currency component
        mid = {
            "goods_value": value_usd * usd_rub,
            "international_freight": freight_usd * usd_rub,
            "hub_handling": handling_usd * usd_rub,
            "insurance": insurance_usd * usd_rub,
            "customs_duty": duty_kgs * kgs_rub,
            "customs_processing_fee": proc_kgs * kgs_rub,
            "broker_fee": broker_kgs * kgs_rub,
            "import_vat_kg": vat_kgs * kgs_rub,
        }
        bank1_rub = bank1_usd * usd_rub
        foreign_total = sum(mid.values()) + bank1_rub
        fx_buffer = foreign_total * delta
        osoo_outlays = foreign_total * (1 + delta)

        # 2.C intra-EAEU transfer: ОсОО markup, RU import VAT 22 %, RUB→KGS clearing
        markup = osoo_outlays * D("0.02")
        transfer_price = osoo_outlays + markup
        vat_ru = transfer_price * D("0.22")
        bank2_rub = min(max(transfer_price * D("0.005"), D(1500)), D(30000)) + transfer_price * D(
            "0.01"
        )

        # Russian-side compliance & on-carriage
        certification = D(18000)
        marking = D(400) * (D("0.60") + D(12))
        local_transport = chargeable * D(35)  # 21 875

        expected = {
            **mid,
            "certification_fee": certification,
            "marking_fee": marking,
            "technology_fee": D(0),
            "import_vat_ru": vat_ru,
            "bank_fees": bank1_rub + bank2_rub,
            "fx_risk_buffer": fx_buffer,
            "agent_markup": markup,
            "payment_agent_fee": D(0),
            "local_transport": local_transport,
        }
        expected = {key: q2(val) for key, val in expected.items()}
        assert route.breakdown == expected

        # 2.D total landed cost and per-unit cost
        total = sum(expected.values(), D(0))
        assert route.total_cost_rub == total == D("1852424.40")
        assert route.cost_per_unit_rub == q2(total / 400) == D("4631.06")
        assert route.cost_per_kg_rub == q2(total / 500)
        assert route.chargeable_weight_kg == chargeable
        assert route.fx_rates_used["USD/KGS"] == D("90.0000")
        assert route.fx_rates_used["EUR/KGS"] == D("100.0000")
        assert route.risk_level is RiskLevel.LOW_LEGAL
        assert (route.estimated_days_min, route.estimated_days_max) == (16, 25)

    def test_cargo_auto_express_total(
        self, engine: VEDCalculatorEngine, sneakers_request: VEDCalculationRequest
    ) -> None:
        route = engine.calculate(sneakers_request).route(
            "china-bishkek-cargo-simplified-auto-express-truck-tyumen"
        )
        assert route is not None
        delta = D("0.025")
        goods = D(12000) * 90
        bank1 = (D(30) + D(72)) * 90
        freight = D(500) * D("3.40") * 90  # density 200 kg/m³ → actual weight, all-in rate
        insurance = D(12000) * D("0.01") * 90
        foreign = goods + bank1 + freight + insurance
        outlays = foreign * (1 + delta)
        markup = outlays * D("0.02")
        transfer = outlays + markup
        bank2 = min(max(transfer * D("0.005"), D(1500)), D(30000)) + transfer * D("0.01")
        total = sum(
            q2(x)
            for x in (goods, bank1 + bank2, freight, insurance, foreign * delta, markup, D(21875))
        )
        assert route.total_cost_rub == total == D("1351515.45")
        assert route.breakdown["customs_duty"] == 0 and route.breakdown["import_vat_ru"] == 0
        assert route.risk_level is RiskLevel.HIGH_CUSTOMS

    def test_ranking_for_the_sample_shipment(
        self, engine: VEDCalculatorEngine, sneakers_request: VEDCalculationRequest
    ) -> None:
        result = engine.calculate(sneakers_request)
        assert (
            result.cheapest_route_id == "china-bishkek-cargo-simplified-auto-standard-truck-tyumen"
        )
        assert result.fastest_route_id == "china-bishkek-cargo-simplified-air-truck-tyumen"
        assert (
            result.optimal_route_id == "china-bishkek-official-eaeu-kg-auto-standard-truck-tyumen"
        )
        assert result.cheapest_legal_route_id == result.optimal_route_id
        assert result.fx_as_of.isoformat() == "2026-09-28"


class TestJeansChinaCny:
    """300 kg of jeans (ТН ВЭД 6203 42), 1 000 pcs, CNY 60 000 → Moscow: formula B in CNY."""

    def test_combined_duty_and_vat_in_cny(self, engine: VEDCalculatorEngine) -> None:
        request = VEDCalculationRequest(
            origin_country=OriginCountry.CHINA,
            destination_city_ru="Moscow",
            cargo=CargoSpec(
                category=CargoCategory.APPAREL,
                hs_code="6203 42 310 0",
                total_weight_kg=300,
                total_volume_m3="1.5",
                declared_value_origin=60000,
                origin_currency=Currency.CNY,
                quantity_units=1000,
            ),
            allow_cargo_simplified=False,
        )
        route = engine.calculate(request).route(
            "china-bishkek-official-eaeu-kg-auto-standard-truck-moscow"
        )
        assert route is not None
        base_kgs = D(60000) * D("12.5")  # CNY→KGS = 90 / 7.2
        duty_kgs = max(base_kgs * D("0.10"), D("1.88") * 300 * 100)  # 75 000 vs 56 400
        freight_usd = max(D(300), D("1.5") * 250) * D("1.35")  # 375 kg × 1.35
        vat_kgs = (base_kgs + duty_kgs + freight_usd * 90) * D("0.12")
        assert route.breakdown["customs_duty"] == q2(duty_kgs)  # KGS→RUB = 1
        assert route.breakdown["import_vat_kg"] == q2(vat_kgs)
        assert route.breakdown["goods_value"] == q2(D(60000) * D("12.5"))  # CNY→RUB = 12.5
        assert route.fx_rates_used["CNY/KGS"] == D("12.5000")
        assert route.breakdown["marking_fee"] == D("12600.00")  # 1 000 × (0.60 + 12)


class TestOtherCorridors:
    def test_turkey_apparel_by_air_uses_eur_swift(self, engine: VEDCalculatorEngine) -> None:
        request = VEDCalculationRequest(
            origin_country="turkey",
            destination_city_ru="Yekaterinburg",
            cargo=CargoSpec(
                category="apparel",
                hs_code="6110 20",
                total_weight_kg=200,
                total_volume_m3="1.4",
                declared_value_origin=9000,
                origin_currency="EUR",
                quantity_units=600,
            ),
        )
        result = engine.calculate(request)
        assert result.fastest is not None and result.fastest.transport_mode is TransportMode.AIR
        white_air = result.route("turkey-bishkek-official-eaeu-kg-air-truck-yekaterinburg")
        assert white_air is not None
        bank1_eur = max(D(9000) * D("0.002"), D(30)) + D(9000) * D("0.006")  # 30 + 54 EUR
        assert white_air.breakdown["bank_fees"] > q2(bank1_eur * 100)
        assert white_air.breakdown["customs_duty"] == q2(D("1.75") * 200 * 100)  # 1.75 EUR/kg

    @pytest.mark.parametrize("origin", ["EU", "USA", "UAE", "VIETNAM"])
    def test_every_origin_yields_ranked_routes(
        self, engine: VEDCalculatorEngine, origin: str
    ) -> None:
        request = VEDCalculationRequest(
            origin_country=origin,
            destination_city_ru="Novosibirsk",
            include_direct_ru_benchmark=True,
            cargo=CargoSpec(
                category=CargoCategory.GENERAL,
                hs_code="3924100000",
                total_weight_kg=120,
                total_volume_m3="0.9",
                declared_value_origin=4000,
                origin_currency=Currency.USD,
                quantity_units=800,
            ),
        )
        result = engine.calculate(request)
        assert result.routes and result.optimal is not None and result.cheapest is not None
        assert {r.clearance_type for r in result.routes} == set(ClearanceType)
        assert all(
            r.total_cost_rub > 0 and r.estimated_days_min <= r.estimated_days_max
            for r in result.routes
        )
        assert all(sum(r.breakdown.values()) == r.total_cost_rub for r in result.routes)
        white = [r for r in result.routes if r.clearance_type is not ClearanceType.CARGO_SIMPLIFIED]
        assert all(r.breakdown["customs_duty"] > 0 for r in white)  # 6.5 % ad valorem

    def test_electronics_from_eu(self, engine: VEDCalculatorEngine) -> None:
        request = VEDCalculationRequest(
            origin_country=OriginCountry.EU,
            destination_city_ru="Kazan",
            cargo=CargoSpec(
                category=CargoCategory.ELECTRONICS,
                hs_code="8471300000",
                total_weight_kg=80,
                total_volume_m3="0.5",
                declared_value_origin=40000,
                origin_currency=Currency.EUR,
                quantity_units=50,
            ),
        )
        result = engine.calculate(request)
        cargo = [r for r in result.routes if r.clearance_type is ClearanceType.CARGO_SIMPLIFIED]
        assert cargo and all(r.risk_level is RiskLevel.HIGH_CUSTOMS for r in cargo)
        white = [r for r in result.routes if r.clearance_type is ClearanceType.OFFICIAL_EAEU_KG]
        assert white and all(r.breakdown["customs_duty"] == 0 for r in white)  # laptops 0 %
        assert all(r.breakdown["marking_fee"] == 0 for r in white)
        assert all(r.breakdown["certification_fee"] == D("45000.00") for r in white)


class TestContracts:
    def test_case_insensitive_enums_and_dict_requests(self, engine: VEDCalculatorEngine) -> None:
        result = engine.calculate(
            {
                "origin_country": "china",
                "destination_city_ru": "тюмень",
                "cargo": {
                    "category": "Footwear",
                    "total_weight_kg": "500",
                    "total_volume_m3": 2.5,
                    "declared_value_origin": 12000,
                    "origin_currency": "usd",
                    "quantity_units": 400,
                },
            }
        )
        assert result.request.origin_country is OriginCountry.CHINA
        assert result.request.cargo.origin_currency is Currency.USD
        assert result.request.cargo.total_volume_m3 == D("2.5")
        assert result.routes

    @pytest.mark.parametrize(
        "patch",
        [
            {"total_weight_kg": 0},
            {"declared_value_origin": -1},
            {"origin_currency": "GBP"},
            {"quantity_units": 0},
            {"category": "toys"},
            {"unknown_field": 1},
        ],
    )
    def test_invalid_cargo_rejected(self, patch: dict[str, object]) -> None:
        cargo = {
            "category": "footwear",
            "total_weight_kg": 500,
            "total_volume_m3": 2.5,
            "declared_value_origin": 12000,
            "origin_currency": "USD",
            "quantity_units": 400,
        }
        with pytest.raises(ValidationError):
            CargoSpec.model_validate({**cargo, **patch})

    def test_request_bounds(self, sneakers_cargo: CargoSpec) -> None:
        with pytest.raises(ValidationError):
            VEDCalculationRequest(
                origin_country="CHINA", cargo=sneakers_cargo, fx_risk_buffer_percent=D("11")
            )
        with pytest.raises(ValidationError):
            VEDCalculationRequest(
                origin_country="CHINA", cargo=sneakers_cargo, destination_city_ru="  "
            )
        with pytest.raises(ValidationError):
            VEDCalculationRequest(origin_country="MARS", cargo=sneakers_cargo)

    def test_result_schema_fields(
        self, engine: VEDCalculatorEngine, sneakers_request: VEDCalculationRequest
    ) -> None:
        route = engine.calculate(sneakers_request).routes[0]
        assert isinstance(route, RouteComparisonResult)
        required = {
            "route_id",
            "route_name",
            "clearance_type",
            "total_cost_rub",
            "cost_per_unit_rub",
            "estimated_days_min",
            "estimated_days_max",
            "breakdown",
            "is_recommended",
            "risk_level",
        }
        dumped = route.model_dump(mode="json")
        assert required <= set(dumped)
        assert isinstance(dumped["total_cost_rub"], str)  # Decimal precision preserved in JSON
        assert set(dumped["breakdown"]) >= {
            "international_freight",
            "customs_duty",
            "import_vat_kg",
            "import_vat_ru",
            "fx_risk_buffer",
            "bank_fees",
            "agent_markup",
            "local_transport",
        }

    def test_module_level_calculate_uses_default_reference_data(
        self, sneakers_request: VEDCalculationRequest
    ) -> None:
        result = calculate(sneakers_request)
        assert result.routes and result.optimal is not None
        assert result.fx_as_of.year >= 2026

    def test_specification_module_facades(self) -> None:
        from ved_calculator import customs, fx_engine, optimizer, router

        assert customs.CustomsService and router.FreightService
        assert fx_engine.FxService and optimizer.RouteOptimizer


class TestCli:
    def _run(self, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "ved_calculator", *args],
            input=stdin,
            capture_output=True,
            text=True,
            check=True,
            cwd=Path(__file__).resolve().parents[1],
        )

    def test_example_and_calculate(self, tmp_path: Path) -> None:
        example = json.loads(self._run("example").stdout)
        assert example == EXAMPLE_REQUEST
        request_file = tmp_path / "request.json"
        request_file.write_text(json.dumps(example), encoding="utf-8")
        payload = json.loads(self._run("calculate", str(request_file)).stdout)
        assert payload["routes"] and payload["optimal_route_id"]
        assert payload["routes"][0]["total_cost_rub"]

    def test_stdin_and_matrix(self) -> None:
        out = self._run("calculate", "-", "--matrix", stdin=json.dumps(EXAMPLE_REQUEST)).stdout
        assert "China-Bishkek-White-Customs" in out and "OPTIMAL" in out

    def test_reference_listings(self) -> None:
        assert "6404110000" in self._run("tariffs").stdout
        assert "CN-FRU-AUTO-EXPRESS-CARGO" in self._run("corridors", "CHINA").stdout


@pytest.mark.skipif(
    importlib.util.find_spec("fastapi") is None, reason="fastapi extra not installed"
)
def test_http_api_calculate() -> None:
    from fastapi.testclient import TestClient

    from ved_calculator.api import create_app

    client = TestClient(create_app())
    assert client.get("/health").json()["status"] == "ok"
    response = client.post("/v1/calculate", json=EXAMPLE_REQUEST)
    assert response.status_code == 200
    assert response.json()["optimal_route_id"]
    bad = client.post("/v1/calculate", json={"origin_country": "MARS"})
    assert bad.status_code == 422
