"""ЛабКомпас: личный кабинет (labcompass.ru/app/). Запуск: uvicorn main:app --port 8000"""
import hashlib
import logging
import os
import secrets
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import db
import equipment as eq
import leads
import mailer

P = "/app"  # приложение живёт по адресу labcompass.ru/app/
SESSION_DAYS = 30
CODE_MINUTES = 10

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.mount(P + "/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
templates.env.globals.update(P=P, eq=eq, ru=eq.ru, FREE_LIMIT=db.FREE_LIMIT,
                             OPERATOR=os.environ.get("OPERATOR") or "владелец сайта labcompass.ru")
# Версия оформления в адресе: после обновления браузер не возьмёт старый app.css из кэша
templates.env.globals["CSS_V"] = hashlib.md5((Path(__file__).parent / "static" / "app.css").read_bytes()).hexdigest()[:8]
db.init()


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


def now():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def later(**kw):
    return (datetime.utcnow() + timedelta(**kw)).strftime("%Y-%m-%d %H:%M:%S")


def is_paid(user):
    return bool(user["paid_until"]) and user["paid_until"] >= date.today().isoformat()


class LoginRequired(Exception):
    pass


@app.exception_handler(LoginRequired)
def _login_required(request, exc):
    return RedirectResponse(P + "/login", 303)


@app.middleware("http")
async def check_origin(request: Request, call_next):
    """Защита от подделки форм с чужих сайтов: POST принимаем только со своего адреса."""
    if request.method == "POST":
        origin = request.headers.get("origin") or request.headers.get("referer")
        if origin and urlparse(origin).netloc != (request.headers.get("host") or ""):
            return Response("Запрос с чужого сайта отклонён", 403)
    return await call_next(request)


def current_user(request):
    token = request.cookies.get("lc_session")
    if not token:
        return None
    with db.db() as con:
        return con.execute(
            "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash = ? AND s.expires > ?",
            (sha(token), now())).fetchone()


def need_user(request):
    user = current_user(request)
    if not user:
        raise LoginRequired()
    return user


def page(request, name, user=None, status_code=200, **ctx):
    return templates.TemplateResponse(request, name, {"user": user, **ctx}, status_code=status_code)


# ---------- Вход по коду на почту ----------

@app.get(P, response_class=HTMLResponse, include_in_schema=False)
@app.get(P, response_class=HTMLResponse)
@app.get(P + "/", response_class=HTMLResponse)
def home(request: Request):
    return RedirectResponse(P + ("/equipment" if current_user(request) else "/login"), 303)


@app.get(P + "/login", response_class=HTMLResponse)
def login_form(request: Request):
    return page(request, "login.html")


@app.post(P + "/login", response_class=HTMLResponse)
def login_send(request: Request, email: str = Form(""), consent: str = Form("")):
    email = email.strip().lower()
    if "@" not in email or "." not in email.split("@")[-1] or len(email) > 200:
        return page(request, "login.html", error="Проверьте адрес почты", email=email, status_code=400)
    if not consent:
        return page(request, "login.html", error="Нужно согласие на обработку персональных данных",
                    email=email, status_code=400)
    with db.db() as con:
        recent = con.execute("SELECT COUNT(*), MAX(created) FROM login_codes WHERE email = ? AND created > ?",
                             (email, (datetime.utcnow() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"))
                             ).fetchone()
        if recent[0] >= 5 or (recent[1] and recent[1] > later(seconds=-60)):
            return page(request, "code.html", email=email,
                        error="Код уже отправлен. Новый можно запросить через минуту (не больше 5 в час).")
        code = f"{secrets.randbelow(1_000_000):06d}"
        con.execute("DELETE FROM login_codes WHERE email = ? AND expires < ?", (email, now()))
        con.execute("INSERT INTO login_codes (email, code_hash, expires) VALUES (?, ?, ?)",
                    (email, sha(email + code), later(minutes=CODE_MINUTES)))
    mailer.send(email, f"Код для входа в ЛабКомпас: {code}",
                f"Ваш код для входа: {code}\n\nКод действует {CODE_MINUTES} минут.\n"
                f"Если вы не запрашивали вход на {db.BASE_URL}{P}/, просто удалите это письмо.\n\n— ЛабКомпас")
    return page(request, "code.html", email=email)


@app.post(P + "/verify", response_class=HTMLResponse)
def login_verify(request: Request, email: str = Form(""), code: str = Form("")):
    email, code = email.strip().lower(), code.strip().replace(" ", "")
    with db.db() as con:
        row = con.execute("SELECT * FROM login_codes WHERE email = ? AND expires > ? ORDER BY id DESC LIMIT 1",
                          (email, now())).fetchone()
        if not row or row["attempts"] >= 5:
            return page(request, "login.html", email=email, error="Код устарел. Запросите новый.", status_code=400)
        if not secrets.compare_digest(row["code_hash"], sha(email + code)):
            con.execute("UPDATE login_codes SET attempts = attempts + 1 WHERE id = ?", (row["id"],))
            return page(request, "code.html", email=email, error="Неверный код", status_code=400)
        con.execute("DELETE FROM login_codes WHERE email = ?", (email,))
        con.execute("INSERT INTO users (email) VALUES (?) ON CONFLICT(email) DO NOTHING", (email,))
        con.execute("UPDATE users SET last_login = ?, is_admin = ? WHERE email = ?",
                    (now(), int(email in db.ADMIN_EMAILS), email))
        user = con.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        token = secrets.token_urlsafe(32)
        con.execute("DELETE FROM sessions WHERE expires < ?", (now(),))
        con.execute("INSERT INTO sessions VALUES (?, ?, ?)", (sha(token), user["id"], later(days=SESSION_DAYS)))
    resp = RedirectResponse(P + ("/equipment" if user["org"] else "/profile"), 303)
    resp.set_cookie("lc_session", token, max_age=SESSION_DAYS * 86400, httponly=True,
                    secure=db.COOKIE_SECURE, samesite="lax", path=P)
    return resp


@app.post(P + "/logout")
def logout(request: Request):
    token = request.cookies.get("lc_session")
    if token:
        with db.db() as con:
            con.execute("DELETE FROM sessions WHERE token_hash = ?", (sha(token),))
    resp = RedirectResponse(P + "/login", 303)
    resp.delete_cookie("lc_session", path=P)
    return resp


@app.get(P + "/privacy", response_class=HTMLResponse)
def privacy(request: Request):
    return page(request, "privacy.html", current_user(request))


# ---------- Профиль ----------

@app.get(P + "/profile", response_class=HTMLResponse)
def profile(request: Request):
    user = need_user(request)
    return page(request, "profile.html", user, paid=is_paid(user))


@app.post(P + "/profile")
def profile_save(request: Request, org: str = Form(""), remind: str = Form("")):
    user = need_user(request)
    with db.db() as con:
        con.execute("UPDATE users SET org = ?, remind = ? WHERE id = ?", (org.strip()[:200], int(bool(remind)), user["id"]))
    return RedirectResponse(P + "/equipment", 303)


# ---------- Оборудование ----------

FIELDS = ["name", "kind", "serial", "inv_no", "service", "last_date", "interval_months", "next_date",
          "doc_no", "place", "note"]


def active_count(con, user):
    return con.execute("SELECT COUNT(*) FROM equipment WHERE user_id = ? AND archived = 0", (user["id"],)).fetchone()[0]


def can_add(con, user, n=1):
    return is_paid(user) or active_count(con, user) + n <= db.FREE_LIMIT


def get_item(con, user, item_id):
    return con.execute("SELECT * FROM equipment WHERE id = ? AND user_id = ?", (item_id, user["id"])).fetchone()


def item_from_form(form):
    """Данные формы → (запись, ошибка)."""
    it = {f: str(form.get(f, "")).strip() for f in FIELDS}
    if not it["name"]:
        return it, "Укажите наименование"
    it["kind"] = it["kind"] if it["kind"] in eq.KINDS else "СИ"
    it["service"] = it["service"] if it["service"] in eq.SERVICES else "поверка"
    try:
        last = eq.parse_date(it["last_date"])
        interval = eq.parse_interval(it["interval_months"])
        nxt = eq.next_due(last, interval, eq.parse_date(it["next_date"]))
    except ValueError as e:
        return it, str(e).capitalize()
    it.update(last_date=last.isoformat() if last else None, interval_months=interval,
              next_date=nxt.isoformat() if nxt else None)
    return it, None


@app.get(P + "/equipment", response_class=HTMLResponse)
def equipment_list(request: Request, show: str = "", q: str = ""):
    user = need_user(request)
    with db.db() as con:
        rows = con.execute("SELECT * FROM equipment WHERE user_id = ? AND archived = ? "
                           "ORDER BY next_date IS NULL, next_date, name",
                           (user["id"], int(show == "archive"))).fetchall()
        count = active_count(con, user)
    items = eq.with_status(rows)
    totals = {s: sum(1 for i in items if i["status"] == s) for s in eq.STATUS_NAMES}
    if show in eq.STATUS_NAMES:
        items = [i for i in items if i["status"] == show]
    if q:
        ql = q.lower()
        items = [i for i in items if ql in (i["name"] + " " + i["serial"] + " " + i["inv_no"]).lower()]
    return page(request, "equipment.html", user, items=items, totals=totals, show=show, q=q,
                count=count, paid=is_paid(user), limit=db.FREE_LIMIT)


@app.get(P + "/equipment/new", response_class=HTMLResponse)
def equipment_new(request: Request):
    user = need_user(request)
    return page(request, "item.html", user, item={"kind": "СИ", "service": "поверка"})


@app.post(P + "/equipment/new", response_class=HTMLResponse)
async def equipment_create(request: Request):
    user = need_user(request)
    it, error = item_from_form(await request.form())
    with db.db() as con:
        if not error and not can_add(con, user):
            error = f"На бесплатном тарифе — до {db.FREE_LIMIT} единиц оборудования. Чтобы добавить больше, оформите подписку в профиле."
        if error:
            return page(request, "item.html", user, item=it, error=error, status_code=400)
        con.execute(f"INSERT INTO equipment (user_id, {', '.join(FIELDS)}) VALUES (?{', ?' * len(FIELDS)})",
                    [user["id"]] + [it[f] for f in FIELDS])
    return RedirectResponse(P + "/equipment", 303)


@app.get(P + "/equipment/{item_id}", response_class=HTMLResponse)
def equipment_edit(request: Request, item_id: int):
    user = need_user(request)
    with db.db() as con:
        it = get_item(con, user, item_id)
    if not it:
        return page(request, "message.html", user, text="Запись не найдена", status_code=404)
    return page(request, "item.html", user, item=dict(it))


@app.post(P + "/equipment/{item_id}", response_class=HTMLResponse)
async def equipment_update(request: Request, item_id: int):
    user = need_user(request)
    form = await request.form()
    with db.db() as con:
        old = get_item(con, user, item_id)
        if not old:
            return page(request, "message.html", user, text="Запись не найдена", status_code=404)
        action = form.get("action", "save")
        if action in ("archive", "restore"):
            if action == "restore" and not can_add(con, user):
                return page(request, "message.html", user, status_code=400,
                            text=f"На бесплатном тарифе — до {db.FREE_LIMIT} единиц оборудования.")
            con.execute("UPDATE equipment SET archived = ?, updated = ? WHERE id = ?",
                        (int(action == "archive"), now(), item_id))
            return RedirectResponse(P + "/equipment", 303)
        it, error = item_from_form(form)
        if error:
            return page(request, "item.html", user, item={**it, "id": item_id}, error=error, status_code=400)
        con.execute(f"UPDATE equipment SET {', '.join(f + ' = ?' for f in FIELDS)}, updated = ? WHERE id = ?",
                    [it[f] for f in FIELDS] + [now(), item_id])
    return RedirectResponse(P + "/equipment", 303)


@app.post(P + "/equipment/{item_id}/done")
def equipment_done(request: Request, item_id: int, done_date: str = Form(""), doc_no: str = Form("")):
    """Отметить выполненную поверку: новая дата → срок пересчитывается по интервалу."""
    user = need_user(request)
    with db.db() as con:
        it = get_item(con, user, item_id)
        if not it:
            return page(request, "message.html", user, text="Запись не найдена", status_code=404)
        try:
            d = eq.parse_date(done_date) or date.today()
        except ValueError as e:
            return page(request, "message.html", user, text=str(e).capitalize(), status_code=400)
        nxt = eq.next_due(d, it["interval_months"])
        con.execute("UPDATE equipment SET last_date = ?, next_date = ?, doc_no = ?, updated = ? WHERE id = ?",
                    (d.isoformat(), nxt.isoformat() if nxt else None, doc_no.strip() or it["doc_no"], now(), item_id))
    return RedirectResponse(P + "/equipment", 303)


@app.get(P + "/import", response_class=HTMLResponse)
def import_form(request: Request):
    user = need_user(request)
    return page(request, "import.html", user)


@app.post(P + "/import", response_class=HTMLResponse)
def import_save(request: Request, text: str = Form("")):
    user = need_user(request)
    items, errors = eq.parse_paste(text)
    if errors or not items:
        return page(request, "import.html", user, text=text, status_code=400,
                    errors=errors or ["Не нашёл ни одной строки с наименованием"])
    with db.db() as con:
        if not can_add(con, user, len(items)):
            free = max(0, db.FREE_LIMIT - active_count(con, user))
            return page(request, "import.html", user, text=text, status_code=400,
                        errors=[f"В списке {len(items)} позиций, на бесплатном тарифе можно добавить ещё {free}."])
        cols = [f for f in FIELDS if f in items[0]]
        con.executemany(f"INSERT INTO equipment (user_id, {', '.join(cols)}) VALUES (?{', ?' * len(cols)})",
                        [[user["id"]] + [i[c] for c in cols] for i in items])
    return RedirectResponse(P + "/equipment", 303)


@app.get(P + "/equipment.xlsx")
def equipment_xlsx(request: Request):
    user = need_user(request)
    with db.db() as con:
        rows = con.execute("SELECT * FROM equipment WHERE user_id = ? AND archived = 0 "
                           "ORDER BY next_date IS NULL, next_date, name", (user["id"],)).fetchall()
    data = eq.to_xlsx(eq.with_status(rows), user["org"])
    name = f"grafik-poverki-{date.today().isoformat()}.xlsx"
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


# ---------- Админка ----------

@app.get(P + "/admin", response_class=HTMLResponse)
def admin(request: Request):
    user = need_user(request)
    if not user["is_admin"]:
        return page(request, "message.html", user, text="Нет доступа", status_code=403)
    with db.db() as con:
        users = con.execute("SELECT u.*, (SELECT COUNT(*) FROM equipment e WHERE e.user_id = u.id AND e.archived = 0) AS items "
                            "FROM users u ORDER BY u.created DESC").fetchall()
    return page(request, "admin.html", user, users=users, today=date.today().isoformat())


@app.post(P + "/admin/{uid}")
def admin_set_paid(request: Request, uid: int, paid_until: str = Form("")):
    user = need_user(request)
    if not user["is_admin"]:
        return page(request, "message.html", user, text="Нет доступа", status_code=403)
    try:
        d = eq.parse_date(paid_until)
    except ValueError as e:
        return page(request, "message.html", user, text=str(e).capitalize(), status_code=400)
    with db.db() as con:
        con.execute("UPDATE users SET paid_until = ? WHERE id = ?", (d.isoformat() if d else None, uid))
    return RedirectResponse(P + "/admin", 303)


# ---------- Заявки с сайта ----------

@app.post(P + "/lead")
async def lead(request: Request):
    """Приём заявки из самопроверки и формы на главной (JSON)."""
    try:
        data = await request.json()
    except ValueError:
        data = None
    if not isinstance(data, dict):
        return JSONResponse({"error": "Неверный запрос"}, 400)
    try:
        error = leads.save(data, request.client.host if request.client else "")
    except Exception:  # заявка уже сохранена, а почта не ушла — пользователю всё равно отвечаем «принято»
        logging.exception("Ошибка отправки письма по заявке")
        error = None
    if error:
        return JSONResponse({"error": error}, 400)
    return {"ok": True}


def need_admin(request):
    user = need_user(request)
    return user if user["is_admin"] else None


@app.get(P + "/admin/leads", response_class=HTMLResponse)
def admin_leads(request: Request):
    user = need_admin(request)
    if not user:
        return page(request, "message.html", need_user(request), text="Нет доступа", status_code=403)
    with db.db() as con:
        rows = con.execute("SELECT * FROM leads ORDER BY id DESC LIMIT 500").fetchall()
    return page(request, "leads.html", user, leads=rows, sources=leads.SOURCES)


@app.post(P + "/admin/leads/{lead_id}")
def admin_lead_status(request: Request, lead_id: int, status: str = Form("")):
    user = need_admin(request)
    if not user:
        return page(request, "message.html", need_user(request), text="Нет доступа", status_code=403)
    if status in LEAD_STATUSES:
        with db.db() as con:
            con.execute("UPDATE leads SET status = ? WHERE id = ?", (status, lead_id))
    return RedirectResponse(P + "/admin/leads", 303)


LEAD_STATUSES = ["новая", "в работе", "договор", "отказ"]
templates.env.globals["LEAD_STATUSES"] = LEAD_STATUSES
