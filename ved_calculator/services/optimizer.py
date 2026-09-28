"""Module 4 — Route Optimization Engine.

Enumerates every (clearance family × international corridor × domestic leg)
combination available for the request, prices each one through
:class:`~ved_calculator.services.landed_cost_service.LandedCostService` and
returns:

1. **Cheapest legal route** – minimal total landed cost (bulk margin).
2. **Fastest route** – minimal ``estimated_days_max`` (express inventory).
3. **Optimal / hybrid route** – minimal *risk-adjusted cost* (see
   :class:`~ved_calculator.domain.models.OptimizationPolicy`)::

       adjusted = total_cost × (1 + delay_cost_per_day × days_max
                                  + expected_loss[risk_level])

   By default the recommendation is restricted to LOW_LEGAL routes, so a grey
   cargo route can be reported as CHEAPEST but is never recommended.

Hard constraints (``target_delivery_days_max``) exclude routes from the
recommendation pool; if nothing satisfies them, the pool falls back to all
routes and a warning is emitted.
"""

from __future__ import annotations

from ved_calculator.domain.models import (
    RECOMMENDED_FX_BUFFER_RANGE,
    BankFeeSchedule,
    ClearanceType,
    FxRateTable,
    OptimizationPolicy,
    OptimizationResult,
    RiskLevel,
    RouteComparisonResult,
    ServiceKind,
    VEDCalculationRequest,
)
from ved_calculator.domain.money import ZERO, q2
from ved_calculator.reference.corridors import BISHKEK, MOSCOW
from ved_calculator.reference.fees import DEFAULT_BANK_FEES
from ved_calculator.reference.fx_rates import DEFAULT_FX_TABLE
from ved_calculator.services.freight_service import FreightService
from ved_calculator.services.fx_service import FxService
from ved_calculator.services.landed_cost_service import LandedCostService, RouteCandidate

__all__ = ["HUB_FOR_CLEARANCE", "RouteOptimizer"]

HUB_FOR_CLEARANCE: dict[ClearanceType, tuple[str, ServiceKind]] = {
    ClearanceType.OFFICIAL_EAEU_KG: (BISHKEK, ServiceKind.WHITE_FREIGHT),
    ClearanceType.CARGO_SIMPLIFIED: (BISHKEK, ServiceKind.CARGO_ALL_IN),
    ClearanceType.OFFICIAL_RU_DIRECT: (MOSCOW, ServiceKind.WHITE_FREIGHT),
}


class RouteOptimizer:
    def __init__(
        self,
        landed_cost: LandedCostService,
        freight: FreightService,
        fx_table: FxRateTable = DEFAULT_FX_TABLE,
        bank_fees: BankFeeSchedule = DEFAULT_BANK_FEES,
        policy: OptimizationPolicy | None = None,
    ) -> None:
        self.landed_cost = landed_cost
        self.freight = freight
        self.fx_table = fx_table
        self.bank_fees = bank_fees
        self.policy = policy or OptimizationPolicy()

    # ------------------------------------------------------------ pipeline
    def fx_for(self, request: VEDCalculationRequest) -> FxService:
        return FxService(
            self.fx_table,
            risk_buffer_percent=request.fx_risk_buffer_percent,
            bank_fees=self.bank_fees,
        )

    def enumerate_candidates(
        self, request: VEDCalculationRequest
    ) -> tuple[list[RouteCandidate], list[str]]:
        candidates: list[RouteCandidate] = []
        warnings: list[str] = []
        fallback_reported: set[str] = set()
        for clearance in request.allowed_clearance_types():
            hub, kind = HUB_FOR_CLEARANCE[clearance]
            corridors = self.freight.corridors_for(request.origin_country, kind, hub)
            if not corridors:
                warnings.append(
                    f"No {kind.value} corridors configured for {request.origin_country.value} → {hub}; "
                    f"{clearance.value} routes skipped."
                )
                continue
            legs, is_fallback = self.freight.domestic_legs_for(hub, request.destination_city_ru)
            if not legs:
                warnings.append(
                    f"No domestic legs configured from {hub}; {clearance.value} routes skipped."
                )
                continue
            if is_fallback and hub not in fallback_reported:
                fallback_reported.add(hub)
                warnings.append(
                    f"Destination '{request.destination_city_ru}' has no configured rate from {hub}; "
                    "a conservative fallback domestic rate was used."
                )
            for corridor in corridors:
                for leg in legs:
                    candidates.append(RouteCandidate(clearance, corridor, leg, is_fallback))
        return candidates, warnings

    def evaluate_routes(
        self, request: VEDCalculationRequest
    ) -> tuple[list[RouteComparisonResult], list[str]]:
        candidates, warnings = self.enumerate_candidates(request)
        fx = self.fx_for(request)
        routes = [self.landed_cost.evaluate(request, candidate, fx) for candidate in candidates]
        return routes, warnings

    def optimize(self, request: VEDCalculationRequest) -> OptimizationResult:
        routes, warnings = self.evaluate_routes(request)
        low, high = RECOMMENDED_FX_BUFFER_RANGE
        if not low <= request.fx_risk_buffer_percent <= high:
            warnings.append(
                f"fx_risk_buffer_percent={request.fx_risk_buffer_percent} is outside the recommended "
                f"{low}–{high}% band."
            )
        if not routes:
            warnings.append("No routes could be evaluated for this request.")
            return OptimizationResult(
                request=request,
                routes=[],
                warnings=warnings,
                summary="No routes available.",
                fx_as_of=self.fx_table.as_of,
            )

        feasible = [r for r in routes if not r.constraint_violations]
        excluded = [r for r in routes if r.constraint_violations]
        if not feasible:
            warnings.append(
                f"No route meets target_delivery_days_max={request.target_delivery_days_max}; "
                "rankings were computed over all routes."
            )
            feasible, excluded = routes, []

        self.score(feasible)
        by_cost = lambda r: (r.total_cost_rub, r.estimated_days_max, r.route_id)  # noqa: E731
        by_time = lambda r: (  # noqa: E731
            r.estimated_days_max,
            r.estimated_days_min,
            r.total_cost_rub,
            r.route_id,
        )
        by_adjusted = lambda r: (r.risk_adjusted_cost_rub or ZERO, r.total_cost_rub, r.route_id)  # noqa: E731

        cheapest = min(feasible, key=by_cost)
        fastest = min(feasible, key=by_time)
        legal = [r for r in feasible if r.risk_level is RiskLevel.LOW_LEGAL]
        cheapest_legal = min(legal, key=by_cost) if legal else None
        pool = legal if (self.policy.prefer_legal_routes and legal) else feasible
        optimal = min(pool, key=by_adjusted)
        if not legal:
            warnings.append(
                "No LOW_LEGAL route available; the recommendation carries transit/customs risk."
            )

        picks: list[tuple[RouteComparisonResult | None, str]] = [
            (cheapest, "CHEAPEST"),
            (cheapest_legal, "CHEAPEST_LEGAL"),
            (fastest, "FASTEST"),
            (optimal, "OPTIMAL"),
        ]
        for route, label in picks:
            if route is not None and label not in route.labels:
                route.labels = [*route.labels, label]
        optimal.is_recommended = True

        feasible.sort(key=by_cost)
        excluded.sort(key=by_cost)
        return OptimizationResult(
            request=request,
            routes=feasible,
            excluded_routes=excluded,
            cheapest_route_id=cheapest.route_id,
            cheapest_legal_route_id=cheapest_legal.route_id if cheapest_legal else None,
            fastest_route_id=fastest.route_id,
            optimal_route_id=optimal.route_id,
            warnings=warnings,
            summary=self._summary(cheapest, cheapest_legal, fastest, optimal),
            fx_as_of=self.fx_table.as_of,
        )

    # -------------------------------------------------------------- scoring
    def score(self, routes: list[RouteComparisonResult]) -> None:
        """Assign ``risk_adjusted_cost_rub`` in place (lower is better)."""
        for route in routes:
            route.risk_adjusted_cost_rub = q2(
                self.policy.risk_adjusted_cost(
                    route.total_cost_rub, route.estimated_days_max, route.risk_level
                )
            )

    @staticmethod
    def _describe(route: RouteComparisonResult) -> str:
        return (
            f"{route.route_name} — {route.total_cost_rub:,.2f} RUB "
            f"({route.cost_per_unit_rub:,.2f} RUB/unit), "
            f"{route.estimated_days_min}–{route.estimated_days_max} days, {route.risk_level.value}"
        )

    def _summary(
        self,
        cheapest: RouteComparisonResult,
        cheapest_legal: RouteComparisonResult | None,
        fastest: RouteComparisonResult,
        optimal: RouteComparisonResult,
    ) -> str:
        parts = [f"Optimal (recommended): {self._describe(optimal)}."]
        parts.append(f"Cheapest: {self._describe(cheapest)}.")
        if cheapest_legal is not None and cheapest_legal.route_id != cheapest.route_id:
            parts.append(f"Cheapest legal: {self._describe(cheapest_legal)}.")
        parts.append(f"Fastest: {self._describe(fastest)}.")
        return " ".join(parts)
