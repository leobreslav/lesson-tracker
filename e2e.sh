#!/usr/bin/env bash
#
# Браузерные тесты одной командой.
#
#   ./e2e.sh                     # весь набор (~8 минут)
#   ./e2e.sh --smoke             # дымовой: все экраны и ряды (~1 минута)
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

# Дымовой набор: два файла, которые обходят **все** экраны — маршруты и ряды
# контролов в обеих локалях. Ловит он ровно тот класс, ради которого
# браузерные тесты и заведены: ошибку в консоли, которую `vite build` не
# видит, и разъехавшуюся вёрстку. Полный набор ловит то же самое плюс
# поведение, и стоит вдесятеро дороже — поэтому он гоняется на GitHub (пуш в
# main и ночью), а этот здесь, при каждой правке.
SMOKE=(navigation controls)

for arg in "$@"; do
    case "$arg" in
        --keep)  KEEP=1 ;;
        --smoke) ARGS+=("${SMOKE[@]}") ;;
        *)       ARGS+=("$arg") ;;
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
# -T, когда терминала нет: в CI `docker compose run` без него спотыкается о
# «the input device is not a TTY». Локально флаг не ставим — с ним пропадает
# цвет и посекундный вывод Playwright, а смотрят на него именно глазами.
[ -t 1 ] && TTY=() || TTY=(-T)

# Зависимости ставятся отдельным шагом, а не командой сервиса: строку
# запуска мы переопределяем ниже (иначе некуда девать аргументы), и
# объявленный в compose `npm ci` до чистого клона не доезжает вовсе.
# Локально каталог уже есть, и шаг ничего не стоит; в CI и в облачной
# сессии без него playwright не находит @playwright/test и падает на
# разборе своего же конфига.
$COMPOSE run --rm -T e2e sh -c '[ -d node_modules/@playwright/test ] || npm ci'

$COMPOSE run --rm "${TTY[@]}" e2e npx playwright test "${ARGS[@]}"
