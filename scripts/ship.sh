#!/usr/bin/env bash
#
# Унести готовую работу на контуры — из любого места, включая облачную сессию
# и телефон. Ни ssh, ни ключей: всё через git и gh.
#
#   ./scripts/ship.sh                 # влить ветку в main (=> стенд)
#   ./scripts/ship.sh --prod          # влить и выкатить на прод
#   ./scripts/ship.sh --prod-only     # main уже в порядке, двинуть только прод
#   ./scripts/ship.sh --prod --yes    # без вопроса, для скриптов
#   ./scripts/ship.sh --reseed        # пересеять стенд (аргументы — с контура)
#   ./scripts/ship.sh --reseed --flush --rich   # и с этими аргументами
#
# ЗАЧЕМ ОТДЕЛЬНЫЙ СКРИПТ. Раньше «унести» умел только push-deploy.sh, а он
# ходит на сервер по ssh — то есть работает ровно на одной машине, где лежит
# ключ. Облачная сессия, чужой ноутбук и телефон не могли ничего. Здесь ssh не
# нужен вовсе: скрипт двигает ветки на GitHub, а контуры подтягивают их сами
# (стенд — origin/main каждые 3 минуты, прод — origin/production каждые 5).
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
# ПЕРЕСЕВ УСТРОЕН ТАК ЖЕ, и по той же причине: он умел работать ровно на той
# машине, где лежит ssh-ключ. Просьба — коммит на ветке `staging-seed`, дерево
# от main, смысл в первой строке сообщения («seed: --flush --rich»). Стенд
# смотрит на эту ветку раз в три минуты (scripts/staging-seed-watch.sh) и сам
# зовёт staging-seed.sh. Коммит, а не передвинутая ветка, — чтобы «пересей ещё
# раз» отличалось от «уже сеяли», когда main с тех пор не двигался.
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
SEED="staging-seed"

log()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
info() { printf '    %s\n' "$*"; }
ok()   { printf '\033[32m%s\033[0m\n' "$*"; }
fail() { printf '\033[31mОшибка: %s\033[0m\n' "$*" >&2; exit 1; }

trap 'fail "команда на строке $LINENO завершилась с ошибкой"' ERR

usage() { sed -n '3,/^$/p' "$0" | sed 's/^# \{0,1\}//'; }

DO_LAND=1
DO_PROD=0
DO_SEED=0
ASSUME_YES=0
SEED_ARGS=""

while [ $# -gt 0 ]; do
    case "$1" in
        --prod)      DO_PROD=1 ;;
        --prod-only) DO_PROD=1; DO_LAND=0 ;;
        --yes|-y)    ASSUME_YES=1 ;;
        -h|--help)   usage; exit 0 ;;
        # Всё после --reseed уезжает в seed_demo, а не разбирается здесь:
        # иначе список его флагов пришлось бы держать в двух местах, и они
        # разъехались бы в первый же новый флаг посева.
        --reseed)    DO_SEED=1; DO_LAND=0; shift; SEED_ARGS="$*"; break ;;
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
# запуске `--reseed`. При ошибке `gh` печатает **тело ответа** в stdout, минуя
# `--jq`, — то есть на несуществующую ветку возвращает не «ничего» и не «null»,
# а json с «Not Found» длиной в сто тридцать символов. Дальше он уезжал в
# параметр `parents`, и GitHub отвечал 422 про сорок символов.
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

# Просит стенд пересеяться. Дерево берётся у main, родителем встаёт прошлая
# просьба — значит ветка читается как история пересевов, а каждая новая
# просьба заведомо отличается от предыдущей.
seed_request() {
    local args="$1" main_sha tree parent message body sha

    main_sha="$(ref_sha "$MAIN")"
    [ -n "$main_sha" ] || fail "не вижу ветки $MAIN на GitHub"
    parent="$(ref_sha "$SEED")"                       # пусто — просьба первая

    if [ "$VIA" = gh ]; then
        tree="$(gh api "repos/$SLUG/git/commits/$main_sha" --jq .tree.sha)"
    else
        # Коммит собирается локально, `commit-tree`. Объекты для этого нужны
        # на руках — и дерево main, и прошлая просьба, — поэтому сначала их
        # приносим. Тянем **ветки**, а не sha: выборку по sha сервер разрешает
        # не всегда, а ветка приносит ровно тот же коммит.
        git fetch --quiet origin "$MAIN"
        [ -z "$parent" ] || git fetch --quiet origin "$SEED"
        # Разъехалось между `ls-remote` и `fetch` — падаем громко, а не
        # собираем просьбу от чужого дерева.
        tree="$(git rev-parse "$main_sha^{tree}")" ||
            fail "$MAIN сдвинулся, пока я смотрел — повторите"
    fi

    message="seed:${args:+ $args}"
    # Кто и когда — не для скрипта, а для того, кто через неделю откроет
    # ветку на github.com и спросит, откуда взялся пересев в среду ночью.
    body="$(printf 'Попросил: %s\nОткуда: %s\nКогда: %s' \
        "$(git config user.email || echo неизвестно)" \
        "$(hostname)" "$(date '+%F %T %Z')")"

    if [ "$VIA" = gh ]; then
        if [ -n "$parent" ]; then
            sha="$(gh api "repos/$SLUG/git/commits" -f message="$message

$body" -f tree="$tree" -f "parents[]=$parent" --jq .sha)"
            gh api "repos/$SLUG/git/refs/heads/$SEED" -X PATCH -f sha="$sha" >/dev/null
        else
            sha="$(gh api "repos/$SLUG/git/commits" -f message="$message

$body" -f tree="$tree" --jq .sha)"
            gh api "repos/$SLUG/git/refs" -f ref="refs/heads/$SEED" -f sha="$sha" >/dev/null
        fi
    else
        # Имя и почта нужны `commit-tree`, а в свежем клоне их может не быть
        # вовсе — и тогда он падает с «unable to auto-detect email address».
        # Подставляем свои, но только если человек своих не назвал: у него они
        # осмысленные, а в журнале пересевов автор и есть ответ на «кто просил».
        export GIT_AUTHOR_NAME="${GIT_AUTHOR_NAME:-$(git config user.name || echo ship.sh)}"
        export GIT_AUTHOR_EMAIL="${GIT_AUTHOR_EMAIL:-$(git config user.email || echo ship@local)}"
        export GIT_COMMITTER_NAME="$GIT_AUTHOR_NAME"
        export GIT_COMMITTER_EMAIL="$GIT_AUTHOR_EMAIL"

        if [ -n "$parent" ]; then
            sha="$(printf '%s\n\n%s\n' "$message" "$body" |
                   git commit-tree "$tree" -p "$parent")"
        else
            sha="$(printf '%s\n\n%s\n' "$message" "$body" | git commit-tree "$tree")"
        fi
        # Просьба — потомок прошлой просьбы, значит это перемотка; первая
        # просьба заводит ветку. Оба случая — обычный пуш без `--force`.
        git push --quiet origin "$sha:refs/heads/$SEED"
    fi

    info "просьба ${sha:0:8}: $message"
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
    info "стенд подтянет сам, до 3 минут"
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

# --- попросить стенд пересеяться --------------------------------------------
if [ "$DO_SEED" -eq 1 ]; then
    log "Прошу стенд пересеять базу"
    if [ -n "$SEED_ARGS" ]; then
        info "аргументы: $SEED_ARGS"
    else
        info "аргументы: те, что записаны на самом стенде (STAGING_SEED_ARGS)"
    fi
    seed_request "$SEED_ARGS"
    info "стенд заметит и посеет, до 3 минут"
    info "данные стенда при этом сносятся — на то он и стенд"
fi

printf '\n'
ok "Готово"
