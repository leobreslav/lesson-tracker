# Где живут контуры. Единственное место в репозитории, знающее адреса.
#
# Подключается точкой, а не запускается:
#
#   . "$(dirname "$0")/contours.sh"   # или scripts/contours.sh из корня
#   contour prod                      # заполнит SERVER, REMOTE_DIR, SITE,
#                                     # ENV_SOURCE, PROJECT_NAME
#
# **Зачем отдельный файл.** Адреса были умолчаниями в трёх скриптах —
# push-deploy.sh, sync-env.sh, check-secrets.sh, — пятью строками. Пока
# сервер один и не меняется, это незаметно; в день переезда это три правки, и
# забытая четвёртая молча продолжает ходить на старую машину. Обнаружилось бы
# это не сразу и не там, где сломано.
#
# Поэтому переезд теперь стоит одной строки здесь. Переменные окружения
# (DEPLOY_SERVER, STAGING_SERVER и прочие) сохранены: ими удобно ткнуть
# скриптом в чужую машину разово, не трогая файл.

# Заполняет переменные окружения контура. Единственный аргумент — prod или
# staging; неизвестное имя это отказ, а не «наверное, прод».
contour() {
    case "${1:-}" in
        prod)
            CONTOUR="prod"
            SERVER="${DEPLOY_SERVER:-leobreslav@194.67.111.40}"
            REMOTE_DIR="${DEPLOY_DIR:-lesson-tracker}"
            SITE="${DEPLOY_SITE:-https://lbreslav.com/}"
            ENV_SOURCE="${DEPLOY_ENV_FILE:-$HOME/secrets/lesson-tracker.env.prod}"
            PROJECT_NAME="lesson-tracker-prod"
            ;;
        staging)
            CONTOUR="staging"
            SERVER="${STAGING_SERVER:-leobreslav@194.67.119.42}"
            REMOTE_DIR="${STAGING_DIR:-apps/lesson-tracker}"
            SITE="${STAGING_SITE:-https://staging.lbreslav.com/}"
            ENV_SOURCE="${STAGING_ENV_FILE:-$HOME/secrets/lesson-tracker.env.staging}"
            PROJECT_NAME="lesson-tracker-staging"
            ;;
        *)
            printf 'Ошибка: неизвестный контур «%s». Есть prod и staging.\n' \
                "${1:-}" >&2
            return 1
            ;;
    esac
}

# Спрашивает у машины, кем она себя считает, и сверяет с ожидаемым контуром.
#
# Ловит единственную ошибку, от которой список адресов не спасает: **адрес
# устарел, а скрипт нет**. При переезде новый сервер поднимается раньше, чем
# правится этот файл, — и команда, посланная «на прод», приходит на машину,
# которая продом уже не является. Снаружи это выглядит успехом: ssh прошёл,
# скрипт отработал, ответ 200. Не тот сервер об этом не сообщит.
#
# Спрашиваем машину **двумя** способами, и это не перестраховка. Сначала
# `COMPOSE_PROJECT_NAME` из env-файла — но у прода этой строки нет: он живёт
# на умолчании `${COMPOSE_PROJECT_NAME:-lesson-tracker-prod}` из
# compose-файла, и сторож, знающий только про env, на боевой машине молчал бы
# всегда. Ровно та беда, ради которой сторожа и заводили.
#
# Поэтому второй способ — имена запущенных контейнеров: их префикс и есть имя
# проекта, оно там независимо от того, записано что-то в env-файле или взято
# из умолчания.
#
# Молчит при успехе. Пустой ответ обоих способов (машина чистая, стек не
# поднят) — не отказ: первый деплой на новый сервер идёт именно так.
contour_matches_machine() {
    local remote
    remote="$(ssh -o BatchMode=yes -o ConnectTimeout=10 "$SERVER" "
        sed -n 's/^COMPOSE_PROJECT_NAME=//p' $REMOTE_DIR/.env.prod 2>/dev/null | head -1
        docker ps --format '{{.Names}}' 2>/dev/null |
            sed -n 's/-\(backend\|db\|nginx\)-[0-9]\+\$//p'
    " < /dev/null 2>/dev/null | tr -d '\r' | sort -u | sed '/^$/d' || true)"

    [ -z "$remote" ] && return 0
    printf '%s\n' "$remote" | grep -qx "$PROJECT_NAME" && return 0

    printf '\033[31mОшибка: %s называет себя «%s», а ждали контур «%s» (%s).\n' \
        "$SERVER" "$(printf '%s' "$remote" | tr '\n' ' ')" "$CONTOUR" "$PROJECT_NAME" >&2
    printf 'Похоже, адрес контура устарел — поправьте scripts/contours.sh.\033[0m\n' >&2
    return 1
}
