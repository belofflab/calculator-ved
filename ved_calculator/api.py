"""Optional HTTP layer (``pip install ved-calculator[api]``).

    uvicorn ved_calculator.api:app --port 8080

Endpoints
---------
POST /v1/calculate          → OptimizationResult
POST /v1/customs/compare    → JurisdictionComparison (Module 1)
GET  /v1/reference/tariffs  → bundled TN VED lines
GET  /v1/reference/corridors?origin=CHINA
GET  /health
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from ved_calculator import __version__
from ved_calculator.domain.models import (
    CargoSpec,
    CustomsValuationBasis,
    JurisdictionComparison,
    OptimizationResult,
    OriginCountry,
)
from ved_calculator.engine import VEDCalculatorEngine, default_engine


class CustomsCompareRequest(BaseModel):
    cargo: CargoSpec
    freight_to_border_usd: Decimal = Field(default=Decimal("0"), ge=0)
    valuation_basis: CustomsValuationBasis = CustomsValuationBasis.INVOICE


def create_app(engine: VEDCalculatorEngine | None = None) -> Any:
    """Build the FastAPI application (FastAPI is imported lazily)."""
    try:
        from fastapi import FastAPI, HTTPException
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise RuntimeError(
            "FastAPI is not installed; run `pip install ved-calculator[api]`"
        ) from exc

    core = engine or default_engine()
    app = FastAPI(
        title="VED Calculator Core",
        version=__version__,
        description="Landed-cost, customs and cross-border logistics optimisation (Bishkek → Russia).",
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__, "fx_as_of": core.fx_table.as_of.isoformat()}

    @app.post("/v1/calculate", response_model=OptimizationResult)
    def calculate(request: dict[str, Any]) -> OptimizationResult:
        try:
            return core.calculate(request)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/v1/customs/compare", response_model=JurisdictionComparison)
    def compare(request: CustomsCompareRequest) -> JurisdictionComparison:
        return core.compare_customs(
            request.cargo,
            freight_to_border_usd=request.freight_to_border_usd,
            valuation_basis=request.valuation_basis,
        )

    @app.get("/v1/reference/tariffs")
    def tariffs() -> list[dict[str, Any]]:
        return [entry.model_dump(mode="json") for entry in core.customs.tariffs.entries]

    @app.get("/v1/reference/corridors")
    def corridors(origin: str | None = None) -> list[dict[str, Any]]:
        cards = (
            core.corridors_for(OriginCountry(origin)) if origin else list(core.freight.corridors)
        )
        return [card.model_dump(mode="json") for card in cards]

    return app


def __getattr__(name: str) -> Any:
    # ``uvicorn ved_calculator.api:app`` — build lazily so importing this module never needs FastAPI.
    if name == "app":
        return create_app()
    raise AttributeError(name)
