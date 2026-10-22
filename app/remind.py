"""Напоминания о сроках поверки и о ВЛК. Запускать раз в день (systemd-таймер): python3 remind.py

Письмо уходит, если у лаборатории:
- есть оборудование, до срока которого ровно 30 или 7 дней, или срок наступает сегодня;
- есть показатель ВЛК, до планового контроля которого ровно 7 дней, или контроль сегодня;
- за последние сутки внесён результат ВЛК, который не выполняет норматив или дал сигнал на контрольной карте.
В письме — весь список просроченного и того, что скоро, и все новые нарушения.
"""
import sys
from datetime import date, datetime, timedelta

import db
import equipment as eq
import mailer
import vlk

TRIGGER_DAYS = {30, 7, 0}
VLK_TRIGGER_DAYS = {7, 0}


def vlk_state(con, user, today, since):
    """Показатели ВЛК: (плановый контроль просрочен или скоро, новые нарушения, есть ли повод для письма)."""
    due, problems, trigger = [], [], False
    inds = con.execute("SELECT * FROM vlk_indicators WHERE user_id = ? AND archived = 0 ORDER BY name", (user["id"],)).fetchall()
    for ind in inds:
        rows = con.execute("SELECT * FROM vlk_results WHERE indicator_id = ? ORDER BY COALESCE(run_date, ''), id",
                           (ind["id"],)).fetchall()
        a = vlk.analyze(ind, rows, today)
        if a["due_status"] in ("overdue", "soon"):
            due.append((ind, a))
            trigger = trigger or a["due_left"] in VLK_TRIGGER_DAYS
        fresh = {r["id"] for r in rows if r["created"] >= since}
        bad = [r for r in a["results"] if r["id"] in fresh and "error" not in r and (not r["ok"] or r.get("signals"))]
        if bad:
            problems.append((ind, bad))
            trigger = True
    return due, problems, trigger


def letter(user, items, due=(), problems=()):
    org = " — " + user["org"] if user["org"] else ""
    lines = ["Здравствуйте!\n"]
    if items:
        lines.append(f"Сроки обслуживания оборудования{org}:\n")
        for title, st in (("Просрочено", "overdue"), (f"В ближайшие {eq.SOON_DAYS} дней", "soon")):
            part = [i for i in items if i["status"] == st]
            if part:
                lines.append(title + ":")
                lines += [f"  • {i['name']}{' зав. № ' + i['serial'] if i['serial'] else ''} — {i['service']} "
                          f"до {eq.ru(i['next_date'])}" for i in part]
                lines.append("")
        lines.append(f"Список и график в Excel: {db.BASE_URL}/app/equipment\n")
    if problems:
        lines.append(f"ВЛК: нарушения в новых результатах{org if not items else ''}:")
        for ind, bad in problems:
            for r in bad:
                what = "норматив не выполнен" if not r["ok"] else "; ".join(r["signals"])
                when = eq.ru(r["run_date"]) if r["run_date"] else "без даты"
                lines.append(f"  • {ind['name']} — {vlk.KINDS[r['kind']].lower()}, {when}: {what}")
        lines.append("Нужны анализ причин и корректирующие действия.\n")
    if due:
        lines.append("ВЛК: плановый контроль:")
        for ind, a in due:
            when = f"до {a['due'].strftime('%d.%m.%Y')}" if a["due"] else "контроль ещё не проводился"
            lines.append(f"  • {ind['name']} — {vlk.DUE_NAMES[a['due_status']].lower()} ({when})")
        lines.append("")
    if due or problems:
        lines.append(f"Показатели ВЛК: {db.BASE_URL}/app/vlk\n")
    lines.append("Отключить напоминания можно в профиле кабинета.\n— ЛабКомпас")
    return "\n".join(lines)


def subject(items, due, problems):
    parts = []
    if items:
        n = sum(1 for i in items if i["status"] == "overdue")
        parts.append(f"сроки поверки — {len(items)} поз." + (f", просрочено {n}" if n else ""))
    if problems:
        parts.append("нарушения ВЛК")
    elif due:
        parts.append("плановый контроль ВЛК")
    return "ЛабКомпас: " + "; ".join(parts)


def run(today=None):
    today = today or date.today()
    since = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    sent = 0
    with db.db() as con:
        users = con.execute("SELECT * FROM users WHERE remind = 1").fetchall()
        for user in users:
            rows = con.execute("SELECT * FROM equipment WHERE user_id = ? AND archived = 0 AND next_date IS NOT NULL "
                               "AND service != 'не требуется' ORDER BY next_date", (user["id"],)).fetchall()
            items = [i for i in eq.with_status(rows, today) if i["status"] in ("overdue", "soon")]
            due, problems, vlk_trigger = vlk_state(con, user, today, since)
            if not (any(i["days_left"] in TRIGGER_DAYS for i in items) or vlk_trigger):
                continue
            try:
                mailer.send(user["email"], subject(items, due, problems), letter(user, items, due, problems))
                sent += 1
            except Exception as e:  # одна ошибка почты не должна останавливать остальных
                print(f"Не отправлено {user['email']}: {e}", file=sys.stderr)
    print(f"Отправлено напоминаний: {sent}")
    return sent


if __name__ == "__main__":
    db.init()
    run()
