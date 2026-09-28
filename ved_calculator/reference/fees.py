"""Tax profiles, bank fee schedules and service fees (reference defaults)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from ved_calculator.domain.models import (
    BankFeeSchedule,
    BankLegFee,
    CargoCategory,
    ClearanceType,
    Currency,
    DayRange,
    FeeTier,
    Jurisdiction,
    JurisdictionTaxProfile,
    PercentFeeRule,
    ServiceFeeSchedule,
    TieredFeeRule,
    TransferCorridor,
)

KG_TAX_PROFILE = JurisdictionTaxProfile(
    jurisdiction=Jurisdiction.KG,
    name="Kyrgyz Republic — EAEU member, importer of record: Bishkek ОсОО",
    currency=Currency.KGS,
    vat_percent=Decimal("12"),
    customs_processing_fee=PercentFeeRule(
        percent=Decimal("0.4"),
        minimum=Decimal("500"),  # 5 × расчётный показатель (100 KGS)
        maximum=Decimal("250000"),  # 2 500 × расчётный показатель
        currency=Currency.KGS,
    ),
    broker_fee_local=Decimal("20000"),
    clearance_days_min=2,
    clearance_days_max=4,
    notes=(
        "VAT 12% (Налоговый кодекс КР). Customs processing fee 0,4% of customs value, "
        "min 5 / max 2 500 расчётных показателей — ПКМ КР №349 от 03.07.2024 "
        "(изменения в ПП КР №79 от 13.02.2020)."
    ),
)

RU_TAX_PROFILE = JurisdictionTaxProfile(
    jurisdiction=Jurisdiction.RU,
    name="Russian Federation — direct import / EAEU recipient",
    currency=Currency.RUB,
    vat_percent=Decimal("22"),
    customs_processing_fee=TieredFeeRule(
        tiers=[
            FeeTier(up_to=Decimal("200000"), fee=Decimal("1231")),
            FeeTier(up_to=Decimal("450000"), fee=Decimal("2462")),
            FeeTier(up_to=Decimal("1200000"), fee=Decimal("4924")),
            FeeTier(up_to=Decimal("2700000"), fee=Decimal("13541")),
            FeeTier(up_to=Decimal("4200000"), fee=Decimal("18465")),
            FeeTier(up_to=Decimal("5500000"), fee=Decimal("21344")),
            FeeTier(up_to=Decimal("10000000"), fee=Decimal("49240")),
            FeeTier(up_to=None, fee=Decimal("73860")),
        ],
        currency=Currency.RUB,
    ),
    broker_fee_local=Decimal("25000"),
    clearance_days_min=2,
    clearance_days_max=5,
    notes=(
        "VAT 22% from 01.01.2026 (Федеральный закон №425-ФЗ от 28.11.2025). "
        "Customs processing fee scale per ПП РФ №1638 от 23.10.2025 (in force 01.01.2026)."
    ),
)

DEFAULT_TAX_PROFILES: dict[Jurisdiction, JurisdictionTaxProfile] = {
    Jurisdiction.KG: KG_TAX_PROFILE,
    Jurisdiction.RU: RU_TAX_PROFILE,
}

DEFAULT_BANK_FEES = BankFeeSchedule(
    legs={
        TransferCorridor.SWIFT_USD: BankLegFee(
            transfer=PercentFeeRule(
                percent=Decimal("0.2"),
                minimum=Decimal("30"),
                maximum=Decimal("250"),
                currency=Currency.USD,
            ),
            conversion_spread_percent=Decimal("0.6"),
        ),
        TransferCorridor.CIPS_CNY: BankLegFee(
            transfer=PercentFeeRule(
                percent=Decimal("0.15"),
                minimum=Decimal("200"),
                maximum=Decimal("1500"),
                currency=Currency.CNY,
            ),
            conversion_spread_percent=Decimal("0.8"),
        ),
        TransferCorridor.SWIFT_EUR: BankLegFee(
            transfer=PercentFeeRule(
                percent=Decimal("0.2"),
                minimum=Decimal("30"),
                maximum=Decimal("250"),
                currency=Currency.EUR,
            ),
            conversion_spread_percent=Decimal("0.6"),
        ),
        TransferCorridor.RUB_KGS_LOCAL: BankLegFee(
            transfer=PercentFeeRule(
                percent=Decimal("0.5"),
                minimum=Decimal("1500"),
                maximum=Decimal("30000"),
                currency=Currency.RUB,
            ),
            conversion_spread_percent=Decimal("1.0"),
        ),
    }
)

DEFAULT_SERVICE_FEES = ServiceFeeSchedule(
    certification_fee_rub={
        CargoCategory.FOOTWEAR: Decimal("18000"),
        CargoCategory.APPAREL: Decimal("18000"),
        CargoCategory.ELECTRONICS: Decimal("45000"),
        CargoCategory.GENERAL: Decimal("15000"),
    },
    marking_code_cost_rub=Decimal("0.60"),  # 50 коп. + НДС per Честный ЗНАК code
    marking_application_cost_rub_per_unit=Decimal("12"),
    hub_processing_days={
        ClearanceType.OFFICIAL_EAEU_KG: DayRange(days_min=2, days_max=4),
        ClearanceType.CARGO_SIMPLIFIED: DayRange(days_min=1, days_max=2),
        ClearanceType.OFFICIAL_RU_DIRECT: DayRange(days_min=2, days_max=5),
    },
    ru_technology_fee_effective_from=date(2026, 12, 1),
)

__all__ = [
    "DEFAULT_BANK_FEES",
    "DEFAULT_SERVICE_FEES",
    "DEFAULT_TAX_PROFILES",
    "KG_TAX_PROFILE",
    "RU_TAX_PROFILE",
]
