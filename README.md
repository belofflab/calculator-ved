# VED Calculator Core

Standalone, high-precision calculation engine for **foreign economic activity (ВЭД)**: it prices,
compares and ranks every legal and simplified route for importing goods from China, Turkey, the EU,
USA, UAE or Vietnam into Russia through an intermediary LLC in Bishkek (ОсОО, Kyrgyzstan, EAEU) and
onward to a Russian ИП / ООО.

* Pure Python 3.11+, `Decimal` arithmetic end to end, Pydantic v2 contracts.
* Zero required runtime dependencies beyond `pydantic`; optional FastAPI layer.
* Deterministic: same request + same reference data ⇒ byte-identical result.

```
[Origin seller]  ──invoice USD/CNY/EUR──►  [Bishkek ОсОО, KG]  ──intra-EAEU──►  [Russian ИП/ООО]
                                              │
                          Route A: official EAEU clearance ("белая растаможка")
                                   duty (ЕТТ ЕАЭС) + KG VAT 12 % + fees, then RU import VAT 22 %
                          Route B: cargo / simplified ("карго / упрощёнка")
                                   flat $/kg all-in, no declaration, HIGH/MEDIUM risk
                          Benchmark: direct white import into Russia (payment agent, RU customs)
```

## Quick start

```bash
pip install -e ".[dev]"          # + ".[api]" for the HTTP service
python -m ved_calculator example > request.json
python -m ved_calculator calculate request.json --matrix
```

```
route                                      clearance             total RUB   per unit    days  risk           labels
China-Bishkek-Cargo-Auto-Standard          CARGO_SIMPLIFIED   1,233,333.68   3,083.33   21–34  HIGH_CUSTOMS   CHEAPEST
China-Bishkek-Cargo-Auto-Express           CARGO_SIMPLIFIED   1,255,485.86   3,138.71   15–24  HIGH_CUSTOMS
China-Bishkek-Cargo-Air                    CARGO_SIMPLIFIED   1,335,233.73   3,338.08   10–17  HIGH_CUSTOMS   FASTEST
China-Moscow-Direct-Customs-Rail           OFFICIAL_RU_DIRECT 1,520,492.49   3,801.23   30–45  LOW_LEGAL      CHEAPEST_LEGAL
China-Moscow-Direct-Customs-Auto-Standard  OFFICIAL_RU_DIRECT 1,533,549.80   3,833.87   23–35  LOW_LEGAL      OPTIMAL
China-Bishkek-White-Customs-Auto-Standard  OFFICIAL_EAEU_KG   1,680,607.76   4,201.52   22–33  LOW_LEGAL
China-Bishkek-White-Customs-Auto-Express   OFFICIAL_EAEU_KG   1,722,116.36   4,305.29   16–25  LOW_LEGAL
...
```

The bundled example enables the direct-import benchmark and models a УСН buyer whose Bishkek ОсОО
does **not** recover its 12 % import VAT — the default, deliberately conservative assumptions. Under
them the white Bishkek route carries both VATs (12 % + 22 %) and loses to a direct white import, while
the grey cargo route is cheapest but never recommended. Set
`assumptions.kg_import_vat_recoverable=true` and/or `recipient_tax_regime="OSNO"` to see the Bishkek
scheme at parity (its real edge is payment feasibility, priced here as the 4 % payment-agent fee on the
direct route).

```python
from ved_calculator import calculate

result = calculate({
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
    },
    "target_sale_price_rub_per_unit": "6900",
})
best = result.optimal                      # recommended (legal, best risk-adjusted cost)
print(best.route_name, best.cost_per_unit_rub, best.breakdown["customs_duty"])
print(result.cheapest.route_name, result.fastest.route_name, result.summary)
```

HTTP: `uvicorn ved_calculator.api:app --port 8080` → `POST /v1/calculate`, `POST /v1/customs/compare`,
`GET /v1/reference/tariffs`, `GET /v1/reference/corridors?origin=CHINA`, `GET /health`.

## Architecture

```
ved_calculator/
├── domain/
│   ├── models.py            # all data contracts (inputs, tariffs, rate cards, outputs)
│   └── money.py             # Decimal helpers (q2/q4 rounding, percent maths)
├── reference/               # replaceable reference data
│   ├── tariffs.py           # TN VED matrix (ЕТТ ЕАЭС lines, marking/cert flags, техсбор)
│   ├── corridors.py         # international rate cards + domestic legs (RUB)
│   ├── fees.py              # KG/RU tax profiles, bank fees, service fees
│   ├── fx_rates.py          # FX snapshot (inject a live table in production)
│   └── cities.py            # Russian city aliases (Latin/Cyrillic)
├── services/
│   ├── customs_service.py   # Module 1 – duty / VAT / fees, KG vs RU comparison
│   ├── freight_service.py   # Module 2 – chargeable weight, corridor & domestic quotes
│   ├── fx_service.py        # Module 3 – conversions, δ_fx buffer, bank legs
│   ├── landed_cost_service.py  # per-route cost assembly (Routes A, B, benchmark)
│   └── optimizer.py         # Module 4 – enumeration, ranking, recommendation
├── engine.py                # composition root (VEDCalculatorEngine / calculate)
├── customs.py router.py fx_engine.py optimizer.py   # §3 module façades
├── __main__.py              # CLI
└── api.py                   # optional FastAPI app
```

## Mathematical model

**Chargeable weight and freight (2.A)**

```
W_chargeable = max(W_actual_kg, V_m3 × k_volumetric)          k: 167 air · 200 cargo · 250 truck · 300 rail
Cost_leg     = max(W_chargeable × rate × category_multiplier, min_charge) + handling_fixed + handling_per_kg × W
```

**Official EAEU clearance in Bishkek (2.B)** — `CustomsService.calculate_clearance(KG, …)`

```
CustomsValue = Invoice_kgs                                     (INVOICE basis, default = spec formula)
             = Invoice_kgs + Freight_to_border_kgs             (CIF basis, EAEU Customs Code art. 40)
Duty         = ad valorem % × CustomsValue                      AD_VALOREM
             = rate_EUR × (kg | pairs | pieces) × EUR/KGS       SPECIFIC
             = max(ad valorem, specific)                        COMBINED "x %, но не менее y евро за …"
VAT_kg       = (CustomsValue + Duty [+ Freight if INVOICE basis]) × 12 %
Fees         = 0.4 % × CustomsValue (min 500 / max 250 000 KGS) + broker 20 000 KGS
Cleared      = Invoice + Duty + VAT_kg + Fees
```

**Intra-EAEU transfer (2.C)** — `LandedCostService._white_kg`

```
ОсОО outlays   = goods + supplier bank leg (SWIFT/CIPS + spread) + freight + handling + insurance
                 + duty + processing fee + broker + KG VAT (unless recoverable)
Transfer price = outlays × (1 + agent markup 1–3 %)
RU import VAT  = Transfer price × 22 %          (sunk cost for УСН, recoverable for ОСНО)
Buyer bank leg = RUB→KGS clearing 0.5 % (1 500–30 000 RUB) + 1 % spread
```

**Total landed cost (2.D)**

```
Total_rub = Σ components (all at mid rate) + fx_risk_buffer + certification + marking + техсбор + local transport
Per unit  = Total_rub / quantity_units
```

The δ_fx risk buffer (default 2.5 %, recommended 1.5–3.0 %) is applied **once per foreign-currency
component** on its native-currency → RUB exposure and reported as its own line; tax bases always use
the official mid rate, exactly as customs assesses them. `sum(breakdown.values()) == total_cost_rub`
holds for every route.

**Ranking (Module 4)**

| Output | Rule |
|---|---|
| `cheapest` | minimal `total_cost_rub` (any risk) |
| `cheapest_legal` | minimal cost among `LOW_LEGAL` routes |
| `fastest` | minimal `estimated_days_max` |
| `optimal` (recommended) | minimal *risk-adjusted cost* = `total × (1 + delay_cost/day × days_max + expected_loss[risk])`, restricted to legal routes when any exist (`OptimizationPolicy`) |

Defaults: delay cost 0.10 %/day; expected loss LOW 1 %, MEDIUM 12 %, HIGH 35 %. A grey cargo route can
therefore be reported as CHEAPEST but is never recommended unless `prefer_legal_routes=False`.

## Request / response contracts

`VEDCalculationRequest` (see `domain/models.py`):

| Field | Default | Notes |
|---|---|---|
| `origin_country` | — | CHINA · TURKEY · EU · USA · UAE · VIETNAM (case-insensitive) |
| `destination_city_ru` | `Tyumen` | Latin or Cyrillic; unknown cities use a flagged fallback rate |
| `cargo` | — | category, optional `hs_code`, weight, volume, declared value + currency, units |
| `target_delivery_days_max` | `None` | hard constraint; violating routes go to `excluded_routes` |
| `allow_white_customs` / `allow_cargo_simplified` | `True` | route families |
| `include_direct_ru_benchmark` | `False` | adds direct white import into Russia |
| `fx_risk_buffer_percent` | `2.5` | δ_fx |
| `target_sale_price_rub_per_unit` | `None` | enables `gross_margin_percent` per route |
| `assumptions.recipient_tax_regime` | `USN` | `OSNO` makes import VAT recoverable (cash-flow only) |
| `assumptions.kg_import_vat_recoverable` | `False` | ОсОО recovers 12 % via 0 % export |
| `assumptions.customs_valuation_basis` | `INVOICE` | or `CIF` |
| `assumptions.agent_markup_percent` | `2.0` | ОсОО markup |
| `assumptions.has_valid_certificates` / `apply_marking` | `False` / `True` | ТР ТС declarations, Честный ЗНАК |
| `assumptions.payment_agent_fee_percent` | `4.0` | direct-RU benchmark only |
| `assumptions.calculation_date` | today | техсбор effective 01.12.2026 |

`RouteComparisonResult`: `route_id`, `route_name`, `clearance_type`, `total_cost_rub`,
`cost_per_unit_rub`, `cost_per_kg_rub`, `estimated_days_min/max`, `breakdown` (17 RUB components),
`recoverable_vat_rub`, `is_recommended`, `labels`, `risk_level` (`LOW_LEGAL` / `MEDIUM_TRANSIT` /
`HIGH_CUSTOMS`), `risk_score`, `risk_adjusted_cost_rub`, `chargeable_weight_kg`, `fx_rates_used`,
`gross_margin_percent`, `meets_deadline`, `constraint_violations`, `notes`.

`OptimizationResult`: `routes` (feasible, sorted by cost), `excluded_routes`, `cheapest_route_id`,
`cheapest_legal_route_id`, `fastest_route_id`, `optimal_route_id`, `warnings`, `summary`, `fx_as_of`,
plus `.cheapest / .cheapest_legal / .fastest / .optimal` accessors and `comparison_matrix()`.

## Reference data and sources

All reference data is plain Python and can be replaced through `VEDCalculatorEngine(...)` keyword
arguments (`fx_table`, `tariffs`, `corridors`, `domestic_legs`, `tax_profiles`, `bank_fees`,
`service_fees`, `policy`).

| Item | Default | Basis |
|---|---|---|
| RU VAT | 22 % | Федеральный закон №425-ФЗ от 28.11.2025 (в силе с 01.01.2026) |
| KG VAT | 12 % | Налоговый кодекс КР |
| KG customs processing fee | 0.4 %, min 500 / max 250 000 KGS | ПКМ КР №349 от 03.07.2024 |
| RU customs processing fee | 1 231 … 73 860 RUB by customs value | ПП РФ №1638 от 23.10.2025 |
| Sneakers 6404 11 000 0 | 0.47 EUR/pair | ЕТТ ЕАЭС |
| Men's leather shoes 6403 99 960 0 | 1.25 EUR/pair | ЕТТ ЕАЭС |
| Cotton trousers/jeans 6203 42 / 6204 62 | 10 %, min 1.88 EUR/kg | ЕТТ ЕАЭС |
| T-shirts, sweaters, shirts 6109/6110/6205 | 1.75 EUR/kg | ЕТТ ЕАЭС |
| Coats/jackets 6201/6202 | 10 %, min 2.25 EUR/kg | ЕТТ ЕАЭС |
| Smartphones / laptops / Li-ion / smart watches | 0 % (+ техсбор 373 / 746 RUB from 01.12.2026) | ЕТТ ЕАЭС, ITA |
| Headphones 8518 30 950 0 · plastic tableware 3924 10 · toys 9503 00 700 0 | 5 % · 6.5 % · 10 % | ЕТТ ЕАЭС |
| TVs 8528 72 | 10 %, min 25.5 EUR/pc | ЕТТ ЕАЭС |
| Freight rate cards | China→Bishkek cargo $2.9–5.2/kg, white $1.05–4.30/kg; Turkey/EU/USA/UAE/Vietnam analogues; Bishkek→RU 30–52 RUB/kg | 2025–2026 forwarder benchmarks |

Entries marked `verified=False` in `reference/tariffs.py` are indicative and produce a note in every
calculation that uses them. **All figures are reference defaults for planning; confirm the 10-digit
ТН ВЭД line, current rates and forwarder quotes with a licensed broker before declaring.**

## Word report (выгрузка расчётов в Word)

`reports/VED_calculations.docx` is a full Russian-language export of every calculation for the bundled
sample request: inputs, reference rates, formulas, the route matrix with all cost components,
step-by-step derivations per clearance scheme, the KG-vs-RU customs comparison, a sensitivity
analysis and six additional shipments. Regenerate it for any request in two steps:

```bash
python scripts/export_report_data.py examples/sample_request.json reports/report_data.json
npm install docx@9            # once; docx-js renders the .docx
node scripts/build_docx_report.js reports/report_data.json reports/VED_calculations.docx
```

## Business case: shoe store in Tyumen

`reports/Tyumen_shoe_store_business_case.docx` is a Russian-language business case built on the engine:
market sizing, real rental listings with a recommended cheap option, CAPEX/OPEX, unit economics with the
engine's landed cost, three 24-month scenarios with monthly P&L and cash flow, break-even, sensitivity,
marketing plan, legal steps, launch timeline and risks. Regenerate with:

```bash
python scripts/business_case_tyumen.py reports/business_case_data.json
node scripts/build_business_case_docx.js reports/business_case_data.json reports/Tyumen_shoe_store_business_case.docx
```

## Testing

```bash
pytest            # 100+ tests incl. hand-verified 500 kg sneakers China→Bishkek→Tyumen shipment
ruff check . && ruff format --check .
mypy ved_calculator
```

`tests/test_ved_calculator.py` recomputes the specification formulas by hand (round FX table:
1 USD = 90 KGS = 90 RUB, 1 EUR = 100 KGS) and asserts every breakdown component of the sample
shipment to the kopeck.
