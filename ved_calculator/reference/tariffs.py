"""TN VED (ТН ВЭД ЕАЭС) tariff matrix for the key import categories.

The EAEU applies one Common Customs Tariff (ЕТТ ЕАЭС, Решение Совета ЕЭК №80 от
17.08.2021 с изменениями), so the *duty* rate is identical whether the goods are
declared in Bishkek or in Moscow; the jurisdictions differ in VAT (12% KG vs
22% RU), customs processing fees, broker fees and non-tariff requirements.

Entries with ``verified=True`` were cross-checked against published ЕТТ listings
(alta.ru, tws.by, brokerpro/kodtnved) while compiling this table.  Entries with
``verified=False`` are indicative and are flagged in calculation notes.
Always confirm the 10-digit line with a licensed broker before declaring.
"""

from __future__ import annotations

from decimal import Decimal

from ved_calculator.domain.models import (
    CargoCategory,
    DutyRateType,
    SpecificRateUnit,
    TariffEntry,
    TariffMatrix,
)

_F = CargoCategory.FOOTWEAR
_A = CargoCategory.APPAREL
_E = CargoCategory.ELECTRONICS
_G = CargoCategory.GENERAL
_AV = DutyRateType.AD_VALOREM
_SP = DutyRateType.SPECIFIC
_CB = DutyRateType.COMBINED_MAX
_KG = SpecificRateUnit.KG
_PAIR = SpecificRateUnit.PAIR
_PIECE = SpecificRateUnit.PIECE

CERT_LIGHT_INDUSTRY = "ТР ТС 017/2011 — декларация о соответствии (лёгкая промышленность)"
CERT_ELECTRONICS = "ТР ТС 020/2011 (ЭМС), ТР ТС 004/2011 (низковольтное оборудование)"
CERT_TELECOM = "ТР ТС 020/2011, ТР ЕАЭС 037/2016; нотификация ФСБ (шифровальные средства)"
CERT_TOYS = "ТР ТС 008/2011 — сертификат соответствия (игрушки)"
CERT_FOOD_CONTACT = "ТР ТС 005/2011 (упаковка) / гос. регистрация (посуда)"

TARIFF_ENTRIES: tuple[TariffEntry, ...] = (
    # ------------------------------------------------------------------ footwear
    TariffEntry(
        hs_code="6404110000",
        description_ru="Обувь спортивная (кроссовки), верх из текстиля, подошва резина/пластмасса",
        description_en="Sports footwear with textile uppers and rubber/plastic soles (sneakers)",
        category=_F,
        rate_type=_SP,
        specific_rate_eur=Decimal("0.47"),
        specific_unit=_PAIR,
        marking_required=True,
        certification_scheme=CERT_LIGHT_INDUSTRY,
        is_category_default=True,
        verified=True,
        source="ЕТТ ЕАЭС 6404 11 000 0 — 0,47 евро за пару (tws.by)",
    ),
    TariffEntry(
        hs_code="6403999600",
        description_ru="Обувь мужская с верхом из натуральной кожи, прочая (стелька ≥ 24 см)",
        description_en="Men's footwear with leather uppers, other",
        category=_F,
        rate_type=_SP,
        specific_rate_eur=Decimal("1.25"),
        specific_unit=_PAIR,
        marking_required=True,
        certification_scheme=CERT_LIGHT_INDUSTRY,
        verified=True,
        source="ЕТТ ЕАЭС 6403 99 960 0 — 1,25 евро за пару (tws.by)",
    ),
    TariffEntry(
        hs_code="640299",
        description_ru="Обувь с верхом из полимерных материалов, прочая (кроссовки из ПУ/ЭВА)",
        description_en="Footwear with plastic/PU uppers, other",
        category=_F,
        rate_type=_SP,
        specific_rate_eur=Decimal("0.34"),
        specific_unit=_PAIR,
        marking_required=True,
        certification_scheme=CERT_LIGHT_INDUSTRY,
        verified=False,
        source="Indicative: chapter 64 specific rates span 0,34–1,5 евро за пару",
    ),
    # ------------------------------------------------------------------ apparel
    TariffEntry(
        hs_code="620342",
        description_ru="Брюки/джинсы мужские из хлопчатобумажной пряжи",
        description_en="Men's cotton trousers / jeans",
        category=_A,
        rate_type=_CB,
        ad_valorem_percent=Decimal("10"),
        specific_rate_eur=Decimal("1.88"),
        specific_unit=_KG,
        marking_required=True,
        certification_scheme=CERT_LIGHT_INDUSTRY,
        is_category_default=True,
        verified=True,
        source="ЕТТ ЕАЭС 6203 42 — 10%, но не менее 1,88 евро за кг (alta.ru)",
    ),
    TariffEntry(
        hs_code="620462",
        description_ru="Брюки/джинсы женские из хлопчатобумажной пряжи",
        description_en="Women's cotton trousers / jeans",
        category=_A,
        rate_type=_CB,
        ad_valorem_percent=Decimal("10"),
        specific_rate_eur=Decimal("1.88"),
        specific_unit=_KG,
        marking_required=True,
        certification_scheme=CERT_LIGHT_INDUSTRY,
        verified=True,
        source="ЕТТ ЕАЭС 6204 62 — 10%, но не менее 1,88 евро за кг (alta.ru)",
    ),
    TariffEntry(
        hs_code="6109100000",
        description_ru="Футболки трикотажные из хлопчатобумажной пряжи",
        description_en="Cotton knitted T-shirts",
        category=_A,
        rate_type=_SP,
        specific_rate_eur=Decimal("1.75"),
        specific_unit=_KG,
        marking_required=True,
        certification_scheme=CERT_LIGHT_INDUSTRY,
        verified=True,
        source="ЕТТ ЕАЭС 6109 10 000 0 — 1,75 евро за кг (alta.ru)",
    ),
    TariffEntry(
        hs_code="611020",
        description_ru="Свитеры, худи, пуловеры трикотажные из хлопчатобумажной пряжи",
        description_en="Cotton knitted sweaters / hoodies",
        category=_A,
        rate_type=_SP,
        specific_rate_eur=Decimal("1.75"),
        specific_unit=_KG,
        marking_required=True,
        certification_scheme=CERT_LIGHT_INDUSTRY,
        verified=True,
        source="ЕТТ ЕАЭС 6110 20 — 1,75 евро за кг (alta.ru)",
    ),
    TariffEntry(
        hs_code="611030",
        description_ru="Свитеры, худи, пуловеры трикотажные из химических нитей",
        description_en="Synthetic knitted sweaters / hoodies",
        category=_A,
        rate_type=_SP,
        specific_rate_eur=Decimal("1.75"),
        specific_unit=_KG,
        marking_required=True,
        certification_scheme=CERT_LIGHT_INDUSTRY,
        verified=True,
        source="ЕТТ ЕАЭС 6110 30 — 1,75 евро за кг (alta.ru)",
    ),
    TariffEntry(
        hs_code="6201",
        description_ru="Пальто, куртки, анораки, ветровки мужские (кроме шерстяных)",
        description_en="Men's coats, jackets, anoraks (non-wool)",
        category=_A,
        rate_type=_CB,
        ad_valorem_percent=Decimal("10"),
        specific_rate_eur=Decimal("2.25"),
        specific_unit=_KG,
        marking_required=True,
        certification_scheme=CERT_LIGHT_INDUSTRY,
        verified=True,
        source="ЕТТ ЕАЭС 6201 — 10%, но не менее 2,25 евро за кг (alta.ru)",
    ),
    TariffEntry(
        hs_code="6202",
        description_ru="Пальто, куртки, анораки, ветровки женские (кроме шерстяных)",
        description_en="Women's coats, jackets, anoraks (non-wool)",
        category=_A,
        rate_type=_CB,
        ad_valorem_percent=Decimal("10"),
        specific_rate_eur=Decimal("2.25"),
        specific_unit=_KG,
        marking_required=True,
        certification_scheme=CERT_LIGHT_INDUSTRY,
        verified=True,
        source="ЕТТ ЕАЭС 6202 — 10%, но не менее 2,25 евро за кг (alta.ru)",
    ),
    TariffEntry(
        hs_code="6205",
        description_ru="Рубашки мужские",
        description_en="Men's shirts",
        category=_A,
        rate_type=_SP,
        specific_rate_eur=Decimal("1.75"),
        specific_unit=_KG,
        marking_required=True,
        certification_scheme=CERT_LIGHT_INDUSTRY,
        verified=True,
        source="ЕТТ ЕАЭС 6205 — 1,75 евро за кг (alta.ru)",
    ),
    TariffEntry(
        hs_code="620630",
        description_ru="Блузки женские из хлопчатобумажной пряжи",
        description_en="Women's cotton blouses",
        category=_A,
        rate_type=_CB,
        ad_valorem_percent=Decimal("10"),
        specific_rate_eur=Decimal("1.5"),
        specific_unit=_KG,
        marking_required=True,
        certification_scheme=CERT_LIGHT_INDUSTRY,
        verified=True,
        source="ЕТТ ЕАЭС 6206 30 — 10%, но не менее 1,5 евро за кг (alta.ru)",
    ),
    TariffEntry(
        hs_code="6104",
        description_ru="Костюмы, платья, юбки женские трикотажные",
        description_en="Women's knitted suits, dresses, skirts",
        category=_A,
        rate_type=_CB,
        ad_valorem_percent=Decimal("10"),
        specific_rate_eur=Decimal("1.88"),
        specific_unit=_KG,
        marking_required=True,
        certification_scheme=CERT_LIGHT_INDUSTRY,
        verified=False,
        source="Indicative: 6104 lines range 2,2 евро/кг … 10%, но не менее 1,88 евро/кг",
    ),
    TariffEntry(
        hs_code="6115",
        description_ru="Чулочно-носочные изделия",
        description_en="Hosiery, socks",
        category=_A,
        rate_type=_AV,
        ad_valorem_percent=Decimal("10"),
        certification_scheme=CERT_LIGHT_INDUSTRY,
        verified=False,
        source="Indicative: 6115 lines range 5–13% ad valorem",
    ),
    # ------------------------------------------------------------------ electronics
    TariffEntry(
        hs_code="",
        description_ru="Бытовая электроника и гаджеты (категория по умолчанию)",
        description_en="Consumer electronics & gadgets (category default)",
        category=_E,
        rate_type=_AV,
        ad_valorem_percent=Decimal("5"),
        certification_scheme=CERT_ELECTRONICS,
        is_category_default=True,
        verified=False,
        source="Synthetic conservative default; ITA lines (phones, laptops, batteries) are 0%",
    ),
    TariffEntry(
        hs_code="8517130000",
        description_ru="Смартфоны",
        description_en="Smartphones",
        category=_E,
        rate_type=_AV,
        ad_valorem_percent=Decimal("0"),
        certification_scheme=CERT_TELECOM,
        ru_technology_fee_rub_per_unit=Decimal("373"),
        verified=True,
        source="ЕТТ ЕАЭС 8517 13 000 0 — 0%; техсбор 373 ₽/шт с 01.12.2026",
    ),
    TariffEntry(
        hs_code="8471300000",
        description_ru="Ноутбуки и планшеты с клавиатурой (портативные вычислительные машины)",
        description_en="Laptops / tablets with keyboard",
        category=_E,
        rate_type=_AV,
        ad_valorem_percent=Decimal("0"),
        certification_scheme=CERT_TELECOM,
        ru_technology_fee_rub_per_unit=Decimal("746"),
        verified=True,
        source="ЕТТ ЕАЭС 8471 30 000 0 — 0%; техсбор 746 ₽/шт с 01.12.2026",
    ),
    TariffEntry(
        hs_code="8507600000",
        description_ru="Аккумуляторы литий-ионные (в т.ч. power bank)",
        description_en="Lithium-ion accumulators (incl. power banks)",
        category=_E,
        rate_type=_AV,
        ad_valorem_percent=Decimal("0"),
        certification_scheme=CERT_ELECTRONICS,
        verified=True,
        source="ЕТТ ЕАЭС 8507 60 000 0 — 0% (alta.ru/tws.by)",
    ),
    TariffEntry(
        hs_code="8517620009",
        description_ru="Смарт-часы и прочая аппаратура для приёма/передачи данных",
        description_en="Smart watches and other data transmission apparatus",
        category=_E,
        rate_type=_AV,
        ad_valorem_percent=Decimal("0"),
        certification_scheme=CERT_TELECOM,
        verified=True,
        source="ЕТТ ЕАЭС 8517 62 000 9 — 0% (tws.by)",
    ),
    TariffEntry(
        hs_code="8518309500",
        description_ru="Наушники и гарнитуры",
        description_en="Headphones and headsets",
        category=_E,
        rate_type=_AV,
        ad_valorem_percent=Decimal("5"),
        certification_scheme=CERT_ELECTRONICS,
        verified=True,
        source="ЕТТ ЕАЭС 8518 30 950 0 — 5% (brokerpro.ru / kodtnved.ru)",
    ),
    TariffEntry(
        hs_code="852872",
        description_ru="Телевизоры цветного изображения",
        description_en="Colour television receivers",
        category=_E,
        rate_type=_CB,
        ad_valorem_percent=Decimal("10"),
        specific_rate_eur=Decimal("25.5"),
        specific_unit=_PIECE,
        certification_scheme=CERT_ELECTRONICS,
        verified=True,
        source="ЕТТ ЕАЭС 8528 72 — 10%, но не менее 25,5 евро за шт (Решение ЕЭК)",
    ),
    # ------------------------------------------------------------------ homeware & general
    TariffEntry(
        hs_code="",
        description_ru="Товары для дома и прочие потребительские товары (категория по умолчанию)",
        description_en="Homeware & general merchandise (category default)",
        category=_G,
        rate_type=_AV,
        ad_valorem_percent=Decimal("10"),
        certification_scheme="ТР ТС по виду товара (декларация/сертификат) либо отказное письмо",
        is_category_default=True,
        verified=False,
        source="Synthetic default: most ЕТТ homeware lines are 5–15% ad valorem",
    ),
    TariffEntry(
        hs_code="3924100000",
        description_ru="Посуда столовая и кухонная из пластмасс",
        description_en="Plastic tableware and kitchenware",
        category=_G,
        rate_type=_AV,
        ad_valorem_percent=Decimal("6.5"),
        certification_scheme=CERT_FOOD_CONTACT,
        verified=True,
        source="ЕТТ ЕАЭС 3924 10 000 0 — 6,5% (alta.ru / aived.pro)",
    ),
    TariffEntry(
        hs_code="9503007000",
        description_ru="Игрушки в наборах или комплектах, прочие",
        description_en="Toys in sets, other",
        category=_G,
        rate_type=_AV,
        ad_valorem_percent=Decimal("10"),
        certification_scheme=CERT_TOYS,
        verified=True,
        source="ЕТТ ЕАЭС 9503 00 700 0 — 10% (alta.ru)",
    ),
)

DEFAULT_TARIFF_MATRIX = TariffMatrix(entries=list(TARIFF_ENTRIES))

__all__ = ["DEFAULT_TARIFF_MATRIX", "TARIFF_ENTRIES"]
