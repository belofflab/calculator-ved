"""Module 3 — FX engine unit tests."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from ved_calculator.domain.models import Currency, FxRateTable, TransferCorridor
from ved_calculator.services.fx_service import FxService

D = Decimal


class TestFxRateTable:
    def test_cross_rate_via_usd_pivot(self, round_fx: FxRateTable) -> None:
        assert round_fx.rate(Currency.CNY, Currency.KGS) == D("12.5")
        assert round_fx.rate(Currency.EUR, Currency.KGS) == D("100")
        assert round_fx.rate(Currency.KGS, Currency.RUB) == D("1")
        assert round_fx.rate(Currency.USD, Currency.RUB) == D("90")

    def test_same_currency_is_identity(self, round_fx: FxRateTable) -> None:
        assert round_fx.rate(Currency.RUB, Currency.RUB) == D("1")

    def test_direct_pair_overrides_cross_rate_in_both_directions(self) -> None:
        table = FxRateTable(
            as_of=date(2026, 1, 1),
            per_usd={Currency.USD: 1, Currency.KGS: 90, Currency.RUB: 90},
            direct_pairs={"KGS/RUB": "0.95"},
        )
        assert table.rate(Currency.KGS, Currency.RUB) == D("0.95")
        assert table.rate(Currency.RUB, Currency.KGS) == D("1") / D("0.95")
        assert table.rate(Currency.USD, Currency.RUB) == D("90")  # untouched cross rate

    def test_unknown_currency_raises(self) -> None:
        table = FxRateTable(as_of=date(2026, 1, 1), per_usd={Currency.USD: 1, Currency.KGS: 90})
        with pytest.raises(ValueError, match="no rate for TRY"):
            table.rate(Currency.TRY, Currency.KGS)

    def test_table_requires_usd_equal_one(self) -> None:
        with pytest.raises(ValidationError):
            FxRateTable(as_of=date(2026, 1, 1), per_usd={Currency.USD: 2, Currency.KGS: 90})

    def test_bad_direct_pair_key_rejected(self) -> None:
        with pytest.raises(ValidationError):
            FxRateTable(
                as_of=date(2026, 1, 1),
                per_usd={Currency.USD: 1},
                direct_pairs={"USDKGS": "90"},
            )


class TestFxService:
    def test_official_conversion_has_no_buffer(self, fx: FxService) -> None:
        assert fx.convert_official(100, Currency.USD, Currency.RUB) == D("9000")
        assert fx.convert_official("7.2", Currency.CNY, Currency.USD) == D("1")

    def test_buffered_conversion_adds_delta_once(self, fx: FxService) -> None:
        conv = fx.convert_with_buffer(100, Currency.USD, Currency.RUB)
        assert conv.mid_rate == D("90")
        assert conv.effective_rate == D("92.25")
        assert conv.amount_at_mid == D("9000")
        assert conv.amount_buffered == D("9225.00")
        assert conv.buffer_cost == D("225.00")
        assert conv.buffer_percent == D("2.5")

    def test_same_currency_conversion_is_not_buffered(self, fx: FxService) -> None:
        conv = fx.convert_with_buffer(100, Currency.RUB, Currency.RUB)
        assert conv.amount_buffered == D("100")
        assert conv.buffer_cost == D("0")
        assert conv.buffer_percent == D("0")

    def test_zero_buffer_equals_mid(self, round_fx: FxRateTable) -> None:
        service = FxService(round_fx)
        conv = service.convert_with_buffer(50, Currency.EUR, Currency.KGS)
        assert conv.amount_buffered == conv.amount_at_mid == D("5000")

    def test_negative_buffer_rejected(self, round_fx: FxRateTable) -> None:
        with pytest.raises(ValueError):
            FxService(round_fx, risk_buffer_percent="-1")

    def test_with_buffer_returns_new_service(self, fx: FxService) -> None:
        other = fx.with_buffer("3")
        assert other.risk_buffer_percent == D("3")
        assert fx.risk_buffer_percent == D("2.5")

    def test_snapshot_keys_and_rounding(self, fx: FxService) -> None:
        snap = fx.snapshot(
            [
                (Currency.USD, Currency.KGS),
                (Currency.KGS, Currency.KGS),
                (Currency.CNY, Currency.KGS),
            ]
        )
        assert snap == {"USD/KGS": D("90.0000"), "CNY/KGS": D("12.5000")}


class TestBankFees:
    def test_swift_usd_minimum_fee_and_spread(self, fx: FxService) -> None:
        leg = fx.bank_leg(TransferCorridor.SWIFT_USD, 12000, Currency.USD)
        assert leg.currency is Currency.USD
        assert leg.transfer_fee == D("30")  # 0.2 % = 24 → floor 30
        assert leg.conversion_spread == D("72.000")  # 0.6 %
        assert leg.total == D("102.000")

    def test_swift_usd_maximum_fee(self, fx: FxService) -> None:
        leg = fx.bank_leg(TransferCorridor.SWIFT_USD, 500000, Currency.USD)
        assert leg.transfer_fee == D("250")  # 0.2 % = 1 000 → cap 250

    def test_cips_cny_minimum(self, fx: FxService) -> None:
        leg = fx.bank_leg(TransferCorridor.CIPS_CNY, 100000, Currency.CNY)
        assert leg.transfer_fee == D("200")  # 0.15 % = 150 → floor 200
        assert leg.conversion_spread == D("800.000")

    def test_amount_converted_into_settlement_currency(self, fx: FxService) -> None:
        # 40 000 TRY = 1 000 USD at the round table → settled via SWIFT USD
        leg = fx.bank_leg(TransferCorridor.SWIFT_USD, 40000, Currency.TRY)
        assert leg.amount == D("1000")
        assert leg.transfer_fee == D("30")
        assert leg.conversion_spread == D("6.000")

    def test_rub_kgs_local_clearing(self, fx: FxService) -> None:
        leg = fx.bank_leg(TransferCorridor.RUB_KGS_LOCAL, 1000000, Currency.RUB)
        assert leg.transfer_fee == D("5000.000")
        assert leg.conversion_spread == D("10000.000")

    @pytest.mark.parametrize(
        ("currency", "corridor"),
        [
            (Currency.USD, TransferCorridor.SWIFT_USD),
            (Currency.CNY, TransferCorridor.CIPS_CNY),
            (Currency.EUR, TransferCorridor.SWIFT_EUR),
            (Currency.TRY, TransferCorridor.SWIFT_USD),
            (Currency.AED, TransferCorridor.SWIFT_USD),
        ],
    )
    def test_supplier_corridor_by_currency(
        self, currency: Currency, corridor: TransferCorridor
    ) -> None:
        assert TransferCorridor.for_supplier_currency(currency) is corridor
