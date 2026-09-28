"""Module 3 — Currency & Banking FX Engine (public façade).

Implementation lives in :mod:`ved_calculator.services.fx_service`.
"""

from ved_calculator.domain.models import (
    RECOMMENDED_FX_BUFFER_RANGE,
    BankFeeSchedule,
    BankLegCost,
    BankLegFee,
    Currency,
    FxConversion,
    FxRateTable,
    TransferCorridor,
)
from ved_calculator.reference.fees import DEFAULT_BANK_FEES
from ved_calculator.reference.fx_rates import DEFAULT_FX_TABLE
from ved_calculator.services.fx_service import FxService

__all__ = [
    "DEFAULT_BANK_FEES",
    "DEFAULT_FX_TABLE",
    "RECOMMENDED_FX_BUFFER_RANGE",
    "BankFeeSchedule",
    "BankLegCost",
    "BankLegFee",
    "Currency",
    "FxConversion",
    "FxRateTable",
    "FxService",
    "TransferCorridor",
]
