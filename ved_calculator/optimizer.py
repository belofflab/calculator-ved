"""Module 4 — Route Optimization Engine (public façade).

Implementation lives in :mod:`ved_calculator.services.optimizer` and
:mod:`ved_calculator.services.landed_cost_service`.
"""

from ved_calculator.domain.models import (
    OptimizationPolicy,
    OptimizationResult,
    RouteComparisonResult,
)
from ved_calculator.engine import VEDCalculatorEngine, calculate
from ved_calculator.services.landed_cost_service import LandedCostService, RouteCandidate
from ved_calculator.services.optimizer import HUB_FOR_CLEARANCE, RouteOptimizer

__all__ = [
    "HUB_FOR_CLEARANCE",
    "LandedCostService",
    "OptimizationPolicy",
    "OptimizationResult",
    "RouteCandidate",
    "RouteComparisonResult",
    "RouteOptimizer",
    "VEDCalculatorEngine",
    "calculate",
]
