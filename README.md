# ЛабКомпас

Подготовка испытательных лабораторий к аккредитации по ГОСТ ISO/IEC 17025-2019 — https://labcompass.ru

| Папка | Что это |
|---|---|
| `labcompass_site/` | Лендинг labcompass.ru (статический сайт). Сборка: `node build.js` → `dist/`. Публикация: `DEPLOY.md` |
| `labcompass_site/src/check/` | Бесплатная самопроверка готовности к аккредитации (labcompass.ru/check/) |
| `app/` | Кабинет на Python (FastAPI + SQLite): учёт оборудования и ВЛК, вход по коду на почту (labcompass.ru/app/) |
| `vlk_web/` | ЛабКомпас.ВЛК — калькулятор внутрилабораторного контроля по РМГ 76-2014, работает в браузере (labcompass.ru/vlk/) |
| `vlk_calc/` | Тот же расчёт на Python: CSV → HTML-отчёт с картами Шухарта |
| `portfolio/` | Образец процедуры ВЛК (Word) |

Тесты: `node --test vlk_web/test/core.test.js`, `cd vlk_calc && python3 -m unittest test_vlk`, `cd app && python3 -m unittest test_app`.

Коэффициенты РМГ 76-2014 в расчётах нужно сверять с действующей редакцией документа.
