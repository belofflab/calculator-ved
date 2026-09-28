"""Module 1 — Customs & Tariff Matrix.

Implements the official EAEU clearance maths for a declaration lodged either in
Kyrgyzstan (Bishkek ОсОО) or directly in Russia:

    Duty      = f(tariff line, customs value)         # ad valorem / specific / combined
    VAT       = (customs value + duty [+ freight]) × VAT%   # KG 12 % · RU 22 %
    Fees      = customs processing fee + broker fee
    Cleared   = invoice + duty + VAT + fees            # specification formula B

Specific and combined rates are denominated in EUR per kg/pair/piece and are
converted at the official EUR rate of the declaring jurisdiction's currency.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

from ved_calculator.domain.models import (
    CargoSpec,
    ClearanceResult,
    Currency,
    CustomsValuationBasis,
    DutyCalculation,
    DutyRateType,
    Jurisdiction,
    JurisdictionComparison,
    JurisdictionTaxProfile,
    SpecificRateUnit,
    TariffEntry,
    TariffMatrix,
    TariffResolution,
)
from ved_calculator.domain.money import ZERO, D, DecimalLike, apply_percent, fmt, q2
from ved_calculator.reference.fees import DEFAULT_TAX_PROFILES
from ved_calculator.reference.tariffs import DEFAULT_TARIFF_MATRIX
from ved_calculator.services.fx_service import FxService

__all__ = ["CustomsService"]


class CustomsService:
    """TN VED lookup, duty/VAT/fee computation and KG-vs-RU comparison."""

    def __init__(
        self,
        tariffs: TariffMatrix = DEFAULT_TARIFF_MATRIX,
        profiles: Mapping[Jurisdiction, JurisdictionTaxProfile] | None = None,
    ) -> None:
        self.tariffs = tariffs
        self.profiles = dict(DEFAULT_TAX_PROFILES if profiles is None else profiles)
        missing = [j.value for j in Jurisdiction if j not in self.profiles]
        if missing:
            raise ValueError(f"missing tax profiles for {missing}")

    def profile(self, jurisdiction: Jurisdiction) -> JurisdictionTaxProfile:
        return self.profiles[Jurisdiction(jurisdiction)]

    # ---------------------------------------------------------------- tariff
    def resolve_tariff(self, cargo: CargoSpec) -> TariffResolution:
        return self.tariffs.resolve(cargo.hs_code, cargo.category)

    # ------------------------------------------------------------------ duty
    def calculate_duty(
        self,
        entry: TariffEntry,
        *,
        customs_value: DecimalLike,
        cargo: CargoSpec,
        eur_rate: DecimalLike,
    ) -> DutyCalculation:
        """Duty in the declaring currency for one tariff line.

        ``eur_rate`` is the official rate (declaring currency per 1 EUR) used to
        convert the specific component ("не менее X евро за кг/пару").
        """
        value = D(customs_value)
        uses_ad_valorem = entry.rate_type in (DutyRateType.AD_VALOREM, DutyRateType.COMBINED_MAX)
        uses_specific = entry.rate_type in (DutyRateType.SPECIFIC, DutyRateType.COMBINED_MAX)

        ad_valorem = apply_percent(value, entry.ad_valorem_percent) if uses_ad_valorem else ZERO

        if entry.specific_unit is SpecificRateUnit.KG:
            quantity = cargo.total_weight_kg
        elif entry.specific_unit in (SpecificRateUnit.PAIR, SpecificRateUnit.PIECE):
            quantity = Decimal(cargo.quantity_units)
        else:
            quantity = ZERO
        specific = entry.specific_rate_eur * quantity * D(eur_rate) if uses_specific else ZERO

        if entry.rate_type is DutyRateType.AD_VALOREM:
            duty = ad_valorem
        elif entry.rate_type is DutyRateType.SPECIFIC:
            duty = specific
        else:
            duty = max(ad_valorem, specific)

        return DutyCalculation(
            rate_type=entry.rate_type,
            rate_description=entry.rate_description(),
            customs_value=value,
            ad_valorem_percent=entry.ad_valorem_percent,
            ad_valorem_amount=ad_valorem,
            specific_rate_eur=entry.specific_rate_eur,
            specific_unit=entry.specific_unit,
            specific_quantity=quantity,
            eur_rate=D(eur_rate),
            specific_amount=specific,
            duty=duty,
        )

    # ------------------------------------------------------------- clearance
    def calculate_clearance(
        self,
        jurisdiction: Jurisdiction,
        cargo: CargoSpec,
        fx: FxService,
        *,
        freight_to_border_usd: DecimalLike = ZERO,
        valuation_basis: CustomsValuationBasis = CustomsValuationBasis.INVOICE,
        resolution: TariffResolution | None = None,
    ) -> ClearanceResult:
        """Full official clearance in the jurisdiction's currency (KGS or RUB)."""
        jurisdiction = Jurisdiction(jurisdiction)
        basis = CustomsValuationBasis(valuation_basis)
        profile = self.profile(jurisdiction)
        local = profile.currency
        resolved = resolution or self.resolve_tariff(cargo)
        entry = resolved.entry

        invoice_local = fx.convert_official(
            cargo.declared_value_origin, cargo.origin_currency, local
        )
        freight_local = fx.convert_official(D(freight_to_border_usd), Currency.USD, local)

        if basis is CustomsValuationBasis.CIF:
            customs_value = invoice_local + freight_local
            vat_freight_addon = ZERO
        else:
            customs_value = invoice_local
            vat_freight_addon = freight_local

        duty = self.calculate_duty(
            entry,
            customs_value=customs_value,
            cargo=cargo,
            eur_rate=fx.mid_rate(Currency.EUR, local),
        )

        vat_percent = profile.vat_percent
        if jurisdiction is Jurisdiction.RU and entry.ru_vat_percent_override is not None:
            vat_percent = entry.ru_vat_percent_override
        vat_base = customs_value + duty.duty + vat_freight_addon
        vat = apply_percent(vat_base, vat_percent)

        processing_fee = profile.customs_processing_fee.apply(customs_value)
        broker_fee = profile.broker_fee_local
        taxes_and_fees = duty.duty + vat + processing_fee + broker_fee

        notes = list(resolved.notes)
        notes.append(
            "Customs value = invoice + freight to border (EAEU CC art. 40)"
            if basis is CustomsValuationBasis.CIF
            else "Customs value = invoice (freight to border added to the VAT base only)"
        )
        if entry.marking_required:
            notes.append(
                "Честный ЗНАК marking is mandatory for this tariff line before sale in Russia"
            )

        return ClearanceResult(
            jurisdiction=jurisdiction,
            currency=local,
            tariff=entry,
            tariff_matched_by=resolved.matched_by,
            invoice_value_local=invoice_local,
            freight_to_border_local=freight_local,
            valuation_basis=basis,
            customs_value=customs_value,
            duty=duty,
            vat_percent=vat_percent,
            vat_base=vat_base,
            vat=vat,
            customs_processing_fee=processing_fee,
            broker_fee=broker_fee,
            total_taxes_and_fees=taxes_and_fees,
            total_cleared_cost=invoice_local + taxes_and_fees,
            clearance_days_min=profile.clearance_days_min,
            clearance_days_max=profile.clearance_days_max,
            notes=notes,
        )

    # ------------------------------------------------------------ comparison
    def compare_jurisdictions(
        self,
        cargo: CargoSpec,
        fx: FxService,
        *,
        freight_to_border_usd: DecimalLike = ZERO,
        valuation_basis: CustomsValuationBasis = CustomsValuationBasis.INVOICE,
    ) -> JurisdictionComparison:
        """Kyrgyz EAEU clearance vs direct Russian clearance for the same cargo.

        Both totals are expressed in RUB at official mid rates.  The comparison
        covers customs-related taxes and fees only; the Russian import VAT that
        becomes due on the intra-EAEU transfer is part of the landed-cost routes.
        """
        resolved = self.resolve_tariff(cargo)
        kg = self.calculate_clearance(
            Jurisdiction.KG,
            cargo,
            fx,
            freight_to_border_usd=freight_to_border_usd,
            valuation_basis=valuation_basis,
            resolution=resolved,
        )
        ru = self.calculate_clearance(
            Jurisdiction.RU,
            cargo,
            fx,
            freight_to_border_usd=freight_to_border_usd,
            valuation_basis=valuation_basis,
            resolution=resolved,
        )
        kg_rub = q2(fx.convert_official(kg.total_taxes_and_fees, kg.currency, Currency.RUB))
        ru_rub = q2(fx.convert_official(ru.total_taxes_and_fees, ru.currency, Currency.RUB))
        difference = ru_rub - kg_rub
        return JurisdictionComparison(
            kg=kg,
            ru=ru,
            kg_taxes_and_fees_rub=kg_rub,
            ru_taxes_and_fees_rub=ru_rub,
            difference_rub=difference,
            cheaper_jurisdiction=Jurisdiction.KG if difference >= ZERO else Jurisdiction.RU,
            notes=[
                "Import duty is identical in both jurisdictions (ЕТТ ЕАЭС common tariff).",
                f"VAT at the border: KG {fmt(kg.vat_percent)}% vs RU {fmt(ru.vat_percent)}%.",
                "Russian import VAT on the subsequent intra-EAEU transfer is excluded here; "
                "see OFFICIAL_EAEU_KG routes for the full landed cost.",
            ],
        )
