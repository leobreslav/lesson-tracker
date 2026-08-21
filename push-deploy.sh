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
# Адрес сервера и домен можно подменить переменными окружения:
# DEPLOY_SERVER, DEPLOY_DIR, DEPLOY_SITE.

set -Eeuo pipefail

SERVER="${DEPLOY_SERVER:-leobreslav@194.67.111.40}"
REMOTE_DIR="${DEPLOY_DIR:-~/lesson-tracker}"
SITE="${DEPLOY_SITE:-https://lbreslav.com/}"
BRANCH="main"

# главный .env.prod: вне папки проекта, чтобы git add -A не мог его подобрать
ENV_SOURCE="${DEPLOY_ENV_FILE:-$HOME/secrets/lesson-tracker.env.prod}"
# сколько прошлых версий держать на сервере
ENV_BACKUPS=3

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
    sed -n '3,17p' "$0" | sed 's/^# \{0,1\}//'
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

# --- .env.prod --------------------------------------------------------------
#
# Файл вне git, поэтому его везёт scp, а не git pull. Здесь можно печатать
# только имена переменных: в значениях лежат пароль базы, секреты Google и
# токены R2, а в истории терминала им делать нечего.
#
# Уезжает он до deploy.sh, а не после: сборка фронта читает оттуда
# VITE_GOOGLE_CLIENT_ID, и новый ключ должен быть на месте раньше сборки.

sha_of() {
    if command -v sha256sum >/dev/null; then
        sha256sum "$1" | cut -d' ' -f1
    else
        shasum -a 256 "$1" | cut -d' ' -f1
    fi
}

# только имена, по одному в строке, отсортированные
NAMES_CMD="grep -oE '^[A-Za-z_][A-Za-z0-9_]*=' .env.prod | tr -d '=' | sort"

env_names() {
    grep -oE '^[A-Za-z_][A-Za-z0-9_]*=' "$1" | tr -d '=' | sort || true
}

# что появилось и что исчезло; значения не сравниваем и не показываем
show_name_changes() {
    local remote_names="$1" added removed
    local remote_file
    remote_file="$(mktemp)"
    printf '%s\n' "$remote_names" | sed '/^$/d' > "$remote_file"

    added="$(comm -23 <(env_names "$ENV_SOURCE") "$remote_file")"
    removed="$(comm -13 <(env_names "$ENV_SOURCE") "$remote_file")"
    rm -f "$remote_file"

    if [ -z "$added" ] && [ -z "$removed" ]; then
        info "набор переменных тот же, различаются значения"
        return
    fi

    [ -z "$added" ]   || printf '    \033[32m+ %s (новая)\033[0m\n' $added
    [ -z "$removed" ] || printf '    \033[33m− %s (исчезла)\033[0m\n' $removed
}

sync_env() {
    local local_sum remote_sum remote_names stamp answer

    if [ "$SKIP_ENV" -eq 1 ]; then
        log "Синхронизация .env.prod пропущена (--skip-env)"
        return
    fi

    log "Проверяю .env.prod на сервере"

    if [ ! -f "$ENV_SOURCE" ]; then
        warn "Нет локального файла $ENV_SOURCE — шаг пропущен."
        info "На сервере останется тот .env.prod, что там уже лежит."
        info "Путь задаётся переменной DEPLOY_ENV_FILE."
        return
    fi

    # один CR вместо перевода строки — и compose прочитает файл как одну
    # переменную, а Django не сойдётся с базой по паролю (см. CLAUDE.md)
    if grep -q $'\r' "$ENV_SOURCE"; then
        fail "в $ENV_SOURCE концы строк CR или CRLF.
compose прочитает такой файл как одну переменную. Лечится:
  tr -d '\\r' < \"$ENV_SOURCE\" > /tmp/env && mv /tmp/env \"$ENV_SOURCE\""
    fi

    local_sum="$(sha_of "$ENV_SOURCE")"
    remote_sum="$(ssh "$SERVER" "cd $REMOTE_DIR && sha256sum .env.prod 2>/dev/null | cut -d' ' -f1" || true)"

    if [ "$local_sum" = "$remote_sum" ]; then
        ok "    .env.prod актуален"
        return
    fi

    if [ -z "$remote_sum" ]; then
        info "на сервере .env.prod ещё нет — будет создан"
    else
        remote_names="$(ssh "$SERVER" "cd $REMOTE_DIR && $NAMES_CMD" || true)"
        show_name_changes "$remote_names"
    fi

    if [ ! -t 0 ]; then
        fail "нужно подтверждение на перезапись .env.prod, а терминала нет.
Запустите вручную или добавьте --skip-env"
    fi

    if [ -z "$remote_sum" ]; then
        printf '    Скопировать .env.prod на сервер? [y/N] '
    else
        printf '    Перезаписать .env.prod на сервере? [y/N] '
    fi
    IFS= read -r answer || fail "ввод прерван"

    case "$answer" in
        y|Y|yes|Yes|д|Д|да|Да) ;;
        *)
            warn "Оставляю .env.prod на сервере как есть."
            return
            ;;
    esac

    if [ -n "$remote_sum" ]; then
        stamp="$(date '+%Y-%m-%d_%H%M%S')"
        # копия делается до перезаписи и до всего остального: если scp
        # оборвётся на середине, откатываться будет к чему
        ssh "$SERVER" "cd $REMOTE_DIR && cp -p .env.prod .env.prod.bak.$stamp &&
            chmod 600 .env.prod.bak.$stamp &&
            ls -1t .env.prod.bak.* | tail -n +$((ENV_BACKUPS + 1)) | xargs -r rm -f"
        info "резервная копия: .env.prod.bak.$stamp (храним последние $ENV_BACKUPS)"
    fi

    scp -q "$ENV_SOURCE" "$SERVER:$REMOTE_DIR/.env.prod"
    ssh "$SERVER" "chmod 600 $REMOTE_DIR/.env.prod"

    remote_sum="$(ssh "$SERVER" "cd $REMOTE_DIR && sha256sum .env.prod | cut -d' ' -f1")"
    [ "$local_sum" = "$remote_sum" ] ||
        fail "файл скопировался, но контрольные суммы не сошлись — проверьте вручную"

    ok "    .env.prod обновлён"
}

sync_env

# --- деплой на сервере ------------------------------------------------------

log "Запускаю деплой на $SERVER"
info "вывод сервера идёт ниже как есть"

if ! ssh "$SERVER" "cd $REMOTE_DIR && ./deploy.sh"; then
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
