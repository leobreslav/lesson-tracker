#!/usr/bin/env bash
#
# Копия прода на свою машину: база и вложения — чтобы посмотреть глазами
# настоящего пользователя через «Войти как» и ломать что угодно, не трогая
# боевой сервер.
#
#   ./scripts/pull-prod-db.sh           # спросит подтверждение
#   ./scripts/pull-prod-db.sh --yes     # без вопроса
#
# Что делает, по порядку:
#   1. снимает дамп боевой базы по ssh — только чтение, прод работает дальше;
#   2. кладёт рядом копию ТЕКУЩЕЙ локальной базы — дорога назад;
#   3. заливает дамп прода в локальную базу (снос схемы, не --clean);
#   4. migrate — main бывает впереди прода;
#   5. докачивает вложения в dev-бакет (manage.py pull_files), если есть
#      ~/secrets/lesson-tracker.pull.env с токеном ТОЛЬКО НА ЧТЕНИЕ.
# Всё складывается в ~/backups/prod-pull-<дата>/ и не удаляется.
#
# Направление одно: прод -> ноутбук. Обратно этим путём не ездит ничего, и
# ни один ключ, который скрипт держит в руках, писать на прод не умеет.
#
# Чего стоит знать до запуска (подробно — .claude/rules/seed-data.md):
#   * на ноутбуке окажутся персональные данные школы;
#   * ключ Anthropic в .env разработки настоящий: «распознать» на копии
#     настоящей работы — это оплаченный запрос;
#   * письма не уходят: EMAIL_HOST в .env разработки пуст, коды входа — в
#     `docker compose logs backend`.
#
# Вернуть посев: docker compose exec backend python manage.py seed_demo --flush
# Вернуть прежнюю базу: заливка local-before.sql.gz тем же порядком, что шаг 3.

set -Eeuo pipefail
# дампы — персональные данные школы: читать их должен только хозяин
umask 077

REPO_DIR="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
cd "$REPO_DIR"

log()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
info() { printf '    %s\n' "$*"; }
warn() { printf '\033[33m    %s\033[0m\n' "$*"; }
fail() { printf '\033[31mОшибка: %s\033[0m\n' "$*" >&2; exit 1; }

ASSUME_YES=0
case "${1:-}" in
    --yes|-y) ASSUME_YES=1 ;;
    "") ;;
    -h|--help) sed -n '3,/^$/p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) fail "неизвестный аргумент: $1" ;;
esac

. scripts/contours.sh
contour prod

PULL_ENV="${PULL_ENV_FILE:-$HOME/secrets/lesson-tracker.pull.env}"
OUT="$HOME/backups/prod-pull-$(date +%F_%H%M)"
C="docker compose"
PROD_C="docker compose --env-file .env.prod -f docker-compose.prod.yml"

env_value() { sed -n "s/^$1=//p" .env 2>/dev/null | tail -1 | tr -d '"\r'; }

# --- это точно машина разработчика? -----------------------------------------
# Белый список, как у остальных скриптов контуров: база, которую сейчас
# снесут, обязана быть базой разработки. На боевом сервере .env нет вовсе
# (там .env.prod), а DEBUG разработки включён всегда.
[ -f .env ] || fail "нет .env в $REPO_DIR — это не машина разработчика"
case "$(env_value DEBUG | tr '[:upper:]' '[:lower:]')" in
    true|1|yes|on) ;;
    *) fail "в .env DEBUG не включён — сносить эту базу не буду" ;;
esac
DBU="$(env_value POSTGRES_USER)"; DBU="${DBU:-lessons}"
DBN="$(env_value POSTGRES_DB)";   DBN="${DBN:-lessons}"

for service in db backend; do
    $C ps --status running --services 2>/dev/null | grep -qx "$service" ||
        fail "контейнер $service не запущен — сначала ./scripts/dev-up.sh"
done

# --- версии: psql цели не старше pg_dump источника --------------------------
# Хвост дампа — метакоманды \restrict/\unrestrict (патчи 16.x), и psql старше
# того, чем снимали, на них спотыкается. Спотыкается уже ПОСЛЕ сноса схемы,
# поэтому спрашиваем до.
log "Сверяю версии Postgres"
prod_ver="$(ssh -o BatchMode=yes "$SERVER" "cd $REMOTE_DIR && $PROD_C exec -T db pg_dump --version" < /dev/null |
    grep -oE '[0-9]+\.[0-9]+' | head -1)" || fail "не достучался до прода ($SERVER)"
local_ver="$($C exec -T db psql --version < /dev/null | grep -oE '[0-9]+\.[0-9]+' | head -1)"
info "прод pg_dump $prod_ver, локальный psql $local_ver"
[ "$(printf '%s\n%s\n' "$prod_ver" "$local_ver" | sort -V | head -1)" = "$prod_ver" ] ||
    fail "локальный psql старше боевого — сначала: $C pull db && $C up -d db"

# --- подтверждение -----------------------------------------------------------
log "Локальная база «$DBN» будет ЗАМЕНЕНА копией прода"
info "копия текущей и дамп прода лягут в $OUT"
if [ "$ASSUME_YES" -eq 0 ]; then
    [ -t 0 ] || fail "нет терминала для подтверждения — передайте --yes"
    printf '    Продолжаем? [y/N] '
    IFS= read -r answer || fail "ввод прерван"
    case "$answer" in [yYдД]*) ;; *) fail "отменено" ;; esac
fi

mkdir -p "$OUT"

# --- 1. дамп прода -----------------------------------------------------------
log "Снимаю дамп прода (только чтение)"
ssh -o BatchMode=yes "$SERVER" \
    "cd $REMOTE_DIR && $PROD_C exec -T db pg_dump -U lessons -d lessons --no-owner --no-acl" \
    < /dev/null | gzip > "$OUT/prod.sql.gz"
# Целость — по хвосту: pg_dump пишет строку о завершении последней, и
# оборванный поток её не содержит.
zcat "$OUT/prod.sql.gz" | tail -5 | grep -q 'PostgreSQL database dump complete' ||
    fail "дамп прода неполный — локальная база не тронута ($OUT/prod.sql.gz)"
info "$(du -h "$OUT/prod.sql.gz" | cut -f1), таблиц: $(zcat "$OUT/prod.sql.gz" | grep -c '^COPY ')"

# --- 2. копия локальной базы -------------------------------------------------
log "Сохраняю текущую локальную базу"
$C exec -T db pg_dump -U "$DBU" -d "$DBN" --no-owner --no-acl < /dev/null |
    gzip > "$OUT/local-before.sql.gz"
zcat "$OUT/local-before.sql.gz" | tail -5 | grep -q 'PostgreSQL database dump complete' ||
    fail "копия локальной базы неполная — дальше не иду"

# --- 3. заливка --------------------------------------------------------------
# backend держит соединения, и DROP SCHEMA при нём встал бы насмерть. Гасим —
# и ловушкой обещаем поднять обратно, как бы ни кончилось.
log "Заливаю дамп прода в локальную базу"
$C stop backend < /dev/null
trap '$C start backend < /dev/null >/dev/null 2>&1 || true' EXIT

$C exec -T db psql -U "$DBU" -d "$DBN" -v ON_ERROR_STOP=1 -q -c \
    "DROP SCHEMA public CASCADE; CREATE SCHEMA public AUTHORIZATION $DBU; GRANT ALL ON SCHEMA public TO public;" \
    < /dev/null
zcat "$OUT/prod.sql.gz" | $C exec -T db psql -U "$DBU" -d "$DBN" -q -v ON_ERROR_STOP=1 >/dev/null

$C start backend < /dev/null
trap - EXIT

# --- 4. миграции -------------------------------------------------------------
log "Догоняю схему до main"
for _ in $(seq 1 30); do
    $C exec -T backend python manage.py check --database default < /dev/null >/dev/null 2>&1 && break
    sleep 2
done
# Вывод — в переменную, а не в grep конвейером: иначе упавшая миграция
# терялась бы в `|| true`, и скрипт сказал бы «Готово» над полуживой базой.
migrated="$($C exec -T backend python manage.py migrate --noinput < /dev/null 2>&1)" ||
    fail "migrate упал — база уже заменена копией прода:
$migrated"
printf '%s\n' "$migrated" | grep -E 'Applying|No migrations' | sed 's/^/    /' || true

# --- 5. вложения -------------------------------------------------------------
log "Вложения"
if [ -f "$PULL_ENV" ]; then
    # Ключи передаются контейнеру ИМЕНАМИ, а не значениями: в тексте команды
    # их нет, и в выводе ps тоже.
    set -a; . "$PULL_ENV"; set +a
    $C exec -T -e PULL_R2_BUCKET -e PULL_R2_ACCESS_KEY_ID -e PULL_R2_SECRET_ACCESS_KEY \
        backend python manage.py pull_files < /dev/null ||
        warn "вложения докачались не все — база уже заменена; повторите: $C exec backend python manage.py pull_files"
else
    warn "нет $PULL_ENV — вложения не копирую, строки в базе будут без файлов"
fi

# --- итог --------------------------------------------------------------------
log "Готово"
q() { $C exec -T db psql -U "$DBU" -d "$DBN" -tAc "$1" < /dev/null; }
info "людей: $(q 'select count(*) from accounts_user'), школ: $(q 'select count(*) from schools_school')"
info "войти: http://localhost:5173 -> меню -> «Войти как»"
info "всё лежит в $OUT"
info "вернуть посев: $C exec backend python manage.py seed_demo --flush"
