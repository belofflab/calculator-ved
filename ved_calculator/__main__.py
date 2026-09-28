"""Command-line interface.

python -m ved_calculator calculate request.json          # full JSON result
python -m ved_calculator calculate request.json --matrix # tabular comparison
cat request.json | python -m ved_calculator calculate -  # from stdin
python -m ved_calculator example                          # sample request
python -m ved_calculator tariffs                          # bundled TN VED lines
python -m ved_calculator corridors CHINA                  # rate cards per origin
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import Any

from ved_calculator.domain.models import OptimizationResult, OriginCountry
from ved_calculator.engine import default_engine

EXAMPLE_REQUEST: dict[str, Any] = {
    "origin_country": "CHINA",
    "destination_city_ru": "Tyumen",
    "cargo": {
        "category": "footwear",
        "hs_code": "6404 11 000 0",
        "total_weight_kg": "500",
        "total_volume_m3": "2.5",
        "declared_value_origin": "12000",
        "origin_currency": "USD",
        "quantity_units": 400,
        "description": "Sneakers, 400 pairs, 40 cartons",
    },
    "target_delivery_days_max": None,
    "allow_cargo_simplified": True,
    "allow_white_customs": True,
    "include_direct_ru_benchmark": True,
    "fx_risk_buffer_percent": "2.5",
    "target_sale_price_rub_per_unit": "6900",
    "assumptions": {
        "recipient_tax_regime": "USN",
        "kg_import_vat_recoverable": False,
        "customs_valuation_basis": "INVOICE",
        "agent_markup_percent": "2.0",
    },
}


def _load_request(path: str) -> dict[str, Any]:
    raw = sys.stdin.read() if path == "-" else open(path, encoding="utf-8").read()
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise SystemExit("request JSON must be an object")
    return data


def _print_matrix(result: OptimizationResult) -> None:
    rows = result.comparison_matrix()
    header = f"{'route':<52} {'clearance':<18} {'total RUB':>15} {'per unit':>11} {'days':>7} {'risk':<15} labels"
    print(header)
    print("-" * len(header))
    for row in rows:
        flag = "" if row["feasible"] else " [excluded]"
        print(
            f"{row['route_name']:<52} {row['clearance_type']:<18} "
            f"{row['total_cost_rub']:>15,.2f} {row['cost_per_unit_rub']:>11,.2f} "
            f"{row['days']:>7} {row['risk_level']:<15} {','.join(row['labels'])}{flag}"
        )
    print()
    print(result.summary)
    for warning in result.warnings:
        print(f"! {warning}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ved-calculator",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    calc = sub.add_parser("calculate", help="evaluate and rank routes for a request JSON")
    calc.add_argument("request", help="path to request JSON, or '-' for stdin")
    calc.add_argument(
        "--matrix", action="store_true", help="print a comparison table instead of JSON"
    )
    calc.add_argument("--compact", action="store_true", help="single-line JSON")

    sub.add_parser("example", help="print a sample request JSON")
    sub.add_parser("tariffs", help="list bundled TN VED tariff lines")
    cor = sub.add_parser("corridors", help="list bundled freight corridors")
    cor.add_argument("origin", nargs="?", help="origin country filter, e.g. CHINA")

    args = parser.parse_args(argv)
    engine = default_engine()

    if args.command == "example":
        print(json.dumps(EXAMPLE_REQUEST, ensure_ascii=False, indent=2))
        return 0
    if args.command == "tariffs":
        for entry in engine.customs.tariffs.entries:
            flag = "✓" if entry.verified else "~"
            print(
                f"{flag} {entry.hs_code or '(default)':<12} {entry.category.value:<12} "
                f"{entry.rate_description():<45} {entry.description_en}"
            )
        return 0
    if args.command == "corridors":
        cards = (
            engine.corridors_for(OriginCountry(args.origin))
            if args.origin
            else list(engine.freight.corridors)
        )
        for card in cards:
            print(
                f"{card.corridor_id:<32} {card.service_kind.value:<14} {card.transport_mode.value:<14} "
                f"${card.rate_per_kg_usd}/kg min ${card.min_charge_usd} "
                f"{card.days_min}-{card.days_max}d → {card.destination_hub}"
            )
        return 0

    result = engine.calculate(_load_request(args.request))
    if args.matrix:
        _print_matrix(result)
    else:
        print(result.model_dump_json(indent=None if args.compact else 2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
