#!/usr/bin/env bash
#
# Унести готовую работу в main и на прод — из любого места, включая облачную
# сессию и телефон. Ни ssh, ни ключей: всё через git и gh.
#
#   ./scripts/ship.sh                 # влить ветку в main (=> полный прогон CI)
#   ./scripts/ship.sh --prod          # влить и выкатить на прод
#   ./scripts/ship.sh --prod-only     # main уже в порядке, двинуть только прод
#   ./scripts/ship.sh --prod --yes    # без вопроса, для скриптов
#
# ЗАЧЕМ ОТДЕЛЬНЫЙ СКРИПТ. Раньше «унести» умел только push-deploy.sh, а он
# ходит на сервер по ssh — то есть работает ровно на одной машине, где лежит
# ключ. Облачная сессия, чужой ноутбук и телефон не могли ничего. Здесь ssh не
# нужен вовсе: скрипт двигает ветки на GitHub, а прод подтягивает
# origin/production сам, раз в 5 минут.
#
# ДВЕ ДОРОГИ, И gh НЕ ОБЯЗАТЕЛЕН. Ветку двигает либо `gh` серверной операцией,
# либо обычный `git push` — что найдётся, в этом порядке.
#
# Изначально дорога была одна, через gh, и с доводом: «в облачной сессии
# площадка запрещает пуш в любую ветку, кроме собственной, а серверные операции
# GitHub под запрет не попадают». Довод оказался неверен — по крайней мере не
# везде: из облачной сессии пуш в main и production прошёл обычным `git push`.
# А вот `gh` там как раз не оказалось, и скрипт умирал первой же строкой
# проверок — то есть был мёртв ровно в том месте, ради которого написан.
#
# Отсюда порядок, а не замена. gh остаётся первым: он проверен, ему не нужны
# объекты в локальном репозитории, и там, где пуш действительно запрещён, он
# единственный сработает. Но его отсутствие больше не отказ.
#
# Обе дороги двигают ветку **только перемоткой**. У gh это проверка предком
# перед PATCH, у git — сам сервер, потому что пуш без `--force`. Совпадение
# намеренное: правило одно, и разойтись дорогам тут негде.
#
# ЧЕГО ЭТОТ ПУТЬ НЕ УМЕЕТ — возить .env.prod: файл лежит вне git. Меняли набор
# переменных — нужен ноутбук (./scripts/sync-env.sh prod), и только потом сюда.
#
# ПРАВО, А НЕ ВОЗМОЖНОСТЬ. Технически этот скрипт запускается откуда угодно, в
# том числе агентом. Правило проекта — в .claude/skills/deploy/SKILL.md:
# выкатка на прод идёт **по явной просьбе человека про этот запуск**, и «делай
# что нужно» в начале сессии ею не является. На том конце живая школа.

set -Eeuo pipefail

REPO_DIR="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
cd "$REPO_DIR"

MAIN="main"
PROD="production"

log()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
info() { printf '    %s\n' "$*"; }
ok()   { printf '\033[32m%s\033[0m\n' "$*"; }
fail() { printf '\033[31mОшибка: %s\033[0m\n' "$*" >&2; exit 1; }

trap 'fail "команда на строке $LINENO завершилась с ошибкой"' ERR

usage() { sed -n '3,/^$/p' "$0" | sed 's/^# \{0,1\}//'; }

DO_LAND=1
DO_PROD=0
ASSUME_YES=0

while [ $# -gt 0 ]; do
    case "$1" in
        --prod)      DO_PROD=1 ;;
        --prod-only) DO_PROD=1; DO_LAND=0 ;;
        --yes|-y)    ASSUME_YES=1 ;;
        -h|--help)   usage; exit 0 ;;
        *)           fail "неизвестный аргумент: $1" ;;
    esac
    shift
done

command -v git >/dev/null || fail "git не найден"

# Чем двигаем ветки. gh первым — см. «ДВЕ ДОРОГИ» в шапке; неавторизованный
# gh считается отсутствующим, потому что толку от него ровно столько же.
if command -v gh >/dev/null && gh auth status >/dev/null 2>&1; then
    VIA=gh
    SLUG="$(gh repo view --json nameWithOwner --jq .nameWithOwner)"
else
    VIA=git
    SLUG=""
fi

# Какой дорогой пошли — говорим, но только когда она вторая. На ноутбуке gh
# есть всегда, и строка «иду через gh» была бы шумом в каждом запуске; а вот
# «gh не годится» объясняет заранее, почему отказ, если он придёт, выглядит
# отказом git'а, а не GitHub API.
[ "$VIA" = gh ] || info "gh нет или не авторизован — двигаю ветки обычным пушем"

# Вершина ветки на GitHub — или пустая строка, если ветки там нет.
#
# Пустая строка получается не сама собой, и это стоило падения на первом же
# запуске. При ошибке `gh` печатает **тело ответа** в stdout, минуя `--jq`, —
# то есть на несуществующую ветку возвращает не «ничего» и не «null», а json с
# «Not Found» длиной в сто тридцать символов. Дальше он уезжал в следующий
# запрос как sha, и GitHub отвечал 422 про сорок символов.
#
# Поэтому ответ проверяется на форму, а не на код возврата: sha — это сорок
# знаков из [0-9a-f], всё остальное значит «ветки нет».
ref_sha() {
    local answer
    if [ "$VIA" = gh ]; then
        answer="$(gh api "repos/$SLUG/git/refs/heads/$1" --jq .object.sha 2>/dev/null || true)"
    else
        # `ls-remote` спрашивает GitHub, а не наш `origin/…`: локальная копия
        # ветки бывает устаревшей, а решение принимается по тому, что там
        # сейчас. Вывод — «sha<TAB>refs/heads/имя», ветки нет — пусто.
        answer="$(git ls-remote --heads origin "$1" 2>/dev/null | awk 'NR==1{print $1}' || true)"
    fi
    case "$answer" in
        *[!0-9a-f]*) answer="" ;;
    esac
    [ "${#answer}" = 40 ] || answer=""
    printf '%s' "$answer"
}

# Двигает ветку на GitHub. Только перемотка: sha обязан быть потомком того, что
# там лежит. force здесь нет и быть не должно — на том конце контуры, которые
# этот ref считают правдой.
move_ref() {
    local branch="$1" sha="$2" current
    current="$(ref_sha "$branch")"

    if [ "$current" = "$sha" ]; then
        info "$branch уже на ${sha:0:8} — двигать нечего"
        return 1
    fi
    if [ -n "$current" ] && ! git merge-base --is-ancestor "$current" "$sha" 2>/dev/null; then
        fail "$branch (${current:0:8}) не является предком ${sha:0:8}.
Это не перемотка, а перезапись — руками и осознанно, не отсюда."
    fi

    if [ "$VIA" = gh ]; then
        gh api "repos/$SLUG/git/refs/heads/$branch" -X PATCH -f sha="$sha" >/dev/null
    else
        # Без `--force` — и это не осторожность, а тот же запрет, что проверен
        # выше: перемотку сервер примет, перезапись отклонит сам.
        git push --quiet origin "$sha:refs/heads/$branch"
    fi
    info "$branch: ${current:0:8}${current:+ → }${sha:0:8}"
    return 0
}

git fetch --quiet origin

# --- влить ветку в main ------------------------------------------------------
if [ "$DO_LAND" -eq 1 ]; then
    BRANCH="$(git rev-parse --abbrev-ref HEAD)"
    case "$BRANCH" in
        "$MAIN"|"$PROD") fail "вы на «$BRANCH» — вливать нечего. Для прода: --prod-only" ;;
    esac

    [ -z "$(git status --porcelain)" ] ||
        fail "в рабочем дереве есть незакоммиченное — сначала коммит:
$(git status --short)"

    LOCAL="$(git rev-parse HEAD)"
    REMOTE="$(git rev-parse --verify --quiet "origin/$BRANCH" || true)"
    [ -n "$REMOTE" ] || fail "ветки «$BRANCH» нет на origin — сначала git push -u origin $BRANCH"
    [ "$LOCAL" = "$REMOTE" ] ||
        fail "origin/$BRANCH (${REMOTE:0:8}) не совпадает с рабочим деревом (${LOCAL:0:8}).
Запушьте ветку: git push"

    # Требуем перемотки, а не сливаем merge-коммитом. История здесь линейная и
    # держится на том, что каждое сообщение коммита — отдельная мысль; слияние
    # прячет их за «Merge branch …», а конфликт превращает в чужую работу
    # посреди чужой ветки. Отказ громкий, и чинится он в той же сессии, где
    # ветка и лежит: git rebase origin/main.
    if ! git merge-base --is-ancestor "origin/$MAIN" "$LOCAL"; then
        fail "«$BRANCH» отстала от origin/$MAIN — это уже не перемотка.
Переберите ветку и повторите:
    git fetch origin && git rebase origin/$MAIN && git push --force-with-lease"
    fi

    log "Вливаю «$BRANCH» в $MAIN"
    move_ref "$MAIN" "$LOCAL" || true
    info "на main пойдёт полный прогон CI; прод ждёт его зелёного и --prod"
fi

# --- двинуть прод ------------------------------------------------------------
if [ "$DO_PROD" -eq 1 ]; then
    git fetch --quiet origin "$MAIN"
    TARGET="$(git rev-parse "origin/$MAIN")"

    if [ "$ASSUME_YES" -eq 0 ]; then
        CURRENT="$(gh api "repos/$SLUG/git/refs/heads/$PROD" --jq .object.sha 2>/dev/null || true)"
        log "Выкатка на ПРОД — на том конце живая школа"
        if [ -n "$CURRENT" ] && [ "$CURRENT" != "$TARGET" ]; then
            info "поедет:"
            git --no-pager log --oneline "$CURRENT..$TARGET" | sed 's/^/      /'
        fi
        [ -t 0 ] || fail "нет терминала для подтверждения — передайте --yes, если так и задумано"
        printf '    Выкатываем? [y/N] '
        IFS= read -r answer || fail "ввод прерван"
        case "$answer" in [yYдД]*) ;; *) fail "отменено" ;; esac
    fi

    log "Двигаю $PROD"
    if move_ref "$PROD" "$TARGET"; then
        info "прод подтянет сам, до 5 минут"
        info "поторопить (нужен ssh): ssh <прод> '~/lesson-tracker/scripts/prod-autodeploy.sh'"
    fi

    printf '\n'
    info "Набор переменных менялся? .env.prod этим путём НЕ едет —"
    info "нужен ноутбук: ./scripts/sync-env.sh prod"
fi

printf '\n'
ok "Готово"
