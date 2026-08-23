#!/usr/bin/env bash
#
# Сторож для scripts/check-login-door.sh.
#
#   bash scripts/test-check-login-door.sh
#
# Замок стоит на пути выкатки и решает один вопрос: можно ли открывать этот
# контур. Ошибётся в одну сторону — стенд выкатится публично открытым;
# ошибётся в другую — перестанет выкатываться прод, которому список
# допущенных не нужен вовсе. Поэтому проверяются обе стороны, и отдельно —
# три способа соврать на ровном месте: форма «да» (`1`, `yes`, `True`),
# кавычки вокруг значения и хвостовой \r от редактора с виндовыми концами
# строк. Каждый из трёх выглядит как «значение задано», а читается как
# пустота.
#
# Секунда, без сети и без контейнера.

set -Eeuo pipefail

GUARD="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)/check-login-door.sh"
[ -f "$GUARD" ] || { echo "нет $GUARD"; exit 1; }

PASS=0
FAIL=0

report() {
    if [ "$1" = "ok" ]; then
        PASS=$((PASS + 1)); printf '  \033[32mok\033[0m   %s\n' "$2"
    else
        FAIL=$((FAIL + 1)); printf '  \033[31mFAIL\033[0m %s\n' "$2"
        [ -n "${3:-}" ] && printf '       %s\n' "$3"
    fi
}

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# Кладёт env-файл из переданных строк и возвращает путь.
env_with() {
    local file="$WORK/env.$RANDOM"
    printf '%s\n' "$@" > "$file"
    printf '%s' "$file"
}

# Ждём, что замок пропустит.
passes() {
    local why="$1"; shift
    local out
    if out="$(bash "$GUARD" "$(env_with "$@")" 2>&1)"; then
        report ok "$why"
    else
        report fail "$why" "отказал: $out"
    fi
}

# Ждём, что замок откажет — и назовёт переменную, которой не хватает.
refuses() {
    local why="$1"; shift
    local out
    if out="$(bash "$GUARD" "$(env_with "$@")" 2>&1)"; then
        report fail "$why" "пропустил, хотя не должен был"
    elif printf '%s' "$out" | grep -q LOGIN_ALLOWED_EMAILS; then
        report ok "$why"
    else
        report fail "$why" "отказал, но не назвал LOGIN_ALLOWED_EMAILS: $out"
    fi
}

printf '\n\033[1mЗамок на дверь контура\033[0m\n'

# --- пропускает -------------------------------------------------------------

passes "прод: дев-двери нет вовсе" \
    'DEBUG=False' 'DOMAIN=example.com'

passes "дев-дверь выключена явно" \
    'E2E_TEST_LOGIN=false' 'DEBUG=False'

passes "стенд со списком" \
    'E2E_TEST_LOGIN=true' 'LOGIN_ALLOWED_EMAILS=me@example.com'

passes "список из нескольких адресов" \
    'E2E_TEST_LOGIN=true' 'LOGIN_ALLOWED_EMAILS=me@example.com,you@example.com'

passes "список в кавычках — это тоже список" \
    'E2E_TEST_LOGIN=true' 'LOGIN_ALLOWED_EMAILS="me@example.com"'

# Пустое значение флага — это «выключено», а не «непонятно». Так же его
# прочтёт и Django, и разойтись эти два чтения не должны: разошедшись, они
# дали бы контур, который замок пропустил, а дверь на нём открыта.
passes "пустое значение флага — дверь закрыта" \
    'E2E_TEST_LOGIN=' 'LOGIN_ALLOWED_EMAILS='

# --- отказывает -------------------------------------------------------------

refuses "дверь открыта, списка нет" \
    'E2E_TEST_LOGIN=true' 'DEBUG=False'

refuses "список есть строкой, но пустой" \
    'E2E_TEST_LOGIN=true' 'LOGIN_ALLOWED_EMAILS='

refuses "список из одних пробелов" \
    'E2E_TEST_LOGIN=true' 'LOGIN_ALLOWED_EMAILS=   '

refuses "список в пустых кавычках" \
    'E2E_TEST_LOGIN=true' 'LOGIN_ALLOWED_EMAILS=""'

refuses "«да» единицей" \
    'E2E_TEST_LOGIN=1'

refuses "«да» с большой буквы" \
    'E2E_TEST_LOGIN=True'

refuses "«да» словом yes" \
    'E2E_TEST_LOGIN=yes'

refuses "«да» в кавычках" \
    'E2E_TEST_LOGIN="true"'

# Редактор с виндовыми концами строк: значение выглядит заданным, а хвостовой
# \r делает его чужим для любого сравнения. В этом проекте на такой файл уже
# наступали — см. «Особенности окружения» в CLAUDE.md.
crlf="$WORK/crlf.env"
printf 'E2E_TEST_LOGIN=true\r\nDEBUG=False\r\n' > "$crlf"
if out="$(bash "$GUARD" "$crlf" 2>&1)"; then
    report fail "виндовые концы строк не прячут открытую дверь" "пропустил"
else
    report ok "виндовые концы строк не прячут открытую дверь"
fi

# --- нет файла --------------------------------------------------------------

if out="$(bash "$GUARD" "$WORK/нет-такого" 2>&1)"; then
    report fail "нет env-файла — отказ" "пропустил"
else
    report ok "нет env-файла — отказ"
fi

printf '\n  прошло: %s, упало: %s\n\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
