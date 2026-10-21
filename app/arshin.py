"""Поиск результатов поверки во ФГИС «Аршин» (открытый API fgis.gost.ru/fundmetrology/eapi)."""
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta


API = "https://fgis.gost.ru/fundmetrology/eapi/vri"
CARD = "https://fgis.gost.ru/fundmetrology/cm/results/"  # карточка поверки для человека
PAUSE = 1.0  # секунд между запросами при массовом обновлении — чтобы «Аршин» не заблокировал сервер
MIT_RE = re.compile(r"^\d{1,6}-\d{2}$")  # № в госреестре СИ: 25405-03


class ArshinError(Exception):
    pass


def _fetch(params):
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "LabCompass/1.0 (+https://labcompass.ru)"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)
    except Exception as e:
        raise ArshinError(f"«Аршин» не ответил ({e.__class__.__name__}). Попробуйте позже.") from e


fetch = _fetch  # в тестах подменяется


def clean(s):
    """Убирает невидимые символы, которые иногда стоят в номерах в «Аршине»."""
    return re.sub(r"[^\w\-/.]", "", str(s or "")).upper()


def _date(s):
    try:
        return datetime.strptime(s, "%d.%m.%Y").date()
    except (TypeError, ValueError):
        return None


def search(serial, mit_number="", rows=20):
    """Записи о поверке прибора по заводскому номеру (и № госреестра), новые первыми."""
    serial = str(serial or "").strip()
    if not serial:
        return []
    params = {"mi_number": serial, "rows": rows, "sort": "verification_date desc"}
    if mit_number:
        params["mit_number"] = mit_number.strip()
    data = fetch(params)
    out = []
    for i in (data.get("result") or {}).get("items") or []:
        if clean(i.get("mi_number")) != clean(serial):
            continue
        d = _date(i.get("verification_date"))
        if not d:
            continue
        v = _date(i.get("valid_date"))
        out.append({
            "vri_id": i.get("vri_id", ""), "date": d.isoformat(), "valid": v.isoformat() if v else "",
            "docnum": i.get("result_docnum", ""), "org": i.get("org_title", ""), "ok": bool(i.get("applicability")),
            "mit_number": i.get("mit_number", ""), "mit_title": i.get("mit_title", ""),
            "notation": i.get("mit_notation", ""), "modification": i.get("mi_modification", ""),
        })
    out.sort(key=lambda r: r["date"], reverse=True)
    return out


def interval(d, valid):
    """Интервал в месяцах: поверка 19.02.2026, годна до 18.02.2027 → 12."""
    if not valid:
        return None
    end = date.fromisoformat(valid) + timedelta(days=1)
    start = date.fromisoformat(d)
    months = (end.year - start.year) * 12 + end.month - start.month + round((end.day - start.day) / 30)
    return months if months > 0 else None


def changes(rec):
    """Запись «Аршина» → поля оборудования. Непригоден — срока следующей нет."""
    return {"last_date": rec["date"], "next_date": rec["valid"] or None,
            "interval_months": interval(rec["date"], rec["valid"]), "doc_no": rec["docnum"],
            "arshin_bad": int(not rec["ok"])}


def apply(con, item, rec, when):
    ch = changes(rec)
    if ch["interval_months"] is None:
        ch["interval_months"] = item["interval_months"]
    if not item["mit_number"] and rec["mit_number"]:
        ch["mit_number"] = rec["mit_number"]
    con.execute(f"UPDATE equipment SET {', '.join(k + ' = ?' for k in ch)}, updated = ? WHERE id = ?",
                list(ch.values()) + [when, item["id"]])


def can_update(item):
    return item["kind"] == "СИ" and item["service"] == "поверка" and item["serial"] and item["mit_number"]


def update_all(con, items, when, pause=PAUSE):
    """Для всех СИ с заводским № и № госреестра берёт из «Аршина» поверку, если она новее.

    Возвращает отчёт: обновлено, без изменений, не найдено, пропущено (нет номеров), ошибки.
    """
    report = {"updated": [], "same": [], "missing": [], "skipped": [], "errors": []}
    first = True
    for it in items:
        if not can_update(it):
            if it["kind"] == "СИ" and it["service"] == "поверка":
                report["skipped"].append(it)
            continue
        if not first:
            time.sleep(pause)
        first = False
        try:
            recs = search(it["serial"], it["mit_number"])
        except ArshinError as e:
            report["errors"].append((it, str(e)))
            if len(report["errors"]) >= 3:  # «Аршин» лёг — не мучаем его дальше
                break
            continue
        if not recs:
            report["missing"].append(it)
        elif not it["last_date"] or recs[0]["date"] > it["last_date"]:
            apply(con, it, recs[0], when)
            con.commit()  # не держим базу занятой, пока ждём «Аршин»
            report["updated"].append((it, recs[0]))
        else:
            report["same"].append(it)
    return report


def card_url(vri_id):
    return CARD + urllib.parse.quote(vri_id) if vri_id else ""


def valid_mit(s):
    return not s or bool(MIT_RE.match(s.strip()))

