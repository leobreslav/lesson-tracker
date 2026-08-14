#!/usr/bin/env bash
#
# Ежедневный дамп боевой базы. Хранит архивы 7 дней — и на диске, и в R2.
# Запуск из cron:
#
#   30 3 * * * /home/leobreslav/lesson-tracker/scripts/backup-db.sh >> /home/leobreslav/backups/backup.log 2>&1
#
# Копия на диске сервера — это не копия: диск и база живут на одной машине
# и умрут вместе. Поэтому дамп ещё и уезжает в резервный бакет, тот же, что
# у вложений, но под префиксом `db/` (`manage.py backup_db`). Локальный
# файл при этом остаётся главным: он быстрее под рукой, и на нём проверяется,
# что дамп вообще получился.
#
# Заливка идёт **после** локального дампа и его не отменяет: не доехало до
# R2 — на диске всё равно лежит сегодняшняя копия, и это видно в логе.

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

# то же, но без отказа: для необязательных ключей
peek_env() {
    grep -E "^$1=" .env.prod | head -1 | cut -d= -f2-
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

# --- копия за пределы сервера -------------------------------------------------

# нет резервных ключей — предупреждение, а не отказ: локальный дамп уже снят,
# и падать после успешной работы значит врать логу
if [ -z "$(peek_env R2_BACKUP_BUCKET_NAME)" ] \
   || [ -z "$(peek_env R2_BACKUP_ACCESS_KEY_ID)" ]; then
    log "R2_BACKUP_* не заданы — копия в бакет пропущена"
    exit 0
fi

if ! docker compose -f docker-compose.prod.yml ps --status running --services \
        2>/dev/null | grep -qx backend; then
    fail "контейнер backend не запущен: дамп на диске есть, в бакет не уехал"
fi

log "Копия в резервный бакет $(peek_env R2_BACKUP_BUCKET_NAME)"

# дамп идёт контейнеру на stdin: pg_dump живёт в контейнере базы, а boto3 —
# в backend'е, и общего тома у них с хостом нет
if ! docker compose -f docker-compose.prod.yml exec -T backend \
        python manage.py backup_db --name "$(basename "$TARGET")" \
        --keep-days "$KEEP_DAYS" < "$TARGET"; then
    fail "загрузка в резервный бакет не удалась (дамп на диске остался)"
fi
