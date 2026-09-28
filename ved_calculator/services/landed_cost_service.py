"""Landed-cost assembly for one route candidate.

Three route families are modelled:

``OFFICIAL_EAEU_KG`` (Route A, "белая растаможка")
    Supplier → Bishkek ОсОО (official KG declaration: duty, 12 % VAT, fees) →
    intra-EAEU transfer at 0 % export VAT → Russian ИП/ООО pays Russian import
    VAT (22 %) to the tax office on the transfer price, plus certification,
    Честный ЗНАК marking and domestic on-carriage.

``CARGO_SIMPLIFIED`` (Route B, "карго / упрощёнка")
    Flat all-in $/kg cargo rate to Bishkek, no declaration, no VAT invoice,
    no marking → cheapest on paper, HIGH_CUSTOMS / MEDIUM_TRANSIT risk.

``OFFICIAL_RU_DIRECT`` (benchmark)
    Direct white import into Russia with a payment agent, Russian customs fees
    and 22 % VAT at the border.

All components are booked in RUB at the mid rate; the δ_fx premium of every
foreign-currency component is accumulated separately as ``fx_risk_buffer`` so
the breakdown stays transparent and sums exactly to the total.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ved_calculator.domain.models import (
    RISK_SCORE_BY_LEVEL,
    CargoCategory,
    ClearanceType,
    CorridorRateCard,
    CostBreakdown,
    Currency,
    DomesticLegRate,
    DomesticQuote,
    FreightQuote,
    Jurisdiction,
    OriginCountry,
    RecipientTaxRegime,
    RiskLevel,
    RouteComparisonResult,
    ServiceFeeSchedule,
    TariffEntry,
    TransferCorridor,
    TransportMode,
    VEDCalculationRequest,
)
from ved_calculator.domain.money import (
    HUNDRED,
    ZERO,
    D,
    DecimalLike,
    apply_percent,
    fmt,
    q2,
    safe_div,
)
from ved_calculator.reference.cities import city_title
from ved_calculator.reference.fees import DEFAULT_SERVICE_FEES
from ved_calculator.services.customs_service import CustomsService
from ved_calculator.services.freight_service import FreightService
from ved_calculator.services.fx_service import FxService

__all__ = ["LandedCostService", "RouteCandidate"]


@dataclass(frozen=True)
class RouteCandidate:
    """One concrete route: clearance family + international corridor + domestic leg."""

    clearance_type: ClearanceType
    corridor: CorridorRateCard
    domestic_leg: DomesticLegRate
    domestic_is_fallback: bool = False


_MODE_TITLES: dict[TransportMode, str] = {
    TransportMode.AUTO_EXPRESS: "Auto-Express",
    TransportMode.AUTO_STANDARD: "Auto-Standard",
    TransportMode.RAIL: "Rail",
    TransportMode.AIR: "Air",
    TransportMode.SEA_MULTIMODAL: "Sea-Multimodal",
    TransportMode.TRUCK: "Truck",
}
_ORIGIN_TITLES: dict[OriginCountry, str] = {
    OriginCountry.CHINA: "China",
    OriginCountry.TURKEY: "Turkey",
    OriginCountry.EU: "EU",
    OriginCountry.USA: "USA",
    OriginCountry.UAE: "UAE",
    OriginCountry.VIETNAM: "Vietnam",
}
_SCHEME_TITLES: dict[ClearanceType, str] = {
    ClearanceType.OFFICIAL_EAEU_KG: "White-Customs",
    ClearanceType.CARGO_SIMPLIFIED: "Cargo",
    ClearanceType.OFFICIAL_RU_DIRECT: "Direct-Customs",
}


class _RubLedger:
    """Books cost components in RUB at mid rate; accumulates the FX buffer separately."""

    def __init__(self, fx: FxService) -> None:
        self.fx = fx
        self.mid: dict[str, Decimal] = dict.fromkeys(CostBreakdown.component_names(), ZERO)
        self.buffer = ZERO

    def add(self, key: str, amount: DecimalLike, currency: Currency) -> Decimal:
        """Book ``amount`` under ``key`` and return its *buffered* RUB value."""
        value = D(amount)
        if value == ZERO:
            return ZERO
        if currency is Currency.RUB:
            self.mid[key] += value
            return value
        conversion = self.fx.convert_with_buffer(value, currency, Currency.RUB)
        self.mid[key] += conversion.amount_at_mid
        self.buffer += conversion.buffer_cost
        return conversion.amount_buffered

    def add_rub(self, key: str, amount: DecimalLike) -> Decimal:
        return self.add(key, amount, Currency.RUB)

    def breakdown(self) -> CostBreakdown:
        data = dict(self.mid)
        data["fx_risk_buffer"] = self.buffer
        return CostBreakdown(**data)


class LandedCostService:
    """Turns a :class:`RouteCandidate` into a fully costed :class:`RouteComparisonResult`."""

    def __init__(
        self,
        customs: CustomsService,
        freight: FreightService,
        service_fees: ServiceFeeSchedule = DEFAULT_SERVICE_FEES,
    ) -> None:
        self.customs = customs
        self.freight = freight
        self.service_fees = service_fees

    # ---------------------------------------------------------------- public
    def evaluate(
        self, request: VEDCalculationRequest, candidate: RouteCandidate, fx: FxService
    ) -> RouteComparisonResult:
        freight_quote = self.freight.quote_corridor(candidate.corridor, request.cargo)
        domestic_quote = self.freight.quote_domestic(
            candidate.domestic_leg, request.cargo, is_fallback=candidate.domestic_is_fallback
        )
        if candidate.clearance_type is ClearanceType.OFFICIAL_EAEU_KG:
            return self._white_kg(request, candidate, fx, freight_quote, domestic_quote)
        if candidate.clearance_type is ClearanceType.CARGO_SIMPLIFIED:
            return self._cargo(request, candidate, fx, freight_quote, domestic_quote)
        return self._direct_ru(request, candidate, fx, freight_quote, domestic_quote)

    # ------------------------------------------------- Route A: white via KG
    def _white_kg(
        self,
        request: VEDCalculationRequest,
        candidate: RouteCandidate,
        fx: FxService,
        fq: FreightQuote,
        dq: DomesticQuote,
    ) -> RouteComparisonResult:
        cargo, a = request.cargo, request.assumptions
        origin_ccy, value = cargo.origin_currency, cargo.declared_value_origin
        ledger = _RubLedger(fx)
        notes: list[str] = []
        recoverable = ZERO

        # ОсОО outlays -------------------------------------------------------
        goods = ledger.add("goods_value", value, origin_ccy)
        supplier_leg = fx.bank_leg(
            TransferCorridor.for_supplier_currency(origin_ccy), value, origin_ccy
        )
        bank_supplier = ledger.add("bank_fees", supplier_leg.total, supplier_leg.currency)
        freight = ledger.add("international_freight", fq.freight_usd, Currency.USD)
        handling = ledger.add("hub_handling", fq.handling_usd, Currency.USD)
        insurance = ledger.add(
            "insurance", apply_percent(value, a.insurance_percent_white), origin_ccy
        )

        clearance = self.customs.calculate_clearance(
            Jurisdiction.KG,
            cargo,
            fx,
            freight_to_border_usd=fq.freight_usd,
            valuation_basis=a.customs_valuation_basis,
        )
        kgs = clearance.currency
        duty = ledger.add("customs_duty", clearance.duty.duty, kgs)
        processing = ledger.add("customs_processing_fee", clearance.customs_processing_fee, kgs)
        broker = ledger.add("broker_fee", clearance.broker_fee, kgs)
        if a.kg_import_vat_recoverable:
            recoverable += fx.convert_official(clearance.vat, kgs, Currency.RUB)
            vat_kg = ZERO
            notes.append(
                "KG import VAT (12%) treated as recoverable via the 0% EAEU export — cash-flow only."
            )
        else:
            vat_kg = ledger.add("import_vat_kg", clearance.vat, kgs)
            notes.append(
                "KG import VAT (12%) treated as a sunk cost of the ОсОО (specification formula B)."
            )

        osoo_outlays = (
            goods
            + bank_supplier
            + freight
            + handling
            + insurance
            + duty
            + processing
            + broker
            + vat_kg
        )
        markup = apply_percent(osoo_outlays, a.agent_markup_percent)
        ledger.add_rub("agent_markup", markup)
        transfer_price = osoo_outlays + markup  # ОсОО invoice to the Russian buyer

        # Russian side ---------------------------------------------------------
        ru_vat_percent = self._ru_vat_percent(clearance.tariff)
        vat_ru = apply_percent(transfer_price, ru_vat_percent)
        if a.recipient_tax_regime is RecipientTaxRegime.OSNO:
            recoverable += vat_ru
            notes.append(
                f"RU import VAT ({fmt(ru_vat_percent)}%) on the EAEU transfer "
                "is deductible (ОСНО) — cash-flow only."
            )
        else:
            ledger.add_rub("import_vat_ru", vat_ru)
            notes.append(
                f"RU import VAT ({fmt(ru_vat_percent)}%) on the EAEU transfer price is a sunk cost (УСН)."
            )
        buyer_leg = fx.bank_leg(TransferCorridor.RUB_KGS_LOCAL, transfer_price, Currency.RUB)
        ledger.add("bank_fees", buyer_leg.total, buyer_leg.currency)
        self._ru_side_fees(ledger, request, clearance.tariff, notes)
        ledger.add_rub("local_transport", dq.cost_rub)

        notes.extend(clearance.notes)
        return self._finalize(
            request,
            candidate,
            fx,
            fq,
            dq,
            ledger,
            recoverable_vat=recoverable,
            risk_level=RiskLevel.LOW_LEGAL,
            notes=notes,
        )

    # --------------------------------------------------- Route B: cargo
    def _cargo(
        self,
        request: VEDCalculationRequest,
        candidate: RouteCandidate,
        fx: FxService,
        fq: FreightQuote,
        dq: DomesticQuote,
    ) -> RouteComparisonResult:
        cargo, a = request.cargo, request.assumptions
        origin_ccy, value = cargo.origin_currency, cargo.declared_value_origin
        ledger = _RubLedger(fx)
        tariff = self.customs.resolve_tariff(cargo).entry

        goods = ledger.add("goods_value", value, origin_ccy)
        supplier_leg = fx.bank_leg(
            TransferCorridor.for_supplier_currency(origin_ccy), value, origin_ccy
        )
        bank_supplier = ledger.add("bank_fees", supplier_leg.total, supplier_leg.currency)
        freight = ledger.add("international_freight", fq.freight_usd, Currency.USD)
        handling = ledger.add("hub_handling", fq.handling_usd, Currency.USD)
        insurance = ledger.add(
            "insurance", apply_percent(value, a.insurance_percent_cargo), origin_ccy
        )

        outlays = goods + bank_supplier + freight + handling + insurance
        markup = apply_percent(outlays, a.agent_markup_percent)
        ledger.add_rub("agent_markup", markup)
        buyer_leg = fx.bank_leg(TransferCorridor.RUB_KGS_LOCAL, outlays + markup, Currency.RUB)
        ledger.add("bank_fees", buyer_leg.total, buyer_leg.currency)
        ledger.add_rub("local_transport", dq.cost_rub)

        risk = self._cargo_risk(tariff, cargo.category)
        notes = [
            "Cargo rate is all-in ($/kg incl. simplified clearance); no customs declaration, "
            "no VAT invoice and no import VAT credit in Russia.",
        ]
        if tariff.marking_required:
            notes.append(
                "Goods arrive without Честный ЗНАК codes — cannot be legally sold on marketplaces/retail."
            )
        if cargo.category is CargoCategory.ELECTRONICS:
            notes.append(
                "High-value electronics without documents carry elevated seizure risk at the KZ/RU border."
            )
        return self._finalize(
            request,
            candidate,
            fx,
            fq,
            dq,
            ledger,
            recoverable_vat=ZERO,
            risk_level=risk,
            notes=notes,
        )

    # ------------------------------------------- Benchmark: direct RU import
    def _direct_ru(
        self,
        request: VEDCalculationRequest,
        candidate: RouteCandidate,
        fx: FxService,
        fq: FreightQuote,
        dq: DomesticQuote,
    ) -> RouteComparisonResult:
        cargo, a = request.cargo, request.assumptions
        origin_ccy, value = cargo.origin_currency, cargo.declared_value_origin
        ledger = _RubLedger(fx)
        notes: list[str] = []
        recoverable = ZERO

        goods = ledger.add("goods_value", value, origin_ccy)
        ledger.add_rub("payment_agent_fee", apply_percent(goods, a.payment_agent_fee_percent))
        ledger.add("international_freight", fq.freight_usd, Currency.USD)
        ledger.add("hub_handling", fq.handling_usd, Currency.USD)
        ledger.add("insurance", apply_percent(value, a.insurance_percent_white), origin_ccy)

        clearance = self.customs.calculate_clearance(
            Jurisdiction.RU,
            cargo,
            fx,
            freight_to_border_usd=fq.freight_usd,
            valuation_basis=a.customs_valuation_basis,
        )
        rub = clearance.currency
        ledger.add("customs_duty", clearance.duty.duty, rub)
        ledger.add("customs_processing_fee", clearance.customs_processing_fee, rub)
        ledger.add("broker_fee", clearance.broker_fee, rub)
        if a.recipient_tax_regime is RecipientTaxRegime.OSNO:
            recoverable += clearance.vat
            notes.append(
                f"RU import VAT ({fmt(clearance.vat_percent)}%) at the border "
                "is deductible (ОСНО) — cash-flow only."
            )
        else:
            ledger.add("import_vat_ru", clearance.vat, rub)
            notes.append(
                f"RU import VAT ({fmt(clearance.vat_percent)}%) at the border is a sunk cost (УСН)."
            )
        self._ru_side_fees(ledger, request, clearance.tariff, notes)
        ledger.add_rub("local_transport", dq.cost_rub)

        notes.append(
            f"Supplier paid from Russia through a payment agent ({fmt(a.payment_agent_fee_percent)}%)."
        )
        notes.extend(clearance.notes)
        return self._finalize(
            request,
            candidate,
            fx,
            fq,
            dq,
            ledger,
            recoverable_vat=recoverable,
            risk_level=RiskLevel.LOW_LEGAL,
            notes=notes,
        )

    # --------------------------------------------------------------- helpers
    def _ru_vat_percent(self, tariff: TariffEntry) -> Decimal:
        profile = self.customs.profile(Jurisdiction.RU)
        if tariff.ru_vat_percent_override is not None:
            return tariff.ru_vat_percent_override
        return profile.vat_percent

    def _ru_side_fees(
        self,
        ledger: _RubLedger,
        request: VEDCalculationRequest,
        tariff: TariffEntry,
        notes: list[str],
    ) -> None:
        cargo, a = request.cargo, request.assumptions
        if not a.has_valid_certificates:
            ledger.add_rub(
                "certification_fee", self.service_fees.certification_fee_rub[cargo.category]
            )
            if tariff.certification_scheme:
                notes.append(f"Conformity assessment: {tariff.certification_scheme}.")
        if tariff.marking_required and a.apply_marking:
            per_unit = (
                self.service_fees.marking_code_cost_rub
                + self.service_fees.marking_application_cost_rub_per_unit
            )
            ledger.add_rub("marking_fee", per_unit * cargo.quantity_units)
        if (
            tariff.ru_technology_fee_rub_per_unit > ZERO
            and a.calculation_date >= self.service_fees.ru_technology_fee_effective_from
        ):
            ledger.add_rub(
                "technology_fee", tariff.ru_technology_fee_rub_per_unit * cargo.quantity_units
            )
            notes.append(
                f"Технологический сбор {fmt(tariff.ru_technology_fee_rub_per_unit)} ₽/unit "
                f"applies from {self.service_fees.ru_technology_fee_effective_from.isoformat()}."
            )

    @staticmethod
    def _cargo_risk(tariff: TariffEntry, category: CargoCategory) -> RiskLevel:
        if tariff.marking_required or category is CargoCategory.ELECTRONICS:
            return RiskLevel.HIGH_CUSTOMS
        return RiskLevel.MEDIUM_TRANSIT

    @staticmethod
    def route_names(request: VEDCalculationRequest, candidate: RouteCandidate) -> tuple[str, str]:
        """``(route_id, route_name)`` for a candidate, e.g. ``China-Bishkek-White-Customs-Auto-Express``."""
        hub = candidate.corridor.destination_hub
        name = "-".join(
            [
                _ORIGIN_TITLES[request.origin_country],
                hub,
                _SCHEME_TITLES[candidate.clearance_type],
                _MODE_TITLES[candidate.corridor.transport_mode],
            ]
        )
        if candidate.domestic_leg.transport_mode is not TransportMode.TRUCK:
            name += f"+{_MODE_TITLES[candidate.domestic_leg.transport_mode]}"
        route_id = "-".join(
            [
                request.origin_country.value.lower(),
                hub.lower(),
                candidate.clearance_type.value.lower(),
                candidate.corridor.transport_mode.value.lower(),
                candidate.domestic_leg.transport_mode.value.lower(),
                candidate.domestic_leg.destination_city,
            ]
        ).replace("_", "-")
        return route_id, name

    def _finalize(
        self,
        request: VEDCalculationRequest,
        candidate: RouteCandidate,
        fx: FxService,
        fq: FreightQuote,
        dq: DomesticQuote,
        ledger: _RubLedger,
        *,
        recoverable_vat: Decimal,
        risk_level: RiskLevel,
        notes: list[str],
    ) -> RouteComparisonResult:
        cargo = request.cargo
        hub_days = self.service_fees.hub_processing_days[candidate.clearance_type]
        days_min = fq.days_min + hub_days.days_min + dq.days_min
        days_max = fq.days_max + hub_days.days_max + dq.days_max

        rounded = ledger.breakdown().rounded()
        total = rounded.total()
        per_unit = q2(safe_div(total, cargo.quantity_units))
        per_kg = q2(safe_div(total, cargo.total_weight_kg))

        margin: Decimal | None = None
        if request.target_sale_price_rub_per_unit is not None:
            price = request.target_sale_price_rub_per_unit
            margin = q2(safe_div(price - per_unit, price) * HUNDRED)
            if margin < ZERO:
                notes.append(
                    "Negative gross margin at the target sale price — route does not protect margin."
                )

        violations: list[str] = []
        meets_deadline: bool | None = None
        if request.target_delivery_days_max is not None:
            meets_deadline = days_max <= request.target_delivery_days_max
            if not meets_deadline:
                violations.append(
                    f"estimated_days_max {days_max} exceeds target_delivery_days_max "
                    f"{request.target_delivery_days_max}"
                )
        if dq.is_fallback:
            notes.append(
                f"No configured domestic leg for '{request.destination_city_ru}'; "
                f"fallback rate from {dq.from_hub} applied."
            )

        pairs = [
            (cargo.origin_currency, Currency.KGS),
            (cargo.origin_currency, Currency.RUB),
            (Currency.USD, Currency.KGS),
            (Currency.USD, Currency.RUB),
            (Currency.KGS, Currency.RUB),
            (Currency.EUR, Currency.KGS),
            (Currency.EUR, Currency.RUB),
        ]
        route_id, route_name = self.route_names(request, candidate)
        return RouteComparisonResult(
            route_id=route_id,
            route_name=route_name,
            clearance_type=candidate.clearance_type,
            origin_country=request.origin_country,
            hub=candidate.corridor.destination_hub,
            destination_city_ru=city_title(dq.destination_city),
            transport_mode=candidate.corridor.transport_mode,
            domestic_transport_mode=dq.transport_mode,
            total_cost_rub=total,
            cost_per_unit_rub=per_unit,
            cost_per_kg_rub=per_kg,
            estimated_days_min=days_min,
            estimated_days_max=days_max,
            breakdown=rounded.components(),
            recoverable_vat_rub=q2(recoverable_vat),
            risk_level=risk_level,
            risk_score=RISK_SCORE_BY_LEVEL[risk_level],
            chargeable_weight_kg=fq.chargeable_weight_kg,
            fx_rates_used=fx.snapshot(pairs),
            gross_margin_percent=margin,
            meets_deadline=meets_deadline,
            constraint_violations=violations,
            notes=notes,
        )
