#!/usr/bin/env node
/**
 * Render the Tyumen shoe-store business case (JSON from scripts/business_case_tyumen.py) into .docx.
 *
 *   NODE_PATH=<node_modules> node scripts/build_business_case_docx.js reports/business_case_data.json reports/Tyumen_shoe_store_business_case.docx
 */
"use strict";

const fs = require("fs");
const path = require("path");
const {
  AlignmentType, BorderStyle, Document, ExternalHyperlink, Footer, Header, HeadingLevel, LevelFormat,
  PageBreak, PageNumber, PageOrientation, Packer, Paragraph, ShadingType, Table, TableCell,
  TableLayoutType, TableRow, TextRun, VerticalAlign, WidthType,
} = require("docx");

const [, , inputPath = "reports/business_case_data.json", outputPath = "reports/Tyumen_shoe_store_business_case.docx"] = process.argv;
const data = JSON.parse(fs.readFileSync(inputPath, "utf8"));

const NBSP = " ";
function money(value, suffix = " ₽") {
  if (value === null || value === undefined || value === "") return "—";
  const s = String(value).replace(",", ".");
  if (!/^-?\d+(\.\d+)?$/.test(s)) return String(value);
  const n = Math.round(parseFloat(s));
  const negative = n < 0;
  const grouped = String(Math.abs(n)).replace(/\B(?=(\d{3})+(?!\d))/g, NBSP);
  return `${negative ? "−" : ""}${grouped}${suffix}`;
}
const num = (v) => money(v, "");
const ru = (v) => String(v).replace(".", ",");
function bigMoney(v) {
  const n = parseFloat(String(v).replace(",", "."));
  if (!isFinite(n)) return String(v);
  if (Math.abs(n) >= 1e9) return `${(n / 1e9).toFixed(1).replace(".", ",")} млрд ₽`;
  if (Math.abs(n) >= 1e6) return `${(n / 1e6).toFixed(1).replace(".", ",")} млн ₽`;
  return money(n);
}

const FONT = "Arial";
const PORTRAIT_WIDTH = 9638;
const LANDSCAPE_WIDTH = 14570;
const R = AlignmentType.RIGHT, C = AlignmentType.CENTER;

function run(text, o = {}) {
  return new TextRun({ text: String(text), font: FONT, size: o.size || 20, bold: !!o.bold, italics: !!o.italics, color: o.color });
}
function p(text, o = {}) {
  return new Paragraph({ children: Array.isArray(text) ? text : [run(text, o)], alignment: o.align || AlignmentType.LEFT, spacing: { before: o.before ?? 60, after: o.after ?? 80 } });
}
const h1 = (t) => new Paragraph({ text: t, heading: HeadingLevel.HEADING_1, spacing: { before: 360, after: 160 } });
const h2 = (t) => new Paragraph({ text: t, heading: HeadingLevel.HEADING_2, spacing: { before: 260, after: 120 } });
const h3 = (t) => new Paragraph({ text: t, heading: HeadingLevel.HEADING_3, spacing: { before: 200, after: 100 } });
function bullet(text, o = {}) {
  return new Paragraph({ children: Array.isArray(text) ? text : [run(text, o)], numbering: { reference: "bullets", level: 0 }, spacing: { before: 30, after: 30 } });
}
const pageBreak = () => new Paragraph({ children: [new PageBreak()] });

function table({ columns, rows, size = 17, headerFill = "D9E2F3" }) {
  const widths = columns.map((c) => c.width);
  const total = widths.reduce((a, b) => a + b, 0);
  const border = { style: BorderStyle.SINGLE, size: 4, color: "A6A6A6" };
  const borders = { top: border, bottom: border, left: border, right: border };
  const cell = (content, col, isHeader) => {
    const spec = typeof content === "object" && content !== null ? content : { text: content };
    const align = spec.align || (isHeader ? C : col.align || AlignmentType.LEFT);
    const lines = String(spec.text ?? "—").split("\n");
    return new TableCell({
      width: { size: col.width, type: WidthType.DXA }, borders, verticalAlign: VerticalAlign.CENTER,
      margins: { top: 40, bottom: 40, left: 70, right: 70 },
      shading: isHeader ? { type: ShadingType.CLEAR, fill: headerFill, color: "auto" } : spec.fill ? { type: ShadingType.CLEAR, fill: spec.fill, color: "auto" } : undefined,
      children: lines.map((line, i) => new Paragraph({ alignment: align, spacing: { before: 0, after: 0 }, children: [run(line, { size, bold: isHeader || !!spec.bold, italics: !!spec.italics && i > 0 })] })),
    });
  };
  return new Table({
    width: { size: total, type: WidthType.DXA }, columnWidths: widths, layout: TableLayoutType.FIXED,
    rows: [
      new TableRow({ tableHeader: true, children: columns.map((c) => cell(c.header, c, true)) }),
      ...rows.map((r) => new TableRow({ cantSplit: true, children: r.map((v, i) => cell(v, columns[i], false)) })),
    ],
  });
}
const kv = (pairs, w1 = 3600) => table({ columns: [{ header: "Показатель", width: w1 }, { header: "Значение", width: PORTRAIT_WIDTH - w1 }], rows: pairs.map(([k, v]) => [{ text: k, bold: true }, v]), size: 18 });

const S = data.scenarios, base = S.base, pess = S.pessimistic, opt = S.optimistic;
const RISK_RU = { LOW_LEGAL: "низкий (легально)", MEDIUM_TRANSIT: "средний", HIGH_CUSTOMS: "высокий (таможня)" };
const CLR_RU = { OFFICIAL_EAEU_KG: "белая растаможка в КР", CARGO_SIMPLIFIED: "карго", OFFICIAL_RU_DIRECT: "прямой импорт РФ" };

// ------------------------------------------------------------------ sections
function titlePage() {
  return [
    new Paragraph({ spacing: { before: 2200, after: 200 }, alignment: C, children: [run("Открытие обувного магазина в Тюмени", { size: 52, bold: true, color: "1F3864" })] }),
    new Paragraph({ spacing: { after: 200 }, alignment: C, children: [run("Бизнес-кейс: рынок, помещение, инвестиции, экономика, реклама, запуск", { size: 26 })] }),
    new Paragraph({ spacing: { after: 600 }, alignment: C, children: [run(data.store.name, { size: 22, italics: true })] }),
    new Paragraph({ alignment: C, children: [run(`Локация базового варианта: ${data.store.location}`, { size: 22 })] }),
    new Paragraph({ alignment: C, children: [run(`Плановое открытие: ${data.meta.opening}`, { size: 22 })] }),
    new Paragraph({ alignment: C, children: [run(`Дата расчёта: ${data.meta.generated} · курсы валют на ${data.meta.fx_as_of}`, { size: 22 })] }),
    new Paragraph({ spacing: { before: 1600 }, alignment: C, children: [run("Все цены и ставки — рыночные данные сентября 2026 г. по открытым источникам (объявления N1.ru/ЦИАН, Тюменьстат, ФНС, рекламные площадки) и расчёт закупки движком VED Calculator Core. Перед подписанием договоров цифры нужно подтвердить у арендодателя, брокера и поставщика.", { size: 18, italics: true, color: "595959" })] }),
    pageBreak(),
    new Paragraph({ children: [run("Содержание", { size: 32, bold: true, color: "1F3864" })], spacing: { after: 200 } }),
    ...TOC.map(([t, lvl]) => new Paragraph({ children: [run(t, { size: lvl ? 18 : 20, bold: !lvl })], spacing: { before: lvl ? 20 : 80, after: 20 }, indent: { left: lvl ? 540 : 0 } })),
  ];
}
const TOC = [
  ["1. Резюме проекта", 0], ["2. Рынок обуви Тюмени", 0], ["3. Концепция магазина и ассортимент", 0],
  ["4. Помещение: рынок аренды и дешёвый вариант", 0], ["5. Закупка и логистика (собственный импорт)", 0],
  ["6. Инвестиции на открытие (CAPEX)", 0], ["7. Ежемесячные расходы (OPEX)", 0], ["8. Ценообразование и юнит-экономика", 0],
  ["9. Финансовая модель: сценарии, P&L, денежный поток", 0], ["10. Точка безубыточности, окупаемость, чувствительность", 0],
  ["11. Реклама и маркетинг", 0], ["12. Юридические и организационные шаги", 0], ["13. План-график открытия", 0],
  ["14. Риски и меры", 0], ["15. Источники", 0],
];

function summary() {
  const f = data.funding;
  return [
    h1("1. Резюме проекта"),
    p(`Небольшой магазин кроссовок и повседневной обуви бюджетного и среднего сегмента с собственным импортом из Китая через ЕАЭС (Бишкек). Базовая локация — павильон 35 м² в районном ТРЦ «Премьер» (ул. 50 лет ВЛКСМ, 63) за ${money(data.store.rent_month)}/мес — самое дешёвое из найденных предложений с трафиком торгового центра. Магазин продаёт проверенные модели по ${money(data.pricing.avg_price)} в среднем при закупочной (полной) стоимости ${money(data.purchase.landed_repeat)}/пара, валовая маржа ${ru(data.pricing.gross_margin_pct)} %.`, { size: 20 }),
    kv([
      ["Инвестиции на открытие (CAPEX, включая первую партию 500 пар)", money(f.capex)],
      ["Рекомендуемый объём финансирования (пик потребности в кэше по пессимистичному сценарию +5 %)", money(f.recommended)],
      ["Аренда базового варианта", `${money(data.store.rent_month)}/мес (35 м², ТРЦ «Премьер»)`],
      ["Постоянные расходы в месяц (аренда, ФОТ, патент, маркетинг и пр.)", money(data.opex.fixed_total)],
      ["Точка безубыточности", `${num(data.break_even.pairs)} пар/мес (${ru(data.break_even.pairs_per_day)} пары в день), выручка ${money(data.break_even.revenue)}/мес`],
      ["Базовый сценарий: выручка / чистая прибыль в среднем за месяц", `${money(base.avg_month_revenue)} / ${money(base.avg_month_net)}`],
      ["Окупаемость инвестиций (базовый / оптимистичный сценарий)", `${base.payback_month ? base.payback_month + " мес." : "более " + base.horizon + " мес."} / ${opt.payback_month ? opt.payback_month + " мес." : "более " + opt.horizon + " мес."}`],
      ["Маркетинг: запуск / ежемесячно", `${money(data.marketing.launch_total)} / ${money(data.marketing.monthly_total)}`],
      ["Срок запуска", "8 недель от регистрации ИП до открытия"],
      ["Налоговый режим", `Патент ≈ ${money(data.taxes.patent_month_gross)}/мес до уменьшения на взносы (≈ ${money(data.taxes.patent_month_net)} после)`],
    ]),
    p(" "),
    p(`Ключевой вывод: при аренде до 30–50 тыс. ₽, собственном импорте и участии владельца в работе зала магазин выходит в плюс от ${ru(data.break_even.pairs_per_day)} пар в день; главный риск — трафик районного ТЦ, поэтому модель предусматривает онлайн-канал (Avito, VK) и тест локации в первые 3 месяца.`, { size: 20, bold: true }),
  ];
}

function market() {
  const m = data.market;
  return [
    h1("2. Рынок обуви Тюмени"),
    h2("2.1. Город и покупательная способность"),
    kv([
      ["Население Тюмени (среднегодовое, 2026, прогноз администрации)", `${num(m.population)} чел.`],
      ["Средняя зарплата в Тюменской области (Тюменьстат, 2025)", `${m.avg_salary_region} ₽`],
      ["Медианная зарплата в Тюмени (февраль 2026)", `${m.median_salary_city} ₽`],
      ["Рост оборота розничной торговли области (2026)", m.retail_growth],
      ["Покупки обуви на человека в год (опрос: 22 % — 2 пары, 16 % — 3, 23 % — 4 и более)", `≈ ${m.pairs_per_capita} пары`],
      ["Средняя цена пары в массовом сегменте (оценка)", money(m.avg_price)],
      ["Оценка ёмкости рынка обуви города", `≈ ${bigMoney(m.market_value)} в год`],
      ["Сегмент кроссовок и повседневной обуви (~30 %)", `≈ ${bigMoney(m.sneakers_value)} в год`],
      ["Целевая доля одного магазина", `${m.target_share_pct} % ≈ ${bigMoney(m.target_revenue_year)} в год`],
    ]),
    h2("2.2. Тренды 2025–2026"),
    bullet("В 2025 г. россияне купили на 35 % больше пар обуви (январь–август), расходы на обувь 564 млрд ₽ (+29 %); кроссовки и кеды — 16 млн пар, обувь без каблука — рекорд. Кроссовки остаются самой востребованной категорией.", { size: 18 }),
    bullet("Цены на обувь выросли на 59 % за три года, в 2025 г. рост замедлился до 6–9 % — покупатель чувствителен к цене и переходит в бюджетный сегмент.", { size: 18 }),
    bullet("В начале 2026 г. продажи одежды и обуви в штуках снизились (−11 %): люди экономят, растёт доля маркетплейсов и дискаунтеров. Для нового магазина это аргумент в пользу цены ниже сетей и локального сервиса (примерка, обмен).", { size: 18 }),
    bullet("Сезонность: пики март–апрель и сентябрь–октябрь (демисезон), декабрь (подарки); спад январь–февраль и июнь–июль.", { size: 18 }),
    h2("2.3. Конкуренты в Тюмени"),
    table({
      columns: [{ header: "Игрок", width: 2300 }, { header: "Где", width: 2600 }, { header: "Сегмент и цены", width: 4738 }],
      rows: m.competitors.map((c) => c), size: 17,
    }),
    p(" "),
    p([run("Позиционирование: ", { bold: true, size: 19 }), run(m.positioning, { size: 19 })]),
  ];
}

function concept() {
  const s = data.store;
  return [
    h1("3. Концепция магазина и ассортимент"),
    kv([
      ["Формат", s.format],
      ["Локация (базовый вариант)", s.location],
      ["Режим работы и персонал", s.hours],
      ["Ассортимент", "60 % кроссовки базовые, 25 % демисезонные кроссовки/полуботинки, 15 % слипоны/сандалии/тапочки + аксессуары; 60–80 моделей, размерный ряд 36–45"],
      ["Запас на старте", `${data.purchase.pairs} пар (полная стоимость ${money(data.purchase.landed_first)}/пара с первой сертификацией)`],
      ["Оборачиваемость", "заказ у поставщика 4 раза в год, склад на 3 месяца продаж + 15 % страховой запас"],
      ["Онлайн-канал", "Avito, группа VK и Telegram-канал магазина, доставка по Тюмени в день заказа (Яндекс Доставка/самовывоз из ТЦ)"],
      ["Сервис", "примерка, обмен 14 дней, бонусная программа 5 %, ремонтная мастерская-партнёр"],
    ]),
    p(" "),
    h3("Ценовая лестница"),
    table({ columns: [{ header: "Группа", width: 5600 }, { header: "Розничная цена", width: 4038, align: C }], rows: data.pricing.ladder, size: 18 }),
  ];
}

function rent() {
  return [
    h1("4. Помещение: рынок аренды и дешёвый вариант"),
    h2("4.1. Ставки аренды в Тюмени (сентябрь 2026)"),
    table({ columns: [{ header: "Тип площадки", width: 5600 }, { header: "Ставка в месяц", width: 4038, align: C }], rows: data.rent_market, size: 18 }),
    p(" "),
    h2("4.2. Конкретные предложения (объявления N1.ru / ЦИАН, сентябрь 2026)"),
    p("Отобраны варианты 35–80 м² с самой низкой ставкой; актуальность и условия (НДС, коммунальные, каникулы) уточняются у собственника перед просмотром.", { size: 18 }),
    table({
      columns: [{ header: "Адрес / объект", width: 2500 }, { header: "м²", width: 500, align: C }, { header: "₽/мес", width: 1000, align: R }, { header: "₽/м²", width: 700, align: R }, { header: "Плюсы", width: 1900 }, { header: "Минусы", width: 1738 }, { header: "Оценка", width: 1300 }],
      rows: data.rent_options.map((o) => [{ text: `${o.address}\n${o.district}`, italics: true, bold: o.score.startsWith("рекомендован"), fill: o.score.startsWith("рекомендован") ? "E2EFDA" : undefined }, String(o.area), money(o.rent, ""), num(Math.round(o.rent / o.area)), o.plus, o.minus, o.score]),
      size: 15,
    }),
    p(" "),
    h2("4.3. Рекомендация"),
    p(`Базовый вариант — павильон 35 м² в ТРЦ «Премьер» (ул. 50 лет ВЛКСМ, 63) за ${money(data.store.rent_month)}/мес (845 ₽/м²). Это районный торговый центр в Восточном округе — плотный спальный массив с семейной аудиторией, которая покупает обувь бюджетного и среднего сегмента. Павильон не требует капитального ремонта, есть парковка и общая охрана ТЦ. Запасной вариант — стрит-ритейл на ул. 30 лет Победы, 7/5 (68 м², 47 740 ₽), если понадобится большая площадь.`, { size: 19 }),
    h3("Чек-лист перед подписанием договора"),
    ...["Трафик: посчитать проходимость у входа в ТЦ в будни и выходные (утро/вечер), запросить у администрации данные счётчиков.", "Условия: срок 11 месяцев с пролонгацией, индексация ≤ 7 %, обеспечительный платёж 1 месяц, арендные каникулы на ремонт 2–3 недели, право на вывеску и штендер.", "Платежи: что входит в ставку (коммунальные, маркетинговый сбор ТЦ, вывоз мусора, охрана), наличие НДС.", "Помещение: электрическая мощность ≥ 3 кВт, интернет, вентиляция, пожарная сигнализация, возможность установки противокражных ворот.", "Соседи: наличие обувных арендаторов (эксклюзив категории), якорные магазины и их график."].map((t) => bullet(t, { size: 18 })),
  ];
}

function purchase() {
  const pu = data.purchase;
  return [
    h1("5. Закупка и логистика (собственный импорт)"),
    p(`Первая партия: ${pu.pairs} пар, средняя цена FOB Гуанчжоу ${pu.fob_avg_usd} $/пара (кроссовки 15 $, демисезон 25 $, лёгкая обувь 8 $), вес ${num(pu.weight_kg)} кг, объём ${pu.volume_m3} м³ (обувь — объёмный груз, платный вес считается по 250 кг/м³). Расчёт выполнен движком VED Calculator Core по маршруту Китай → Бишкек (ОсОО, ЕАЭС) → Тюмень с белой растаможкой: пошлина 0,47 €/пара (ЕТТ ЕАЭС 6404 11 000 0), НДС КР 12 %, ввозной НДС РФ 22 %, маркировка «Честный ЗНАК», декларация ТР ТС 017/2011.`, { size: 19 }),
    table({
      columns: [{ header: "Маршрут", width: 2900 }, { header: "Схема", width: 1500 }, { header: "₽/пара", width: 1000, align: R }, { header: "Всего, ₽", width: 1200, align: R }, { header: "Срок, дн.", width: 900, align: C }, { header: "Риск", width: 2138 }],
      rows: pu.routes.map((r) => [{ text: r.name, bold: r.name === pu.white_first.name }, CLR_RU[r.clearance], money(r.per_unit, ""), money(r.total, ""), r.days, RISK_RU[r.risk]]),
      size: 16,
    }),
    p(" "),
    kv([
      ["Полная стоимость пары, первая партия (с сертификацией 18 000 ₽)", money(pu.landed_first)],
      ["Полная стоимость пары, повторные партии", money(pu.landed_repeat)],
      ["Из них: пошлина / НДС КР / НДС РФ на партию", `${money(pu.white_repeat.duty)} / ${money(pu.white_repeat.vat_kg)} / ${money(pu.white_repeat.vat_ru)}`],
      ["Логистика Гуанчжоу → Бишкек → Тюмень на партию", money(pu.white_repeat.freight)],
      ["Маркировка «Честный ЗНАК» на партию", money(pu.white_repeat.marking)],
      ["Для сравнения: карго-схема (без документов, высокий риск)", `${money(pu.landed_cargo)}/пара — не рекомендуется: товар без кодов маркировки нельзя легально продать`],
      ["Для сравнения: московские оптовики", pu.wholesale_benchmark],
      ["Срок поставки", `${pu.white_first.days} дней от отгрузки; заказ за 6–7 недель до сезона`],
    ]),
    p(" "),
    p("Полный расчёт всех маршрутов, ставок и формул приведён в отдельном отчёте «Расчёт маршрутов ВЭД» (reports/VED_calculations.docx).", { size: 17, italics: true }),
  ];
}

function capex() {
  const c = data.capex;
  return [
    h1("6. Инвестиции на открытие (CAPEX)"),
    table({
      columns: [{ header: "Статья", width: 4700 }, { header: "Сумма, ₽", width: 1400, align: R }, { header: "Комментарий", width: 3538 }],
      rows: [...c.items.map(([n, v, k]) => [n, money(v, ""), k]), [{ text: "Итого без резерва", bold: true }, { text: money(c.subtotal, ""), bold: true }, ""], ["Непредвиденные расходы 5 %", money(c.contingency, ""), ""], [{ text: "ИТОГО инвестиции на открытие", bold: true, fill: "E2EFDA" }, { text: money(c.total, ""), bold: true, fill: "E2EFDA" }, { text: "", fill: "E2EFDA" }]],
      size: 16,
    }),
    p(" "),
    p(`Первая партия товара — крупнейшая статья (${money(data.purchase.landed_first)} × ${data.purchase.pairs} пар). Оборудование и ремонт взяты по нижней границе рынка: павильон в ТЦ обычно передаётся с готовой отделкой, поэтому ремонт ограничен покраской, светом и напольным покрытием.`, { size: 18 }),
    p(`Потребность в финансировании с учётом закупок следующих партий до выхода на самоокупаемость: базовый сценарий ${money(data.funding.peak_base)}, пессимистичный ${money(data.funding.peak_pess)}. Рекомендуемый бюджет проекта — ${money(data.funding.recommended)}.`, { size: 18, bold: true }),
  ];
}

function opex() {
  const o = data.opex;
  return [
    h1("7. Ежемесячные расходы (OPEX)"),
    table({
      columns: [{ header: "Статья", width: 4700 }, { header: "₽/мес", width: 1400, align: R }, { header: "Комментарий", width: 3538 }],
      rows: [...o.items.map(([n, v, k]) => [n, money(v, ""), k]), [{ text: "Итого постоянные расходы", bold: true, fill: "E2EFDA" }, { text: money(o.fixed_total, ""), bold: true, fill: "E2EFDA" }, { text: "+ переменные: " + o.variable_note, fill: "E2EFDA" }]],
      size: 16,
    }),
    p(" "),
    kv([
      ["Оплата продавца", `${money(data.payroll.seller_gross)} на руки до НДФЛ; взносы работодателя ${money(data.payroll.seller_contrib)} (30 % до 1,5 МРОТ = ${money(data.payroll.mrot)}, далее 15 % — тариф МСП, + 0,2 % травматизм); полная стоимость ${money(data.payroll.seller_cost)}`],
      ["Взносы ИП за себя (2026)", `${money(data.payroll.ip_fixed)} в год + 1 % с ПВД свыше 300 000 ₽ (${money(data.taxes.ip_extra_1pct)}/год)`],
      ["Патент", `ПВД ${money(data.taxes.pvd_m2)}/м² × ${data.taxes.sales_area} м² торгового зала × 6 % = ${money(data.taxes.patent_year)}/год (${money(data.taxes.patent_month_gross)}/мес); уменьшается на взносы до 50 % → ≈ ${money(data.taxes.patent_month_net)}/мес. Проверить ставку на patent.nalog.ru`],
      ["Альтернатива — УСН 6 % с выручки", `≈ ${money(data.taxes.usn_alt_month)}/мес в базовом сценарии — дороже патента в 4–5 раз`],
      ["Владелец", "работает в зале в одну из смен и не получает зарплату (его доход — чистая прибыль); найм второго продавца стоит " + money(data.payroll.seller_cost) + "/мес — см. чувствительность"],
    ]),
  ];
}

function unitEconomics() {
  const pr = data.pricing;
  return [
    h1("8. Ценообразование и юнит-экономика"),
    kv([
      ["Полная закупочная стоимость пары (повторные партии)", money(data.purchase.landed_repeat)],
      ["Наценка", `× ${pr.markup} (коэффициент к полной стоимости)`],
      ["Средняя розничная цена пары", money(pr.avg_price)],
      ["Валовая прибыль с пары", `${money(pr.gp_pair)} (${ru(pr.gross_margin_pct)} % от цены)`],
      ["Аксессуары к чеку", `+${pr.accessories_share} % к выручке при марже 55 %`],
      ["Переменные расходы", `эквайринг ${pr.acquiring} % + потери/уценка ${pr.losses} % от выручки`],
      ["Вклад одной пары в покрытие постоянных расходов", money(Math.round(parseFloat(pr.gp_pair) + parseFloat(pr.avg_price) * 0.04 * 0.55 - parseFloat(pr.avg_price) * 0.025))],
    ]),
    p(" "),
    p("Средняя цена ниже сетевых магазинов (Zenden, Спортмастер) на 15–25 % при сопоставимом качестве, но выше рыночных no-name точек — за счёт легального товара с маркировкой, примерки и обмена. Это ключевой аргумент для покупателя, который экономит, но не готов рисковать возвратом на маркетплейсе.", { size: 18 }),
  ];
}

function financials() {
  const out = [h1("9. Финансовая модель: сценарии, P&L, денежный поток")];
  out.push(p("Модель на 24 месяца с открытия (ноябрь 2026); в таблицах показаны первые 12 месяцев. Учтены сезонность (индекс по месяцам), раскачка (60 % плана в 1-й месяц, 80 % во 2-й), закупки следующих партий по предоплате раз в 3 месяца с запасом 15 %, патент после уменьшения на взносы, переменные расходы. Товар первой партии входит в CAPEX; в денежном потоке себестоимость заменена реальными закупками.", { size: 18 }));
  out.push(h2("9.1. Сводка по сценариям (12 месяцев)"));
  out.push(table({
    columns: [{ header: "Показатель", width: 3800 }, { header: "Пессимистичный", width: 1946, align: R }, { header: "Базовый", width: 1946, align: R }, { header: "Оптимистичный", width: 1946, align: R }],
    rows: [
      ["Продажи в магазине + онлайн, пар/мес (план без сезонности)", ...[pess, base, opt].map((s) => `${s.pairs_store} + ${s.pairs_online}`)],
      ["Продано пар за 12 месяцев", ...[pess, base, opt].map((s) => num(s.totals.pairs))],
      ["Выручка за 12 месяцев", ...[pess, base, opt].map((s) => money(s.totals.revenue, ""))],
      ["Валовая прибыль", ...[pess, base, opt].map((s) => money(s.totals.gross, ""))],
      ["Операционные расходы", ...[pess, base, opt].map((s) => money(s.totals.opex, ""))],
      ["Патент", ...[pess, base, opt].map((s) => money(s.totals.tax, ""))],
      [{ text: "Чистая прибыль за 12 месяцев", bold: true }, ...[pess, base, opt].map((s) => ({ text: money(s.totals.net, ""), bold: true }))],
      ["Средняя выручка в месяц", ...[pess, base, opt].map((s) => money(s.avg_month_revenue, ""))],
      ["Средняя чистая прибыль в месяц", ...[pess, base, opt].map((s) => money(s.avg_month_net, ""))],
      ["Закупки товара за год (без первой партии)", ...[pess, base, opt].map((s) => money(s.totals.purchases, ""))],
      ["Пиковая потребность в финансировании", ...[pess, base, opt].map((s) => money(s.peak_funding_need, ""))],
      ["Накопленный денежный поток на конец года (после CAPEX)", ...[pess, base, opt].map((s) => money(s.cumulative_end, ""))],
      ["Чистая прибыль за 2-й год (без раскачки, тот же план продаж)", ...[pess, base, opt].map((s) => money(s.totals_y2.net, ""))],
      [{ text: "Срок окупаемости инвестиций (горизонт 24 мес.)", bold: true }, ...[pess, base, opt].map((s) => ({ text: s.payback_month ? `${s.payback_month} мес.` : `более ${s.horizon} мес.`, bold: true }))],
    ],
    size: 17,
  }));
  out.push(p(" "));
  out.push(h2("9.2. Базовый сценарий по месяцам"));
  return out;
}

function monthlyTable(s, title) {
  return [
    h3(title),
    table({
      columns: [{ header: "Месяц", width: 1000 }, { header: "Пар", width: 700, align: R }, { header: "Выручка", width: 1350, align: R }, { header: "Себестоимость", width: 1350, align: R }, { header: "Валовая прибыль", width: 1350, align: R }, { header: "OPEX", width: 1250, align: R }, { header: "Патент", width: 950, align: R }, { header: "Чистая прибыль", width: 1350, align: R }, { header: "Закупки", width: 1350, align: R }, { header: "Денежный поток", width: 1350, align: R }, { header: "Накопл. с учётом CAPEX", width: 1470, align: R }, { header: "Остаток, пар", width: 1100, align: R }],
      rows: [...s.rows.map((r) => [r.month, r.pairs, money(r.revenue, ""), money(r.cogs, ""), money(r.gross, ""), money(r.opex, ""), money(r.tax, ""), { text: money(r.net, ""), bold: true }, money(r.purchases, ""), money(r.cash, ""), { text: money(r.cumulative, ""), bold: true, fill: parseFloat(r.cumulative) >= 0 ? "E2EFDA" : undefined }, r.stock]),
        [{ text: "Итого", bold: true }, { text: num(s.totals.pairs), bold: true }, { text: money(s.totals.revenue, ""), bold: true }, { text: money(s.totals.cogs, ""), bold: true }, { text: money(s.totals.gross, ""), bold: true }, { text: money(s.totals.opex, ""), bold: true }, { text: money(s.totals.tax, ""), bold: true }, { text: money(s.totals.net, ""), bold: true }, { text: money(s.totals.purchases, ""), bold: true }, "", "", ""]],
      size: 14,
    }),
    p(" "),
  ];
}

function breakEven() {
  const b = data.break_even;
  return [
    h1("10. Точка безубыточности, окупаемость, чувствительность"),
    kv([
      ["Постоянные расходы + патент в месяц", money(parseFloat(data.opex.fixed_total) + parseFloat(data.taxes.patent_month_net))],
      ["Вклад пары в покрытие (валовая прибыль + аксессуары − переменные)", money(Math.round(parseFloat(data.pricing.gp_pair) + parseFloat(data.pricing.avg_price) * 0.04 * 0.55 - parseFloat(data.pricing.avg_price) * 0.025))],
      ["Точка безубыточности", `${num(b.pairs)} пар/мес = ${ru(b.pairs_per_day)} пары в день`],
      ["Выручка в точке безубыточности", `${money(b.revenue)}/мес`],
      ["Запас прочности в базовом сценарии", `${num(Math.round((parseFloat(base.totals.pairs) / 12 / parseFloat(b.pairs) - 1) * 100))} % по объёму продаж`],
    ]),
    p(" "),
    h2("10.1. Чувствительность (базовый сценарий, 12 месяцев)"),
    table({
      columns: [{ header: "Сценарий", width: 4000 }, { header: "Выручка за год", width: 1500, align: R }, { header: "Чистая прибыль за год", width: 1500, align: R }, { header: "Прибыль в месяц", width: 1300, align: R }, { header: "Окупаемость", width: 1338, align: C }],
      rows: data.sensitivity.map((s) => [s.title, money(s.revenue, ""), money(s.net, ""), money(s.avg_net, ""), s.payback ? `${s.payback} мес.` : "> 24 мес."]),
      size: 16,
    }),
    p(" "),
    p("Наибольшее влияние на результат оказывают цена и объём продаж, затем аренда: переезд на первую линию в центре удваивает постоянные расходы и требует вдвое большего трафика. Карго-схема даёт лучшую бумажную экономику, но товар без маркировки нельзя продавать легально — риск изъятия и штрафов, поэтому в модель заложена белая схема.", { size: 18 }),
  ];
}

function marketing() {
  const m = data.marketing;
  return [
    h1("11. Реклама и маркетинг"),
    p("Аудитория: жители Восточного округа и прилегающих районов 18–45 лет, семьи с детьми, студенты; радиус 3–5 км от ТЦ. Каналы выбраны по принципу «карты + соцсети + Avito»: именно там ищут обувь в регионах, а стоимость контакта в Тюмени низкая (клик в Директе ≈ 24 ₽, CPM VK ≈ 85 ₽).", { size: 18 }),
    h2("11.1. Бюджет запуска (6 недель)"),
    table({ columns: [{ header: "Канал", width: 4700 }, { header: "₽", width: 1200, align: R }, { header: "Комментарий", width: 3738 }], rows: [...m.launch.map(([n, v, k]) => [n, money(v, ""), k]), [{ text: "Итого", bold: true }, { text: money(m.launch_total, ""), bold: true }, ""]], size: 16 }),
    p(" "),
    h2("11.2. Ежемесячный бюджет"),
    table({ columns: [{ header: "Канал", width: 4700 }, { header: "₽/мес", width: 1200, align: R }, { header: "Ожидание", width: 3738 }], rows: [...m.monthly.map(([n, v, k]) => [n, money(v, ""), k]), [{ text: "Итого", bold: true }, { text: money(m.monthly_total, ""), bold: true }, ""]], size: 16 }),
    p(" "),
    h2("11.3. KPI рекламы"),
    table({ columns: [{ header: "Показатель", width: 5600 }, { header: "Целевое значение", width: 4038, align: C }], rows: m.kpi, size: 17 }),
    p(" "),
    h2("11.4. Календарь первых 90 дней"),
    table({ columns: [{ header: "Период", width: 2000 }, { header: "Действия", width: 7638 }], rows: m.calendar, size: 17 }),
    p(" "),
    h2("11.5. Что не делать на старте"),
    ...["Маркетплейсы (Wildberries/Ozon): комиссия 25–35 % + логистика и возвраты 30–40 % — экономика бюджетной обуви не выдерживает; рассматривать после 6 месяцев как канал распродажи остатков.", "Билборды 3×6 (от 15 000 ₽/мес) и радио — дорого для радиуса 3 км; эффективнее оформление входа в ТЦ и штендер.", "Скидки глубже 20 % вне сезонных распродаж — разрушают маржу; вместо этого бонусы и подарок к паре."].map((t) => bullet(t, { size: 18 })),
  ];
}

function legal() {
  return [h1("12. Юридические и организационные шаги"), table({ columns: [{ header: "Вопрос", width: 2600 }, { header: "Решение", width: 7038 }], rows: data.legal, size: 17 })];
}
function timeline() {
  return [h1("13. План-график открытия"), table({ columns: [{ header: "Срок", width: 1800 }, { header: "Работы", width: 7838 }], rows: data.timeline, size: 17 })];
}
function risks() {
  return [h1("14. Риски и меры"), table({ columns: [{ header: "Риск", width: 3400 }, { header: "Вероятность", width: 1500, align: C }, { header: "Мера", width: 4738 }], rows: data.risks, size: 17 })];
}
function sources() {
  const out = [h1("15. Источники")];
  data.sources.forEach(([label, url]) => out.push(bullet([run(label + ": ", { size: 16 }), new ExternalHyperlink({ link: url, children: [new TextRun({ text: url, style: "Hyperlink", font: FONT, size: 16 })] })])));
  out.push(p(" "));
  out.push(p("Оговорка: документ — планово-аналитический расчёт на основе открытых данных на дату формирования. Ставки аренды, налогов, логистики и рекламы подлежат подтверждению у арендодателя, ФНС, таможенного представителя и рекламных площадок перед принятием решений.", { size: 16, italics: true, color: "595959" }));
  return out;
}

// ------------------------------------------------------------------ assembly
const hf = {
  headers: { default: new Header({ children: [new Paragraph({ alignment: R, children: [run("Обувной магазин в Тюмени — бизнес-кейс", { size: 16, color: "808080" })] })] }) },
  footers: { default: new Footer({ children: [new Paragraph({ alignment: C, children: [run("Стр. ", { size: 16, color: "808080" }), new TextRun({ children: [PageNumber.CURRENT], font: FONT, size: 16, color: "808080" }), run(" из ", { size: 16, color: "808080" }), new TextRun({ children: [PageNumber.TOTAL_PAGES], font: FONT, size: 16, color: "808080" })] })] }) },
};
const margins = { top: 1134, bottom: 1134, left: 1134, right: 1134 };
const portrait = { page: { size: { width: 11906, height: 16838 }, margin: margins } };
const landscape = { page: { size: { width: 11906, height: 16838, orientation: PageOrientation.LANDSCAPE }, margin: margins } };

const doc = new Document({
  creator: "VED Calculator Core", title: "Открытие обувного магазина в Тюмени — бизнес-кейс",
  styles: {
    default: { document: { run: { font: FONT, size: 20 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 32, bold: true, color: "1F3864", font: FONT }, paragraph: { spacing: { before: 360, after: 160 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 26, bold: true, color: "2F5496", font: FONT }, paragraph: { spacing: { before: 260, after: 120 }, outlineLevel: 1 } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 22, bold: true, color: "404040", font: FONT }, paragraph: { spacing: { before: 200, after: 100 }, outlineLevel: 2 } },
    ],
  },
  numbering: { config: [{ reference: "bullets", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 540, hanging: 270 } } } }] }] },
  sections: [
    { properties: portrait, ...hf, children: [...titlePage(), pageBreak(), ...summary(), ...market(), ...concept(), ...rent(), ...purchase(), ...capex(), ...opex(), ...unitEconomics(), ...financials()] },
    { properties: landscape, ...hf, children: [...monthlyTable(base, "Базовый сценарий: P&L и денежный поток по месяцам, ₽"), ...monthlyTable(pess, "Пессимистичный сценарий по месяцам, ₽"), ...monthlyTable(opt, "Оптимистичный сценарий по месяцам, ₽")] },
    { properties: portrait, ...hf, children: [...breakEven(), ...marketing(), ...legal(), ...timeline(), ...risks(), ...sources()] },
  ],
});

Packer.toBuffer(doc).then((buffer) => {
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  fs.writeFileSync(outputPath, buffer);
  console.log(`wrote ${outputPath} (${Math.round(buffer.length / 1024)} KB)`);
});
