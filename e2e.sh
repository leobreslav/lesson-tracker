#!/usr/bin/env bash
#
# Браузерные тесты одной командой.
#
#   ./e2e.sh                     # весь набор
#   ./e2e.sh plan                # только файлы, чьё имя содержит «plan»
#   ./e2e.sh -g "перетаскивание" # по названию теста
#   ./e2e.sh --keep              # не гасить стек после прогона
#
# Стек поднимается свой (docker-compose.e2e.yml): nginx с собранным бандлом,
# gunicorn, база в памяти. Никакого dev-сервера — ловим то, что ломается
# именно в сборке.

set -Eeuo pipefail

COMPOSE="docker compose -f docker-compose.e2e.yml"
KEEP=0
ARGS=()

log()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
fail() { printf '\033[31mОшибка: %s\033[0m\n' "$*" >&2; exit 1; }

for arg in "$@"; do
    case "$arg" in
        --keep) KEEP=1 ;;
        *)      ARGS+=("$arg") ;;
    esac
done

[ -f docker-compose.e2e.yml ] || fail "запускайте из корня репозитория"

cleanup() {
    if [ "$KEEP" -eq 0 ]; then
        log "Гашу стек"
        $COMPOSE down --remove-orphans >/dev/null 2>&1 || true
    else
        printf '\nСтек оставлен: http://localhost:8080 (погасить — %s down)\n' "$COMPOSE"
    fi
}
trap cleanup EXIT

log "Собираю и поднимаю прод-подобный стек"
# --build обязателен: фронтенд собирается в образе, и без пересборки тесты
# гоняли бы прошлый бандл, а именно его свежесть мы и проверяем
$COMPOSE up -d --build db backend frontend-build nginx

log "Прогоняю тесты"
$COMPOSE run --rm e2e npx playwright test "${ARGS[@]}"
