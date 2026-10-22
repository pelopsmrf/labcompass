"""Тесты кабинета: python3 -m unittest test_app (нужны пакеты из requirements.txt и httpx)."""
import os
import re
import tempfile
import unittest
from datetime import date, timedelta

os.environ.update(DB_PATH=os.path.join(tempfile.mkdtemp(), "t.db"), SMTP_HOST="", ADMIN_EMAILS="boss@lab.ru",
                  FREE_LIMIT="3", COOKIE_SECURE="0")

from fastapi.testclient import TestClient  # noqa: E402

import json  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
from pathlib import Path  # noqa: E402

import arshin  # noqa: E402
import equipment as eq  # noqa: E402
import mailer  # noqa: E402
import main  # noqa: E402
import remind  # noqa: E402
import vlk  # noqa: E402

EXAMPLE = Path(__file__).parent.parent / "vlk_calc" / "example.csv"
CORE = Path(__file__).parent.parent / "vlk_web" / "src" / "vlk-core.js"
PARAMS = {"sigma_r": 4.0, "sigma_rl": 6.0, "delta": 15.0, "delta_lab": None, "use_lab": False}


def login(client, email):
    client.post("/app/login", data={"email": email, "consent": "1"})
    code = re.search(r"\d{6}", mailer.sent[-1]["Subject"]).group()
    return client.post("/app/verify", data={"email": email, "code": code}, follow_redirects=False)


class TestEquipment(unittest.TestCase):
    def test_dates(self):
        self.assertEqual(eq.add_months(date(2026, 1, 31), 1), date(2026, 2, 28))
        self.assertEqual(eq.parse_date("15.03.2026"), date(2026, 3, 15))
        self.assertEqual(eq.parse_interval("2 года"), 24)
        self.assertEqual(eq.next_due(date(2026, 3, 15), 12), date(2027, 3, 15))
        t = date(2026, 10, 16)
        self.assertEqual(eq.status("2026-10-15", t), ("overdue", -1))
        self.assertEqual(eq.status("2026-11-10", t)[0], "soon")
        self.assertEqual(eq.status("2027-01-01", t)[0], "ok")

    def test_paste(self):
        text = ("Наименование\tВид\n"
                "Весы ВЛ-210\tСИ\t1234\t0101\tповерка\t15.03.2026\t12\t\tС-ВЯ/1\n"
                "Термостат ТС-1/80\tиспыт.\t55\t\tаттестация\t01.02.2026\t1 год\n"
                "Плохая\tСИ\t\t\t\t32.13.2026\n")
        items, errors = eq.parse_paste(text)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["next_date"], "2027-03-15")
        self.assertEqual(items[1]["kind"], "ИО")
        self.assertEqual(items[1]["service"], "аттестация")
        self.assertEqual(len(errors), 1)


def fake_arshin(params):
    """Ответ «Аршина» без сети: два прибора с зав. № 1234 разных типов, у мегаомметра — две поверки."""
    items = [
        {"vri_id": "1-2", "org_title": "ФБУ «ЦСМ»", "mit_number": "25405-03", "mit_title": "Мегаомметры",
         "mi_modification": "Е6-24", "mi_number": "\ufffc1234", "verification_date": "20.10.2026",
         "valid_date": "19.10.2027", "result_docnum": "С-ВЭ/20-10-2026/2", "applicability": True},
        {"vri_id": "1-1", "org_title": "ФБУ «ЦСМ»", "mit_number": "25405-03", "mit_title": "Мегаомметры",
         "mi_number": "1234", "verification_date": "15.10.2025", "valid_date": "14.10.2026",
         "result_docnum": "С-ВЭ/15-10-2025/1", "applicability": True},
        {"vri_id": "1-3", "org_title": "ООО «Поверка»", "mit_number": "13590-01", "mit_title": "Весы",
         "mi_number": "1234", "verification_date": "01.09.2026", "result_docnum": "И-АР/01-09-2026/3",
         "applicability": False},
        {"vri_id": "1-4", "mit_number": "25405-03", "mi_number": "12345", "verification_date": "01.01.2026"},
    ]
    items = [i for i in items if not params.get("mit_number") or i["mit_number"] == params["mit_number"]]
    return {"result": {"count": len(items), "items": items}}


class TestArshin(unittest.TestCase):
    def setUp(self):
        arshin.fetch = fake_arshin

    def test_search_and_interval(self):
        recs = arshin.search("1234")
        self.assertEqual([r["vri_id"] for r in recs], ["1-2", "1-3", "1-1"])  # чужой 12345 отброшен, новые первыми
        self.assertEqual(arshin.interval("2026-10-20", "2027-10-19"), 12)
        self.assertEqual(arshin.interval("2026-02-19", "2032-02-18"), 72)
        ch = arshin.changes(recs[1])
        self.assertEqual((ch["next_date"], ch["arshin_bad"]), (None, 1))
        self.assertEqual(arshin.search("1234", "25405-03")[0]["valid"], "2027-10-19")
        self.assertTrue(arshin.valid_mit("25405-03"))
        self.assertFalse(arshin.valid_mit("Е6-24"))


class TestVlk(unittest.TestCase):
    def example(self):
        rows, errors = vlk.parse_paste(EXAMPLE.read_text(encoding="utf-8-sig"))
        self.assertEqual(errors, [])
        return [{**r, "id": i, "created": ""} for i, r in enumerate(rows, 1)]

    def test_formulas(self):
        r = vlk.evaluate({"kind": "повт", "x1": 1.0, "x2": 0.9}, PARAMS)
        self.assertAlmostEqual(r["norm"], 2.77 * 4 / 100 * 0.95)
        self.assertTrue(r["ok"])
        r = vlk.evaluate({"kind": "ок", "x1": 0.6, "x2": None, "c": 0.5}, PARAMS)
        self.assertAlmostEqual(r["norm"], 0.84 * 15 / 100 * 0.5)
        self.assertFalse(r["ok"])  # 20 % > 12,6 %
        self.assertIn("σr", vlk.evaluate({"kind": "повт", "x1": 1, "x2": 1}, {**PARAMS, "sigma_r": None})["error"])
        self.assertEqual(vlk.row_from(["", "доб", "1", "", "0,5"])[1], "заполните X′₁")
        self.assertEqual(vlk.row_from(["01.01.2026", "пов", "1,2", "1,1"])[0]["kind"], "повт")
        self.assertIn("дату", vlk.row_from(["32.01.2026", "ок", "1", "", "1"])[1])
        self.assertEqual(vlk.fmt(0.012345), "0,0123")
        self.assertEqual(vlk.fmt(1234.5), "1 230")

    def test_same_as_calculator(self):
        """Те же цифры, сигналы и пределы, что у калькулятора /vlk/ (vlk-core.js) на example.csv."""
        node = shutil.which("node")
        if not node:
            self.skipTest("нет node")
        js = (f"const V=require({json.dumps(str(CORE))});const p={{sigma_r:'4',sigma_R:'6',delta:'15',useLab:false}};"
              f"const rows=V.rowsFromTable(V.parseTable(require('fs').readFileSync({json.dumps(str(EXAMPLE))},'utf8')));"
              "const res=rows.map(r=>V.evaluate(r,p));const sig={};"
              "for(const k of Object.keys(V.KINDS)){const it=res.filter(r=>r.kind===k);"
              "sig[k]=V.findSignals(it.map(r=>r.rel),V.chartLimits(k,p));}"
              "console.log(JSON.stringify({res,sig}));")
        want = json.loads(subprocess.run([node, "-e", js], capture_output=True, text=True, check=True).stdout)
        a = vlk.analyze({**PARAMS, "period": ""}, self.example())
        self.assertEqual(len(a["results"]), len(want["res"]))
        for got, exp in zip(a["results"], want["res"]):
            self.assertEqual(got["kind"], exp["kind"])
            for k in ("value", "norm", "rel"):
                self.assertAlmostEqual(got[k], exp[k], places=9)
            self.assertEqual(got["ok"], exp["ok"])
        for ch in a["charts"]:
            self.assertEqual({str(k): v for k, v in ch["signals"].items()}, want["sig"][ch["kind"]])
        self.assertTrue(a["signals"])  # в примере есть сигналы
        self.assertIn("<svg", a["charts"][0]["svg"])

    def test_status_and_due(self):
        today = date(2026, 10, 22)
        ind = {**PARAMS, "period": "month"}
        rows = [{"id": 1, "run_date": "2026-09-20", "kind": "повт", "x1": 1.0, "x2": 0.99, "c": None, "xd1": None,
                 "xd2": None, "performer": "", "created": ""}]
        a = vlk.analyze(ind, rows, today)
        self.assertEqual((a["status"], a["due"], a["due_status"]), ("ok", date(2026, 10, 20), "overdue"))
        rows.append({**rows[0], "id": 2, "run_date": "2026-10-21", "x2": 0.5})
        a = vlk.analyze(ind, rows, today)
        self.assertEqual((a["status"], a["due_status"], a["due_left"]), ("bad", "ok", 30))
        self.assertEqual(vlk.analyze({**ind, "period": ""}, [], today)["due_status"], "none")
        self.assertEqual(vlk.analyze(ind, [], today)["due_status"], "overdue")

    def test_project_file(self):
        data = {"app": "vlk-web", "version": 1, "params": {"name": "Аммоний", "units": "мг/дм³", "sigma_r": "4",
                "sigma_R": "6,5", "delta": "15", "delta_lab": "", "useLab": False},
                "rows": [{"date": "01.09.2026", "kind": "повт", "x1": "1,1", "x2": "1,0"},
                         {"date": "", "kind": "", "x1": "", "x2": ""}]}
        ind, rows, errors = vlk.parse_project(json.dumps(data))
        self.assertEqual((ind["sigma_rl"], len(rows), errors), (6.5, 1, []))
        self.assertTrue(vlk.parse_project("не json")[2])


class TestApp(unittest.TestCase):
    def setUp(self):
        self.c = TestClient(main.app, base_url="http://testserver")

    def test_login_wrong_code_and_limits(self):
        r = self.c.post("/app/login", data={"email": "a@lab.ru"})
        self.assertEqual(r.status_code, 400)  # без согласия
        self.c.post("/app/login", data={"email": "a@lab.ru", "consent": "1"})
        r = self.c.post("/app/verify", data={"email": "a@lab.ru", "code": "000000x"})
        self.assertIn("Неверный код", r.text)
        r = self.c.post("/app/login", data={"email": "a@lab.ru", "consent": "1"})
        self.assertIn("через минуту", r.text)  # повторный код не раньше чем через минуту

    def test_flow(self):
        r = self.c.get("/app/equipment", follow_redirects=False)
        self.assertEqual(r.headers["location"], "/app/login")
        r = login(self.c, "Lab@Example.ru")
        self.assertEqual(r.headers["location"], "/app/profile")
        self.c.post("/app/profile", data={"org": "ИЛ Водоканал", "remind": "1"})
        soon = (date.today() + timedelta(days=7)).isoformat()
        r = self.c.post("/app/equipment/new", data={"name": "pH-метр", "kind": "СИ", "service": "поверка",
                                                    "next_date": soon, "interval_months": "12"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("pH-метр", r.text)
        self.assertIn("Скоро срок", r.text)
        r = self.c.post("/app/import", data={"text": "Весы\tСИ\t1\t\tповерка\t01.01.2026\t12\nПечь\tИО"})
        self.assertIn("Весы", r.text)
        r = self.c.post("/app/equipment/new", data={"name": "Четвёртое"})
        self.assertIn("бесплатном тарифе", r.text)  # лимит 3
        x = self.c.get("/app/equipment.xlsx")
        self.assertEqual(x.content[:2], b"PK")
        # чужая лаборатория не видит записи
        other = TestClient(main.app, base_url="http://testserver")
        login(other, "other@lab.ru")
        self.assertNotIn("pH-метр", other.get("/app/equipment").text)
        self.assertEqual(other.get("/app/equipment/1").status_code, 404)
        self.assertEqual(other.get("/app/admin").status_code, 403)
        # напоминание: срок через 7 дней
        mailer.sent.clear()
        self.assertGreaterEqual(remind.run(), 1)
        self.assertIn("pH-метр", mailer.sent[-1].get_content())
        # админ включает подписку → лимит снят
        admin = TestClient(main.app, base_url="http://testserver")
        login(admin, "boss@lab.ru")
        self.assertIn("lab@example.ru", admin.get("/app/admin").text)
        uid = main.db.connect().execute("SELECT id FROM users WHERE email='lab@example.ru'").fetchone()[0]
        admin.post(f"/app/admin/{uid}", data={"paid_until": "2099-01-01"})
        r = self.c.post("/app/equipment/new", data={"name": "Четвёртое"})
        self.assertIn("Четвёртое", r.text)

    def test_leads(self):
        r = self.c.post("/app/lead", json={"source": "check", "email": "bad", "consent": True})
        self.assertEqual(r.status_code, 400)
        r = self.c.post("/app/lead", json={"source": "check", "email": "x@lab.ru", "org": "ИЛ"})
        self.assertIn("согласие", r.json()["error"])
        mailer.sent.clear()
        data = {"source": "check", "email": "Lead@Lab.ru", "org": "ИЛ Вода", "consent": True, "score": 62,
                "sections": [["Персонал", 80]], "gaps": [{"text": "Внутренние аудиты", "a": "no", "key": True}]}
        r = self.c.post("/app/lead", json=data)
        self.assertEqual(r.json(), {"ok": True})
        to_owner, to_lead = mailer.sent[-2], mailer.sent[-1]
        self.assertEqual(to_owner["Reply-To"], "lead@lab.ru")
        self.assertIn("Внутренние аудиты — нет [ключевой]", to_owner.get_content())
        self.assertEqual(to_lead["To"], "lead@lab.ru")
        self.assertIn("62%", to_lead["Subject"])
        for _ in range(2):
            self.c.post("/app/lead", json=data)
        self.assertEqual(self.c.post("/app/lead", json=data).status_code, 400)  # не больше 3 в сутки
        r = self.c.post("/app/lead", json={"source": "contact", "email": "c@lab.ru", "consent": True, "message": "коротко"})
        self.assertEqual(r.status_code, 400)
        r = self.c.post("/app/lead", json={"source": "contact", "email": "c@lab.ru", "consent": True,
                                           "message": "Нужна помощь с ПК в марте"})
        self.assertEqual(r.status_code, 200)
        n = len(mailer.sent)
        self.c.post("/app/lead", json={"source": "contact", "email": "bot@x.ru", "consent": True,
                                       "message": "spam spam spam", "website": "http://x"})
        self.assertEqual(len(mailer.sent), n)  # робот: тихо игнорируем
        admin = TestClient(main.app, base_url="http://testserver")
        login(admin, "boss@lab.ru")
        page = admin.get("/app/admin/leads").text
        self.assertIn("lead@lab.ru", page)
        self.assertIn("Нужна помощь", page)
        self.assertNotIn("bot@x.ru", page)

    def test_arshin(self):
        arshin.fetch = fake_arshin
        login(self.c, "metro@lab.ru")
        main.db.connect().execute("UPDATE users SET paid_until='2099-01-01' WHERE email='metro@lab.ru'").connection.commit()
        r = self.c.post("/app/equipment/new", data={"name": "Мегаомметр", "serial": "1234", "mit_number": "Е6-24"})
        self.assertIn("госреестре", r.text)  # неверный формат номера
        self.c.post("/app/equipment/new", data={"name": "Мегаомметр", "serial": "1234", "mit_number": "25405-03",
                                                "last_date": "2025-10-15", "interval_months": "12"})
        self.c.post("/app/equipment/new", data={"name": "Весы", "serial": "1234"})
        self.c.post("/app/equipment/new", data={"name": "Нет номера", "serial": "999", "mit_number": "11111-11"})
        con = main.db.connect()
        ids = {r["name"]: r["id"] for r in con.execute(
            "SELECT e.id, e.name FROM equipment e JOIN users u ON u.id = e.user_id WHERE u.email='metro@lab.ru'")}
        # карточка: без № госреестра видны оба прибора, берём весы — непригодны
        r = self.c.get(f"/app/equipment/{ids['Весы']}/arshin")
        self.assertIn("Мегаомметры", r.text)
        self.assertIn("Непригоден", r.text)
        self.c.post(f"/app/equipment/{ids['Весы']}/arshin", data={"vri_id": "1-3"})
        it = con.execute("SELECT * FROM equipment WHERE id = ?", (ids["Весы"],)).fetchone()
        self.assertEqual((it["last_date"], it["next_date"], it["arshin_bad"], it["mit_number"]),
                         ("2026-09-01", None, 1, "13590-01"))
        self.assertIn("Аршин: непригоден", self.c.get("/app/equipment").text)
        r = self.c.post(f"/app/equipment/{ids['Весы']}/arshin", data={"vri_id": "подделка"})
        self.assertEqual(r.status_code, 404)
        # массовое обновление
        r = self.c.post("/app/arshin")
        self.assertIn("Обновлено", r.text)
        it = con.execute("SELECT * FROM equipment WHERE id = ?", (ids["Мегаомметр"],)).fetchone()
        self.assertEqual((it["last_date"], it["next_date"], it["doc_no"]), ("2026-10-20", "2027-10-19", "С-ВЭ/20-10-2026/2"))
        self.assertIn("Нет номера", r.text)  # не найден
        self.assertEqual(self.c.post("/app/arshin").status_code, 429)  # не чаще раза в 5 минут
        # «Аршин» не отвечает
        def down(params):
            raise arshin.ArshinError("«Аршин» не ответил")
        arshin.fetch = down
        self.assertIn("не ответил", self.c.get(f"/app/equipment/{ids['Весы']}/arshin").text)
        # чужой кабинет не видит
        other = TestClient(main.app, base_url="http://testserver")
        login(other, "spy@lab.ru")
        self.assertEqual(other.get(f"/app/equipment/{ids['Весы']}/arshin").status_code, 404)

    def test_vlk(self):
        r = self.c.get("/app/vlk", follow_redirects=False)
        self.assertEqual(r.headers["location"], "/app/login")
        login(self.c, "vlk@lab.ru")
        self.c.post("/app/profile", data={"org": "ИЛ ЛОС", "remind": "1"})
        r = self.c.post("/app/vlk/new", data={"name": "", "sigma_r": "4"})
        self.assertIn("Укажите показатель", r.text)
        r = self.c.post("/app/vlk/new", data={"name": "Аммоний", "sigma_r": "abc"})
        self.assertIn("σr", r.text)
        r = self.c.post("/app/vlk/new", data={"name": "Аммоний", "method": "ПНД Ф 14.1:2:4.262", "units": "мг/дм³",
                                              "sigma_r": "4", "sigma_rl": "6", "delta": "15", "use_lab": "0",
                                              "period": "month"}, follow_redirects=False)
        url = r.headers["location"]
        ind_id = int(url.rsplit("/", 1)[1])
        r = self.c.get(url)
        self.assertIn("Результатов пока нет", r.text)
        self.assertIn("Δл = 12,6 %", r.text)
        # одна строка вручную: ошибка, потом верно
        r = self.c.post(url + "/add", data={"run_date": date.today().isoformat(), "kind": "ок", "x1": "1"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("заполните C", r.text)
        r = self.c.post(url + "/add", data={"run_date": date.today().isoformat(), "kind": "ок", "x1": "0,51",
                                            "x2": "0,49", "c": "0,5", "performer": "Иванова"})
        self.assertIn("Иванова", r.text)
        self.assertIn("удовл.", r.text)
        # вставка из Excel: ошибка — ничего не сохранено; потом пример целиком
        r = self.c.post(url + "/import", data={"text": "01.09.2026\tповт\t1,1\n"})
        self.assertIn("заполните X₂", r.text)
        r = self.c.post(url + "/import", data={"text": EXAMPLE.read_text(encoding="utf-8-sig")})
        self.assertIn("<svg", r.text)
        self.assertIn("Точка", r.text)  # сигналы примера
        self.assertIn("не удовл.: 2", self.c.get("/app/vlk").text)
        # удаление результата
        con = main.db.connect()
        rid = con.execute("SELECT id FROM vlk_results WHERE indicator_id = ? AND performer = 'Иванова'", (ind_id,)).fetchone()[0]
        self.c.post(f"{url}/delete/{rid}")
        self.assertNotIn("Иванова", self.c.get(url).text)
        # проект из калькулятора
        proj = json.dumps({"params": {"name": "Нитрит", "sigma_r": "3", "sigma_R": "5", "delta": "12"},
                           "rows": [{"date": "01.10.2026", "kind": "повт", "x1": "0,1", "x2": "0,1"}]})
        r = self.c.post("/app/vlk/project", files={"file": ("n.vlk.json", proj.encode(), "application/json")})
        self.assertIn("Нитрит", r.text)
        r = self.c.post("/app/vlk/project", files={"file": ("x.json", b"{}", "application/json")})
        self.assertIn("не файл проекта", r.text)
        # параметры и архив
        r = self.c.post(url + "/edit", data={"name": "Аммоний-ион", "sigma_r": "4", "sigma_rl": "6", "delta_lab": "10",
                                             "use_lab": "1", "period": "week"})
        self.assertIn("Δл = 10 %", r.text)
        # напоминание: свежие нарушения ВЛК
        mailer.sent.clear()
        remind.run()
        msg = [m for m in mailer.sent if m["To"] == "vlk@lab.ru"][-1]
        self.assertIn("нарушения ВЛК", msg["Subject"])
        self.assertIn("Аммоний-ион", msg.get_content())
        # чужой кабинет не видит
        other = TestClient(main.app, base_url="http://testserver")
        login(other, "spy2@lab.ru")
        self.assertEqual(other.get(url).status_code, 404)
        self.assertEqual(other.post(url + "/add", data={"kind": "повт"}).status_code, 404)
        self.assertEqual(other.post(f"{url}/delete/1").status_code, 404)
        self.assertNotIn("Аммоний", other.get("/app/vlk").text)
        self.c.post(url + "/edit", data={"action": "archive"})
        self.assertNotIn("Аммоний-ион", self.c.get("/app/vlk").text)
        self.assertIn("Аммоний-ион", self.c.get("/app/vlk?show=archive").text)

    def test_foreign_origin(self):
        r = self.c.post("/app/login", data={"email": "x@lab.ru", "consent": "1"},
                        headers={"origin": "https://evil.example"})
        self.assertEqual(r.status_code, 403)


if __name__ == "__main__":
    unittest.main()
