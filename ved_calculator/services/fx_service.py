"""Module 3 — Currency & Banking FX Engine.

Two conversion modes are exposed on purpose:

* :meth:`FxService.convert_official` – mid rate, no buffer.  Used for every tax
  base (customs duty, VAT), because customs authorities assess at the official
  central-bank rate of the declaration date.
* :meth:`FxService.convert_with_buffer` – mid rate × (1 + δ_fx).  Used for the
  landed-cost view so that the quoted RUB price survives exchange-rate swings
  during transit.  The buffer is applied exactly once per cost component, on
  its native-currency → RUB exposure; it is never compounded across legs.

Bank charges are modelled per transfer corridor (SWIFT USD / CIPS CNY / SWIFT
EUR to the supplier, RUB→KGS local clearing from the Russian buyer) as a
percentage-with-floor/cap transfer fee plus a conversion spread.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

from ved_calculator.domain.models import (
    BankFeeSchedule,
    BankLegCost,
    Currency,
    FxConversion,
    FxRateTable,
    TransferCorridor,
)
from ved_calculator.domain.money import ONE, ZERO, D, DecimalLike, apply_percent, pct, q4
from ved_calculator.reference.fees import DEFAULT_BANK_FEES
from ved_calculator.reference.fx_rates import DEFAULT_FX_TABLE

__all__ = ["FxService"]


class FxService:
    """Multi-currency conversion with risk buffers and bank-fee modelling."""

    def __init__(
        self,
        table: FxRateTable = DEFAULT_FX_TABLE,
        *,
        risk_buffer_percent: DecimalLike = ZERO,
        bank_fees: BankFeeSchedule | None = None,
    ) -> None:
        buffer = D(risk_buffer_percent)
        if buffer < ZERO:
            raise ValueError("risk_buffer_percent must be >= 0")
        self.table = table
        self.risk_buffer_percent = buffer
        self.bank_fees = bank_fees or DEFAULT_BANK_FEES

    # ----------------------------------------------------------------- rates
    @property
    def buffer_multiplier(self) -> Decimal:
        return ONE + pct(self.risk_buffer_percent)

    def with_buffer(self, risk_buffer_percent: DecimalLike) -> FxService:
        return FxService(
            self.table, risk_buffer_percent=risk_buffer_percent, bank_fees=self.bank_fees
        )

    def mid_rate(self, from_currency: Currency, to_currency: Currency) -> Decimal:
        """Units of ``to_currency`` per 1 ``from_currency`` at mid market."""
        return self.table.rate(Currency(from_currency), Currency(to_currency))

    def buffered_rate(self, from_currency: Currency, to_currency: Currency) -> Decimal:
        src, dst = Currency(from_currency), Currency(to_currency)
        rate = self.mid_rate(src, dst)
        return rate if src is dst else rate * self.buffer_multiplier

    # ----------------------------------------------------------- conversions
    def convert_official(
        self, amount: DecimalLike, from_currency: Currency, to_currency: Currency
    ) -> Decimal:
        """Mid-rate conversion (tax bases, customs valuation)."""
        return D(amount) * self.mid_rate(from_currency, to_currency)

    def convert_with_buffer(
        self, amount: DecimalLike, from_currency: Currency, to_currency: Currency
    ) -> FxConversion:
        """Buffered conversion (cost planning).  ``buffer_cost`` is the δ_fx premium."""
        src, dst = Currency(from_currency), Currency(to_currency)
        value = D(amount)
        mid = self.mid_rate(src, dst)
        effective = self.buffered_rate(src, dst)
        at_mid = value * mid
        buffered = value * effective
        return FxConversion(
            amount=value,
            from_currency=src,
            to_currency=dst,
            mid_rate=mid,
            buffer_percent=ZERO if src is dst else self.risk_buffer_percent,
            effective_rate=effective,
            amount_at_mid=at_mid,
            amount_buffered=buffered,
            buffer_cost=buffered - at_mid,
        )

    # --------------------------------------------------------------- banking
    def bank_leg(
        self, corridor: TransferCorridor, amount: DecimalLike, amount_currency: Currency
    ) -> BankLegCost:
        """Transfer fee + conversion spread for moving ``amount`` through ``corridor``.

        The amount is first expressed in the corridor's settlement currency at
        the mid rate (e.g. a TRY invoice settled through SWIFT USD).
        """
        leg = self.bank_fees.leg(TransferCorridor(corridor))
        settlement = leg.transfer.currency
        base = self.convert_official(amount, Currency(amount_currency), settlement)
        transfer_fee = leg.transfer.apply(base)
        spread = apply_percent(base, leg.conversion_spread_percent)
        return BankLegCost(
            corridor=TransferCorridor(corridor),
            currency=settlement,
            amount=base,
            transfer_fee=transfer_fee,
            conversion_spread=spread,
            total=transfer_fee + spread,
        )

    # -------------------------------------------------------------- snapshot
    def snapshot(self, pairs: Iterable[tuple[Currency, Currency]]) -> dict[str, Decimal]:
        """Mid rates for the given pairs, keyed ``"USD/KGS"`` and rounded to 4 dp."""
        out: dict[str, Decimal] = {}
        for src, dst in pairs:
            a, b = Currency(src), Currency(dst)
            if a is b:
                continue
            key = f"{a.value}/{b.value}"
            if key not in out:
                out[key] = q4(self.mid_rate(a, b))
        return out
