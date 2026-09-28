"""Engine facade: wires reference data and services into one calculator.

    >>> from ved_calculator import VEDCalculatorEngine, VEDCalculationRequest
    >>> engine = VEDCalculatorEngine()            # default reference data
    >>> result = engine.calculate({...})           # dict or VEDCalculationRequest
    >>> result.optimal.route_name

Every dependency can be injected (live FX table, customer-specific rate cards,
updated tariff lines) without touching the services.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import Decimal
from functools import lru_cache
from typing import Any

from ved_calculator.domain.models import (
    BankFeeSchedule,
    CargoSpec,
    CorridorRateCard,
    CustomsValuationBasis,
    DomesticLegRate,
    FxRateTable,
    Jurisdiction,
    JurisdictionComparison,
    JurisdictionTaxProfile,
    OptimizationPolicy,
    OptimizationResult,
    OriginCountry,
    RouteComparisonResult,
    ServiceFeeSchedule,
    TariffMatrix,
    VEDCalculationRequest,
)
from ved_calculator.domain.money import ZERO, DecimalLike
from ved_calculator.reference import (
    DEFAULT_BANK_FEES,
    DEFAULT_CORRIDORS,
    DEFAULT_DOMESTIC_LEGS,
    DEFAULT_FALLBACK_DOMESTIC,
    DEFAULT_FX_TABLE,
    DEFAULT_SERVICE_FEES,
    DEFAULT_TARIFF_MATRIX,
    DEFAULT_TAX_PROFILES,
)
from ved_calculator.services.customs_service import CustomsService
from ved_calculator.services.freight_service import FreightService
from ved_calculator.services.fx_service import FxService
from ved_calculator.services.landed_cost_service import LandedCostService
from ved_calculator.services.optimizer import RouteOptimizer

__all__ = ["VEDCalculatorEngine", "calculate", "default_engine"]


class VEDCalculatorEngine:
    """Composition root of the VED Calculator Core."""

    def __init__(
        self,
        *,
        fx_table: FxRateTable = DEFAULT_FX_TABLE,
        tariffs: TariffMatrix = DEFAULT_TARIFF_MATRIX,
        corridors: Iterable[CorridorRateCard] = DEFAULT_CORRIDORS,
        domestic_legs: Iterable[DomesticLegRate] = DEFAULT_DOMESTIC_LEGS,
        fallback_domestic: Mapping[str, DomesticLegRate] = DEFAULT_FALLBACK_DOMESTIC,
        tax_profiles: Mapping[Jurisdiction, JurisdictionTaxProfile] = DEFAULT_TAX_PROFILES,
        bank_fees: BankFeeSchedule = DEFAULT_BANK_FEES,
        service_fees: ServiceFeeSchedule = DEFAULT_SERVICE_FEES,
        policy: OptimizationPolicy | None = None,
    ) -> None:
        self.fx_table = fx_table
        self.bank_fees = bank_fees
        self.customs = CustomsService(tariffs, tax_profiles)
        self.freight = FreightService(corridors, domestic_legs, fallback_domestic)
        self.landed_cost = LandedCostService(self.customs, self.freight, service_fees)
        self.optimizer = RouteOptimizer(
            self.landed_cost, self.freight, fx_table, bank_fees, policy or OptimizationPolicy()
        )

    # ---------------------------------------------------------------- facade
    @staticmethod
    def parse_request(request: VEDCalculationRequest | Mapping[str, Any]) -> VEDCalculationRequest:
        if isinstance(request, VEDCalculationRequest):
            return request
        return VEDCalculationRequest.model_validate(request)

    def calculate(self, request: VEDCalculationRequest | Mapping[str, Any]) -> OptimizationResult:
        """Evaluate every available route and return the ranked comparison."""
        return self.optimizer.optimize(self.parse_request(request))

    def evaluate_routes(
        self, request: VEDCalculationRequest | Mapping[str, Any]
    ) -> list[RouteComparisonResult]:
        """All priced routes without ranking (useful for matrices/exports)."""
        routes, _ = self.optimizer.evaluate_routes(self.parse_request(request))
        return routes

    def fx_service(self, risk_buffer_percent: DecimalLike = ZERO) -> FxService:
        return FxService(
            self.fx_table, risk_buffer_percent=risk_buffer_percent, bank_fees=self.bank_fees
        )

    def compare_customs(
        self,
        cargo: CargoSpec | Mapping[str, Any],
        *,
        freight_to_border_usd: DecimalLike = ZERO,
        valuation_basis: CustomsValuationBasis = CustomsValuationBasis.INVOICE,
    ) -> JurisdictionComparison:
        """Module 1 comparison: Kyrgyz EAEU clearance vs direct Russian clearance."""
        spec = cargo if isinstance(cargo, CargoSpec) else CargoSpec.model_validate(cargo)
        return self.customs.compare_jurisdictions(
            spec,
            self.fx_service(),
            freight_to_border_usd=freight_to_border_usd,
            valuation_basis=valuation_basis,
        )

    def corridors_for(self, origin: OriginCountry) -> list[CorridorRateCard]:
        return self.freight.corridors_for(origin)

    @property
    def fx_buffer_default(self) -> Decimal:
        return VEDCalculationRequest.model_fields["fx_risk_buffer_percent"].get_default()  # type: ignore[no-any-return]


@lru_cache(maxsize=1)
def default_engine() -> VEDCalculatorEngine:
    """Process-wide engine built from the bundled reference data."""
    return VEDCalculatorEngine()


def calculate(request: VEDCalculationRequest | Mapping[str, Any]) -> OptimizationResult:
    """Convenience wrapper around :meth:`VEDCalculatorEngine.calculate`."""
    return default_engine().calculate(request)
