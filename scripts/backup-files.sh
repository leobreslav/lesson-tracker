#!/usr/bin/env bash
#
# Ежедневная синхронизация бакета вложений в резервный.
# Запуск из cron (со сдвигом от backup-db.sh, чтобы не пересекаться):
#
#   10 4 * * * /home/leobreslav/lesson-tracker/scripts/backup-files.sh >> /home/leobreslav/backups/backup.log 2>&1
#
# Аргументы прокидываются в manage.py backup_files:
#
#   ./scripts/backup-files.sh --dry-run   посмотреть, что скопировалось бы
#   ./scripts/backup-files.sh --restore   обратная сторона: вернуть из резерва
#
# Копирование идёт внутри Cloudflare (server-side copy): байты не проходят
# через сервер, диск VPS не участвует. Удалённое в основном бакете в резерве
# остаётся — в этом и смысл резерва.

set -Eeuo pipefail

# cron даёт урезанный PATH, docker в нём может не найтись
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

REPO_DIR="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"

cd "$REPO_DIR"

log()  { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
fail() { log "ОШИБКА: $*" >&2; exit 1; }

[ -f .env.prod ] || fail "нет .env.prod в $REPO_DIR"

# читаем через grep, а не через source: ключ может содержать # или $
read_env() {
    grep -E "^$1=" .env.prod | head -1 | cut -d= -f2-
}

for name in R2_BUCKET_NAME R2_ENDPOINT_URL R2_BACKUP_BUCKET_NAME \
            R2_BACKUP_ACCESS_KEY_ID R2_BACKUP_SECRET_ACCESS_KEY; do
    [ -n "$(read_env "$name")" ] || fail "в .env.prod не задан $name"
done

# один бакет в оба конца — это не резерв, а способ его потерять
[ "$(read_env R2_BUCKET_NAME)" != "$(read_env R2_BACKUP_BUCKET_NAME)" ] \
    || fail "R2_BUCKET_NAME и R2_BACKUP_BUCKET_NAME совпадают"

log "Синхронизация вложений в резервный бакет $(read_env R2_BACKUP_BUCKET_NAME)"

# контейнер должен быть поднят: свой питон с boto3 на хосте не нужен, все
# ключи и так лежат в окружении backend'а через env_file
if ! docker compose --env-file .env.prod -f docker-compose.prod.yml ps --status running --services \
        2>/dev/null | grep -qx backend; then
    fail "контейнер backend не запущен"
fi

docker compose --env-file .env.prod -f docker-compose.prod.yml exec -T backend \
    python manage.py backup_files "$@"

log "Готово"
