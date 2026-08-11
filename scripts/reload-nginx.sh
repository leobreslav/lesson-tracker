#!/usr/bin/env bash
#
# Хук certbot: перечитать конфиг nginx после продления сертификата.
# Ставится копированием (certbot запускает хуки от root):
#
#   sudo cp scripts/reload-nginx.sh /etc/letsencrypt/renewal-hooks/deploy/
#   sudo chmod +x /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh

set -Eeuo pipefail

PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

REPO_DIR=/home/leobreslav/lesson-tracker

cd "$REPO_DIR"
docker compose -f docker-compose.prod.yml -f docker-compose.ssl.yml \
    exec -T nginx nginx -s reload

echo "nginx перечитал конфиг после обновления сертификата"
