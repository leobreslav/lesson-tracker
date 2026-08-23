#!/usr/bin/env bash
#
# Сверка ключей по всем контурам — одной командой и не показывая значений.
#
#   ./scripts/check-secrets.sh
#
# Отвечает на вопрос, который иначе занимает полчаса и три ssh-сессии: «везде
# ли поправлено и не забыли ли где». Печатает отпечатки (первые 12 символов
# sha256), а не сами ключи, поэтому вывод можно показывать кому угодно и
# оставлять в переписке.
#
# Читать так: одинаковый отпечаток в двух столбцах значит ОДИН И ТОТ ЖЕ
# секрет в двух контурах. Иногда это правильно (`VITE_GOOGLE_CLIENT_ID` —
# копия `GOOGLE_CLIENT_ID` по построению), а иногда это и есть то, что вы
# ищете: боевой ключ, уехавший на стенд.
#
# Значения не печатаются никогда и никуда не копируются: скрипт только
# считает и сравнивает.

set -Eeuo pipefail

log()  { printf '\n\033[1m%s\033[0m\n' "$*"; }
warn() { printf '\033[33m  %s\033[0m\n' "$*"; }
bad()  { printf '\033[31m  %s\033[0m\n' "$*"; }

# --- где искать ---------------------------------------------------------------
# Контуры перечислены явно. Забытый контур — та же беда, что забытый ключ,
# поэтому список тут, а не собирается догадкой.
LOCAL_DEV="${LOCAL_DEV:-$PWD/.env}"
LOCAL_PROD="${LOCAL_PROD:-$HOME/secrets/lesson-tracker.env.local-prod}"
# Адреса машин — из общего описания контуров, а не своей копией здесь.
. "$(dirname "$(readlink -f "$0")")/contours.sh"
contour prod    || exit 1
PROD_HOST="$SERVER";    PROD_DIR="$REMOTE_DIR";    MASTER_PROD="$ENV_SOURCE"
contour staging || exit 1
STAGING_HOST="$SERVER"; STAGING_DIR="$REMOTE_DIR"; MASTER_STAGING="$ENV_SOURCE"

# Ключи, которые вообще стоит сверять. Не все переменные — только секреты и
# то, что различает контуры.
KEYS=(
    SECRET_KEY POSTGRES_PASSWORD
    GOOGLE_CLIENT_ID GOOGLE_CLIENT_SECRET
    R2_ACCESS_KEY_ID R2_SECRET_ACCESS_KEY R2_BUCKET_NAME
    R2_BACKUP_ACCESS_KEY_ID R2_BACKUP_BUCKET_NAME
    ANTHROPIC_API_KEY
    DOMAIN
    LOGIN_ALLOWED_EMAILS
)

# --- сбор ---------------------------------------------------------------------
# Отпечаток считается от «ИМЯ=значение», а не от одного значения: так две
# пустые строки не выглядят одинаковыми секретами.
fingerprints() {  # читает файл на stdin, печатает «ИМЯ отпечаток»
    python3 -c '
import sys, re, hashlib
keys = set(sys.argv[1:])
text = sys.stdin.read()
found = {}
for m in re.finditer(r"^([A-Z][A-Z0-9_]*)=(.*)$", text, re.M):
    if m.group(1) in keys:
        v = m.group(2).strip()
        found[m.group(1)] = ("—" if not v
                             else hashlib.sha256(m.group(0).encode()).hexdigest()[:12])
for k in sorted(keys):
    print(k, found.get(k, "нет"))
' "${KEYS[@]}"
}

collect() {  # collect <метка> <команда, печатающая файл>
    local label="$1"; shift
    if ! "$@" 2>/dev/null | fingerprints > "/tmp/secrets-$label.txt"; then
        warn "контур «$label» недоступен — пропускаю"
        : > "/tmp/secrets-$label.txt"
    fi
}

log "Собираю отпечатки"
collect dev      cat "$LOCAL_DEV"
collect master   cat "$MASTER_PROD"
collect localprod cat "$LOCAL_PROD"
collect masterstaging cat "$MASTER_STAGING"
collect prod     ssh -o BatchMode=yes "$PROD_HOST" "cat $PROD_DIR/.env.prod"
collect staging  ssh -o BatchMode=yes "$STAGING_HOST" "cat $STAGING_DIR/.env.prod"

# --- вывод --------------------------------------------------------------------
log "Отпечатки по контурам (— пусто, «нет» строки нет вовсе)"
printf '  %-24s %-13s %-13s %-13s %-13s %-13s %-13s\n' \
    'ключ' 'dev' 'локал-прод' 'мастер-прод' 'ПРОД' 'мастер-стенд' 'стенд'
for k in "${KEYS[@]}"; do
    row=""
    for c in dev localprod master prod masterstaging staging; do
        v="$(awk -v k="$k" '$1==k{print $2}' "/tmp/secrets-$c.txt" 2>/dev/null)"
        row+="$(printf '%-13s ' "${v:-?}")"
    done
    printf '  %-24s %s\n' "$k" "$row"
done

# --- что должно настораживать -------------------------------------------------
log "Разбор"
for k in SECRET_KEY POSTGRES_PASSWORD R2_SECRET_ACCESS_KEY ANTHROPIC_API_KEY; do
    p="$(awk -v k="$k" '$1==k{print $2}' /tmp/secrets-prod.txt 2>/dev/null)"
    s="$(awk -v k="$k" '$1==k{print $2}' /tmp/secrets-staging.txt 2>/dev/null)"
    [ -n "$p" ] && [ "$p" = "$s" ] && [ "$p" != "—" ] &&
        bad "$k одинаков на проде и стенде — боевой секрет лежит на машине, где можно всё"
done
# Мастер-копия на ноутбуке — единственный хозяин env-файла (см.
# .claude/rules/deploy.md). Разошлась с сервером — значит либо забыли отвезти,
# либо правили руками на машине; и то и другое кончается затёртым ключом.
for k in "${KEYS[@]}"; do
    m="$(awk -v k="$k" '$1==k{print $2}' /tmp/secrets-master.txt 2>/dev/null)"
    p="$(awk -v k="$k" '$1==k{print $2}' /tmp/secrets-prod.txt 2>/dev/null)"
    [ -n "$m" ] && [ -n "$p" ] && [ "$m" != "$p" ] &&
        bad "$k расходится: мастер-копия и ПРОД разные — отвезите sync-env.sh prod"
    ms="$(awk -v k="$k" '$1==k{print $2}' /tmp/secrets-masterstaging.txt 2>/dev/null)"
    s="$(awk -v k="$k" '$1==k{print $2}' /tmp/secrets-staging.txt 2>/dev/null)"
    [ -n "$ms" ] && [ -n "$s" ] && [ "$ms" != "$s" ] &&
        bad "$k расходится: мастер-копия и стенд разные — отвезите sync-env.sh staging"
done
g_p="$(awk '$1=="GOOGLE_CLIENT_SECRET"{print $2}' /tmp/secrets-prod.txt 2>/dev/null)"
g_s="$(awk '$1=="GOOGLE_CLIENT_SECRET"{print $2}' /tmp/secrets-staging.txt 2>/dev/null)"
[ -n "$g_p" ] && [ "$g_p" = "$g_s" ] && [ "$g_p" != "—" ] &&
    warn "GOOGLE_CLIENT_SECRET общий у прода и стенда — один OAuth-клиент на два контура"
for k in DOMAIN SECRET_KEY POSTGRES_PASSWORD; do
    for c in prod staging; do
        v="$(awk -v k="$k" '$1==k{print $2}' "/tmp/secrets-$c.txt" 2>/dev/null)"
        [ "$v" = "—" ] || [ "$v" = "нет" ] && bad "$k пуст на контуре «$c» — без него контур не поднимется"
    done
done
rm -f /tmp/secrets-*.txt
printf '\n'
