#!/usr/bin/env bash
#
# Хук certbot: перечитать конфиг nginx после продления сертификата.
#
# Ставится симлинком — тогда он остаётся в git и не разъезжается с ним:
#
#   sudo ln -sf "$PWD/scripts/reload-nginx.sh" \
#       /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh
#
# Копией тоже работает (так он стоял на проде): каталог проекта тогда
# берётся из списка ниже.

set -Eeuo pipefail

PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# Где лежит проект. Первый кандидат срабатывает, когда хук поставлен
# симлинком: readlink разворачивает его обратно в репозиторий. Остальные —
# для копии, у которой своего пути до проекта нет вовсе.
REPO_DIR=""
for d in "$(dirname "$(readlink -f "$0")")/.." \
         /home/leobreslav/lesson-tracker \
         /home/leobreslav/apps/lesson-tracker; do
    if [ -f "$d/docker-compose.prod.yml" ]; then REPO_DIR="$(cd "$d" && pwd)"; break; fi
done
[ -n "$REPO_DIR" ] || { echo "reload-nginx: не нашёл каталог проекта" >&2; exit 1; }

cd "$REPO_DIR"

# --env-file обязателен: в compose-файлах есть ${DOMAIN}, и без него команда
# отказывает целиком — даже `exec`, которому домен не нужен. Без этого флага
# хук молча переставал работать, а замечено это было бы через три месяца, по
# просроченному сертификату на живом сайте.
docker compose --env-file .env.prod \
    -f docker-compose.prod.yml -f docker-compose.ssl.yml \
    exec -T nginx nginx -s reload

echo "nginx перечитал конфиг после обновления сертификата ($REPO_DIR)"
