# Как выложить labcompass.ru на виртуальную машину cloud.ru

Сайт берётся из публичного репозитория https://github.com/pelopsmrf/labcompass
(папка `labcompass_site/dist`). Расчёт на Ubuntu или Debian. Если на машине другая система,
сначала напишите агенту. `ЛОГИН` — пользователь машины, `IP` — её публичный адрес.

## Шаг 1. Кабинет cloud.ru
1. У машины должен быть **публичный IP**. Запишите его.
2. В группе безопасности (файрволе) машины откройте входящие порты **22, 80 и 443** (TCP).

## Шаг 2. DNS у регистратора домена
1. Проверьте, что у домена указаны DNS-серверы регистратора.
2. Добавьте две записи:
   - `A`  `@` (labcompass.ru)  →  `IP`
   - `A`  `www`  →  `IP`
3. Проверка в командной строке Windows: `nslookup labcompass.ru` должен вернуть `IP`.

## Шаг 3. Подключиться к машине (PowerShell на ноутбуке)
```
ssh ЛОГИН@IP
```

## Шаг 4. Проверить, что порты 80 и 443 свободны
```
sudo ss -ltnp | grep -E ':(80|443) '
```
Пусто — всё хорошо. Если что-то выводится, остановитесь и покажите вывод агенту.

## Шаг 5. Установить git
```
sudo apt update && sudo apt install -y git
```

## Шаг 6. Скачать сайт из репозитория
```
sudo mkdir -p /var/www/labcompass
sudo chown $USER: /var/www/labcompass
git clone https://github.com/pelopsmrf/labcompass.git /var/www/labcompass
ls /var/www/labcompass/labcompass_site/dist
```
Должны быть `index.html`, `style.css`, `vlk`, `img` и другие файлы.

## Шаг 7. Установить Caddy (веб-сервер с автоматическим HTTPS)
```
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update
sudo apt install -y caddy
```

## Шаг 8. Настроить Caddy
Сохраняем копию стандартного файла настроек и записываем свой:
```
sudo cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.bak
sudo tee /etc/caddy/Caddyfile > /dev/null <<'EOF'
www.labcompass.ru {
	redir https://labcompass.ru{uri} permanent
}

labcompass.ru {
	root * /var/www/labcompass/labcompass_site/dist
	encode gzip
	file_server
}
EOF
sudo systemctl reload caddy
sudo systemctl status caddy --no-pager
```
Если на машине включён ufw: `sudo ufw allow 80,443/tcp`.

## Шаг 9. Проверить
- https://labcompass.ru — открывается лендинг, в адресной строке замок.
- https://labcompass.ru/vlk/ — открывается калькулятор.
- Если HTTPS не работает: `sudo journalctl -u caddy -n 40 --no-pager` и показать вывод агенту.
  Чаще всего причина в том, что DNS ещё не обновился или закрыт порт 80/443.

## Как обновлять сайт
Агент вносит правки и отправляет их в GitHub. На машине:
```
git -C /var/www/labcompass pull
```
Перезапускать Caddy не нужно.

**Автообновление (по желанию):** машина сама забирает изменения каждые 5 минут.
```
(crontab -l 2>/dev/null; echo '*/5 * * * * git -C /var/www/labcompass pull -q') | crontab -
```
