#!/usr/bin/env node
/**
 * Render the Word report from the JSON produced by scripts/export_report_data.py.
 *
 *   NODE_PATH=<dir with node_modules> node scripts/build_docx_report.js reports/report_data.json reports/VED_calculations.docx
 */
"use strict";

const fs = require("fs");
const path = require("path");
const {
  AlignmentType, BorderStyle, Document, ExternalHyperlink, Footer, Header, HeadingLevel, LevelFormat,
  PageBreak, PageNumber, PageOrientation, Packer, Paragraph, ShadingType, Table, TableCell,
  TableLayoutType, TableRow, TextRun, VerticalAlign, WidthType,
} = require("docx");

const [, , inputPath = "reports/report_data.json", outputPath = "reports/VED_calculations.docx"] = process.argv;
const data = JSON.parse(fs.readFileSync(inputPath, "utf8"));

// ------------------------------------------------------------------ formatting helpers
const NBSP = " ";
function money(value, suffix = "") {
  if (value === null || value === undefined || value === "—" || value === "") return "—";
  const s = String(value);
  if (!/^-?\d+(\.\d+)?$/.test(s)) return s;
  const [intPart, decPart = "00"] = s.split(".");
  const negative = intPart.startsWith("-");
  const digits = negative ? intPart.slice(1) : intPart;
  const grouped = digits.replace(/\B(?=(\d{3})+(?!\d))/g, NBSP);
  return `${negative ? "−" : ""}${grouped},${(decPart + "00").slice(0, 2)}${suffix}`;
}
function num(value) {
  if (value === null || value === undefined) return "—";
  const s = String(value);
  if (!/^-?\d+(\.\d+)?$/.test(s)) return s;
  const [intPart, decPart] = s.split(".");
  const grouped = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, NBSP);
  return decPart ? `${grouped},${decPart.replace(/0+$/, "") || "0"}` : grouped;
}

const FONT = "Arial";
const MONO = "Consolas";
const PORTRAIT_WIDTH = 9638; // A4 minus 2 × 1134 margins
const LANDSCAPE_WIDTH = 14570;

function run(text, opts = {}) {
  return new TextRun({ text: String(text), font: opts.mono ? MONO : FONT, size: opts.size || 20, bold: !!opts.bold, italics: !!opts.italics, color: opts.color });
}
function p(text, opts = {}) {
  return new Paragraph({
    children: Array.isArray(text) ? text : [run(text, opts)],
    alignment: opts.align || AlignmentType.LEFT,
    spacing: { before: opts.before ?? 60, after: opts.after ?? 60 },
    keepNext: opts.keepNext,
  });
}
function h1(text) { return new Paragraph({ text, heading: HeadingLevel.HEADING_1, spacing: { before: 360, after: 160 } }); }
function h2(text) { return new Paragraph({ text, heading: HeadingLevel.HEADING_2, spacing: { before: 280, after: 120 } }); }
function h3(text) { return new Paragraph({ text, heading: HeadingLevel.HEADING_3, spacing: { before: 200, after: 100 } }); }
function bullet(text, opts = {}) {
  return new Paragraph({ children: Array.isArray(text) ? text : [run(text, opts)], numbering: { reference: "bullets", level: 0 }, spacing: { before: 30, after: 30 } });
}
function formula(text) {
  return new Paragraph({ children: [run(text, { mono: true, size: 16 })], spacing: { before: 20, after: 20 }, indent: { left: 360 } });
}
function pageBreak() { return new Paragraph({ children: [new PageBreak()] }); }

/**
 * table({ columns: [{ header, width, align }], rows: [[cell, ...]], size, headerFill })
 * A cell may be a string or { text, bold, align, fill, mono }.
 */
function table({ columns, rows, size = 16, headerFill = "D9E2F3", totalWidth }) {
  const widths = columns.map((c) => c.width);
  const sum = widths.reduce((a, b) => a + b, 0);
  const target = totalWidth || sum;
  if (sum !== target) throw new Error(`column widths ${sum} != ${target}`);
  const border = { style: BorderStyle.SINGLE, size: 4, color: "A6A6A6" };
  const borders = { top: border, bottom: border, left: border, right: border };
  const cell = (content, col, isHeader) => {
    const spec = typeof content === "object" && content !== null ? content : { text: content };
    const align = spec.align || (isHeader ? AlignmentType.CENTER : col.align || AlignmentType.LEFT);
    const lines = String(spec.text ?? "—").split("\n");
    return new TableCell({
      width: { size: col.width, type: WidthType.DXA },
      borders,
      verticalAlign: VerticalAlign.CENTER,
      margins: { top: 40, bottom: 40, left: 70, right: 70 },
      shading: isHeader ? { type: ShadingType.CLEAR, fill: headerFill, color: "auto" } : spec.fill ? { type: ShadingType.CLEAR, fill: spec.fill, color: "auto" } : undefined,
      children: lines.map((line, i) => new Paragraph({
        alignment: align,
        spacing: { before: 0, after: 0 },
        children: [run(line, { size, bold: isHeader || !!spec.bold, mono: !!spec.mono, italics: !!spec.italics && i > 0 })],
      })),
    });
  };
  return new Table({
    width: { size: target, type: WidthType.DXA },
    columnWidths: widths,
    layout: TableLayoutType.FIXED,
    rows: [
      new TableRow({ tableHeader: true, children: columns.map((c) => cell(c.header, c, true)) }),
      ...rows.map((r) => new TableRow({ cantSplit: true, children: r.map((v, i) => cell(v, columns[i], false)) })),
    ],
  });
}
const R = AlignmentType.RIGHT;
const C = AlignmentType.CENTER;

function kvTable(pairs, w1 = 3800, w2 = PORTRAIT_WIDTH - 3800) {
  return table({ columns: [{ header: "Параметр", width: w1 }, { header: "Значение", width: w2 }], rows: pairs.map(([k, v]) => [{ text: k, bold: true }, v]), size: 18 });
}

// ------------------------------------------------------------------ content builders
const res = data.result;
const routes = res.routes;
const byId = Object.fromEntries(routes.map((r) => [r.route_id, r]));
const picks = [
  ["Оптимальный (рекомендован)", byId[res.optimal_id]],
  ["Самый дешёвый", byId[res.cheapest_id]],
  ["Самый дешёвый легальный", byId[res.cheapest_legal_id]],
  ["Самый быстрый", byId[res.fastest_id]],
];

function titlePage() {
  return [
    new Paragraph({ spacing: { before: 2400, after: 200 }, alignment: C, children: [run("Расчёт маршрутов ВЭД", { size: 56, bold: true, color: "1F3864" })] }),
    new Paragraph({ spacing: { after: 200 }, alignment: C, children: [run("Китай / Турция / ЕС / США / ОАЭ / Вьетнам → Бишкек (ОсОО, ЕАЭС) → Россия (ИП / ООО)", { size: 26 })] }),
    new Paragraph({ spacing: { after: 600 }, alignment: C, children: [run("Полная выгрузка расчётов движка VED Calculator Core", { size: 24, italics: true })] }),
    new Paragraph({ alignment: C, children: [run(`Версия движка: ${data.meta.version}`, { size: 22 })] }),
    new Paragraph({ alignment: C, children: [run(`Дата формирования: ${data.meta.generated}`, { size: 22 })] }),
    new Paragraph({ alignment: C, children: [run(`Курсы валют на: ${data.meta.fx_as_of}`, { size: 22 })] }),
    new Paragraph({ alignment: C, spacing: { before: 200 }, children: [run(`Файл запроса: ${data.meta.request_file}`, { size: 20, mono: true })] }),
    new Paragraph({ spacing: { before: 1800 }, alignment: C, children: [run("Все суммы в рублях приведены с точностью до копейки; налоговые базы рассчитаны по официальному (среднему) курсу, стоимостная оценка — с валютным буфером δ_fx. Ставки и тарифы являются справочными и подлежат подтверждению у лицензированного таможенного представителя.", { size: 18, italics: true, color: "595959" })] }),
    pageBreak(),
    new Paragraph({ children: [run("Содержание", { size: 32, bold: true, color: "1F3864" })], spacing: { after: 200 } }),
    ...TOC_ENTRIES.map(([title, level]) => new Paragraph({
      children: [run(title, { size: level ? 18 : 20, bold: !level })],
      spacing: { before: level ? 20 : 80, after: 20 },
      indent: { left: level ? 540 : 0 },
    })),
  ];
}

const TOC_ENTRIES = [
  ["1. Резюме", 0], ["2. Исходные данные расчёта", 0], ["3. Справочные данные, использованные в расчёте", 0],
  ["3.1. Курсы валют", 1], ["3.2. Тарифная линия ТН ВЭД", 1], ["3.3. Налоговые профили юрисдикций", 1], ["3.4. Банковские комиссии и спреды", 1],
  ["3.5. Сервисные расходы и сроки обработки", 1], ["3.6. Тарифные карты международных коридоров", 1], ["3.7. Доставка по территории ЕАЭС/РФ до города назначения", 1], ["3.8. Политика выбора оптимального маршрута", 1],
  ["4. Методика расчёта", 0], ["5. Сводная таблица маршрутов", 0], ["6. Структура затрат по маршрутам (₽)", 0],
  ["7. Пошаговый расчёт по схемам", 0], ...data.detailed.map((d, i) => [`7.${i + 1}. ${d.route_name} — ${d.clearance_ru}`, 1]),
  ["8. Сравнение таможенного оформления: Кыргызстан (ЕАЭС) vs прямой ввоз в РФ", 0], ["9. Сценарный анализ (чувствительность)", 0],
  ["10. Дополнительные расчёты: другие поставки", 0], ...data.extras.map((e, i) => [`10.${i + 1}. ${e.title}`, 1]),
  ["11. Встроенный справочник ставок ТН ВЭД", 0], ["12. Примечания по маршрутам основного расчёта", 0], ["13. Источники ставок и тарифов", 0],
];

function summarySection() {
  const out = [h1("1. Резюме")];
  const describe = (r) => `${r.route_name} — ${money(r.total_cost_rub)} ₽ (${money(r.cost_per_unit_rub)} ₽/ед.), ${r.days} дн., риск: ${r.risk_ru.toLowerCase()}`;
  const parts = [];
  const optimal = byId[res.optimal_id], cheapest = byId[res.cheapest_id], cheapestLegal = byId[res.cheapest_legal_id], fastest = byId[res.fastest_id];
  if (optimal) parts.push(`Рекомендованный (оптимальный) маршрут: ${describe(optimal)}.`);
  if (cheapest) parts.push(`Самый дешёвый: ${describe(cheapest)}.`);
  if (cheapestLegal && (!cheapest || cheapestLegal.route_id !== cheapest.route_id)) parts.push(`Самый дешёвый легальный: ${describe(cheapestLegal)}.`);
  if (fastest) parts.push(`Самый быстрый: ${describe(fastest)}.`);
  out.push(p(parts.join(" "), { size: 20 }));
  out.push(p(" "));
  out.push(table({
    columns: [
      { header: "Выбор", width: 2300 }, { header: "Маршрут", width: 2900 }, { header: "Итого, ₽", width: 1400, align: R },
      { header: "₽ / ед.", width: 1100, align: R }, { header: "Срок, дн.", width: 800, align: C }, { header: "Риск", width: 1138 },
    ],
    rows: picks.map(([label, r]) => r ? [{ text: label, bold: true }, r.route_name, money(r.total_cost_rub), money(r.cost_per_unit_rub), r.days, r.risk_ru] : [{ text: label, bold: true }, "—", "—", "—", "—", "—"]),
    size: 17,
  }));
  const opt = byId[res.optimal_id];
  if (opt && opt.gross_margin_percent !== null && opt.gross_margin_percent !== undefined) {
    out.push(p(" "));
    out.push(p(`Валовая маржа рекомендованного маршрута при целевой цене продажи: ${money(opt.gross_margin_percent)} %.`, { size: 20 }));
  }
  if (res.warnings.length) {
    out.push(h3("Предупреждения"));
    res.warnings.forEach((w) => out.push(bullet(w, { size: 18 })));
  }
  return out;
}

function inputsSection() {
  return [h1("2. Исходные данные расчёта"), kvTable(data.request)];
}

function referenceSection() {
  const ref = data.reference;
  const out = [h1("3. Справочные данные, использованные в расчёте")];
  out.push(h2("3.1. Курсы валют"));
  out.push(p(`Средние курсы на ${data.meta.fx_as_of}; буфер δ_fx = ${num(ref.fx_buffer)} % применяется один раз к каждому компоненту в иностранной валюте при пересчёте в рубли. Налоговые базы (пошлина, НДС) считаются по среднему курсу без буфера.`, { size: 18 }));
  out.push(table({
    columns: [{ header: "Пара", width: 2400 }, { header: "Средний курс", width: 3600, align: R }, { header: "Курс с буфером δ_fx", width: 3638, align: R }],
    rows: ref.fx.map((f) => [f.pair, num(f.mid), num(f.buffered)]), size: 18,
  }));
  out.push(h2("3.2. Тарифная линия ТН ВЭД"));
  const t = ref.tariff;
  out.push(kvTable([
    ["Код ТН ВЭД", t.hs_code || "категория по умолчанию"],
    ["Описание", t.description],
    ["Ставка ЕТТ ЕАЭС", t.rate],
    ["Способ подбора", { exact: "точное совпадение", prefix: "по префиксу кода", child: "по дочерней позиции", category_default: "по умолчанию категории" }[t.matched_by] || t.matched_by],
    ["Маркировка «Честный ЗНАК»", t.marking ? "обязательна" : "не требуется"],
    ["Подтверждение соответствия", t.certification || "—"],
    ["Технологический сбор, ₽/ед.", num(t.tech_fee)],
    ["Проверка ставки", t.verified ? "сверена с опубликованным ЕТТ" : "справочная оценка — требует проверки"],
    ["Источник", t.source],
  ]));
  if (t.notes.length) t.notes.forEach((n) => out.push(bullet(n, { size: 18 })));
  out.push(h2("3.3. Налоговые профили юрисдикций"));
  out.push(table({
    columns: [{ header: "Юрисдикция", width: 2200 }, { header: "НДС, %", width: 900, align: C }, { header: "Таможенный сбор", width: 3000 }, { header: "Брокер", width: 1700, align: R }, { header: "Срок, дн.", width: 1838, align: C }],
    rows: ref.tax_profiles.map((x) => [x.jurisdiction, x.vat, x.fee, x.broker, x.days]), size: 17,
  }));
  ref.tax_profiles.forEach((x) => out.push(bullet(x.notes, { size: 17 })));
  if (ref.ru_fee_tiers.length) {
    out.push(h3("Шкала таможенных сборов РФ (ПП РФ №1638, с 01.01.2026)"));
    out.push(table({
      columns: [{ header: "Таможенная стоимость до, ₽ (включительно)", width: 4800, align: R }, { header: "Сбор, ₽", width: 4838, align: R }],
      rows: ref.ru_fee_tiers.map((x) => [x.up_to === "свыше" ? "свыше 10 000 000" : num(x.up_to), num(x.fee)]), size: 17,
    }));
  }
  out.push(h2("3.4. Банковские комиссии и спреды"));
  out.push(table({
    columns: [{ header: "Коридор", width: 2200 }, { header: "Валюта", width: 1000, align: C }, { header: "Комиссия, %", width: 1200, align: R }, { header: "Минимум", width: 1400, align: R }, { header: "Максимум", width: 1400, align: R }, { header: "Спред конверсии, %", width: 2438, align: R }],
    rows: ref.bank.map((b) => [b.corridor, b.currency, num(b.percent), num(b.min), num(b.max), num(b.spread)]), size: 17,
  }));
  out.push(h2("3.5. Сервисные расходы и сроки обработки"));
  const sf = ref.service_fees;
  out.push(kvTable([
    ...Object.entries(sf.certification).map(([k, v]) => [`Сертификация: ${k}`, `${money(v)} ₽ за партию`]),
    ["Код маркировки «Честный ЗНАК»", `${money(sf.marking_code)} ₽ / ед.`],
    ["Нанесение маркировки", `${money(sf.marking_apply)} ₽ / ед.`],
    ...Object.entries(sf.hub_days).map(([k, v]) => [`Обработка на хабе: ${k}`, `${v} дн.`]),
    ["Технологический сбор действует с", sf.tech_fee_from],
  ]));
  out.push(h2("3.6. Тарифные карты международных коридоров"));
  out.push(table({
    columns: [{ header: "Коридор", width: 2300 }, { header: "Хаб", width: 900 }, { header: "Транспорт", width: 1200 }, { header: "Тип", width: 1400 }, { header: "$/кг", width: 650, align: R }, { header: "Мин, $", width: 650, align: R }, { header: "кг/м³", width: 650, align: R }, { header: "Обработка", width: 1088 }, { header: "Срок, дн.", width: 800, align: C }],
    rows: ref.corridors.map((c) => [{ text: c.corridor_id, mono: true }, c.hub, c.mode, c.kind, num(c.rate), num(c.min), num(c.coef), c.handling, c.days]), size: 15,
  }));
  out.push(p("Коэффициенты категорий для карго: " + [...new Set(ref.corridors.map((c) => c.multipliers).filter((m) => m !== "—"))].join("; ") + ".", { size: 17 }));
  out.push(h2("3.7. Доставка по территории ЕАЭС/РФ до города назначения"));
  out.push(table({
    columns: [{ header: "Откуда", width: 1500 }, { header: "Транспорт", width: 1300 }, { header: "₽/кг", width: 1200, align: R }, { header: "Минимум, ₽", width: 1400, align: R }, { header: "кг/м³", width: 1200, align: R }, { header: "Срок, дн.", width: 1200, align: C }, { header: "Расстояние, км", width: 1838, align: R }],
    rows: ref.domestic_legs.map((l) => [l.from + (l.fallback ? " (резервный тариф)" : ""), l.mode, num(l.rate), num(l.min), num(l.coef), l.days, num(l.km)]), size: 17,
  }));
  out.push(h2("3.8. Политика выбора оптимального маршрута"));
  out.push(p(`Риск-скорректированная стоимость = Итого × (1 + ${num(ref.policy.delay)} % × срок_макс + ожидаемые потери по уровню риска). Ожидаемые потери: ${Object.entries(ref.policy.loss).map(([k, v]) => `${k} — ${num(v)} %`).join("; ")}. ${ref.policy.prefer_legal ? "Рекомендация ограничена легальными маршрутами (низкий риск), если такие есть." : "Ограничение по легальности отключено."}`, { size: 18 }));
  return out;
}

function methodologySection() {
  return [
    h1("4. Методика расчёта"),
    h2("4.1. Объёмный вес и фрахт"),
    formula("W_расч = max(W_факт, V_м³ × k_объёмный)"),
    formula("         k_объёмный: авиа 167 · карго 200 · авто 250 · ж/д 300 кг/м³"),
    formula("Фрахт  = max(W_расч × ставка $/кг × коэфф. категории; минимум)"),
    formula("         + обработка_фикс + обработка_за_кг × W_расч"),
    h2("4.2. Белая растаможка в Бишкеке (ОсОО, ЕАЭС)"),
    formula("ТС = Инвойс_KGS                          [базис «инвойс» — формула спецификации]"),
    formula("ТС = Инвойс_KGS + Фрахт_до_границы_KGS   [базис CIF — ст. 40 ТК ЕАЭС]"),
    formula("Пошлина = ТС × ставка %                                 (адвалорная)"),
    formula("        = ставка_EUR × (кг | пары | шт) × курс EUR/KGS    (специфическая)"),
    formula("        = max(адвалорная; специфическая)                  (комбинированная)"),
    formula("НДС_КР  = (ТС + Пошлина [+ Фрахт при базисе «инвойс»]) × 12 %"),
    formula("Сборы   = 0,4 % × ТС (мин 500 / макс 250 000 KGS) + брокер 20 000 KGS"),
    formula("Очищенная стоимость = Инвойс + Пошлина + НДС_КР + Сборы"),
    h2("4.3. Поставка внутри ЕАЭС: ОсОО → российский ИП / ООО"),
    formula("Затраты ОсОО = товар + перевод поставщику (SWIFT/CIPS + спред) + фрахт"),
    formula("               + обработка + страхование + пошлина + сбор + брокер"),
    formula("               + НДС_КР (если не возмещается)"),
    formula("Цена поставки      = Затраты ОсОО × (1 + наценка агента 1–3 %)"),
    formula("НДС при ввозе в РФ = Цена поставки × 22 %   (затраты при УСН; к вычету при ОСНО)"),
    formula("Перевод RUB → KGS  = 0,5 % (мин 1 500 / макс 30 000 ₽) + спред 1 %"),
    h2("4.4. Итоговая стоимость (landed cost)"),
    formula("Итого_₽ = Σ компонентов по среднему курсу + валютный буфер δ_fx"),
    formula("          + сертификация + маркировка + техсбор + доставка по РФ"),
    formula("На единицу = Итого_₽ / количество единиц;   На кг = Итого_₽ / вес брутто"),
    p("Валютный буфер δ_fx применяется ровно один раз к каждому компоненту в иностранной валюте при его пересчёте в рубли и выделен отдельной строкой; сумма всех компонентов детализации равна итогу маршрута с точностью до копейки.", { size: 18 }),
    h2("4.5. Карго / упрощёнка"),
    formula("Итого = товар + перевод поставщику + карго-фрахт (всё включено) + страхование"),
    formula("        + наценка агента + перевод RUB → KGS + доставка по РФ"),
    p("Пошлина, НДС, сертификация и маркировка не начисляются — груз перемещается без декларации и документов, поэтому маршруту присваивается высокий (для обуви, одежды, электроники) или средний уровень риска.", { size: 18 }),
  ];
}

function routesSection() {
  const out = [h1("5. Сводная таблица маршрутов")];
  out.push(p("Маршруты отсортированы по возрастанию итоговой стоимости. Маршруты, не удовлетворяющие ограничению по сроку, помечены и исключены из рекомендаций.", { size: 18 }));
  out.push(table({
    columns: [
      { header: "№", width: 500, align: C }, { header: "Маршрут", width: 3300 }, { header: "Схема", width: 2000 }, { header: "Транспорт", width: 1500 },
      { header: "Итого, ₽", width: 1500, align: R }, { header: "₽ / ед.", width: 1100, align: R }, { header: "₽ / кг", width: 1000, align: R },
      { header: "Срок, дн.", width: 900, align: C }, { header: "Риск", width: 1400 }, { header: "Риск-скорр., ₽", width: 1370, align: R },
    ],
    rows: routes.map((r, i) => [
      String(i + 1),
      { text: r.route_name + (r.labels.length ? "\n" + r.labels.join(", ") : "") + (r.meets_deadline === false ? "\n(исключён: превышен срок)" : ""), bold: r.is_recommended, italics: true, fill: r.is_recommended ? "E2EFDA" : undefined },
      r.clearance_ru, `${r.transport_mode} → ${r.domestic_mode}`, money(r.total_cost_rub), money(r.cost_per_unit_rub), money(r.cost_per_kg_rub), r.days, r.risk_ru, money(r.risk_adjusted_cost_rub),
    ]),
    size: 15,
  }));
  return out;
}

function breakdownSection() {
  const out = [h1("6. Структура затрат по маршрутам (₽)")];
  out.push(p("Каждый столбец — один маршрут; строки — компоненты landed cost по среднему курсу, валютный буфер выделен отдельно. Сумма строк равна строке «Итого».", { size: 18 }));
  const chunkSize = 6;
  for (let start = 0; start < routes.length; start += chunkSize) {
    const chunk = routes.slice(start, start + chunkSize);
    const colW = Math.floor((LANDSCAPE_WIDTH - 3200) / chunk.length);
    const widths = chunk.map(() => colW);
    widths[widths.length - 1] += LANDSCAPE_WIDTH - 3200 - colW * chunk.length;
    const columns = [{ header: "Компонент", width: 3200 }, ...chunk.map((r, i) => ({ header: `${start + i + 1}. ${r.route_name}`, width: widths[i], align: R }))];
    const rows = res.component_names.map(([key, label]) => [label, ...chunk.map((r) => money(r.breakdown[key]))]);
    rows.push([{ text: "ИТОГО", bold: true }, ...chunk.map((r) => ({ text: money(r.total_cost_rub), bold: true }))]);
    rows.push([{ text: "Возмещаемый НДС (не в итоге)", italics: true }, ...chunk.map((r) => money(r.recoverable_vat_rub))]);
    rows.push(["На единицу", ...chunk.map((r) => money(r.cost_per_unit_rub))]);
    rows.push(["На кг брутто", ...chunk.map((r) => money(r.cost_per_kg_rub))]);
    rows.push(["Расчётный вес, кг", ...chunk.map((r) => num(r.chargeable_weight_kg))]);
    rows.push(["Срок, дн.", ...chunk.map((r) => r.days)]);
    rows.push(["Уровень риска", ...chunk.map((r) => r.risk_ru)]);
    if (routes.some((r) => r.gross_margin_percent !== null && r.gross_margin_percent !== undefined)) {
      rows.push(["Валовая маржа при целевой цене, %", ...chunk.map((r) => r.gross_margin_percent === null || r.gross_margin_percent === undefined ? "—" : money(r.gross_margin_percent))]);
    }
    out.push(table({ columns, rows, size: 14 }));
    out.push(p(" "));
  }
  return out;
}

function detailedSection() {
  const out = [h1("7. Пошаговый расчёт по схемам")];
  out.push(p("Для каждой схемы приведён полный расчёт репрезентативного маршрута: физические параметры и фрахт, таможенное оформление, пересчёт в рубли с валютным буфером, налоги и сборы на российской стороне, итог.", { size: 18 }));
  data.detailed.forEach((d, idx) => {
    out.push(h2(`7.${idx + 1}. ${d.route_name} — ${d.clearance_ru}`));
    out.push(p([run("Тарифная линия: ", { size: 18, bold: true }), run(d.tariff_line, { size: 18 })]));
    out.push(p([run("Коридор: ", { size: 18, bold: true }), run(d.corridor_id, { size: 18, mono: true })]));
    out.push(h3("Шаг 1. Фрахт, страхование, платежи и таможенное оформление"));
    out.push(table({
      columns: [{ header: "№", width: 500, align: C }, { header: "Шаг", width: 2900 }, { header: "Формула / расчёт", width: 3900 }, { header: "Значение", width: 1500, align: R }, { header: "Ед.", width: 838, align: C }],
      rows: d.steps.map((s) => [s.n, s.title, { text: s.formula, mono: true }, money(s.value), s.unit]), size: 15,
    }));
    out.push(h3("Шаг 2. Пересчёт компонентов в рубли (средний курс + буфер δ_fx)"));
    out.push(table({
      columns: [{ header: "Компонент", width: 2400 }, { header: "Сумма", width: 1300, align: R }, { header: "Вал.", width: 700, align: C }, { header: "Курс", width: 1000, align: R }, { header: "₽ по курсу", width: 1500, align: R }, { header: "Буфер δ_fx, ₽", width: 1238, align: R }, { header: "₽ с буфером", width: 1500, align: R }],
      rows: [
        ...d.rub_table.map((r) => [r.component, money(r.amount), r.currency, num(r.mid_rate), money(r.rub_mid), money(r.buffer), money(r.rub_buffered)]),
        [{ text: "Итого буфер δ_fx", bold: true }, "", "", "", "", { text: money(d.buffer_total), bold: true }, ""],
      ], size: 15,
    }));
    out.push(h3("Шаг 3. Наценка, налоги в РФ, доставка и итог"));
    out.push(table({
      columns: [{ header: "№", width: 500, align: C }, { header: "Шаг", width: 2900 }, { header: "Формула / расчёт", width: 3900 }, { header: "Значение", width: 1500, align: R }, { header: "Ед.", width: 838, align: C }],
      rows: d.tail.map((s) => [s.n, { text: s.title, bold: s.title.startsWith("ИТОГО") }, { text: s.formula, mono: true }, { text: money(s.value), bold: s.title.startsWith("ИТОГО") }, s.unit]), size: 15,
    }));
    out.push(p(`Контроль: итог движка по маршруту — ${money(d.engine_total)} ₽ (компоненты округляются до копейки перед суммированием). Возмещаемый НДС, не входящий в итог: ${money(d.recoverable_vat_rub)} ₽.`, { size: 17, italics: true }));
  });
  return out;
}

function comparisonSection() {
  const c = data.comparison;
  const kg = c.kg, ru = c.ru;
  const out = [h1("8. Сравнение таможенного оформления: Кыргызстан (ЕАЭС) vs прямой ввоз в РФ")];
  out.push(p(`Одинаковый груз, одинаковая пошлина по ЕТТ ЕАЭС; фрахт до границы ${money(c.freight_usd)} USD (коридор ${c.corridor}). Суммы в национальной валюте юрисдикции и в рублях по среднему курсу.`, { size: 18 }));
  const rows = [
    ["Стоимость товара", money(kg.invoice), money(ru.invoice)],
    ["Фрахт до границы", money(kg.freight), money(ru.freight)],
    ["Таможенная стоимость", money(kg.customs_value), money(ru.customs_value)],
    [`Пошлина (${kg.duty_rule})`, money(kg.duty), money(ru.duty)],
    ["Ставка НДС, %", num(kg.vat_percent), num(ru.vat_percent)],
    ["База НДС", money(kg.vat_base), money(ru.vat_base)],
    ["НДС при ввозе", money(kg.vat), money(ru.vat)],
    ["Таможенный сбор", money(kg.processing_fee), money(ru.processing_fee)],
    ["Брокер", money(kg.broker), money(ru.broker)],
    [{ text: "Итого налоги и сборы", bold: true }, { text: money(kg.taxes_and_fees), bold: true }, { text: money(ru.taxes_and_fees), bold: true }],
    ["Очищенная стоимость (инвойс + налоги и сборы)", money(kg.cleared), money(ru.cleared)],
    ["Срок оформления, дн.", kg.days, ru.days],
    [{ text: "Итого налоги и сборы, ₽", bold: true }, { text: money(kg.taxes_and_fees_rub), bold: true }, { text: money(ru.taxes_and_fees_rub), bold: true }],
  ];
  out.push(table({ columns: [{ header: "Показатель", width: 3638 }, { header: `КР, ${kg.currency}`, width: 3000, align: R }, { header: `РФ, ${ru.currency}`, width: 3000, align: R }], rows, size: 17 }));
  out.push(p(`Разница (РФ − КР): ${money(c.difference_rub)} ₽; дешевле оформление в ${c.cheaper === "KG" ? "Кыргызстане" : "России"}.`, { size: 18, bold: true }));
  c.notes.forEach((n) => out.push(bullet(n, { size: 17 })));
  return out;
}

function scenariosSection() {
  const out = [h1("9. Сценарный анализ (чувствительность)")];
  out.push(p("Каждый сценарий пересчитывает все маршруты при изменённом допущении. В трёх последних столбцах — итоговая стоимость репрезентативных маршрутов «авто-стандарт»: белая схема через Бишкек, карго через Бишкек и прямой импорт в РФ.", { size: 18 }));
  out.push(table({
    columns: [{ header: "Код", width: 600, align: C }, { header: "Сценарий", width: 3200 }, { header: "Оптимальный (рекомендован)", width: 3000 }, { header: "Самый дешёвый", width: 2800 }, { header: "Белая КР, ₽", width: 1650, align: R }, { header: "Карго, ₽", width: 1650, align: R }, { header: "Прямой РФ, ₽", width: 1670, align: R }],
    rows: data.scenarios.map((s) => {
      const pick = (x) => (x ? `${x.name}\n${money(x.total)} ₽` : "—");
      return [s.code, s.title, pick(s.optimal), pick(s.cheapest), money(s.white), money(s.cargo), money(s.direct)];
    }),
    size: 15,
  }));
  const warned = data.scenarios.filter((s) => s.warnings.length);
  if (warned.length) {
    out.push(h3("Предупреждения по сценариям"));
    warned.forEach((s) => s.warnings.forEach((w) => out.push(bullet(`${s.code}: ${w}`, { size: 17 }))));
  }
  return out;
}

function extrasSection() {
  const out = [h1("10. Дополнительные расчёты: другие поставки")];
  data.extras.forEach((e, idx) => {
    out.push(h2(`10.${idx + 1}. ${e.title}`));
    const keys = new Set(["Страна отправления", "Город назначения (РФ)", "Категория", "Код ТН ВЭД", "Описание", "Вес брутто, кг", "Объём, м³", "Стоимость по инвойсу", "Количество единиц", "Целевой срок доставки, дней", "Бенчмарк: прямой импорт в РФ", "Дата расчёта"]);
    out.push(kvTable(e.inputs.filter(([k]) => keys.has(k))));
    out.push(p(" "));
    out.push(table({
      columns: [{ header: "Маршрут", width: 3400 }, { header: "Схема", width: 1700 }, { header: "Итого, ₽", width: 1400, align: R }, { header: "₽ / ед.", width: 1000, align: R }, { header: "Срок", width: 800, align: C }, { header: "Риск", width: 1338 }],
      rows: e.routes.map((r) => [{ text: r.route_name + (r.labels.length ? "\n" + r.labels.join(", ") : "") + (r.meets_deadline === false ? "\n(исключён: превышен срок)" : ""), bold: r.is_recommended, italics: true, fill: r.is_recommended ? "E2EFDA" : undefined }, r.clearance_ru, money(r.total_cost_rub), money(r.cost_per_unit_rub), r.days, r.risk_ru]),
      size: 15,
    }));
    const opt = e.routes.find((r) => r.route_id === e.optimal_id);
    if (opt) {
      out.push(p(`Рекомендованный маршрут: ${opt.route_name}. Пошлина ${money(opt.breakdown.customs_duty)} ₽, НДС КР ${money(opt.breakdown.import_vat_kg)} ₽, НДС РФ ${money(opt.breakdown.import_vat_ru)} ₽, фрахт ${money(opt.breakdown.international_freight)} ₽, доставка по РФ ${money(opt.breakdown.local_transport)} ₽, валютный буфер ${money(opt.breakdown.fx_risk_buffer)} ₽.`, { size: 17 }));
    }
    e.warnings.forEach((w) => out.push(bullet(w, { size: 17 })));
  });
  return out;
}

function tariffsSection() {
  return [
    h1("11. Встроенный справочник ставок ТН ВЭД"),
    p("Свер.: ✓ — ставка сверена с опубликованным ЕТТ ЕАЭС при составлении таблицы; ~ — справочная оценка, требует подтверждения по 10-значному коду. Марк.: обязательная маркировка «Честный ЗНАК».", { size: 17 }),
    table({
      columns: [{ header: "Код", width: 1300 }, { header: "Категория", width: 1300 }, { header: "Ставка", width: 2200 }, { header: "Описание", width: 3200 }, { header: "Марк.", width: 700, align: C }, { header: "Свер.", width: 938, align: C }],
      rows: data.tariffs.map((t) => [{ text: t.hs, mono: true }, t.category, t.rate, t.desc, t.marking, t.verified]), size: 15,
    }),
  ];
}

function notesSection() {
  const out = [h1("12. Примечания по маршрутам основного расчёта")];
  routes.forEach((r) => {
    out.push(h3(r.route_name));
    r.notes.forEach((n) => out.push(bullet(n, { size: 17 })));
  });
  return out;
}

function sourcesSection() {
  const out = [h1("13. Источники ставок и тарифов")];
  data.sources.forEach(([label, url]) => {
    out.push(bullet([run(label + ": ", { size: 17 }), new ExternalHyperlink({ link: url, children: [new TextRun({ text: url, style: "Hyperlink", font: FONT, size: 17 })] })]));
  });
  out.push(p(" "));
  out.push(p("Отказ от ответственности: расчёт носит планово-аналитический характер. Ставки пошлин, налогов, сборов и тарифы перевозчиков являются справочными на дату формирования и должны быть подтверждены у лицензированного таможенного представителя и экспедитора перед подачей декларации.", { size: 17, italics: true, color: "595959" }));
  return out;
}

// ------------------------------------------------------------------ document assembly
const headerFooter = {
  headers: { default: new Header({ children: [new Paragraph({ alignment: AlignmentType.RIGHT, children: [run("VED Calculator Core — выгрузка расчётов", { size: 16, color: "808080" })] })] }) },
  footers: { default: new Footer({ children: [new Paragraph({ alignment: C, children: [run("Стр. ", { size: 16, color: "808080" }), new TextRun({ children: [PageNumber.CURRENT], font: FONT, size: 16, color: "808080" }), run(" из ", { size: 16, color: "808080" }), new TextRun({ children: [PageNumber.TOTAL_PAGES], font: FONT, size: 16, color: "808080" })] })] }) },
};
const margins = { top: 1134, bottom: 1134, left: 1134, right: 1134 };
const portrait = { page: { size: { width: 11906, height: 16838 }, margin: margins } };
const landscape = { page: { size: { width: 11906, height: 16838, orientation: PageOrientation.LANDSCAPE }, margin: margins } };

const doc = new Document({
  creator: "VED Calculator Core",
  title: "Расчёт маршрутов ВЭД — полная выгрузка",
  description: "Landed cost, customs and logistics calculations",
  styles: {
    default: { document: { run: { font: FONT, size: 20 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 32, bold: true, color: "1F3864", font: FONT }, paragraph: { spacing: { before: 360, after: 160 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 26, bold: true, color: "2F5496", font: FONT }, paragraph: { spacing: { before: 280, after: 120 }, outlineLevel: 1 } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 22, bold: true, color: "404040", font: FONT }, paragraph: { spacing: { before: 200, after: 100 }, outlineLevel: 2 } },
    ],
  },
  numbering: { config: [{ reference: "bullets", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 540, hanging: 270 } } } }] }] },
  sections: [
    { properties: portrait, ...headerFooter, children: [...titlePage(), pageBreak(), ...summarySection(), ...inputsSection(), ...referenceSection(), ...methodologySection()] },
    { properties: landscape, ...headerFooter, children: [...routesSection(), ...breakdownSection()] },
    { properties: portrait, ...headerFooter, children: [...detailedSection(), ...comparisonSection()] },
    { properties: landscape, ...headerFooter, children: [...scenariosSection()] },
    { properties: portrait, ...headerFooter, children: [...extrasSection(), ...tariffsSection(), ...notesSection(), ...sourcesSection()] },
  ],
});

Packer.toBuffer(doc).then((buffer) => {
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  fs.writeFileSync(outputPath, buffer);
  console.log(`wrote ${outputPath} (${Math.round(buffer.length / 1024)} KB)`);
});
