"""
ЛабКомпас.ВЛК — калькулятор внутрилабораторного контроля (ВЛК) по РМГ 76-2014.

Читает CSV с результатами контрольных процедур, проверяет нормативы
оперативного контроля, строит контрольные карты Шухарта, ищет признаки
нарушения стабильности и формирует HTML-отчёт.

Пример запуска:
    python3 vlk.py example.csv --name "Аммоний-ион" --units "мг/дм³" \
        --sigma-r 4 --sigma-R 6 --delta 15
"""

import argparse
import base64
import csv
import html
import io
import math
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Коэффициенты РМГ 76-2014 для n = 2 параллельных определений.
# Перед использованием в лаборатории сверить с действующей редакцией.
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


# ---------- исходные данные ----------

@dataclass
class Params:
    name: str
    units: str
    sigma_r: float   # σr, % (относительное)
    sigma_R: float   # σRл, %
    delta_lab: float # Δл, %


@dataclass
class Check:
    n: int
    when: str
    kind: str
    xbar: float
    value: float      # Кк, rк или Rл,к (абсолютное)
    norm: float       # норматив К, r или Rл (абсолютный)
    rel: float        # значение для контрольной карты, %
    ok: bool = field(init=False)

    def __post_init__(self):
        self.ok = self.value <= self.norm


def to_float(s):
    s = (s or "").strip().replace(",", ".").replace(" ", "")
    return float(s) if s else None


def read_rows(path):
    """Читает CSV, сохранённый из Excel: разделитель «;» или «,», десятичная запятая."""
    text = Path(path).read_text(encoding="utf-8-sig")
    dialect = csv.Sniffer().sniff(text.splitlines()[0], delimiters=";,\t")
    rows = list(csv.DictReader(io.StringIO(text), dialect=dialect))
    return [{k.strip().lower(): (v or "").strip() for k, v in r.items() if k} for r in rows]


# ---------- расчёты ----------

def mean(a, b):
    return a if b is None else (a + b) / 2


def evaluate(row, n, p):
    kind = row["вид"].lower()
    x1, x2 = to_float(row.get("x1")), to_float(row.get("x2"))
    when = row.get("дата", "")

    if kind in ("повт", "прец"):
        xbar = mean(x1, x2)
        sigma = p.sigma_r if kind == "повт" else p.sigma_R
        value = abs(x1 - x2)
        norm = Q_P2 * sigma / 100 * xbar
        return Check(n, when, kind, xbar, value, norm, rel=value / xbar * 100)

    if kind == "ок":
        c = to_float(row["c"])
        xbar = mean(x1, x2)
        return Check(n, when, kind, xbar, abs(xbar - c), p.delta_lab / 100 * c,
                     rel=(xbar - c) / c * 100)

    if kind == "доб":
        c = to_float(row["c"])
        xbar = mean(x1, x2)
        xbar_add = mean(to_float(row["xd1"]), to_float(row.get("xd2")))
        value = abs(xbar_add - xbar - c)
        norm = math.hypot(p.delta_lab * xbar_add, p.delta_lab * xbar) / 100
        return Check(n, when, kind, xbar, value, norm,
                     rel=(xbar_add - xbar - c) / c * 100)

    raise ValueError(f"Строка {n}: неизвестный вид контроля «{row['вид']}». "
                     f"Допустимо: {', '.join(KINDS)}")


# ---------- контрольные карты ----------

def chart_limits(kind, p):
    """Средняя линия, предел предупреждения, предел действия (в %)."""
    if kind in ("повт", "прец"):
        s = p.sigma_r if kind == "повт" else p.sigma_R
        return D2_CL * s, D2_WARN * s, D2_ACTION * s
    return 0.0, ACCURACY_WARN * p.delta_lab, p.delta_lab


def find_signals(values, cl, warn, action, two_sided):
    """Признаки нарушения стабильности. Возвращает {номер точки: [правила]}."""
    out = {}

    def add(i, rule):
        out.setdefault(i + 1, [])
        if rule not in out[i + 1]:
            out[i + 1].append(rule)

    def side(v, limit):
        if v > limit:
            return 1
        if two_sided and v < -limit:
            return -1
        return 0

    for i, v in enumerate(values):
        if side(v, action):
            add(i, "выход за предел действия")
        if i >= 2:
            sides = [side(x, warn) for x in values[i - 2:i + 1]]
            for s in (1, -1):
                if sides.count(s) >= 2:
                    last = i - 2 + max(j for j, x in enumerate(sides) if x == s)
                    add(last, "2 из 3 точек за пределом предупреждения")
        if i >= 8:
            window = values[i - 8:i + 1]
            if all(x > cl for x in window) or all(x < cl for x in window):
                add(i, "9 точек подряд по одну сторону средней линии")
        if i >= 5:
            w = values[i - 5:i + 1]
            diffs = [b - a for a, b in zip(w, w[1:])]
            if all(d > 0 for d in diffs) or all(d < 0 for d in diffs):
                add(i, "6 точек подряд монотонно растут или убывают")
    return out


def plot_chart(checks, kind, p, signals):
    cl, warn, action = chart_limits(kind, p)
    two_sided = kind in ("ок", "доб")
    xs = [c.n for c in checks]
    ys = [c.rel for c in checks]

    fig, ax = plt.subplots(figsize=(8, 3.4), dpi=150)
    ax.plot(range(1, len(ys) + 1), ys, color="#2f5d8a", lw=1.3, marker="o", ms=4, zorder=3)
    ax.axhline(cl, color="#555555", lw=1, label=f"Средняя линия {cl:.1f} %")
    pm = "±" if two_sided else ""
    for sign in ((1, -1) if two_sided else (1,)):
        ax.axhline(sign * warn, color="#d08a1a", lw=1, ls="--",
                   label=f"ПП {pm}{warn:.1f} %" if sign == 1 else None)
        ax.axhline(sign * action, color="#b03030", lw=1.2,
                   label=f"ПД {pm}{action:.1f} %" if sign == 1 else None)
    bad = [(i, y) for i, (c, y) in enumerate(zip(checks, ys), start=1) if not c.ok]
    if bad:
        ax.scatter(*zip(*bad), s=30, color="#b03030", zorder=5, label="Норматив не выполнен")
    for i in signals:
        ax.scatter([i], [ys[i - 1]], s=90, facecolors="none", edgecolors="#b03030", lw=1.6, zorder=4)

    ax.set_title(f"{KINDS[kind]}: {p.name}", fontsize=10)
    ax.set_xlabel("Номер точки на карте")
    ax.set_ylabel("% от X̄" if not two_sided else "отклонение, % от C")
    top = max([action] + [abs(y) for y in ys]) * 1.2
    ax.set_ylim(-top if two_sided else 0, top)
    ax.set_xlim(0.5, len(ys) + 0.5)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.grid(axis="y", color="#e5e5e5", lw=0.6)
    ax.legend(fontsize=7.5, loc="upper left", frameon=False, ncol=4)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()


# ---------- отчёт ----------

def fmt(x):
    return f"{x:.3g}".replace(".", ",")


def build_report(checks, p, source):
    by_kind = {k: [c for c in checks if c.kind == k] for k in KINDS}
    failed = [c for c in checks if not c.ok]
    sections, all_signals = [], []

    for kind, items in by_kind.items():
        if not items:
            continue
        rows = "".join(
            f"<tr class='{'ok' if c.ok else 'bad'}'><td>{c.n}</td><td>{html.escape(c.when)}</td>"
            f"<td>{fmt(c.xbar)}</td><td>{fmt(c.value)}</td><td>{fmt(c.norm)}</td>"
            f"<td>{f'{c.rel:.1f}'.replace('.', ',')}</td><td>{'удовл.' if c.ok else 'НЕ удовл.'}</td></tr>"
            for c in items
        )
        block = (f"<h2>{KINDS[kind]}</h2><table><tr><th>№ строки</th><th>Дата</th><th>X̄</th>"
                 f"<th>Результат контроля</th><th>Норматив</th><th>На карте, %</th><th>Вывод</th></tr>{rows}</table>")

        if len(items) >= 3:
            cl, warn, action = chart_limits(kind, p)
            sig = find_signals([c.rel for c in items], cl, warn, action, kind in ("ок", "доб"))
            png = plot_chart(items, kind, p, sig)
            block += f"<img src='data:image/png;base64,{base64.b64encode(png).decode()}'>"
            if sig:
                lis = "".join(f"<li>Точка {i} (строка {items[i - 1].n}, {html.escape(items[i - 1].when)}): "
                              f"{'; '.join(r)}</li>" for i, r in sig.items())
                block += f"<p class='warn'>Признаки нарушения стабильности:</p><ul>{lis}</ul>"
                all_signals += [(kind, i) for i in sig]
            else:
                block += "<p>Признаков нарушения стабильности не выявлено.</p>"
        sections.append(block)

    verdict = ("<p class='okmsg'>Все контрольные процедуры удовлетворительны, "
               "признаков нарушения стабильности нет.</p>"
               if not failed and not all_signals else
               f"<p class='badmsg'>Неудовлетворительных результатов: {len(failed)}. "
               f"Сигналов по контрольным картам: {len(all_signals)}. "
               "Требуется анализ причин (раздел 9 процедуры ВЛК).</p>")

    style = """
    body{font-family:Arial,sans-serif;max-width:900px;margin:30px auto;color:#222;padding:0 16px}
    h1{font-size:22px} h2{font-size:17px;margin-top:28px;border-bottom:1px solid #ccc;padding-bottom:4px}
    table{border-collapse:collapse;width:100%;font-size:13px;margin:8px 0}
    td,th{border:1px solid #ccc;padding:4px 7px;text-align:center} th{background:#e8eef4}
    tr.bad td{background:#fbe3e3} img{max-width:100%;margin-top:8px}
    .warn,.badmsg{color:#b03030;font-weight:bold} .okmsg{color:#2c7a3f;font-weight:bold}
    .meta td{text-align:left} .small{font-size:12px;color:#666}"""
    meta = (f"<table class='meta'><tr><td>Показатель</td><td>{html.escape(p.name)}, {html.escape(p.units)}</td></tr>"
            f"<tr><td>Характеристики</td><td>σr = {p.sigma_r} %; σRл = {p.sigma_R} %; Δл = {p.delta_lab:.1f} %</td></tr>"
            f"<tr><td>Исходный файл</td><td>{html.escape(Path(source).name)}</td></tr>"
            f"<tr><td>Дата отчёта</td><td>{date.today():%d.%m.%Y}</td></tr></table>")
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>ЛабКомпас.ВЛК: {html.escape(p.name)}</title>"
            f"<style>{style}</style></head><body><h1>ЛабКомпас.ВЛК · отчёт о внутрилабораторном контроле</h1>{meta}{verdict}"
            + "".join(sections) +
            "<p class='small'>Расчёт по РМГ 76-2014 для n = 2. Коэффициенты и правила интерпретации "
            "необходимо сверить с действующей редакцией документа и процедурой ВЛК лаборатории.<br>"
            "ЛабКомпас · labcompass.ru</p>"
            "</body></html>")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Калькулятор ВЛК по РМГ 76-2014")
    ap.add_argument("csv", help="файл с результатами контроля")
    ap.add_argument("--name", default="Показатель", help="название показателя")
    ap.add_argument("--units", default="мг/дм³")
    ap.add_argument("--sigma-r", type=float, required=True, help="σr, %%")
    ap.add_argument("--sigma-R", type=float, required=True, help="σRл, %%")
    ap.add_argument("--delta", type=float, help="Δ методики, %% (тогда Δл = 0,84·Δ)")
    ap.add_argument("--delta-lab", type=float, help="Δл лаборатории, %% (если уже установлен)")
    ap.add_argument("-o", "--out", help="HTML-отчёт (по умолчанию рядом с CSV)")
    a = ap.parse_args(argv)

    if a.delta_lab is None and a.delta is None:
        ap.error("укажите --delta или --delta-lab")
    delta_lab = a.delta_lab if a.delta_lab is not None else DELTA_LAB_K * a.delta
    p = Params(a.name, a.units, a.sigma_r, a.sigma_R, delta_lab)

    try:
        checks = [evaluate(row, i, p) for i, row in enumerate(read_rows(a.csv), start=1)]
    except (KeyError, ValueError, TypeError) as e:
        sys.exit(f"Ошибка в данных: {e}")

    out = Path(a.out or Path(a.csv).with_suffix(".html"))
    out.write_text(build_report(checks, p, a.csv), encoding="utf-8")

    for c in checks:
        mark = "ok " if c.ok else "!!!"
        print(f"{mark} {c.n:3} {c.when:10} {KINDS[c.kind]:26} {fmt(c.value):>8} ≤ {fmt(c.norm):>8}")
    print(f"\nНеудовлетворительных: {sum(not c.ok for c in checks)} из {len(checks)}")
    print(f"Отчёт: {out}")


if __name__ == "__main__":
    main()
