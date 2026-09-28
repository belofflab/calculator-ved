"""Module 1 — Customs & Tariff Matrix (public façade).

Implementation lives in :mod:`ved_calculator.services.customs_service`; the
reference TN VED table in :mod:`ved_calculator.reference.tariffs`.
"""

from ved_calculator.domain.models import (
    ClearanceResult,
    DutyCalculation,
    DutyRateType,
    Jurisdiction,
    JurisdictionComparison,
    JurisdictionTaxProfile,
    TariffEntry,
    TariffMatrix,
    TariffResolution,
)
from ved_calculator.reference.fees import DEFAULT_TAX_PROFILES, KG_TAX_PROFILE, RU_TAX_PROFILE
from ved_calculator.reference.tariffs import DEFAULT_TARIFF_MATRIX, TARIFF_ENTRIES
from ved_calculator.services.customs_service import CustomsService

__all__ = [
    "DEFAULT_TARIFF_MATRIX",
    "DEFAULT_TAX_PROFILES",
    "KG_TAX_PROFILE",
    "RU_TAX_PROFILE",
    "TARIFF_ENTRIES",
    "ClearanceResult",
    "CustomsService",
    "DutyCalculation",
    "DutyRateType",
    "Jurisdiction",
    "JurisdictionComparison",
    "JurisdictionTaxProfile",
    "TariffEntry",
    "TariffMatrix",
    "TariffResolution",
]
