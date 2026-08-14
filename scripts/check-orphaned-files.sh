#!/usr/bin/env bash
#
# Еженедельная сверка бакета с базой. Запуск из cron:
#
#   0 5 * * 1 /home/leobreslav/lesson-tracker/scripts/check-orphaned-files.sh >> /home/leobreslav/backups/orphans.log 2>&1
#
# Ничего не удаляет и не должно: `cleanup_orphaned_files` без `--delete`
# только перечисляет находки. Удаление учебных материалов школы по
# расписанию, без человека, — не та операция, которую доверяют cron'у;
# задача этой строки в другом: сирот в норме не бывает вовсе, и заметить их
# появление сейчас нечем.
#
# Пустой лог — это и есть «всё в порядке». Появились строки — идти руками:
#
#   docker compose -f docker-compose.prod.yml exec backend \
#       python manage.py cleanup_orphaned_files --delete

set -Eeuo pipefail

# cron даёт урезанный PATH, docker в нём может не найтись
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

REPO_DIR="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"

cd "$REPO_DIR"

log()  { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
fail() { log "ОШИБКА: $*" >&2; exit 1; }

[ -f .env.prod ] || fail "нет .env.prod в $REPO_DIR"

if ! docker compose -f docker-compose.prod.yml ps --status running --services \
        2>/dev/null | grep -qx backend; then
    fail "контейнер backend не запущен"
fi

# --quiet: команда молчит, когда находить нечего. Пустой лог — это и есть
# «всё в порядке», а еженедельная строка «сирот нет» через год стала бы
# всем логом
output="$(docker compose -f docker-compose.prod.yml exec -T backend \
    python manage.py cleanup_orphaned_files --quiet "$@")"

if [ -n "${output//[[:space:]]/}" ]; then
    log "Сверка бакета нашла лишнее:"
    printf '%s\n' "$output"
fi
