#!/usr/bin/env bash
#
# Деплой с ноутбука одной командой: коммит, пуш и запуск deploy.sh на сервере.
#
#   ./push-deploy.sh "правка календаря"   # закоммитить, запушить, раскатать
#   ./push-deploy.sh                      # спросит сообщение коммита
#   ./push-deploy.sh --deploy-only        # ничего не коммитить, только раскатать
#   ./push-deploy.sh --no-verify "текст"  # не проверять сайт после деплоя
#   ./push-deploy.sh --skip-env "текст"   # не трогать .env.prod на сервере
#
# Перед деплоем на сервер уезжает .env.prod — из локального файла вне
# репозитория (по умолчанию ~/secrets/lesson-tracker.env.prod, меняется
# переменной DEPLOY_ENV_FILE). Главная копия живёт на ноутбуке; на сервере
# файл руками не правят — см. DEPLOY.md, раздел 2.
#
# На проде стоит не main, а ветка `production`: она и есть «то, что сейчас
# выкачено». Скрипт двигает её сам, поэтому здесь ничего не изменилось — но
# знать про неё надо, потому что двинуть её можно и без ноутбука (с github.com
# или через gh), а сервер подхватит из своего crontab. См. scripts/
# prod-autodeploy.sh и .claude/rules/deploy.md.
#
# Адрес сервера и домен можно подменить переменными окружения:
# DEPLOY_SERVER, DEPLOY_DIR, DEPLOY_SITE.

set -Eeuo pipefail

# Адрес, каталог, сайт и главная копия .env.prod — из общего описания
# контуров: единственное место в репозитории, знающее адреса машин.
# ENV_SOURCE лежит вне папки проекта, чтобы git add -A не мог его подобрать.
. "$(dirname "$(readlink -f "$0")")/scripts/contours.sh"
contour prod || exit 1
BRANCH="main"
# Ветка, по которой живёт прод. Отдельная от main намеренно: main двигается
# каждой задачей, а прод — только когда так решили.
DEPLOY_BRANCH="production"

# то, что не должно уехать в репозиторий ни при каких обстоятельствах
FORBIDDEN=(
    '.env' '.env.prod' '.env.local' '.env.*.local' '.env.prod.bak.*'
    '*.pem' '*.key' '*.p12' 'id_rsa*'
    '*.sqlite3' '*.sql' '*.dump'
)

log()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
info() { printf '    %s\n' "$*"; }
ok()   { printf '\033[32m%s\033[0m\n' "$*"; }
warn() { printf '\033[33m%s\033[0m\n' "$*" >&2; }
fail() { printf '\033[31mОшибка: %s\033[0m\n' "$*" >&2; exit 1; }

trap 'fail "команда на строке $LINENO завершилась с ошибкой"' ERR

usage() {
    # До первой пустой строки, а не до номера 17: номер молча устаревает при
    # любой правке шапки — уже устарел однажды.
    sed -n '3,/^$/p' "$0" | sed 's/^# \{0,1\}//'
}

# --- аргументы --------------------------------------------------------------

MESSAGE=""
VERIFY=1
DEPLOY_ONLY=0
SKIP_ENV=0

while [ $# -gt 0 ]; do
    case "$1" in
        --no-verify)   VERIFY=0 ;;
        --deploy-only) DEPLOY_ONLY=1 ;;
        --skip-env)    SKIP_ENV=1 ;;
        -h|--help)     usage; exit 0 ;;
        -*)            fail "неизвестный флаг: $1" ;;
        *)
            [ -z "$MESSAGE" ] || fail "лишний аргумент: $1"
            MESSAGE="$1"
            ;;
    esac
    shift
done

# --- проверки перед стартом -------------------------------------------------

command -v git >/dev/null || fail "git не найден"
command -v ssh >/dev/null || fail "ssh не найден"
command -v scp >/dev/null || fail "scp не найден"
# ship.sh двигает production через API GitHub, а не пушем: та же реализация
# работает в облачной сессии, где пуш в чужую ветку запрещён.
command -v gh  >/dev/null || fail "gh не найден — им двигается ветка $DEPLOY_BRANCH"

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
[ -n "$ROOT" ] || fail "это не git-репозиторий"
[ "$ROOT" = "$PWD" ] || fail "запускайте из корня репозитория: cd $ROOT"

CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
[ "$CURRENT_BRANCH" = "$BRANCH" ] ||
    fail "текущая ветка «$CURRENT_BRANCH», а деплоится только «$BRANCH»"

# секреты не должны быть даже в индексе — это хуже, чем незакоммиченный файл
TRACKED_SECRETS="$(git ls-files -- .env .env.prod .env.local || true)"
[ -z "$TRACKED_SECRETS" ] ||
    fail "в репозитории отслеживаются секреты:
$TRACKED_SECRETS
Уберите их: git rm --cached <файл>"

# git status может показать секрет, если .gitignore правили: git add -A
# утащил бы такой файл в коммит
check_status_files() {
    local line path name pattern found=0

    while IFS= read -r line; do
        [ -n "$line" ] || continue
        path="${line:3}"
        path="${path##* -> }"          # переименование: берём новое имя
        path="${path%\"}"
        path="${path#\"}"
        name="${path##*/}"

        for pattern in "${FORBIDDEN[@]}"; do
            # shellcheck disable=SC2053
            if [[ "$name" == $pattern ]]; then
                warn "  $path"
                found=1
                break
            fi
        done
    done < <(git status --porcelain)

    [ "$found" -eq 0 ] ||
        fail "в рабочем дереве файлы, которым не место в репозитории (см. выше).
Добавьте их в .gitignore или уберите — деплой остановлен"
}

check_status_files

# .env.prod внутри репозитория — вопрос времени, а не вероятности: git add -A
# берёт всё, а имя вроде secrets/lesson-tracker.env.prod под FORBIDDEN не
# подходит. Проверяем до коммита, потому что после него было бы поздно.
if [ "$SKIP_ENV" -eq 0 ] && [ -f "$ENV_SOURCE" ]; then
    ENV_DIR="$(cd "$(dirname "$ENV_SOURCE")" && pwd)"
    case "$ENV_DIR/" in
        "$ROOT"/*)
            fail "$ENV_SOURCE лежит внутри репозитория.
Главный .env.prod должен быть вне проекта — перенесите его, например в
~/secrets/, или укажите путь переменной DEPLOY_ENV_FILE"
            ;;
    esac
fi

# --- коммит и пуш -----------------------------------------------------------

if [ "$DEPLOY_ONLY" -eq 1 ]; then
    log "Коммит и пуш пропущены (--deploy-only)"
else
    if [ -n "$(git status --porcelain)" ]; then
        if [ -z "$MESSAGE" ]; then
            [ -t 0 ] || fail "нет сообщения коммита — передайте его аргументом"

            while [ -z "$MESSAGE" ]; do
                printf 'Сообщение коммита: '
                IFS= read -r MESSAGE || fail "ввод прерван"
                # пробелы по краям не считаются сообщением
                MESSAGE="$(printf '%s' "$MESSAGE" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
                [ -n "$MESSAGE" ] || warn "Пустое сообщение не подойдёт."
            done
        fi

        log "Коммичу изменения"
        git add -A
        git status --short
        git commit -m "$MESSAGE"
    else
        log "Рабочее дерево чистое — коммитить нечего"
    fi

    log "Отправляю в origin/$BRANCH"
    if git rev-parse --abbrev-ref --symbolic-full-name '@{u}' >/dev/null 2>&1; then
        git push
    else
        git push -u origin "$BRANCH"
    fi
fi

# --- ветка production -------------------------------------------------------
#
# Прод стоит на `production`, а не на main, и `deploy.sh` тянет **текущую**
# ветку сервера. Значит после пуша в main прод не увидел бы ничего: выкатка
# прошла бы, отчиталась «Готово» и не поменяла ровно ничего. Молчаливый успех
# хуже отказа, поэтому ветку двигаем здесь, до ssh.
#
# Двигает её scripts/ship.sh — та же реализация, которой пользуются облачная
# сессия и телефон. Второй перенос рядом с первым это тот же случай, что был с
# .env.prod: выглядят одинаково, расходятся молча, а расхождение здесь значит
# прод, стоящий не на том коммите, который вы только что проверили.
#
# --yes: вопрос про выкатку человек уже ответил самим запуском этого скрипта,
# второй раз спрашивать незачем.
log "Двигаю ветку $DEPLOY_BRANCH"
./scripts/ship.sh --prod-only --yes

# --- .env.prod --------------------------------------------------------------
#
# Файл вне git, поэтому его везёт scp, а не git pull. Здесь можно печатать
# только имена переменных: в значениях лежат пароль базы, секреты Google и
# токены R2, а в истории терминала им делать нечего.
#
# Уезжает он до deploy.sh, а не после: сборка фронта читает оттуда
# VITE_GOOGLE_CLIENT_ID, и новый ключ должен быть на месте раньше сборки.

# Перенос .env.prod живёт в scripts/sync-env.sh — он же возит файл стенда.
# Реализация одна намеренно: две копии одного и того же разъезжаются, а
# расхождение здесь значит затёртый ключ на боевом сервере.
sync_env() {
    if [ "$SKIP_ENV" -eq 1 ]; then
        log "Синхронизация .env.prod пропущена (--skip-env)"
        return
    fi
    DEPLOY_ENV_FILE="$ENV_SOURCE" DEPLOY_SERVER="$SERVER" DEPLOY_DIR="$REMOTE_DIR" \
        ./scripts/sync-env.sh prod
}

sync_env

# --- деплой на сервере ------------------------------------------------------

log "Запускаю деплой на $SERVER"
info "вывод сервера идёт ниже как есть"

# flock — тот же замок, что берёт scripts/prod-autodeploy.sh: опрос из crontab
# может совпасть с выкаткой отсюда, а два `docker compose up` над одним стеком
# это не гонка данных, а погашенный сайт. Ждём, а не отказываемся: чужая
# выкатка идёт минуты, и правильный исход — пойти следом, а не бросить.
if ! ssh "$SERVER" "cd $REMOTE_DIR && flock -w 900 ~/.prod-deploy.lock ./deploy.sh"; then
    fail "деплой на сервере не прошёл — код на сервере мог остаться прежним.
Логи: ssh $SERVER 'cd $REMOTE_DIR && docker compose --env-file .env.prod -f docker-compose.prod.yml -f docker-compose.ssl.yml logs --tail 50 backend nginx'"
fi

# --- проверка сайта ---------------------------------------------------------

SITE_OK=1

if [ "$VERIFY" -eq 1 ]; then
    log "Проверяю $SITE"
    CODE="$(curl -sSI -o /dev/null -w '%{http_code}' --max-time 20 "$SITE" || true)"

    if [ "$CODE" = "200" ]; then
        ok "Сайт отвечает: $CODE"
    else
        SITE_OK=0
        warn "Сайт ответил «${CODE:-нет ответа}» вместо 200."
        info "Логи:   ssh $SERVER 'cd $REMOTE_DIR && docker compose --env-file .env.prod -f docker-compose.prod.yml -f docker-compose.ssl.yml logs --tail 50 backend nginx'"
        info "Статус: ssh $SERVER 'cd $REMOTE_DIR && docker compose --env-file .env.prod -f docker-compose.prod.yml -f docker-compose.ssl.yml ps'"
    fi
else
    log "Проверка сайта пропущена (--no-verify)"
fi

# --- итог -------------------------------------------------------------------

if [ "$SECONDS" -ge 60 ]; then
    ELAPSED="$((SECONDS / 60)) мин $((SECONDS % 60)) с"
else
    ELAPSED="$SECONDS с"
fi

if [ "$SITE_OK" -eq 1 ]; then
    ok "Готово за $ELAPSED"
else
    # деплой прошёл, но сайт не отвечает — зелёным это называть нельзя
    warn "Деплой завершён за $ELAPSED, но сайт не ответил 200"
    exit 1
fi
