#!/usr/bin/env python3
"""Collect every calculation of the VED Calculator Core into one JSON file.

The JSON feeds ``scripts/build_docx_report.js`` which renders the Word report.

    python scripts/export_report_data.py examples/sample_request.json reports/report_data.json
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1])
)  # run from a checkout without installing

from ved_calculator import VEDCalculationRequest, VEDCalculatorEngine, __version__
from ved_calculator.domain.models import (
    CargoCategory,
    ClearanceType,
    CorridorRateCard,
    Currency,
    CustomsValuationBasis,
    DomesticLegRate,
    DutyRateType,
    Jurisdiction,
    RecipientTaxRegime,
    RouteComparisonResult,
    TransferCorridor,
)
from ved_calculator.domain.money import ZERO, apply_percent, fmt, q2, q4
from ved_calculator.reference.corridors import BISHKEK, MOSCOW
from ved_calculator.services.fx_service import FxService
from ved_calculator.services.optimizer import HUB_FOR_CLEARANCE

engine = VEDCalculatorEngine()

CATEGORY_RU = {
    CargoCategory.FOOTWEAR: "Обувь",
    CargoCategory.APPAREL: "Одежда / текстиль",
    CargoCategory.ELECTRONICS: "Электроника и гаджеты",
    CargoCategory.GENERAL: "Товары для дома / прочее",
}
CLEARANCE_RU = {
    ClearanceType.OFFICIAL_EAEU_KG: "Белая растаможка в КР (ЕАЭС)",
    ClearanceType.CARGO_SIMPLIFIED: "Карго / упрощёнка",
    ClearanceType.OFFICIAL_RU_DIRECT: "Прямой импорт в РФ (бенчмарк)",
}
RISK_RU = {
    "LOW_LEGAL": "Низкий (легально)",
    "MEDIUM_TRANSIT": "Средний (транзит)",
    "HIGH_CUSTOMS": "Высокий (таможня)",
}
COMPONENT_RU = {
    "goods_value": "Стоимость товара",
    "international_freight": "Международный фрахт",
    "hub_handling": "Обработка на хабе",
    "insurance": "Страхование",
    "customs_duty": "Таможенная пошлина",
    "customs_processing_fee": "Таможенный сбор",
    "broker_fee": "Услуги брокера / декларанта",
    "certification_fee": "Сертификация (ТР ТС)",
    "marking_fee": "Маркировка «Честный ЗНАК»",
    "technology_fee": "Технологический сбор",
    "import_vat_kg": "НДС при ввозе в КР (12%)",
    "import_vat_ru": "НДС при ввозе в РФ (22%)",
    "bank_fees": "Банковские комиссии и спреды",
    "fx_risk_buffer": "Валютный буфер (δ_fx)",
    "agent_markup": "Наценка агента (ОсОО)",
    "payment_agent_fee": "Платёжный агент (прямой импорт)",
    "local_transport": "Доставка по РФ (хаб → город)",
}
LABEL_RU = {
    "CHEAPEST": "Самый дешёвый",
    "CHEAPEST_LEGAL": "Самый дешёвый легальный",
    "FASTEST": "Самый быстрый",
    "OPTIMAL": "Оптимальный (рекомендован)",
}
MODE_RU = {
    "AUTO_EXPRESS": "Авто-экспресс",
    "AUTO_STANDARD": "Авто-стандарт",
    "RAIL": "Ж/д",
    "AIR": "Авиа",
    "SEA_MULTIMODAL": "Море + авто",
    "TRUCK": "Авто",
}
ORIGIN_RU = {
    "CHINA": "Китай",
    "TURKEY": "Турция",
    "EU": "ЕС",
    "USA": "США",
    "UAE": "ОАЭ",
    "VIETNAM": "Вьетнам",
}


_NOTE_RULES: list[tuple[re.Pattern[str], Any]] = [
    (
        re.compile(
            r"^KG import VAT \((\d+)%\) treated as a sunk cost of the ОсОО \(specification formula B\)\.$"
        ),
        r"НДС при ввозе в КР (\1%) учтён как невозмещаемые затраты ОсОО (формула B спецификации).",
    ),
    (
        re.compile(
            r"^KG import VAT \((\d+)%\) treated as recoverable via the 0% EAEU export — cash-flow only\.$"
        ),
        r"НДС при ввозе в КР (\1%) считается возмещаемым через экспорт в ЕАЭС по ставке 0% — влияет только на денежный поток.",
    ),
    (
        re.compile(
            r"^RU import VAT \(([\d.]+)%\) on the EAEU transfer price is a sunk cost \(УСН\)\.$"
        ),
        r"НДС при ввозе в РФ (\1%) с цены поставки внутри ЕАЭС — невозмещаемые затраты (УСН).",
    ),
    (
        re.compile(
            r"^RU import VAT \(([\d.]+)%\) on the EAEU transfer is deductible \(ОСНО\) — cash-flow only\.$"
        ),
        r"НДС при ввозе в РФ (\1%) с поставки внутри ЕАЭС принимается к вычету (ОСНО) — влияет только на денежный поток.",
    ),
    (
        re.compile(r"^RU import VAT \(([\d.]+)%\) at the border is a sunk cost \(УСН\)\.$"),
        r"НДС при ввозе в РФ (\1%) на таможне — невозмещаемые затраты (УСН).",
    ),
    (
        re.compile(
            r"^RU import VAT \(([\d.]+)%\) at the border is deductible \(ОСНО\) — cash-flow only\.$"
        ),
        r"НДС при ввозе в РФ (\1%) на таможне принимается к вычету (ОСНО) — влияет только на денежный поток.",
    ),
    (re.compile(r"^Conformity assessment: (.+)\.$"), r"Подтверждение соответствия: \1."),
    (
        re.compile(r"^Customs value = invoice \(freight to border added to the VAT base only\)$"),
        "Таможенная стоимость = инвойс (фрахт до границы включён только в базу НДС)",
    ),
    (
        re.compile(r"^Customs value = invoice \+ freight to border \(EAEU CC art\. 40\)$"),
        "Таможенная стоимость = инвойс + фрахт до границы (ст. 40 ТК ЕАЭС)",
    ),
    (
        re.compile(
            r"^Честный ЗНАК marking is mandatory for this tariff line before sale in Russia$"
        ),
        "Маркировка «Честный ЗНАК» обязательна для этой товарной позиции до продажи в России",
    ),
    (
        re.compile(r"^Cargo rate is all-in .*$"),
        "Ставка карго — «всё включено» ($/кг с упрощённым оформлением): нет таможенной декларации, счёта-фактуры и вычета ввозного НДС в России.",
    ),
    (
        re.compile(r"^Goods arrive without Честный ЗНАК codes.*$"),
        "Товар прибывает без кодов «Честный ЗНАК» — легальная продажа на маркетплейсах и в рознице невозможна.",
    ),
    (
        re.compile(r"^High-value electronics without documents.*$"),
        "Дорогостоящая электроника без документов несёт повышенный риск изъятия на границе Казахстан / Россия.",
    ),
    (
        re.compile(r"^Supplier paid from Russia through a payment agent \(([\d.]+)%\)\.$"),
        r"Оплата поставщику из России через платёжного агента (\1%).",
    ),
    (
        re.compile(r"^Технологический сбор (.+) ₽/unit applies from (.+)\.$"),
        r"Технологический сбор \1 ₽/ед. применяется с \2.",
    ),
    (
        re.compile(r"^Negative gross margin at the target sale price.*$"),
        "Отрицательная валовая маржа при целевой цене продажи — маршрут не защищает маржу.",
    ),
    (
        re.compile(r"^No configured domestic leg for '(.+)'; fallback rate from (.+) applied\.$"),
        r"Для города «\1» нет настроенного тарифа доставки; применён резервный тариф от хаба \2.",
    ),
    (
        re.compile(
            r"^Tariff rate for (.+) is a reference estimate; verify against current ЕТТ ЕАЭС\.$"
        ),
        r"Ставка для \1 — справочная оценка; сверьте с действующим ЕТТ ЕАЭС.",
    ),
    (
        re.compile(
            r"^hs_code (\S+) belongs to category '(.+)', request says '(.+)'; the HS code takes precedence for duty\.$"
        ),
        r"Код \1 относится к категории «\2», в запросе указана «\3»; для пошлины приоритет у кода ТН ВЭД.",
    ),
    (
        re.compile(r"^No tariff line for hs_code (\S+); using the (.+) default\.$"),
        r"Для кода \1 нет тарифной линии; применён тариф категории «\2» по умолчанию.",
    ),
    (
        re.compile(
            r"^hs_code (\S+) matches (\d+) tariff lines with different rates; using (\S+) \((.+)\)\.$"
        ),
        r"Код \1 соответствует \2 тарифным линиям с разными ставками; применена линия \3 (\4).",
    ),
    (
        re.compile(
            r"^fx_risk_buffer_percent=(\S+) is outside the recommended ([\d.]+)–([\d.]+)% band\.$"
        ),
        lambda m: (
            f"Валютный буфер {m.group(1).replace('.', ',')}% вне рекомендуемого диапазона "
            f"{m.group(2).replace('.', ',')}–{m.group(3).replace('.', ',')}%."
        ),
    ),
    (
        re.compile(
            r"^No route meets target_delivery_days_max=(\d+); rankings were computed over all routes\.$"
        ),
        r"Ни один маршрут не укладывается в целевой срок \1 дн.; ранжирование выполнено по всем маршрутам.",
    ),
    (
        re.compile(
            r"^Destination '(.+)' has no configured rate from (.+); a conservative fallback domestic rate was used\.$"
        ),
        r"Для города «\1» нет тарифа доставки от хаба \2; применён консервативный резервный тариф.",
    ),
    (
        re.compile(r"^No LOW_LEGAL route available.*$"),
        "Нет маршрутов с низким (легальным) уровнем риска; рекомендация несёт транзитный / таможенный риск.",
    ),
    (
        re.compile(r"^Import duty is identical in both jurisdictions.*$"),
        "Ввозная пошлина одинакова в обеих юрисдикциях (единый таможенный тариф ЕАЭС).",
    ),
    (
        re.compile(r"^VAT at the border: KG ([\d.]+)% vs RU ([\d.]+)%\.$"),
        r"НДС на границе: КР \1% против РФ \2%.",
    ),
    (
        re.compile(
            r"^Russian import VAT on the subsequent intra-EAEU transfer is excluded here.*$"
        ),
        "Российский НДС при последующей поставке внутри ЕАЭС здесь не учтён; полная стоимость — в маршрутах белой схемы через КР.",
    ),
    (
        re.compile(r"^No (\S+) corridors configured for (\S+) → (.+); (\S+) routes skipped\.$"),
        r"Для направления \2 → \3 не настроены коридоры типа \1; маршруты \4 пропущены.",
    ),
    (
        re.compile(r"^No routes could be evaluated for this request\.$"),
        "Для запроса не удалось рассчитать ни одного маршрута.",
    ),
]


def ru(text: str) -> str:
    """Translate an engine note/warning template into Russian (unknown texts pass through)."""
    for pattern, replacement in _NOTE_RULES:
        if pattern.match(text):
            return pattern.sub(replacement, text)
    return text


_UNIT_RU = {"kg": "кг", "pair": "пара", "piece": "шт"}


def rate_ru(entry: Any) -> str:
    """Russian rendering of a tariff rate ('10%, но не менее 1,88 EUR/кг')."""
    unit = (
        _UNIT_RU.get(entry.specific_unit.value, entry.specific_unit.value)
        if entry.specific_unit
        else ""
    )
    ad_valorem = f"{fmt(entry.ad_valorem_percent).replace('.', ',')}%"
    specific = f"{fmt(entry.specific_rate_eur).replace('.', ',')} EUR/{unit}"
    if entry.rate_type is DutyRateType.AD_VALOREM:
        return f"{ad_valorem} адвалорная"
    if entry.rate_type is DutyRateType.SPECIFIC:
        return f"{specific} (специфическая)"
    return f"{ad_valorem}, но не менее {specific}"


def money(value: Decimal | int | str) -> str:
    return str(q2(Decimal(str(value))))


def rate(value: Decimal) -> str:
    return str(q4(value))


def route_row(route: RouteComparisonResult) -> dict[str, Any]:
    return {
        "route_id": route.route_id,
        "route_name": route.route_name,
        "clearance_type": route.clearance_type.value,
        "clearance_ru": CLEARANCE_RU[route.clearance_type],
        "hub": route.hub,
        "transport_mode": MODE_RU[route.transport_mode.value],
        "domestic_mode": MODE_RU[route.domestic_transport_mode.value],
        "total_cost_rub": money(route.total_cost_rub),
        "cost_per_unit_rub": money(route.cost_per_unit_rub),
        "cost_per_kg_rub": money(route.cost_per_kg_rub),
        "days": f"{route.estimated_days_min}–{route.estimated_days_max}",
        "days_max": route.estimated_days_max,
        "risk_level": route.risk_level.value,
        "risk_ru": RISK_RU[route.risk_level.value],
        "risk_score": route.risk_score,
        "risk_adjusted_cost_rub": money(route.risk_adjusted_cost_rub or ZERO),
        "labels": [LABEL_RU[label] for label in route.labels],
        "is_recommended": route.is_recommended,
        "breakdown": {key: money(val) for key, val in route.breakdown.items()},
        "recoverable_vat_rub": money(route.recoverable_vat_rub),
        "gross_margin_percent": money(route.gross_margin_percent)
        if route.gross_margin_percent is not None
        else None,
        "meets_deadline": route.meets_deadline,
        "chargeable_weight_kg": rate(route.chargeable_weight_kg),
        "notes": [ru(n) for n in route.notes],
        "fx_rates_used": {k: str(v) for k, v in route.fx_rates_used.items()},
    }


def request_summary(request: VEDCalculationRequest) -> list[tuple[str, str]]:
    cargo, a = request.cargo, request.assumptions
    return [
        ("Страна отправления", ORIGIN_RU[request.origin_country.value]),
        ("Город назначения (РФ)", request.destination_city_ru),
        ("Категория", CATEGORY_RU[cargo.category]),
        ("Код ТН ВЭД", cargo.hs_code or "— (тариф категории по умолчанию)"),
        ("Описание", cargo.description or "—"),
        ("Вес брутто, кг", str(cargo.total_weight_kg)),
        ("Объём, м³", str(cargo.total_volume_m3)),
        ("Плотность, кг/м³", str(cargo.density_kg_per_m3)),
        ("Стоимость по инвойсу", f"{cargo.declared_value_origin} {cargo.origin_currency.value}"),
        ("Количество единиц", str(cargo.quantity_units)),
        ("Стоимость единицы", f"{cargo.declared_value_per_unit} {cargo.origin_currency.value}"),
        ("Целевой срок доставки, дней", str(request.target_delivery_days_max or "не задан")),
        ("Белая растаможка", "да" if request.allow_white_customs else "нет"),
        ("Карго / упрощёнка", "да" if request.allow_cargo_simplified else "нет"),
        ("Бенчмарк: прямой импорт в РФ", "да" if request.include_direct_ru_benchmark else "нет"),
        ("Валютный буфер δ_fx, %", str(request.fx_risk_buffer_percent)),
        ("Целевая цена продажи, ₽/ед.", str(request.target_sale_price_rub_per_unit or "не задана")),
        (
            "Налоговый режим получателя",
            "ОСНО (НДС к вычету)"
            if a.recipient_tax_regime is RecipientTaxRegime.OSNO
            else "УСН (НДС — затраты)",
        ),
        (
            "НДС КР 12% возмещается ОсОО",
            "да" if a.kg_import_vat_recoverable else "нет (формула B спецификации)",
        ),
        (
            "База таможенной стоимости",
            "CIF (инвойс + фрахт до границы)"
            if a.customs_valuation_basis is CustomsValuationBasis.CIF
            else "Инвойс (фрахт только в базе НДС)",
        ),
        ("Наценка агента ОсОО, %", str(a.agent_markup_percent)),
        (
            "Страхование (белая / карго), %",
            f"{a.insurance_percent_white} / {a.insurance_percent_cargo}",
        ),
        ("Сертификаты уже есть", "да" if a.has_valid_certificates else "нет"),
        ("Маркировка «Честный ЗНАК»", "учитывается" if a.apply_marking else "не учитывается"),
        ("Комиссия платёжного агента (прямой импорт), %", str(a.payment_agent_fee_percent)),
        ("Дата расчёта", a.calculation_date.isoformat()),
    ]


# --------------------------------------------------------------------------- step-by-step
def _step(
    steps: list[dict[str, str]], title: str, formula: str, value: Decimal | str, unit: str
) -> None:
    steps.append(
        {
            "n": str(len(steps) + 1),
            "title": title,
            "formula": formula,
            "value": money(value) if not isinstance(value, str) else value,
            "unit": unit,
        }
    )


def _freight_steps(
    steps: list[dict[str, str]], card: CorridorRateCard, request: VEDCalculationRequest
) -> Any:
    cargo = request.cargo
    fq = engine.freight.quote_corridor(card, cargo)
    _step(
        steps,
        "Объёмный вес",
        f"{cargo.total_volume_m3} м³ × {card.volumetric_coefficient_kg_per_m3} кг/м³",
        fq.volumetric_weight_kg,
        "кг",
    )
    _step(
        steps,
        "Расчётный (платный) вес",
        f"max({cargo.total_weight_kg}; {fmt(fq.volumetric_weight_kg)})",
        fq.chargeable_weight_kg,
        "кг",
    )
    mult = "" if fq.category_multiplier == 1 else f" × коэфф. категории {fq.category_multiplier}"
    _step(
        steps,
        f"Фрахт {card.origin_hub} → {card.destination_hub} ({MODE_RU[card.transport_mode.value]})",
        f"max({fmt(fq.chargeable_weight_kg)} кг × {card.rate_per_kg_usd} $/кг{mult}; минимум {card.min_charge_usd} $)",
        fq.freight_usd,
        "USD",
    )
    if fq.handling_usd:
        _step(
            steps,
            "Обработка на хабе",
            f"{card.handling_fixed_usd} $ + {card.handling_per_kg_usd} $/кг × {fmt(fq.chargeable_weight_kg)} кг",
            fq.handling_usd,
            "USD",
        )
    return fq


def _bank_step(
    steps: list[dict[str, str]],
    fx: FxService,
    corridor: TransferCorridor,
    amount: Decimal,
    currency: Currency,
    title: str,
) -> Any:
    leg = fx.bank_leg(corridor, amount, currency)
    rule = fx.bank_fees.leg(corridor).transfer
    spread = fx.bank_fees.leg(corridor).conversion_spread_percent
    _step(
        steps,
        title,
        f"комиссия clamp({fmt(leg.amount)} × {rule.percent}%; мин {rule.minimum}; макс {rule.maximum}) = {money(leg.transfer_fee)} + спред {spread}% = {money(leg.conversion_spread)}",
        leg.total,
        leg.currency.value,
    )
    return leg


def _customs_steps(
    steps: list[dict[str, str]],
    jurisdiction: Jurisdiction,
    request: VEDCalculationRequest,
    fx: FxService,
    freight_usd: Decimal,
) -> Any:
    cargo, a = request.cargo, request.assumptions
    clr = engine.customs.calculate_clearance(
        jurisdiction,
        cargo,
        fx,
        freight_to_border_usd=freight_usd,
        valuation_basis=a.customs_valuation_basis,
    )
    local = clr.currency.value
    ccy = cargo.origin_currency
    _step(
        steps,
        f"Стоимость товара в {local} (официальный курс)",
        f"{cargo.declared_value_origin} {ccy.value} × {rate(fx.mid_rate(ccy, clr.currency))}",
        clr.invoice_value_local,
        local,
    )
    _step(
        steps,
        f"Фрахт до границы ЕАЭС в {local}",
        f"{money(freight_usd)} USD × {rate(fx.mid_rate(Currency.USD, clr.currency))}",
        clr.freight_to_border_local,
        local,
    )
    basis = (
        "инвойс + фрахт (CIF, ст. 40 ТК ЕАЭС)"
        if a.customs_valuation_basis is CustomsValuationBasis.CIF
        else "инвойс (базис по спецификации)"
    )
    _step(steps, "Таможенная стоимость", basis, clr.customs_value, local)
    d = clr.duty
    eur = rate(d.eur_rate)
    if d.rate_type is DutyRateType.AD_VALOREM:
        formula = f"{fmt(d.ad_valorem_percent)}% × {money(d.customs_value)}"
    elif d.rate_type is DutyRateType.SPECIFIC:
        formula = f"{fmt(d.specific_rate_eur)} EUR × {fmt(d.specific_quantity)} {d.specific_unit.value if d.specific_unit else ''} × {eur} {local}/EUR"
    else:
        formula = (
            f"max({fmt(d.ad_valorem_percent)}% × {money(d.customs_value)} = {money(d.ad_valorem_amount)}; "
            f"{fmt(d.specific_rate_eur)} EUR × {fmt(d.specific_quantity)} {d.specific_unit.value if d.specific_unit else ''} × {eur} = {money(d.specific_amount)})"
        )
    _step(steps, f"Таможенная пошлина (ЕТТ ЕАЭС: {rate_ru(clr.tariff)})", formula, d.duty, local)
    if a.customs_valuation_basis is CustomsValuationBasis.CIF:
        vat_formula = f"({money(clr.customs_value)} + {money(d.duty)})"
    else:
        vat_formula = (
            f"({money(clr.customs_value)} + {money(d.duty)} + {money(clr.freight_to_border_local)})"
        )
    _step(steps, "База НДС", vat_formula, clr.vat_base, local)
    _step(
        steps,
        f"НДС при ввозе ({fmt(clr.vat_percent)}%)",
        f"{money(clr.vat_base)} × {fmt(clr.vat_percent)}%",
        clr.vat,
        local,
    )
    profile = engine.customs.profile(jurisdiction)
    if profile.customs_processing_fee.kind == "percent":
        rule = profile.customs_processing_fee
        fee_formula = f"clamp({fmt(rule.percent)}% × {money(clr.customs_value)}; мин {rule.minimum}; макс {rule.maximum})"
    else:
        fee_formula = (
            f"ставка по шкале ПП РФ №1638 для таможенной стоимости {money(clr.customs_value)} ₽"
        )
    _step(
        steps,
        "Таможенный сбор за таможенные операции",
        fee_formula,
        clr.customs_processing_fee,
        local,
    )
    _step(
        steps,
        "Услуги таможенного представителя (брокера)",
        "фиксированная ставка за декларацию",
        clr.broker_fee,
        local,
    )
    _step(
        steps,
        "Итого расходы на очистку",
        f"{money(d.duty)} + {money(clr.vat)} + {money(clr.customs_processing_fee)} + {money(clr.broker_fee)}",
        clr.total_taxes_and_fees,
        local,
    )
    return clr


def _rub_table(
    fx: FxService, items: list[tuple[str, Decimal, Currency]]
) -> tuple[list[dict[str, str]], dict[str, Decimal], Decimal]:
    rows = []
    mids: dict[str, Decimal] = {}
    buffer_total = ZERO
    for label, amount, ccy in items:
        conv = fx.convert_with_buffer(amount, ccy, Currency.RUB)
        mids[label] = mids.get(label, ZERO) + conv.amount_at_mid
        buffer_total += conv.buffer_cost
        rows.append(
            {
                "component": label,
                "amount": money(amount),
                "currency": ccy.value,
                "mid_rate": rate(conv.mid_rate),
                "rub_mid": money(conv.amount_at_mid),
                "buffer": money(conv.buffer_cost),
                "rub_buffered": money(conv.amount_buffered),
            }
        )
    return rows, mids, buffer_total


def _ru_side(steps: list[dict[str, str]], request: VEDCalculationRequest, tariff: Any) -> Decimal:
    cargo, a = request.cargo, request.assumptions
    fees = engine.landed_cost.service_fees
    total = ZERO
    if not a.has_valid_certificates:
        cert = fees.certification_fee_rub[cargo.category]
        _step(
            steps,
            "Сертификация / декларирование соответствия",
            tariff.certification_scheme or "по категории",
            cert,
            "RUB",
        )
        total += cert
    if tariff.marking_required and a.apply_marking:
        per_unit = fees.marking_code_cost_rub + fees.marking_application_cost_rub_per_unit
        marking = per_unit * cargo.quantity_units
        _step(
            steps,
            "Маркировка «Честный ЗНАК»",
            f"{cargo.quantity_units} ед. × ({fees.marking_code_cost_rub} ₽ код + {fees.marking_application_cost_rub_per_unit} ₽ нанесение)",
            marking,
            "RUB",
        )
        total += marking
    if (
        tariff.ru_technology_fee_rub_per_unit > ZERO
        and a.calculation_date >= fees.ru_technology_fee_effective_from
    ):
        tech = tariff.ru_technology_fee_rub_per_unit * cargo.quantity_units
        _step(
            steps,
            "Технологический сбор",
            f"{cargo.quantity_units} × {tariff.ru_technology_fee_rub_per_unit} ₽",
            tech,
            "RUB",
        )
        total += tech
    return total


def _domestic_step(
    steps: list[dict[str, str]], leg: DomesticLegRate, request: VEDCalculationRequest
) -> Decimal:
    dq = engine.freight.quote_domestic(leg, request.cargo)
    _step(
        steps,
        f"Доставка {leg.from_hub} → {request.destination_city_ru} ({MODE_RU[leg.transport_mode.value]})",
        f"max({fmt(dq.chargeable_weight_kg)} кг × {leg.rate_per_kg_rub} ₽/кг; минимум {leg.min_charge_rub} ₽)",
        dq.cost_rub,
        "RUB",
    )
    return dq.cost_rub


def steps_for_route(
    request: VEDCalculationRequest,
    route: RouteComparisonResult,
    corridor_id: str,
    leg: DomesticLegRate,
) -> dict[str, Any]:
    cargo, a = request.cargo, request.assumptions
    fx = engine.optimizer.fx_for(request)
    card = engine.freight.corridor(corridor_id)
    ccy, value = cargo.origin_currency, cargo.declared_value_origin
    steps: list[dict[str, str]] = []
    fq = _freight_steps(steps, card, request)
    ct = route.clearance_type
    rub_rows: list[dict[str, str]] = []
    tail: list[dict[str, str]] = []
    resolved = engine.customs.resolve_tariff(cargo).entry

    if ct is ClearanceType.OFFICIAL_EAEU_KG:
        ins = apply_percent(value, a.insurance_percent_white)
        _step(steps, "Страхование груза", f"{value} × {a.insurance_percent_white}%", ins, ccy.value)
        leg1 = _bank_step(
            steps,
            fx,
            TransferCorridor.for_supplier_currency(ccy),
            value,
            ccy,
            "Перевод поставщику (SWIFT/CIPS)",
        )
        clr = _customs_steps(steps, Jurisdiction.KG, request, fx, fq.freight_usd)
        items = [
            ("Стоимость товара", value, ccy),
            ("Банковский перевод поставщику", leg1.total, leg1.currency),
            ("Международный фрахт", fq.freight_usd, Currency.USD),
            ("Обработка на хабе", fq.handling_usd, Currency.USD),
            ("Страхование", ins, ccy),
            ("Таможенная пошлина", clr.duty.duty, Currency.KGS),
            ("Таможенный сбор", clr.customs_processing_fee, Currency.KGS),
            ("Брокер", clr.broker_fee, Currency.KGS),
        ]
        recoverable = ZERO
        if a.kg_import_vat_recoverable:
            recoverable += fx.convert_official(clr.vat, Currency.KGS, Currency.RUB)
        else:
            items.append(("НДС КР 12%", clr.vat, Currency.KGS))
        rub_rows, mids, buffer_total = _rub_table(fx, items)
        outlays = sum(mids.values(), ZERO) + buffer_total
        _step(
            tail,
            "Затраты ОсОО в рублях (с буфером δ_fx)",
            "сумма столбца «₽ с буфером»",
            outlays,
            "RUB",
        )
        markup = apply_percent(outlays, a.agent_markup_percent)
        _step(
            tail,
            "Наценка агента ОсОО",
            f"{money(outlays)} × {a.agent_markup_percent}%",
            markup,
            "RUB",
        )
        transfer = outlays + markup
        _step(
            tail,
            "Цена поставки ОсОО → РФ (база ввозного НДС)",
            f"{money(outlays)} + {money(markup)}",
            transfer,
            "RUB",
        )
        vat_pct = engine.customs.profile(Jurisdiction.RU).vat_percent
        vat_ru = apply_percent(transfer, vat_pct)
        if a.recipient_tax_regime is RecipientTaxRegime.OSNO:
            _step(
                tail,
                f"НДС при ввозе в РФ ({fmt(vat_pct)}%) — к вычету (ОСНО), в итог не входит",
                f"{money(transfer)} × {fmt(vat_pct)}%",
                vat_ru,
                "RUB",
            )
            recoverable += vat_ru
            vat_ru_cost = ZERO
        else:
            _step(
                tail,
                f"НДС при ввозе в РФ ({fmt(vat_pct)}%) — уплачивается в ФНС по заявлению о ввозе",
                f"{money(transfer)} × {fmt(vat_pct)}%",
                vat_ru,
                "RUB",
            )
            vat_ru_cost = vat_ru
        leg2 = _bank_step(
            tail,
            fx,
            TransferCorridor.RUB_KGS_LOCAL,
            transfer,
            Currency.RUB,
            "Перевод покупателя ОсОО (RUB → KGS)",
        )
        ru_side = _ru_side(tail, request, clr.tariff)
        local = _domestic_step(tail, leg, request)
        total = outlays + markup + vat_ru_cost + leg2.total + ru_side + local
    elif ct is ClearanceType.CARGO_SIMPLIFIED:
        ins = apply_percent(value, a.insurance_percent_cargo)
        _step(
            steps,
            "Страхование груза (карго)",
            f"{value} × {a.insurance_percent_cargo}%",
            ins,
            ccy.value,
        )
        leg1 = _bank_step(
            steps,
            fx,
            TransferCorridor.for_supplier_currency(ccy),
            value,
            ccy,
            "Перевод поставщику (SWIFT/CIPS)",
        )
        items = [
            ("Стоимость товара", value, ccy),
            ("Банковский перевод поставщику", leg1.total, leg1.currency),
            ("Карго-фрахт (всё включено)", fq.freight_usd, Currency.USD),
            ("Обработка на хабе", fq.handling_usd, Currency.USD),
            ("Страхование", ins, ccy),
        ]
        rub_rows, mids, buffer_total = _rub_table(fx, items)
        outlays = sum(mids.values(), ZERO) + buffer_total
        _step(
            tail, "Затраты в рублях (с буфером δ_fx)", "сумма столбца «₽ с буфером»", outlays, "RUB"
        )
        markup = apply_percent(outlays, a.agent_markup_percent)
        _step(
            tail,
            "Наценка агента ОсОО",
            f"{money(outlays)} × {a.agent_markup_percent}%",
            markup,
            "RUB",
        )
        transfer = outlays + markup
        leg2 = _bank_step(
            tail,
            fx,
            TransferCorridor.RUB_KGS_LOCAL,
            transfer,
            Currency.RUB,
            "Перевод покупателя агенту (RUB → KGS)",
        )
        _step(
            tail,
            "Пошлина, НДС, сертификация, маркировка",
            "не начисляются — груз без декларации и документов",
            ZERO,
            "RUB",
        )
        local = _domestic_step(tail, leg, request)
        total = outlays + markup + leg2.total + local
        recoverable = ZERO
    else:
        ins = apply_percent(value, a.insurance_percent_white)
        _step(steps, "Страхование груза", f"{value} × {a.insurance_percent_white}%", ins, ccy.value)
        clr = _customs_steps(steps, Jurisdiction.RU, request, fx, fq.freight_usd)
        items = [
            ("Стоимость товара", value, ccy),
            ("Международный фрахт", fq.freight_usd, Currency.USD),
            ("Обработка на хабе", fq.handling_usd, Currency.USD),
            ("Страхование", ins, ccy),
        ]
        rub_rows, mids, buffer_total = _rub_table(fx, items)
        goods_buffered = fx.convert_with_buffer(value, ccy, Currency.RUB).amount_buffered
        agent = apply_percent(goods_buffered, a.payment_agent_fee_percent)
        _step(
            tail,
            "Комиссия платёжного агента",
            f"{money(goods_buffered)} × {a.payment_agent_fee_percent}%",
            agent,
            "RUB",
        )
        _step(
            tail,
            "Пошлина + сбор + брокер (в ₽, официальный курс)",
            f"{money(clr.duty.duty)} + {money(clr.customs_processing_fee)} + {money(clr.broker_fee)}",
            clr.duty.duty + clr.customs_processing_fee + clr.broker_fee,
            "RUB",
        )
        recoverable = ZERO
        if a.recipient_tax_regime is RecipientTaxRegime.OSNO:
            _step(
                tail,
                f"НДС при ввозе ({fmt(clr.vat_percent)}%) — к вычету (ОСНО), в итог не входит",
                "см. таможенный расчёт",
                clr.vat,
                "RUB",
            )
            recoverable += clr.vat
            vat_cost = ZERO
        else:
            _step(
                tail,
                f"НДС при ввозе ({fmt(clr.vat_percent)}%) — затраты (УСН)",
                "см. таможенный расчёт",
                clr.vat,
                "RUB",
            )
            vat_cost = clr.vat
        ru_side = _ru_side(tail, request, clr.tariff)
        local = _domestic_step(tail, leg, request)
        total = (
            sum(mids.values(), ZERO)
            + buffer_total
            + agent
            + clr.duty.duty
            + clr.customs_processing_fee
            + clr.broker_fee
            + vat_cost
            + ru_side
            + local
        )

    _step(tail, "ИТОГО landed cost", "сумма всех компонентов", total, "RUB")
    _step(
        tail,
        "Стоимость на единицу",
        f"{money(total)} / {cargo.quantity_units}",
        total / cargo.quantity_units,
        "RUB/ед.",
    )
    _step(
        tail,
        "Стоимость на кг брутто",
        f"{money(total)} / {cargo.total_weight_kg}",
        total / cargo.total_weight_kg,
        "RUB/кг",
    )
    # consistency check against the engine (components are rounded before summing there)
    assert abs(q2(total) - route.total_cost_rub) <= Decimal("0.10"), (
        q2(total),
        route.total_cost_rub,
        route.route_id,
    )
    return {
        "route_id": route.route_id,
        "route_name": route.route_name,
        "clearance_ru": CLEARANCE_RU[ct],
        "corridor_id": corridor_id,
        "steps": steps,
        "rub_table": rub_rows,
        "buffer_total": money(buffer_total),
        "tail": tail,
        "recoverable_vat_rub": money(recoverable),
        "engine_total": money(route.total_cost_rub),
        "tariff_line": f"{resolved.hs_code or 'категория'} — {resolved.description_ru} — {rate_ru(resolved)}",
    }


def candidate_parts(
    request: VEDCalculationRequest, route: RouteComparisonResult
) -> tuple[str, DomesticLegRate]:
    hub, kind = HUB_FOR_CLEARANCE[route.clearance_type]
    cards = [
        c
        for c in engine.freight.corridors_for(request.origin_country, kind, hub)
        if c.transport_mode is route.transport_mode
    ]
    legs, _ = engine.freight.domestic_legs_for(hub, request.destination_city_ru)
    leg = next(leg for leg in legs if leg.transport_mode is route.domestic_transport_mode)
    return cards[0].corridor_id, leg


# --------------------------------------------------------------------------- scenarios
SCENARIOS: list[tuple[str, str, dict[str, Any]]] = [
    ("S0", "Базовый (УСН, НДС КР — затраты, буфер 2,5%)", {}),
    (
        "S1",
        "ОсОО возмещает НДС КР 12% (экспорт по ставке 0%)",
        {"assumptions": {"kg_import_vat_recoverable": True}},
    ),
    (
        "S2",
        "Получатель на ОСНО (ввозной НДС к вычету)",
        {"assumptions": {"recipient_tax_regime": "OSNO"}},
    ),
    (
        "S3",
        "ОСНО + возмещение НДС КР",
        {"assumptions": {"recipient_tax_regime": "OSNO", "kg_import_vat_recoverable": True}},
    ),
    ("S4", "Без бенчмарка прямого импорта в РФ", {"include_direct_ru_benchmark": False}),
    ("S5", "Ограничение срока: не более 20 дней", {"target_delivery_days_max": 20}),
    ("S6", "Валютный буфер 0%", {"fx_risk_buffer_percent": "0"}),
    ("S7", "Валютный буфер 3%", {"fx_risk_buffer_percent": "3"}),
    (
        "S8",
        "Таможенная стоимость CIF (фрахт в базе пошлины)",
        {"assumptions": {"customs_valuation_basis": "CIF"}},
    ),
    ("S9", "Сертификаты уже оформлены", {"assumptions": {"has_valid_certificates": True}}),
]

EXTRA_SHIPMENTS: list[tuple[str, dict[str, Any]]] = [
    (
        "Джинсы из Китая (инвойс в CNY) → Москва",
        {
            "origin_country": "CHINA",
            "destination_city_ru": "Москва",
            "cargo": {
                "category": "apparel",
                "hs_code": "6203 42 310 0",
                "total_weight_kg": "300",
                "total_volume_m3": "1.5",
                "declared_value_origin": "60000",
                "origin_currency": "CNY",
                "quantity_units": 1000,
                "description": "Джинсы мужские, 1 000 шт.",
            },
        },
    ),
    (
        "Худи из Турции (инвойс в EUR) → Екатеринбург",
        {
            "origin_country": "TURKEY",
            "destination_city_ru": "Екатеринбург",
            "cargo": {
                "category": "apparel",
                "hs_code": "6110 20",
                "total_weight_kg": "200",
                "total_volume_m3": "1.4",
                "declared_value_origin": "9000",
                "origin_currency": "EUR",
                "quantity_units": 600,
                "description": "Худи хлопковые, 600 шт.",
            },
        },
    ),
    (
        "Ноутбуки из ЕС (инвойс в EUR) → Казань",
        {
            "origin_country": "EU",
            "destination_city_ru": "Казань",
            "cargo": {
                "category": "electronics",
                "hs_code": "8471 30 000 0",
                "total_weight_kg": "80",
                "total_volume_m3": "0.5",
                "declared_value_origin": "40000",
                "origin_currency": "EUR",
                "quantity_units": 50,
                "description": "Ноутбуки, 50 шт.",
            },
            "assumptions": {"calculation_date": "2026-12-15"},
        },
    ),
    (
        "Смартфоны из ОАЭ (инвойс в USD) → Москва",
        {
            "origin_country": "UAE",
            "destination_city_ru": "Москва",
            "cargo": {
                "category": "electronics",
                "hs_code": "8517 13 000 0",
                "total_weight_kg": "60",
                "total_volume_m3": "0.35",
                "declared_value_origin": "45000",
                "origin_currency": "USD",
                "quantity_units": 150,
                "description": "Смартфоны, 150 шт.",
            },
            "include_direct_ru_benchmark": True,
        },
    ),
    (
        "Пластиковая посуда из Вьетнама (USD) → Новосибирск",
        {
            "origin_country": "VIETNAM",
            "destination_city_ru": "Новосибирск",
            "cargo": {
                "category": "general",
                "hs_code": "3924 10 000 0",
                "total_weight_kg": "400",
                "total_volume_m3": "3.2",
                "declared_value_origin": "6000",
                "origin_currency": "USD",
                "quantity_units": 2000,
                "description": "Посуда пластиковая, 2 000 шт.",
            },
        },
    ),
    (
        "Кожаная обувь из США (USD) → Санкт-Петербург",
        {
            "origin_country": "USA",
            "destination_city_ru": "Санкт-Петербург",
            "cargo": {
                "category": "footwear",
                "hs_code": "6403 99 960 0",
                "total_weight_kg": "150",
                "total_volume_m3": "0.9",
                "declared_value_origin": "18000",
                "origin_currency": "USD",
                "quantity_units": 120,
                "description": "Мужская кожаная обувь, 120 пар",
            },
            "target_delivery_days_max": 30,
        },
    ),
]

SOURCES = [
    (
        "НДС 22% с 01.01.2026 (ФЗ №425-ФЗ от 28.11.2025)",
        "https://its.1c.ru/db/newscomm/content/497590/hdoc",
    ),
    (
        "Ставки таможенных сборов РФ с 01.01.2026 (ПП РФ №1638)",
        "https://www.garant.ru/news/1897566/",
    ),
    (
        "Таблица сборов 2026",
        "https://sttlogistics.ru/information/o-tamozhennom-oformlenii/tamozhennye-sbory-2026/",
    ),
    ("Таможенный сбор КР 0,4% (ПКМ КР №349 от 03.07.2024)", "https://www.alta.ru/tamdoc/24kg0349/"),
    ("ЕТТ ЕАЭС 6404 11 000 0 — 0,47 евро/пара", "https://www.tws.by/tws/tnved/code/7561"),
    ("ЕТТ ЕАЭС 6403 99 960 0 — 1,25 евро/пара", "https://www.tws.by/tws/tnved/code/7559"),
    ("ЕТТ ЕАЭС группа 61", "https://www.alta.ru/ett/gruppa61.html"),
    ("ЕТТ ЕАЭС группа 62", "https://www.alta.ru/ett/gruppa62.html"),
    ("ЕТТ ЕАЭС 8518 30 950 0 — 5%", "https://www.alta.ru/tnved/code/8518309500/"),
    ("ЕТТ ЕАЭС 3924 10 000 0 — 6,5%", "https://www.alta.ru/tnved/code/3924100000/"),
    ("ЕТТ ЕАЭС 9503 00 700 0 — 10%", "https://www.alta.ru/tnved/code/9503007000/"),
    ("Технологический сбор с 01.12.2026", "https://predprinimatel.ru/news/tehsbor-stavki/"),
    ("Карго Китай → Бишкек: тарифы", "https://techpoint.kg/home/kargo.html"),
    ("Карго Китай → Бишкек: сроки и цены", "https://trialkg.com/cargo-iz-kitaya/"),
    (
        "Сборные грузы Бишкек → Москва",
        "https://maintransport.ru/transportnye-kompanii/bishkek/moskva",
    ),
]


def build(request_path: Path) -> dict[str, Any]:
    raw = json.loads(request_path.read_text(encoding="utf-8"))
    request = VEDCalculationRequest.model_validate(raw)
    result = engine.calculate(request)
    routes = [route_row(r) for r in result.routes] + [route_row(r) for r in result.excluded_routes]
    fx = engine.optimizer.fx_for(request)

    # step-by-step for one representative route per family (auto-standard truck where available)
    detailed: list[dict[str, Any]] = []
    for ct in request.allowed_clearance_types():
        family = [r for r in result.routes + result.excluded_routes if r.clearance_type is ct]
        pick = next(
            (
                r
                for r in family
                if r.transport_mode.value == "AUTO_STANDARD"
                and r.domestic_transport_mode.value == "TRUCK"
            ),
            family[0],
        )
        corridor_id, leg = candidate_parts(request, pick)
        detailed.append(steps_for_route(request, pick, corridor_id, leg))

    # customs comparison KG vs RU with the white auto-standard freight
    white_card = next(
        c
        for c in engine.freight.corridors_for(request.origin_country, "WHITE_FREIGHT", BISHKEK)
        if c.transport_mode.value == "AUTO_STANDARD"
    )
    white_fq = engine.freight.quote_corridor(white_card, request.cargo)
    cmp = engine.customs.compare_jurisdictions(
        request.cargo,
        fx.with_buffer(0),
        freight_to_border_usd=white_fq.freight_usd,
        valuation_basis=request.assumptions.customs_valuation_basis,
    )

    def clr_block(c: Any) -> dict[str, str]:
        return {
            "jurisdiction": c.jurisdiction.value,
            "currency": c.currency.value,
            "invoice": money(c.invoice_value_local),
            "freight": money(c.freight_to_border_local),
            "customs_value": money(c.customs_value),
            "duty": money(c.duty.duty),
            "duty_rule": rate_ru(c.tariff),
            "vat_percent": fmt(c.vat_percent),
            "vat_base": money(c.vat_base),
            "vat": money(c.vat),
            "processing_fee": money(c.customs_processing_fee),
            "broker": money(c.broker_fee),
            "taxes_and_fees": money(c.total_taxes_and_fees),
            "cleared": money(c.total_cleared_cost),
            "days": f"{c.clearance_days_min}–{c.clearance_days_max}",
            "taxes_and_fees_rub": money(
                fx.convert_official(c.total_taxes_and_fees, c.currency, Currency.RUB)
            ),
        }

    comparison = {
        "freight_usd": money(white_fq.freight_usd),
        "corridor": white_card.corridor_id,
        "kg": clr_block(cmp.kg),
        "ru": clr_block(cmp.ru),
        "difference_rub": money(cmp.difference_rub),
        "cheaper": cmp.cheaper_jurisdiction.value,
        "notes": [ru(n) for n in cmp.notes],
    }

    # scenarios
    ref_ids = {
        "white": "official-eaeu-kg-auto-standard-truck",
        "cargo": "cargo-simplified-auto-standard-truck",
        "direct": "official-ru-direct-auto-standard-truck",
    }
    scenarios = []
    for code, title, patch in SCENARIOS:
        merged = json.loads(json.dumps(raw))
        for key, val in patch.items():
            if key == "assumptions":
                merged.setdefault("assumptions", {}).update(val)
            else:
                merged[key] = val
        res = engine.calculate(merged)
        pool = res.routes + res.excluded_routes

        def find(fragment: str, pool: list[RouteComparisonResult] = pool) -> str:
            hit = next((r for r in pool if fragment in r.route_id), None)
            return money(hit.total_cost_rub) if hit else "—"

        def pick(r: RouteComparisonResult | None) -> dict[str, str] | None:
            return {"name": r.route_name, "total": money(r.total_cost_rub)} if r else None

        scenarios.append(
            {
                "code": code,
                "title": title,
                "optimal": pick(res.optimal),
                "cheapest": pick(res.cheapest),
                "cheapest_legal": pick(res.cheapest_legal),
                "fastest": pick(res.fastest),
                "white": find(ref_ids["white"]),
                "cargo": find(ref_ids["cargo"]),
                "direct": find(ref_ids["direct"]),
                "warnings": [ru(w) for w in res.warnings],
            }
        )

    # extra shipments
    extras = []
    for title, req in EXTRA_SHIPMENTS:
        r2 = VEDCalculationRequest.model_validate(req)
        res = engine.calculate(r2)
        extras.append(
            {
                "title": title,
                "inputs": request_summary(r2),
                "routes": [route_row(r) for r in res.routes]
                + [route_row(r) for r in res.excluded_routes],
                "summary": res.summary,
                "warnings": [ru(w) for w in res.warnings],
                "optimal_id": res.optimal_route_id,
            }
        )

    # reference data
    ccy = request.cargo.origin_currency
    pairs = [
        (ccy, Currency.KGS),
        (ccy, Currency.RUB),
        (Currency.USD, Currency.KGS),
        (Currency.USD, Currency.RUB),
        (Currency.KGS, Currency.RUB),
        (Currency.EUR, Currency.KGS),
        (Currency.EUR, Currency.RUB),
        (Currency.CNY, Currency.KGS),
    ]
    fx_rows = [
        {"pair": k, "mid": str(v), "buffered": rate(Decimal(v) * fx.buffer_multiplier)}
        for k, v in fx.snapshot(pairs).items()
    ]
    kg_profile, ru_profile = (
        engine.customs.profile(Jurisdiction.KG),
        engine.customs.profile(Jurisdiction.RU),
    )
    fees = engine.landed_cost.service_fees
    policy = engine.optimizer.policy
    tariff_res = engine.customs.resolve_tariff(request.cargo)
    corridors = [
        {
            "corridor_id": c.corridor_id,
            "hub": c.destination_hub,
            "mode": MODE_RU[c.transport_mode.value],
            "kind": "карго (всё включено)"
            if c.service_kind.value == "CARGO_ALL_IN"
            else "фрахт для белой схемы",
            "rate": str(c.rate_per_kg_usd),
            "min": str(c.min_charge_usd),
            "coef": str(c.volumetric_coefficient_kg_per_m3),
            "handling": f"{c.handling_fixed_usd} $ + {c.handling_per_kg_usd} $/кг",
            "days": f"{c.days_min}–{c.days_max}",
            "multipliers": ", ".join(
                f"{CATEGORY_RU[k].split(' /')[0].lower()} ×{v}"
                for k, v in c.category_multipliers.items()
            )
            or "—",
        }
        for c in engine.freight.corridors_for(request.origin_country)
    ]
    legs_rows = []
    for hub in (BISHKEK, MOSCOW):
        legs, is_fb = engine.freight.domestic_legs_for(hub, request.destination_city_ru)
        for leg in legs:
            legs_rows.append(
                {
                    "from": hub,
                    "mode": MODE_RU[leg.transport_mode.value],
                    "rate": str(leg.rate_per_kg_rub),
                    "min": str(leg.min_charge_rub),
                    "coef": str(leg.volumetric_coefficient_kg_per_m3),
                    "days": f"{leg.days_min}–{leg.days_max}",
                    "km": str(leg.distance_km or "—"),
                    "fallback": is_fb,
                }
            )
    bank_rows = []
    for corridor, leg in fx.bank_fees.legs.items():
        t = leg.transfer
        bank_rows.append(
            {
                "corridor": corridor.value,
                "currency": t.currency.value,
                "percent": fmt(t.percent),
                "min": str(t.minimum),
                "max": str(t.maximum),
                "spread": fmt(leg.conversion_spread_percent),
            }
        )

    return {
        "meta": {
            "generated": date.today().isoformat(),
            "version": __version__,
            "fx_as_of": result.fx_as_of.isoformat(),
            "request_file": str(request_path),
        },
        "request": request_summary(request),
        "reference": {
            "fx": fx_rows,
            "fx_buffer": str(request.fx_risk_buffer_percent),
            "tax_profiles": [
                {
                    "jurisdiction": "Кыргызская Республика (КР)",
                    "vat": fmt(kg_profile.vat_percent),
                    "fee": "0,4% таможенной стоимости, мин 500 / макс 250 000 KGS",
                    "broker": f"{kg_profile.broker_fee_local} KGS",
                    "days": f"{kg_profile.clearance_days_min}–{kg_profile.clearance_days_max}",
                    "notes": kg_profile.notes,
                },
                {
                    "jurisdiction": "Российская Федерация (РФ)",
                    "vat": fmt(ru_profile.vat_percent),
                    "fee": "шкала ПП РФ №1638: 1 231 … 73 860 ₽",
                    "broker": f"{ru_profile.broker_fee_local} RUB",
                    "days": f"{ru_profile.clearance_days_min}–{ru_profile.clearance_days_max}",
                    "notes": ru_profile.notes,
                },
            ],
            "ru_fee_tiers": [
                {"up_to": str(t.up_to) if t.up_to is not None else "свыше", "fee": str(t.fee)}
                for t in ru_profile.customs_processing_fee.tiers
            ]
            if ru_profile.customs_processing_fee.kind == "tiered"
            else [],
            "tariff": {
                "hs_code": tariff_res.entry.hs_code,
                "description": tariff_res.entry.description_ru,
                "rate": rate_ru(tariff_res.entry),
                "matched_by": tariff_res.matched_by,
                "marking": tariff_res.entry.marking_required,
                "certification": tariff_res.entry.certification_scheme,
                "verified": tariff_res.entry.verified,
                "source": tariff_res.entry.source,
                "notes": [ru(n) for n in tariff_res.notes],
                "tech_fee": str(tariff_res.entry.ru_technology_fee_rub_per_unit),
            },
            "bank": bank_rows,
            "service_fees": {
                "certification": {
                    CATEGORY_RU[k]: str(v) for k, v in fees.certification_fee_rub.items()
                },
                "marking_code": str(fees.marking_code_cost_rub),
                "marking_apply": str(fees.marking_application_cost_rub_per_unit),
                "hub_days": {
                    CLEARANCE_RU[k]: f"{v.days_min}–{v.days_max}"
                    for k, v in fees.hub_processing_days.items()
                },
                "tech_fee_from": fees.ru_technology_fee_effective_from.isoformat(),
            },
            "policy": {
                "delay": fmt(policy.delay_cost_percent_per_day),
                "loss": {RISK_RU[k.value]: fmt(v) for k, v in policy.expected_loss_percent.items()},
                "prefer_legal": policy.prefer_legal_routes,
            },
            "corridors": corridors,
            "domestic_legs": legs_rows,
        },
        "result": {
            "routes": routes,
            "summary": result.summary,
            "warnings": [ru(w) for w in result.warnings],
            "optimal_id": result.optimal_route_id,
            "cheapest_id": result.cheapest_route_id,
            "cheapest_legal_id": result.cheapest_legal_route_id,
            "fastest_id": result.fastest_route_id,
            "component_names": [(k, COMPONENT_RU[k]) for k in routes[0]["breakdown"]]
            if routes
            else [],
        },
        "detailed": detailed,
        "comparison": comparison,
        "scenarios": scenarios,
        "extras": extras,
        "tariffs": [
            {
                "hs": e.hs_code or "(по умолчанию)",
                "category": CATEGORY_RU[e.category],
                "rate": rate_ru(e),
                "desc": e.description_ru,
                "marking": "да" if e.marking_required else "—",
                "verified": "✓" if e.verified else "~",
                "source": e.source,
            }
            for e in engine.customs.tariffs.entries
        ],
        "sources": SOURCES,
    }


def main() -> None:
    request_path = Path(sys.argv[1] if len(sys.argv) > 1 else "examples/sample_request.json")
    out_path = Path(sys.argv[2] if len(sys.argv) > 2 else "reports/report_data.json")
    data = build(request_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(
        f"wrote {out_path} ({out_path.stat().st_size // 1024} KB): {len(data['result']['routes'])} routes, "
        f"{len(data['detailed'])} detailed, {len(data['scenarios'])} scenarios, {len(data['extras'])} extra shipments"
    )


if __name__ == "__main__":
    main()
