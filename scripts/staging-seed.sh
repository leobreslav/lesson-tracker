#!/usr/bin/env bash
#
# Пересев стенда демо-данными.
#
#   ./scripts/staging-seed.sh              # обычный набор
#   ./scripts/staging-seed.sh --rich       # школа в рабочем размере
#   ./scripts/staging-seed.sh --flush --rich
#
# Зачем отдельный скрипт. `seed_demo` отказывается работать при DEBUG=False, и
# это защита, а не недосмотр: он выдумывает данные и умеет их сносить. Стенд же
# должен стоять прод-подобным. Значит посев — это короткое окно: включить
# отладку, посеять, выключить обратно. Три шага руками рано или поздно
# заканчиваются тем, что DEBUG=True остаётся на публичном сервере навсегда.
#
# ЦЕНА ОКНА НАЗВАНА ПРЯМО: пока скрипт работает (десятки секунд), стенд отдаёт
# наружу трейсбеки Django. Стенд закрыт basic-auth, так что это не улица, но и
# не ноль.

set -Eeuo pipefail

REPO_DIR="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
cd "$REPO_DIR"

ENV_FILE=".env.prod"
COMPOSE=(docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml)

log()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
fail() { printf '\033[31mОшибка: %s\033[0m\n' "$*" >&2; exit 1; }

env_value() { sed -n "s/^$1=//p" "$ENV_FILE" | tail -n1; }

[ -f "$ENV_FILE" ] || fail "нет файла $ENV_FILE"

# --- защита от запуска на боевом контуре -------------------------------------
#
# Проверка стоит первой и написана «в белый список», а не «в чёрный»: скрипт
# идёт только туда, где имя контура названо и названо не боевым. Забытая
# переменная тут значит отказ, а не «наверное, это стенд».
PROJECT="$(env_value COMPOSE_PROJECT_NAME)"
[ -n "$PROJECT" ] || fail "в $ENV_FILE не задан COMPOSE_PROJECT_NAME.
Без него непонятно, какой это контур, а выдуманные данные не должны
оказаться там, где живут настоящие."
case "$PROJECT" in
    *staging*|*stand*|*test*) ;;
    *) fail "контур называется «$PROJECT» — это не похоже на стенд.
Скрипт сеет выдуманные данные и умеет их сносить; на боевом контуре ему
делать нечего." ;;
esac

DEBUG_NOW="$(env_value DEBUG)"
[ "$DEBUG_NOW" = "False" ] || log "ВНИМАНИЕ: DEBUG уже $DEBUG_NOW, а не False"

restore_debug() {
    sed -i 's/^DEBUG=.*/DEBUG=False/' "$ENV_FILE"
    log "Возвращаю DEBUG=False и перезапускаю backend"
    "${COMPOSE[@]}" up -d backend >/dev/null
}
# ловушка на любой выход, включая падение и Ctrl+C: окно с отладкой не должно
# пережить скрипт ни при каком исходе
trap restore_debug EXIT

log "Контур: $PROJECT. Включаю DEBUG на время посева"
sed -i 's/^DEBUG=.*/DEBUG=True/' "$ENV_FILE"
"${COMPOSE[@]}" up -d backend >/dev/null

log "Жду, пока backend поднимется"
for i in $(seq 30); do
    if "${COMPOSE[@]}" exec -T backend python -c "import django" >/dev/null 2>&1; then
        break
    fi
    [ "$i" = 30 ] && fail "backend не поднялся"
    sleep 2
done

log "Сею: seed_demo $*"
"${COMPOSE[@]}" exec -T backend python manage.py seed_demo "$@"

# DEBUG вернёт ловушка на выходе
log "Готово"
