"""Module 4 — route optimisation tests."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from ved_calculator import VEDCalculationRequest, VEDCalculatorEngine
from ved_calculator.domain.models import (
    CalculationAssumptions,
    CargoCategory,
    CargoSpec,
    ClearanceType,
    Currency,
    OptimizationPolicy,
    OptimizationResult,
    OriginCountry,
    RecipientTaxRegime,
    RiskLevel,
    TransportMode,
)

D = Decimal

WHITE_EXPRESS = "china-bishkek-official-eaeu-kg-auto-express-truck-tyumen"
CARGO_EXPRESS = "china-bishkek-cargo-simplified-auto-express-truck-tyumen"


def _assert_consistent(result: OptimizationResult) -> None:
    routes = result.routes
    assert routes == sorted(
        routes, key=lambda r: (r.total_cost_rub, r.estimated_days_max, r.route_id)
    )
    assert len({r.route_id for r in routes + result.excluded_routes}) == len(routes) + len(
        result.excluded_routes
    )
    assert sum(r.is_recommended for r in routes) == 1
    assert result.optimal is not None and result.optimal.is_recommended
    assert result.cheapest is not None and result.cheapest.total_cost_rub == min(
        r.total_cost_rub for r in routes
    )
    assert result.fastest is not None and result.fastest.estimated_days_max == min(
        r.estimated_days_max for r in routes
    )
    for route in routes + result.excluded_routes:
        assert sum(route.breakdown.values()) == route.total_cost_rub
        assert route.estimated_days_min <= route.estimated_days_max
        assert route.total_cost_rub > 0
        assert set(route.breakdown) == set(route.breakdown)  # dict keys stable


class TestEnumeration:
    def test_default_families(
        self, engine: VEDCalculatorEngine, sneakers_request: VEDCalculationRequest
    ) -> None:
        result = engine.calculate(sneakers_request)
        assert {r.clearance_type for r in result.routes} == {
            ClearanceType.OFFICIAL_EAEU_KG,
            ClearanceType.CARGO_SIMPLIFIED,
        }
        assert all(r.hub == "Bishkek" for r in result.routes)
        assert len(result.routes) == 7  # 4 white + 3 cargo corridors × 1 truck leg

    def test_flags_filter_families(
        self, engine: VEDCalculatorEngine, sneakers_request: VEDCalculationRequest
    ) -> None:
        only_white = engine.calculate(
            sneakers_request.model_copy(update={"allow_cargo_simplified": False})
        )
        assert {r.clearance_type for r in only_white.routes} == {ClearanceType.OFFICIAL_EAEU_KG}
        with_direct = engine.calculate(
            sneakers_request.model_copy(update={"include_direct_ru_benchmark": True})
        )
        direct = [
            r for r in with_direct.routes if r.clearance_type is ClearanceType.OFFICIAL_RU_DIRECT
        ]
        assert len(direct) == 3 and all(r.hub == "Moscow" for r in direct)

    def test_all_families_disabled_is_rejected(self, sneakers_cargo: CargoSpec) -> None:
        with pytest.raises(ValidationError, match="at least one route family"):
            VEDCalculationRequest(
                origin_country=OriginCountry.CHINA,
                cargo=sneakers_cargo,
                allow_cargo_simplified=False,
                allow_white_customs=False,
            )

    def test_moscow_adds_air_domestic_leg(
        self, engine: VEDCalculatorEngine, sneakers_request: VEDCalculationRequest
    ) -> None:
        result = engine.calculate(
            sneakers_request.model_copy(update={"destination_city_ru": "Москва"})
        )
        air = [r for r in result.routes if r.domestic_transport_mode is TransportMode.AIR]
        assert air and all(r.route_name.endswith("+Air") for r in air)
        assert len(result.routes) == 14

    def test_route_naming(
        self, engine: VEDCalculatorEngine, sneakers_request: VEDCalculationRequest
    ) -> None:
        result = engine.calculate(sneakers_request)
        route = result.route(WHITE_EXPRESS)
        assert route is not None
        assert route.route_name == "China-Bishkek-White-Customs-Auto-Express"
        assert route.destination_city_ru == "Tyumen"


class TestRanking:
    def test_consistency_invariants(
        self, engine: VEDCalculatorEngine, sneakers_request: VEDCalculationRequest
    ) -> None:
        _assert_consistent(engine.calculate(sneakers_request))

    def test_recommendation_is_legal_cheapest_is_cargo(
        self, engine: VEDCalculatorEngine, sneakers_request: VEDCalculationRequest
    ) -> None:
        result = engine.calculate(sneakers_request)
        assert (
            result.cheapest is not None
            and result.cheapest.clearance_type is ClearanceType.CARGO_SIMPLIFIED
        )
        assert result.optimal is not None and result.optimal.risk_level is RiskLevel.LOW_LEGAL
        assert result.cheapest_legal is not None
        assert result.cheapest_legal.clearance_type is ClearanceType.OFFICIAL_EAEU_KG
        assert "CHEAPEST" in result.cheapest.labels
        assert "OPTIMAL" in result.optimal.labels
        assert "CHEAPEST_LEGAL" in result.cheapest_legal.labels
        assert "Optimal (recommended)" in result.summary

    def test_risk_adjusted_cost_formula(
        self, engine: VEDCalculatorEngine, sneakers_request: VEDCalculationRequest
    ) -> None:
        result = engine.calculate(sneakers_request)
        cargo = result.route(CARGO_EXPRESS)
        assert cargo is not None and cargo.risk_adjusted_cost_rub is not None
        expected = cargo.total_cost_rub * (D(1) + D("0.001") * cargo.estimated_days_max + D("0.35"))
        assert cargo.risk_adjusted_cost_rub == expected.quantize(D("0.01"))

    def test_policy_without_legal_preference_can_recommend_cargo(
        self, round_fx, sneakers_request: VEDCalculationRequest
    ) -> None:
        policy = OptimizationPolicy(
            delay_cost_percent_per_day=0,
            expected_loss_percent={level: D("0") for level in RiskLevel},
            prefer_legal_routes=False,
        )
        result = VEDCalculatorEngine(fx_table=round_fx, policy=policy).calculate(sneakers_request)
        assert result.optimal_route_id == result.cheapest_route_id

    def test_delay_cost_favours_fast_routes(
        self, round_fx, sneakers_request: VEDCalculationRequest
    ) -> None:
        policy = OptimizationPolicy(
            delay_cost_percent_per_day=5,
            expected_loss_percent={level: D("0") for level in RiskLevel},
            prefer_legal_routes=False,
        )
        result = VEDCalculatorEngine(fx_table=round_fx, policy=policy).calculate(sneakers_request)
        assert result.optimal_route_id == result.fastest_route_id

    def test_policy_requires_all_risk_levels(self) -> None:
        with pytest.raises(ValidationError):
            OptimizationPolicy(expected_loss_percent={RiskLevel.LOW_LEGAL: D("1")})

    def test_determinism_and_json_roundtrip(
        self, engine: VEDCalculatorEngine, sneakers_request: VEDCalculationRequest
    ) -> None:
        first = engine.calculate(sneakers_request)
        second = engine.calculate(sneakers_request)
        assert first.model_dump() == second.model_dump()
        assert OptimizationResult.model_validate_json(first.model_dump_json()) == first

    def test_comparison_matrix(
        self, engine: VEDCalculatorEngine, sneakers_request: VEDCalculationRequest
    ) -> None:
        rows = engine.calculate(sneakers_request).comparison_matrix()
        assert len(rows) == 7
        assert all(row["feasible"] for row in rows)
        assert {"route_id", "total_cost_rub", "days", "risk_level", "labels"} <= set(rows[0])


class TestConstraints:
    def test_deadline_excludes_slow_routes(
        self, engine: VEDCalculatorEngine, sneakers_request: VEDCalculationRequest
    ) -> None:
        result = engine.calculate(
            sneakers_request.model_copy(update={"target_delivery_days_max": 20})
        )
        assert result.routes and all(r.estimated_days_max <= 20 for r in result.routes)
        assert result.excluded_routes and all(
            r.estimated_days_max > 20 for r in result.excluded_routes
        )
        assert all(
            r.meets_deadline is False and r.constraint_violations for r in result.excluded_routes
        )
        assert all(r.meets_deadline is True for r in result.routes)
        _assert_consistent(result)

    def test_impossible_deadline_falls_back_with_warning(
        self, engine: VEDCalculatorEngine, sneakers_request: VEDCalculationRequest
    ) -> None:
        result = engine.calculate(
            sneakers_request.model_copy(update={"target_delivery_days_max": 5})
        )
        assert not result.excluded_routes and len(result.routes) == 7
        assert any("No route meets" in w for w in result.warnings)
        assert result.optimal is not None

    def test_fallback_city_is_flagged(
        self, engine: VEDCalculatorEngine, sneakers_request: VEDCalculationRequest
    ) -> None:
        result = engine.calculate(
            sneakers_request.model_copy(update={"destination_city_ru": "Nizhny Novgorod"})
        )
        assert any("fallback" in w for w in result.warnings)
        assert all(any("fallback" in n for n in r.notes) for r in result.routes)
        assert all(r.destination_city_ru == "Nizhny Novgorod" for r in result.routes)

    def test_fx_buffer_outside_band_warns_and_zero_buffer_removes_component(
        self, engine: VEDCalculatorEngine, sneakers_request: VEDCalculationRequest
    ) -> None:
        high = engine.calculate(
            sneakers_request.model_copy(update={"fx_risk_buffer_percent": D("5")})
        )
        assert any("outside the recommended" in w for w in high.warnings)
        zero = engine.calculate(
            sneakers_request.model_copy(update={"fx_risk_buffer_percent": D("0")})
        )
        assert all(r.breakdown["fx_risk_buffer"] == 0 for r in zero.routes)
        assert all(
            r.total_cost_rub < h.total_cost_rub
            for r, h in zip(zero.routes, high.routes, strict=True)
        )


class TestRouteFamilies:
    def test_cargo_route_has_no_customs_components(
        self, engine: VEDCalculatorEngine, sneakers_request: VEDCalculationRequest
    ) -> None:
        route = engine.calculate(sneakers_request).route(CARGO_EXPRESS)
        assert route is not None
        for key in (
            "customs_duty",
            "import_vat_kg",
            "import_vat_ru",
            "broker_fee",
            "certification_fee",
            "marking_fee",
            "customs_processing_fee",
        ):
            assert route.breakdown[key] == 0, key
        assert route.risk_level is RiskLevel.HIGH_CUSTOMS and route.risk_score == 80

    def test_general_cargo_is_medium_risk(self, engine: VEDCalculatorEngine) -> None:
        request = VEDCalculationRequest(
            origin_country=OriginCountry.CHINA,
            cargo=CargoSpec(
                category=CargoCategory.GENERAL,
                total_weight_kg=300,
                total_volume_m3=2,
                declared_value_origin=5000,
                origin_currency=Currency.USD,
                quantity_units=1000,
            ),
        )
        result = engine.calculate(request)
        cargo = [r for r in result.routes if r.clearance_type is ClearanceType.CARGO_SIMPLIFIED]
        assert cargo and all(r.risk_level is RiskLevel.MEDIUM_TRANSIT for r in cargo)

    def test_white_route_components(
        self, engine: VEDCalculatorEngine, sneakers_request: VEDCalculationRequest
    ) -> None:
        route = engine.calculate(sneakers_request).route(WHITE_EXPRESS)
        assert route is not None
        for key in (
            "customs_duty",
            "import_vat_kg",
            "import_vat_ru",
            "broker_fee",
            "certification_fee",
            "marking_fee",
            "agent_markup",
            "bank_fees",
        ):
            assert route.breakdown[key] > 0, key
        assert route.breakdown["payment_agent_fee"] == 0
        assert route.risk_level is RiskLevel.LOW_LEGAL

    def test_osno_makes_ru_vat_recoverable(
        self, engine: VEDCalculatorEngine, sneakers_request: VEDCalculationRequest
    ) -> None:
        usn = engine.calculate(sneakers_request).route(WHITE_EXPRESS)
        osno = engine.calculate(
            sneakers_request.model_copy(
                update={
                    "assumptions": CalculationAssumptions(
                        recipient_tax_regime=RecipientTaxRegime.OSNO
                    )
                }
            )
        ).route(WHITE_EXPRESS)
        assert usn is not None and osno is not None
        assert osno.breakdown["import_vat_ru"] == 0
        assert osno.recoverable_vat_rub == usn.breakdown["import_vat_ru"]
        assert usn.total_cost_rub - osno.total_cost_rub == osno.recoverable_vat_rub

    def test_kg_vat_recoverable_lowers_total(
        self, engine: VEDCalculatorEngine, sneakers_request: VEDCalculationRequest
    ) -> None:
        base = engine.calculate(sneakers_request).route(WHITE_EXPRESS)
        recov = engine.calculate(
            sneakers_request.model_copy(
                update={"assumptions": CalculationAssumptions(kg_import_vat_recoverable=True)}
            )
        ).route(WHITE_EXPRESS)
        assert base is not None and recov is not None
        assert recov.breakdown["import_vat_kg"] == 0
        assert recov.recoverable_vat_rub == base.breakdown["import_vat_kg"]
        # markup, RU VAT and bank fees shrink with the smaller transfer price
        assert base.total_cost_rub - recov.total_cost_rub > recov.recoverable_vat_rub

    def test_direct_benchmark_components(
        self, engine: VEDCalculatorEngine, sneakers_request: VEDCalculationRequest
    ) -> None:
        result = engine.calculate(
            sneakers_request.model_copy(update={"include_direct_ru_benchmark": True})
        )
        route = result.route("china-moscow-official-ru-direct-auto-standard-truck-tyumen")
        assert route is not None
        assert route.breakdown["payment_agent_fee"] == D("44280.00")  # 4 % of buffered goods value
        assert route.breakdown["customs_processing_fee"] == D("4924.00")
        assert route.breakdown["broker_fee"] == D("25000.00")
        assert route.breakdown["import_vat_kg"] == 0
        assert route.breakdown["agent_markup"] == 0
        assert route.risk_level is RiskLevel.LOW_LEGAL

    def test_margin_reporting(
        self, engine: VEDCalculatorEngine, sneakers_request: VEDCalculationRequest
    ) -> None:
        result = engine.calculate(
            sneakers_request.model_copy(update={"target_sale_price_rub_per_unit": D("6900")})
        )
        route = result.route(WHITE_EXPRESS)
        assert route is not None and route.gross_margin_percent is not None
        expected = ((D("6900") - route.cost_per_unit_rub) / D("6900") * 100).quantize(D("0.01"))
        assert route.gross_margin_percent == expected
        cheap = engine.calculate(
            sneakers_request.model_copy(update={"target_sale_price_rub_per_unit": D("100")})
        )
        assert all(
            r.gross_margin_percent is not None and r.gross_margin_percent < 0 for r in cheap.routes
        )
        assert all(any("Negative gross margin" in n for n in r.notes) for r in cheap.routes)

    @pytest.mark.parametrize(
        ("calc_date", "expected_fee"),
        [(date(2026, 11, 30), D("0")), (date(2026, 12, 1), D("37300.00"))],
    )
    def test_technology_fee_from_effective_date(
        self, engine: VEDCalculatorEngine, calc_date: date, expected_fee: Decimal
    ) -> None:
        request = VEDCalculationRequest(
            origin_country=OriginCountry.CHINA,
            cargo=CargoSpec(
                category=CargoCategory.ELECTRONICS,
                hs_code="8517130000",
                total_weight_kg=50,
                total_volume_m3="0.3",
                declared_value_origin=20000,
                origin_currency=Currency.USD,
                quantity_units=100,
            ),
            allow_cargo_simplified=False,
            assumptions=CalculationAssumptions(calculation_date=calc_date),
        )
        result = engine.calculate(request)
        assert result.routes and all(
            r.breakdown["technology_fee"] == expected_fee for r in result.routes
        )
        assert all(r.breakdown["customs_duty"] == 0 for r in result.routes)  # smartphones 0 %

    def test_days_composition(
        self, engine: VEDCalculatorEngine, sneakers_request: VEDCalculationRequest
    ) -> None:
        route = engine.calculate(sneakers_request).route(WHITE_EXPRESS)
        assert route is not None
        assert (route.estimated_days_min, route.estimated_days_max) == (10 + 2 + 4, 14 + 4 + 7)
