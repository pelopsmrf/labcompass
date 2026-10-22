"""ВЛК в кабинете: расчёты по РМГ 76-2014 (n = 2), контрольные карты Шухарта, статусы, разбор вставки из Excel.

Формулы те же, что в vlk_calc/vlk.py и vlk_web/src/vlk-core.js (проверены тестами друг против друга).
"""
import html
import json
import math
from datetime import date, timedelta

import equipment as eq

# Коэффициенты РМГ 76-2014. Перед использованием сверить с действующей редакцией.
Q_P2 = 2.77          # r = Q(P, 2)·σr при P = 0,95
D2_CL = 1.128        # средняя линия карты размахов
D2_WARN = 2.834      # предел предупреждения
D2_ACTION = 3.686    # предел действия
ACCURACY_WARN = 0.67 # предел предупреждения карты точности, доля от К
DELTA_LAB_K = 0.84   # Δл = 0,84·Δ на этапе внедрения методики

KINDS = {
    "повт": "Повторяемость",
    "прец": "Внутрилаб. прецизионность",
    "ок": "Точность (ОК)",
    "доб": "Точность (добавки)",
}
FIELDS = {
    "повт": ["x1", "x2"],
    "прец": ["x1", "x2"],
    "ок": ["x1", "x2", "c"],
    "доб": ["x1", "x2", "c", "xd1", "xd2"],
}
REQUIRED = {
    "повт": ["x1", "x2"],
    "прец": ["x1", "x2"],
    "ок": ["x1", "c"],
    "доб": ["x1", "c", "xd1"],
}
VALUES = ["x1", "x2", "c", "xd1", "xd2"]
FIELD_NAMES = {"x1": "X₁", "x2": "X₂", "c": "C", "xd1": "X′₁", "xd2": "X′₂"}

# Периодичность контроля: ключ → (название, месяцев, дней)
PERIODS = {
    "": ("не задана", 0, 0),
    "week": ("еженедельно", 0, 7),
    "2weeks": ("раз в 2 недели", 0, 14),
    "month": ("ежемесячно", 1, 0),
    "quarter": ("ежеквартально", 3, 0),
    "half": ("раз в полгода", 6, 0),
    "year": ("ежегодно", 12, 0),
}
DUE_SOON_DAYS = 7  # «скоро контроль» — за столько дней

STATUS_NAMES = {"bad": "Нарушение", "warn": "Предупреждение", "ok": "Норма", "none": "Нет данных"}
DUE_NAMES = {"overdue": "Контроль просрочен", "soon": "Скоро контроль", "ok": "По графику", "none": "Периодичность не задана"}

IMPORT_COLUMNS = ["Дата", "Вид контроля", "X₁", "X₂", "C", "X′₁", "X′₂", "Исполнитель"]


# ---------- числа и строки ----------

def num(s):
    """Число из строки (десятичная запятая, пробелы); пусто → None; не число → nan."""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    s = str(s).strip().replace(" ", "").replace(" ", "").replace(",", ".")
    if not s:
        return None
    try:
        v = float(s)
    except ValueError:
        return math.nan
    return v if math.isfinite(v) else math.nan


def is_nan(v):
    return isinstance(v, float) and math.isnan(v)


def norm_kind(s):
    s = str(s or "").strip().lower()
    if s in KINDS:
        return s
    if s.startswith("пов"):
        return "повт"
    if s.startswith("пре") or s.startswith("вну"):
        return "прец"
    if "доб" in s:
        return "доб"
    if s == "ок" or "(ок)" in s or s.startswith("обр") or s.startswith("точ"):
        return "ок"
    return ""


def fmt(x):
    """3 значащие цифры, десятичная запятая: 0,0123; 12,3; 1 230."""
    if x is None:
        return ""
    if x == 0:
        return "0"
    v = float(f"{x:.3g}")
    s = f"{v:,.6f}".rstrip("0").rstrip(".") if abs(v) < 1e6 else f"{v:,.0f}"
    return s.replace(",", " ").replace(".", ",")


def pct(x):
    return f"{x:.1f}".replace(".", ",")


# ---------- расчёт ----------

def delta_lab(p):
    if p.get("use_lab"):
        return p.get("delta_lab")
    d = p.get("delta")
    return DELTA_LAB_K * d if d else d


def mean(a, b):
    return a if b is None else (a + b) / 2


def check_values(kind, v):
    """Проверка введённых чисел (без параметров методики). Возвращает текст ошибки или None."""
    if kind not in KINDS:
        return "выберите вид контроля"
    for f in FIELDS[kind]:
        if is_nan(v.get(f)):
            return f"{FIELD_NAMES[f]}: не число"
    missing = [FIELD_NAMES[f] for f in REQUIRED[kind] if v.get(f) is None]
    if missing:
        return "заполните " + ", ".join(missing)
    if not mean(v["x1"], v.get("x2")) > 0:
        return "X̄ должно быть больше нуля"
    if kind in ("ок", "доб") and not v["c"] > 0:
        return "C должно быть больше нуля"
    return None


def evaluate(row, p):
    """Одна контрольная процедура. row: kind, x1..xd2 (числа или None); p: sigma_r, sigma_rl, delta, delta_lab, use_lab.

    Возвращает {kind, xbar, value, norm, rel, ok} или {kind, error}.
    """
    kind = row["kind"]
    v = {f: row.get(f) for f in VALUES}
    if not FIELDS.get(kind):
        return {"kind": kind, "error": "выберите вид контроля"}
    for f in VALUES:
        if f not in FIELDS[kind]:
            v[f] = None
    err = check_values(kind, v)
    if err:
        return {"kind": kind, "error": err}
    xbar = mean(v["x1"], v["x2"])
    if kind in ("повт", "прец"):
        s = p.get("sigma_r") if kind == "повт" else p.get("sigma_rl")
        if not (s and s > 0):
            return {"kind": kind, "error": f"укажите {'σr' if kind == 'повт' else 'σRл'} в параметрах"}
        value = abs(v["x1"] - v["x2"])
        norm = Q_P2 * s / 100 * xbar
        rel = value / xbar * 100
    else:
        dl = delta_lab(p)
        if not (dl and dl > 0):
            return {"kind": kind, "error": "укажите Δ или Δл в параметрах"}
        c = v["c"]
        if kind == "ок":
            value = abs(xbar - c)
            norm = dl / 100 * c
            rel = (xbar - c) / c * 100
        else:
            xadd = mean(v["xd1"], v["xd2"])
            value = abs(xadd - xbar - c)
            norm = math.hypot(dl * xadd, dl * xbar) / 100
            rel = (xadd - xbar - c) / c * 100
    return {"kind": kind, "xbar": xbar, "value": value, "norm": norm, "rel": rel, "ok": value <= norm}


def chart_limits(kind, p):
    """Средняя линия, предел предупреждения, предел действия (в %), двусторонняя ли карта."""
    if kind in ("повт", "прец"):
        s = p.get("sigma_r") if kind == "повт" else p.get("sigma_rl")
        return {"cl": D2_CL * s, "warn": D2_WARN * s, "action": D2_ACTION * s, "two_sided": False}
    dl = delta_lab(p)
    return {"cl": 0.0, "warn": ACCURACY_WARN * dl, "action": dl, "two_sided": True}


def find_signals(values, lim):
    """Признаки нарушения стабильности. Возвращает {номер точки (с 1): [правила]}."""
    cl, warn, action, two = lim["cl"], lim["warn"], lim["action"], lim["two_sided"]
    out = {}

    def add(i, rule):
        out.setdefault(i + 1, [])
        if rule not in out[i + 1]:
            out[i + 1].append(rule)

    def side(v, limit):
        if v > limit:
            return 1
        if two and v < -limit:
            return -1
        return 0

    for i, v in enumerate(values):
        if side(v, action):
            add(i, "выход за предел действия")
        if i >= 2:
            sides = [side(x, warn) for x in values[i - 2:i + 1]]
            for s in (1, -1):
                if sides.count(s) >= 2:
                    add(i - 2 + max(j for j, x in enumerate(sides) if x == s), "2 из 3 точек за пределом предупреждения")
        if i >= 8:
            w = values[i - 8:i + 1]
            if all(x > cl for x in w) or all(x < cl for x in w):
                add(i, "9 точек подряд по одну сторону средней линии")
        if i >= 5:
            w = values[i - 5:i + 1]
            d = [b - a for a, b in zip(w, w[1:])]
            if all(x > 0 for x in d) or all(x < 0 for x in d):
                add(i, "6 точек подряд монотонно растут или убывают")
    return out


def params_of(ind):
    """Параметры методики из записи показателя."""
    return {"sigma_r": ind["sigma_r"], "sigma_rl": ind["sigma_rl"], "delta": ind["delta"],
            "delta_lab": ind["delta_lab"], "use_lab": bool(ind["use_lab"])}


def next_control(ind, last, today=None):
    """Срок следующего контроля и его статус: (дата|None, overdue/soon/ok/none, дней осталось)."""
    _, months, days = PERIODS.get(ind["period"] or "", PERIODS[""])
    if not (months or days):
        return None, "none", None
    if not last:
        return None, "overdue", None  # периодичность задана, а контроля ещё не было
    d = eq.add_months(last, months) if months else last + timedelta(days=days)
    left = (d - (today or date.today())).days
    return d, "overdue" if left < 0 else "soon" if left <= DUE_SOON_DAYS else "ok", left


def analyze(ind, rows, today=None):
    """Всё, что нужно для карточки и списка: результаты по строкам, карты, сигналы, статусы."""
    p = params_of(ind)
    results = []
    for r in rows:
        res = evaluate(dict(r), p)
        res.update(id=r["id"], run_date=r["run_date"], performer=r["performer"],
                   **{f: r[f] for f in VALUES})
        results.append(res)
    charts, failed, signals = [], 0, 0
    status = "none"
    for kind, title in KINDS.items():
        items = [r for r in results if r["kind"] == kind and "error" not in r]
        if not items:
            continue
        lim = chart_limits(kind, p)
        sig = find_signals([r["rel"] for r in items], lim) if len(items) >= 3 else {}
        for i, r in enumerate(items, 1):
            r["point"] = i
            r["signals"] = sig.get(i, [])
        bad = sum(1 for r in items if not r["ok"])
        failed += bad
        signals += len(sig)
        last = items[-1]
        beyond_warn = last["rel"] > lim["warn"] or (lim["two_sided"] and last["rel"] < -lim["warn"])
        st = "bad" if not last["ok"] or last["signals"] else "warn" if beyond_warn else "ok"
        status = max(status, st, key=list(STATUS_NAMES)[::-1].index)
        charts.append({"kind": kind, "title": title, "lim": lim, "items": items, "bad": bad, "signals": sig,
                       "status": st, "svg": chart_svg(items, lim, sig) if len(items) >= 3 else ""})
    dates = [date.fromisoformat(r["run_date"]) for r in rows if r["run_date"]]
    last_date = max(dates) if dates else None
    due, due_status, due_left = next_control(ind, last_date, today)
    return {"results": results, "charts": charts, "failed": failed, "signals": signals,
            "errors": sum(1 for r in results if "error" in r), "status": status,
            "last_date": last_date, "due": due, "due_status": due_status, "due_left": due_left}


# ---------- контрольная карта (SVG) ----------

def nice_step(rng):
    raw = rng / 5
    p = 10 ** math.floor(math.log10(raw))
    m = raw / p
    return (1 if m < 1.5 else 2 if m < 3.5 else 5 if m < 7.5 else 10) * p


def chart_svg(items, lim, sig):
    """Контрольная карта Шухарта — та же картинка, что в калькуляторе /vlk/."""
    W, H, ml, mr, mt, mb = 760, 270, 46, 14, 12, 36
    ys = [r["rel"] for r in items]
    top = max([lim["action"]] + [abs(y) for y in ys]) * 1.12
    bottom = -top if lim["two_sided"] else 0
    n = len(items)
    sx = lambda i: round(ml + (i + 0.5) * (W - ml - mr) / n, 2)  # noqa: E731
    sy = lambda v: round(mt + (top - v) / (top - bottom) * (H - mt - mb), 2)  # noqa: E731
    out = []
    step = nice_step(top - bottom)
    v = math.ceil(bottom / step) * step
    while v <= top + 1e-9:
        out.append(f'<line x1="{ml}" x2="{W - mr}" y1="{sy(v)}" y2="{sy(v)}" stroke="#ececec"/>'
                   f'<text x="{ml - 6}" y="{sy(v) + 4}" text-anchor="end">{fmt(round(v, 2))}</text>')
        v += step

    def hline(v, color, dash, w=1.2):
        out.append(f'<line x1="{ml}" x2="{W - mr}" y1="{sy(v)}" y2="{sy(v)}" stroke="{color}" stroke-width="{w}"'
                   + (' stroke-dasharray="6 4"' if dash else "") + "/>")

    hline(lim["cl"], "#555", False, 1)
    for s in ((1, -1) if lim["two_sided"] else (1,)):
        hline(s * lim["warn"], "#d08a1a", True)
        hline(s * lim["action"], "#b03030", False, 1.4)
    out.append('<polyline fill="none" stroke="#2f5d8a" stroke-width="1.6" points="'
               + " ".join(f"{sx(i)},{sy(y)}" for i, y in enumerate(ys)) + '"/>')
    for i, r in enumerate(items):
        when = eq.ru(r["run_date"]) if r["run_date"] else ""
        tip = html.escape(f"Точка {i + 1}{' (' + when + ')' if when else ''}: {pct(r['rel'])} %"
                          + ("" if r["ok"] else " — норматив не выполнен"))
        if sig.get(i + 1):
            out.append(f'<circle cx="{sx(i)}" cy="{sy(r["rel"])}" r="9" fill="none" stroke="#b03030" stroke-width="1.8"/>')
        out.append(f'<circle cx="{sx(i)}" cy="{sy(r["rel"])}" r="{3.5 if r["ok"] else 5}" '
                   f'fill="{"#2f5d8a" if r["ok"] else "#b03030"}"><title>{tip}</title></circle>')
    every = math.ceil(n / 15)
    for i in range(n):
        if i % every == 0 or i == n - 1:
            out.append(f'<text x="{sx(i)}" y="{H - mb + 16}" text-anchor="middle">{i + 1}</text>')
    out.append(f'<line x1="{ml}" x2="{W - mr}" y1="{H - mb}" y2="{H - mb}" stroke="#999"/>'
               f'<text x="{(ml + W - mr) / 2}" y="{H - 4}" text-anchor="middle" fill="#66727f">Номер точки на карте</text>'
               f'<text transform="translate(12 {(mt + H - mb) / 2}) rotate(-90)" text-anchor="middle" fill="#66727f">'
               f'{"отклонение, % от C" if lim["two_sided"] else "% от X̄"}</text>')
    return (f'<svg viewBox="0 0 {W} {H}" font-size="11" font-family="system-ui, Arial, sans-serif" role="img" '
            f'aria-label="Контрольная карта">{"".join(out)}</svg>')


# ---------- ввод данных ----------

def row_from(cells):
    """Ячейки [дата, вид, x1, x2, c, xd1, xd2, исполнитель] → (запись, ошибка)."""
    cells = [str(c if c is not None else "").strip() for c in cells] + [""] * 8
    kind = norm_kind(cells[1])
    try:
        d = eq.parse_date(cells[0])
    except ValueError as e:
        return None, str(e)
    v = {f: num(c) for f, c in zip(VALUES, cells[2:7])}
    if kind:
        v = {f: (v[f] if f in FIELDS[kind] else None) for f in VALUES}
    err = check_values(kind, v) if kind else f"не понимаю вид контроля «{cells[1]}»" if cells[1] else "не указан вид контроля"
    if err:
        return None, err
    return {"run_date": d.isoformat() if d else None, "kind": kind, **v, "performer": cells[7][:100]}, None


def parse_paste(text):
    """Строки из Excel (через табуляцию или «;») → (записи, ошибки). Строку заголовка пропускаем."""
    rows, errors = [], []
    for n, line in enumerate(text.replace("\r", "").split("\n"), 1):
        if not line.strip():
            continue
        cells = line.split("\t") if "\t" in line else line.split(";")
        head = " ".join(cells[:2]).lower()
        if "дата" in head or "вид" in head:
            continue
        row, err = row_from(cells)
        if err:
            errors.append(f"строка {n}: {err}")
        else:
            rows.append(row)
    return rows, errors


def parse_project(text):
    """Файл .vlk.json из калькулятора /vlk/ → (параметры показателя, записи, ошибки)."""
    try:
        data = json.loads(text)
    except ValueError:
        return None, [], ["это не файл проекта калькулятора ВЛК (.vlk.json)"]
    if not isinstance(data, dict) or not isinstance(data.get("params"), dict) or not isinstance(data.get("rows"), list):
        return None, [], ["это не файл проекта калькулятора ВЛК (.vlk.json)"]
    p = data["params"]
    ind = {"name": str(p.get("name") or "").strip()[:200] or "Показатель из калькулятора",
           "units": str(p.get("units") or "").strip()[:50],
           "use_lab": int(bool(p.get("useLab")))}
    for k, src in (("sigma_r", "sigma_r"), ("sigma_rl", "sigma_R"), ("delta", "delta"), ("delta_lab", "delta_lab")):
        v = num(p.get(src))
        ind[k] = None if v is None or is_nan(v) else v
    rows, errors = [], []
    for n, r in enumerate(data["rows"], 1):
        if not isinstance(r, dict) or not any(str(r.get(k) or "").strip() for k in ["kind"] + VALUES):
            continue
        row, err = row_from([r.get("date"), r.get("kind")] + [r.get(f) for f in VALUES])
        if err:
            errors.append(f"строка {n}: {err}")
        else:
            rows.append(row)
    return ind, rows, errors


def indicator_from_form(form):
    """Форма параметров показателя → (запись, ошибка)."""
    it = {k: str(form.get(k, "")).strip() for k in ("name", "method", "range_text", "units", "note", "period")}
    it["name"] = it["name"][:200]
    it["method"] = it["method"][:300]
    it["range_text"] = it["range_text"][:100]
    it["units"] = it["units"][:50]
    it["note"] = it["note"][:500]
    if it["period"] not in PERIODS:
        it["period"] = ""
    it["use_lab"] = int(form.get("use_lab") == "1")
    error = None if it["name"] else "Укажите показатель (что определяем)"
    names = {"sigma_r": "σr", "sigma_rl": "σRл", "delta": "Δ", "delta_lab": "Δл"}
    for k, title in names.items():
        raw = str(form.get(k, "")).strip()
        v = num(raw)
        if is_nan(v) or (v is not None and not 0 < v < 1000):
            it[k] = raw
            error = error or f"{title}: нужно положительное число в процентах"
        else:
            it[k] = v
    return it, error
