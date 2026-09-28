#!/usr/bin/env python3
"""Business case: opening a sneakers / casual footwear store in Tyumen.

Builds the full financial model (CAPEX, OPEX, unit economics, 12-month P&L and
cash flow for three scenarios, break-even, payback, sensitivity) on top of the
VED Calculator Core landed-cost engine and dumps everything into JSON for
``scripts/build_business_case_docx.js``.

    python scripts/business_case_tyumen.py reports/business_case_data.json
"""

from __future__ import annotations

import json
import sys
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ved_calculator import VEDCalculationRequest, VEDCalculatorEngine
from ved_calculator.domain.models import (
    CalculationAssumptions,
    CargoCategory,
    CargoSpec,
    Currency,
    OriginCountry,
)

D = Decimal
ZERO = D(0)
ONE = D(1)


def q0(x: Decimal | int | float | str) -> str:
    return str(D(str(x)).quantize(D("1"), rounding=ROUND_HALF_UP))


def q1(x: Decimal | int | float | str) -> str:
    return str(D(str(x)).quantize(D("0.1"), rounding=ROUND_HALF_UP))


def rub(x: Decimal | int | float | str) -> str:
    """Thousands-separated integer rubles for narrative strings ("2 494")."""
    return f"{int(q0(x)):,}".replace(",", "\u00a0")


def pct(x: Decimal, base: Decimal) -> str:
    return q1(x / base * 100) if base else "0"


engine = VEDCalculatorEngine()

# --------------------------------------------------------------------------- 1. Store concept
STORE = {
    "name": "Магазин кроссовок и повседневной обуви (бюджетный и средний сегмент, собственный импорт)",
    "format": "Павильон в районном торговом центре, 35 м² (торговый зал ~28 м², подсобка ~7 м²)",
    "location": "ТРЦ «Премьер», ул. 50 лет ВЛКСМ, 63 (Восточный округ, спальный массив)",
    "rent_month": D(30000),
    "area_m2": D(35),
    "sales_area_m2": D(28),
    "hours": "ежедневно 10:00–21:00; в зале 1 наёмный продавец и владелец по графику 2/2",
    "opening_month": "ноябрь 2026",
}

# --------------------------------------------------------------------------- 2. Purchase via VED engine
FIRST_ORDER_PAIRS = 500
AVG_FOB_USD = D("16")  # blended: sneakers $15 (60 %), boots $25 (25 %), slippers/sandals $8 (15 %)
KG_PER_PAIR = D("0.9")
M3_PER_PAIR = D("0.007")


def order_request(pairs: int, has_certs: bool) -> VEDCalculationRequest:
    return VEDCalculationRequest(
        origin_country=OriginCountry.CHINA,
        destination_city_ru="Тюмень",
        cargo=CargoSpec(
            category=CargoCategory.FOOTWEAR,
            hs_code="6404 11 000 0",
            total_weight_kg=KG_PER_PAIR * pairs,
            total_volume_m3=M3_PER_PAIR * pairs,
            declared_value_origin=AVG_FOB_USD * pairs,
            origin_currency=Currency.USD,
            quantity_units=pairs,
            description=f"Кроссовки и повседневная обувь, {pairs} пар",
        ),
        allow_cargo_simplified=True,
        allow_white_customs=True,
        include_direct_ru_benchmark=False,
        assumptions=CalculationAssumptions(has_valid_certificates=has_certs),
    )


first = engine.calculate(order_request(FIRST_ORDER_PAIRS, has_certs=False))
repeat = engine.calculate(order_request(FIRST_ORDER_PAIRS, has_certs=True))
white_first = first.cheapest_legal
white_repeat = repeat.cheapest_legal
cargo_first = first.cheapest
assert white_first and white_repeat and cargo_first
LANDED_FIRST = white_first.cost_per_unit_rub
LANDED_REPEAT = white_repeat.cost_per_unit_rub
LANDED_CARGO = cargo_first.cost_per_unit_rub

# --------------------------------------------------------------------------- 3. Pricing
TARGET_MARKUP = D("1.9")  # retail = landed × 1.9  → gross margin ≈ 47 %
avg_price_raw = LANDED_REPEAT * TARGET_MARKUP
AVG_PRICE = (avg_price_raw / 100).quantize(D("1"), rounding=ROUND_HALF_UP) * 100 - 10  # …90 pricing
ACCESSORIES_SHARE = D("0.04")  # socks, insoles, care products: +4 % to the check at 55 % margin
GP_PER_PAIR = AVG_PRICE - LANDED_REPEAT
PRICE_LADDER = [
    ("Кроссовки базовые (60 % продаж)", "3 990 – 4 990 ₽"),
    ("Кроссовки/полуботинки демисезонные (25 %)", "5 490 – 6 490 ₽"),
    ("Слипоны, сандалии, тапочки (15 %)", "1 490 – 2 490 ₽"),
    ("Аксессуары (носки, стельки, уход)", "190 – 690 ₽"),
]

# --------------------------------------------------------------------------- 4. Payroll (2026 rules)
MROT_2026 = D(27093)
SELLER_GROSS = D(45000)
IP_FIXED_CONTRIBUTIONS_2026 = D(57390)


def employer_cost(gross: Decimal) -> tuple[Decimal, Decimal]:
    """Monthly employer cost for an МСП employer: 30 % up to 1.5×МРОТ, 15 % above, +0.2 % injury."""
    threshold = MROT_2026 * D("1.5")
    contributions = min(gross, threshold) * D("0.30") + max(gross - threshold, ZERO) * D("0.15")
    contributions += gross * D("0.002")
    return gross + contributions, contributions


seller_cost, seller_contrib = employer_cost(SELLER_GROSS)

# --------------------------------------------------------------------------- 5. Taxes
PATENT_PVD_PER_M2 = D(
    80000
)  # Закон Тюменской области №96 от 27.11.2012 (прил. 5) — verify on patent.nalog.ru
patent_year = PATENT_PVD_PER_M2 * STORE["sales_area_m2"] * D("0.06")
patent_month_gross = patent_year / 12
patent_month_net = patent_month_gross * D(
    "0.5"
)  # reduced by insurance contributions (max 50 % with employees)
IP_EXTRA_1PCT = (PATENT_PVD_PER_M2 * STORE["sales_area_m2"] - D(300000)) * D(
    "0.01"
)  # 1 % over 300 000 of ПВД
USN_RATE = D("0.06")

# --------------------------------------------------------------------------- 6. CAPEX
CAPEX: list[tuple[str, Decimal, str]] = [
    (
        "Регистрация ИП, УКЭП, открытие счёта",
        D(3000),
        "госпошлина 0 ₽ при подаче онлайн; УКЭП ~2 500 ₽",
    ),
    ("Обеспечительный платёж по аренде (1 месяц)", STORE["rent_month"], "возвращается при выезде"),
    (
        "Косметический ремонт павильона 35 м² (пол, стены, потолок, свет)",
        D(6000) * STORE["area_m2"],
        "6 000 ₽/м² — нижняя граница рынка 2025",
    ),
    (
        "Вывеска с подсветкой + оформление входа",
        D(55000),
        "световой короб/буквы 45 000 ₽ + витринная графика 10 000 ₽",
    ),
    (
        "Торговое оборудование (экономпанели, полки для обуви, подиумы, зеркала, пуфы, кассовая стойка)",
        D(230000),
        "12 пог. м экспозиции + островной подиум + примерочная зона",
    ),
    ("Освещение экспозиции (трековые светильники)", D(25000), "акцентный свет на товар"),
    ("Стеллажи подсобки", D(20000), "хранение размерного ряда"),
    (
        "Онлайн-касса Эвотор 7.2 + ФН 36 мес + 2D-сканер + принтер этикеток",
        D(54000),
        "25 100 + 14 000 + 6 000 + 9 000 ₽",
    ),
    (
        "Ноутбук/планшет, роутер, видеонаблюдение (4 камеры)",
        D(55000),
        "учёт, Честный ЗНАК, безопасность",
    ),
    ("Противокражные ворота (EAS) и датчики", D(55000), "снижают потери на 2–3 % выручки"),
    (
        "Учётная система (МойСклад/1С:Розница), подключение ОФД на год",
        D(12000),
        "ОФД ~3 000 ₽/год, ПО ~9 000 ₽/год",
    ),
    (
        "Первая партия товара — 500 пар, белая схема через Бишкек",
        LANDED_FIRST * FIRST_ORDER_PAIRS,
        f"{rub(LANDED_FIRST)} ₽/пара с пошлиной, НДС, маркировкой и сертификацией",
    ),
    ("Маркетинг запуска (первые 6 недель)", D(75000), "см. раздел «Реклама»"),
    ("Расходные материалы, пакеты, ценники, форма продавцов", D(15000), ""),
]
capex_subtotal = sum(v for _, v, _ in CAPEX)
CONTINGENCY = (capex_subtotal * D("0.05")).quantize(D("1"))
capex_total = capex_subtotal + CONTINGENCY

# --------------------------------------------------------------------------- 7. OPEX (monthly)
MARKETING_MONTHLY = D(30000)
OPEX_FIXED: list[tuple[str, Decimal, str]] = [
    ("Аренда павильона 35 м²", STORE["rent_month"], "845 ₽/м² — объявление N1.ru, ТРЦ «Премьер»"),
    ("Коммунальные и эксплуатационные платежи ТЦ", D(6000), "электричество, уборка МОП"),
    (
        "ФОТ: 1 продавец × 45 000 ₽ + взносы 30/15 % (МСП); вторую смену закрывает владелец",
        seller_cost,
        f"взносы {rub(seller_contrib)} ₽; второй наёмный продавец — см. чувствительность",
    ),
    (
        "Страховые взносы ИП за себя (фикс. 2026 + 1 % с ПВД свыше 300 000 ₽)",
        (IP_FIXED_CONTRIBUTIONS_2026 + IP_EXTRA_1PCT) / 12,
        f"57 390 + {rub(IP_EXTRA_1PCT)} ₽/год",
    ),
    ("Маркетинг (постоянный)", MARKETING_MONTHLY, "2ГИС, VK, Avito, Telegram-паблики"),
    ("Бухгалтерия на аутсорсе, банк, ОФД, ПО", D(8000), ""),
    ("Интернет, связь, охранная сигнализация", D(3500), ""),
    ("Расходные материалы, упаковка, мелкий ремонт", D(4000), ""),
]
opex_fixed_total = sum(v for _, v, _ in OPEX_FIXED)
ACQUIRING_RATE = D("0.015")  # blended: 80 % cards at 1.8 % + SBP 0.7 %
LOSSES_RATE = D("0.01")  # shrinkage, markdowns on returns

# --------------------------------------------------------------------------- 8. Scenarios & seasonality
SCENARIOS = {
    "pessimistic": {"title": "Пессимистичный", "pairs_store": 75, "pairs_online": 10},
    "base": {"title": "Базовый", "pairs_store": 105, "pairs_online": 20},
    "optimistic": {"title": "Оптимистичный", "pairs_store": 150, "pairs_online": 35},
}
SEASON = {  # index by calendar month, mean = 1.0
    1: D("0.75"),
    2: D("0.80"),
    3: D("1.05"),
    4: D("1.10"),
    5: D("1.00"),
    6: D("0.85"),
    7: D("0.80"),
    8: D("1.05"),
    9: D("1.25"),
    10: D("1.20"),
    11: D("1.00"),
    12: D("1.15"),
}
RAMP = {1: D("0.60"), 2: D("0.80")}  # opening ramp-up
MONTH_NAMES = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
START = (2026, 11)


def month_label(i: int) -> str:
    y, m = START
    m += i - 1
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    return f"{MONTH_NAMES[m - 1]} {y}"


def calendar_month(i: int) -> int:
    return (START[1] + i - 2) % 12 + 1


def run_scenario(
    key: str,
    months: int = 12,
    *,
    landed_repeat: Decimal = LANDED_REPEAT,
    price: Decimal = AVG_PRICE,
    rent: Decimal | None = None,
    sales_multiplier: Decimal = ONE,
    extra_fixed: Decimal = ZERO,
    horizon: int = 24,
) -> dict[str, Any]:
    sc = SCENARIOS[key]
    fixed = (
        opex_fixed_total if rent is None else opex_fixed_total - STORE["rent_month"] + rent
    ) + extra_fixed
    gp_pair = price - landed_repeat
    rows = []
    cumulative = -capex_total
    stock = D(FIRST_ORDER_PAIRS)
    payback_month: int | None = None
    peak_need = cumulative
    total = {
        "pairs": ZERO,
        "revenue": ZERO,
        "cogs": ZERO,
        "gross": ZERO,
        "opex": ZERO,
        "tax": ZERO,
        "net": ZERO,
        "purchases": ZERO,
    }
    total_y2 = dict(total)
    forecast = [
        D(sc["pairs_store"] + sc["pairs_online"])
        * SEASON[calendar_month(i)]
        * RAMP.get(i, D(1))
        * sales_multiplier
        for i in range(1, horizon + 4)
    ]
    for i in range(1, horizon + 1):
        pairs = forecast[i - 1].quantize(D("1"))
        revenue = pairs * price
        accessories = revenue * ACCESSORIES_SHARE
        cogs = pairs * landed_repeat + accessories * D("0.45")
        gross = revenue + accessories - cogs
        variable = (revenue + accessories) * (ACQUIRING_RATE + LOSSES_RATE)
        opex = fixed + variable
        ebitda = gross - opex
        tax = patent_month_net  # patent is due regardless of profit
        net = ebitda - tax
        # inventory: replenish every 3 months to cover the next 3 months (prepaid at order time)
        purchases = ZERO
        if i >= 2 and (i - 2) % 3 == 0 and i <= horizon - 1:
            need = sum(forecast[i : i + 3], ZERO) * D("1.15")  # 15 % safety stock
            order_pairs = max(need - stock + sum(forecast[i - 1 : i], ZERO), D(300)).quantize(
                D("1")
            )
            purchases = order_pairs * landed_repeat
            stock += order_pairs
        stock -= pairs
        cash = net + cogs - purchases  # COGS is not a cash item; purchases are (prepaid at order)
        cumulative += cash
        peak_need = min(peak_need, cumulative)
        if payback_month is None and cumulative >= 0:
            payback_month = i
        if i <= months:
            rows.append(
                {
                    "month": month_label(i),
                    "pairs": q0(pairs),
                    "revenue": q0(revenue + accessories),
                    "cogs": q0(cogs),
                    "gross": q0(gross),
                    "opex": q0(opex),
                    "ebitda": q0(ebitda),
                    "tax": q0(tax),
                    "net": q0(net),
                    "purchases": q0(purchases),
                    "cash": q0(cash),
                    "cumulative": q0(cumulative),
                    "stock": q0(stock),
                }
            )
        bucket = total if i <= months else total_y2
        for k, v in (
            ("pairs", pairs),
            ("revenue", revenue + accessories),
            ("cogs", cogs),
            ("gross", gross),
            ("opex", opex),
            ("tax", tax),
            ("net", net),
            ("purchases", purchases),
        ):
            bucket[k] += v
    return {
        "key": key,
        "title": sc["title"],
        "pairs_store": sc["pairs_store"],
        "pairs_online": sc["pairs_online"],
        "rows": rows,
        "totals": {k: q0(v) for k, v in total.items()},
        "totals_y2": {k: q0(v) for k, v in total_y2.items()},
        "avg_month_revenue": q0(total["revenue"] / months),
        "avg_month_net": q0(total["net"] / months),
        "gross_margin_pct": pct(total["gross"], total["revenue"]),
        "payback_month": payback_month,
        "peak_funding_need": q0(-peak_need),
        "cumulative_end": q0(cumulative),
        "gp_pair": q0(gp_pair),
        "horizon": horizon,
        "break_even_pairs": q0(
            (fixed + patent_month_net)
            / (
                gp_pair
                + price * ACCESSORIES_SHARE * D("0.55")
                - price * (ACQUIRING_RATE + LOSSES_RATE)
            )
        ),
    }


scenario_results = {k: run_scenario(k) for k in SCENARIOS}
base = scenario_results["base"]
be_pairs = D(base["break_even_pairs"])
be_revenue = be_pairs * AVG_PRICE * (1 + ACCESSORIES_SHARE)

# --------------------------------------------------------------------------- 9. Sensitivity (base scenario, 12 months)
SENSITIVITY = [
    ("Базовый сценарий", run_scenario("base")),
    ("Цена −10 %", run_scenario("base", price=(AVG_PRICE * D("0.9")).quantize(D("1")))),
    ("Продажи −20 %", run_scenario("base", sales_multiplier=D("0.8"))),
    ("Продажи +20 %", run_scenario("base", sales_multiplier=D("1.2"))),
    (
        "Курс USD/RUB +10 % (закупка +8 %)",
        run_scenario("base", landed_repeat=(LANDED_REPEAT * D("1.08")).quantize(D("0.01"))),
    ),
    (
        "Стрит-ритейл 1-я линия, 40 м² × 1 700 ₽ (аренда 68 000 ₽)",
        run_scenario("base", rent=D(68000)),
    ),
    (
        "Карго вместо белой схемы (риск изъятия/маркировки)",
        run_scenario("base", landed_repeat=LANDED_CARGO),
    ),
    (
        "Два наёмных продавца (владелец не работает в зале)",
        run_scenario("base", extra_fixed=seller_cost),
    ),
    ("Маркетинг 20 000 ₽/мес после запуска", run_scenario("base", extra_fixed=D(-10000))),
]

# --------------------------------------------------------------------------- 10. Rental options (Tyumen, Sept 2026 listings)
RENT_OPTIONS = [
    {
        "address": "ТРЦ «Премьер», ул. 50 лет ВЛКСМ, 63 (павильон)",
        "area": 35,
        "rent": 30000,
        "district": "Восточный округ, спальный массив",
        "source": "N1.ru",
        "plus": "самый дешёвый вариант с трафиком ТЦ; готовый павильон; парковка",
        "minus": "районный ТЦ — трафик ниже, чем у Кристалла/Гудвина",
        "score": "рекомендован (базовый вариант модели)",
    },
    {
        "address": "ул. 30 лет Победы, 7/5 (1-й этаж, стрит-ритейл)",
        "area": 68,
        "rent": 47740,
        "district": "Восточный-2, плотная жилая застройка",
        "source": "N1.ru",
        "plus": "700 ₽/м²; большая площадь — можно расширить ассортимент",
        "minus": "нужен ремонт и своя вывеска; трафик зависит от первой линии",
        "score": "альтернатива",
    },
    {
        "address": "ул. Домостроителей, 28 ст1",
        "area": 70,
        "rent": 35000,
        "district": "промзона, низкий пешеходный трафик",
        "source": "N1.ru",
        "plus": "500 ₽/м² — самая низкая ставка",
        "minus": "не подходит для розницы; вариант под склад/шоурум + онлайн",
        "score": "только как склад",
    },
    {
        "address": "ул. Михаила Сперанского, 17",
        "area": 81,
        "rent": 76950,
        "district": "новые кварталы (молодые семьи)",
        "source": "N1.ru",
        "plus": "950 ₽/м²; растущий район",
        "minus": "площадь избыточна для старта",
        "score": "на этап масштабирования",
    },
    {
        "address": "ул. Молодёжная, 80а ст1",
        "area": 46,
        "rent": 63912,
        "district": "Восточный округ",
        "source": "N1.ru",
        "plus": "1 374 ₽/м²; удобная площадь",
        "minus": "дороже базового варианта в 2 раза",
        "score": "запасной",
    },
    {
        "address": "ТЦ на въезде в спальный район (37 м²)",
        "area": 37,
        "rent": 46250,
        "district": "спальный район",
        "source": "ЦИАН",
        "plus": "1 250 ₽/м²; трафик ТЦ",
        "minus": "конкретный ТЦ уточнить",
        "score": "запасной",
    },
    {
        "address": "ул. Мельникайте, 100 (центр, 1-я линия)",
        "area": 66,
        "rent": 150000,
        "district": "центр",
        "source": "N1.ru",
        "plus": "высокий трафик, имиджевая локация",
        "minus": "2 272 ₽/м² — аренда съедает всю маржу на старте",
        "score": "не рекомендуется на старте",
    },
    {
        "address": "ТРЦ «Кристалл», павильон 35 м²",
        "area": 35,
        "rent": 120000,
        "district": "крупнейший ТРЦ города",
        "source": "ЦИАН/Альтера",
        "plus": "максимальный трафик",
        "minus": "3 430 ₽/м² + электричество; для бюджетного формата нерентабельно",
        "score": "не рекомендуется на старте",
    },
]
RENT_MARKET = [
    ("Стрит-ритейл 1-я линия, центр", "1 500 – 2 300 ₽/м²"),
    ("Стрит-ритейл в спальных районах", "700 – 1 400 ₽/м²"),
    ("Павильоны в районных ТЦ", "800 – 1 300 ₽/м²"),
    ("Павильоны в топовых ТРЦ (Кристалл, Гудвин, Колумб)", "2 500 – 3 500 ₽/м² + коммунальные"),
    ("Тематические/непрофильные центры (Премьер Дом, Нобель-Парк)", "600 – 800 ₽/м²"),
]

# --------------------------------------------------------------------------- 11. Marketing
MARKETING_LAUNCH = [
    (
        "2ГИС: приоритетное размещение + карточка (первые 2 мес.)",
        24000,
        "пакет ~12 000 ₽/мес, договор от 6 мес.",
    ),
    ("Яндекс Бизнес (Карты) — приоритет в выдаче", 12000, "~6 000 ₽/мес"),
    (
        "VK Реклама: гео-таргетинг Тюмень, 18–45, интересы «обувь/спорт»",
        15000,
        "CPM ~85 ₽ → ~175 000 показов, ~1 200 переходов",
    ),
    (
        "Telegram/VK-паблики Тюмени: 3–4 поста об открытии",
        12000,
        "«Новости Тюмени» от 1 800 ₽, «чат Тюмень» ~5 600 ₽/пост",
    ),
    ("Микроблогеры Тюмени (2 интеграции)", 8000, "3 000 – 5 000 ₽ за обзор"),
    ("Avito Pro: 20 объявлений с продвижением", 4000, "основной онлайн-канал для обуви в регионах"),
    ("Открытие: скидка −15 % первую неделю, розыгрыш пары в соцсетях", 0, "учтено в марже"),
    ("Печать: листовки в ТЦ и у входа, штендер", 0, "включено в оформление входа (CAPEX)"),
]
MARKETING_MONTHLY_PLAN = [
    ("2ГИС приоритет", 12000, "звонки/маршруты из карт — главный канал районного ТЦ"),
    ("VK Реклама (лиды на промо, ретаргетинг)", 8000, "~95 000 показов/мес"),
    ("Avito Pro + продвижение объявлений", 4000, "онлайн-продажи 15–20 % оборота"),
    ("Telegram/VK-паблики (1 пост в месяц)", 4000, "новинки сезона, акции"),
    (
        "CRM: WhatsApp/SMS-рассылки по базе покупателей",
        2000,
        "повторные покупки, программа лояльности",
    ),
]
MARKETING_KPI = [
    ("Стоимость перехода (VK/Директ)", "20 – 35 ₽"),
    ("Переходов в месяц (30 000 ₽ бюджета)", "≈ 1 000 – 1 300"),
    ("Конверсия перехода в визит магазина", "8 – 12 %"),
    ("Визитов из рекламы в месяц", "≈ 100 – 150"),
    ("Конверсия визита в покупку", "25 – 35 % (у пришедших целевых)"),
    ("Покупок из рекламы в месяц", "≈ 30 – 45"),
    ("CAC (стоимость привлечённой покупки)", f"≈ {rub(D(30000) / 38)} ₽ при 38 покупках"),
    (
        "ROMI при марже " + rub(GP_PER_PAIR) + " ₽/пара",
        f"≈ {q0((GP_PER_PAIR * 38 - 30000) / 30000 * 100)} %",
    ),
]
MARKETING_CALENDAR = [
    (
        "Недели −4…−1",
        "Карточки в 2ГИС/Яндекс Картах, группа VK и канал Telegram, съёмка ассортимента, анонс открытия в пабликах",
    ),
    (
        "Неделя 1",
        "Открытие: −15 % на всё, розыгрыш пары, посты у блогеров, VK-таргет на радиус 3 км от ТЦ",
    ),
    (
        "Недели 2–4",
        "Ретаргетинг посетителей группы, отзывы в 2ГИС (бонус за отзыв), Avito-объявления по каждой модели",
    ),
    (
        "Месяц 2",
        "Программа лояльности (5 % бонусами), рассылка по базе, коллаборация с фитнес-клубом/школой района",
    ),
    ("Месяц 3", "Сезонная кампания «демисезон», анализ каналов по CAC, перераспределение бюджета"),
]

# --------------------------------------------------------------------------- 12. Timeline, legal, risks
TIMELINE = [
    (
        "Неделя 1",
        "Регистрация ИП (ОКВЭД 47.72), заявление на патент, расчётный счёт, УКЭП; бронирование павильона",
    ),
    (
        "Неделя 1–2",
        "Договор аренды (11 мес., каникулы на ремонт), выбор моделей у поставщика, образцы, предоплата 30 %",
    ),
    (
        "Неделя 2–3",
        "Регистрация в Честном ЗНАКе, заказ кодов; оформление декларации ТР ТС 017/2011 через ОсОО-импортёра",
    ),
    (
        "Неделя 2–5",
        "Ремонт павильона, заказ и монтаж оборудования, вывески, ККТ, эквайринг, видеонаблюдение",
    ),
    (
        "Неделя 2–7",
        "Производство и доставка партии: Гуанчжоу → Бишкек → Тюмень (22–33 дня), таможня в КР, нанесение кодов",
    ),
    (
        "Неделя 6–7",
        "Найм и обучение продавца, настройка учёта, приёмка товара, ценники, фотосъёмка",
    ),
    (
        "Неделя 7",
        "Уведомление Роспотребнадзора, уголок потребителя, тест-запуск, посты об открытии",
    ),
    ("Неделя 8", "Открытие магазина"),
]
LEGAL = [
    ("Форма бизнеса", "ИП, ОКВЭД 47.72 (розничная торговля обувью и изделиями из кожи)"),
    (
        "Налоговый режим",
        f"Патент (ПСН): ПВД 80 000 ₽/м² торгового зала × {STORE['sales_area_m2']} м² × 6 % = {q0(patent_year)} ₽/год; уменьшается на взносы до 50 %. Лимит выручки 20 млн ₽/год. Резерв — УСН 6 %",
    ),
    ("Касса", "ККТ с ФН, ОФД, эквайринг + СБП; чек с кодом маркировки"),
    (
        "Маркировка",
        "Честный ЗНАК обязателен для всей обуви: регистрация, УКЭП, 2D-сканер, вывод из оборота при продаже",
    ),
    (
        "Подтверждение соответствия",
        "Декларация ТР ТС 017/2011 на импортируемую обувь (оформляет импортёр); хранить копии в магазине",
    ),
    (
        "Импорт",
        "Белая схема через ОсОО в Бишкеке (ЕАЭС): пошлина 0,47 €/пара, НДС КР 12 %, ввозной НДС РФ 22 % по заявлению о ввозе",
    ),
    (
        "Роспотребнадзор",
        "Уведомление о начале розничной торговли; уголок потребителя, книга отзывов, правила возврата",
    ),
    (
        "Персонал",
        "1 наёмный продавец на старте (трудовой договор, график 2/2 с владельцем), СОУТ рабочего места, инструктажи по ОТ и пожарной безопасности; второй продавец — при выручке выше 700 000 ₽/мес",
    ),
    (
        "Аренда",
        "Договор 11 месяцев с пролонгацией, индексация не выше 7 %/год, арендные каникулы на ремонт, право на вывеску",
    ),
]
RISKS = [
    (
        "Низкий трафик районного ТЦ",
        "средняя",
        "тест 3 месяца; онлайн-канал Avito/VK; переезд на стрит-ритейл при выручке < точки безубыточности 2 месяца подряд",
    ),
    (
        "Сезонность (январь–февраль, июнь–июль −20…−25 %)",
        "высокая",
        "сезонная матрица, распродажи остатков, предзаказы, накопление кэша к низкому сезону",
    ),
    (
        "Курс USD/RUB и стоимость логистики",
        "средняя",
        "валютный буфер 2,5 % в цене закупки, заказы 4 раза в год, фиксация цен с поставщиком",
    ),
    (
        "Таможня/маркировка (изъятие товара без документов)",
        "высокая для карго",
        "только белая схема; коды Честного ЗНАКа до ввоза в РФ",
    ),
    (
        "Неликвид (неудачные модели/размеры)",
        "средняя",
        "первая партия — проверенные модели, глубина 6–8 размеров, распродажа через Avito",
    ),
    (
        "Конкуренция с маркетплейсами и сетями",
        "средняя",
        "примерка и обмен на месте, локальный сервис, цена ниже сетей на 15–20 %",
    ),
    (
        "Кассовые разрывы перед закупками",
        "средняя",
        "резерв 2 месяца OPEX, заказ частями, отсрочка от поставщика после 2-й партии",
    ),
]

SOURCES = [
    (
        "N1.ru — объявления об аренде торговых помещений в Тюмени (сентябрь 2026)",
        "https://tumen.n1.ru/snyat/kommercheskaya/type-torgovye-ploschadi/",
    ),
    (
        "Коммерческая.RU — ставки ТЦ Тюмени (Премьер Дом, Нобель-Парк, Остров)",
        "https://www.kommercheskaya.ru/tmn_retail_rent",
    ),
    ("ЦИАН — торговые площади Тюмени", "https://tyumen.cian.ru/snyat-torgovuyu-ploshad/"),
    (
        "ТРЦ Премьер, 50 лет ВЛКСМ, 63 — карточка ТЦ",
        "https://shopandmall.ru/torgovye-centry/premer-tyumen-ul_50_let_vlksm_63",
    ),
    (
        "ТРЦ Кристалл — арендные условия",
        "https://tyumen.cian.ru/torgovo-razvlekatelnyy-centr-kristall-tyumen-98133/",
    ),
    (
        "Закон Тюменской области №96 от 27.11.2012 о ПСН (ПВД по розничной торговле)",
        "https://www.klerk.ru/doc/303448/",
    ),
    ("ФНС: калькулятор патента", "https://patent.nalog.ru/info/"),
    (
        "Патент 2026: лимит 20 млн ₽, условия для розницы",
        "https://www.moedelo.org/club/nalogovyj-uchet/patent-dla-roznicnoj-torgovli-v-2026-godu-cto-izmenitsa-i-kak-rabotat-s-limitom-20-mln",
    ),
    (
        "Зарплата продавца-консультанта в Тюмени 2026",
        "https://tumen.gorodrabot.ru/salaries/prodavec-konsultant",
    ),
    ("Тюменьстат: средняя зарплата 2025", "https://72.ru/text/gorod/2026/02/25/76281415/"),
    (
        "Медианная зарплата в Тюмени 76 тыс. ₽ (февраль 2026)",
        "https://abnews.ru/ural/news/tyumen/2026/2/21/v-tyumeni-mediannaya-zarplata-dostigla-76-tysyach-rublej",
    ),
    ("Население Тюмени 2026 — прогноз 884 тыс.", "https://72.ru/text/gorod/2026/02/19/76267161/"),
    ("Оборот розницы Тюменской области +5,7 % (2026)", "https://tmn.aif.ru/society/6325245"),
    (
        "Сколько пар обуви покупают россияне в год (опрос)",
        "https://novard.ru/news/rossiyane-rasskazali-skolko-obuvi-pokupayut-v-god",
    ),
    (
        "Продажи обуви 2025: +35 % пар, 564 млрд ₽ за 8 мес.",
        "https://www.osnmedia.ru/ekonomika/prodazhi-obuvi-v-rossii-vyrosli-na-tret-a-tseny-snizilis-na-4/",
    ),
    (
        "Кроссовки и кеды: 16 млн пар в 2025",
        "https://www.retail.ru/news/v-2025-godu-rossiyane-kupili-rekordnoe-kolichestvo-obuvi-bez-kabluka-26-yanvarya-2026-273771/",
    ),
    (
        "Обувь подорожала на 59 % за 3 года, +6–9 % в 2025",
        "https://www.moysklad.ru/poleznoe/statyi/za-tri-goda-obuv-v-rf-podorozhala-na-59-a-odezhda-na-36/",
    ),
    (
        "Экономия на одежде и обуви в 2026 (−11 % продаж)",
        "https://78.ru/news/2026-03-20/prodazhi-odezhdi-i-obuvi-v-rossii-upali-na-11",
    ),
    (
        "Стоимость открытия обувного магазина (бенчмарки)",
        "https://pos-center.ru/journal/kak-otkryt-obuvnoy-magazin-sovety-dlya-nachinayushchih-s-nulya-i-opytnyh-predprinimateley/",
    ),
    ("Ремонт коммерческих помещений 2025: 9–20 тыс. ₽/м²", "https://sknebo.ru/remont-magazina/"),
    (
        "Онлайн-кассы Эвотор/АТОЛ, ФН 36 мес — цены",
        "https://online-kassa.ru/kupit/cat/kassa-evotor/",
    ),
    (
        "Средняя цена клика в Яндекс Директ 2025",
        "https://www.demis.ru/articles/skolko-stoit-klik-v-yandeks-direkt/",
    ),
    (
        "CPM VK Ads Q2 2025 — 85,54 ₽",
        "https://blog.click.ru/analytics/issledovanie-klyuchevyh-pokazateley-internet-reklamy/",
    ),
    (
        "Реклама в 2ГИС: пакеты ~20 000 ₽/мес, срок от 6 мес.",
        "https://blog.click.ru/target/vse-o-reklame-v-2gis/",
    ),
    ("Билборды 3×6 в Тюмени от 15 000 ₽/мес", "https://linasee.com/tyumen/reklama-na-bilbordah/"),
    ("Telegram-паблики Тюмени: цены постов", "https://telega.in/channels/tyumen_gruppa/card"),
    (
        "Комиссии Wildberries/Ozon на обувь 2026",
        "https://bidline.ru/blog/komissiya-wildberries-2026",
    ),
]


def route_brief(r: Any) -> dict[str, str]:
    return {
        "name": r.route_name,
        "clearance": r.clearance_type.value,
        "per_unit": str(r.cost_per_unit_rub),
        "total": str(r.total_cost_rub),
        "days": f"{r.estimated_days_min}–{r.estimated_days_max}",
        "risk": r.risk_level.value,
        "duty": str(r.breakdown["customs_duty"]),
        "vat_kg": str(r.breakdown["import_vat_kg"]),
        "vat_ru": str(r.breakdown["import_vat_ru"]),
        "freight": str(r.breakdown["international_freight"] + r.breakdown["local_transport"]),
        "marking": str(r.breakdown["marking_fee"]),
        "cert": str(r.breakdown["certification_fee"]),
    }


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "reports/business_case_data.json")
    market_pairs_per_capita = D("2.4")
    market_avg_price = D(3500)
    population = D(884235)
    market_value = population * market_pairs_per_capita * market_avg_price
    sneakers_share = D("0.30")
    data = {
        "meta": {
            "generated": date.today().isoformat(),
            "fx_as_of": first.fx_as_of.isoformat(),
            "opening": STORE["opening_month"],
        },
        "store": {k: (str(v) if isinstance(v, Decimal) else v) for k, v in STORE.items()},
        "market": {
            "population": q0(population),
            "avg_salary_region": "94 124",
            "median_salary_city": "76 000",
            "retail_growth": "+5,7 %",
            "pairs_per_capita": str(market_pairs_per_capita).replace(".", ","),
            "avg_price": q0(market_avg_price),
            "market_value": q0(market_value),
            "sneakers_value": q0(market_value * sneakers_share),
            "target_share_pct": "0,3",
            "target_revenue_year": q0(market_value * sneakers_share * D("0.003")),
            "competitors": [
                ("Kari", "ТРЦ Колумб и др.", "масс-маркет, 1 500 – 4 000 ₽, широкая сеть"),
                ("Zenden", "несколько магазинов", "средний сегмент 3 000 – 7 000 ₽"),
                ("Respect", "ТЦ Галерея Вояж", "средний+, кожаная обувь 5 000 – 12 000 ₽"),
                ("Rendez-Vous", "ТРЦ Кристалл", "премиум, бренды 8 000 – 25 000 ₽"),
                (
                    "Спортмастер, Kixbox, бренд-бутики",
                    "Кристалл, Гудвин, Колумб",
                    "брендовые кроссовки 6 000 – 18 000 ₽",
                ),
                (
                    "Wildberries / Ozon / Lamoda",
                    "ПВЗ в каждом районе",
                    "главный конкурент по цене; нет примерки, возвраты 30–40 %",
                ),
                (
                    "Рынки и «стоки»",
                    "Восточный округ, рынок на Пермякова",
                    "no-name обувь 1 000 – 3 000 ₽, без чеков и маркировки",
                ),
            ],
            "positioning": "Ниша между рынками и сетями: проверенные модели 3 990 – 6 490 ₽ с примеркой, обменом и гарантией, собственный импорт даёт цену на 15–20 % ниже сетей при легальном товаре с маркировкой.",
        },
        "purchase": {
            "pairs": FIRST_ORDER_PAIRS,
            "fob_avg_usd": str(AVG_FOB_USD),
            "weight_kg": str(KG_PER_PAIR * FIRST_ORDER_PAIRS),
            "volume_m3": str(M3_PER_PAIR * FIRST_ORDER_PAIRS),
            "landed_first": str(LANDED_FIRST),
            "landed_repeat": str(LANDED_REPEAT),
            "landed_cargo": str(LANDED_CARGO),
            "white_first": route_brief(white_first),
            "white_repeat": route_brief(white_repeat),
            "cargo": route_brief(cargo_first),
            "routes": [route_brief(r) for r in first.routes],
            "wholesale_benchmark": "2 300 – 3 200 ₽/пара у московских оптовиков (Садовод, Южные ворота) за аналогичные модели",
        },
        "pricing": {
            "avg_price": q0(AVG_PRICE),
            "markup": str(TARGET_MARKUP),
            "gp_pair": q0(GP_PER_PAIR),
            "gross_margin_pct": pct(GP_PER_PAIR, AVG_PRICE),
            "ladder": PRICE_LADDER,
            "accessories_share": "4",
            "acquiring": "1,5",
            "losses": "1",
        },
        "payroll": {
            "seller_gross": q0(SELLER_GROSS),
            "seller_cost": q0(seller_cost),
            "seller_contrib": q0(seller_contrib),
            "mrot": q0(MROT_2026),
            "ip_fixed": q0(IP_FIXED_CONTRIBUTIONS_2026),
        },
        "taxes": {
            "patent_year": q0(patent_year),
            "patent_month_gross": q0(patent_month_gross),
            "patent_month_net": q0(patent_month_net),
            "pvd_m2": q0(PATENT_PVD_PER_M2),
            "sales_area": str(STORE["sales_area_m2"]),
            "usn_alt_month": q0(D(base["avg_month_revenue"]) * USN_RATE),
            "ip_extra_1pct": q0(IP_EXTRA_1PCT),
        },
        "capex": {
            "items": [(n, q0(v), c) for n, v, c in CAPEX],
            "subtotal": q0(capex_subtotal),
            "contingency": q0(CONTINGENCY),
            "total": q0(capex_total),
        },
        "opex": {
            "items": [(n, q0(v), c) for n, v, c in OPEX_FIXED],
            "fixed_total": q0(opex_fixed_total),
            "variable_note": "эквайринг 1,5 % + потери/уценки 1 % от выручки",
        },
        "scenarios": scenario_results,
        "break_even": {
            "pairs": q0(be_pairs),
            "pairs_per_day": q1(be_pairs / 30),
            "revenue": q0(be_revenue),
        },
        "sensitivity": [
            {
                "title": t,
                "revenue": r["totals"]["revenue"],
                "net": r["totals"]["net"],
                "avg_net": r["avg_month_net"],
                "payback": r["payback_month"],
                "peak": r["peak_funding_need"],
            }
            for t, r in SENSITIVITY
        ],
        "rent_options": RENT_OPTIONS,
        "rent_market": RENT_MARKET,
        "marketing": {
            "launch": MARKETING_LAUNCH,
            "launch_total": q0(sum(v for _, v, _ in MARKETING_LAUNCH)),
            "monthly": MARKETING_MONTHLY_PLAN,
            "monthly_total": q0(sum(v for _, v, _ in MARKETING_MONTHLY_PLAN)),
            "kpi": MARKETING_KPI,
            "calendar": MARKETING_CALENDAR,
        },
        "timeline": TIMELINE,
        "legal": LEGAL,
        "risks": RISKS,
        "sources": SOURCES,
        "funding": {
            "capex": q0(capex_total),
            "peak_base": base["peak_funding_need"],
            "peak_pess": scenario_results["pessimistic"]["peak_funding_need"],
            "recommended": q0(D(scenario_results["pessimistic"]["peak_funding_need"]) * D("1.05")),
        },
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"wrote {out}")
    print(
        f"landed first/repeat/cargo: {LANDED_FIRST} / {LANDED_REPEAT} / {LANDED_CARGO} ₽/pair | price {AVG_PRICE} | GP {GP_PER_PAIR}"
    )
    print(
        f"CAPEX {capex_total} | fixed OPEX {opex_fixed_total} | patent/month {patent_month_gross} | seller cost {seller_cost}"
    )
    for k, r in scenario_results.items():
        print(
            f"{k:<12} rev/mo {r['avg_month_revenue']:>9} net/mo {r['avg_month_net']:>8} payback {r['payback_month']} peak need {r['peak_funding_need']} BE pairs {r['break_even_pairs']}"
        )


if __name__ == "__main__":
    main()
