#!/bin/sh
# Резервная копия базы кабинета: раз в сутки, хранить 30 последних. Запуск из cron пользователя labcompass.
set -e
mkdir -p /var/lib/labcompass/backup
sqlite3 /var/lib/labcompass/app.db ".backup /var/lib/labcompass/backup/app-$(date +%F).db"
ls -1t /var/lib/labcompass/backup/app-*.db | tail -n +31 | xargs -r rm --
