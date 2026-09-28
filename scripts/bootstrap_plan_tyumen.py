#!/usr/bin/env python3
"""Zero-capital bootstrap roadmap: online pre-orders → own stock → offline store in Tyumen.

Simulates monthly cash, inventory and net worth for a seller starting with 0 ₽ who
(1) takes prepaid Poizon orders as a buying agent (income = agent fee),
(2) adds prepaid orders from Russian wholesalers with marking (Yekaterinburg, 2–4 days),
(3) reinvests into an own China → Bishkek → Tyumen batch once cash allows,
and reports when the milestones from the business case are reached.

    python scripts/bootstrap_plan_tyumen.py
"""

from __future__ import annotations

from decimal import Decimal

D = Decimal
ONE = D(1)

# ------------------------------------------------------------------ unit economics
POIZON_PRICE, POIZON_FEE = D(12500), D(1800)  # customer pays goods+delivery; our income = fee
WHOLESALE_PRICE, WHOLESALE_COST = (
    D(4490),
    D(2990),
)  # Yekaterinburg wholesaler incl. delivery, with marking codes
OWN_PRICE, OWN_COST_FIRST, OWN_COST = (
    D(4690),
    D("2493.96"),
    D("2457.96"),
)  # from the business case (VED engine)
IP_CONTRIB_YEAR = D(57390)  # fixed ИП contributions 2026, paid by year end
USN = D("0.06")
FIRST_BATCH_PAIRS, FIRST_BATCH_CASH = 200, D(200) * OWN_COST_FIRST  # ≈ 499 k ₽
OFFLINE_CAPEX_EX_STOCK = D(940000)  # business-case CAPEX minus the first 500-pair batch
OFFLINE_RESERVE = D(300000)  # 2 months of fixed OPEX
OFFLINE_STOCK_PAIRS = 500

# monthly volumes: (poizon pairs, wholesale pairs, own-stock pairs if stock exists)
PLAN = [
    (8, 0, 0),
    (15, 0, 0),
    (22, 10, 0),
    (28, 18, 0),
    (34, 26, 0),
    (40, 34, 0),
    (45, 40, 0),
    (50, 45, 0),
    (50, 35, 60),
    (50, 25, 90),
    (50, 20, 110),
    (50, 20, 120),
    (55, 20, 125),
    (55, 20, 130),
    (55, 20, 135),
    (55, 20, 140),
    (55, 20, 140),
    (55, 20, 145),
    (60, 20, 150),
    (60, 20, 150),
    (60, 20, 155),
    (60, 20, 160),
    (60, 20, 160),
    (60, 20, 165),
]
MARKETING = [0, 3000, 5000, 7000, 8000, 10000, 12000, 15000, 18000, 20000, 20000, 20000] + [
    25000
] * 12
TOOLS = [0, 0, 2000, 2000, 2500, 2500, 3000, 3000, 3500, 3500, 3500, 3500] + [
    4000
] * 12  # Avito paid listings, CRM, ЭДО


def run(scale: Decimal = ONE, *, verbose: bool = True) -> dict[str, int]:
    """Simulate 24 months; ``scale`` multiplies wholesale and own-stock volumes (Poizon fees unchanged)."""
    cash, stock_pairs, stock_cost = D(0), 0, D(0)
    contrib_paid = D(0)
    milestones: dict[str, int] = {}
    if verbose:
        print(
            f"{'мес':>3} {'Poizon':>6} {'опт':>4} {'свой':>5} {'выручка':>9} {'маржа':>8} {'налог':>7} {'расходы':>8} {'закупка':>9} {'кэш':>10} {'запас,пар':>9} {'активы':>10}"
        )
    plan = [(pz, int(ws * scale), int(own * scale)) for pz, ws, own in PLAN]
    for i, (pz, ws, own) in enumerate(plan, start=1):
        own_sold = min(own, stock_pairs)
        revenue_taxable = (
            pz * POIZON_FEE + ws * WHOLESALE_PRICE + own_sold * OWN_PRICE
        )  # agent fee + resale revenue
        gross = (
            pz * POIZON_FEE
            + ws * (WHOLESALE_PRICE - WHOLESALE_COST)
            + own_sold * (OWN_PRICE - (stock_cost / stock_pairs if stock_pairs else OWN_COST))
        )
        cogs_own = own_sold * (stock_cost / stock_pairs) if stock_pairs else D(0)
        stock_pairs -= own_sold
        stock_cost -= cogs_own
        tax = revenue_taxable * USN
        contrib_due = IP_CONTRIB_YEAR / 12
        contrib_paid += contrib_due
        tax = max(
            tax - contrib_due, D(0)
        )  # УСН 6 % is reduced by contributions (no employees → up to 100 %)
        expenses = D(MARKETING[i - 1] + TOOLS[i - 1]) + contrib_due + tax
        purchases = D(0)
        # cash: agent fees + wholesale margin (customer prepays, supplier paid the same month) + full price of own-stock sales
        cash += (
            pz * POIZON_FEE
            + ws * (WHOLESALE_PRICE - WHOLESALE_COST)
            + own_sold * OWN_PRICE
            - expenses
        )
        # reinvest: first own batch when cash covers it plus a 60 k cushion; then keep ~2 months of own sales in stock,
        # buying as many pairs as cash allows (min lot 50 pairs) — partial restocks keep the shelf from running empty
        cushion = D(60000)
        if "первая своя партия 200 пар" not in milestones:
            if cash >= FIRST_BATCH_CASH + cushion:
                purchases = FIRST_BATCH_CASH
                stock_pairs += FIRST_BATCH_PAIRS
                stock_cost += purchases
                milestones["первая своя партия 200 пар"] = i
        elif i < len(plan):
            next_own = plan[i][2]
            target = 2 * next_own
            need = target - stock_pairs
            affordable = int((cash - cushion) // OWN_COST)
            lot = min(need, affordable)
            if lot >= 50:
                purchases = lot * OWN_COST
                stock_pairs += lot
                stock_cost += purchases
        cash -= purchases
        assets = cash + stock_cost
        if cash >= 100000:
            milestones.setdefault("100 000 ₽ на счёте", i)
        top_up = max(OFFLINE_STOCK_PAIRS - stock_pairs, 0) * OWN_COST
        if cash >= OFFLINE_CAPEX_EX_STOCK + OFFLINE_RESERVE + top_up:
            milestones.setdefault(
                "готовность к оффлайн-точке (CAPEX 0,94 млн + резерв 0,3 млн + добор склада до 500 пар)",
                i,
            )
        if assets >= D(2900000):
            milestones.setdefault("активы 2,9 млн ₽ (полный бюджет бизнес-кейса)", i)
        if verbose:
            print(
                f"{i:>3} {pz:>6} {ws:>4} {own_sold:>5} {revenue_taxable:>9.0f} {gross:>8.0f} {tax:>7.0f} {expenses:>8.0f} {purchases:>9.0f} {cash:>10.0f} {stock_pairs:>9} {assets:>10.0f}"
            )
    if verbose:
        print("\nMilestones:")
        for k, v in milestones.items():
            print(f"  месяц {v:>2}: {k}")
    return milestones


if __name__ == "__main__":
    print("=== Базовый план ===")
    run()
    print("\n=== Осторожный план: объёмы опта и своего товара −35 % ===")
    for k, v in run(D("0.65"), verbose=False).items():
        print(f"  месяц {v:>2}: {k}")
