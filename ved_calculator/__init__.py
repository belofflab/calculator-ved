"""VED Calculator Core — landed-cost and customs route optimisation for imports into Russia via Bishkek.

Public entry points::

    from ved_calculator import calculate, VEDCalculationRequest, VEDCalculatorEngine

Module map (specification §3 ↔ implementation §5):

* ``ved_calculator.customs``    → :mod:`ved_calculator.services.customs_service`
* ``ved_calculator.router``     → :mod:`ved_calculator.services.freight_service`
* ``ved_calculator.fx_engine``  → :mod:`ved_calculator.services.fx_service`
* ``ved_calculator.optimizer``  → :mod:`ved_calculator.services.optimizer`
"""

from ved_calculator.domain.models import (
    CalculationAssumptions,
    CargoCategory,
    CargoSpec,
    ClearanceType,
    CostBreakdown,
    Currency,
    CustomsValuationBasis,
    OptimizationPolicy,
    OptimizationResult,
    OriginCountry,
    RecipientTaxRegime,
    RiskLevel,
    RouteComparisonResult,
    TransportMode,
    VEDCalculationRequest,
)
from ved_calculator.engine import VEDCalculatorEngine, calculate, default_engine

__version__ = "0.1.0"

__all__ = [
    "CalculationAssumptions",
    "CargoCategory",
    "CargoSpec",
    "ClearanceType",
    "CostBreakdown",
    "Currency",
    "CustomsValuationBasis",
    "OptimizationPolicy",
    "OptimizationResult",
    "OriginCountry",
    "RecipientTaxRegime",
    "RiskLevel",
    "RouteComparisonResult",
    "TransportMode",
    "VEDCalculationRequest",
    "VEDCalculatorEngine",
    "__version__",
    "calculate",
    "default_engine",
]
