"""Заявки с сайта: разбор самопроверки на почту и форма «Расскажите о лаборатории»."""
import hashlib
import re
from datetime import datetime, timedelta

import db
import mailer

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SOURCES = {"check": "Самопроверка готовности", "contact": "Форма на сайте"}
MARKS = {"no": "нет", "part": "частично", "": "нет ответа"}


def clean(s, n):
    return re.sub(r"[\x00-\x08\x0b-\x1f]", "", str(s or "")).strip()[:n]


def check_report(data):
    """Данные самопроверки из браузера → (процент, текст разбора)."""
    score = data.get("score")
    score = int(score) if isinstance(score, (int, float)) and 0 <= score <= 100 else None
    lines = [f"Готовность: {score}%", "", "По разделам:"]
    for row in (data.get("sections") or [])[:20]:
        if isinstance(row, list) and len(row) == 2:
            lines.append(f"  {clean(row[0], 80)} — {int(row[1]) if isinstance(row[1], (int, float)) else '?'}%")
    gaps = (data.get("gaps") or [])[:60]
    lines += ["", "Что доработать (сначала ключевые):"]
    for i, g in enumerate(gaps, 1):
        if isinstance(g, dict):
            key = " [ключевой]" if g.get("key") else ""
            lines.append(f"{i}. {clean(g.get('text'), 300)} — {MARKS.get(g.get('a') or '', 'нет')}{key}")
    if not gaps:
        lines.append("Пробелов не отмечено.")
    return score, "\n".join(lines)


def save(data, ip):
    """Проверяет и сохраняет заявку, отправляет письма. Возвращает текст ошибки или None."""
    source = data.get("source") if data.get("source") in SOURCES else "contact"
    email = clean(data.get("email"), 200).lower()
    org = clean(data.get("org"), 200)
    message = clean(data.get("message"), 3000)
    if not EMAIL_RE.match(email):
        return "Проверьте адрес почты"
    if not data.get("consent"):
        return "Нужно согласие на обработку персональных данных"
    if data.get("website"):  # скрытое поле: его заполняют только роботы
        return None
    if source == "contact" and len(message) < 10:
        return "Опишите задачу в паре предложений"
    score, details = check_report(data) if source == "check" else (None, "")
    ip_hash = hashlib.sha256(("lc" + ip).encode()).hexdigest()[:16]
    since = (datetime.utcnow() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    with db.db() as con:
        by_email = con.execute("SELECT COUNT(*) FROM leads WHERE email = ? AND created > ?", (email, since)).fetchone()[0]
        by_ip = con.execute("SELECT COUNT(*) FROM leads WHERE ip_hash = ? AND created > ?", (ip_hash, since)).fetchone()[0]
        if by_email >= 3 or by_ip >= 10:
            return "Заявка уже получена. Если нужно что-то добавить — напишите на info@labcompass.ru"
        con.execute("INSERT INTO leads (source, email, org, message, score, details, ip_hash) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (source, email, org, message, score, details, ip_hash))
    head = f"{SOURCES[source]}\nПочта: {email}\nОрганизация: {org or '—'}\n"
    if message:
        head += f"Сообщение:\n{message}\n"
    mailer.send(db.LEADS_TO, f"Заявка с сайта: {SOURCES[source]} — {org or email}",
                head + ("\n" + details if details else ""), reply_to=email)
    if source == "check":
        mailer.send(email, f"Разбор самопроверки ЛабКомпас: {score}%",
                    "Здравствуйте!\n\nВы прошли самопроверку готовности лаборатории к аккредитации на labcompass.ru.\n"
                    "Ниже — ваши результаты.\n\n" + details +
                    "\n\nСамопроверка — ориентир, а не заключение эксперта.\n"
                    "Если хотите разобрать результаты и составить план доработки — просто ответьте на это письмо: "
                    "напишите, что за лаборатория и когда экспертиза.\n\n— ЛабКомпас, labcompass.ru")
    return None
