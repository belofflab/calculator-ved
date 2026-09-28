"""Data contracts for the VED Calculator Core.

This module defines every input, reference-data and output structure used by the
engine.  All monetary fields are :class:`decimal.Decimal`; enumerations are
``str`` enums that also accept case-insensitive spellings (``"china"``,
``"Footwear"``) so that JSON requests can be written by hand.

Sections
--------
1. Enumerations
2. Calculation request (``CargoSpec``, ``CalculationAssumptions``,
   ``VEDCalculationRequest``)
3. Reference data: tariffs, fee rules, tax profiles, bank fees, service fees,
   FX tables, freight rate cards
4. Service outputs: FX conversions, freight quotes, customs clearance results
5. Optimisation outputs: ``CostBreakdown``, ``RouteComparisonResult``,
   ``OptimizationResult``
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from enum import StrEnum
from itertools import pairwise
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ved_calculator.domain.money import HUNDRED, ZERO, D, clamp, fmt, q2, q4, safe_div

__all__ = [
    "RECOMMENDED_FX_BUFFER_RANGE",
    "RISK_SCORE_BY_LEVEL",
    "BankFeeSchedule",
    "BankLegCost",
    "BankLegFee",
    "CalculationAssumptions",
    "CargoCategory",
    "CargoSpec",
    "ClearanceResult",
    "ClearanceType",
    "CorridorRateCard",
    "CostBreakdown",
    "Currency",
    "CustomsValuationBasis",
    "DayRange",
    "DomesticLegRate",
    "DomesticQuote",
    "DutyCalculation",
    "DutyRateType",
    "FeeTier",
    "FreightQuote",
    "FxConversion",
    "FxRateTable",
    "Jurisdiction",
    "JurisdictionComparison",
    "JurisdictionTaxProfile",
    "OptimizationPolicy",
    "OptimizationResult",
    "OriginCountry",
    "PercentFeeRule",
    "RecipientTaxRegime",
    "RiskLevel",
    "RouteComparisonResult",
    "ServiceFeeSchedule",
    "ServiceKind",
    "SpecificRateUnit",
    "TariffEntry",
    "TariffMatrix",
    "TariffResolution",
    "TieredFeeRule",
    "TransferCorridor",
    "TransportMode",
    "VEDCalculationRequest",
]


# --------------------------------------------------------------------------- #
# 1. Enumerations
# --------------------------------------------------------------------------- #
class CaseInsensitiveEnum(StrEnum):
    """``str`` enum that resolves ``"china"``/``"China"``/``"CHINA"`` alike."""

    @classmethod
    def _missing_(cls, value: object) -> Any:
        if isinstance(value, str):
            folded = value.strip().casefold()
            for member in cls:
                if member.value.casefold() == folded or member.name.casefold() == folded:
                    return member
        return None


class Currency(CaseInsensitiveEnum):
    USD = "USD"
    CNY = "CNY"
    EUR = "EUR"
    KGS = "KGS"
    RUB = "RUB"
    TRY = "TRY"
    AED = "AED"


class OriginCountry(CaseInsensitiveEnum):
    CHINA = "CHINA"
    TURKEY = "TURKEY"
    EU = "EU"
    USA = "USA"
    UAE = "UAE"
    VIETNAM = "VIETNAM"


class CargoCategory(CaseInsensitiveEnum):
    FOOTWEAR = "footwear"
    APPAREL = "apparel"
    ELECTRONICS = "electronics"
    GENERAL = "general"  # homeware & general merchandise


class ClearanceType(CaseInsensitiveEnum):
    OFFICIAL_EAEU_KG = "OFFICIAL_EAEU_KG"  # "белая растаможка" in Bishkek + intra-EAEU transfer
    CARGO_SIMPLIFIED = "CARGO_SIMPLIFIED"  # "карго / упрощёнка" flat $/kg all-in
    OFFICIAL_RU_DIRECT = "OFFICIAL_RU_DIRECT"  # benchmark: direct white import into Russia


class TransportMode(CaseInsensitiveEnum):
    AUTO_EXPRESS = "AUTO_EXPRESS"
    AUTO_STANDARD = "AUTO_STANDARD"
    RAIL = "RAIL"
    AIR = "AIR"
    SEA_MULTIMODAL = "SEA_MULTIMODAL"
    TRUCK = "TRUCK"  # domestic (hub → Russian city) leg


class RiskLevel(CaseInsensitiveEnum):
    LOW_LEGAL = "LOW_LEGAL"
    MEDIUM_TRANSIT = "MEDIUM_TRANSIT"
    HIGH_CUSTOMS = "HIGH_CUSTOMS"


RISK_SCORE_BY_LEVEL: dict[RiskLevel, int] = {
    RiskLevel.LOW_LEGAL: 10,
    RiskLevel.MEDIUM_TRANSIT: 45,
    RiskLevel.HIGH_CUSTOMS: 80,
}


class RecipientTaxRegime(CaseInsensitiveEnum):
    """Tax status of the Russian receiver (ИП / ООО).

    * ``OSNO`` – VAT payer: import VAT is deductible, i.e. a cash-flow item only.
    * ``USN`` – simplified regime: import VAT (incl. intra-EAEU) is a sunk cost
      (НК РФ ст. 346.11 п. 2/3).
    """

    OSNO = "OSNO"
    USN = "USN"


class CustomsValuationBasis(CaseInsensitiveEnum):
    """How freight to the EAEU border enters the tax bases.

    * ``INVOICE`` – the specification formula: duty on the invoice value only,
      freight added to the VAT base.
    * ``CIF`` – EAEU Customs Code art. 40 method 1: transport costs to the place
      of arrival are part of the customs value, so both duty and VAT include them.
    """

    INVOICE = "INVOICE"
    CIF = "CIF"


class DutyRateType(CaseInsensitiveEnum):
    AD_VALOREM = "AD_VALOREM"  # x % of customs value
    SPECIFIC = "SPECIFIC"  # y EUR per kg / pair / piece
    COMBINED_MAX = "COMBINED_MAX"  # "x %, но не менее y евро за …" = max(ad valorem, specific)


class SpecificRateUnit(CaseInsensitiveEnum):
    KG = "kg"
    PAIR = "pair"
    PIECE = "piece"


class ServiceKind(CaseInsensitiveEnum):
    WHITE_FREIGHT = "WHITE_FREIGHT"  # pure transport for official clearance
    CARGO_ALL_IN = "CARGO_ALL_IN"  # cargo rate incl. simplified clearance/handling


class TransferCorridor(CaseInsensitiveEnum):
    SWIFT_USD = "SWIFT_USD"
    CIPS_CNY = "CIPS_CNY"
    SWIFT_EUR = "SWIFT_EUR"
    RUB_KGS_LOCAL = "RUB_KGS_LOCAL"

    @classmethod
    def for_supplier_currency(cls, currency: Currency) -> TransferCorridor:
        """Corridor used by the Bishkek ОсОО to pay a supplier invoiced in ``currency``."""
        if currency is Currency.CNY:
            return cls.CIPS_CNY
        if currency is Currency.EUR:
            return cls.SWIFT_EUR
        return cls.SWIFT_USD  # USD, and TRY/AED invoices are settled in USD


class Jurisdiction(CaseInsensitiveEnum):
    KG = "KG"
    RU = "RU"


RECOMMENDED_FX_BUFFER_RANGE: tuple[Decimal, Decimal] = (Decimal("1.5"), Decimal("3.0"))


# --------------------------------------------------------------------------- #
# Base classes
# --------------------------------------------------------------------------- #
class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class FrozenModel(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


_HS_CLEAN = re.compile(r"[\s.\-]")


def _normalise_hs_code(value: object, *, allow_empty: bool) -> str | None:
    if value is None:
        return None
    cleaned = _HS_CLEAN.sub("", str(value))
    if cleaned == "":
        if allow_empty:
            return ""
        return None
    if not cleaned.isdigit() or not 2 <= len(cleaned) <= 10:
        raise ValueError("hs_code must contain 2–10 digits (ТН ВЭД ЕАЭС), e.g. '6404 11 000 0'")
    return cleaned


# --------------------------------------------------------------------------- #
# 2. Calculation request
# --------------------------------------------------------------------------- #
class CargoSpec(FrozenModel):
    """Physical and commercial description of one consolidated shipment."""

    category: CargoCategory
    hs_code: str | None = Field(
        default=None,
        description="ТН ВЭД ЕАЭС code (2–10 digits, spaces/dots allowed). "
        "Omit to use the category default tariff line.",
    )
    total_weight_kg: Decimal = Field(gt=0)
    total_volume_m3: Decimal = Field(gt=0)
    declared_value_origin: Decimal = Field(
        gt=0, description="Invoice value of the whole shipment in origin_currency"
    )
    origin_currency: Currency
    quantity_units: int = Field(gt=0, description="Units (pairs/pieces) in the shipment")
    description: str | None = None

    @field_validator("hs_code", mode="before")
    @classmethod
    def _validate_hs_code(cls, value: object) -> str | None:
        return _normalise_hs_code(value, allow_empty=False)

    @property
    def density_kg_per_m3(self) -> Decimal:
        return q4(safe_div(self.total_weight_kg, self.total_volume_m3))

    @property
    def declared_value_per_unit(self) -> Decimal:
        return q4(safe_div(self.declared_value_origin, self.quantity_units))


class CalculationAssumptions(FrozenModel):
    """Tunable business assumptions.  Defaults are conservative (cost-maximising)."""

    recipient_tax_regime: RecipientTaxRegime = RecipientTaxRegime.USN
    kg_import_vat_recoverable: bool = Field(
        default=False,
        description="True if the Bishkek ОсОО recovers its 12% import VAT through the "
        "0% export to Russia; False treats it as a sunk cost (specification formula B).",
    )
    customs_valuation_basis: CustomsValuationBasis = CustomsValuationBasis.INVOICE
    agent_markup_percent: Decimal = Field(
        default=Decimal("2.0"), ge=0, le=15, description="ОсОО agent markup, typically 1–3%"
    )
    insurance_percent_white: Decimal = Field(default=Decimal("0.4"), ge=0, le=10)
    insurance_percent_cargo: Decimal = Field(default=Decimal("1.0"), ge=0, le=10)
    has_valid_certificates: bool = Field(
        default=False,
        description="True if EAEU declarations/certificates of conformity already exist "
        "(certification fee is then not charged to this shipment).",
    )
    apply_marking: bool = Field(
        default=True, description="Charge Честный ЗНАК marking for categories that require it."
    )
    payment_agent_fee_percent: Decimal = Field(
        default=Decimal("4.0"),
        ge=0,
        le=20,
        description="Payment-agent commission for paying the supplier directly from Russia "
        "(used only by the OFFICIAL_RU_DIRECT benchmark route).",
    )
    calculation_date: date = Field(default_factory=date.today)


class VEDCalculationRequest(FrozenModel):
    """Input contract of the calculation service."""

    origin_country: OriginCountry
    destination_city_ru: str = "Tyumen"
    cargo: CargoSpec
    target_delivery_days_max: int | None = Field(default=None, gt=0)
    allow_cargo_simplified: bool = True
    allow_white_customs: bool = True
    include_direct_ru_benchmark: bool = Field(
        default=False,
        description="Also evaluate a direct white import into Russia (no Bishkek hub) "
        "as a benchmark route.",
    )
    fx_risk_buffer_percent: Decimal = Field(default=Decimal("2.5"), ge=0, le=10)
    target_sale_price_rub_per_unit: Decimal | None = Field(
        default=None, gt=0, description="Optional: enables gross-margin reporting per route."
    )
    assumptions: CalculationAssumptions = Field(default_factory=CalculationAssumptions)

    @field_validator("destination_city_ru")
    @classmethod
    def _validate_city(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("destination_city_ru must not be empty")
        return value

    @model_validator(mode="after")
    def _at_least_one_route_family(self) -> VEDCalculationRequest:
        if not (
            self.allow_cargo_simplified
            or self.allow_white_customs
            or self.include_direct_ru_benchmark
        ):
            raise ValueError(
                "at least one route family must be enabled "
                "(allow_white_customs / allow_cargo_simplified / include_direct_ru_benchmark)"
            )
        return self

    def allowed_clearance_types(self) -> list[ClearanceType]:
        allowed: list[ClearanceType] = []
        if self.allow_white_customs:
            allowed.append(ClearanceType.OFFICIAL_EAEU_KG)
        if self.allow_cargo_simplified:
            allowed.append(ClearanceType.CARGO_SIMPLIFIED)
        if self.include_direct_ru_benchmark:
            allowed.append(ClearanceType.OFFICIAL_RU_DIRECT)
        return allowed


# --------------------------------------------------------------------------- #
# 3. Reference data
# --------------------------------------------------------------------------- #
class TariffEntry(FrozenModel):
    """One line (or prefix) of the EAEU Common Customs Tariff (ЕТТ ЕАЭС)."""

    hs_code: str = Field(
        default="",
        description="ТН ВЭД prefix (2–10 digits). Empty string = synthetic category default.",
    )
    description_ru: str
    description_en: str
    category: CargoCategory
    rate_type: DutyRateType
    ad_valorem_percent: Decimal = Field(default=ZERO, ge=0)
    specific_rate_eur: Decimal = Field(default=ZERO, ge=0)
    specific_unit: SpecificRateUnit | None = None
    ru_vat_percent_override: Decimal | None = Field(
        default=None, description="Reduced Russian VAT rate (e.g. 10% for children's goods)."
    )
    marking_required: bool = Field(default=False, description="Честный ЗНАК mandatory marking")
    certification_scheme: str = ""
    ru_technology_fee_rub_per_unit: Decimal = Field(
        default=ZERO, ge=0, description="Russian технологический сбор per unit (from 01.12.2026)"
    )
    is_category_default: bool = False
    verified: bool = Field(
        default=False, description="Rate cross-checked against a published ЕТТ listing"
    )
    source: str = ""

    @field_validator("hs_code", mode="before")
    @classmethod
    def _validate_hs_code(cls, value: object) -> str:
        return _normalise_hs_code(value, allow_empty=True) or ""

    @model_validator(mode="after")
    def _validate_rate_shape(self) -> TariffEntry:
        needs_specific = self.rate_type in (DutyRateType.SPECIFIC, DutyRateType.COMBINED_MAX)
        if needs_specific and (self.specific_rate_eur <= ZERO or self.specific_unit is None):
            raise ValueError(
                f"{self.rate_type.value} tariff needs specific_rate_eur and specific_unit"
            )
        if self.rate_type is DutyRateType.AD_VALOREM and self.specific_rate_eur != ZERO:
            raise ValueError("AD_VALOREM tariff must not carry a specific rate")
        return self

    def matches(self, hs_code: str) -> bool:
        return bool(self.hs_code) and hs_code.startswith(self.hs_code)

    def rate_description(self) -> str:
        if self.rate_type is DutyRateType.AD_VALOREM:
            return f"{fmt(self.ad_valorem_percent)}% ad valorem"
        unit = self.specific_unit.value if self.specific_unit else "unit"
        specific = f"{fmt(self.specific_rate_eur)} EUR/{unit}"
        if self.rate_type is DutyRateType.SPECIFIC:
            return specific
        return f"{fmt(self.ad_valorem_percent)}%, but not less than {specific}"


class TariffResolution(FrozenModel):
    entry: TariffEntry
    matched_by: Literal["exact", "prefix", "child", "category_default"]
    requested_hs_code: str | None = None
    notes: list[str] = Field(default_factory=list)


class TariffMatrix(FrozenModel):
    """Lookup table of tariff lines with longest-prefix resolution."""

    entries: list[TariffEntry]

    @model_validator(mode="after")
    def _validate_defaults(self) -> TariffMatrix:
        for category in CargoCategory:
            defaults = [e for e in self.entries if e.category is category and e.is_category_default]
            if len(defaults) != 1:
                raise ValueError(f"category {category.value} must have exactly one default entry")
        return self

    def by_category(self, category: CargoCategory) -> list[TariffEntry]:
        return [e for e in self.entries if e.category is category]

    def category_default(self, category: CargoCategory) -> TariffEntry:
        return next(e for e in self.entries if e.category is category and e.is_category_default)

    def resolve(self, hs_code: str | None, category: CargoCategory) -> TariffResolution:
        notes: list[str] = []
        code = _normalise_hs_code(hs_code, allow_empty=False)
        entry: TariffEntry | None = None
        matched_by: Literal["exact", "prefix", "child", "category_default"] = "category_default"
        if code:
            exact = [e for e in self.entries if e.hs_code == code]
            if exact:
                entry, matched_by = exact[0], "exact"
            else:
                prefixes = [e for e in self.entries if e.matches(code)]
                if prefixes:
                    entry = max(prefixes, key=lambda e: len(e.hs_code))
                    matched_by = "prefix"
                else:
                    children = [e for e in self.entries if e.hs_code and e.hs_code.startswith(code)]
                    if children:
                        entry, matched_by = children[0], "child"
                        if len({c.rate_description() for c in children}) > 1:
                            notes.append(
                                f"hs_code {code} matches {len(children)} tariff lines with different "
                                f"rates; using {entry.hs_code} ({entry.rate_description()})."
                            )
            if entry is None:
                notes.append(
                    f"No tariff line for hs_code {code}; using the {category.value} default."
                )
        if entry is None:
            entry = self.category_default(category)
        elif entry.category is not category:
            notes.append(
                f"hs_code {code} belongs to category '{entry.category.value}', request says "
                f"'{category.value}'; the HS code takes precedence for duty."
            )
        if not entry.verified:
            notes.append(
                f"Tariff rate for {entry.hs_code or entry.category.value} is a reference "
                "estimate; verify against current ЕТТ ЕАЭС."
            )
        return TariffResolution(
            entry=entry, matched_by=matched_by, requested_hs_code=code, notes=notes
        )


class PercentFeeRule(FrozenModel):
    """``fee = clamp(base × percent/100 + fixed, minimum, maximum)``."""

    kind: Literal["percent"] = "percent"
    percent: Decimal = Field(default=ZERO, ge=0)
    fixed: Decimal = Field(default=ZERO, ge=0)
    minimum: Decimal | None = Field(default=None, ge=0)
    maximum: Decimal | None = Field(default=None, ge=0)
    currency: Currency

    @model_validator(mode="after")
    def _validate_bounds(self) -> PercentFeeRule:
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("minimum must not exceed maximum")
        return self

    def apply(self, base: Decimal) -> Decimal:
        return clamp(D(base) * self.percent / HUNDRED + self.fixed, self.minimum, self.maximum)


class FeeTier(FrozenModel):
    up_to: Decimal | None = Field(default=None, description="Inclusive upper bound; None = ∞")
    fee: Decimal = Field(ge=0)


class TieredFeeRule(FrozenModel):
    """Step function of the base amount (Russian customs processing fee scale)."""

    kind: Literal["tiered"] = "tiered"
    tiers: list[FeeTier] = Field(min_length=1)
    currency: Currency

    @model_validator(mode="after")
    def _validate_tiers(self) -> TieredFeeRule:
        bounds = [t.up_to for t in self.tiers]
        if bounds[-1] is not None:
            raise ValueError("last tier must be open-ended (up_to=None)")
        finite = [b for b in bounds[:-1]]
        if any(b is None for b in finite):
            raise ValueError("only the last tier may be open-ended")
        if any(a >= b for a, b in pairwise(finite) if a is not None and b is not None):
            raise ValueError("tier bounds must be strictly ascending")
        return self

    def apply(self, base: Decimal) -> Decimal:
        amount = D(base)
        for tier in self.tiers:
            if tier.up_to is None or amount <= tier.up_to:
                return tier.fee
        raise AssertionError("unreachable: last tier is open-ended")


class JurisdictionTaxProfile(FrozenModel):
    jurisdiction: Jurisdiction
    name: str
    currency: Currency
    vat_percent: Decimal = Field(ge=0, le=100)
    customs_processing_fee: PercentFeeRule | TieredFeeRule = Field(discriminator="kind")
    broker_fee_local: Decimal = Field(ge=0, description="Broker/declarant fee per declaration")
    clearance_days_min: int = Field(ge=0)
    clearance_days_max: int = Field(ge=0)
    notes: str = ""

    @model_validator(mode="after")
    def _validate_days(self) -> JurisdictionTaxProfile:
        if self.clearance_days_max < self.clearance_days_min:
            raise ValueError("clearance_days_max must be >= clearance_days_min")
        if self.customs_processing_fee.currency is not self.currency:
            raise ValueError("customs_processing_fee currency must match the jurisdiction currency")
        return self


class BankLegFee(FrozenModel):
    transfer: PercentFeeRule
    conversion_spread_percent: Decimal = Field(default=ZERO, ge=0, le=20)


class BankFeeSchedule(FrozenModel):
    legs: dict[TransferCorridor, BankLegFee]

    def leg(self, corridor: TransferCorridor) -> BankLegFee:
        try:
            return self.legs[corridor]
        except KeyError as exc:  # pragma: no cover - defensive
            raise ValueError(f"no bank fee configured for corridor {corridor.value}") from exc


class DayRange(FrozenModel):
    days_min: int = Field(ge=0)
    days_max: int = Field(ge=0)

    @model_validator(mode="after")
    def _validate(self) -> DayRange:
        if self.days_max < self.days_min:
            raise ValueError("days_max must be >= days_min")
        return self


class ServiceFeeSchedule(FrozenModel):
    """Non-tax service costs on the Russian side and hub processing times."""

    certification_fee_rub: dict[CargoCategory, Decimal]
    marking_code_cost_rub: Decimal = Field(default=Decimal("0.60"), ge=0)
    marking_application_cost_rub_per_unit: Decimal = Field(default=Decimal("12"), ge=0)
    hub_processing_days: dict[ClearanceType, DayRange]
    ru_technology_fee_effective_from: date = date(2026, 12, 1)

    @model_validator(mode="after")
    def _validate_coverage(self) -> ServiceFeeSchedule:
        missing = [c.value for c in CargoCategory if c not in self.certification_fee_rub]
        if missing:
            raise ValueError(f"certification_fee_rub missing categories: {missing}")
        missing_ct = [c.value for c in ClearanceType if c not in self.hub_processing_days]
        if missing_ct:
            raise ValueError(f"hub_processing_days missing clearance types: {missing_ct}")
        return self


_PAIR_RE = re.compile(r"^([A-Z]{3})/([A-Z]{3})$")


class FxRateTable(FrozenModel):
    """Mid-market FX snapshot.

    ``per_usd[X]`` = units of ``X`` per 1 USD.  ``direct_pairs["A/B"]`` = units of
    ``B`` per 1 ``A`` and takes precedence over the USD cross-rate (both
    directions are honoured).
    """

    as_of: date
    per_usd: dict[Currency, Decimal]
    direct_pairs: dict[str, Decimal] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_rates(self) -> FxRateTable:
        if self.per_usd.get(Currency.USD) != Decimal(1):
            raise ValueError("per_usd must contain USD with rate 1")
        for currency, rate in self.per_usd.items():
            if rate <= ZERO:
                raise ValueError(f"per_usd[{currency.value}] must be positive")
        for pair, rate in self.direct_pairs.items():
            match = _PAIR_RE.match(pair)
            if not match:
                raise ValueError(f"direct pair key must look like 'USD/KGS', got {pair!r}")
            Currency(match.group(1))
            Currency(match.group(2))
            if rate <= ZERO:
                raise ValueError(f"direct pair {pair} must be positive")
        return self

    def has(self, currency: Currency) -> bool:
        return currency in self.per_usd

    def rate(self, from_currency: Currency, to_currency: Currency) -> Decimal:
        """Units of ``to_currency`` per 1 unit of ``from_currency`` (mid)."""
        if from_currency is to_currency:
            return Decimal(1)
        direct = self.direct_pairs.get(f"{from_currency.value}/{to_currency.value}")
        if direct is not None:
            return direct
        inverse = self.direct_pairs.get(f"{to_currency.value}/{from_currency.value}")
        if inverse is not None:
            return Decimal(1) / inverse
        try:
            return self.per_usd[to_currency] / self.per_usd[from_currency]
        except KeyError as exc:
            raise ValueError(f"FX table has no rate for {exc.args[0].value}") from exc


class CorridorRateCard(FrozenModel):
    """International leg: origin hub → Bishkek (or Moscow for the direct benchmark)."""

    corridor_id: str
    origin: OriginCountry
    origin_hub: str
    destination_hub: str
    transport_mode: TransportMode
    service_kind: ServiceKind
    rate_per_kg_usd: Decimal = Field(gt=0)
    min_charge_usd: Decimal = Field(default=ZERO, ge=0)
    volumetric_coefficient_kg_per_m3: Decimal = Field(gt=0)
    handling_fixed_usd: Decimal = Field(default=ZERO, ge=0)
    handling_per_kg_usd: Decimal = Field(default=ZERO, ge=0)
    days_min: int = Field(ge=1)
    days_max: int = Field(ge=1)
    category_multipliers: dict[CargoCategory, Decimal] = Field(default_factory=dict)
    notes: str = ""

    @model_validator(mode="after")
    def _validate_days(self) -> CorridorRateCard:
        if self.days_max < self.days_min:
            raise ValueError("days_max must be >= days_min")
        return self

    def multiplier_for(self, category: CargoCategory) -> Decimal:
        return self.category_multipliers.get(category, Decimal(1))


class DomesticLegRate(FrozenModel):
    """Hub → Russian city leg priced in RUB."""

    leg_id: str
    from_hub: str
    destination_city: str = Field(description="Canonical city key, e.g. 'tyumen'")
    transport_mode: TransportMode
    rate_per_kg_rub: Decimal = Field(ge=0)
    min_charge_rub: Decimal = Field(default=ZERO, ge=0)
    volumetric_coefficient_kg_per_m3: Decimal = Field(gt=0)
    days_min: int = Field(ge=0)
    days_max: int = Field(ge=0)
    distance_km: int | None = Field(default=None, ge=0)
    notes: str = ""

    @model_validator(mode="after")
    def _validate_days(self) -> DomesticLegRate:
        if self.days_max < self.days_min:
            raise ValueError("days_max must be >= days_min")
        return self


# --------------------------------------------------------------------------- #
# 4. Service outputs
# --------------------------------------------------------------------------- #
class FxConversion(FrozenModel):
    amount: Decimal
    from_currency: Currency
    to_currency: Currency
    mid_rate: Decimal
    buffer_percent: Decimal
    effective_rate: Decimal
    amount_at_mid: Decimal
    amount_buffered: Decimal
    buffer_cost: Decimal


class BankLegCost(FrozenModel):
    corridor: TransferCorridor
    currency: Currency
    amount: Decimal
    transfer_fee: Decimal
    conversion_spread: Decimal
    total: Decimal


class FreightQuote(FrozenModel):
    corridor_id: str
    transport_mode: TransportMode
    service_kind: ServiceKind
    destination_hub: str
    actual_weight_kg: Decimal
    volumetric_weight_kg: Decimal
    chargeable_weight_kg: Decimal
    volumetric_coefficient_kg_per_m3: Decimal
    category_multiplier: Decimal
    rate_per_kg_usd: Decimal
    base_freight_usd: Decimal
    min_charge_applied: bool
    freight_usd: Decimal
    handling_usd: Decimal
    total_usd: Decimal
    days_min: int
    days_max: int


class DomesticQuote(FrozenModel):
    leg_id: str
    from_hub: str
    destination_city: str
    transport_mode: TransportMode
    chargeable_weight_kg: Decimal
    rate_per_kg_rub: Decimal
    min_charge_applied: bool
    cost_rub: Decimal
    days_min: int
    days_max: int
    is_fallback: bool = False


class DutyCalculation(FrozenModel):
    rate_type: DutyRateType
    rate_description: str
    customs_value: Decimal
    ad_valorem_percent: Decimal
    ad_valorem_amount: Decimal
    specific_rate_eur: Decimal
    specific_unit: SpecificRateUnit | None
    specific_quantity: Decimal
    eur_rate: Decimal
    specific_amount: Decimal
    duty: Decimal


class ClearanceResult(FrozenModel):
    """Official clearance maths for one jurisdiction, in that jurisdiction's currency."""

    jurisdiction: Jurisdiction
    currency: Currency
    tariff: TariffEntry
    tariff_matched_by: str
    invoice_value_local: Decimal
    freight_to_border_local: Decimal
    valuation_basis: CustomsValuationBasis
    customs_value: Decimal
    duty: DutyCalculation
    vat_percent: Decimal
    vat_base: Decimal
    vat: Decimal
    customs_processing_fee: Decimal
    broker_fee: Decimal
    total_taxes_and_fees: Decimal
    total_cleared_cost: Decimal = Field(
        description="invoice + duty + VAT + processing fee + broker fee (specification formula)"
    )
    clearance_days_min: int
    clearance_days_max: int
    notes: list[str] = Field(default_factory=list)


class JurisdictionComparison(FrozenModel):
    kg: ClearanceResult
    ru: ClearanceResult
    kg_taxes_and_fees_rub: Decimal
    ru_taxes_and_fees_rub: Decimal
    difference_rub: Decimal = Field(description="RU minus KG (positive = KG cheaper)")
    cheaper_jurisdiction: Jurisdiction
    notes: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# 5. Optimisation outputs
# --------------------------------------------------------------------------- #
class CostBreakdown(StrictModel):
    """Landed-cost components in RUB.  ``sum(components) == total``."""

    goods_value: Decimal = ZERO
    international_freight: Decimal = ZERO
    hub_handling: Decimal = ZERO
    insurance: Decimal = ZERO
    customs_duty: Decimal = ZERO
    customs_processing_fee: Decimal = ZERO
    broker_fee: Decimal = ZERO
    certification_fee: Decimal = ZERO
    marking_fee: Decimal = ZERO
    technology_fee: Decimal = ZERO
    import_vat_kg: Decimal = ZERO
    import_vat_ru: Decimal = ZERO
    bank_fees: Decimal = ZERO
    fx_risk_buffer: Decimal = ZERO
    agent_markup: Decimal = ZERO
    payment_agent_fee: Decimal = ZERO
    local_transport: Decimal = ZERO

    @classmethod
    def component_names(cls) -> list[str]:
        return list(cls.model_fields)

    def components(self) -> dict[str, Decimal]:
        return {name: getattr(self, name) for name in self.component_names()}

    def total(self) -> Decimal:
        return sum(self.components().values(), ZERO)

    def rounded(self) -> CostBreakdown:
        return CostBreakdown(**{k: q2(v) for k, v in self.components().items()})


class RouteComparisonResult(StrictModel):
    route_id: str
    route_name: str
    clearance_type: ClearanceType
    origin_country: OriginCountry
    hub: str
    destination_city_ru: str
    transport_mode: TransportMode
    domestic_transport_mode: TransportMode
    total_cost_rub: Decimal
    cost_per_unit_rub: Decimal
    cost_per_kg_rub: Decimal
    estimated_days_min: int
    estimated_days_max: int
    breakdown: dict[str, Decimal]
    recoverable_vat_rub: Decimal = Field(
        default=ZERO, description="VAT paid but deductible (cash-flow only, excluded from total)"
    )
    is_recommended: bool = False
    labels: list[str] = Field(default_factory=list)
    risk_level: RiskLevel
    risk_score: int = Field(ge=0, le=100)
    risk_adjusted_cost_rub: Decimal | None = Field(
        default=None,
        description="total_cost × (1 + delay cost + expected risk loss); see OptimizationPolicy",
    )
    chargeable_weight_kg: Decimal
    fx_rates_used: dict[str, Decimal]
    gross_margin_percent: Decimal | None = None
    meets_deadline: bool | None = None
    constraint_violations: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class OptimizationPolicy(FrozenModel):
    """Policy behind the hybrid ("optimal") ranking.

    Every route is scored by its *risk-adjusted cost* in RUB::

        total_cost × (1 + delay_cost_percent_per_day × days_max / 100
                        + expected_loss_percent[risk_level] / 100)

    ``delay_cost_percent_per_day`` monetises capital tied up in transit and
    lost sales; ``expected_loss_percent`` monetises the probability-weighted
    cost of seizure, penalties and unsellable (undocumented / unmarked) stock.
    With ``prefer_legal_routes`` the OPTIMAL pick is restricted to LOW_LEGAL
    routes whenever at least one exists, so a grey route can be the CHEAPEST
    but never the recommendation.
    """

    delay_cost_percent_per_day: Decimal = Field(default=Decimal("0.10"), ge=0, le=5)
    expected_loss_percent: dict[RiskLevel, Decimal] = Field(
        default_factory=lambda: {
            RiskLevel.LOW_LEGAL: Decimal("1"),
            RiskLevel.MEDIUM_TRANSIT: Decimal("12"),
            RiskLevel.HIGH_CUSTOMS: Decimal("35"),
        }
    )
    prefer_legal_routes: bool = True

    @model_validator(mode="after")
    def _validate_coverage(self) -> OptimizationPolicy:
        missing = [level.value for level in RiskLevel if level not in self.expected_loss_percent]
        if missing:
            raise ValueError(f"expected_loss_percent missing risk levels: {missing}")
        if any(v < ZERO for v in self.expected_loss_percent.values()):
            raise ValueError("expected_loss_percent values must be >= 0")
        return self

    def risk_adjusted_cost(
        self, total_cost: Decimal, days_max: int, risk_level: RiskLevel
    ) -> Decimal:
        delay = self.delay_cost_percent_per_day * Decimal(days_max) / HUNDRED
        loss = self.expected_loss_percent[risk_level] / HUNDRED
        return D(total_cost) * (Decimal(1) + delay + loss)


class OptimizationResult(StrictModel):
    request: VEDCalculationRequest
    routes: list[RouteComparisonResult] = Field(
        description="Feasible routes sorted by total_cost_rub ascending"
    )
    excluded_routes: list[RouteComparisonResult] = Field(
        default_factory=list, description="Routes violating hard constraints (e.g. deadline)"
    )
    cheapest_route_id: str | None = None
    cheapest_legal_route_id: str | None = None
    fastest_route_id: str | None = None
    optimal_route_id: str | None = None
    warnings: list[str] = Field(default_factory=list)
    summary: str = ""
    fx_as_of: date

    def route(self, route_id: str | None) -> RouteComparisonResult | None:
        if route_id is None:
            return None
        for candidate in (*self.routes, *self.excluded_routes):
            if candidate.route_id == route_id:
                return candidate
        return None

    @property
    def cheapest(self) -> RouteComparisonResult | None:
        return self.route(self.cheapest_route_id)

    @property
    def cheapest_legal(self) -> RouteComparisonResult | None:
        return self.route(self.cheapest_legal_route_id)

    @property
    def fastest(self) -> RouteComparisonResult | None:
        return self.route(self.fastest_route_id)

    @property
    def optimal(self) -> RouteComparisonResult | None:
        return self.route(self.optimal_route_id)

    def comparison_matrix(self) -> list[dict[str, Any]]:
        """Compact tabular view (one row per route, feasible first)."""
        rows: list[dict[str, Any]] = []
        for route in (*self.routes, *self.excluded_routes):
            rows.append(
                {
                    "route_id": route.route_id,
                    "route_name": route.route_name,
                    "clearance_type": route.clearance_type.value,
                    "total_cost_rub": route.total_cost_rub,
                    "cost_per_unit_rub": route.cost_per_unit_rub,
                    "days": f"{route.estimated_days_min}–{route.estimated_days_max}",
                    "risk_level": route.risk_level.value,
                    "labels": list(route.labels),
                    "feasible": not route.constraint_violations,
                }
            )
        return rows
