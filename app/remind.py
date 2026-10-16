"""Напоминания о сроках поверки. Запускать раз в день (systemd-таймер): python3 remind.py

Письмо уходит, если у лаборатории есть позиция, до срока которой ровно 30 или 7 дней,
или срок наступает сегодня. В письме — весь список просроченного и того, что скоро.
"""
import sys
from datetime import date

import db
import equipment as eq
import mailer

TRIGGER_DAYS = {30, 7, 0}


def letter(user, items):
    lines = [f"Здравствуйте!\n\nСроки обслуживания оборудования{' — ' + user['org'] if user['org'] else ''}:\n"]
    for title, st in (("Просрочено", "overdue"), (f"В ближайшие {eq.SOON_DAYS} дней", "soon")):
        part = [i for i in items if i["status"] == st]
        if part:
            lines.append(title + ":")
            lines += [f"  • {i['name']}{' зав. № ' + i['serial'] if i['serial'] else ''} — {i['service']} "
                      f"до {eq.ru(i['next_date'])}" for i in part]
            lines.append("")
    lines.append(f"Список и график в Excel: {db.BASE_URL}/app/equipment\n")
    lines.append("Отключить напоминания можно в профиле кабинета.\n— ЛабКомпас")
    return "\n".join(lines)


def run(today=None):
    today = today or date.today()
    sent = 0
    with db.db() as con:
        users = con.execute("SELECT * FROM users WHERE remind = 1").fetchall()
        for user in users:
            rows = con.execute("SELECT * FROM equipment WHERE user_id = ? AND archived = 0 AND next_date IS NOT NULL "
                               "AND service != 'не требуется' ORDER BY next_date", (user["id"],)).fetchall()
            items = [i for i in eq.with_status(rows, today) if i["status"] in ("overdue", "soon")]
            if not any(i["days_left"] in TRIGGER_DAYS for i in items):
                continue
            n = sum(1 for i in items if i["status"] == "overdue")
            subject = f"ЛабКомпас: сроки поверки — {len(items)} поз." + (f", просрочено {n}" if n else "")
            try:
                mailer.send(user["email"], subject, letter(user, items))
                sent += 1
            except Exception as e:  # одна ошибка почты не должна останавливать остальных
                print(f"Не отправлено {user['email']}: {e}", file=sys.stderr)
    print(f"Отправлено напоминаний: {sent}")
    return sent


if __name__ == "__main__":
    db.init()
    run()
