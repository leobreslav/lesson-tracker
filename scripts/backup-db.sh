#!/usr/bin/env bash
#
# Ежедневный дамп боевой базы. Хранит архивы 7 дней.
# Запуск из cron:
#
#   30 3 * * * /home/leobreslav/lesson-tracker/scripts/backup-db.sh >> /home/leobreslav/backups/backup.log 2>&1

set -Eeuo pipefail

# cron даёт урезанный PATH, docker в нём может не найтись
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

REPO_DIR="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
BACKUP_DIR="${BACKUP_DIR:-$HOME/backups/lesson-tracker}"
KEEP_DAYS="${KEEP_DAYS:-7}"

cd "$REPO_DIR"

log()  { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
fail() { log "ОШИБКА: $*" >&2; exit 1; }

[ -f .env.prod ] || fail "нет .env.prod в $REPO_DIR"

# читаем через grep, а не через source: пароль может содержать # или $
read_env() {
    local value
    value="$(grep -E "^$1=" .env.prod | head -1 | cut -d= -f2-)"
    [ -n "$value" ] || fail "в .env.prod не задан $1"
    printf '%s' "$value"
}

DB_NAME="$(read_env POSTGRES_DB)"
DB_USER="$(read_env POSTGRES_USER)"

mkdir -p "$BACKUP_DIR"

STAMP="$(date '+%Y-%m-%d_%H%M')"
TARGET="$BACKUP_DIR/lessons_$STAMP.sql.gz"
TMP="$TARGET.part"

log "Дамп базы $DB_NAME -> $TARGET"

# пишем во временный файл: оборванный дамп не должен выглядеть как готовый
# pipefail гарантирует, что падение pg_dump уронит весь конвейер
if ! docker compose -f docker-compose.prod.yml exec -T db \
        pg_dump -U "$DB_USER" -d "$DB_NAME" --clean --if-exists | gzip > "$TMP"; then
    rm -f "$TMP"
    fail "pg_dump завершился с ошибкой"
fi

[ -s "$TMP" ] || { rm -f "$TMP"; fail "дамп получился пустым"; }

mv "$TMP" "$TARGET"
log "Готово, размер: $(du -h "$TARGET" | cut -f1)"

# старое удаляем только после успешного дампа, иначе неудачный запуск
# постепенно съел бы весь архив
DELETED="$(find "$BACKUP_DIR" -maxdepth 1 -name 'lessons_*.sql.gz' -mtime "+$KEEP_DAYS" -print -delete | wc -l)"
log "Удалено старых копий: $DELETED, всего в архиве: $(find "$BACKUP_DIR" -maxdepth 1 -name 'lessons_*.sql.gz' | wc -l)"
