/*
 * Расчёты ВЛК по РМГ 76-2014 (n = 2). Работает в браузере и в Node.js (для тестов).
 * Логика повторяет vlk_calc/vlk.py.
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.VLK = factory();
})(typeof self !== "undefined" ? self : this, function () {
  // Коэффициенты РМГ 76-2014. Перед использованием сверить с действующей редакцией.
  const K = {
    Q_P2: 2.77,          // r = Q(P, 2)·σr при P = 0,95
    D2_CL: 1.128,        // средняя линия карты размахов
    D2_WARN: 2.834,      // предел предупреждения
    D2_ACTION: 3.686,    // предел действия
    ACCURACY_WARN: 0.67, // предел предупреждения карты точности, доля от К
    DELTA_LAB_K: 0.84,   // Δл = 0,84·Δ на этапе внедрения методики
  };

  const KINDS = {
    "повт": "Повторяемость",
    "прец": "Внутрилаб. прецизионность",
    "ок": "Точность (ОК)",
    "доб": "Точность (добавки)",
  };
  const FIELDS = {
    "повт": ["x1", "x2"],
    "прец": ["x1", "x2"],
    "ок": ["x1", "x2", "c"],
    "доб": ["x1", "x2", "c", "xd1", "xd2"],
  };
  const REQUIRED = {
    "повт": ["x1", "x2"],
    "прец": ["x1", "x2"],
    "ок": ["x1", "c"],
    "доб": ["x1", "c", "xd1"],
  };
  const FIELD_NAMES = { x1: "X₁", x2: "X₂", c: "C", xd1: "X′₁", xd2: "X′₂" };

  function num(s) {
    if (s === null || s === undefined) return null;
    s = String(s).trim().replace(/\s/g, "").replace(",", ".");
    if (!s) return null;
    const v = Number(s);
    return Number.isFinite(v) ? v : NaN;
  }

  function normKind(s) {
    s = String(s || "").trim().toLowerCase();
    if (s.startsWith("пов")) return "повт";
    if (s.startsWith("пре") || s.startsWith("вну")) return "прец";
    if (s.includes("доб")) return "доб";
    if (s === "ок" || s.includes("(ок)") || s.startsWith("обр")) return "ок";
    return "";
  }

  const mean = (a, b) => (b === null ? a : (a + b) / 2);

  function deltaLab(p) {
    if (p.useLab) return num(p.delta_lab);
    const d = num(p.delta);
    return d === null || Number.isNaN(d) ? d : K.DELTA_LAB_K * d;
  }

  /** Проверка одной строки. Возвращает null для пустой строки. */
  function evaluate(row, p) {
    const kind = normKind(row.kind);
    const v = {};
    let blank = true;
    for (const f of ["x1", "x2", "c", "xd1", "xd2"]) {
      v[f] = num(row[f]);
      if (v[f] !== null) blank = false;
    }
    if (blank && !kind) return null;
    if (!kind) return { error: "выберите вид контроля" };
    for (const f of FIELDS[kind]) {
      if (Number.isNaN(v[f])) return { kind, error: `${FIELD_NAMES[f]}: не число` };
    }
    const missing = REQUIRED[kind].filter((f) => v[f] === null);
    if (missing.length) return { kind, error: "заполните " + missing.map((f) => FIELD_NAMES[f]).join(", ") };

    const sigma_r = num(p.sigma_r), sigma_R = num(p.sigma_R), dl = deltaLab(p);
    const xbar = mean(v.x1, v.x2);
    if (!(xbar > 0)) return { kind, error: "X̄ должно быть больше нуля" };
    let value, norm, rel;

    if (kind === "повт" || kind === "прец") {
      const s = kind === "повт" ? sigma_r : sigma_R;
      if (!(s > 0)) return { kind, error: `укажите ${kind === "повт" ? "σr" : "σRл"} в параметрах` };
      value = Math.abs(v.x1 - v.x2);
      norm = K.Q_P2 * s / 100 * xbar;
      rel = value / xbar * 100;
    } else {
      if (!(dl > 0)) return { kind, error: "укажите Δ или Δл в параметрах" };
      if (!(v.c > 0)) return { kind, error: "C должно быть больше нуля" };
      if (kind === "ок") {
        value = Math.abs(xbar - v.c);
        norm = dl / 100 * v.c;
        rel = (xbar - v.c) / v.c * 100;
      } else {
        const xadd = mean(v.xd1, v.xd2);
        value = Math.abs(xadd - xbar - v.c);
        norm = Math.hypot(dl * xadd, dl * xbar) / 100;
        rel = (xadd - xbar - v.c) / v.c * 100;
      }
    }
    return { kind, xbar, value, norm, rel, ok: value <= norm };
  }

  /** Средняя линия, предел предупреждения, предел действия (в %). */
  function chartLimits(kind, p) {
    if (kind === "повт" || kind === "прец") {
      const s = num(kind === "повт" ? p.sigma_r : p.sigma_R);
      return { cl: K.D2_CL * s, warn: K.D2_WARN * s, action: K.D2_ACTION * s, twoSided: false };
    }
    const dl = deltaLab(p);
    return { cl: 0, warn: K.ACCURACY_WARN * dl, action: dl, twoSided: true };
  }

  /** Признаки нарушения стабильности. Возвращает {номер точки (с 1): [правила]}. */
  function findSignals(values, { cl, warn, action, twoSided }) {
    const out = {};
    const add = (i, rule) => {
      (out[i + 1] = out[i + 1] || []);
      if (!out[i + 1].includes(rule)) out[i + 1].push(rule);
    };
    const side = (v, limit) => (v > limit ? 1 : twoSided && v < -limit ? -1 : 0);

    values.forEach((v, i) => {
      if (side(v, action)) add(i, "выход за предел действия");
      if (i >= 2) {
        const sides = values.slice(i - 2, i + 1).map((x) => side(x, warn));
        for (const s of [1, -1]) {
          if (sides.filter((x) => x === s).length >= 2) {
            add(i - 2 + sides.lastIndexOf(s), "2 из 3 точек за пределом предупреждения");
          }
        }
      }
      if (i >= 8) {
        const w = values.slice(i - 8, i + 1);
        if (w.every((x) => x > cl) || w.every((x) => x < cl)) add(i, "9 точек подряд по одну сторону средней линии");
      }
      if (i >= 5) {
        const w = values.slice(i - 5, i + 1);
        const d = w.slice(1).map((x, j) => x - w[j]);
        if (d.every((x) => x > 0) || d.every((x) => x < 0)) add(i, "6 точек подряд монотонно растут или убывают");
      }
    });
    return out;
  }

  /** Разбор CSV/TSV из Excel: разделитель «;», «,» или табуляция. */
  function parseTable(text, delim) {
    text = text.replace(/^﻿/, "").replace(/\r/g, "");
    const lines = text.split("\n").filter((l) => l.trim());
    if (!lines.length) return [];
    const first = lines[0];
    delim = delim || (first.includes("\t") ? "\t" : first.includes(";") ? ";" : ",");
    return lines.map((l) => l.split(delim).map((c) => c.trim().replace(/^"|"$/g, "")));
  }

  const COLUMNS = ["date", "kind", "x1", "x2", "c", "xd1", "xd2"];
  const HEADER_ALIASES = { "дата": "date", "вид": "kind", x1: "x1", x2: "x2", c: "c", xd1: "xd1", xd2: "xd2" };

  /** Строки таблицы → объекты. Понимает файлы с заголовком (как у vlk.py) и без него. */
  function rowsFromTable(cells) {
    if (!cells.length) return [];
    const head = cells[0].map((h) => HEADER_ALIASES[h.toLowerCase()]);
    const hasHeader = head.filter(Boolean).length >= 2;
    const cols = hasHeader ? head : COLUMNS;
    return cells.slice(hasHeader ? 1 : 0).map((r) => {
      const o = { date: "", kind: "", x1: "", x2: "", c: "", xd1: "", xd2: "" };
      r.forEach((val, i) => { if (cols[i]) o[cols[i]] = val; });
      o.kind = normKind(o.kind);
      return o;
    });
  }

  function toCSV(rows) {
    const head = "дата;вид;x1;x2;c;xd1;xd2";
    const body = rows.map((r) => COLUMNS.map((c) => (r[c] || "").replace(/;/g, ",")).join(";"));
    return "﻿" + [head, ...body].join("\r\n") + "\r\n";
  }

  return { K, KINDS, FIELDS, REQUIRED, COLUMNS, num, normKind, deltaLab, evaluate, chartLimits, findSignals, parseTable, rowsFromTable, toCSV };
});
