#!/usr/bin/env bash
#
# Раскатывает свежий код на сервере: git pull, пересборка, перезапуск.
# Запускать из-под обычного пользователя, состоящего в группе docker:
#
#   ./deploy.sh
#
# Скрипт идемпотентен: повторный запуск без изменений просто пересоберёт
# образы из кэша и оставит стек в том же состоянии.

set -Eeuo pipefail

REPO_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
cd "$REPO_DIR"

ENV_FILE=".env.prod"
HEALTHCHECK_RETRIES=30

log()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
fail() { printf '\033[31mОшибка: %s\033[0m\n' "$*" >&2; exit 1; }

trap 'fail "команда на строке $LINENO завершилась с ошибкой"' ERR

# --- проверки окружения -----------------------------------------------------

command -v docker >/dev/null || fail "docker не найден"
docker compose version >/dev/null 2>&1 || fail "плагин docker compose не установлен"
docker info >/dev/null 2>&1 || fail "нет доступа к docker (пользователь в группе docker?)"

[ -f "$ENV_FILE" ] || fail "нет файла $ENV_FILE — создайте его из .env.prod.example"

# HTTPS включается одним флагом в .env.prod, вместе с secure-куками
COMPOSE_FILES=(-f docker-compose.prod.yml)
SCHEME="http"
if grep -Eq '^NGINX_SSL=(1|true|True|yes)[[:space:]]*$' "$ENV_FILE"; then
    COMPOSE_FILES+=(-f docker-compose.ssl.yml)
    SCHEME="https"
    [ -d /etc/letsencrypt/live ] || fail "NGINX_SSL включён, но /etc/letsencrypt/live отсутствует"
fi

log "Режим: $SCHEME"

# --- обновление кода --------------------------------------------------------

if [ -n "$(git status --porcelain)" ]; then
    fail "в рабочем дереве есть локальные изменения — деплой остановлен
$(git status --short)"
fi

log "Забираю изменения из git"
git pull --ff-only

# --- пересборка и перезапуск ------------------------------------------------

log "Собираю образы"
docker compose "${COMPOSE_FILES[@]}" build

log "Перезапускаю стек"
# --remove-orphans убирает контейнеры сервисов, удалённых из compose-файла
docker compose "${COMPOSE_FILES[@]}" up -d --remove-orphans

# nginx пересоздаётся **всегда**, и это не перестраховка.
#
# Его конфиг смонтирован отдельным файлом (`./nginx/default.conf:...:ro`), а
# bind-mount файла держит inode, а не имя. `git pull` меняет файл заменой:
# пишет новый и переименовывает поверх — inode другой, и контейнер до конца
# своей жизни видит прежний конфиг. Ни `up -d` (образ и настройки сервиса не
# менялись — пересоздавать нечего), ни `nginx -s reload` (перечитывает тот же
# старый файл) этого не лечат.
#
# Поймано на проде: правка `location /assets/` уехала на сервер, `nginx -t`
# внутри контейнера её не видел, а сайт продолжал отвечать по-старому.
# Пересоздание стоит секунду, поэтому проще делать его всегда, чем помнить.
docker compose "${COMPOSE_FILES[@]}" up -d --force-recreate nginx

# --- проверка ---------------------------------------------------------------

log "Жду ответа приложения"
for i in $(seq "$HEALTHCHECK_RETRIES"); do
    # -k: локально сертификат проверяется по localhost, а выписан на домен
    code=$(curl -sk -o /dev/null -w '%{http_code}' "$SCHEME://localhost/" || true)
    if [ "$code" = "200" ]; then
        log "Приложение отвечает: $SCHEME://localhost/ -> 200"
        break
    fi
    if [ "$i" = "$HEALTHCHECK_RETRIES" ]; then
        docker compose "${COMPOSE_FILES[@]}" ps
        docker compose "${COMPOSE_FILES[@]}" logs --tail 50 backend nginx
        fail "приложение не ответило 200 (последний код: ${code:-нет ответа})"
    fi
    sleep 2
done

# --- уборка -----------------------------------------------------------------

log "Удаляю образы, оставшиеся от прошлых сборок"
docker image prune -f >/dev/null

log "Готово"
docker compose "${COMPOSE_FILES[@]}" ps --format 'table {{.Service}}\t{{.Status}}'
