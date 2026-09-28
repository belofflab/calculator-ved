"""Module 2 — Multi-Country Logistics Router.

Chargeable weight follows the density rule

    W_chargeable = max(W_actual_kg, V_m3 × k_volumetric)

and the leg cost is

    Cost = max(W_chargeable × rate × category_multiplier, min_charge) + handling.

International corridors (origin hub → Bishkek/Moscow) are priced in USD, the
domestic on-carriage (hub → Russian city) in RUB.  Unknown Russian cities fall
back to a conservative hub-specific rate and are flagged.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import Decimal

from ved_calculator.domain.models import (
    CargoSpec,
    CorridorRateCard,
    DomesticLegRate,
    DomesticQuote,
    FreightQuote,
    OriginCountry,
    ServiceKind,
)
from ved_calculator.domain.money import D, DecimalLike
from ved_calculator.reference.cities import normalize_city
from ved_calculator.reference.corridors import (
    DEFAULT_CORRIDORS,
    DEFAULT_DOMESTIC_LEGS,
    DEFAULT_FALLBACK_DOMESTIC,
)

__all__ = ["FreightService"]


class FreightService:
    """Rate-card based freight quoting for international and domestic legs."""

    def __init__(
        self,
        corridors: Iterable[CorridorRateCard] = DEFAULT_CORRIDORS,
        domestic_legs: Iterable[DomesticLegRate] = DEFAULT_DOMESTIC_LEGS,
        fallback_domestic: Mapping[str, DomesticLegRate] | None = None,
    ) -> None:
        self._corridors = tuple(corridors)
        self._legs = tuple(domestic_legs)
        self._fallback = dict(
            DEFAULT_FALLBACK_DOMESTIC if fallback_domestic is None else fallback_domestic
        )
        ids = [c.corridor_id for c in self._corridors]
        if len(ids) != len(set(ids)):
            raise ValueError("corridor ids must be unique")

    # ------------------------------------------------------------ catalogue
    @property
    def corridors(self) -> tuple[CorridorRateCard, ...]:
        return self._corridors

    @property
    def domestic_legs(self) -> tuple[DomesticLegRate, ...]:
        return self._legs

    def corridor(self, corridor_id: str) -> CorridorRateCard:
        for card in self._corridors:
            if card.corridor_id == corridor_id:
                return card
        raise KeyError(f"unknown corridor {corridor_id!r}")

    def corridors_for(
        self,
        origin: OriginCountry,
        service_kind: ServiceKind | None = None,
        destination_hub: str | None = None,
    ) -> list[CorridorRateCard]:
        origin = OriginCountry(origin)
        return [
            card
            for card in self._corridors
            if card.origin is origin
            and (service_kind is None or card.service_kind is ServiceKind(service_kind))
            and (destination_hub is None or card.destination_hub == destination_hub)
        ]

    def hubs_for(self, origin: OriginCountry) -> list[str]:
        seen: list[str] = []
        for card in self.corridors_for(origin):
            if card.destination_hub not in seen:
                seen.append(card.destination_hub)
        return seen

    # --------------------------------------------------------------- maths
    @staticmethod
    def chargeable_weight(
        weight_kg: DecimalLike, volume_m3: DecimalLike, coefficient_kg_per_m3: DecimalLike
    ) -> Decimal:
        """``max(actual weight, volume × volumetric coefficient)``."""
        return max(D(weight_kg), D(volume_m3) * D(coefficient_kg_per_m3))

    def quote_corridor(self, card: CorridorRateCard, cargo: CargoSpec) -> FreightQuote:
        volumetric = cargo.total_volume_m3 * card.volumetric_coefficient_kg_per_m3
        chargeable = self.chargeable_weight(
            cargo.total_weight_kg, cargo.total_volume_m3, card.volumetric_coefficient_kg_per_m3
        )
        multiplier = card.multiplier_for(cargo.category)
        rate = card.rate_per_kg_usd * multiplier
        base = chargeable * rate
        min_applied = base < card.min_charge_usd
        freight = card.min_charge_usd if min_applied else base
        handling = card.handling_fixed_usd + card.handling_per_kg_usd * chargeable
        return FreightQuote(
            corridor_id=card.corridor_id,
            transport_mode=card.transport_mode,
            service_kind=card.service_kind,
            destination_hub=card.destination_hub,
            actual_weight_kg=cargo.total_weight_kg,
            volumetric_weight_kg=volumetric,
            chargeable_weight_kg=chargeable,
            volumetric_coefficient_kg_per_m3=card.volumetric_coefficient_kg_per_m3,
            category_multiplier=multiplier,
            rate_per_kg_usd=rate,
            base_freight_usd=base,
            min_charge_applied=min_applied,
            freight_usd=freight,
            handling_usd=handling,
            total_usd=freight + handling,
            days_min=card.days_min,
            days_max=card.days_max,
        )

    # ------------------------------------------------------------ domestic
    def domestic_legs_for(self, from_hub: str, city: str) -> tuple[list[DomesticLegRate], bool]:
        """Configured legs for ``city`` (all modes), or a flagged fallback leg."""
        key = normalize_city(city)
        legs = [
            leg for leg in self._legs if leg.from_hub == from_hub and leg.destination_city == key
        ]
        if legs:
            return legs, False
        fallback = self._fallback.get(from_hub)
        if fallback is None:
            return [], False
        leg = fallback.model_copy(
            update={"destination_city": key, "leg_id": f"{fallback.leg_id}-{key.upper()}"}
        )
        return [leg], True

    def quote_domestic(
        self, leg: DomesticLegRate, cargo: CargoSpec, *, is_fallback: bool = False
    ) -> DomesticQuote:
        chargeable = self.chargeable_weight(
            cargo.total_weight_kg, cargo.total_volume_m3, leg.volumetric_coefficient_kg_per_m3
        )
        base = chargeable * leg.rate_per_kg_rub
        min_applied = base < leg.min_charge_rub
        return DomesticQuote(
            leg_id=leg.leg_id,
            from_hub=leg.from_hub,
            destination_city=leg.destination_city,
            transport_mode=leg.transport_mode,
            chargeable_weight_kg=chargeable,
            rate_per_kg_rub=leg.rate_per_kg_rub,
            min_charge_applied=min_applied,
            cost_rub=leg.min_charge_rub if min_applied else base,
            days_min=leg.days_min,
            days_max=leg.days_max,
            is_fallback=is_fallback,
        )
