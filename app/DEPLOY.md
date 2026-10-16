# Установка кабинета на ВМ (Ubuntu 24.04, Caddy уже стоит)

Сайт уже лежит в `/var/www/labcompass` (клон репозитория). Кабинет запускается из `app/` того же клона.

```bash
# 1. Пользователь службы, папки, Python-окружение
sudo apt install -y python3-venv sqlite3
sudo useradd --system --home /var/lib/labcompass --shell /usr/sbin/nologin labcompass
sudo mkdir -p /var/lib/labcompass /etc/labcompass && sudo chown labcompass: /var/lib/labcompass
sudo python3 -m venv /opt/labcompass-venv
sudo /opt/labcompass-venv/bin/pip install -r /var/www/labcompass/app/requirements.txt

# 2. Настройки (пароль почты — только здесь, не в git)
sudo cp /var/www/labcompass/app/.env.example /etc/labcompass/app.env
sudo nano /etc/labcompass/app.env        # SMTP_PASSWORD, OPERATOR
sudo chown root:labcompass /etc/labcompass/app.env && sudo chmod 640 /etc/labcompass/app.env

# 3. Службы
sudo cp /var/www/labcompass/app/deploy/labcompass-*.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now labcompass-app labcompass-remind.timer

# 4. Резервные копии базы — каждый день в 03:00
echo '0 3 * * * /var/www/labcompass/app/deploy/backup.sh' | sudo crontab -u labcompass -

# 5. Caddy: сравнить с текущим /etc/caddy/Caddyfile, вписать хэш пароля админки
caddy hash-password                       # ввести пароль, хэш вставить в Caddyfile
sudo cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.bak-$(date +%F)
sudo cp /var/www/labcompass/app/deploy/Caddyfile /etc/caddy/Caddyfile && sudo nano /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

## Обновление
```bash
git -C /var/www/labcompass pull
sudo /opt/labcompass-venv/bin/pip install -r /var/www/labcompass/app/requirements.txt
sudo systemctl restart labcompass-app
```

## Проверка
- `systemctl status labcompass-app` — active (running); логи: `journalctl -u labcompass-app -n 50`
- https://labcompass.ru/app/ — страница входа; код должен прийти на почту.
- Напоминания вручную: `sudo systemctl start labcompass-remind && journalctl -u labcompass-remind -n 5`
