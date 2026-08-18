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

# nginx пересоздаётся, **только когда его конфиг разошёлся** с репозиторием.
#
# Почему вообще пересоздаётся: конфиг смонтирован отдельным файлом
# (`./nginx/default.conf:...:ro`), а bind-mount файла держит inode, а не имя.
# `git pull` меняет файл заменой — пишет новый и переименовывает поверх, —
# inode другой, и контейнер до конца своей жизни видит прежний конфиг. Ни
# `up -d` (образ и настройки сервиса не менялись, пересоздавать нечего), ни
# `nginx -s reload` (перечитывает тот же старый файл) этого не лечат.
#
# Почему не всегда: пересоздание — это остановка и запуск, и на секунду-две
# 443 не слушает никто. Сначала так и делали, каждую выкатку, и это тут же
# поймал учитель на проде: `ERR_CONNECTION_REFUSED` посреди работы. Обычная
# выкатка конфиг не трогает, а значит и трогать nginx незачем.
# Сравниваются **все** файлы, смонтированные внутрь по отдельности: сайтовый
# конфиг (его подменяет ssl-оверлей на том же mount point) и proxy_params.
# Каталоги в этот список не входят — у них inode не подменяется, правка в
# них видна контейнеру сразу.
active_conf="nginx/default.conf"
[ "$SCHEME" = "https" ] && active_conf="nginx/ssl.conf"

inside="$(docker compose "${COMPOSE_FILES[@]}" exec -T nginx \
    cat /etc/nginx/conf.d/default.conf /etc/nginx/proxy_params.conf 2>/dev/null |
    sha256sum | cut -d' ' -f1 || true)"
outside="$(cat "$active_conf" nginx/proxy_params.conf | sha256sum | cut -d' ' -f1)"

if [ "$inside" != "$outside" ]; then
    log "Конфиг nginx изменился — пересоздаю контейнер"
    docker compose "${COMPOSE_FILES[@]}" up -d --force-recreate nginx
else
    printf '    конфиг nginx тот же — контейнер не трогаю\n'
fi

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
