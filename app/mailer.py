"""Отправка писем через SMTP (почта info@labcompass.ru на timeweb)."""
import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, parseaddr

log = logging.getLogger("labcompass.mail")
sent = []  # последние письма; нужно тестам и для проверки без SMTP


def send(to, subject, text, reply_to=None):
    host = os.environ.get("SMTP_HOST", "")
    msg = EmailMessage()
    name, addr = parseaddr(os.environ.get("MAIL_FROM", "ЛабКомпас <info@labcompass.ru>"))
    msg["From"] = formataddr((name, addr))
    msg["To"] = to
    msg["Subject"] = subject
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(text)
    sent.append(msg)
    del sent[:-20]
    if not host:
        log.warning("SMTP_HOST не задан, письмо не отправлено: %s → %s\n%s", subject, to, text)
        return
    port = int(os.environ.get("SMTP_PORT", "465"))
    ctx = ssl.create_default_context()
    if port == 465:
        smtp = smtplib.SMTP_SSL(host, port, context=ctx, timeout=20)
    else:
        smtp = smtplib.SMTP(host, port, timeout=20)
        smtp.starttls(context=ctx)
    with smtp:
        smtp.login(os.environ.get("SMTP_USER", addr), os.environ.get("SMTP_PASSWORD", ""))
        smtp.send_message(msg)
