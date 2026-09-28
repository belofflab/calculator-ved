"""Module 1 — customs & tariff matrix unit tests."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from ved_calculator import VEDCalculatorEngine
from ved_calculator.domain.models import (
    CargoCategory,
    CargoSpec,
    Currency,
    CustomsValuationBasis,
    DutyRateType,
    FeeTier,
    Jurisdiction,
    SpecificRateUnit,
    TariffEntry,
    TariffMatrix,
    TieredFeeRule,
)
from ved_calculator.reference.fees import RU_TAX_PROFILE
from ved_calculator.reference.tariffs import DEFAULT_TARIFF_MATRIX, TARIFF_ENTRIES
from ved_calculator.services.customs_service import CustomsService
from ved_calculator.services.fx_service import FxService

D = Decimal


def _cargo(category: CargoCategory, hs_code: str | None, **overrides: object) -> CargoSpec:
    base: dict[str, object] = {
        "category": category,
        "hs_code": hs_code,
        "total_weight_kg": D("200"),
        "total_volume_m3": D("1"),
        "declared_value_origin": D("2000"),
        "origin_currency": Currency.USD,
        "quantity_units": 100,
    }
    base.update(overrides)
    return CargoSpec.model_validate(base)


class TestTariffResolution:
    def test_exact_match(self) -> None:
        res = DEFAULT_TARIFF_MATRIX.resolve("6404110000", CargoCategory.FOOTWEAR)
        assert res.matched_by == "exact"
        assert res.entry.specific_rate_eur == D("0.47")

    def test_formatted_code_is_normalised(self) -> None:
        cargo = _cargo(CargoCategory.FOOTWEAR, "6404 11 000 0")
        assert cargo.hs_code == "6404110000"

    def test_longest_prefix_match(self) -> None:
        res = DEFAULT_TARIFF_MATRIX.resolve("6203423100", CargoCategory.APPAREL)
        assert res.matched_by == "prefix"
        assert res.entry.hs_code == "620342"

    def test_child_match_for_short_code(self) -> None:
        res = DEFAULT_TARIFF_MATRIX.resolve("6404", CargoCategory.FOOTWEAR)
        assert res.matched_by == "child"
        assert res.entry.hs_code == "6404110000"

    def test_ambiguous_child_match_is_noted(self) -> None:
        res = DEFAULT_TARIFF_MATRIX.resolve("62", CargoCategory.APPAREL)
        assert res.matched_by == "child"
        assert any("different" in note for note in res.notes)

    def test_unknown_code_falls_back_to_category_default(self) -> None:
        res = DEFAULT_TARIFF_MATRIX.resolve("9999", CargoCategory.GENERAL)
        assert res.matched_by == "category_default"
        assert res.entry.is_category_default
        assert any("default" in note for note in res.notes)

    def test_missing_code_uses_category_default(self) -> None:
        res = DEFAULT_TARIFF_MATRIX.resolve(None, CargoCategory.APPAREL)
        assert res.entry.hs_code == "620342"

    def test_category_mismatch_is_noted_and_hs_code_wins(self) -> None:
        res = DEFAULT_TARIFF_MATRIX.resolve("6404110000", CargoCategory.APPAREL)
        assert res.entry.category is CargoCategory.FOOTWEAR
        assert any("takes precedence" in note for note in res.notes)

    def test_unverified_entry_is_flagged(self) -> None:
        res = DEFAULT_TARIFF_MATRIX.resolve("640299", CargoCategory.FOOTWEAR)
        assert res.entry.verified is False
        assert any("reference estimate" in note for note in res.notes)

    @pytest.mark.parametrize("bad", ["ABC", "1", "12345678901", "64.04.x"])
    def test_invalid_hs_code_rejected(self, bad: str) -> None:
        with pytest.raises(ValidationError):
            _cargo(CargoCategory.FOOTWEAR, bad)

    def test_matrix_requires_one_default_per_category(self) -> None:
        with pytest.raises(ValidationError, match="exactly one default"):
            TariffMatrix(entries=[])

    def test_rate_descriptions(self) -> None:
        by_code = {e.hs_code: e for e in TARIFF_ENTRIES}
        assert by_code["6404110000"].rate_description() == "0.47 EUR/pair"
        assert by_code["620342"].rate_description() == "10%, but not less than 1.88 EUR/kg"
        assert by_code["8518309500"].rate_description() == "5% ad valorem"

    def test_reference_table_integrity(self) -> None:
        for entry in TARIFF_ENTRIES:
            assert entry.hs_code == "" or entry.hs_code.isdigit()
            if entry.hs_code == "":
                assert entry.is_category_default
            if entry.rate_type is not DutyRateType.AD_VALOREM:
                assert entry.specific_unit is not None and entry.specific_rate_eur > 0
            if (
                entry.category in (CargoCategory.FOOTWEAR, CargoCategory.APPAREL)
                and entry.hs_code != "6115"
            ):
                assert entry.marking_required, entry.hs_code


class TestDuty:
    def test_specific_rate_per_pair(
        self, engine: VEDCalculatorEngine, fx: FxService, sneakers_cargo: CargoSpec
    ) -> None:
        entry = engine.customs.resolve_tariff(sneakers_cargo).entry
        duty = engine.customs.calculate_duty(
            entry, customs_value=1_080_000, cargo=sneakers_cargo, eur_rate=100
        )
        assert duty.specific_quantity == D("400")
        assert duty.duty == D("18800.00")  # 0.47 EUR × 400 pairs × 100 KGS/EUR
        assert duty.ad_valorem_amount == D("0")

    def test_combined_rate_specific_component_wins_for_cheap_goods(
        self, engine: VEDCalculatorEngine
    ) -> None:
        jeans = _cargo(CargoCategory.APPAREL, "620342")  # 200 kg, USD 2 000 → 180 000 KGS
        entry = engine.customs.resolve_tariff(jeans).entry
        duty = engine.customs.calculate_duty(
            entry, customs_value=180_000, cargo=jeans, eur_rate=100
        )
        assert duty.ad_valorem_amount == D("18000.00")
        assert duty.specific_amount == D("37600.00")  # 1.88 × 200 kg × 100
        assert duty.duty == D("37600.00")

    def test_combined_rate_ad_valorem_wins_for_expensive_goods(
        self, engine: VEDCalculatorEngine
    ) -> None:
        jeans = _cargo(CargoCategory.APPAREL, "620342", declared_value_origin=D("50000"))
        entry = engine.customs.resolve_tariff(jeans).entry
        duty = engine.customs.calculate_duty(
            entry, customs_value=4_500_000, cargo=jeans, eur_rate=100
        )
        assert duty.duty == D("450000.00")

    def test_ad_valorem_rate(self, engine: VEDCalculatorEngine) -> None:
        headphones = _cargo(
            CargoCategory.ELECTRONICS, "8518309500", declared_value_origin=D("10000")
        )
        entry = engine.customs.resolve_tariff(headphones).entry
        duty = engine.customs.calculate_duty(
            entry, customs_value=900_000, cargo=headphones, eur_rate=100
        )
        assert duty.duty == D("45000.00")

    def test_combined_rate_per_piece(self, engine: VEDCalculatorEngine) -> None:
        tvs = _cargo(
            CargoCategory.ELECTRONICS, "852872", quantity_units=10, declared_value_origin=D("1000")
        )
        entry = engine.customs.resolve_tariff(tvs).entry
        duty = engine.customs.calculate_duty(entry, customs_value=90_000, cargo=tvs, eur_rate=100)
        assert duty.specific_unit is SpecificRateUnit.PIECE
        assert duty.duty == D("25500.0")  # 25.5 EUR × 10 pcs × 100 beats 10 % × 90 000


class TestKyrgyzClearance:
    def test_specification_formula_b(
        self, engine: VEDCalculatorEngine, fx: FxService, sneakers_cargo: CargoSpec
    ) -> None:
        res = engine.customs.calculate_clearance(
            Jurisdiction.KG, sneakers_cargo, fx, freight_to_border_usd=D("1187.5")
        )
        assert res.currency is Currency.KGS
        assert res.invoice_value_local == D("1080000")
        assert res.freight_to_border_local == D("106875.0")
        assert res.customs_value == D("1080000")  # INVOICE basis: duty on the invoice only
        assert res.duty.duty == D("18800.00")
        assert res.vat_percent == D("12")
        assert res.vat_base == D("1205675.00")  # invoice + duty + freight
        assert res.vat == D("144681.0000")
        assert res.customs_processing_fee == D("4320.000")  # 0.4 %
        assert res.broker_fee == D("20000")
        assert res.total_taxes_and_fees == D("187801.0000")
        assert res.total_cleared_cost == D("1267801.0000")
        assert (res.clearance_days_min, res.clearance_days_max) == (2, 4)

    def test_cif_basis_counts_freight_once(
        self, engine: VEDCalculatorEngine, fx: FxService
    ) -> None:
        jeans = _cargo(CargoCategory.APPAREL, "620342", declared_value_origin=D("50000"))
        invoice = engine.customs.calculate_clearance(
            Jurisdiction.KG,
            jeans,
            fx,
            freight_to_border_usd=1000,
            valuation_basis=CustomsValuationBasis.INVOICE,
        )
        cif = engine.customs.calculate_clearance(
            Jurisdiction.KG,
            jeans,
            fx,
            freight_to_border_usd=1000,
            valuation_basis=CustomsValuationBasis.CIF,
        )
        assert cif.customs_value == invoice.customs_value + D("90000")
        assert cif.duty.duty == D("459000.00")  # 10 % of (4 500 000 + 90 000)
        assert invoice.duty.duty == D("450000.00")
        # VAT base = customs value + duty (+ freight only when it is not already inside)
        assert invoice.vat_base == D("4500000") + D("450000") + D("90000")
        assert cif.vat_base == D("4590000") + D("459000")

    def test_processing_fee_floor_and_cap(self, engine: VEDCalculatorEngine, fx: FxService) -> None:
        tiny = _cargo(CargoCategory.GENERAL, None, declared_value_origin=D("100"))
        huge = _cargo(CargoCategory.GENERAL, None, declared_value_origin=D("100000000"))
        assert engine.customs.calculate_clearance(
            Jurisdiction.KG, tiny, fx
        ).customs_processing_fee == D("500")
        assert engine.customs.calculate_clearance(
            Jurisdiction.KG, huge, fx
        ).customs_processing_fee == D("250000")


class TestRussianClearance:
    def test_vat_22_and_tiered_fee(
        self, engine: VEDCalculatorEngine, fx: FxService, sneakers_cargo: CargoSpec
    ) -> None:
        res = engine.customs.calculate_clearance(
            Jurisdiction.RU, sneakers_cargo, fx, freight_to_border_usd=D("1187.5")
        )
        assert res.currency is Currency.RUB
        assert res.duty.duty == D("18800.00")  # same ЕТТ duty as in KG
        assert res.vat_percent == D("22")
        assert res.vat == D("265248.5000")  # 22 % × 1 205 675
        assert res.customs_processing_fee == D("4924")  # bracket ≤ 1 200 000 RUB
        assert res.broker_fee == D("25000")

    @pytest.mark.parametrize(
        ("customs_value", "fee"),
        [
            ("1", "1231"),
            ("200000", "1231"),
            ("200000.01", "2462"),
            ("450000", "2462"),
            ("1200000", "4924"),
            ("2700000", "13541"),
            ("4200000", "18465"),
            ("5500000", "21344"),
            ("10000000", "49240"),
            ("10000000.01", "73860"),
        ],
    )
    def test_processing_fee_scale_2026(self, customs_value: str, fee: str) -> None:
        assert RU_TAX_PROFILE.customs_processing_fee.apply(D(customs_value)) == D(fee)

    def test_reduced_vat_override_applies_only_in_russia(self, round_fx, fx: FxService) -> None:
        entries = [
            *DEFAULT_TARIFF_MATRIX.entries,
            TariffEntry(
                hs_code="6111",
                description_ru="Детская одежда",
                description_en="Babies' garments",
                category=CargoCategory.APPAREL,
                rate_type=DutyRateType.AD_VALOREM,
                ad_valorem_percent=D("10"),
                ru_vat_percent_override=D("10"),
            ),
        ]
        service = CustomsService(TariffMatrix(entries=entries))
        cargo = _cargo(CargoCategory.APPAREL, "6111")
        assert service.calculate_clearance(Jurisdiction.RU, cargo, fx).vat_percent == D("10")
        assert service.calculate_clearance(Jurisdiction.KG, cargo, fx).vat_percent == D("12")


class TestJurisdictionComparison:
    def test_kg_is_cheaper_at_the_border(
        self, engine: VEDCalculatorEngine, sneakers_cargo: CargoSpec
    ) -> None:
        cmp = engine.compare_customs(sneakers_cargo, freight_to_border_usd=D("1187.5"))
        assert cmp.kg.duty.duty == cmp.ru.duty.duty  # common EAEU tariff
        assert cmp.kg_taxes_and_fees_rub == D("187801.0000")
        assert cmp.ru_taxes_and_fees_rub == D("313972.500")
        assert cmp.difference_rub == D("126171.500")
        assert cmp.cheaper_jurisdiction is Jurisdiction.KG
        assert any("intra-EAEU" in note for note in cmp.notes)


class TestFeeRules:
    def test_tiered_rule_requires_ascending_open_ended_tiers(self) -> None:
        with pytest.raises(ValidationError):
            TieredFeeRule(tiers=[FeeTier(up_to=D("10"), fee=D("1"))], currency=Currency.RUB)
        with pytest.raises(ValidationError):
            TieredFeeRule(
                tiers=[
                    FeeTier(up_to=D("20"), fee=D("1")),
                    FeeTier(up_to=D("10"), fee=D("2")),
                    FeeTier(up_to=None, fee=D("3")),
                ],
                currency=Currency.RUB,
            )

    def test_specific_tariff_needs_unit(self) -> None:
        with pytest.raises(ValidationError):
            TariffEntry(
                hs_code="1234",
                description_ru="x",
                description_en="x",
                category=CargoCategory.GENERAL,
                rate_type=DutyRateType.SPECIFIC,
                specific_rate_eur=D("1"),
            )
