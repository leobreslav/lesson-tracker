#!/usr/bin/env bash
#
# Перенос env-файла контура с ноутбука на его сервер.
#
#   ./scripts/sync-env.sh prod
#   ./scripts/sync-env.sh staging
#   ./scripts/sync-env.sh staging --yes     # без вопроса, для скриптов
#
# Правило, ради которого это заведено: **ключи правятся только на ноутбуке**.
# На серверах их не редактируют руками вовсе. Иначе у файла два хозяина, и
# однажды перенос затрёт правку, сделанную на сервере, — а заметят это в день,
# когда что-нибудь перестанет пускать.
#
# До этого скрипта правило действовало только для прода: перенос жил внутри
# push-deploy.sh, а файл стенда правился прямо на сервере. Отсюда и вышла
# путаница с двумя открытыми `nano` на одном файле.
#
# Значения не печатаются никогда. При расхождении показываются только ИМЕНА
# появившихся и исчезнувших переменных — по ним видно, что меняется, и по ним
# же ловится опечатка в имени.

set -Eeuo pipefail

REPO_DIR="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
cd "$REPO_DIR"

log()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
info() { printf '    %s\n' "$*"; }
ok()   { printf '\033[32m    %s\033[0m\n' "$*"; }
warn() { printf '\033[33m    %s\033[0m\n' "$*"; }
fail() { printf '\033[31mОшибка: %s\033[0m\n' "$*" >&2; exit 1; }

ENV_BACKUPS=3

CONTOUR="${1:-}"
ASSUME_YES=0
[ "${2:-}" = "--yes" ] && ASSUME_YES=1

# --- контур ------------------------------------------------------------------
# Адреса живут в одном месте на весь репозиторий: в день переезда правится
# один файл, а не три скрипта.
. "$REPO_DIR/scripts/contours.sh"
contour "$CONTOUR" || exit 1

log "Проверяю .env.prod контура «$CONTOUR» на $SERVER"

# Нет файла — это не отказ: контур мог не заводиться на этой машине.
if [ ! -f "$ENV_SOURCE" ]; then
    warn "нет локального файла $ENV_SOURCE — шаг пропущен."
    info "На сервере останется тот .env.prod, что там уже лежит."
    exit 0
fi

# Один CR вместо перевода строки — и compose прочитает файл как одну
# переменную, а Django не сойдётся с базой по паролю (см. CLAUDE.md).
if grep -q $'\r' "$ENV_SOURCE"; then
    fail "в $ENV_SOURCE концы строк CR или CRLF.
compose прочитает такой файл как одну переменную. Лечится:
  tr -d '\\r' < \"$ENV_SOURCE\" > /tmp/env && mv /tmp/env \"$ENV_SOURCE\""
fi

sha_of() { sha256sum "$1" | cut -d' ' -f1; }

# `LC_ALL=C` здесь обязателен с обеих сторон, и стоило это ложной тревоги.
# `comm` требует, чтобы оба списка были отсортированы **одинаково**, а порядок
# зависит от локали: в C локали подчёркивание (0x5F) идёт после букв, в
# UTF-8 — не участвует в сравнении первого уровня вовсе. Поэтому
# BOOTSTRAP_SUPERUSERS и BOOTSTRAP_SUPERUSER_EMAIL встают в разном порядке на
# ноутбуке и на сервере, и `comm` докладывает о переменной, которая никуда не
# девалась. Ошибка безобидна ровно до того дня, когда на такое сообщение
# перестанут смотреть, — а это единственное место, которое говорит, что
# меняется в секретах.
NAMES_CMD="grep -oE '^[A-Za-z_][A-Za-z0-9_]*=' .env.prod | tr -d '=' | LC_ALL=C sort"

local_sum="$(sha_of "$ENV_SOURCE")"
remote_sum="$(ssh -o BatchMode=yes "$SERVER" "cd $REMOTE_DIR && sha256sum .env.prod 2>/dev/null | cut -d' ' -f1" || true)"

if [ "$local_sum" = "$remote_sum" ]; then
    ok ".env.prod актуален"
    exit 0
fi

if [ -z "$remote_sum" ]; then
    info "на сервере .env.prod ещё нет — будет создан"
else
    remote_names="$(ssh -o BatchMode=yes "$SERVER" "cd $REMOTE_DIR && $NAMES_CMD" || true)"
    remote_file="$(mktemp)"; printf '%s\n' "$remote_names" | sed '/^$/d' > "$remote_file"
    local_names="$(grep -oE '^[A-Za-z_][A-Za-z0-9_]*=' "$ENV_SOURCE" | tr -d '=' | LC_ALL=C sort)"
    added="$(comm -23 <(printf '%s\n' "$local_names") "$remote_file" || true)"
    removed="$(comm -13 <(printf '%s\n' "$local_names") "$remote_file" || true)"
    rm -f "$remote_file"
    if [ -z "$added" ] && [ -z "$removed" ]; then
        info "набор переменных тот же, различаются значения"
    else
        [ -z "$added" ]   || printf '    \033[32m+ %s (новая)\033[0m\n' $added
        [ -z "$removed" ] || printf '    \033[33m− %s (исчезла)\033[0m\n' $removed
    fi
fi

if [ "$ASSUME_YES" -eq 0 ]; then
    [ -t 0 ] || fail "нужно подтверждение на перезапись .env.prod, а терминала нет.
Запустите вручную или добавьте --yes"
    if [ -z "$remote_sum" ]; then
        printf '    Скопировать .env.prod на сервер? [y/N] '
    else
        printf '    Перезаписать .env.prod на сервере? [y/N] '
    fi
    IFS= read -r answer || fail "ввод прерван"
    case "$answer" in
        y|Y|yes|Yes|д|Д|да|Да) ;;
        *) warn "Оставляю .env.prod на сервере как есть."; exit 0 ;;
    esac
fi

# Прежде чем писать — убедиться, что машина та. Список адресов не спасает от
# устаревшего адреса, а перезапись env-файла не на том сервере это худшее из
# того, что этот скрипт умеет.
contour_matches_machine || exit 1

# Копия делается до перезаписи и до всего остального: если scp оборвётся на
# середине, откатываться будет к чему.
if [ -n "$remote_sum" ]; then
    stamp="$(date '+%Y-%m-%d_%H%M%S')"
    ssh -o BatchMode=yes "$SERVER" "cd $REMOTE_DIR && cp -p .env.prod .env.prod.bak.$stamp &&
        chmod 600 .env.prod.bak.$stamp &&
        ls -1t .env.prod.bak.* | tail -n +$((ENV_BACKUPS + 1)) | xargs -r rm -f"
    info "резервная копия: .env.prod.bak.$stamp (храним последние $ENV_BACKUPS)"
fi

scp -q "$ENV_SOURCE" "$SERVER:$REMOTE_DIR/.env.prod"
ssh -o BatchMode=yes "$SERVER" "chmod 600 $REMOTE_DIR/.env.prod"

remote_sum="$(ssh -o BatchMode=yes "$SERVER" "cd $REMOTE_DIR && sha256sum .env.prod | cut -d' ' -f1")"
[ "$local_sum" = "$remote_sum" ] ||
    fail "файл скопировался, но контрольные суммы не сошлись — проверьте вручную"

ok ".env.prod обновлён"
info "чтобы контейнеры увидели новые значения, нужен перезапуск:"
info "  ssh $SERVER 'cd $REMOTE_DIR && ./deploy.sh'"
